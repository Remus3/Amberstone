"""agents/agent5_ui/champion_fallback.py - s144 true-audit (RM-1966..RM-1973).

The module feeds GET /api/locked-champion (agents/_supervisor_http.py), which
the dashboard champion pill polls every 15 s whenever the Live Client has no
champion (web/js/main.js refreshChampionFallback). Every numbered group below
holds at least one test that was RED against the pre-audit module (measured:
56 of the 70 tests); the other 14 are controls the old code already met -
the well-formed path (a normal newest row, a path with a space, an unknown
id's placeholder, "playing JINX", the no-false-positive texts, the in-TTL
cache hit) so a fix cannot pass by refusing everything, plus degenerate
inputs (a directory DB, no myTeam, LCU not connected, every probe failing):

- 528: the match_db probe returned the newest row of ANY mode, and a TFT row
  stores its comp label in ``champion`` (core/match_db.py; measured on the
  live store 2026-11-06: the newest row was TFT, so the pill read "Flora
  Fatalis 2 / Lunar 3 / Executioner 2").
- 529: the read-only URI was an f-string, so a '#' / '%' in the DB path made
  sqlite open a different file (or none); a BLOB / int champion came back as
  "b'Jinx'" / "42"; a failed query leaked the connection.
- 530: the LCU probe matched a teammate with no cellId when the session had
  no localPlayerCellId (None == None), and one non-dict myTeam entry raised
  out of the probe so current_champion fell through to the LAST game's
  champion while a champion was being picked.
- 531: the id -> name step asked the LCU an inventory path keyed by the FIRST
  teammate's summonerId and, on a miss, shipped "champion#222" to the pill;
  a bool / str / negative championId shipped "champion#True".
- 532: one non-object JSON line (or a non-dict task / payload, a non-str
  user_text) in the queue tail raised and lost the whole user-note probe.
- 533: the note scanner could never match a display name with a space or an
  apostrophe ("Lee Sin", "Kai'Sa"), "Wukong", "Vi", or the four champions the
  hard-coded set lacked (Ambessa, Aurora, Locke, Zaahen).
- 534: the cache TTL ran on the wall clock, so a backwards clock step served
  a stale champion until the wall clock caught up.
- 535: a cache hit read ``_CACHE["source"] + " (cache)"`` and raised
  TypeError when a champion was cached under a non-str source.
"""
from __future__ import annotations

import json
import sqlite3
import types

import pytest

from agents.agent5_ui import champion_fallback as cf


# -- helpers -----------------------------------------------------------------

def _make_db(path, rows):
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp TEXT NOT NULL, mode TEXT NOT NULL, champion TEXT DEFAULT '')"
    )
    conn.executemany(
        "INSERT INTO matches (timestamp, mode, champion) VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(cf, "_CACHE", {"champion": None, "source": None, "ts": 0.0})


class _FakeLcu:
    """Stand-in for lcu.lcu_client.LcuClient: one canned session, every other
    endpoint None, and a record of every request made."""

    session: object = None
    connected = True
    calls: list = []

    def connect(self):
        return self.connected

    def _request(self, method, endpoint, data=None):
        type(self).calls.append((method, endpoint))
        if endpoint == "/lol-champ-select/v1/session":
            return type(self).session
        return None


@pytest.fixture
def fake_lcu(monkeypatch):
    import lcu.lcu_client as real

    class Fake(_FakeLcu):
        session = None
        calls = []

    monkeypatch.setattr(real, "LcuClient", Fake)
    return Fake


# -- 528 / 529: match_db probe -----------------------------------------------

def test_528_match_db_skips_tft_comp_label(tmp_path, monkeypatch):
    db = tmp_path / "match_history.db"
    _make_db(db, [
        ("2026-08-02 17:34:35", "ARAM", "Caitlyn"),
        ("2026-10-25 17:05:11", "TFT", "Flora Fatalis 2 / Lunar 3 / Executioner 2"),
    ])
    monkeypatch.setattr(cf, "_MATCH_DB_PATH", db)
    assert cf._try_match_db_last() == "Caitlyn"


def test_528_match_db_only_tft_rows_is_none(tmp_path, monkeypatch):
    db = tmp_path / "match_history.db"
    _make_db(db, [("2026-10-25 17:05:11", "tft", "Lunar 5 / Flora Fatalis 2")])
    monkeypatch.setattr(cf, "_MATCH_DB_PATH", db)
    assert cf._try_match_db_last() is None


def test_528_match_db_well_formed_newest_row_unchanged(tmp_path, monkeypatch):
    db = tmp_path / "match_history.db"
    _make_db(db, [
        ("2026-08-02 10:33:30", "ARAM", "Lee Sin"),
        ("2026-08-02 17:34:35", "SR", "Nunu & Willump"),
    ])
    monkeypatch.setattr(cf, "_MATCH_DB_PATH", db)
    assert cf._try_match_db_last() == "Nunu & Willump"


@pytest.mark.parametrize("dirname", ["a#b", "a%23b", "a b"])
def test_529_match_db_path_with_uri_metachar_opens_that_db(tmp_path, monkeypatch, dirname):
    d = tmp_path / dirname
    d.mkdir()
    db = d / "match_history.db"
    _make_db(db, [("2026-08-02 17:34:35", "ARAM", "Caitlyn")])
    # A decoy at the path the unquoted URI resolves to for "a%23b" ("a#b").
    if dirname == "a%23b":
        decoy_dir = tmp_path / "a#b"
        decoy_dir.mkdir(exist_ok=True)
        _make_db(decoy_dir / "match_history.db",
                 [("2026-08-02 17:34:35", "ARAM", "Decoy")])
    monkeypatch.setattr(cf, "_MATCH_DB_PATH", db)
    assert cf._try_match_db_last() == "Caitlyn"


def test_529_ro_uri_unc_path_has_no_authority():
    from pathlib import PureWindowsPath
    uri = cf._ro_uri(PureWindowsPath(r"\\srv\share\data\match_history.db"))
    assert uri == "file:////srv/share/data/match_history.db?mode=ro"


def test_529_ro_uri_quotes_and_roots_a_slashless_path():
    # A drive path's as_posix() has no leading "/" either; this is that branch.
    from pathlib import PurePosixPath
    uri = cf._ro_uri(PurePosixPath("x y/a#b/50%/match_history.db"))
    assert uri == "file:///x%20y/a%23b/50%25/match_history.db?mode=ro"


@pytest.mark.parametrize("bad", [b"Jinx", 42, 3.5, "Ji\nnx", "\x00", "   ", "x" * 40])
def test_529_match_db_non_name_champion_skipped(tmp_path, monkeypatch, bad):
    db = tmp_path / "match_history.db"
    _make_db(db, [("2026-08-01 10:00:00", "ARAM", "Caitlyn")])
    conn = sqlite3.connect(str(db))
    conn.execute("INSERT INTO matches (timestamp, mode, champion) VALUES (?, ?, ?)",
                 ("2026-08-02 10:00:00", "ARAM", bad))
    conn.commit()
    conn.close()
    monkeypatch.setattr(cf, "_MATCH_DB_PATH", db)
    assert cf._try_match_db_last() == "Caitlyn"


def test_529_many_newer_blob_rows_do_not_hide_a_real_one(tmp_path, monkeypatch):
    db = tmp_path / "match_history.db"
    _make_db(db, [("2026-08-01 10:00:00", "ARAM", "Caitlyn")])
    conn = sqlite3.connect(str(db))
    conn.executemany(
        "INSERT INTO matches (timestamp, mode, champion) VALUES (?, ?, ?)",
        [(f"2026-08-02 10:00:{i:02d}", "ARAM", b"Jinx") for i in range(30)])
    conn.commit()
    conn.close()
    monkeypatch.setattr(cf, "_MATCH_DB_PATH", db)
    assert cf._try_match_db_last() == "Caitlyn"


def test_529_match_db_strips_whitespace(tmp_path, monkeypatch):
    db = tmp_path / "match_history.db"
    _make_db(db, [("2026-08-02 10:00:00", "ARAM", "  Caitlyn ")])
    monkeypatch.setattr(cf, "_MATCH_DB_PATH", db)
    assert cf._try_match_db_last() == "Caitlyn"


def test_529_match_db_connection_closed_when_query_fails(tmp_path, monkeypatch):
    db = tmp_path / "match_history.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE other (x)")
    conn.commit()
    conn.close()
    opened = []
    real_connect = sqlite3.connect

    class Tracking:
        def __init__(self, inner):
            self.inner = inner
            self.closed = False

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def close(self):
            self.closed = True
            self.inner.close()

    def connect(*a, **kw):
        c = Tracking(real_connect(*a, **kw))
        opened.append(c)
        return c

    monkeypatch.setattr(cf.sqlite3, "connect", connect)
    monkeypatch.setattr(cf, "_MATCH_DB_PATH", db)
    assert cf._try_match_db_last() is None
    assert opened and all(c.closed for c in opened)


def test_529_match_db_directory_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(cf, "_MATCH_DB_PATH", tmp_path)
    assert cf._try_match_db_last() is None


# -- 530 / 531: LCU champ-select probe ----------------------------------------

def test_530_no_local_cell_never_matches_cellless_teammate(fake_lcu):
    fake_lcu.session = {"myTeam": [{"championId": 222}]}
    assert cf._try_lcu_champ_select() is None


def test_530_junk_team_entry_skipped_local_player_found(fake_lcu):
    fake_lcu.session = {
        "localPlayerCellId": 2,
        "myTeam": ["junk", None, 7, {"cellId": 1, "championId": 51},
                   {"cellId": 2, "championId": 222}],
    }
    assert cf._try_lcu_champ_select() == "Jinx"


@pytest.mark.parametrize("team", ["abc", 5, {"cellId": 2}, None])
def test_530_junk_my_team_is_none(fake_lcu, team):
    fake_lcu.session = {"localPlayerCellId": 2, "myTeam": team}
    assert cf._try_lcu_champ_select() is None


@pytest.mark.parametrize("cell,team_cell", [(True, 1), (2.0, 2), ("2", "2")])
def test_530_non_int_local_cell_is_none(fake_lcu, cell, team_cell):
    fake_lcu.session = {"localPlayerCellId": cell,
                        "myTeam": [{"cellId": team_cell, "championId": 222}]}
    assert cf._try_lcu_champ_select() is None


def test_531_id_resolved_from_ddragon_not_first_teammate(fake_lcu):
    fake_lcu.session = {
        "localPlayerCellId": 3,
        "myTeam": [{"cellId": 0, "summonerId": 111, "championId": 51},
                   {"cellId": 3, "summonerId": 999, "championId": 222}],
    }
    assert cf._try_lcu_champ_select() == "Jinx"
    assert [e for _m, e in fake_lcu.calls] == ["/lol-champ-select/v1/session"]


def test_531_pick_intent_used_when_not_locked(fake_lcu):
    fake_lcu.session = {"localPlayerCellId": 0,
                        "myTeam": [{"cellId": 0, "championId": 0,
                                    "championPickIntent": 51}]}
    assert cf._try_lcu_champ_select() == "Caitlyn"


def test_531_unknown_id_keeps_honest_placeholder(fake_lcu):
    fake_lcu.session = {"localPlayerCellId": 0,
                        "myTeam": [{"cellId": 0, "championId": 987654}]}
    assert cf._try_lcu_champ_select() == "champion#987654"


@pytest.mark.parametrize("cid", [True, "222", -5, 1.5, [222]])
def test_531_junk_champion_id_is_none(fake_lcu, cid):
    fake_lcu.session = {"localPlayerCellId": 0,
                        "myTeam": [{"cellId": 0, "championId": cid}]}
    assert cf._try_lcu_champ_select() is None


def test_531_not_connected_is_none(fake_lcu):
    fake_lcu.connected = False
    fake_lcu.session = {"localPlayerCellId": 0,
                        "myTeam": [{"cellId": 0, "championId": 222}]}
    assert cf._try_lcu_champ_select() is None


# -- 532 / 533: user-note probe -----------------------------------------------

def _queue(tmp_path, monkeypatch, lines):
    q = tmp_path / "task_queue.jsonl"
    q.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    monkeypatch.setattr(cf, "_QUEUE_LOG_PATH", q)


@pytest.mark.parametrize("junk", [
    "[1, 2]", '"text"', "null", "7",
    json.dumps({"task": "x"}),
    json.dumps({"task": {"payload": ["a"]}}),
    json.dumps({"task": {"payload": {"user_text": 12}}}),
    json.dumps({"task": {"payload": {"user_text": ["Jinx"]}}}),
])
def test_532_junk_newest_line_does_not_lose_older_note(tmp_path, monkeypatch, junk):
    good = json.dumps({"task": {"payload": {"user_text": "playing Vayne"}}})
    _queue(tmp_path, monkeypatch, [good, junk])
    assert cf._try_recent_user_note() == "Vayne"


def test_532_bom_first_line_read(tmp_path, monkeypatch):
    q = tmp_path / "task_queue.jsonl"
    rec = json.dumps({"task": {"payload": {"user_text": "playing Jinx"}}})
    q.write_bytes(b"\xef\xbb\xbf" + rec.encode("utf-8") + b"\n")
    monkeypatch.setattr(cf, "_QUEUE_LOG_PATH", q)
    assert cf._try_recent_user_note() == "Jinx"


@pytest.mark.parametrize("text,want", [
    ("playing Lee Sin tonight", "LeeSin"),
    ("on Kai'Sa", "Kaisa"),
    ("Miss Fortune bot", "MissFortune"),
    ("Dr. Mundo top", "DrMundo"),
    ("Nunu & Willump jungle", "Nunu"),
    ("going Wukong", "MonkeyKing"),
    ("Vi jungle", "Vi"),
    ("first time Ambessa", "Ambessa"),
    ("Aurora mid", "Aurora"),
    ("playing JINX", "Jinx"),
])
def test_533_display_name_forms_match(tmp_path, monkeypatch, text, want):
    _queue(tmp_path, monkeypatch,
           [json.dumps({"task": {"payload": {"user_text": text}}})])
    assert cf._try_recent_user_note() == want


@pytest.mark.parametrize("text", ["my karma is bad", "no champion here", "I Am"])
def test_533_no_false_positive(tmp_path, monkeypatch, text):
    _queue(tmp_path, monkeypatch,
           [json.dumps({"task": {"payload": {"user_text": text}}})])
    assert cf._try_recent_user_note() is None


def test_533_first_name_in_text_wins(tmp_path, monkeypatch):
    _queue(tmp_path, monkeypatch,
           [json.dumps({"task": {"payload": {"user_text": "Jinx into Lee Sin"}}})])
    assert cf._try_recent_user_note() == "Jinx"


def test_533_every_ddragon_champion_is_known():
    from core import archetype_picks as ap
    raw = json.loads(ap._CHAMPS_PATH.read_text(encoding="utf-8"))
    data = raw.get("data", raw)
    lookup = cf._champion_lookup()
    for entry in data.values():
        assert lookup.get(cf._norm(entry["id"])) == entry["id"]
        assert lookup.get(cf._norm(entry["name"])) == entry["id"]


def test_533_champion_newer_than_static_list_matches_via_ddragon(tmp_path, monkeypatch):
    dd = tmp_path / "ddragon_champions.json"
    dd.write_bytes(b"\xef\xbb\xbf" + json.dumps({"data": {
        "Zzyzx": {"id": "Zzyzx", "name": "Zzy'Zx Prime", "key": "9001"},
        "junk": "x",
    }}).encode("utf-8"))
    monkeypatch.setattr(cf, "_DDRAGON_CHAMPS_PATH", dd)
    monkeypatch.setattr(cf, "_LOOKUP_CACHE", None)
    _queue(tmp_path, monkeypatch,
           [json.dumps({"task": {"payload": {"user_text": "on Zzy'Zx Prime"}}})])
    assert cf._try_recent_user_note() == "Zzyzx"


def test_533_ddragon_lookup_read_once(tmp_path, monkeypatch):
    dd = tmp_path / "ddragon_champions.json"
    dd.write_text(json.dumps({"data": {"Zzyzx": {"id": "Zzyzx", "name": "Zzyzx"}}}),
                  encoding="utf-8")
    monkeypatch.setattr(cf, "_DDRAGON_CHAMPS_PATH", dd)
    monkeypatch.setattr(cf, "_LOOKUP_CACHE", None)
    assert cf._champion_lookup()["zzyzx"] == "Zzyzx"
    dd.unlink()
    assert cf._champion_lookup()["zzyzx"] == "Zzyzx"


@pytest.mark.parametrize("body", [b"not json", b"[1]", b'{"data": 5}'])
def test_533_unreadable_ddragon_keeps_static_floor_uncached(tmp_path, monkeypatch, body):
    dd = tmp_path / "ddragon_champions.json"
    dd.write_bytes(body)
    monkeypatch.setattr(cf, "_DDRAGON_CHAMPS_PATH", dd)
    monkeypatch.setattr(cf, "_LOOKUP_CACHE", None)
    assert cf._champion_lookup()["jinx"] == "Jinx"
    assert cf._LOOKUP_CACHE is None


# -- 534 / 535: cache ---------------------------------------------------------

def _clock(wall, mono):
    return types.SimpleNamespace(time=lambda: wall[0], monotonic=lambda: mono[0])


def test_534_backwards_wall_clock_step_does_not_pin_cache(monkeypatch):
    seq = iter(["Jinx", "Vayne"])
    monkeypatch.setattr(cf, "_try_lcu_champ_select", lambda: next(seq))
    wall, mono = [1_000_000.0], [500.0]
    monkeypatch.setattr(cf, "time", _clock(wall, mono))
    assert cf.current_champion()["champion"] == "Jinx"
    wall[0] -= 3600.0          # NTP / DST step back one hour
    mono[0] += cf.CACHE_TTL_SEC + 1
    out = cf.current_champion()
    assert out["champion"] == "Vayne" and out["source"] == "lcu"


def test_534_cache_served_inside_ttl(monkeypatch):
    seq = iter(["Jinx", "Vayne"])
    monkeypatch.setattr(cf, "_try_lcu_champ_select", lambda: next(seq))
    wall, mono = [1_000_000.0], [500.0]
    monkeypatch.setattr(cf, "time", _clock(wall, mono))
    first = cf.current_champion()
    mono[0] += 1
    wall[0] += 1
    out = cf.current_champion()
    assert out == {"champion": "Jinx", "source": "lcu (cache)",
                   "fetched_at_epoch": first["fetched_at_epoch"]}
    assert cf.current_champion(force_fresh=True)["champion"] == "Vayne"


def test_535_cache_hit_with_junk_source_never_raises(monkeypatch):
    wall, mono = [1_000_000.0], [500.0]
    monkeypatch.setattr(cf, "time", _clock(wall, mono))
    monkeypatch.setattr(cf, "_CACHE", {"champion": "Jinx", "source": None,
                                       "ts": wall[0], "mono": mono[0]})
    out = cf.current_champion()
    assert out["champion"] == "Jinx" and isinstance(out["source"], str)


def test_current_champion_all_probes_fail_is_none(monkeypatch):
    def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(cf, "_try_lcu_champ_select", boom)
    monkeypatch.setattr(cf, "_try_match_db_last", lambda: None)
    monkeypatch.setattr(cf, "_try_recent_user_note", lambda: None)
    out = cf.current_champion(force_fresh=True)
    assert out["champion"] is None and out["source"] == "none"

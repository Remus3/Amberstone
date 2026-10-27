"""
tests/test_routes_lobby_aux_true_audit.py
s144 lane 8 (true-audit) cycle 2: dashboard/routes_lobby_aux.py.

The module serves GET/POST /api/top8 (the pre-game lobby Top 8 list,
persisted to data/top8_list.json) and GET /api/mains (per-champion stats
from rewind_history.db, plus LCU mastery). Each class below pins one
weakness the audit found; every test was RED against the pre-fix module.

Hermetic: the Top 8 file and the rewind DB are redirected into tmp_path,
and the live-state read is monkeypatched, so nothing touches data/ or a
running server. All ids are synthetic.
"""
import json
import math
import sqlite3

import pytest

from dashboard import routes_lobby_aux as rla


class _StubHandler:
    """Captures _send calls (same shape as tests/test_p2w1_dash_c.py)."""

    def __init__(self, path: str = "/"):
        self.path = path
        self.headers = {}
        self.client_address = ("127.0.0.1", 0)
        self.responses: list = []

    def _send(self, code, body, ctype="application/json"):
        self.responses.append((code, body, ctype))

    @property
    def code(self) -> int:
        return self.responses[-1][0]

    def body(self):
        return _strict_loads(self.responses[-1][1])


def _strict_loads(raw: bytes):
    """json.loads that refuses NaN / Infinity, like a browser's JSON.parse."""
    def _refuse(tok):
        raise ValueError(f"non-strict JSON constant {tok}")
    return json.loads(raw, parse_constant=_refuse)


@pytest.fixture
def top8_path(tmp_path, monkeypatch):
    p = tmp_path / "top8_list.json"
    monkeypatch.setattr(rla, "_TOP8_PATH", p)
    return p


def _post(entries):
    h = _StubHandler("/api/top8")
    rla._serve_top8_post(h, {"entries": entries})
    return h


# -- F1: a wrong-typed number escaped the handler (no HTTP response) ------

class TestTop8PostNumericFields:
    """Pre-fix: `int(raw.get("added_ts") or time.time())` and
    `int(rank.get("lp") or 0)` were bare, and `level` / `icon_id` caught
    TypeError / ValueError but not OverflowError. The handler has no
    wrapper and do_POST does not catch a route exception, so the request
    died with no HTTP response at all."""

    @pytest.mark.parametrize("bad", ["abc", [1], {"x": 1}, math.inf,
                                     -math.inf, math.nan])
    def test_bad_added_ts_answers_and_restamps(self, top8_path, bad):
        h = _post([{"riot_id": "Sample#EUW", "added_ts": bad}])
        assert h.code == 200
        e = h.body()["entries"][0]
        assert isinstance(e["added_ts"], int) and e["added_ts"] > 0

    @pytest.mark.parametrize("bad", ["abc", [1], math.inf, math.nan])
    def test_bad_rank_lp_answers_and_zeroes(self, top8_path, bad):
        h = _post([{"riot_id": "Sample#EUW",
                    "rank": {"tier": "gold", "division": "ii", "lp": bad}}])
        assert h.code == 200
        assert h.body()["entries"][0]["rank"] == {
            "tier": "GOLD", "division": "II", "lp": 0}

    @pytest.mark.parametrize("field", ["level", "icon_id"])
    @pytest.mark.parametrize("bad", [math.inf, -math.inf, -5, True])
    def test_bad_level_and_icon_dropped(self, top8_path, field, bad):
        h = _post([{"riot_id": "Sample#EUW", field: bad}])
        assert h.code == 200
        assert field not in h.body()["entries"][0]

    def test_good_numbers_kept(self, top8_path):
        h = _post([{"riot_id": "Sample#EUW", "added_ts": 1778561234,
                    "level": 412, "icon_id": 4567,
                    "rank": {"tier": "DIAMOND", "division": "II", "lp": 67}}])
        e = h.body()["entries"][0]
        assert e["added_ts"] == 1778561234
        assert e["level"] == 412 and e["icon_id"] == 4567
        assert e["rank"]["lp"] == 67

    def test_digit_strings_still_coerce(self, top8_path):
        # The pre-fix int() accepted these; keep accepting them.
        h = _post([{"riot_id": "Sample#EUW", "level": " 12 ",
                    "rank": {"tier": "GOLD", "lp": "30"}}])
        e = h.body()["entries"][0]
        assert e["level"] == 12 and e["rank"]["lp"] == 30

    @pytest.mark.parametrize("bad", ["-5", "1e3", "12.5", chr(0x661) + chr(0x662),
                                     "9" * 5000])
    def test_non_digit_strings_refused(self, top8_path, bad):
        h = _post([{"riot_id": "Sample#EUW", "level": bad}])
        assert h.code == 200
        assert "level" not in h.body()["entries"][0]

    def test_float_seconds_truncate(self, top8_path):
        h = _post([{"riot_id": "Sample#EUW", "added_ts": 1778561234.9}])
        assert h.body()["entries"][0]["added_ts"] == 1778561234


# -- F2: operator-authored fields the client renders were silently dropped --

class TestTop8PostKeepsRenderedFields:
    """Pre-fix: the sanitizer kept only riot_id / summoner_name / note /
    added_ts / rank / level / icon_id / puuid. web/js/main.js renders and
    the operator EDITS `user_tag` (the edit-tag prompt), and the client
    replaces its cache with the POST response - so a tag vanished the
    moment it was saved."""

    def test_user_tag_survives_post_and_get(self, top8_path):
        h = _post([{"riot_id": "Sample#EUW", "user_tag": "  duo  "}])
        assert h.body()["entries"][0]["user_tag"] == "duo"
        g = _StubHandler("/api/top8")
        rla._serve_top8_get(g)
        assert g.body()["entries"][0]["user_tag"] == "duo"

    def test_client_add_shape_round_trips(self, top8_path):
        # The exact object main.js tryAdd() pushes.
        h = _post([{"riot_id": "Sample#EUW", "summoner_name": "Sample",
                    "added_at": 1778561234000, "user_tag": "",
                    "is_online": False, "games_with_me": None,
                    "preferred_role": None, "rank": None}])
        e = h.body()["entries"][0]
        assert e["user_tag"] == ""
        assert e["is_online"] is False
        assert e["games_with_me"] is None
        assert e["preferred_role"] is None
        assert "rank" not in e

    def test_typed_rendered_fields(self, top8_path):
        h = _post([{"riot_id": "Sample#EUW", "games_with_me": 12,
                    "preferred_role": "bottom", "is_online": True,
                    "summoner_level": 300}])
        e = h.body()["entries"][0]
        assert e["games_with_me"] == 12
        assert e["preferred_role"] == "bottom"
        assert e["is_online"] is True
        assert e["summoner_level"] == 300

    def test_wrong_typed_rendered_fields_coerced(self, top8_path):
        h = _post([{"riot_id": "Sample#EUW", "games_with_me": "lots",
                    "preferred_role": {"x": 1}, "is_online": "yes",
                    "summoner_level": math.inf, "user_tag": ["a"]}])
        e = h.body()["entries"][0]
        assert e["games_with_me"] is None
        assert e["preferred_role"] is None
        assert e["is_online"] is False
        assert "summoner_level" not in e
        assert e["user_tag"] == ""

    def test_unknown_fields_still_dropped(self, top8_path):
        h = _post([{"riot_id": "Sample#EUW", "evil": "<script>"}])
        assert "evil" not in h.body()["entries"][0]


# -- F3: string fields were unbounded and non-strings were repr'd ---------

class TestTop8PostStrings:
    """Pre-fix: every string was `str(raw.get(...))` with no type check and
    no cap, so a dict became its Python repr on disk and a 1 MiB note was
    persisted and re-served on every GET."""

    def test_non_string_identity_is_not_repred(self, top8_path):
        h = _post([{"riot_id": {"a": 1}, "summoner_name": "Sample"}])
        e = h.body()["entries"][0]
        assert e["riot_id"] == ""
        assert e["summoner_name"] == "Sample"

    def test_entry_with_only_non_string_identity_dropped(self, top8_path):
        h = _post([{"riot_id": ["x"], "summoner_name": 7}])
        assert h.body()["entries"] == []

    def test_long_strings_capped(self, top8_path):
        big = "x" * 100_000
        h = _post([{"riot_id": big, "summoner_name": big, "note": big,
                    "user_tag": big, "puuid": big,
                    "rank": {"tier": big, "division": big}}])
        e = h.body()["entries"][0]
        assert len(e["riot_id"]) <= rla._MAX_ID_LEN
        assert len(e["summoner_name"]) <= rla._MAX_ID_LEN
        assert len(e["note"]) <= rla._MAX_NOTE_LEN
        assert len(e["user_tag"]) <= rla._MAX_NOTE_LEN
        assert len(e["puuid"]) <= rla._MAX_PUUID_LEN
        assert len(e["rank"]["tier"]) <= rla._MAX_RANK_LEN
        assert len(e["rank"]["division"]) <= rla._MAX_RANK_LEN
        assert top8_path.stat().st_size < 4096


# -- F4: the stored file was served raw, and a bad file wiped the list -----

class TestTop8Load:
    """Pre-fix: _load_top8 returned whatever list the file held. A NaN
    (json.load accepts it) went straight back out as a bare `NaN` token,
    which the browser's r.json() rejects; main.js then sets its cache to []
    and the operator's next add POSTs a one-entry list over the whole file.
    Non-dict junk elements and over-cap lists were served too."""

    def test_nan_in_file_served_as_strict_json(self, top8_path):
        top8_path.write_text(
            '[{"riot_id": "Sample#EUW", "added_ts": NaN, "level": Infinity}]',
            encoding="utf-8")
        g = _StubHandler("/api/top8")
        rla._serve_top8_get(g)
        assert g.code == 200
        e = g.body()["entries"][0]
        assert e["riot_id"] == "Sample#EUW"
        assert "level" not in e

    def test_junk_elements_dropped_and_capped(self, top8_path):
        rows = [None, 7, "x", {"note": "no identity"}]
        rows += [{"riot_id": f"P{i}#EUW", "added_ts": 1} for i in range(12)]
        top8_path.write_text(json.dumps(rows), encoding="utf-8")
        entries = rla._load_top8()
        assert [e["riot_id"] for e in entries] == [f"P{i}#EUW" for i in range(8)]

    def test_deeply_nested_file_answers(self, top8_path):
        top8_path.write_text("[" * 200_000 + "]" * 200_000, encoding="utf-8")
        g = _StubHandler("/api/top8")
        rla._serve_top8_get(g)
        assert g.code == 200
        assert g.body()["entries"] == []

    def test_missing_and_corrupt_file_empty(self, top8_path):
        assert rla._load_top8() == []
        top8_path.write_bytes(b"\xff\xfe not json")
        assert rla._load_top8() == []
        top8_path.write_text('{"entries": []}', encoding="utf-8")
        assert rla._load_top8() == []


# -- rewind DB fixture for the /api/mains half ----------------------------

_COLS = ("match_id", "team_id", "puuid", "champion_id", "champion_name",
         "win", "kills", "deaths", "assists", "total_minions_killed",
         "neutral_minions_killed", "vision_score",
         "total_damage_dealt_to_champs", "time_played")


def _db(path=":memory:", with_champion_id=True):
    c = sqlite3.connect(str(path))
    cols = [n for n in _COLS if with_champion_id or n != "champion_id"]
    ddl = ", ".join(f"{n} TEXT" if n in ("match_id", "puuid", "champion_name")
                    else f"{n} INTEGER" for n in cols)
    c.execute(f"CREATE TABLE participants ({ddl})")
    c.execute("CREATE TABLE matches (match_id TEXT, game_creation_ts INTEGER)")
    return c


def _ins(c, **row):
    have = [r[1] for r in c.execute("PRAGMA table_info(participants)")]
    full = {n: 0 for n in have if n != "match_id"}
    full["match_id"] = "m0"
    full.update({k: v for k, v in row.items() if k in have})
    c.execute(f"INSERT INTO participants ({', '.join(full)}) VALUES "
              f"({', '.join('?' for _ in full)})", tuple(full.values()))


# -- F5: cs_per_min divided by a floored 1 minute when time was missing ---

class TestCsPerMin:
    """Pre-fix: `played_min = max(1, played_s / 60)`, so a champ whose rows
    carry no time_played reported its TOTAL CS across every game as a
    per-minute rate, and a mix of timed and untimed rows put untimed CS
    over timed minutes."""

    def test_untimed_rows_give_none_not_total_cs(self):
        c = _db()
        for i in range(3):
            _ins(c, match_id=f"m{i}", puuid="P", champion_name="Jinx",
                 total_minions_killed=200, time_played=None)
        av = rla._query_mains_for_puuid(c, "P", 8)[0]["averaged"]
        assert av["cs_per_min"] is None
        assert av["cs"] == 200

    def test_mixed_rows_use_timed_cs_over_timed_minutes(self):
        c = _db()
        _ins(c, match_id="m1", puuid="P", champion_name="Jinx",
             total_minions_killed=300, time_played=1800)   # 10.0 / min
        _ins(c, match_id="m2", puuid="P", champion_name="Jinx",
             total_minions_killed=900, time_played=None)   # untimed
        av = rla._query_mains_for_puuid(c, "P", 8)[0]["averaged"]
        assert av["cs_per_min"] == 10.0
        assert av["cs"] == 600

    def test_negative_time_played_is_untimed(self):
        c = _db()
        _ins(c, match_id="m1", puuid="P", champion_name="Jinx",
             total_minions_killed=300, time_played=1800)
        _ins(c, match_id="m2", puuid="P", champion_name="Jinx",
             total_minions_killed=300, time_played=-600)
        av = rla._query_mains_for_puuid(c, "P", 8)[0]["averaged"]
        assert av["cs_per_min"] == 10.0

    def test_timed_rows_unchanged(self):
        c = _db()
        _ins(c, match_id="m1", puuid="P", champion_name="Jinx",
             total_minions_killed=200, time_played=1800)
        _ins(c, match_id="m2", puuid="P", champion_name="Jinx",
             total_minions_killed=150, time_played=1500)
        av = rla._query_mains_for_puuid(c, "P", 8)[0]["averaged"]
        assert av["cs_per_min"] == round(350 / 55, 1)


# -- F6: ties were ordered by the query plan, not by a rule ---------------

class TestDeterministicOrder:
    """Pre-fix: `ORDER BY games DESC` with LIMIT and no tiebreak let SQLite
    pick which tied champs made the cut (measured: Zed and Mid ahead of Ahri
    and Bard), and the last-5 query had no tiebreak for equal timestamps."""

    def test_tied_champs_break_by_name(self):
        c = _db()
        for ch in ("Zed", "Ahri", "Mid", "Bard"):
            for i in range(2):
                _ins(c, match_id=f"{ch}{i}", puuid="P", champion_name=ch)
        rows = rla._query_mains_for_puuid(c, "P", 2)
        assert [r["name"] for r in rows] == ["Ahri", "Bard"]

    def test_equal_timestamp_last_match_breaks_by_match_id(self):
        c = _db()
        _ins(c, match_id="m2", puuid="P", champion_name="Jinx", win=1,
             kills=9)
        _ins(c, match_id="m1", puuid="P", champion_name="Jinx", win=0,
             kills=1)
        _ins(c, match_id="m3", puuid="P", champion_name="Jinx", win=0,
             kills=3)
        for m in ("m1", "m2", "m3"):
            c.execute("INSERT INTO matches VALUES (?, 5000)", (m,))
        lm = rla._query_mains_for_puuid(c, "P", 8)[0]["last_match"]
        assert lm["kda"].startswith("3/")


# -- F7: mastery overlay looked up by NAME in a map keyed by champion ID --

class TestMasteryOverlay:
    """Pre-fix: lcu/snapshot_shape._maybe_refresh_mastery keys the map by
    integer championId (a JSON string key once it crosses /api/state),
    while _mastery_overlay looked it up by champion NAME, so
    mastery_level / mastery_points were never filled."""

    def test_rows_carry_champion_id(self):
        c = _db()
        _ins(c, match_id="m1", puuid="P", champion_id=67,
             champion_name="Vayne")
        rows = rla._query_mains_for_puuid(c, "P", 8)
        assert rows[0]["champion_id"] == 67

    def test_db_without_champion_id_column_still_serves(self):
        c = _db(with_champion_id=False)
        _ins(c, match_id="m1", puuid="P", champion_name="Vayne")
        rows = rla._query_mains_for_puuid(c, "P", 8)
        assert rows[0]["name"] == "Vayne"
        assert rows[0].get("champion_id") is None

    @pytest.mark.parametrize("key", ["67", 67])
    def test_overlay_matches_by_champion_id(self, key):
        rows = [{"name": "Vayne", "champion_id": 67}]
        out = rla._mastery_overlay(rows, {key: {"level": 7, "points": 487213}})
        assert out[0]["mastery_level"] == 7
        assert out[0]["mastery_points"] == 487213

    def test_overlay_legacy_name_key_still_matches(self):
        rows = [{"name": "Vayne", "champion_id": None}]
        out = rla._mastery_overlay(rows, {"Vayne": {"level": 5, "points": 9}})
        assert out[0]["mastery_level"] == 5

    def test_overlay_non_numeric_values_become_none(self):
        rows = [{"name": "Vayne", "champion_id": 67}]
        out = rla._mastery_overlay(
            rows, {"67": {"level": "seven", "points": math.inf}})
        assert out[0]["mastery_level"] is None
        assert out[0]["mastery_points"] is None

    def test_mains_route_end_to_end_fills_mastery(self, tmp_path, monkeypatch):
        db = tmp_path / "rh.db"
        c = _db(db)
        _ins(c, match_id="m1", puuid="P", champion_id=67,
             champion_name="Vayne")
        c.commit()
        c.close()
        monkeypatch.setattr(rla, "_REWIND_DB", db)
        monkeypatch.setattr(rla, "_read_live_mastery",
                            lambda: {"67": {"level": 7, "points": 100}})
        h = _StubHandler("/api/mains")
        rla._serve_mains_get(h)
        assert h.code == 200
        assert h.body()["main_champs"][0]["mastery_level"] == 7


class TestLiveMasteryRead:
    """Pre-fix: _read_live_mastery made a self-HTTPS request to a
    hard-coded :8888 through urllib's default opener (which honours a
    process proxy), from inside a request handler, to read a key it can
    take in-process from the same LCU snapshot /api/state serves."""

    def test_reads_in_process_snapshot(self, monkeypatch):
        import dashboard._state_builder as sb
        monkeypatch.setattr(sb, "_read_lcu_snapshot",
                            lambda: {"mastery": {"67": {"level": 7}}})
        import urllib.request as ur

        def _no_http(*a, **k):
            raise AssertionError("self-HTTP request made")
        monkeypatch.setattr(ur, "urlopen", _no_http)
        monkeypatch.setattr(ur.OpenerDirector, "open", _no_http)
        assert rla._read_live_mastery() == {"67": {"level": 7}}

    @pytest.mark.parametrize("snap", [None, [], [1], "snapshot",
                                      {"mastery": [1, 2]},
                                      {"mastery": None}])
    def test_wrong_shapes_give_empty(self, monkeypatch, snap):
        import dashboard._state_builder as sb
        monkeypatch.setattr(sb, "_read_lcu_snapshot", lambda: snap)
        assert rla._read_live_mastery() == {}

    def test_snapshot_fault_gives_empty(self, monkeypatch):
        import dashboard._state_builder as sb

        def _boom():
            raise OSError("relay down")
        monkeypatch.setattr(sb, "_read_lcu_snapshot", _boom)
        assert rla._read_live_mastery() == {}


# -- F8: the rewind DB URI was built from the raw path --------------------

class TestRewindUri:
    """Pre-fix: `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`. SQLite
    parses that as a URI, so a `#` (fragment) or `%` (escape) in the checkout
    path opened the wrong file and the panel went silently empty."""

    @pytest.mark.parametrize("dirname", ["a#b", "a%20b", "a b"])
    def test_special_char_paths_open(self, tmp_path, monkeypatch, dirname):
        d = tmp_path / dirname
        d.mkdir()
        db = d / "rh.db"
        c = _db(db)
        _ins(c, match_id="m1", puuid="P", champion_name="Vayne")
        c.commit()
        c.close()
        monkeypatch.setattr(rla, "_REWIND_DB", db)
        rows = rla._operator_mains("P")
        assert [r["name"] for r in rows] == ["Vayne"]

    def test_connection_is_read_only(self, tmp_path, monkeypatch):
        db = tmp_path / "rh.db"
        c = _db(db)
        c.commit()
        c.close()
        monkeypatch.setattr(rla, "_REWIND_DB", db)
        conn = rla._connect_rewind_ro()
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("CREATE TABLE x (y)")
        finally:
            conn.close()


# -- F9: the puuid query parameter was unbounded -------------------------

class TestMainsPuuidParam:
    """Pre-fix: any length of `puuid` went into two SQL queries and was
    echoed back in the body. A Riot puuid is 78 characters."""

    def test_oversized_puuid_refused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rla, "_REWIND_DB", tmp_path / "absent.db")
        h = _StubHandler("/api/mains?puuid=" + "a" * 5000)
        rla._serve_mains_get(h)
        assert h.code == 400
        assert "a" * 200 not in h.responses[-1][1].decode()

    def test_normal_puuid_accepted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rla, "_REWIND_DB", tmp_path / "absent.db")
        h = _StubHandler("/api/mains?puuid=" + "a" * 78)
        rla._serve_mains_get(h)
        assert h.code == 200
        assert h.body()["main_champs"] == []

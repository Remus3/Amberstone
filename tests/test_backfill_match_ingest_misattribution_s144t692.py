"""S144-T-692 - tools/backfill_match_ingest_misattribution.py true-audit pins.

The item-211 backfill moves ``lcu_match_detail`` blobs between rows of the LIVE
``data/match_history.db`` (WAL, written by RC's ingest route and
performance_tracker while the tool runs). Each test below is one finding of the
s144 true-audit, red against the pre-audit file:

- the "atomic backup" was ``shutil.copy2`` of the ``.db`` alone, so committed
  rows still in ``-wal`` were missing from it, and it wrote the final name
  directly (a crash left a torn file under the real backup name);
- the plan was read with no write lock and applied from that stale snapshot, so
  a concurrent ingest between scan and apply was silently overwritten;
- an empty / missing ``tracked_puuid`` matched any participant with no puuid
  and MOVED the detail on the strength of a stranger's champion;
- one junk row (a non-object detail, a non-numeric gameId, a JSON-list
  raw_data, a non-string puuid, a pre-1970 timestamp) raised and aborted the run;
- a MATCH row's non-zero game_id was overwritten by a different detail gameId,
  a move target with a different non-zero game_id was still chosen, and a move
  zeroed the source row's own unrelated game_id;
- an undecodable raw_data row could be chosen as a move target;
- a negative ``--window`` was accepted.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "backfill_match_ingest_misattribution.py"

ME = "puuid-me-0001"
CHAMPS = {"222": "Jinx", "51": "Caitlyn", "1": "Annie", "103": "Ahri"}


def _load(monkeypatch):
    name = "_bf211_under_test"
    spec = importlib.util.spec_from_file_location(name, TOOL)
    mod = importlib.util.module_from_spec(spec)
    # dataclasses resolve the defining module through sys.modules.
    monkeypatch.setitem(sys.modules, name, mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    m = _load(monkeypatch)
    dd = tmp_path / "data" / "meta_build" / "ddragon" / "15.1.1"
    dd.mkdir(parents=True)
    data = {n: {"key": k, "name": n} for k, n in CHAMPS.items()}
    (dd / "champion.json").write_text(json.dumps({"data": data}), encoding="utf-8")
    monkeypatch.setattr(m, "_ROOT", tmp_path)
    return m


def _ts_unix(ts):
    import datetime as dt
    return int(dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp())


def _detail(champ_id, end_ts, gid=5000000001, puuid=ME, duration=1800):
    creation_ms = (_ts_unix(end_ts) - duration) * 1000
    return {
        "gameId": gid, "gameCreation": creation_ms, "gameDuration": duration,
        "participantIdentities": [
            {"participantId": 1, "player": {"puuid": "someone-else"}},
            {"participantId": 2, "player": {"puuid": puuid}},
        ],
        "participants": [
            {"participantId": 1, "championId": 1},
            {"participantId": 2, "championId": champ_id},
        ],
    }


def _make_db(path, rows, wal=True):
    """rows: (id, timestamp, mode, champion, game_id, raw_data-or-obj)."""
    conn = sqlite3.connect(path)
    if wal:
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(
        "CREATE TABLE matches (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, "
        "mode TEXT NOT NULL, champion TEXT DEFAULT '', game_id INTEGER DEFAULT 0, "
        "raw_data TEXT DEFAULT '')")
    for rid, ts, mode, champ, gid, raw in rows:
        blob = raw if isinstance(raw, str) else json.dumps(raw)
        conn.execute("INSERT INTO matches VALUES (?,?,?,?,?,?)",
                     (rid, ts, mode, champ, gid, blob))
    conn.commit()
    return conn


def _rows(path):
    conn = sqlite3.connect(path)
    conn.text_factory = lambda raw: raw.decode("utf-8", "replace")
    try:
        return {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
            "SELECT id, champion, game_id, raw_data FROM matches")}
    finally:
        conn.close()


def _run(mod, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["backfill", *argv])
    return mod.main()


def _misattributed(tmp_path):
    """Row 1 (Jinx, earlier) carries Caitlyn's detail; row 2 is that Caitlyn game."""
    db = tmp_path / "match_history.db"
    cait_end = "2026-05-27 23:57:12"
    rows = [
        (1, "2026-05-27 22:54:03", "ARAM", "Jinx", 0,
         {"lcu_match_detail": _detail(51, cait_end), "tracked_puuid": ME,
          "lcu_ingested_at": "x"}),
        (2, "2026-05-27 23:57:40", "ARAM", "Caitlyn", 0, {"k": 1}),
        (3, "2026-05-27 21:00:00", "ARAM", "Ahri", 0,
         {"lcu_match_detail": _detail(103, "2026-05-27 21:00:00", gid=5000000003),
          "tracked_puuid": ME}),
    ]
    _make_db(db, rows).close()
    return db


# -- characterization ---------------------------------------------------------

def test_mismatch_moves_detail_and_match_stamps_game_id(mod, tmp_path, monkeypatch):
    db = _misattributed(tmp_path)
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    rows = _rows(db)
    src = json.loads(rows[1][2])
    dst = json.loads(rows[2][2])
    assert "lcu_match_detail" not in src and "tracked_puuid" not in src
    assert src["item211_backfill_moved_to"] == 2
    assert dst["lcu_match_detail"]["gameId"] == 5000000001
    assert dst["tracked_puuid"] == ME and dst["lcu_ingested_at"] == "x"
    assert dst["item211_backfill_received_from"] == 1 and dst["k"] == 1
    assert rows[2][1] == 5000000001
    assert rows[3][1] == 5000000003  # MATCH row stamped


def test_dry_run_mutates_nothing_and_takes_no_backup(mod, tmp_path, monkeypatch):
    db = _misattributed(tmp_path)
    before = _rows(db)
    assert _run(mod, monkeypatch, "--db", str(db), "--dry-run") == 0
    assert _rows(db) == before
    assert not list(tmp_path.glob("*.bak-item211-*"))


def test_tft_rows_are_ignored(mod, tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    _make_db(db, [(1, "2026-05-27 22:54:03", "TFT", "Jinx", 0,
                   {"lcu_match_detail": _detail(51, "2026-05-27 22:54:03"),
                    "tracked_puuid": ME})]).close()
    before = _rows(db)
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    assert _rows(db) == before


# -- backup -------------------------------------------------------------------

def test_backup_contains_rows_still_in_the_wal(mod, tmp_path, monkeypatch):
    db = tmp_path / "match_history.db"
    writer = _make_db(db, [], wal=True)
    try:
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        writer.execute("INSERT INTO matches VALUES (9, '2026-05-27 20:00:00', 'SR', "
                       "'Annie', 0, '{}')")
        writer.commit()
        assert (tmp_path / "match_history.db-wal").stat().st_size > 0
        assert _run(mod, monkeypatch, "--db", str(db)) == 0
    finally:
        writer.close()
    backups = list(tmp_path.glob("match_history.db.bak-item211-*"))
    assert len(backups) == 1, backups
    alone = tmp_path / "alone"
    alone.mkdir()
    copy = alone / "b.db"
    copy.write_bytes(backups[0].read_bytes())  # the backup file alone, no sidecars
    conn = sqlite3.connect(copy)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT id FROM matches").fetchall() == [(9,)]
    finally:
        conn.close()
    assert not [p for p in tmp_path.iterdir() if ".tmp" in p.name]


def test_backup_never_overwrites_an_existing_backup(mod, tmp_path):
    db = tmp_path / "match_history.db"
    _make_db(db, []).close()
    taken = tmp_path / "match_history.db.bak-item211-20260101-000000"
    taken.write_bytes(b"earlier backup")
    out = mod._backup_db(db, "20260101-000000")
    assert out != taken and out.is_file()
    assert taken.read_bytes() == b"earlier backup"


# -- concurrency --------------------------------------------------------------

def test_concurrent_write_between_scan_and_apply_is_not_lost(mod, tmp_path, monkeypatch):
    db = _misattributed(tmp_path)
    real_connect = sqlite3.connect
    outcome = {}

    def _connect(*a, **kw):
        conn = real_connect(*a, **kw)

        def _trace(sql):
            # The first statement AFTER the scan SELECT is the window between
            # reading the plan and applying it.
            if "SELECT" in sql and "FROM matches" in sql:
                outcome.setdefault("scanned", True)
                return
            if outcome.get("scanned") and "w" not in outcome:
                other = real_connect(str(db), timeout=0)
                try:
                    other.execute("UPDATE matches SET raw_data = ? WHERE id = 1",
                                  (json.dumps({"concurrent": True}),))
                    other.commit()
                    outcome["w"] = "written"
                except sqlite3.OperationalError:
                    outcome["w"] = "refused"
                finally:
                    other.close()
        conn.set_trace_callback(_trace)
        return conn

    monkeypatch.setattr(mod.sqlite3, "connect", _connect)
    _run(mod, monkeypatch, "--db", str(db), "--no-backup")
    assert outcome.get("w") in ("written", "refused")
    if outcome["w"] == "written":
        assert json.loads(_rows(db)[1][2]).get("concurrent") is True, (
            "a write landed between scan and apply and the tool clobbered it")


# -- correctness on wrong input ----------------------------------------------

@pytest.mark.parametrize("tracked", ["", None, "   "])
def test_empty_tracked_puuid_never_matches_an_anonymous_participant(
        mod, tmp_path, monkeypatch, tracked):
    db = tmp_path / "m.db"
    detail = _detail(51, "2026-05-27 23:57:12", puuid="")
    detail["participantIdentities"][1]["player"] = {}  # no puuid at all
    raw = {"lcu_match_detail": detail}
    if tracked is not None:
        raw["tracked_puuid"] = tracked
    _make_db(db, [
        (1, "2026-05-27 22:54:03", "SR", "Jinx", 0, raw),
        (2, "2026-05-27 23:57:40", "SR", "Caitlyn", 0, {}),
    ]).close()
    before = _rows(db)
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    assert _rows(db) == before


@pytest.mark.parametrize("junk_raw", [
    {"lcu_match_detail": ["not", "an", "object"], "tracked_puuid": ME},
    {"lcu_match_detail": "a string", "tracked_puuid": ME},
    {"lcu_match_detail": {"gameId": "abc", "participantIdentities": []},
     "tracked_puuid": ME},
    {"lcu_match_detail": {"gameId": 1, "participantIdentities": "x"},
     "tracked_puuid": ME},
    {"lcu_match_detail": {"gameId": 1, "participantIdentities": [None, 3]},
     "tracked_puuid": ME},
    {"lcu_match_detail": _detail(222, "2026-05-27 20:00:00"), "tracked_puuid": 7},
    {"lcu_match_detail": {**_detail(51, "2026-05-27 20:00:00"), "participants": None},
     "tracked_puuid": ME},
    ["raw", "is", "a", "list"],
    "{not json",
])
def test_one_junk_row_does_not_abort_the_run(mod, tmp_path, monkeypatch, junk_raw):
    db = _misattributed(tmp_path)
    conn = sqlite3.connect(db)
    raw = junk_raw if isinstance(junk_raw, str) else json.dumps(junk_raw)
    conn.execute("INSERT INTO matches VALUES (4, '2026-05-27 20:00:00', 'SR', "
                 "'Annie', 0, ?)", (raw,))
    conn.commit()
    conn.close()
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    rows = _rows(db)
    assert rows[4][2] == raw  # junk row untouched
    assert json.loads(rows[2][2])["item211_backfill_received_from"] == 1


def test_pre_epoch_timestamp_row_does_not_abort_the_run(mod, tmp_path, monkeypatch):
    db = _misattributed(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO matches VALUES (5, '0001-01-01 00:00:00', 'SR', "
                 "'Caitlyn', 0, '{}')")
    conn.commit()
    conn.close()
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    assert json.loads(_rows(db)[2][2])["item211_backfill_received_from"] == 1


def test_match_row_with_a_different_game_id_is_not_overwritten(mod, tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    _make_db(db, [(1, "2026-05-27 22:54:03", "SR", "Jinx", 4242,
                   {"lcu_match_detail": _detail(222, "2026-05-27 22:54:03",
                                                gid=5000000009),
                    "tracked_puuid": ME})]).close()
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    assert _rows(db)[1][1] == 4242


def test_match_stamp_never_duplicates_a_game_id_held_by_another_row(
        mod, tmp_path, monkeypatch):
    db = tmp_path / "m.db"
    _make_db(db, [
        (1, "2026-05-27 22:54:03", "SR", "Jinx", 0,
         {"lcu_match_detail": _detail(222, "2026-05-27 22:54:03", gid=777),
          "tracked_puuid": ME}),
        (2, "2026-05-27 20:00:00", "SR", "Annie", 777, {}),
    ]).close()
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    assert _rows(db)[1][1] == 0


def test_move_target_with_a_different_game_id_is_not_chosen(mod, tmp_path, monkeypatch):
    db = _misattributed(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE matches SET game_id = 31337 WHERE id = 2")
    conn.commit()
    conn.close()
    before = _rows(db)
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    after = _rows(db)
    assert after[1] == before[1] and after[2] == before[2]


def test_move_keeps_the_source_rows_own_game_id(mod, tmp_path, monkeypatch):
    db = _misattributed(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE matches SET game_id = 4242 WHERE id = 1")
    conn.commit()
    conn.close()
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    rows = _rows(db)
    assert json.loads(rows[2][2])["item211_backfill_received_from"] == 1
    assert rows[1][1] == 4242


def test_move_clears_a_source_game_id_that_came_from_the_moved_detail(
        mod, tmp_path, monkeypatch):
    db = _misattributed(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE matches SET game_id = 5000000001 WHERE id = 1")
    conn.commit()
    conn.close()
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    rows = _rows(db)
    assert rows[1][1] == 0 and rows[2][1] == 5000000001


def test_undecodable_row_is_never_a_move_target(mod, tmp_path, monkeypatch):
    db = _misattributed(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE matches SET raw_data = '{broken' WHERE id = 2")
    conn.commit()
    conn.close()
    before = _rows(db)
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    after = _rows(db)
    assert after[1] == before[1] and after[2] == before[2]


def test_negative_window_is_rejected(mod, tmp_path, monkeypatch):
    db = _misattributed(tmp_path)
    with pytest.raises(SystemExit) as exc:
        _run(mod, monkeypatch, "--db", str(db), "--dry-run", "--window", "-5")
    assert exc.value.code == 2


def test_junk_ddragon_entry_is_skipped(mod, tmp_path):
    cj = tmp_path / "data" / "meta_build" / "ddragon" / "15.1.1" / "champion.json"
    data = json.loads(cj.read_text(encoding="utf-8"))
    data["data"]["Bad"] = {"key": "abc", "name": "Bad"}
    data["data"]["Worse"] = ["x"]
    cj.write_text(json.dumps(data), encoding="utf-8")
    out = mod._load_champion_map()
    assert out[51] == "Caitlyn" and len(out) == len(CHAMPS)


@pytest.mark.parametrize("tracked", ["", "   ", None, 7])
def test_row_lcu_owner_never_resolves_an_empty_puuid(mod, tracked):
    detail = _detail(51, "2026-05-27 23:57:12")
    detail["participantIdentities"][1]["player"] = {"puuid": ""}
    assert mod._row_lcu_owner(detail, tracked) is None
    assert mod._row_lcu_owner(_detail(51, "2026-05-27 23:57:12"), ME) == 51


def test_row_lcu_owner_refuses_a_puuid_matched_twice(mod):
    detail = _detail(51, "2026-05-27 23:57:12")
    detail["participantIdentities"][0]["player"] = {"puuid": ME}
    assert mod._row_lcu_owner(detail, ME) is None


def test_plan_reports_a_missing_tracked_puuid(mod):
    rows = [(1, "2026-05-27 22:54:03", "SR", "Jinx", 0,
             json.dumps({"lcu_match_detail": _detail(51, "2026-05-27 23:57:12"),
                         "tracked_puuid": "  "}))]
    plan, _decoded = mod.build_plan(rows, {51: "Caitlyn", 222: "Jinx"}, 180)
    assert plan.unresolved == [(1, "tracked_puuid missing")] and not plan.move


def test_tied_move_targets_are_ambiguous_and_skipped(mod, tmp_path, monkeypatch):
    db = _misattributed(tmp_path)
    conn = sqlite3.connect(db)
    # Caitlyn game ended 23:57:12; rows 2 (+28 s) and 6 (-28 s) tie.
    conn.execute("INSERT INTO matches VALUES (6, '2026-05-27 23:56:44', 'ARAM', "
                 "'Caitlyn', 0, '{}')")
    conn.commit()
    conn.close()
    before = _rows(db)
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    after = _rows(db)
    assert all(after[i] == before[i] for i in (1, 2, 6))


@pytest.mark.parametrize("junk_gid", [-5, "", "abc"])
def test_junk_game_id_column_is_a_conflict_not_an_abort(
        mod, tmp_path, monkeypatch, junk_gid):
    db = _misattributed(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE matches SET game_id = ? WHERE id = 3", (junk_gid,))
    conn.commit()
    conn.close()
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    rows = _rows(db)
    assert rows[3][1] == junk_gid  # left as-is
    assert rows[2][1] == 5000000001  # the valid move still landed


def test_junk_game_id_row_is_never_a_move_target(mod, tmp_path, monkeypatch):
    db = _misattributed(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE matches SET game_id = 'abc' WHERE id = 2")
    conn.commit()
    conn.close()
    before = _rows(db)
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    after = _rows(db)
    assert after[1] == before[1] and after[2] == before[2]


def test_dry_run_opens_the_db_read_only(mod, tmp_path, monkeypatch):
    db = _misattributed(tmp_path)
    real_connect = sqlite3.connect
    seen = []

    def _connect(target, *a, **kw):
        seen.append((str(target), kw.get("uri")))
        return real_connect(target, *a, **kw)

    monkeypatch.setattr(mod.sqlite3, "connect", _connect)
    assert _run(mod, monkeypatch, "--db", str(db), "--dry-run") == 0
    assert seen and all(t.endswith("?mode=ro") and uri for t, uri in seen)


def test_a_failure_mid_apply_rolls_the_whole_batch_back(mod, tmp_path, monkeypatch):
    db = _misattributed(tmp_path)
    before = _rows(db)
    real = mod._update_one
    calls = []

    def _flaky(conn, sql, params):
        calls.append(sql)
        if len(calls) == 2:
            raise RuntimeError("injected")
        return real(conn, sql, params)

    monkeypatch.setattr(mod, "_update_one", _flaky)
    with pytest.raises(RuntimeError, match="injected"):
        _run(mod, monkeypatch, "--db", str(db), "--no-backup")
    assert _rows(db) == before


def test_failed_backup_leaves_no_temp_and_no_backup(mod, tmp_path, monkeypatch):
    db = tmp_path / "match_history.db"
    _make_db(db, []).close()

    def _boom(*_a, **_k):
        raise OSError("injected")

    monkeypatch.setattr(mod.os, "replace", _boom)
    with pytest.raises(OSError, match="injected"):
        mod._backup_db(db, "20260101-000000")
    assert not [p for p in tmp_path.iterdir() if ".bak-item211-" in p.name]


@pytest.mark.parametrize("huge", [10 ** 20, "9999999999999999999", 1e300])
def test_game_id_beyond_sqlite_int64_is_junk_not_an_overflow(
        mod, tmp_path, monkeypatch, huge):
    db = _misattributed(tmp_path)
    conn = sqlite3.connect(db)
    raw = json.loads(conn.execute("SELECT raw_data FROM matches WHERE id = 3"
                                  ).fetchone()[0])
    raw["lcu_match_detail"]["gameId"] = huge
    conn.execute("UPDATE matches SET raw_data = ? WHERE id = 3", (json.dumps(raw),))
    conn.commit()
    conn.close()
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    rows = _rows(db)
    assert rows[3][1] == 0  # unknown gameId: nothing stamped
    assert rows[2][1] == 5000000001  # the valid move still landed


def test_absurdly_deep_raw_data_is_skipped_not_a_recursion_abort(mod, tmp_path, monkeypatch):
    db = _misattributed(tmp_path)
    conn = sqlite3.connect(db)
    deep = '{"lcu_match_detail": ' + "[" * 200000 + "]" * 200000 + "}"
    conn.execute("INSERT INTO matches VALUES (7, '2026-05-27 20:00:00', 'SR', "
                 "'Annie', 0, ?)", (deep,))
    conn.commit()
    conn.close()
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    rows = _rows(db)
    assert rows[7][2] == deep
    assert json.loads(rows[2][2])["item211_backfill_received_from"] == 1


@pytest.mark.parametrize("row_id", [1, 2])
def test_lone_surrogate_escape_on_a_moved_row_does_not_abort(
        mod, tmp_path, monkeypatch, row_id):
    db = _misattributed(tmp_path)
    conn = sqlite3.connect(db)
    raw = json.loads(conn.execute("SELECT raw_data FROM matches WHERE id = ?",
                                  (row_id,)).fetchone()[0])
    raw["note"] = "\ud800"
    conn.execute("UPDATE matches SET raw_data = ? WHERE id = ?",
                 (json.dumps(raw), row_id))
    conn.commit()
    conn.close()
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    rows = _rows(db)
    assert json.loads(rows[row_id][2])["note"] == "\ud800"
    assert json.loads(rows[2][2])["item211_backfill_received_from"] == 1


# "0" / " 0" are not here: INTEGER affinity stores them as int 0.
@pytest.mark.parametrize("text_gid", ["\x1c0", "0\x1c", 5.5, b"\x00"])
def test_non_integer_game_id_storage_is_junk(mod, tmp_path, monkeypatch, text_gid):
    db = _misattributed(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE matches SET game_id = CAST(? AS TEXT) WHERE id = 3"
                 if isinstance(text_gid, str) else
                 "UPDATE matches SET game_id = ? WHERE id = 3", (text_gid,))
    conn.commit()
    stored = conn.execute("SELECT game_id FROM matches WHERE id = 3").fetchone()[0]
    conn.close()
    assert not isinstance(stored, int)  # the column really holds non-integer storage
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    rows = _rows(db)
    assert rows[3][1] == stored  # left as stored
    assert rows[2][1] == 5000000001  # the valid move still landed


def test_ddragon_folder_with_a_non_ascii_digit_is_not_a_crash(mod, tmp_path):
    (tmp_path / "data" / "meta_build" / "ddragon" / "15.\u00b2").mkdir()
    assert mod._load_champion_map()[51] == "Caitlyn"


def _raw_bytes(path, rid):
    conn = sqlite3.connect(path)
    conn.text_factory = bytes
    try:
        return conn.execute("SELECT champion, raw_data FROM matches WHERE id = ?",
                            (rid,)).fetchone()
    finally:
        conn.close()


@pytest.mark.parametrize("dry", [True, False])
def test_invalid_utf8_raw_data_skips_only_its_row(mod, tmp_path, monkeypatch, dry):
    db = _misattributed(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO matches VALUES (8, '2026-05-27 20:00:00', 'SR', "
                 "'Annie', 0, CAST(X'80FF7B7D' AS TEXT))")
    conn.commit()
    conn.close()
    before = _raw_bytes(db, 8)
    argv = ["--db", str(db), "--no-backup"] + (["--dry-run"] if dry else [])
    assert _run(mod, monkeypatch, *argv) == 0
    assert _raw_bytes(db, 8) == before
    if not dry:
        assert json.loads(_rows(db)[2][2])["item211_backfill_received_from"] == 1


@pytest.mark.parametrize("champ_sql", ["CAST(X'80FF' AS TEXT)", "''", "X'00'"])
def test_unreadable_or_empty_champion_never_moves_its_detail(
        mod, tmp_path, monkeypatch, champ_sql):
    db = _misattributed(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute(f"UPDATE matches SET champion = {champ_sql} WHERE id = 1")
    conn.commit()
    conn.close()
    before_1 = _raw_bytes(db, 1)
    assert _run(mod, monkeypatch, "--db", str(db), "--no-backup") == 0
    assert _raw_bytes(db, 1) == before_1
    assert "item211_backfill_received_from" not in json.loads(_rows(db)[2][2])


@pytest.mark.parametrize("dry", [True, False])
def test_non_cp1252_champion_names_print_on_a_cp1252_stdout(
        mod, tmp_path, monkeypatch, dry):
    import io
    cj = tmp_path / "data" / "meta_build" / "ddragon" / "15.1.1" / "champion.json"
    data = json.loads(cj.read_text(encoding="utf-8"))
    data["data"]["Caitlyn"]["name"] = "Cait\u0142yn"  # not in cp1252
    cj.write_text(json.dumps(data), encoding="utf-8")
    db = tmp_path / "m.db"
    _make_db(db, [
        # MOVE line carries the DDragon name.
        (1, "2026-05-27 22:54:03", "SR", "Jinx", 0,
         {"lcu_match_detail": _detail(51, "2026-05-27 23:57:12"), "tracked_puuid": ME}),
        (2, "2026-05-27 23:57:40", "SR", "Cait\u0142yn", 0, {}),
        # ORPHAN line carries the DB champion.
        (3, "2026-05-27 10:00:00", "SR", "\u5409\u514b\u65af", 0,
         {"lcu_match_detail": _detail(103, "2026-05-27 10:00:00"), "tracked_puuid": ME}),
    ]).close()
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    argv = ["--db", str(db), "--no-backup"] + (["--dry-run"] if dry else [])
    assert _run(mod, monkeypatch, *argv) == 0
    out.flush()
    text = out.buffer.getvalue().decode("cp1252")
    assert "MOVE src=1 -> dst=2" in text and "ORPHAN id=3" in text
    assert "\\u0142" in text and "\\u5409" in text  # escaped, not dropped

"""s144 true-audit cycle 109 - dashboard/routes_replay_events.py.

One regression test (or group) per finding, each written RED before the
fix. The characterization suite stays tests/test_routes_replay_events.py.

  F1  the response cache was read and pruned with no lock on a
      ThreadingHTTPServer (a concurrent put could raise "dictionary
      changed size during iteration" inside the prune).
  F2  the cache TTL ran on the wall clock, so a clock step back made an
      entry immortal.
  F3  the read-only URI was an f-string ``file:{path}?mode=ro``: a '#',
      '?' or '%' in the checkout path truncated it and opened the wrong
      file.
  F4  a corrupt DB, a DB without timeline_events, or a locked DB was a
      generic 500 instead of the documented retryable 503.
  F5  match_id was never validated: any length, any character, given
      twice, padded - all reached SQLite and the 404 echoed them back.
  F6  _assists iterated a JSON STRING ('"12"' -> [1, 2]), counted JSON
      true as participant 1, kept 0 / negatives, and one non-ASCII digit
      threw the whole assist list away.
  F7  one non-integer participant_id in the participants table 500'd the
      whole ribbon.
  F8  one non-numeric or infinite kill position, or a non-numeric
      timestamp, 500'd the whole ribbon.
  F9  ``SELECT *`` dragged every row's victim_damage_json blob out of
      SQLite for a field the route never reads.
  F11 the 500 path logged no traceback, and a failed 500 send was
      swallowed by a bare ``except Exception: pass``.
  F12 a repeated include= parameter honoured only its first value.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from dashboard import routes_replay_events as routes

MID = "NA1_9000001"

_SCHEMA = """
CREATE TABLE matches (match_id TEXT PRIMARY KEY, queue_id INTEGER,
                      duration_s INTEGER);
CREATE TABLE participants (match_id TEXT, participant_id INTEGER,
                           team_id INTEGER, summoner_name TEXT,
                           champion_name TEXT);
CREATE TABLE timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT NOT NULL,
    timestamp_ms INTEGER, event_type TEXT, participant_id INTEGER,
    item_id INTEGER, killer_id INTEGER, victim_id INTEGER,
    assisting_ids_json TEXT, bounty INTEGER, shutdown_bounty INTEGER,
    kill_streak_len INTEGER, kill_pos_x INTEGER, kill_pos_y INTEGER,
    victim_damage_json TEXT, building_type TEXT, lane_type TEXT,
    tower_type TEXT, team_id INTEGER, monster_type TEXT,
    monster_subtype TEXT, ward_type TEXT, skill_slot INTEGER,
    level_up_type TEXT, level INTEGER, raw_json TEXT);
"""


def _seed(path: Path, *, extra_participants=(), kills=None) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_SCHEMA)
        conn.execute("INSERT INTO matches VALUES (?, 420, 1800)", (MID,))
        for pid in range(1, 11):
            conn.execute(
                "INSERT INTO participants VALUES (?, ?, ?, ?, ?)",
                (MID, pid, 100 if pid <= 5 else 200, f"P{pid}", f"C{pid}"))
        for row in extra_participants:
            conn.execute("INSERT INTO participants VALUES (?, ?, ?, ?, ?)",
                         (MID, *row))
        if kills is None:
            kills = [(60_000, 2, 8, "[3, 5]", 6126, 13581)]
        for ts, killer, victim, assists, x, y in kills:
            conn.execute(
                "INSERT INTO timeline_events(match_id, timestamp_ms, "
                "event_type, killer_id, victim_id, assisting_ids_json, "
                "kill_pos_x, kill_pos_y, victim_damage_json) "
                "VALUES (?, ?, 'CHAMPION_KILL', ?, ?, ?, ?, ?, ?)",
                (MID, ts, killer, victim, assists, x, y,
                 json.dumps([{"damage": 1}] * 50)))
        conn.commit()
    finally:
        conn.close()


class _H:
    def __init__(self, path: str, *, fail_send: bool = False):
        self.path = path
        self.fail_send = fail_send
        self.responses: list[tuple[int, dict]] = []

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        if self.fail_send:
            raise ConnectionResetError("client went away")
        assert content_type == "application/json"
        self.responses.append((status, json.loads(body)))

    @property
    def last(self) -> tuple[int, dict]:
        assert self.responses, "no response sent"
        return self.responses[-1]


@pytest.fixture(autouse=True)
def _clean_cache():
    routes._CACHE.clear()
    yield
    routes._CACHE.clear()


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "rewind_history.db"
    _seed(path)
    monkeypatch.setattr(routes, "_REWIND_DB", path)
    return path


def _get(query: str, **kw) -> _H:
    h = _H("/api/replay/events?" + query, **kw)
    routes._serve_replay_events(h)
    return h


# -- F1 ------------------------------------------------------------------

class _CountingLock:
    def __init__(self):
        self._lock = threading.Lock()
        self.entries = 0

    def __enter__(self):
        self._lock.acquire()
        self.entries += 1
        return self

    def __exit__(self, *exc):
        self._lock.release()
        return False


def test_f1_cache_get_and_put_hold_the_cache_lock(monkeypatch):
    lock = _CountingLock()
    monkeypatch.setattr(routes, "_CACHE_LOCK", lock)
    routes._cache_put(("k",), {"ok": True})
    assert lock.entries == 1
    assert routes._cache_get(("k",)) == {"ok": True}
    assert lock.entries == 2


def test_f1_prune_under_the_lock_keeps_the_newest(monkeypatch):
    clock = iter(range(1, 10_000))
    monkeypatch.setattr(routes.time, "monotonic", lambda: next(clock))
    for i in range(routes._CACHE_MAX + 1):
        routes._cache_put((i,), {"i": i})
    assert len(routes._CACHE) <= routes._CACHE_MAX
    assert (routes._CACHE_MAX,) in routes._CACHE
    assert (0,) not in routes._CACHE


# -- F2 ------------------------------------------------------------------

def test_f2_ttl_runs_on_the_monotonic_clock(monkeypatch):
    mono = [1_000.0]
    monkeypatch.setattr(routes.time, "monotonic", lambda: mono[0])
    # A wall clock frozen in place must not keep an entry alive.
    monkeypatch.setattr(routes.time, "time", lambda: 5.0)
    routes._cache_put(("k",), {"ok": True})
    mono[0] += routes._CACHE_TTL_S - 1
    assert routes._cache_get(("k",)) == {"ok": True}
    mono[0] += 2
    assert routes._cache_get(("k",)) is None


# -- F3 ------------------------------------------------------------------

@pytest.mark.parametrize("dirname", ["co#rner", "per%41cent", "q?mark"])
def test_f3_checkout_path_with_uri_metacharacters_opens_the_db(
        tmp_path, monkeypatch, dirname):
    try:
        root = tmp_path / dirname
        root.mkdir()
    except OSError:
        pytest.skip(f"filesystem refuses {dirname!r}")
    path = root / "rewind_history.db"
    _seed(path)
    monkeypatch.setattr(routes, "_REWIND_DB", path)
    status, body = _get(f"match_id={MID}").last
    assert status == 200, body
    assert body["count"] == 1


# -- F4 ------------------------------------------------------------------

def _assert_retryable_503(h: _H, tmp_path: Path) -> None:
    status, body = h.last
    assert status == 503, body
    assert body["ok"] is False
    assert "retry" in body["error"]
    assert str(tmp_path) not in json.dumps(body)


def test_f4_corrupt_db_is_a_retryable_503(tmp_path, monkeypatch):
    path = tmp_path / "rewind_history.db"
    path.write_bytes(b"this is not a sqlite database at all" * 200)
    monkeypatch.setattr(routes, "_REWIND_DB", path)
    _assert_retryable_503(_get(f"match_id={MID}"), tmp_path)


def test_f4_db_without_timeline_table_is_a_retryable_503(tmp_path,
                                                        monkeypatch):
    path = tmp_path / "rewind_history.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        "CREATE TABLE matches (match_id TEXT PRIMARY KEY);"
        "CREATE TABLE participants (match_id TEXT, participant_id INTEGER, "
        "team_id INTEGER, summoner_name TEXT, champion_name TEXT);")
    conn.execute("INSERT INTO matches VALUES (?)", (MID,))
    conn.commit()
    conn.close()
    monkeypatch.setattr(routes, "_REWIND_DB", path)
    _assert_retryable_503(_get(f"match_id={MID}"), tmp_path)


def test_f4_sqlite_error_is_logged_with_its_class(tmp_path, monkeypatch,
                                                 caplog):
    path = tmp_path / "rewind_history.db"
    path.write_bytes(b"garbage" * 600)
    monkeypatch.setattr(routes, "_REWIND_DB", path)
    with caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        _get(f"match_id={MID}")
    assert any("DatabaseError" in r.getMessage() for r in caplog.records)


# -- F5 ------------------------------------------------------------------

@pytest.mark.parametrize("query", [
    "match_id=" + "A" * 65,
    "match_id=NA1%20123",
    "match_id=%3Cscript%3E",
    "match_id=NA1_1%0A",
    "match_id=%20" + MID,
    "match_id=_NA1",
    "match_id=NA1_%C3%A9",
    f"match_id={MID}&match_id={MID}",
])
def test_f5_malformed_match_id_is_a_400(db, query):
    status, body = _get(query).last
    assert status == 400, body
    assert body["ok"] is False
    assert "match_id" in body["error"]
    assert "match_id" not in body or body.get("match_id") is None


def test_f5_well_formed_ids_still_pass(db):
    assert _get(f"match_id={MID}").last[0] == 200
    assert _get("match_id=" + "A" * 64).last[0] == 404
    assert _get("match_id=TEST-M1").last[0] == 404


# -- F6 ------------------------------------------------------------------

def _row(raw):
    return {"assisting_ids_json": raw}


@pytest.mark.parametrize("raw, expected", [
    ('"12"', []),
    ('"7"', []),
    ("[true, 3]", [3]),
    ("[false, 4]", [4]),
    ('["\\u00b2", 4]', [4]),
    ('{"3": 1}', []),
    ("[-1, 0, 5]", [5]),
    ('["7", 8]', [7, 8]),
    ("[2.0, 2.5]", []),
    ("null", []),
    ("[[1], 6]", [6]),
    ("not json", []),
    ("", []),
    (None, []),
])
def test_f6_assists_accept_only_positive_participant_ids(raw, expected):
    assert routes._assists(_row(raw)) == expected


# -- F7 ------------------------------------------------------------------

def test_f7_bad_participant_row_does_not_500_the_ribbon(tmp_path,
                                                        monkeypatch):
    path = tmp_path / "rewind_history.db"
    _seed(path, extra_participants=[("ghost", 100, "G", "Gc"),
                                    (11, "blue", "H", "Hc")])
    monkeypatch.setattr(routes, "_REWIND_DB", path)
    status, body = _get(f"match_id={MID}").last
    assert status == 200, body
    ev = body["events"][0]
    assert ev["actor_name"] == "P2"
    assert ev["victim_champion"] == "C8"
    assert ev["team"] == 100


# -- F8 ------------------------------------------------------------------

def test_f8_bad_positions_degrade_to_null_not_500(tmp_path, monkeypatch):
    path = tmp_path / "rewind_history.db"
    _seed(path, kills=[
        (60_000, 2, 8, "[]", "west", 100),
        (70_000, 3, 9, "[]", 1e999, 100),
        (80_000, 4, 10, "[]", 500, 600),
    ])
    monkeypatch.setattr(routes, "_REWIND_DB", path)
    status, body = _get(f"match_id={MID}").last
    assert status == 200, body
    assert [e["pos"] for e in body["events"]] == [None, None, [500, 600]]


def test_f8_unusable_timestamp_row_is_skipped_not_500(tmp_path, monkeypatch,
                                                     caplog):
    path = tmp_path / "rewind_history.db"
    _seed(path, kills=[
        (60_000, 2, 8, "[]", 1, 1),
        ("soon", 3, 9, "[]", 1, 1),
        (1e999, 4, 10, "[]", 1, 1),
        (None, 5, 6, "[]", 1, 1),
    ])
    monkeypatch.setattr(routes, "_REWIND_DB", path)
    with caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        status, body = _get(f"match_id={MID}").last
    assert status == 200, body
    # NULL keeps its historical clock 0; the two unusable rows are dropped.
    assert sorted(e["clock_s"] for e in body["events"]) == [0, 60]
    assert body["count"] == 2
    assert any("skipped 2" in r.getMessage() for r in caplog.records)


def test_f8_as_int_contract():
    f = routes._as_int
    assert f(7) == 7
    assert f(7.0) == 7
    assert f("7") == 7
    for bad in (None, True, False, 7.5, "x", "", chr(0xB2), float("inf"),
                float("nan"), b"7", [7]):
        assert f(bad) is None, bad


# -- F9 ------------------------------------------------------------------

def test_f9_query_names_its_columns_and_skips_the_damage_blob(db,
                                                             monkeypatch):
    statements: list[str] = []
    real_connect = sqlite3.connect

    def tracing_connect(*a, **kw):
        conn = real_connect(*a, **kw)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(routes.sqlite3, "connect", tracing_connect)
    status, body = _get(f"match_id={MID}&include=all").last
    assert status == 200, body
    events_sql = [s for s in statements if "timeline_events" in s]
    assert events_sql, statements
    for s in events_sql:
        assert "*" not in s, s
        assert "victim_damage_json" not in s, s
        assert "raw_json" not in s, s


# -- F11 -----------------------------------------------------------------

def test_f11_unexpected_failure_logs_a_traceback(db, caplog):
    with patch.object(routes, "_event_types_for",
                      side_effect=RuntimeError("boom")), \
            caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        status, body = _get(f"match_id={MID}").last
    assert status == 500
    assert body == {"ok": False, "error": "internal error - see logs"}
    assert any(r.exc_info for r in caplog.records)


def test_f11_failed_500_send_is_logged_not_swallowed(db, caplog):
    with patch.object(routes, "_event_types_for",
                      side_effect=RuntimeError("boom")), \
            caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        h = _get(f"match_id={MID}", fail_send=True)
    assert h.responses == []
    assert any("could not send" in r.getMessage() for r in caplog.records)


# -- F12 -----------------------------------------------------------------

def test_f12_repeated_include_params_are_unioned(tmp_path, monkeypatch):
    path = tmp_path / "rewind_history.db"
    _seed(path)
    conn = sqlite3.connect(str(path))
    conn.execute("INSERT INTO timeline_events(match_id, timestamp_ms, "
                 "event_type, participant_id, item_id) "
                 "VALUES (?, 90000, 'ITEM_PURCHASED', 1, 3865)", (MID,))
    conn.execute("INSERT INTO timeline_events(match_id, timestamp_ms, "
                 "event_type, participant_id, ward_type) "
                 "VALUES (?, 95000, 'WARD_PLACED', 1, 'YELLOW_TRINKET')",
                 (MID,))
    conn.commit()
    conn.close()
    monkeypatch.setattr(routes, "_REWIND_DB", path)
    status, body = _get(f"match_id={MID}&include=items&include=wards").last
    assert status == 200, body
    assert body["include"] == ["items", "wards"]
    assert body["count"] == 3
    # Same set, one comma-joined parameter: one cache entry, served cached.
    _status, body2 = _get(f"match_id={MID}&include=wards,items").last
    assert body2["cached"] is True

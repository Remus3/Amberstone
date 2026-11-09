"""
tests/test_routes_replay_events_exact_ms.py
GET /api/replay/events carries each event's own millisecond as
`timestamp_ms` beside the whole-second `clock_s` (s144 lane uiux,
S144-U-195; the U-193 FUTURE row "a ribbon seek uses clock_s * 1000, which
lands before a kill's own ms (230000 < 230254), so at the seek moment the
victim is not yet dead on the map").

The past-match minimap (web/js/panels/replay_minimap.js) opens a death
window at the kill's own `timestamp_ms` from the match reply's `kills`
rows. The ribbon only had `clock_s` (timestamp_ms // 1000), so a Timeline
kill seek put the map up to 999 ms before the kill: the victim still
alive, the killer still at its last frame. The field is additive; the
ribbon row carries it as data-ms and the seek uses it.

Contract pinned here:
  - every event carries `timestamp_ms`, the stored integer ms, with
    clock_s == timestamp_ms // 1000;
  - a NULL stored timestamp keeps clock 0 and reads `timestamp_ms: null`
    (the ms is unknown; the row seeks on its clock as before);
  - a REAL (float) stored timestamp is floored like clock_s.
"""
from __future__ import annotations

import sqlite3

import pytest

from dashboard import routes_replay_events as routes
from tests.test_routes_replay_events_audit_s144 import MID, _get, _seed


@pytest.fixture(autouse=True)
def _clean_cache():
    routes._CACHE.clear()
    yield
    routes._CACHE.clear()


def _events(tmp_path, monkeypatch, kills, extra_sql=()):
    path = tmp_path / "rewind_history.db"
    _seed(path, kills=kills)
    if extra_sql:
        conn = sqlite3.connect(str(path))
        try:
            for sql, args in extra_sql:
                conn.execute(sql, args)
            conn.commit()
        finally:
            conn.close()
    monkeypatch.setattr(routes, "_REWIND_DB", path)
    status, body = _get(f"match_id={MID}").last
    assert status == 200, body
    return body["events"]


def test_every_event_carries_its_exact_ms(tmp_path, monkeypatch):
    events = _events(tmp_path, monkeypatch, kills=[
        (230_254, 1, 6, "[]", 3328, 11272),
        (1_488_912, 4, 6, "[3, 5]", 9557, 6064),
    ], extra_sql=[(
        "INSERT INTO timeline_events(match_id, timestamp_ms, event_type, "
        "killer_id, team_id, building_type, lane_type, tower_type) "
        "VALUES (?, 940517, 'BUILDING_KILL', 4, 200, 'TOWER_BUILDING', "
        "'MID_LANE', 'OUTER_TURRET')", (MID,))])
    got = [(e["type"], e["clock_s"], e.get("timestamp_ms")) for e in events]
    assert got == [
        ("CHAMPION_KILL", 230, 230_254),
        ("BUILDING_KILL", 940, 940_517),
        ("CHAMPION_KILL", 1488, 1_488_912),
    ], got
    for e in events:
        assert isinstance(e["timestamp_ms"], int), e
        assert e["clock_s"] == e["timestamp_ms"] // 1000, e


def test_a_null_timestamp_reads_null_ms_and_clock_zero(tmp_path, monkeypatch):
    events = _events(tmp_path, monkeypatch, kills=[
        (None, 5, 6, "[]", 1, 1),
        (60_000, 2, 8, "[]", 1, 1),
    ])
    got = sorted((e["clock_s"], e["timestamp_ms"]) for e in events)
    assert got == [(0, None), (60, 60_000)], got


def test_a_real_timestamp_is_floored_like_its_clock(tmp_path, monkeypatch):
    events = _events(tmp_path, monkeypatch, kills=[
        (230_254.75, 1, 6, "[]", 1, 1),
    ])
    assert [(e["clock_s"], e["timestamp_ms"]) for e in events] == [
        (230, 230_254)]
    assert isinstance(events[0]["timestamp_ms"], int)


def test_no_non_ascii_in_this_file():
    from pathlib import Path
    raw = Path(__file__).read_bytes()
    assert all(b < 0x80 for b in raw)
    assert b"\r" not in raw

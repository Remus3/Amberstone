"""Tests for core.session_hygiene - deterministic session-hygiene analytics.

TDD-first. Every fixture is a synthetic tmp_path sqlite db so the suite is
clean-checkout safe (data/rewind_history.db is gitignored). The one real-db
test asserts STRUCTURE only (keys present, readiness bounded), never exact
values, because the corpus changes.

WR math is asserted against the SAME laplace_rate the module uses (imported
from core.smoothed_rates), never a hand-written float, so the test cannot
drift from the primitive.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core import session_hygiene as sh
from core.smoothed_rates import laplace_rate

_HOUR_MS = 3600 * 1000
_DAY_MS = 24 * _HOUR_MS

# A fixed non-UTC tz so hour/weekday bucketing is deterministic + not the CI
# host's local zone.
FIXED_TZ = timezone(timedelta(hours=5))

# 2024-01-01 00:00:00 UTC. 2024-01-01 is a Monday (weekday()==0).
_ANCHOR_UTC_MS = int(
    datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000
)


def _make_db(tmp_path: Path, rows) -> Path:
    """rows: iterable of (creation_ms, end_ms, win, champ_id[, queue_id]).

    Builds a minimal matches table matching the real schema's relevant
    columns. duration is derived; game_mode/champion_name are filler.
    """
    db = tmp_path / "hygiene_test.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE matches ("
        "game_creation_ts INTEGER, game_end_ts INTEGER, game_duration_s INTEGER,"
        "tracked_win INTEGER, tracked_champion_id INTEGER,"
        "tracked_champion_name TEXT, queue_id INTEGER, game_mode TEXT)"
    )
    for r in rows:
        creation, end, win, champ = r[0], r[1], r[2], r[3]
        queue = r[4] if len(r) > 4 else 450
        dur = max(1, int((end - creation) / 1000))
        conn.execute(
            "INSERT INTO matches VALUES (?,?,?,?,?,?,?,?)",
            (creation, end, dur, win, champ, "Champ", queue, "ARAM"),
        )
    conn.commit()
    conn.close()
    return db


def _game(start_ms, win, champ=1, dur_ms=20 * 60 * 1000):
    """One game: returns (creation, end, win, champ). end = start + duration."""
    return (start_ms, start_ms + dur_ms, win, champ)


# --------------------------------------------------------------------------
# session detection
# --------------------------------------------------------------------------

def test_session_split_at_gap_boundary_same_session(tmp_path):
    # Gap between game A end and game B creation == SESSION_GAP_MS exactly ->
    # still one session (split is a STRICT > gap).
    a = _game(_ANCHOR_UTC_MS, 1)
    b_start = a[1] + sh.SESSION_GAP_MS
    b = _game(b_start, 0)
    db = _make_db(tmp_path, [a, b])
    now = b[1] + 60_000
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    assert out["session_detection"]["session_count"] == 1


def test_session_split_over_gap_boundary_new_session(tmp_path):
    a = _game(_ANCHOR_UTC_MS, 1)
    b_start = a[1] + sh.SESSION_GAP_MS + 1
    b = _game(b_start, 0)
    db = _make_db(tmp_path, [a, b])
    now = b[1] + 60_000
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    assert out["session_detection"]["session_count"] == 2


def test_current_session_games_counts_open_session(tmp_path):
    # Two games close together, now_ms shortly after the last -> current
    # session is open and has 2 games.
    a = _game(_ANCHOR_UTC_MS, 1)
    b = _game(a[1] + 10 * 60 * 1000, 0)  # 10m gap, same session
    db = _make_db(tmp_path, [a, b])
    now = b[1] + 30 * 60 * 1000  # 30m after last game, < gap
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    assert out["session_detection"]["current_session_games"] == 2
    assert out["session_detection"]["in_session"] is True


def test_current_session_closed_when_now_far_past(tmp_path):
    a = _game(_ANCHOR_UTC_MS, 1)
    b = _game(a[1] + 10 * 60 * 1000, 0)
    db = _make_db(tmp_path, [a, b])
    now = b[1] + sh.SESSION_GAP_MS + 1  # long past -> session closed
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    assert out["session_detection"]["current_session_games"] == 0
    assert out["session_detection"]["in_session"] is False


# --------------------------------------------------------------------------
# wr by session position
# --------------------------------------------------------------------------

def test_wr_by_session_position_direction(tmp_path):
    # 5 sessions, each 3 games: position 1 always LOSES, position 3 always
    # WINS. Shrunk WR must order position3 > position1.
    rows = []
    base = _ANCHOR_UTC_MS
    for s in range(5):
        session_start = base + s * (sh.SESSION_GAP_MS + _DAY_MS)
        g1 = _game(session_start, 0)                       # pos1 loss
        g2 = _game(g1[1] + 5 * 60 * 1000, 0)               # pos2
        g3 = _game(g2[1] + 5 * 60 * 1000, 1)               # pos3 win
        rows += [g1, g2, g3]
    db = _make_db(tmp_path, rows)
    now = rows[-1][1] + _DAY_MS * 30
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    by_pos = {b["position"]: b for b in out["wr_by_session_position"]}
    assert by_pos[1]["games"] == 5
    assert by_pos[3]["games"] == 5
    assert by_pos[1]["wr"] is not None
    assert by_pos[3]["wr"] is not None
    assert by_pos[3]["wr"] > by_pos[1]["wr"]
    # WR routed through laplace_rate: pos1 5 losses -> shrunk, not raw 0.0.
    # wr is rounded to 4dp for display, so compare within that precision.
    assert by_pos[1]["wr"] == pytest.approx(laplace_rate(0, 5), abs=1e-4)
    assert by_pos[1]["wr"] > 0.0


def test_session_position_tail_bucket_caps(tmp_path):
    # A single 10-game session: positions 8,9,10 fold into the 8+ tail.
    start = _ANCHOR_UTC_MS
    rows = []
    t = start
    for i in range(10):
        g = _game(t, 1)
        rows.append(g)
        t = g[1] + 5 * 60 * 1000
    db = _make_db(tmp_path, rows)
    now = rows[-1][1] + _DAY_MS * 30
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    tail = [b for b in out["wr_by_session_position"] if b["position"] == sh.POSITION_CAP][0]
    # positions 8,9,10 -> 3 games in the tail bucket.
    assert tail["games"] == 3
    assert tail["label"].endswith("+")


# --------------------------------------------------------------------------
# hour / weekday bucketing (fixed tz)
# --------------------------------------------------------------------------

def test_hour_bucketing_fixed_tz(tmp_path):
    # anchor is 00:00 UTC; FIXED_TZ is +5 -> local hour 5.
    g = _game(_ANCHOR_UTC_MS, 1)
    db = _make_db(tmp_path, [g])
    now = g[1] + _DAY_MS * 30
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    by_hour = {b["hour"]: b for b in out["wr_by_hour"]}
    assert by_hour[5]["games"] == 1
    assert sum(b["games"] for b in out["wr_by_hour"]) == 1


def test_weekday_bucketing_fixed_tz(tmp_path):
    # 2024-01-01 is Monday. At 00:00 UTC + tz +5 it is still Monday 05:00.
    g = _game(_ANCHOR_UTC_MS, 1)
    db = _make_db(tmp_path, [g])
    now = g[1] + _DAY_MS * 30
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    by_wd = {b["weekday"]: b for b in out["wr_by_weekday"]}
    assert by_wd[0]["games"] == 1  # Monday
    assert by_wd[0]["label"] == "Mon"


def test_weekday_crosses_local_midnight(tmp_path):
    # 2024-01-01 22:00 UTC + tz +5 -> 2024-01-02 03:00 local = Tuesday(1).
    ms = int(datetime(2024, 1, 1, 22, 0, tzinfo=timezone.utc).timestamp() * 1000)
    g = _game(ms, 1)
    db = _make_db(tmp_path, [g])
    now = g[1] + _DAY_MS * 30
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    by_wd = {b["weekday"]: b for b in out["wr_by_weekday"]}
    assert by_wd[1]["games"] == 1  # Tuesday
    by_hour = {b["hour"]: b for b in out["wr_by_hour"]}
    assert by_hour[3]["games"] == 1  # 03:00 local


# --------------------------------------------------------------------------
# rust buckets
# --------------------------------------------------------------------------

def test_rust_bucket_boundaries(tmp_path):
    # Chain of games with controlled gaps-since-previous-game.
    # g0 (no prev), then gaps of 3h, 12h, 36h, 72h.
    g0 = _game(_ANCHOR_UTC_MS, 1)
    g1 = _game(g0[1] + 3 * _HOUR_MS, 1)     # <6h
    g2 = _game(g1[1] + 12 * _HOUR_MS, 1)    # 6-24h
    g3 = _game(g2[1] + 36 * _HOUR_MS, 1)    # 1-2d
    g4 = _game(g3[1] + 72 * _HOUR_MS, 1)    # 2d+
    db = _make_db(tmp_path, [g0, g1, g2, g3, g4])
    now = g4[1] + _DAY_MS * 30
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    by_label = {b["label"]: b for b in out["rust"]}
    assert by_label["<6h"]["games"] == 1
    assert by_label["6-24h"]["games"] == 1
    assert by_label["1-2d"]["games"] == 1
    assert by_label["2d+"]["games"] == 1
    # g0 has no previous game -> excluded from every rust bucket.
    assert sum(b["games"] for b in out["rust"]) == 4


# --------------------------------------------------------------------------
# same-champ requeue
# --------------------------------------------------------------------------

def test_same_champ_requeue_within_session(tmp_path):
    # Same champ back-to-back INSIDE a session -> same_champ bucket.
    g0 = _game(_ANCHOR_UTC_MS, 0, champ=7)
    g1 = _game(g0[1] + 5 * 60 * 1000, 1, champ=7)  # same champ, same session
    db = _make_db(tmp_path, [g0, g1])
    now = g1[1] + _DAY_MS * 30
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    assert out["same_champ_requeue"]["same_champ"]["games"] == 1
    assert out["same_champ_requeue"]["diff_champ"]["games"] == 0


def test_diff_champ_requeue_within_session(tmp_path):
    g0 = _game(_ANCHOR_UTC_MS, 0, champ=7)
    g1 = _game(g0[1] + 5 * 60 * 1000, 1, champ=8)  # different champ
    db = _make_db(tmp_path, [g0, g1])
    now = g1[1] + _DAY_MS * 30
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    assert out["same_champ_requeue"]["same_champ"]["games"] == 0
    assert out["same_champ_requeue"]["diff_champ"]["games"] == 1


def test_requeue_not_counted_across_session_boundary(tmp_path):
    # Same champ but a session gap between them -> the second game is position
    # 1 of a new session, so it has NO in-session previous and is excluded.
    g0 = _game(_ANCHOR_UTC_MS, 0, champ=7)
    g1 = _game(g0[1] + sh.SESSION_GAP_MS + 1, 1, champ=7)
    db = _make_db(tmp_path, [g0, g1])
    now = g1[1] + _DAY_MS * 30
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    assert out["same_champ_requeue"]["same_champ"]["games"] == 0
    assert out["same_champ_requeue"]["diff_champ"]["games"] == 0


# --------------------------------------------------------------------------
# readiness
# --------------------------------------------------------------------------

def test_readiness_bounded_and_tier_present(tmp_path):
    rows = [_game(_ANCHOR_UTC_MS + i * _DAY_MS, i % 2) for i in range(10)]
    db = _make_db(tmp_path, rows)
    now = rows[-1][1] + _DAY_MS * 30
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    r = out["readiness"]
    assert 0 <= r["score"] <= 100
    assert r["confidence"] in ("HIGH", "MED", "LOW")


def test_readiness_drops_for_tilt_pattern(tmp_path):
    # Build a strong late-session tilt: deep positions (4th+) always lose.
    # Then set now_ms so the player is mid-session with several games already
    # played -> next position is a losing one -> readiness must fall below 50.
    rows = []
    base = _ANCHOR_UTC_MS
    for s in range(8):
        session_start = base + s * (sh.SESSION_GAP_MS + _DAY_MS)
        t = session_start
        session_games = []
        for pos in range(6):
            win = 1 if pos < 3 else 0   # first 3 win, rest lose (tilt)
            g = _game(t, win)
            session_games.append(g)
            t = g[1] + 5 * 60 * 1000
        rows += session_games
    db = _make_db(tmp_path, rows)
    # Put now_ms just after the 4th game of the final session so 4 games are
    # already played this session (next position = 5, a losing bucket).
    last_session_start = base + 7 * (sh.SESSION_GAP_MS + _DAY_MS)
    t = last_session_start
    ends = []
    for pos in range(6):
        end = t + 20 * 60 * 1000
        ends.append(end)
        t = end + 5 * 60 * 1000
    now = ends[3] + 60_000  # right after 4th game
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    assert out["session_detection"]["current_session_games"] == 4
    assert out["readiness"]["score"] < 50


# --------------------------------------------------------------------------
# thin buckets / fail-soft
# --------------------------------------------------------------------------

def test_thin_bucket_does_not_read_extreme(tmp_path):
    # A single win in a bucket must NOT surface as 100% (1.0) or 0%.
    g = _game(_ANCHOR_UTC_MS, 1)
    db = _make_db(tmp_path, [g])
    now = g[1] + _DAY_MS * 30
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ)
    pos1 = [b for b in out["wr_by_session_position"] if b["position"] == 1][0]
    assert pos1["games"] == 1
    # thin -> surfaced wr omitted (None), never 1.0/0.0.
    assert pos1["wr"] is None
    # the shrink-toward-prior blended value stays strictly interior.
    assert 0.0 < pos1["wr_blended"] < 1.0


def test_empty_db_fails_soft(tmp_path):
    db = _make_db(tmp_path, [])
    out = sh.compute_session_hygiene(db_path=db, now_ms=_ANCHOR_UTC_MS, tz=FIXED_TZ)
    assert out["ok"] is True
    assert out["n"] == 0
    assert out["session_detection"]["session_count"] == 0
    assert 0 <= out["readiness"]["score"] <= 100


def test_single_game_db_fails_soft(tmp_path):
    g = _game(_ANCHOR_UTC_MS, 1)
    db = _make_db(tmp_path, [g])
    out = sh.compute_session_hygiene(db_path=db, now_ms=g[1] + 1000, tz=FIXED_TZ)
    assert out["ok"] is True
    assert out["n"] == 1


def test_missing_db_fails_soft(tmp_path):
    out = sh.compute_session_hygiene(
        db_path=tmp_path / "does_not_exist.db", now_ms=_ANCHOR_UTC_MS, tz=FIXED_TZ
    )
    assert out["ok"] is True
    assert out["n"] == 0


def test_null_timestamps_are_dropped(tmp_path):
    # Rows with null creation/end cannot be sequenced -> dropped, no crash.
    db = tmp_path / "nulls.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE matches ("
        "game_creation_ts INTEGER, game_end_ts INTEGER, game_duration_s INTEGER,"
        "tracked_win INTEGER, tracked_champion_id INTEGER,"
        "tracked_champion_name TEXT, queue_id INTEGER, game_mode TEXT)"
    )
    good = _game(_ANCHOR_UTC_MS, 1)
    conn.execute("INSERT INTO matches VALUES (?,?,?,?,?,?,?,?)",
                 (good[0], good[1], 1200, 1, 1, "C", 450, "ARAM"))
    conn.execute("INSERT INTO matches VALUES (?,?,?,?,?,?,?,?)",
                 (None, None, 1200, 0, 1, "C", 450, "ARAM"))
    conn.commit()
    conn.close()
    out = sh.compute_session_hygiene(db_path=db, now_ms=_ANCHOR_UTC_MS + _DAY_MS, tz=FIXED_TZ)
    assert out["n"] == 1


# --------------------------------------------------------------------------
# queue filter
# --------------------------------------------------------------------------

def test_queue_id_filter(tmp_path):
    g0 = _game(_ANCHOR_UTC_MS, 1)                         # queue 450 (default)
    g1 = (_ANCHOR_UTC_MS + _DAY_MS, _ANCHOR_UTC_MS + _DAY_MS + 1200_000, 0, 1, 420)
    db = _make_db(tmp_path, [g0, g1])
    now = _ANCHOR_UTC_MS + _DAY_MS * 30
    out = sh.compute_session_hygiene(db_path=db, now_ms=now, tz=FIXED_TZ, queue_ids=[450])
    assert out["n"] == 1


# --------------------------------------------------------------------------
# real-db smoke (STRUCTURE only)
# --------------------------------------------------------------------------

def test_real_db_smoke_structure():
    real = Path(sh.__file__).resolve().parent.parent / "data" / "rewind_history.db"
    if not real.exists():
        pytest.skip("real rewind_history.db not present (gitignored)")
    out = sh.compute_session_hygiene(now_ms=1784606573679 + 60_000, tz=FIXED_TZ)
    for key in (
        "ok", "n", "overall_wr", "session_detection",
        "wr_by_session_position", "wr_by_hour", "wr_by_weekday",
        "rust", "same_champ_requeue", "readiness",
    ):
        assert key in out
    assert out["ok"] is True
    assert 0 <= out["readiness"]["score"] <= 100
    assert len(out["wr_by_hour"]) == 24
    assert len(out["wr_by_weekday"]) == 7
    assert 0.0 <= out["overall_wr"] <= 1.0

"""Tests for core.perf_curve - per-minute averaged performance curve.

All tests inject an in-memory sqlite via the conn= seam so they never touch
the gitignored rewind_history.db (clean-checkout safe).
"""
from __future__ import annotations

import sqlite3

import pytest

from core import perf_curve


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE matches (
            match_id TEXT PRIMARY KEY,
            tracked_win INTEGER,
            tracked_champion_id INTEGER,
            tracked_team_id INTEGER,
            map_id INTEGER,
            has_stats INTEGER,
            game_duration_s INTEGER
        );
        CREATE TABLE participants (
            match_id TEXT,
            participant_id INTEGER,
            champion_id INTEGER,
            team_id INTEGER
        );
        CREATE TABLE timeline_frames (
            match_id TEXT,
            participant_id INTEGER,
            timestamp_ms INTEGER,
            total_gold INTEGER,
            minions_killed INTEGER,
            jungle_minions INTEGER
        );
        """
    )
    return conn


def _add_game(conn, mid, *, win, champ=64, team=100, map_id=12,
              dur=1200, pid=3, frames=None, has_stats=1):
    """frames = list of (minute, total_gold, minions, jungle)."""
    conn.execute(
        "INSERT INTO matches VALUES (?,?,?,?,?,?,?)",
        (mid, 1 if win else 0, champ, team, map_id, has_stats, dur),
    )
    conn.execute(
        "INSERT INTO participants VALUES (?,?,?,?)",
        (mid, pid, champ, team),
    )
    for (minute, gold, minions, jungle) in (frames or []):
        conn.execute(
            "INSERT INTO timeline_frames VALUES (?,?,?,?,?,?)",
            (mid, pid, minute * 60000, gold, minions, jungle),
        )


def _series(payload, minute, key):
    for row in payload["minutes"]:
        if row["minute"] == minute:
            return row[key]
    return "MISSING"


def test_gold_curve_averages_win_loss_split():
    conn = _db()
    # 6 wins each 1000 gold @min1, 6 losses each 600 gold @min1.
    for i in range(6):
        _add_game(conn, f"W{i}", win=True,
                  frames=[(1, 1000, 10, 0)])
    for i in range(6):
        _add_game(conn, f"L{i}", win=False,
                  frames=[(1, 600, 6, 0)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="gold", conn=conn)
    assert out["ok"] is True
    assert out["n_games"] == 12
    assert _series(out, 1, "win_avg") == 1000.0
    assert _series(out, 1, "win_n") == 6
    assert _series(out, 1, "loss_avg") == 600.0
    assert _series(out, 1, "loss_n") == 6


def test_cs_metric_sums_minions_and_jungle():
    conn = _db()
    for i in range(5):
        _add_game(conn, f"W{i}", win=True, frames=[(2, 0, 30, 4)])
    for i in range(5):
        _add_game(conn, f"L{i}", win=False, frames=[(2, 0, 20, 0)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="cs", conn=conn)
    assert _series(out, 2, "win_avg") == 34.0   # 30 + 4
    assert _series(out, 2, "loss_avg") == 20.0


def test_min_games_gate_nulls_thin_series():
    conn = _db()
    # only 3 wins at min1 -> below MIN_GAMES_N -> win_avg None, but 5 losses ok.
    for i in range(3):
        _add_game(conn, f"W{i}", win=True, frames=[(1, 1000, 0, 0)])
    for i in range(5):
        _add_game(conn, f"L{i}", win=False, frames=[(1, 500, 0, 0)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="gold", conn=conn)
    assert _series(out, 1, "win_avg") is None
    assert _series(out, 1, "win_n") == 3
    assert _series(out, 1, "loss_avg") == 500.0


def test_champion_filter():
    conn = _db()
    for i in range(5):
        _add_game(conn, f"A{i}", win=True, champ=64, frames=[(1, 900, 0, 0)])
    for i in range(5):
        _add_game(conn, f"B{i}", win=True, champ=99, frames=[(1, 100, 0, 0)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="gold",
                                        champion=64, conn=conn)
    assert out["n_games"] == 5
    assert _series(out, 1, "win_avg") == 900.0


def test_remake_gate_drops_short_games():
    conn = _db()
    for i in range(5):
        _add_game(conn, f"S{i}", win=True, dur=120,  # < MIN_DURATION_S
                  frames=[(1, 1000, 0, 0)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="gold", conn=conn)
    assert out["n_games"] == 0
    assert out["minutes"] == []


def test_sentinel_double_participant_not_double_counted():
    conn = _db()
    # 5 clean games + 1 game whose tracked join matches TWO participant rows
    # (sentinel collision): both share champ/team but different participant_id.
    for i in range(5):
        _add_game(conn, f"C{i}", win=True, frames=[(1, 1000, 0, 0)])
    _add_game(conn, "DUP", win=True, pid=3, frames=[(1, 1000, 0, 0)])
    # second colliding participant row + its (wrong) frames
    conn.execute("INSERT INTO participants VALUES (?,?,?,?)", ("DUP", 7, 64, 100))
    conn.execute("INSERT INTO timeline_frames VALUES (?,?,?,?,?,?)",
                 ("DUP", 7, 60000, 9999, 0, 0))
    out = perf_curve.compute_perf_curve(mode="aram", metric="gold", conn=conn)
    assert out["n_games"] == 6
    # the 9999 sentinel frame must NOT pollute the average (all 6 are 1000).
    assert _series(out, 1, "win_avg") == 1000.0


def test_max_minute_cap_drops_corrupt_frames():
    conn = _db()
    for i in range(5):
        _add_game(conn, f"W{i}", win=True, dur=3000,
                  frames=[(1, 1000, 0, 0), (perf_curve.MAX_MINUTE + 10, 5, 0, 0)])
    out = perf_curve.compute_perf_curve(mode="aram", metric="gold", conn=conn)
    minutes = [r["minute"] for r in out["minutes"]]
    assert 1 in minutes
    assert all(m <= perf_curve.MAX_MINUTE for m in minutes)


def test_mode_and_metric_fallback():
    conn = _db()
    for i in range(5):
        _add_game(conn, f"W{i}", win=True, frames=[(1, 1000, 0, 0)])
    out = perf_curve.compute_perf_curve(mode="bogus", metric="bogus", conn=conn)
    assert out["mode"] == perf_curve.DEFAULT_MODE
    assert out["metric"] == perf_curve.DEFAULT_METRIC


def test_no_db_returns_ok_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(perf_curve, "_REWIND_DB", tmp_path / "absent.db")
    out = perf_curve.compute_perf_curve(mode="aram")
    assert out["ok"] is True
    assert out["minutes"] == []
    assert out["n_games"] == 0


@pytest.mark.parametrize("metric", perf_curve.VALID_METRICS)
def test_every_metric_returns_curve(metric):
    conn = _db()
    for i in range(5):
        _add_game(conn, f"W{i}", win=True, frames=[(1, 1000, 20, 2)])
    out = perf_curve.compute_perf_curve(mode="aram", metric=metric, conn=conn)
    assert out["ok"] is True
    assert out["metric"] == metric
    assert _series(out, 1, "win_avg") is not None

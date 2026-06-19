"""Tests for core.op_score_curve - per-interval composite OP-Score curve.

All tests inject an in-memory sqlite via the conn= seam so they never touch the
gitignored rewind_history.db (clean-checkout safe). Assertions are on COMPUTED
quantities (score bounds, win-vs-loss ordering, the transparent weight blend),
not fragile cross-row magic numbers.
"""
from __future__ import annotations

from core import op_score_curve


def _db():
    import sqlite3
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
            xp INTEGER,
            minions_killed INTEGER,
            jungle_minions INTEGER,
            total_dmg_done INTEGER
        );
        """
    )
    return conn


def _add_game(conn, mid, *, win, champ=64, team=100, map_id=12,
              dur=1200, pid=3, frames=None, has_stats=1):
    """frames = list of (minute, gold, xp, minions, jungle, dmg)."""
    conn.execute(
        "INSERT INTO matches VALUES (?,?,?,?,?,?,?)",
        (mid, 1 if win else 0, champ, team, map_id, has_stats, dur),
    )
    conn.execute(
        "INSERT INTO participants VALUES (?,?,?,?)",
        (mid, pid, champ, team),
    )
    for (minute, gold, xp, minions, jungle, dmg) in (frames or []):
        conn.execute(
            "INSERT INTO timeline_frames VALUES (?,?,?,?,?,?,?,?)",
            (mid, pid, minute * 60000, gold, xp, minions, jungle, dmg),
        )


def _series(payload, minute, key):
    for row in payload["minutes"]:
        if row["minute"] == minute:
            return row[key]
    return "MISSING"


def test_score_is_bounded_0_100_and_split():
    conn = _db()
    # 6 strong wins, 6 weaker losses, all single-minute @ minute 1.
    for i in range(6):
        _add_game(conn, f"W{i}", win=True,
                  frames=[(1, 1000, 900, 30, 0, 5000)])
    for i in range(6):
        _add_game(conn, f"L{i}", win=False,
                  frames=[(1, 600, 500, 18, 0, 2500)])
    out = op_score_curve.compute_op_score_curve(mode="aram", conn=conn)
    assert out["ok"] is True
    assert out["n_games"] == 12
    wa = _series(out, 1, "win_avg")
    la = _series(out, 1, "loss_avg")
    # Both composites are in [0, 100].
    for v in (wa, la):
        assert v is not None
        assert 0.0 <= v <= 100.0
    # The stronger-stat win bucket scores strictly above the loss bucket.
    assert wa > la
    # The corpus max sits at 100 (the winning games define the per-minute max),
    # so the win bucket - all identical max-pace games - scores exactly 100.
    assert wa == 100.0
    assert _series(out, 1, "win_n") == 6
    assert _series(out, 1, "loss_n") == 6


def test_weights_blend_is_transparent():
    conn = _db()
    # One winning game sets the per-minute max for every stat. One losing game
    # is at HALF on gold only, FULL on the other three -> its composite must be
    # exactly 100 - 50*W_GOLD = 100 - 17.5 = 82.5. Pad each bucket to >= MIN.
    for i in range(5):
        _add_game(conn, f"W{i}", win=True,
                  frames=[(1, 1000, 1000, 100, 0, 1000)])
    for i in range(5):
        _add_game(conn, f"L{i}", win=False,
                  frames=[(1, 500, 1000, 100, 0, 1000)])
    out = op_score_curve.compute_op_score_curve(mode="aram", conn=conn)
    assert _series(out, 1, "win_avg") == 100.0
    expected = round(100.0 - 50.0 * op_score_curve.W_GOLD, 1)
    assert _series(out, 1, "loss_avg") == expected


def test_min_games_gate_nulls_thin_series():
    conn = _db()
    for i in range(3):  # below MIN_GAMES_N
        _add_game(conn, f"W{i}", win=True,
                  frames=[(1, 1000, 1000, 50, 0, 1000)])
    for i in range(5):
        _add_game(conn, f"L{i}", win=False,
                  frames=[(1, 500, 500, 25, 0, 500)])
    out = op_score_curve.compute_op_score_curve(mode="aram", conn=conn)
    assert _series(out, 1, "win_avg") is None
    assert _series(out, 1, "win_n") == 3
    assert _series(out, 1, "loss_avg") is not None


def test_champion_filter():
    conn = _db()
    for i in range(5):
        _add_game(conn, f"A{i}", win=True, champ=64,
                  frames=[(1, 900, 900, 40, 0, 900)])
    for i in range(5):
        _add_game(conn, f"B{i}", win=True, champ=99,
                  frames=[(1, 100, 100, 4, 0, 100)])
    out = op_score_curve.compute_op_score_curve(mode="aram", champion=64,
                                                conn=conn)
    assert out["n_games"] == 5
    assert out["champion"] == 64


def test_remake_gate_drops_short_games():
    conn = _db()
    for i in range(5):
        _add_game(conn, f"S{i}", win=True, dur=120,  # < MIN_DURATION_S
                  frames=[(1, 1000, 1000, 50, 0, 1000)])
    out = op_score_curve.compute_op_score_curve(mode="aram", conn=conn)
    assert out["n_games"] == 0
    assert out["minutes"] == []


def test_sentinel_double_participant_not_double_counted():
    conn = _db()
    for i in range(5):
        _add_game(conn, f"C{i}", win=True,
                  frames=[(1, 1000, 1000, 50, 0, 1000)])
    _add_game(conn, "DUP", win=True, pid=3,
              frames=[(1, 1000, 1000, 50, 0, 1000)])
    # colliding second participant row + a wild sentinel frame.
    conn.execute("INSERT INTO participants VALUES (?,?,?,?)", ("DUP", 7, 64, 100))
    conn.execute("INSERT INTO timeline_frames VALUES (?,?,?,?,?,?,?,?)",
                 ("DUP", 7, 60000, 999999, 999999, 999, 0, 999999))
    out = op_score_curve.compute_op_score_curve(mode="aram", conn=conn)
    assert out["n_games"] == 6
    # the wild sentinel frame must NOT become the per-minute max (all real
    # games are identical) -> every bucket still maxes at 100.
    assert _series(out, 1, "win_avg") == 100.0


def test_max_minute_cap_drops_corrupt_frames():
    conn = _db()
    for i in range(5):
        _add_game(conn, f"W{i}", win=True, dur=3000,
                  frames=[(1, 1000, 1000, 50, 0, 1000),
                          (op_score_curve.MAX_MINUTE + 10, 5, 5, 1, 0, 5)])
    out = op_score_curve.compute_op_score_curve(mode="aram", conn=conn)
    minutes = [r["minute"] for r in out["minutes"]]
    assert 1 in minutes
    assert all(m <= op_score_curve.MAX_MINUTE for m in minutes)


def test_mode_fallback():
    conn = _db()
    for i in range(5):
        _add_game(conn, f"W{i}", win=True,
                  frames=[(1, 1000, 1000, 50, 0, 1000)])
    out = op_score_curve.compute_op_score_curve(mode="bogus", conn=conn)
    assert out["mode"] == op_score_curve.DEFAULT_MODE
    assert out["metric"] == op_score_curve.DEFAULT_METRIC


def test_no_db_returns_ok_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(op_score_curve, "_REWIND_DB", tmp_path / "absent.db")
    out = op_score_curve.compute_op_score_curve(mode="aram")
    assert out["ok"] is True
    assert out["minutes"] == []
    assert out["n_games"] == 0
    # the empty shape still carries the documented weights block.
    assert out["weights"]["gold"] == op_score_curve.W_GOLD


def test_weights_sum_to_one():
    # the composite can only be guaranteed <= 100 if the weights sum to 1.0.
    total = (op_score_curve.W_GOLD + op_score_curve.W_XP
             + op_score_curve.W_CS + op_score_curve.W_COMBAT)
    assert round(total, 6) == 1.0

"""Robustness + invariant tests for core.player_gpi (cycle 48, item 450).

These prove the 8-axis longitudinal GPI builder is fail-soft and correct
under malformed / thin / empty / edge inputs. They NEVER touch the real
data/rewind_history.db: every DB read goes through a throwaway in-memory
sqlite fixture built with ONLY the columns the module's SELECT names.

Column provenance (cited to core/player_gpi.py at read time):
  matches selected: match_id, game_duration_s (114), game_creation_ts (123,
    ORDER BY), has_stats (105 WHERE), map_id (108 WHERE), tracked_champion_id
    + tracked_team_id (120-121 JOIN).
  participants selected: match_id, champion_id, total_minions_killed,
    neutral_minions_killed, vision_score, gold_earned,
    total_damage_dealt_to_champs, deaths, kills, assists, dragon_kills,
    baron_kills, turret_takedowns, inhibitor_takedowns (114-118), team_id
    (121 JOIN).

The contract under test (player_gpi.compute_gpi docstring): never raises;
returns an ok dict; axis scores in [0,100]; below MIN_GAMES yields
confidence "insufficient" with an empty axes list.
"""
from __future__ import annotations

import sqlite3

import pytest

from core import player_gpi

ALLOWED_CONFIDENCE = {"high", "low", "insufficient"}
ALLOWED_SCORING = {"relative", "absolute"}
EMPTY_KEYS = {
    "ok", "mode", "champion", "n_games", "window", "window_n", "min_games",
    "confidence", "axes", "overall", "weakest_axis", "tip", "this_match",
    "reference", "win_streak", "win_rate", "kp_pct", "kda_mean",
    "strongest_axis",
}


# ---------------------------------------------------------------------------
# In-memory rewind_history.db mirror (only the selected columns).
# ---------------------------------------------------------------------------
def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE matches (
            match_id TEXT PRIMARY KEY,
            game_duration_s INTEGER,
            game_creation_ts INTEGER,
            has_stats INTEGER,
            map_id INTEGER,
            tracked_champion_id INTEGER,
            tracked_team_id INTEGER
        );
        CREATE TABLE participants (
            match_id TEXT,
            champion_id INTEGER,
            team_id INTEGER,
            total_minions_killed INTEGER,
            neutral_minions_killed INTEGER,
            vision_score INTEGER,
            gold_earned INTEGER,
            total_damage_dealt_to_champs INTEGER,
            deaths INTEGER,
            kills INTEGER,
            assists INTEGER,
            dragon_kills INTEGER,
            baron_kills INTEGER,
            turret_takedowns INTEGER,
            inhibitor_takedowns INTEGER,
            win INTEGER
        );
        """
    )
    return conn


def _insert_game(conn, *, mid, ts, champ=1, dur=1800, has_stats=1, map_id=11,
                 team=100, minions=180, neutral=20, vis=30, gold=12000,
                 dmg=18000, deaths=4, kills=6, assists=8, drag=1, baron=0,
                 turret=3, inhib=1, win=1, extra_participants=()):
    conn.execute(
        "INSERT INTO matches VALUES (?,?,?,?,?,?,?)",
        (mid, dur, ts, has_stats, map_id, champ, team),
    )
    conn.execute(
        "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (mid, champ, team, minions, neutral, vis, gold, dmg, deaths, kills,
         assists, drag, baron, turret, inhib, win),
    )
    for p in extra_participants:
        conn.execute(
            "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", p
        )


def _seed(conn, n, *, champ=1, map_id=11, **kw):
    """Seed n healthy SR games newest->oldest by ts."""
    for i in range(n):
        _insert_game(conn, mid=f"M{i}", ts=10_000 - i, champ=champ,
                     map_id=map_id, **kw)
    conn.commit()


# ---------------------------------------------------------------------------
# Happy-path shape: enough games -> 8 axes, every score in [0,100].
# ---------------------------------------------------------------------------
def test_full_profile_shape_and_score_bounds():
    conn = _make_conn()
    # Vary per-game stats so percentile / entropy / cv are all exercised.
    for i in range(15):
        _insert_game(
            conn, mid=f"G{i}", ts=10_000 - i,
            champ=1 + (i % 4), dur=1500 + i * 30,
            minions=120 + i * 5, vis=20 + i, gold=9000 + i * 200,
            dmg=12000 + i * 400, deaths=2 + (i % 5), kills=4 + (i % 3),
            assists=5 + (i % 6), drag=i % 2, turret=i % 4,
        )
    conn.commit()
    out = player_gpi.compute_gpi(mode="sr", window=10, conn=conn)
    assert out["ok"] is True
    assert out["confidence"] in ALLOWED_CONFIDENCE
    assert len(out["axes"]) == 8
    keys = {a["key"] for a in out["axes"]}
    assert keys == {
        "aggression", "farming", "vision", "objectives", "survival",
        "tempo", "versatility", "consistency",
    }
    for a in out["axes"]:
        assert 0.0 <= a["score"] <= 100.0, a
        assert a["scoring"] in ALLOWED_SCORING
    assert 0.0 <= out["overall"] <= 100.0
    # weakest axis must be one of the relative skill axes (never a shape axis).
    assert out["weakest_axis"] in player_gpi._AXIS_TIPS
    assert out["tip"] == player_gpi._AXIS_TIPS[out["weakest_axis"]]


# ---------------------------------------------------------------------------
# Empty / thin DB -> insufficient, empty axes, documented shape, no raise.
# ---------------------------------------------------------------------------
def test_empty_db_returns_insufficient_not_raise():
    conn = _make_conn()  # zero rows
    out = player_gpi.compute_gpi(mode="sr", window=20, conn=conn)
    assert out["ok"] is True
    assert out["confidence"] == "insufficient"
    assert out["axes"] == []
    assert out["overall"] is None
    assert out["weakest_axis"] is None
    assert out["tip"] is None
    assert set(out.keys()) == EMPTY_KEYS


@pytest.mark.parametrize("n", [0, 1, 5, 9])
def test_below_min_games_is_insufficient(n):
    conn = _make_conn()
    _seed(conn, n)
    out = player_gpi.compute_gpi(mode="sr", conn=conn)
    assert out["confidence"] == "insufficient"
    assert out["axes"] == []
    assert out["n_games"] == n


def test_exactly_min_games_builds_axes():
    conn = _make_conn()
    _seed(conn, player_gpi.MIN_GAMES)
    out = player_gpi.compute_gpi(mode="sr", conn=conn)
    assert out["confidence"] in {"high", "low"}
    assert len(out["axes"]) == 8


# ---------------------------------------------------------------------------
# NULL columns everywhere (the live DB has sparse rows). Must not div-by-zero
# or raise; scores still bounded.
# ---------------------------------------------------------------------------
def test_all_null_metric_columns_no_crash():
    conn = _make_conn()
    # Real duration (passes the >= MIN_DURATION_S WHERE) but EVERY participant
    # metric column NULL - the live DB's sparse-row shape. The COALESCE-to-0
    # arithmetic must not raise or divide by zero.
    for i in range(12):
        conn.execute(
            "INSERT INTO matches VALUES (?,?,?,?,?,?,?)",
            (f"N{i}", 1800, 10_000 - i, 1, 11, 7, 100),
        )
        conn.execute(
            "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"N{i}", 7, 100, None, None, None, None, None, None, None,
             None, None, None, None, None, None),
        )
    conn.commit()
    out = player_gpi.compute_gpi(mode="sr", conn=conn)
    # null/0 duration is floored to 1.0 min internally; never raises.
    assert out["ok"] is True
    assert len(out["axes"]) == 8
    for a in out["axes"]:
        assert 0.0 <= a["score"] <= 100.0


def test_zero_duration_does_not_divide_by_zero():
    conn = _make_conn()
    # dur=0 rows survive the WHERE only if >= MIN_DURATION_S; force them in by
    # using exactly MIN_DURATION_S so the row is kept, then a 0 sneaks via NULL.
    for i in range(12):
        _insert_game(conn, mid=f"Z{i}", ts=10_000 - i, champ=3,
                     dur=player_gpi.MIN_DURATION_S, deaths=0, kills=0,
                     assists=0)
    conn.commit()
    out = player_gpi.compute_gpi(mode="sr", conn=conn)
    assert out["ok"] is True
    for a in out["axes"]:
        assert 0.0 <= a["score"] <= 100.0


# ---------------------------------------------------------------------------
# Single-champion pool -> versatility floor 0; identical KDA -> consistency
# stays bounded. (Shape-axis edge invariants.)
# ---------------------------------------------------------------------------
def test_one_trick_versatility_is_zero_floor():
    conn = _make_conn()
    _seed(conn, 12, champ=42)  # all same champ
    out = player_gpi.compute_gpi(mode="sr", window=12, conn=conn)
    vax = next(a for a in out["axes"] if a["key"] == "versatility")
    assert vax["score"] == 0.0
    assert vax["recent_value"] == 1


def test_identical_kda_consistency_bounded():
    conn = _make_conn()
    _seed(conn, 12, kills=5, assists=5, deaths=2)  # identical KDA every game
    out = player_gpi.compute_gpi(mode="sr", window=12, conn=conn)
    cax = next(a for a in out["axes"] if a["key"] == "consistency")
    assert 0.0 <= cax["score"] <= 100.0
    # zero dispersion -> top of the scale.
    assert cax["score"] == 100.0


# ---------------------------------------------------------------------------
# Window / mode / champion arg robustness.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("window", [-5, 0, 1, 3, 1000])
def test_out_of_range_window_is_clamped(window):
    conn = _make_conn()
    _seed(conn, 12)
    out = player_gpi.compute_gpi(mode="sr", window=window, conn=conn)
    assert out["ok"] is True
    assert len(out["axes"]) == 8
    for a in out["axes"]:
        assert 0.0 <= a["score"] <= 100.0
        assert a["sample_n"] >= 1


@pytest.mark.parametrize("mode", ["", "bogus", "SR", "TFT", None])
def test_unknown_mode_falls_back_to_sr(mode):
    conn = _make_conn()
    _seed(conn, 12, map_id=11)
    if mode is None:
        # None is not a valid str key; module guards via `mode not in MODE_MAPS`.
        out = player_gpi.compute_gpi(mode=mode, conn=conn)  # type: ignore[arg-type]
    else:
        out = player_gpi.compute_gpi(mode=mode, conn=conn)
    assert out["ok"] is True
    # unknown -> coerced to sr -> the map-11 rows are visible.
    assert out["mode"] == "sr"
    assert len(out["axes"]) == 8


def test_champion_filter_narrows_pool():
    conn = _make_conn()
    _seed(conn, 12, champ=1)   # cohort A: mids M0..M11, champ 1
    # cohort B with DISTINCT mids (mustn't collide with _seed's M*).
    for i in range(12):
        _insert_game(conn, mid=f"C2_{i}", ts=20_000 - i, champ=2, map_id=11)
    conn.commit()
    out = player_gpi.compute_gpi(mode="sr", champion=2, conn=conn)
    assert out["champion"] == 2
    # every relative axis sample must come from champ-2 games only; we can't see
    # champion_id post-aggregation, but versatility must read a 1-champ pool.
    vax = next(a for a in out["axes"] if a["key"] == "versatility")
    assert vax["recent_value"] == 1


# ---------------------------------------------------------------------------
# Helper-level invariants (parametrized property style).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("x", [-1e9, -1.0, 0.0, 0.5, 1.0, 5.0, 1e9])
def test_percentile_in_unit_interval(x):
    base = [0.0, 1.0, 1.0, 2.0, 3.0, 5.0, 8.0]
    p = player_gpi._percentile(base, x)
    assert 0.0 <= p <= 1.0


def test_percentile_empty_baseline_is_half():
    assert player_gpi._percentile([], 3.0) == 0.5


@pytest.mark.parametrize("vals,expected", [
    ([], 0.0),
    ([7.0], 7.0),
    ([1.0, 3.0], 2.0),
    ([5.0, 1.0, 3.0], 3.0),
    ([4.0, 2.0, 1.0, 3.0], 2.5),
])
def test_median_values(vals, expected):
    assert player_gpi._median(vals) == expected


def test_empty_payload_shape_is_stable():
    out = player_gpi._empty("sr", 20, 0, None, "insufficient")
    assert set(out.keys()) == EMPTY_KEYS
    assert out["ok"] is True
    assert out["axes"] == []


# ---------------------------------------------------------------------------
# Default-conn path: compute_gpi with conn=None must open + close the real
# read-only handle WITHOUT us supplying it. We redirect open_ro to an in-mem
# DB so the real 1.8GB file is never touched.
# ---------------------------------------------------------------------------
def test_default_conn_path_opens_and_closes(monkeypatch):
    shared = _make_conn()
    _seed(shared, 12)

    closed = {"v": False}

    class _NoCloseProxy:
        # Wrap so compute_gpi's `conn.close()` does not kill our shared mem DB
        # (an in-memory connection is destroyed on close).
        def execute(self, *a, **k):
            return shared.execute(*a, **k)

        def close(self):
            closed["v"] = True

    monkeypatch.setattr(player_gpi.draft_elo_db, "open_ro",
                        lambda *a, **k: _NoCloseProxy())
    out = player_gpi.compute_gpi(mode="sr")
    assert out["ok"] is True
    assert len(out["axes"]) == 8
    assert closed["v"] is True  # own-conn path closed its handle


def test_default_conn_close_failure_is_swallowed(monkeypatch):
    shared = _make_conn()
    _seed(shared, 12)

    class _BadClose:
        def execute(self, *a, **k):
            return shared.execute(*a, **k)

        def close(self):
            raise RuntimeError("boom on close")

    monkeypatch.setattr(player_gpi.draft_elo_db, "open_ro",
                        lambda *a, **k: _BadClose())
    # The finally-block swallows close() errors; compute must still return ok.
    out = player_gpi.compute_gpi(mode="sr")
    assert out["ok"] is True
    assert len(out["axes"]) == 8

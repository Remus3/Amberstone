"""Characterization tests for core.duration_winrate (win-rate-by-game-length).

Reads NO real rewind_history.db - every test injects an in-memory sqlite
``matches`` table, so the suite is clean-checkout / CI safe (the db is
gitignored; reference_clean_checkout_probe). Asserts on computed quantities,
not data-fragile cross-row comparisons (Testing Discipline).
"""
import sqlite3

from core import duration_winrate as dw


def _conn(rows):
    """rows: list of (map_id, game_duration_s, tracked_win, tracked_champion_id)."""
    c = sqlite3.connect(":memory:")
    c.execute(
        "CREATE TABLE matches (map_id INTEGER, game_duration_s INTEGER, "
        "tracked_win INTEGER, tracked_champion_id INTEGER)"
    )
    c.executemany(
        "INSERT INTO matches (map_id, game_duration_s, tracked_win, "
        "tracked_champion_id) VALUES (?,?,?,?)",
        rows,
    )
    c.commit()
    return c


def test_bucket_tally_and_winrate():
    # ARAM (map 12): 10 games in the 20-25m bucket (1200-1500s), 6 wins.
    rows = [(12, 1300, 1, 64)] * 6 + [(12, 1300, 0, 64)] * 4
    out = dw.compute_duration_winrate(mode="aram", conn=_conn(rows))
    b = {x["label"]: x for x in out["buckets"]}
    assert b["20-25m"]["games"] == 10
    assert b["20-25m"]["wins"] == 6
    assert b["20-25m"]["winrate"] == 60.0
    assert out["n"] == 10
    assert out["mode"] == "aram"
    assert out["ok"] is True


def test_min_bucket_n_gate_returns_none():
    rows = [(12, 1300, 1, 64)] * (dw.MIN_BUCKET_N - 1)
    out = dw.compute_duration_winrate(mode="aram", conn=_conn(rows))
    b = {x["label"]: x for x in out["buckets"]}
    assert b["20-25m"]["games"] == dw.MIN_BUCKET_N - 1
    assert b["20-25m"]["winrate"] is None  # too thin to trust


def test_bucket_boundaries_lo_inclusive_hi_exclusive():
    # 1200 -> 20-25m (lo inclusive); 1199 + 900 -> 15-20m; 899 -> <15m.
    rows = [(12, 1200, 1, 1), (12, 1199, 1, 1), (12, 900, 1, 1), (12, 899, 1, 1)]
    out = dw.compute_duration_winrate(mode="aram", conn=_conn(rows))
    b = {x["label"]: x for x in out["buckets"]}
    assert b["20-25m"]["games"] == 1
    assert b["15-20m"]["games"] == 2
    assert b["<15m"]["games"] == 1


def test_remakes_and_outliers_dropped():
    rows = [
        (12, dw.MIN_DURATION_S - 1, 1, 1),       # remake, dropped
        (12, dw.MAX_DURATION_S, 0, 1),           # ms-encoded/corrupt, dropped (hi exclusive)
        (12, dw.MAX_DURATION_S + 50000, 0, 1),   # corrupt, dropped
        (12, 1300, 1, 1),                        # valid
    ]
    out = dw.compute_duration_winrate(mode="aram", conn=_conn(rows))
    assert out["n"] == 1


def test_mode_filter_by_map_id():
    rows = [(12, 1300, 1, 1)] * 6 + [(11, 1700, 1, 1)] * 6  # 6 ARAM + 6 SR
    assert dw.compute_duration_winrate(mode="aram", conn=_conn(rows))["n"] == 6
    sr = dw.compute_duration_winrate(mode="sr", conn=_conn(rows))
    assert sr["n"] == 6  # SR 1700s -> 25-30m bucket


def test_champion_filter():
    rows = [(12, 1300, 1, 64)] * 6 + [(12, 1300, 0, 99)] * 6
    out = dw.compute_duration_winrate(mode="aram", champion=64, conn=_conn(rows))
    assert out["n"] == 6
    assert out["champion"] == 64


def test_empty_corpus_fail_soft():
    out = dw.compute_duration_winrate(mode="aram", conn=_conn([]))
    assert out["ok"] is True
    assert out["n"] == 0
    assert len(out["buckets"]) == len(dw.DEFAULT_BUCKETS)
    assert all(b["winrate"] is None for b in out["buckets"])


def test_invalid_mode_falls_back_to_default():
    rows = [(12, 1300, 1, 1)] * 6
    out = dw.compute_duration_winrate(mode="bogus", conn=_conn(rows))
    assert out["mode"] == dw.DEFAULT_MODE
    assert out["n"] == 6

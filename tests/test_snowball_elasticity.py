"""Characterization tests for core.snowball_elasticity.

Personal win-rate bucketed by TEAM gold differential at ~10min / ~20min
checkpoints, over the local rewind_history.db timeline. Reads NO real db -
every test injects an in-memory sqlite (matches + participants +
timeline_frames), so the suite is clean-checkout / CI safe (the db is
gitignored; reference_clean_checkout_probe). Asserts on computed quantities,
not data-fragile cross-row comparisons (Testing Discipline).
"""
import sqlite3

from core import smoothed_rates
from core import snowball_elasticity as se


def _conn(matches, participants, frames):
    """matches:      (match_id, map_id, has_timeline, tracked_team_id, tracked_win)
    participants:    (match_id, participant_id, team_id)
    frames:          (match_id, timestamp_ms, participant_id, total_gold)
    """
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE matches (match_id TEXT, map_id INTEGER, "
              "has_timeline INTEGER, tracked_team_id INTEGER, tracked_win INTEGER)")
    c.execute("CREATE TABLE participants (match_id TEXT, participant_id INTEGER, "
              "team_id INTEGER)")
    c.execute("CREATE TABLE timeline_frames (match_id TEXT, timestamp_ms INTEGER, "
              "participant_id INTEGER, total_gold INTEGER)")
    c.executemany("INSERT INTO matches VALUES (?,?,?,?,?)", matches)
    c.executemany("INSERT INTO participants VALUES (?,?,?)", participants)
    c.executemany("INSERT INTO timeline_frames VALUES (?,?,?,?)", frames)
    c.commit()
    return c


def _match(mid, win, diff_by_ts, tracked_team=100, map_id=11, has_timeline=1):
    """Build one SR match where the tracked team's gold lead is exactly
    ``diff`` (tracked_team_gold - enemy_team_gold) at each frame timestamp.
    Team 100 = participant ids 1-5, team 200 = ids 6-10. Enemy team totals
    5000; tracked team totals 5000+diff, so the differential is exactly diff.
    """
    enemy_team = 200 if tracked_team == 100 else 100
    parts = ([(mid, pid, 100) for pid in range(1, 6)]
             + [(mid, pid, 200) for pid in range(6, 11)])
    frames = []
    for ts, diff in diff_by_ts.items():
        tracked_each = (5000 + diff) // 5
        enemy_each = 5000 // 5
        for pid in range(1, 11):
            team = 100 if pid <= 5 else 200
            g = tracked_each if team == tracked_team else enemy_each
            frames.append((mid, ts, pid, g))
    m = (mid, map_id, has_timeline, tracked_team, win)
    return [m], parts, frames


def _corpus(matchspecs):
    ms, ps, fs = [], [], []
    for spec in matchspecs:
        m, p, f = _match(*spec[0], **spec[1])
        ms += m
        ps += p
        fs += f
    return _conn(ms, ps, fs)


def _cp(out, key):
    return next(c for c in out["checkpoints"] if c["key"] == key)


def _bkt(cp, label):
    return {b["label"]: b for b in cp["buckets"]}[label]


def test_bucket_by_gold_diff_and_winrate():
    # 10 SR games all +3000 gold at 10min (ahead_big): 6 wins, 4 losses.
    specs = ([((f"g{i}", 1, {600_000: 3000}), {}) for i in range(6)]
             + [((f"g{i}", 0, {600_000: 3000}), {}) for i in range(6, 10)])
    out = se.compute_snowball_elasticity(conn=_corpus(specs))
    cp = _cp(out, "10min")
    b = _bkt(cp, "ahead_big")
    assert b["games"] == 10
    assert b["wins"] == 6
    assert b["winrate"] == 60.0
    assert out["ok"] is True
    assert out["mode"] == "sr"


def test_smoothed_rate_matches_laplace():
    specs = ([((f"g{i}", 1, {600_000: 3000}), {}) for i in range(6)]
             + [((f"g{i}", 0, {600_000: 3000}), {}) for i in range(6, 10)])
    out = se.compute_snowball_elasticity(conn=_corpus(specs))
    b = _bkt(_cp(out, "10min"), "ahead_big")
    expected = round(100.0 * smoothed_rates.laplace_rate(6, 10), 1)
    assert b["winrate_smoothed"] == expected  # (6+1)/(10+2) = 58.3


def test_min_bucket_n_gate_raw_none_smoothed_present():
    # 4 games in one bucket: below MIN_BUCKET_N -> raw None, smoothed present.
    specs = [((f"g{i}", 1, {600_000: 3000}), {}) for i in range(se.MIN_BUCKET_N - 1)]
    out = se.compute_snowball_elasticity(conn=_corpus(specs))
    b = _bkt(_cp(out, "10min"), "ahead_big")
    assert b["games"] == se.MIN_BUCKET_N - 1
    assert b["winrate"] is None
    assert b["winrate_smoothed"] is not None


def test_signed_bucket_boundaries():
    # even (-800..800), ahead (800..2500), behind (-2500..-800).
    specs = [
        (("even0", 1, {600_000: 0}), {}),
        (("ahead0", 1, {600_000: 1500}), {}),
        (("behind0", 0, {600_000: -1500}), {}),
        (("behindbig", 0, {600_000: -4000}), {}),
    ]
    out = se.compute_snowball_elasticity(conn=_corpus(specs))
    cp = _cp(out, "10min")
    assert _bkt(cp, "even")["games"] == 1
    assert _bkt(cp, "ahead")["games"] == 1
    assert _bkt(cp, "behind")["games"] == 1
    assert _bkt(cp, "behind_big")["games"] == 1


def test_tracked_team_200_uses_correct_side():
    # tracked team is 200; diff builder makes tracked lead by 3000 -> ahead_big.
    specs = [((f"t200_{i}", 1, {600_000: 3000}), {"tracked_team": 200})
             for i in range(6)]
    out = se.compute_snowball_elasticity(conn=_corpus(specs))
    b = _bkt(_cp(out, "10min"), "ahead_big")
    assert b["games"] == 6
    assert b["wins"] == 6


def test_sr_only_excludes_aram():
    specs = ([((f"sr{i}", 1, {600_000: 3000}), {}) for i in range(6)]
             + [((f"aram{i}", 1, {600_000: 3000}), {"map_id": 12}) for i in range(6)])
    out = se.compute_snowball_elasticity(conn=_corpus(specs))
    assert _cp(out, "10min")["n"] == 6  # ARAM rows dropped


def test_checkpoint_tolerance_excludes_short_games():
    # only frame at 8min (480000ms): >90s from the 10min checkpoint -> not counted.
    specs = [((f"short{i}", 1, {480_000: 3000}), {}) for i in range(6)]
    out = se.compute_snowball_elasticity(conn=_corpus(specs))
    assert _cp(out, "10min")["n"] == 0


def test_twenty_min_checkpoint_independent():
    specs = [((f"g{i}", 1, {600_000: 3000, 1_200_000: -3000}), {}) for i in range(6)]
    out = se.compute_snowball_elasticity(conn=_corpus(specs))
    assert _bkt(_cp(out, "10min"), "ahead_big")["games"] == 6
    assert _bkt(_cp(out, "20min"), "behind_big")["games"] == 6


def test_empty_corpus_fail_soft():
    out = se.compute_snowball_elasticity(conn=_conn([], [], []))
    assert out["ok"] is True
    for cp in out["checkpoints"]:
        assert cp["n"] == 0
        assert len(cp["buckets"]) == len(se.DEFAULT_BUCKETS)
        assert all(b["winrate"] is None for b in cp["buckets"])

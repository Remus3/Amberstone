"""Tests for tools/replay_matchup_validate.py - the Haiku-flip validation gate.

All tests build a TINY temp SQLite db with the same table shape the harness reads
(subset of the real rewind_history.db columns) and stub ``compute_matchup`` with a
deterministic lambda - so nothing depends on the real 1.8GB db or the DS data
files. Covers: lane pairing on correct same-position opponents, even-band
exclusion, hand-checked agreement math, fail-soft on a malformed row, and the
JSON report key shape. Plus an ASCII-hygiene guard on the tool file.
"""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import replay_matchup_validate as rv  # noqa: E402


# --------------------------------------------------------------------------- helpers
@dataclass
class _FakeResult:
    """Minimal stand-in for MatchupResult - only net_swing is read."""

    net_swing: float


def _make_db(path: Path, matches, participants, frames) -> None:
    """Build a temp db with the columns the harness reads.

    matches: list of (match_id, game_mode, has_timeline, game_creation_ts)
    participants: list of (match_id, participant_id, team_id, champion_name, team_position)
    frames: list of (match_id, timestamp_ms, participant_id, total_gold)
    """
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE matches (match_id TEXT, game_mode TEXT, has_timeline INTEGER, "
        "game_creation_ts INTEGER)"
    )
    conn.execute(
        "CREATE TABLE participants (match_id TEXT, participant_id INTEGER, team_id INTEGER, "
        "champion_name TEXT, team_position TEXT)"
    )
    conn.execute(
        "CREATE TABLE timeline_frames (match_id TEXT, timestamp_ms INTEGER, "
        "participant_id INTEGER, total_gold REAL)"
    )
    conn.executemany("INSERT INTO matches VALUES (?,?,?,?)", matches)
    conn.executemany("INSERT INTO participants VALUES (?,?,?,?,?)", participants)
    conn.executemany("INSERT INTO timeline_frames VALUES (?,?,?,?)", frames)
    conn.commit()
    conn.close()


def _full_match(match_id, lanes_spec, ts_creation=1000):
    """Build (participants, frames) for a clean 5-lane SR match at a 10-min frame.

    lanes_spec: dict lane -> (champ_a, gold_a, champ_b, gold_b)
    Team 100 = participant ids 1..5, team 200 = ids 6..10, lane order = _LANES.
    """
    parts = []
    frames = []
    ts10 = 10 * 60 * 1000  # exact 10-min frame
    for i, lane in enumerate(rv._LANES):
        if lane not in lanes_spec:
            continue
        champ_a, gold_a, champ_b, gold_b = lanes_spec[lane]
        pid_a = i + 1  # 1..5
        pid_b = i + 6  # 6..10
        parts.append((match_id, pid_a, 100, champ_a, lane))
        parts.append((match_id, pid_b, 200, champ_b, lane))
        # one frame at t=0 and one at 10min so nearest-frame resolves cleanly
        frames.append((match_id, 0, pid_a, 500.0))
        frames.append((match_id, 0, pid_b, 500.0))
        frames.append((match_id, ts10, pid_a, gold_a))
        frames.append((match_id, ts10, pid_b, gold_b))
    return parts, frames


# ------------------------------------------------------------------- pairing tests
def test_lane_pairing_picks_correct_same_position_opponents(tmp_path):
    db = tmp_path / "t.db"
    parts, frames = _full_match(
        "M1",
        {
            "TOP": ("Garen", 4000, "Darius", 3000),
            "MIDDLE": ("Annie", 3500, "Ahri", 3600),
        },
    )
    _make_db(db, [("M1", "CLASSIC", 1, 1000)], parts, frames)
    conn = sqlite3.connect(str(db))
    pairs = rv.extract_lane_pairs(conn, "M1", gold_frame_min=10)
    conn.close()

    by_lane = {p.lane: p for p in pairs}
    assert set(by_lane) == {"TOP", "MIDDLE"}
    top = by_lane["TOP"]
    assert top.champ_a == "Garen" and top.champ_b == "Darius"
    assert top.gold_a == 4000 and top.gold_b == 3000
    mid = by_lane["MIDDLE"]
    assert mid.champ_a == "Annie" and mid.champ_b == "Ahri"


def test_lane_skipped_when_one_side_missing(tmp_path):
    db = tmp_path / "t.db"
    # TOP has only a team-100 entry (no opponent) -> must be skipped.
    parts = [("M1", 1, 100, "Garen", "TOP")]
    frames = [("M1", 0, 1, 500.0), ("M1", 600000, 1, 4000.0)]
    _make_db(db, [("M1", "CLASSIC", 1, 1000)], parts, frames)
    conn = sqlite3.connect(str(db))
    pairs = rv.extract_lane_pairs(conn, "M1", gold_frame_min=10)
    conn.close()
    assert pairs == []


def test_select_sr_match_ids_filters_mode_and_timeline_and_limit(tmp_path):
    db = tmp_path / "t.db"
    matches = [
        ("SR1", "CLASSIC", 1, 300),
        ("SR2", "CLASSIC", 1, 200),
        ("SR3", "CLASSIC", 1, 100),
        ("ARAM1", "ARAM", 1, 999),  # wrong mode
        ("NOTL", "CLASSIC", 0, 999),  # no timeline
    ]
    _make_db(db, matches, [], [])
    conn = sqlite3.connect(str(db))
    # newest-first by game_creation_ts; limit 2 keeps SR1, SR2
    ids = rv.select_sr_match_ids(conn, limit=2)
    assert ids == ["SR1", "SR2"]
    # limit 0 = all SR-with-timeline
    ids_all = rv.select_sr_match_ids(conn, limit=0)
    conn.close()
    assert set(ids_all) == {"SR1", "SR2", "SR3"}


# --------------------------------------------------------------- score_pair tests
def test_even_band_exclusion_works():
    pair = rv.LanePair("M", "MIDDLE", "Annie", "Ahri", 4000, 3000)
    stub = lambda *a, **k: _FakeResult(net_swing=0.005)  # below default 0.02 band
    status, agreed = rv.score_pair(pair, 6, snapshot=None, matchup_fn=stub)
    assert status == "even"
    assert agreed is False


def test_decisive_agreement_when_engine_and_gold_agree():
    # engine favors A (net_swing>0); gold favors A (4000>3000) -> agreed True
    pair = rv.LanePair("M", "TOP", "Garen", "Darius", 4000, 3000)
    stub = lambda *a, **k: _FakeResult(net_swing=0.30)
    status, agreed = rv.score_pair(pair, 6, snapshot=None, matchup_fn=stub)
    assert status == "decisive"
    assert agreed is True


def test_decisive_disagreement_when_engine_and_gold_disagree():
    # engine favors B (net_swing<0); gold favors A (4000>3000) -> disagree
    pair = rv.LanePair("M", "TOP", "Garen", "Darius", 4000, 3000)
    stub = lambda *a, **k: _FakeResult(net_swing=-0.30)
    status, agreed = rv.score_pair(pair, 6, snapshot=None, matchup_fn=stub)
    assert status == "decisive"
    assert agreed is False


def test_gold_tie_excluded():
    pair = rv.LanePair("M", "TOP", "Garen", "Darius", 3000, 3000)
    stub = lambda *a, **k: _FakeResult(net_swing=0.30)
    status, agreed = rv.score_pair(pair, 6, snapshot=None, matchup_fn=stub)
    assert status == "gold_tie"


def test_engine_none_excluded():
    pair = rv.LanePair("M", "TOP", "Garen", "Darius", 4000, 3000)
    stub = lambda *a, **k: None
    status, agreed = rv.score_pair(pair, 6, snapshot=None, matchup_fn=stub)
    assert status == "engine_none"


def test_engine_exception_is_failsoft_engine_none():
    pair = rv.LanePair("M", "TOP", "Garen", "Darius", 4000, 3000)

    def boom(*a, **k):
        raise RuntimeError("boom")

    status, agreed = rv.score_pair(pair, 6, snapshot=None, matchup_fn=boom)
    assert status == "engine_none"
    assert agreed is False


# ------------------------------------------------------------- agreement math case
def test_agreement_math_two_of_three_is_0667(tmp_path):
    db = tmp_path / "t.db"
    # 3 lanes; engine favors A on all 3 (net_swing>0). Gold favors A on TOP+MID
    # but B on BOTTOM -> 2 of 3 agree -> agreement 0.667.
    parts, frames = _full_match(
        "M1",
        {
            "TOP": ("Garen", 4000, "Darius", 3000),  # gold A -> agree
            "MIDDLE": ("Annie", 4000, "Ahri", 3000),  # gold A -> agree
            "BOTTOM": ("Jinx", 2000, "Caitlyn", 5000),  # gold B -> disagree
        },
    )
    _make_db(db, [("M1", "CLASSIC", 1, 1000)], parts, frames)

    stub = lambda *a, **k: _FakeResult(net_swing=0.25)  # always favors A
    report = rv.run_validation(
        db_path=db,
        levels=[6],
        limit=0,
        gold_frame_min=10,
        snapshot=None,
        matchup_fn=stub,
    )
    lv = report["levels"][0]
    assert lv["level"] == 6
    assert lv["n_decisive"] == 3
    assert lv["n_agree"] == 2
    assert abs(lv["agreement"] - (2.0 / 3.0)) < 1e-9
    # per-role: TOP + MIDDLE agree, BOTTOM disagrees
    assert lv["per_role"]["TOP"]["agreement"] == 1.0
    assert lv["per_role"]["BOTTOM"]["agreement"] == 0.0


def test_failsoft_skips_malformed_participant_row(tmp_path):
    db = tmp_path / "t.db"
    parts, frames = _full_match(
        "M1",
        {"TOP": ("Garen", 4000, "Darius", 3000)},
    )
    # inject a malformed participant row: NULL champion + NULL position
    parts.append(("M1", 11, 100, None, None))
    _make_db(db, [("M1", "CLASSIC", 1, 1000)], parts, frames)

    stub = lambda *a, **k: _FakeResult(net_swing=0.25)
    report = rv.run_validation(
        db_path=db, levels=[6], limit=0, gold_frame_min=10, snapshot=None, matchup_fn=stub
    )
    lv = report["levels"][0]
    # the malformed row is silently skipped; the clean TOP pair still scores
    assert lv["n_decisive"] == 1
    assert lv["n_agree"] == 1


def test_report_has_expected_keys(tmp_path):
    db = tmp_path / "t.db"
    parts, frames = _full_match("M1", {"TOP": ("Garen", 4000, "Darius", 3000)})
    _make_db(db, [("M1", "CLASSIC", 1, 1000)], parts, frames)
    stub = lambda *a, **k: _FakeResult(net_swing=0.25)
    report = rv.run_validation(
        db_path=db, levels=[6, 9], limit=0, gold_frame_min=10, snapshot=None, matchup_fn=stub
    )
    for key in (
        "generated_at",
        "db",
        "game_mode",
        "gold_frame_min",
        "even_band",
        "limit",
        "matches_selected",
        "matches_used",
        "matches_skipped",
        "pairs_total",
        "levels",
        "interpretation",
    ):
        assert key in report, f"missing top-level key {key}"
    assert len(report["levels"]) == 2
    lv = report["levels"][0]
    for key in ("level", "n_decisive", "n_agree", "agreement", "wilson_95_lo", "wilson_95_hi", "excluded", "per_role"):
        assert key in lv, f"missing level key {key}"
    for key in ("even_band", "gold_tie", "engine_none"):
        assert key in lv["excluded"]


def test_multi_level_independent_scoring(tmp_path):
    db = tmp_path / "t.db"
    parts, frames = _full_match("M1", {"TOP": ("Garen", 4000, "Darius", 3000)})
    _make_db(db, [("M1", "CLASSIC", 1, 1000)], parts, frames)

    # net_swing depends on the level arg so the two levels diverge.
    def by_level(snapshot, a, b, *, level_a, level_b, mode):
        return _FakeResult(net_swing=0.30 if level_a == 6 else -0.30)

    report = rv.run_validation(
        db_path=db, levels=[6, 9], limit=0, gold_frame_min=10, snapshot=None, matchup_fn=by_level
    )
    l6 = next(lv for lv in report["levels"] if lv["level"] == 6)
    l9 = next(lv for lv in report["levels"] if lv["level"] == 9)
    assert l6["agreement"] == 1.0  # favors A, gold A -> agree
    assert l9["agreement"] == 0.0  # favors B, gold A -> disagree


# -------------------------------------------------------------------- wilson math
def test_wilson_interval_basic_bounds():
    lo, hi = rv.wilson_interval(0, 0)
    assert lo is None and hi is None
    lo, hi = rv.wilson_interval(50, 100)
    assert 0.0 <= lo < 0.5 < hi <= 1.0  # interval brackets the 0.5 point estimate


# ----------------------------------------------------------------------- ascii guard
def test_tool_file_is_ascii_only():
    tool = _ROOT / "tools" / "replay_matchup_validate.py"
    data = tool.read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(data) if b > 0x7F]
    assert not non_ascii, f"non-ASCII bytes in tool file at offsets {non_ascii[:5]}"

"""Tests for tools/replay_laning_verdict_validate.py (the HZ-A laning-verdict gate).

The scoring + orchestration are exercised with an INJECTED ``verdict_fn`` and a
throwaway in-memory sqlite fixture that mirrors only the columns the reused
``replay_matchup_validate`` readers touch - so the suite never loads the real
1.8GB ``data/rewind_history.db`` or the shipped HZ-A tables.

ASCII only.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_TOOLS = _ROOT / "tools"
for _p in (str(_ROOT), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_mod():
    """Import the tool module by path (tools/ is not a package)."""
    path = _TOOLS / "replay_laning_verdict_validate.py"
    spec = importlib.util.spec_from_file_location("replay_laning_verdict_validate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load_mod()


# ------------------------------------------------------------------- favored_side
@pytest.mark.parametrize(
    "verdict,swing,expected",
    [
        ("all_in", 0.0, True),       # action verdict wins over the (zero) swing
        ("trade", -0.9, True),       # action authoritative even against swing sign
        ("back_off", 0.9, False),    # back_off -> champ_a yields, b favored
        ("even", 0.5, None),         # even -> excluded regardless of swing
        ("even", 0.001, None),       # below dead-band -> excluded
        (None, 0.5, True),           # unlabeled cell -> swing sign decides
        (None, -0.5, False),
        (None, 0.001, None),         # unlabeled + below dead-band -> excluded
        (None, "x", None),           # non-numeric swing -> excluded
    ],
)
def test_favored_side(verdict, swing, expected):
    assert MOD.favored_side(verdict, swing, MOD._EVEN_BAND) is expected


# ------------------------------------------------------------------------ scoring
def _pair(champ_a="A", champ_b="B", gold_a=1000.0, gold_b=900.0, pid_a=1, pid_b=6):
    return MOD.LanePair(
        match_id="M1", lane="MIDDLE", champ_a=champ_a, champ_b=champ_b,
        gold_a=gold_a, gold_b=gold_b, pid_a=pid_a, pid_b=pid_b,
    )


def test_score_pair_gold_uncovered():
    vf = lambda a, b, lvl: (None, None)
    status, agreed, verdict = MOD.score_pair_gold(_pair(), 6, vf)
    assert status == "uncovered" and agreed is False and verdict is None


def test_score_pair_gold_decisive_agree():
    # all_in favors A; A has higher gold -> agree.
    vf = lambda a, b, lvl: ("all_in", 0.3)
    status, agreed, verdict = MOD.score_pair_gold(_pair(gold_a=1200, gold_b=800), 6, vf)
    assert status == "decisive" and agreed is True and verdict == "all_in"


def test_score_pair_gold_decisive_disagree():
    # back_off favors B; A has higher gold -> disagree.
    vf = lambda a, b, lvl: ("back_off", -0.3)
    status, agreed, _ = MOD.score_pair_gold(_pair(gold_a=1200, gold_b=800), 6, vf)
    assert status == "decisive" and agreed is False


def test_score_pair_gold_tie_excluded():
    vf = lambda a, b, lvl: ("trade", 0.3)
    status, agreed, _ = MOD.score_pair_gold(_pair(gold_a=1000, gold_b=1000), 6, vf)
    assert status == "gold_tie" and agreed is False


def test_score_pair_gold_even_excluded():
    vf = lambda a, b, lvl: ("even", 0.0)
    status, _, _ = MOD.score_pair_gold(_pair(), 6, vf)
    assert status == "even"


def test_score_pair_duel_no_duel_and_tie():
    vf = lambda a, b, lvl: ("trade", 0.3)
    assert MOD.score_pair_duel(_pair(), 6, vf, 0, 0)[0] == "no_duel"
    assert MOD.score_pair_duel(_pair(), 6, vf, 2, 2)[0] == "kill_tie"


def test_score_pair_duel_decisive():
    # trade favors A; A killed B more -> agree.
    vf = lambda a, b, lvl: ("trade", 0.3)
    status, agreed, verdict = MOD.score_pair_duel(_pair(), 6, vf, 2, 0)
    assert status == "decisive" and agreed is True and verdict == "trade"


# --------------------------------------------------------------- action breakdown
def test_action_breakdown_only_action_verdicts():
    ab = MOD._ActionBreakdown()
    ab.record("all_in", True)
    ab.record("all_in", False)
    ab.record("trade", True)
    ab.record("even", True)   # ignored (not an action verdict)
    ab.record(None, True)     # ignored
    out = ab.to_dict()
    assert out["all_in"]["n"] == 2 and out["all_in"]["agree"] == 1
    assert out["trade"]["n"] == 1 and out["trade"]["agreement"] == 1.0
    assert out["back_off"]["n"] == 0 and out["back_off"]["agreement"] is None
    assert "even" not in out


# ------------------------------------------------------------------- fixture db
def _build_fixture_db(path: Path) -> None:
    """A 1-match SR fixture with two clean lanes + a 10min frame + one duel.

    Mirrors only the columns select_sr_match_ids / extract_lane_pairs /
    extract_kill_counts read (cited from tools/replay_matchup_validate.py).
    """
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE matches (match_id TEXT, game_mode TEXT, has_timeline INT, "
        "game_creation_ts INT)"
    )
    cur.execute(
        "CREATE TABLE participants (match_id TEXT, participant_id INT, team_id INT, "
        "champion_name TEXT, team_position TEXT)"
    )
    cur.execute(
        "CREATE TABLE timeline_frames (match_id TEXT, timestamp_ms INT, "
        "participant_id INT, total_gold REAL)"
    )
    cur.execute(
        "CREATE TABLE timeline_events (match_id TEXT, event_type TEXT, killer_id INT, "
        "victim_id INT, assisting_ids_json TEXT)"
    )
    cur.execute("INSERT INTO matches VALUES ('M1','CLASSIC',1,1000)")
    # TOP: pid1 (A, team100) vs pid6 (B, team200); MIDDLE: pid2 vs pid7.
    parts = [
        ("M1", 1, 100, "Garen", "TOP"),
        ("M1", 6, 200, "Darius", "TOP"),
        ("M1", 2, 100, "Ahri", "MIDDLE"),
        ("M1", 7, 200, "Zed", "MIDDLE"),
    ]
    cur.executemany("INSERT INTO participants VALUES (?,?,?,?,?)", parts)
    # 10-min frame (600000 ms): team100 ahead in both lanes.
    frame_ms = 600000
    golds = [(1, 5000.0), (6, 4000.0), (2, 5200.0), (7, 4100.0)]
    cur.executemany(
        "INSERT INTO timeline_frames VALUES ('M1', ?, ?, ?)",
        [(frame_ms, pid, g) for pid, g in golds],
    )
    # TOP duel: pid1 solo-kills pid6 once (assists empty).
    cur.execute(
        "INSERT INTO timeline_events VALUES ('M1','CHAMPION_KILL',1,6,'[]')"
    )
    conn.commit()
    conn.close()


def test_run_validation_end_to_end(tmp_path):
    db = tmp_path / "fix.db"
    _build_fixture_db(db)

    # Injected verdict: A (team100 champ) is always told to all_in, swing +0.3.
    # Team100 is ahead on gold in both lanes -> gold agreement should be 100%.
    def vf(champ_a, champ_b, level):
        return ("all_in", 0.3)

    report = MOD.run_validation(
        db_path=db, levels=[6], limit=0, gold_frame_min=10, verdict_fn=vf,
    )
    assert report["matches_used"] == 1
    assert report["pairs_total"] == 2
    g = report["levels_gold"][0]
    assert g["n_decisive"] == 2 and g["n_agree"] == 2 and g["agreement"] == 1.0
    # Only the TOP lane had a duel (pid1 killed pid6) -> 1 decisive duel, agree.
    d = report["levels_duel"][0]
    assert d["n_decisive"] == 1 and d["n_agree"] == 1
    ab = report["action_breakdown_gold"]
    assert ab["all_in"]["n"] == 2 and ab["all_in"]["agreement"] == 1.0
    assert report["coverage"]["uncovered"] == 0 and report["coverage"]["covered"] == 2


def test_run_validation_uncovered_counted(tmp_path):
    db = tmp_path / "fix.db"
    _build_fixture_db(db)
    report = MOD.run_validation(
        db_path=db, levels=[6], limit=0, gold_frame_min=10,
        verdict_fn=lambda a, b, lvl: (None, None),
    )
    # Every cell uncovered -> no decisive scoring, coverage all-uncovered.
    assert report["levels_gold"][0]["n_decisive"] == 0
    assert report["coverage"]["covered"] == 0
    assert report["coverage"]["uncovered"] == 2
    assert report["coverage"]["covered_fraction"] == 0.0


# ----------------------------------------------------------------------- helpers
def test_parse_levels_fail_soft():
    assert MOD._parse_levels("6, 11 ,x,") == [6, 11]
    assert MOD._parse_levels("") == list(MOD._DEFAULT_LEVELS)


def test_write_report_atomic(tmp_path):
    out = tmp_path / "sub" / "gate.json"
    MOD._write_report({"k": "v", "n": 1}, out)
    import json
    assert json.loads(out.read_text(encoding="utf-8")) == {"k": "v", "n": 1}
    # No leftover temp file.
    assert not (out.with_suffix(out.suffix + ".tmp")).exists()


def test_fmt_pct():
    assert MOD._fmt_pct(None).strip() == "n/a"
    assert MOD._fmt_pct(0.5).strip() == "50.0%"

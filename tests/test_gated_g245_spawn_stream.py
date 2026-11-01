"""Tests for tools/gated_g245_spawn_stream.py (G2-45 PREP, s144 lane gated c47).

Every input is hand-built (RM-906: no real game, match or player id). The tool
is a read-only grader; these tests pin its verdicts, that its R221 schedule is
the production ``wave_timing`` walked forward, that its R124 schedule is the
G2-39 tool's (``wave_callout``), and the source facts the doc row cites.
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard import _wave_timing
from tools import gated_g239_wave_clock as g239
from tools import gated_g245_spawn_stream as g245

ROOT = Path(__file__).resolve().parent.parent


def _state(gt, spawns, anchors=None):
    anchors = spawns if anchors is None else anchors
    return {"liveclient": {
        "game_time_s": gt,
        "minion_spawn_events": [{"spawn_at_s": s, "event_id": i} for i, s in enumerate(spawns)],
        "minion_events": [{"at_s": s} for s in anchors],
    }}


def _grade(*states):
    return g245.grade_stream([g245.read_snapshot(s) for s in states])


def test_not_in_game_when_liveclient_empty_or_missing():
    assert g245.read_snapshot({"liveclient": {}}) is None
    assert g245.read_snapshot({}) is None
    assert g245.read_snapshot([]) is None
    assert _grade({"liveclient": {}})["verdict"] == "NOT_IN_GAME"


def test_once_needs_the_wait_after_the_single_event():
    assert _grade(_state(65.0 + g245.ONCE_MIN_WAIT_S, [65.0]))["verdict"] == "ONCE"
    assert _grade(_state(65.0 + g245.ONCE_MIN_WAIT_S - 1, [65.0]))["verdict"] == "TOO_EARLY"
    assert _grade(_state(None, [65.0]))["verdict"] == "TOO_EARLY"


def test_once_wait_covers_two_later_waves_at_the_longest_interval():
    assert g245.ONCE_MIN_WAIT_S > 2 * _wave_timing._DEFAULT_WAVE_INTERVAL_S


def test_repeats_reports_distinct_times_and_median_gap():
    r = _grade(_state(130.0, [65.0, 95.0, 125.0]))
    assert r["verdict"] == "REPEATS"
    assert r["spawn_times"] == [65.0, 95.0, 125.0]
    assert r["median_gap_s"] == 30.0


def test_duplicate_reads_of_one_event_are_not_repeats():
    r = _grade(_state(200.0, [65.0, 65.0]))
    assert r["verdict"] == "ONCE"
    assert r["spawn_times"] == [65.0]


def test_extracts_disagree_voids_the_read():
    r = _grade(_state(200.0, [65.0, 95.0], anchors=[65.0]))
    assert r["verdict"] == "EXTRACTS_DISAGREE"


def test_no_event_only_after_the_first_wave_is_due():
    assert _grade(_state(g245.FIRST_WAVE_BY_S, []))["verdict"] == "NO_EVENT"
    assert _grade(_state(g245.FIRST_WAVE_BY_S - 1, []))["verdict"] == "TOO_EARLY"


def test_missing_extract_keys_are_not_read_as_no_event():
    r = _grade({"liveclient": {"game_time_s": 200.0}})
    assert r["verdict"] == "FIELDS_MISSING"


def test_newest_snapshot_decides_in_any_order_and_cumulative_is_reported():
    early = _state(70.0, [65.0])
    late = _state(160.0, [65.0, 95.0, 125.0, 155.0])
    r = _grade(late, early)
    assert r["verdict"] == "REPEATS" and r["game_time_s"] == 160.0
    assert r["cumulative"] is True
    reset = _grade(_state(70.0, [65.0]), _state(160.0, [155.0]))
    assert reset["cumulative"] is False


def test_timing_schedule_is_production_wave_timing_walked_forward():
    spawns = [65.0]
    cannons = g245.timing_cannons(spawns, until_s=1700.0)
    assert cannons[:3] == [125.0, 215.0, 305.0]
    events = [{"spawn_at_s": 65.0, "event_id": None}]
    for spawn in cannons:
        r = _wave_timing.wave_timing(events, spawn - 1.0)
        assert r["next_spawn_s"] == spawn and r["next_is_cannon"] is True


def test_callouts_schedule_is_the_g239_tool_schedule():
    r = g245.grade_clocks(65.0, until_s=1800.0)
    assert r["callouts_cannons"] == [g239.clock(s) for s in g239.predicted_cannons(65.0, 1800.0)]


def test_the_two_models_agree_before_14_00_and_part_after_it_under_once():
    r = g245.grade_clocks(65.0, until_s=1800.0)
    pre = [c for c in r["callouts_cannons"] if g239.parse_clock(c) < 840.0]
    assert r["timing_cannons"][:len(pre)] == pre
    assert r["first_divergence"] == {"index": len(pre), "callouts": "14:30", "timing": "14:35"}


def test_observed_grading_names_which_clock_matched():
    both = g245.grade_clocks(65.0, observed=[125.0, 215.0])
    assert both["verdict"] == "BOTH_MATCH"
    callouts_only = g245.grade_clocks(65.0, observed=[125.0, 870.0])
    assert callouts_only["verdict"] == "CALLOUTS_ONLY"
    timing_only = g245.grade_clocks(65.0, observed=[125.0, 875.0], tolerance_s=2.0)
    assert timing_only["verdict"] == "TIMING_ONLY"
    assert g245.grade_clocks(65.0, observed=[100.0])["verdict"] == "NEITHER"
    assert g245.grade_clocks(65.0)["verdict"] == "SCHEDULE"


def test_source_still_states_both_answers_to_question_one():
    text = (ROOT / "dashboard" / "_liveclient.py").read_text(encoding="utf-8")
    assert "emits a single MinionsSpawning event at first-wave spawn" in text
    assert "emits it once per" in text
    assert 'out["minion_events"] = minion_events' in text
    assert 'out["minion_spawn_events"] = minion_spawn_events' in text
    g239_text = (ROOT / "tools" / "gated_g239_wave_clock.py").read_text(encoding="utf-8")
    assert '"ANCHOR_MULTI"' in g239_text


def test_wave_timing_still_has_no_production_caller():
    scanned = 0
    callers = []
    for sub in ("dashboard", "core", "coaches", "modes", "game_reader", "app", "web"):
        base = ROOT / sub
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix not in (".py", ".js", ".mjs") or not path.is_file():
                continue
            if path.name == "_wave_timing.py":
                continue
            scanned += 1
            if "_wave_timing" in path.read_text(encoding="utf-8", errors="replace"):
                callers.append(path.relative_to(ROOT).as_posix())
    assert scanned > 50
    assert callers == []


def test_cadence_table_the_row_grades_is_unchanged():
    assert _wave_timing._CANNON_CADENCE == ((0.0, 3), (840.0, 2), (1500.0, 1))


def test_cli_stream_exit_codes(tmp_path, capsys):
    once = tmp_path / "once.json"
    once.write_text(json.dumps(_state(200.0, [65.0])), encoding="utf-8")
    assert g245.main(["stream", str(once), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "ONCE"
    early = tmp_path / "early.json"
    early.write_text(json.dumps(_state(80.0, [65.0])), encoding="utf-8")
    assert g245.main(["stream", str(early)]) == 3
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert g245.main(["stream", str(bad)]) == 2
    assert g245.main(["stream", str(tmp_path / "missing.json")]) == 2


def test_cli_clocks_exit_codes(capsys):
    assert g245.main(["clocks", "--anchor", "1:05"]) == 0
    assert g245.main(["clocks", "--anchor", "1:05", "--observed", "2:05,3:35"]) == 0
    assert g245.main(["clocks", "--anchor", "1:05", "--observed", "1:40"]) == 3
    assert g245.main(["clocks", "--anchor", "1:5"]) == 2
    capsys.readouterr()

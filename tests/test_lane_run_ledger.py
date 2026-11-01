"""ops/loop/lane_run_ledger.py: MAIN ORDER items RC-3 (exit tags), RC-4 (the daily line)
and FLEET-1b (the per-lane model trial). The s144 driver is gitignored, so only this
tracked module and the tracked runner are pinned here."""
from __future__ import annotations

import json
from pathlib import Path

from ops.loop import lane_run_ledger as RL

REPO_ROOT = Path(__file__).resolve().parent.parent
DAY = "2026-11-01"


def _row(note="lane-s144-ds", rc=0, subtype="success", is_error=False, cost=1.0,
         ts=f"{DAY}T10:00:00-06:00", model="claude-opus-5-5"):
    return {"ts": ts, "note": note, "rc": rc, "subtype": subtype, "is_error": is_error,
            "cost_usd": cost, "num_turns": 1, "error": None, "model": model}


def _write_tree(root: Path, usage, cycles_by_lane):
    usage_path = root / RL.USAGE_REL
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    usage_path.write_bytes("".join(json.dumps(r) + "\n" for r in usage).encode("ascii"))
    cdir = root / RL.CYCLES_REL
    cdir.mkdir(parents=True, exist_ok=True)
    for lane, rows in cycles_by_lane.items():
        (cdir / f"s144_{lane}_cycles.jsonl").write_bytes(
            "".join(json.dumps(r) + "\n" for r in rows).encode("ascii"))


# ------------------------------------------------------------------ RC-3

def test_rc1_with_subtype_success_is_tagged_apart_from_a_crash():
    measured = _row(rc=1, subtype="success", is_error=True)
    assert RL.exit_tag(1, measured) == RL.FAILED_REPORTS_SUCCESS
    assert RL.exit_tag(1, _row(rc=1, subtype="error_during_execution")) == RL.CRASH
    assert RL.exit_tag(1, None) == RL.CRASH  # no usage row at all
    assert RL.exit_tag(1073807364, None) == RL.CRASH  # the measured killed-runner code


def test_other_exits_are_neither_tag():
    assert RL.exit_tag(0, _row()) == RL.CLEAN
    assert RL.exit_tag(3, None) == RL.REFUSED
    assert RL.exit_tag(None, None) == RL.NO_EXIT_CODE
    assert RL.exit_tag(1, _row(rc=1), "timeout_killed") == RL.KILLED


def test_exit_counts_keep_the_two_failures_separate():
    rows = [_row(), _row(rc=1, is_error=True), _row(rc=1, is_error=True),
            _row(rc=1, subtype="error_max_turns"), _row(rc=3, subtype=None)]
    assert RL.exit_counts(rows) == {RL.FAILED_REPORTS_SUCCESS: 2, RL.CRASH: 1, RL.REFUSED: 1,
                                    RL.NO_EXIT_CODE: 0}


def test_exit_record_logs_last_result_text_and_exit_path():
    row = _row(rc=1, is_error=True, cost=0)
    rec = RL.exit_record(1, row, "worker_failed", "API Error:   the   text\n",
                         "lane exit 2026-10-31T17:14:49 code=1")
    assert rec["exit_tag"] == RL.FAILED_REPORTS_SUCCESS
    assert rec["last_result"] == "API Error: the text"
    assert rec["exit_path"].startswith("lane exit 2026-10-31T17:14:49 code=1 | kit rc=1 ")
    assert "subtype=success is_error=True" in rec["exit_path"]
    assert rec["exit_path"].endswith("driver rc=1 outcome=worker_failed")


def test_exit_record_of_a_clean_run_carries_no_failure_text():
    rec = RL.exit_record(0, _row(), "completed", "done", "lane exit x code=0")
    assert rec == {"exit_tag": RL.CLEAN, "usage_model": "claude-opus-5-5", "usage_cost_usd": 1.0}


def test_exit_record_without_a_usage_row_says_so():
    rec = RL.exit_record(1, None, "worker_failed", "", "")
    assert rec["exit_tag"] == RL.CRASH and rec["usage_model"] is None
    assert "no lane exit marker | kit no usage row" in rec["exit_path"]


def test_exit_marker_reads_the_last_marker_of_a_bom_crlf_log(tmp_path):
    log = tmp_path / "lane.log"
    log.write_bytes(b"\xef\xbb\xbflane start x\r\nlane exit a code=0\r\nlane exit b code=1\r\n")
    assert RL.exit_marker(log) == "lane exit b code=1"
    assert RL.exit_marker(tmp_path / "absent.log") == ""
    assert RL.exit_marker(None) == ""

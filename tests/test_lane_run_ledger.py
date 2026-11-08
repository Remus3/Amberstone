"""ops/loop/lane_run_ledger.py: MAIN ORDER items RC-3 (exit tags), RC-4 (the daily line)
and FLEET-1b (the per-lane model trial). The s144 driver is gitignored, so only this
tracked module and the tracked runner are pinned here."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

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


# ------------------------------------------------------------------ RC-4

def _daily_tree(root):
    usage = [_row(cost=2.5), _row(note="lane-s144-repo", cost=1.5, rc=1, is_error=True),
             _row(note="inbox tick", cost=10.0),
             _row(cost=99.0, ts="2026-10-31T23:00:00-05:00"), _row(cost=None)]
    cycles = {"ds": [{"lane": "ds", "ended": f"{DAY}T10:01:00-06:00", "own_commits": 3},
                     {"lane": "ds", "ended": "2026-10-31T23:01:00-05:00", "own_commits": 50}],
              "repo": [{"lane": "repo", "ended": f"{DAY}T11:01:00-06:00", "own_commits": 1},
                       {"lane": "repo", "ended": f"{DAY}T12:01:00-06:00"}]}
    _write_tree(root, usage, cycles)


def test_daily_figures_count_today_only_and_lane_rows_apart_from_the_tree(tmp_path):
    _daily_tree(tmp_path)
    fig = RL.today_daily(tmp_path, DAY)
    assert fig["lane_runs"] == 3 and fig["lane_usd"] == 4.0
    assert fig["tree_runs"] == 4 and fig["tree_usd"] == 14.0
    assert fig["lane_commits"] == 4 and fig["usd_per_lane_commit"] == 1.0
    assert fig["exits"][RL.FAILED_REPORTS_SUCCESS] == 1 and fig["exits"][RL.CRASH] == 0


def test_daily_line_labels_commits_lane_local_never_landed(tmp_path):
    _daily_tree(tmp_path)
    line = RL.today_daily(tmp_path, DAY)["line"]
    assert line.startswith(f"{DAY}: lane runs 3, lane USD 4.00, lane-local commits 4 ")
    assert "(not landed on main)" in line
    assert "failed-reports-success 1, crashes 0" in line
    assert line.isascii()


def test_a_day_with_no_commits_has_no_cost_per_commit():
    fig = RL.daily_figures([_row()], [], DAY)
    assert fig["usd_per_lane_commit"] is None
    assert "USD per lane-local commit n/a" in RL.daily_line(fig)


def test_stamp_daily_merges_into_the_status_file_and_reads_back(tmp_path):
    _daily_tree(tmp_path)
    status = tmp_path / RL.STATUS_REL
    status.parent.mkdir(parents=True)
    status.write_text(json.dumps({"task": "s144-lanes", "status": "running", "pct": 5}))
    assert RL.read_daily(tmp_path) is None
    fig = RL.stamp_daily(tmp_path, DAY)
    doc = json.loads(status.read_text())
    assert doc["task"] == "s144-lanes" and doc["pct"] == 5
    assert RL.read_daily(tmp_path) == fig == doc["daily"]
    assert fig["line"].startswith(DAY)
    assert sorted(p.name for p in status.parent.iterdir()) == [status.name]  # no tmp left


def _status_doc(root):
    status = root / RL.STATUS_REL
    status.parent.mkdir(parents=True)
    status.write_text(json.dumps({"task": "s144-lanes", "status": "running", "pct": 5}))
    return status


def test_stamp_daily_survives_a_refused_rename_on_a_per_writer_scratch(tmp_path, monkeypatch):
    """RM-258 / RM-261: the status file is polled by the lane widget while the kit's
    write_progress rewrites it, so a held target is a normal Windows state. The first
    version used a bare `<dest>.daily.tmp` + Path.replace: one refusal lost the stamp."""
    _daily_tree(tmp_path)
    status = _status_doc(tmp_path)
    real_replace = os.replace
    scratch: list[str] = []

    def refuse_once(src, dst):
        scratch.append(Path(src).name)
        if len(scratch) == 1:
            raise PermissionError(13, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", refuse_once)
    fig = RL.stamp_daily(tmp_path, DAY)
    assert RL.read_daily(tmp_path) == fig
    assert len(scratch) == 2, scratch
    assert scratch[0].startswith(status.name + ".") and scratch[0].endswith(".tmp"), scratch
    assert f".{os.getpid()}." in scratch[0], scratch
    assert sorted(p.name for p in status.parent.iterdir()) == [status.name]


def test_stamp_daily_writes_ascii_lf_bytes_and_cleans_up_on_a_lasting_refusal(tmp_path, monkeypatch):
    _daily_tree(tmp_path)
    status = _status_doc(tmp_path)
    RL.stamp_daily(tmp_path, DAY)
    raw = status.read_bytes()
    assert b"\r" not in raw and raw.isascii()

    def refused(src, dst):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(os, "replace", refused)
    with pytest.raises(OSError):
        RL.stamp_daily(tmp_path, DAY)
    assert status.read_bytes() == raw
    assert sorted(p.name for p in status.parent.iterdir()) == [status.name]


def test_module_still_loads_by_file_path_with_no_repo_on_sys_path(tmp_path):
    """The module doc promises it. `-I` drops the cwd and PYTHON* from the child, so
    `core` is not importable and the writer has to come from the absolute-path bind."""
    _daily_tree(tmp_path)
    status = _status_doc(tmp_path)
    code = (
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('rl_by_path', sys.argv[1])\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "assert 'core' not in sys.modules and 'core.polled_json' not in sys.modules\n"
        "mod.stamp_daily(sys.argv[2], sys.argv[3])\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code, str(REPO_ROOT / "ops/loop/lane_run_ledger.py"),
         str(tmp_path), DAY],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert done.returncode == 0, done.stderr
    assert json.loads(status.read_bytes())["daily"]["day"] == DAY


def test_week_usd_peak_and_median(tmp_path):
    usage = [_row(cost=100.0, ts="2026-10-28T01:00:00-05:00"),
             _row(cost=40.0, ts="2026-10-28T02:00:00-05:00"),
             _row(cost=10.0, ts="2026-10-30T01:00:00-05:00"),
             _row(cost=500.0, ts="2026-10-01T01:00:00-05:00"),  # outside the week
             _row(cost=999.0, ts=f"{DAY}T01:00:00-06:00")]  # partial today
    week = RL.week_usd(usage, today=DAY)
    assert len(week["days"]) == 7 and week["days"]["2026-10-28"] == 140.0
    assert week["peak"] == 999.0 and week["peak_complete_days"] == 140.0
    assert week["median_complete_days"] == 0.0


def test_peak_rolling_runs_uses_a_24h_window_and_splits_lane_rows():
    usage = [_row(ts="2026-10-30T01:00:00-05:00"), _row(ts="2026-10-30T02:00:00-05:00"),
             _row(ts="2026-10-31T01:30:00-05:00"), _row(note="x", ts="2026-10-31T01:40:00-05:00")]
    assert RL.peak_rolling_runs(usage) == 3
    assert RL.peak_rolling_runs(usage, lanes=True) == 2
    assert RL.peak_rolling_runs(usage, lanes=False) == 1


def test_runs_reserve_is_twenty_percent_of_the_live_cap():
    assert RL.runs_reserve(500) == 100
    assert RL.runs_reserve(120) == 24  # a config fault's cap keeps the old fixed reserve


# ------------------------------------------------------------------ FLEET-1b

def test_model_trial_keeps_only_the_repo_lane_to_the_extended_end():
    # RM-1267 (s155): repo's USD per lane commit fell, ds and research rose, so only
    # repo stays on sonnet, re-read on the new end date.
    assert RL.MODEL_TRIAL == {"repo": "claude-sonnet-5-5"}
    assert RL.MODEL_TRIAL_END == "2026-12-08"


def test_lane_model_holds_through_the_end_date_then_falls_back():
    assert RL.lane_model("repo", "2026-11-01") == "claude-sonnet-5-5"
    assert RL.lane_model("repo", "2026-11-09") == "claude-sonnet-5-5"
    assert RL.lane_model("repo", "2026-12-08") == "claude-sonnet-5-5"
    assert RL.lane_model("repo", "2026-12-09") is None


def test_opus_lanes_get_no_override():
    for lane in ("ds", "research", "true-audit", "queue", "uiux", "gated"):
        assert RL.lane_model(lane, "2026-11-02") is None
        assert RL.lane_model(lane, "2026-11-09") is None


def test_trial_ids_are_in_the_current_model_guard_set():
    from tests.test_rm511_model_pins_current import CURRENT_MODEL_IDS
    assert set(RL.MODEL_TRIAL.values()) <= CURRENT_MODEL_IDS


def test_trial_measure_splits_before_during_and_ignores_the_default_model_during():
    repo, sonnet = "lane-s144-repo", "claude-sonnet-5-5"
    usage = [_row(note=repo, cost=4.0, ts="2026-10-30T01:00:00-05:00"),
             _row(note=repo, cost=8.0, ts=f"{DAY}T01:00:00-06:00"),  # first day, still on opus
             _row(note=repo, cost=1.0, ts=f"{DAY}T05:00:00-06:00", model=sonnet),
             _row(note=repo, cost=1.0, ts="2026-12-08T05:00:00-06:00", model=sonnet),  # last day
             _row(note=repo, cost=1.0, ts="2026-12-09T05:00:00-06:00", model=sonnet),  # past it
             _row(note="lane-s144-queue", cost=6.0, ts=f"{DAY}T05:00:00-06:00")]
    cycles = [{"lane": "repo", "ended": "2026-10-30T01:00:00-05:00", "own_commits": 2},
              {"lane": "repo", "ended": f"{DAY}T01:00:00-06:00", "own_commits": 9},
              {"lane": "repo", "ended": f"{DAY}T05:00:00-06:00", "own_commits": 1,
               "model": sonnet},
              {"lane": "repo", "ended": "2026-12-08T05:00:00-06:00", "own_commits": 1,
               "model": sonnet}]
    out = RL.trial_measure(usage, cycles)
    assert out["repo"]["before"]["usd_per_lane_commit"] == 2.0
    assert out["repo"]["during"]["runs"] == 2 and out["repo"]["during"]["usd"] == 2.0
    assert out["repo"]["during"]["lane_commits"] == 2
    assert out["repo"]["during"]["models"] == [sonnet]
    assert out["queue"]["during"]["runs"] == 1  # a non-trial lane is not model-filtered


def _runner_text():
    return (REPO_ROOT / "ops" / "loop" / "run_lane.ps1").read_text(encoding="utf-8")


def test_runner_lets_the_lane_model_win_after_the_config_and_before_the_route():
    text = _runner_text()
    config = text.index("$cfg.executor_model")
    override = text.index("$env:RC_LANE_MODEL")
    route = text.index('"--model", $model')
    assert config < override < route


def test_runner_override_shape_matches_only_exact_ids():
    m = re.search(r"-cmatch '([^']+)'\) \{ \$model = \$env:RC_LANE_MODEL \}", _runner_text())
    assert m, "the runner's RC_LANE_MODEL override line changed shape"
    pat = re.compile(m.group(1))
    assert pat.match("claude-sonnet-5-5")
    assert not pat.match("sonnet") and not pat.match("") and not pat.match("--evil")

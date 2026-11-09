"""ops/loop/lane_run_ledger.py: MAIN ORDER items RC-3 (exit tags), RC-4 (the daily line)
and FLEET-1b (the per-lane model trial). The s144 driver is gitignored, so only this
tracked module and the tracked runner are pinned here."""
from __future__ import annotations

import datetime
import inspect
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
    status.write_text(json.dumps({"task": "s144-lanes", "status": "running", "pct": 5}), encoding="utf-8")
    assert RL.read_daily(tmp_path) is None
    fig = RL.stamp_daily(tmp_path, DAY)
    doc = json.loads(status.read_text(encoding="utf-8"))
    assert doc["task"] == "s144-lanes" and doc["pct"] == 5
    assert RL.read_daily(tmp_path) == fig == doc["daily"]
    assert fig["line"].startswith(DAY)
    assert sorted(p.name for p in status.parent.iterdir()) == [status.name]  # no tmp left


def _status_doc(root):
    status = root / RL.STATUS_REL
    status.parent.mkdir(parents=True)
    status.write_text(json.dumps({"task": "s144-lanes", "status": "running", "pct": 5}), encoding="utf-8")
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
        cwd=tmp_path, capture_output=True, text=True, timeout=120, check=False,
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


# ------------------------------------------------------------------ s158 C9 hourly start pace
# Measured 2026-11-09: 400 lane runs of a rolling 24 h landed in about 12.5 h (about 31 an
# hour), then every lane starved for about 11 h in "budget wait". The pace spreads the
# reserve-free runs over the day: at most (cap - reserve) // 24 starts in any rolling hour.

class _Budget:
    """The one member of the kit's RunBudget (fleet_headless.tree_budget) the pace reads."""

    def __init__(self, cap):
        self.cap = cap


def _epoch(iso):
    return datetime.datetime.fromisoformat(iso).timestamp()


def test_pace_limit_is_the_reserve_free_cap_spread_over_24_hours():
    assert RL.pace_limit(500) == (500 - RL.runs_reserve(500)) // 24 == 16
    assert RL.pace_limit(120) == (120 - RL.runs_reserve(120)) // 24 == 4
    assert RL.pace_limit(10) == 1  # never zero: a lane can always start again


def test_pace_limit_is_read_from_the_cap_never_a_hard_coded_500():
    limits = [RL.pace_limit(cap) for cap in (120, 250, 500, 1000)]
    assert limits == sorted(limits) and len(set(limits)) == 4
    src = inspect.getsource(RL.pace_limit) + inspect.getsource(RL.pace_check)
    assert "500" not in src and "16" not in src


def test_pace_check_counts_a_rolling_hour_and_waits_for_the_oldest_to_age_out():
    cap, now = 120, 10_000.0  # limit 4
    assert RL.pace_check([], now, cap) == (0, 4, 0.0)
    three = [now - 3000, now - 2000, now - 10]
    assert RL.pace_check(three, now, cap) == (3, 4, 0.0)
    four = [now - 3599, *three]
    n, m, wait = RL.pace_check(four, now, cap)
    assert (n, m) == (4, 4) and wait == pytest.approx(1.0)  # 3599 s old: 1 s to go
    # a start exactly an hour old is out of the window
    assert RL.pace_check([now - 3600, *three], now, cap) == (3, 4, 0.0)
    # more starts than the limit (the cap fell): wait until enough have aged out
    six = sorted([now - 3500, now - 3400, *four])
    n, m, wait = RL.pace_check(six, now, cap)
    assert (n, m) == (6, 4) and wait == pytest.approx(six[2] + 3600 - now)


def test_recent_starts_reads_the_rotator_start_events(tmp_path):
    path = tmp_path / RL.EVENTS_REL
    path.parent.mkdir(parents=True)
    now = _epoch("2026-11-09T12:00:00-06:00")
    rows = [{"kind": "start", "lane": "repo", "at": "2026-11-09T11:30:00-06:00"},
            {"kind": "end", "lane": "repo", "at": "2026-11-09T11:40:00-06:00"},
            {"kind": "start", "lane": "ds", "at": "2026-11-09T10:59:00-06:00"},  # too old
            {"kind": "start", "lane": "uiux", "at": "not a time"},
            {"kind": "start", "lane": "queue", "at": "2026-11-09T11:59:59-06:00"}]
    path.write_bytes(("".join(json.dumps(r) + "\n" for r in rows) + "{torn").encode("ascii"))
    assert RL.recent_starts(tmp_path, now) == [now - 1800, now - 1]
    assert RL.recent_starts(tmp_path / "missing", now) == []


# Seven lanes, one of them short-cycle (the measured repo lane took 36 percent of starts).
_DURATIONS = {"gated": 2400.0, "queue": 5400.0, "uiux": 3600.0, "research": 1800.0,
              "ds": 4200.0, "repo": 420.0, "true-audit": 3000.0}


def _simulate_day(budget, durations=None, horizon=86400.0):
    """A fake-clock model of the s144 rotator's launch loop: a lane may start when it is
    not running, the pick is least-recently-started (rotate_main's key), and the pace
    gate is RL.pace_check over every start so far against the budget's cap. No launch gap
    and no poll delay (the worst case for the pace). Time jumps to the next event: a lane
    end or the end of a pace wait. Returns (starts [(t, lane)], waits [(t, wait_s)])."""
    durations = durations or _DURATIONS
    order = list(durations)
    now, running, last, starts, waits = 0.0, {}, {}, [], []
    while now < horizon:
        for lane, end in list(running.items()):
            if end <= now:
                del running[lane]
        free = [lane for lane in order if lane not in running]
        _n, _m, wait = RL.pace_check([t for t, _l in starts], now, budget.cap)
        if free and wait == 0:
            pick = min(free, key=lambda x: (last.get(x, -1.0), order.index(x)))
            starts.append((now, pick))
            last[pick] = now
            running[pick] = now + durations[pick]
            continue
        nxt = list(running.values())
        if free:
            waits.append((now, wait))
            nxt.append(now + wait)
        now = min(nxt) if nxt else horizon
    return starts, waits


def _max_in_any_hour(times):
    best = lo = 0
    for hi, t in enumerate(times):
        while t - times[lo] >= 3600:
            lo += 1
        best = max(best, hi - lo + 1)
    return best


@pytest.mark.parametrize("cap", [500, 250, 120])
def test_simulated_day_never_exceeds_the_pace_and_waits_no_longer_than_needed(cap):
    budget = _Budget(cap)
    starts, waits = _simulate_day(budget)
    times = [t for t, _l in starts]
    limit = RL.pace_limit(budget.cap)
    assert _max_in_any_hour(times) == limit  # reached, never exceeded
    assert len(starts) <= budget.cap - RL.runs_reserve(budget.cap)
    per_hour = [0] * 24
    for t in times:
        per_hour[int(t // 3600)] += 1
    assert min(per_hour) >= limit // 2, per_hour  # spread over the day: no hour starves
    held = [(t, wait) for t, wait in waits if t + wait < 86400.0]
    assert held, "the pace never held a launch: the simulation proves nothing"
    for t, wait in held:
        assert wait > 0
        ready = t + wait
        # the next start is exactly when the oldest start in the window ages out
        assert any(abs(s - ready) < 1e-6 for s in times), (t, wait)
        assert not any(t < s < ready - 1e-6 for s in times), (t, wait)


def test_mutating_the_budget_cap_moves_the_simulated_hourly_peak():
    peaks = {}
    for cap in (500, 250):
        starts, _w = _simulate_day(_Budget(cap))
        peaks[cap] = _max_in_any_hour([t for t, _l in starts])
    assert peaks == {500: RL.pace_limit(500), 250: RL.pace_limit(250)}
    assert peaks[500] != peaks[250]


# ------------------------------------------------------------------ s158 C9 verifier round cap
# Measured 2026-11-09: queue cycle s144q227 was timeout_killed at 9000 s on "W6 verifier
# round 7" (the gate rejected its fix 7 rounds running). The directive caps it at 3.

_FILLS = {"@@LANE@@": "queue", "@@RUN_ID@@": "s144q999-abc123", "@@CODE@@": "Q",
          "@@MAIN@@": "<main>"}  # the build_prompt substitutions the cap text may use
_GATE = ("- VERIFIER GATE, mandatory before the commit: one foreground independent read-only "
         "sub-agent re-runs ONLY your cited test files and reviews your diff, defaulting to "
         "REFUTED. Agreement is not evidence.")


def _render(template):
    text = RL.fill_verifier_cap(template)
    for key, val in _FILLS.items():
        text = text.replace(key, val)
    return text


def _assert_cap_wording(out, cap=3):
    assert "@@" not in out
    assert f"at most {cap} verifier rounds" in out
    assert f"{RL.ordinal(cap)} rejection" in out
    assert "git stash push -u -m s144-nonconverge-s144q999-abc123" in out
    assert 's144_lane_progress.py" queue <pct> failed "verifier non-convergence"' in out
    assert "FILINGS" in out and "S144-Q-<nn>" in out
    assert "then EXIT" in out


def test_rendered_directive_carries_the_verifier_round_cap_at_its_slot():
    out = _render(f"TESTS\n{_GATE}\n{RL.VERIFIER_CAP_SLOT}\n\nRACE GUARDS\n")
    _assert_cap_wording(out)
    assert out.index("VERIFIER GATE") < out.index("VERIFIER ROUND CAP") < out.index("RACE")
    assert out.count("VERIFIER ROUND CAP") == 1


def test_an_older_template_without_the_slot_gets_the_cap_after_its_gate_line():
    out = _render(f"TESTS\n{_GATE}\n\nRACE GUARDS\n")
    _assert_cap_wording(out)
    assert out.index("Agreement is not evidence.") < out.index("VERIFIER ROUND CAP")
    assert out.count("VERIFIER ROUND CAP") == 1
    assert RL.fill_verifier_cap("no gate here\n") == "no gate here\n"


def test_cap_text_uses_only_placeholders_build_prompt_fills_and_is_ascii():
    text = RL.verifier_cap_text()
    assert set(re.findall(r"@@[A-Z_]+@@", text)) <= set(_FILLS)
    text.encode("ascii")
    assert RL.VERIFIER_ROUND_CAP == 3
    assert RL.VERIFIER_NONCONVERGENCE_STEP == "verifier non-convergence"


def test_cap_wording_follows_the_cap():
    out = RL.verifier_cap_text(cap=5)
    assert "at most 5 verifier rounds" in out and "5th rejection" in out
    assert "at most 3" not in out
    assert [RL.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd"]


def test_the_stash_follows_the_reference_r1_leftover_path_it_cites():
    ref = (REPO_ROOT / "docs" / "LANE_PROMPT_REFERENCE.md").read_text(encoding="utf-8")
    r1 = re.search(r"`git stash push (-m s144-)leftover-<run id>`", ref)
    assert r1, "reference R1 no longer names its leftover stash"
    text = RL.verifier_cap_text()
    assert "reference R1" in text
    # the same command and message shape as R1, plus -u for new untracked files
    cap = re.search(r"`git stash push -u (-m s144-)nonconverge-@@RUN_ID@@`", text)
    assert cap and cap.group(1) == r1.group(1)


def test_the_live_template_renders_the_cap_when_present():
    """The s144 template is gitignored (absent in CI and a fresh clone): render it with
    the real fill when this checkout has it, slot or no slot."""
    path = REPO_ROOT / "ops" / "loop" / "control" / "lane_prompts" / "s144-common.tmpl"
    if not path.is_file():
        pytest.skip("gitignored s144-common.tmpl absent in this checkout")
    out = _render(path.read_text(encoding="utf-8"))
    assert "VERIFIER GATE, mandatory before the commit" in out
    assert out.count("VERIFIER ROUND CAP") == 1
    assert out.index("VERIFIER GATE, mandatory") < out.index("VERIFIER ROUND CAP")
    assert "at most 3 verifier rounds" in out and "verifier non-convergence" in out

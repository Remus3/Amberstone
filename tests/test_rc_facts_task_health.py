"""Scheduled-task health in the SessionStart banner (tools/rc_facts.py).

rc_facts is the ONLY mechanism in this repo that alerts on scheduled-task
health, and it was blind in four measured ways. This file pins the fix for
each of them:

  1. A HUNG TASK READ GREEN. The old result-code whitelist accepted 267009
     (0x00041301 SCHED_S_TASK_RUNNING), which means "still running, no
     completed result" - NOT success. A periodic task wedged for days
     reported clean. 267009 is only benign for a LONG-LIVED SERVICE; on a
     periodic task it means the task started and never finished.
  2. DISABLED TASKS WERE SUPPRESSED ENTIRELY. RC-WeeklyHygiene sat Disabled
     with missed weekly runs and never once appeared. A deliberately
     disabled periodic task must stay VISIBLE as DISARMED, not vanish.
  3. NO STALENESS CHECK AT ALL. Nothing asked how long since a task's output
     artifact advanced, so a task that ran, exited 0 and produced nothing
     read as healthy.
  4. A FAILED PROBE WAS SILENT. `_legion_tasks()` returned [] on timeout or
     parse error and the emitting block was gated `if tasks:`, so a broken
     probe printed nothing and read identical to "all healthy". The probe
     now returns None for "could not measure" and [] for "measured, no
     RC-* tasks", and both are loud.

Three further defects, measured 2026-09-30 and pinned at the bottom of this
file:

  5. ONE TASK PRODUCED TWO ANOMALIES. The state loop reported a Disabled task
     as DISARMED and then the artifact loop reported the SAME task again as
     artifact UNKNOWN/STALE. The stale artifact is a symptom of the disarm,
     not an independent finding, so the artifact arm now skips any task whose
     root cause the state loop already named.
  6. THE WINDOW COLLIDED WITH THE LOG REAPER, so STALE was unreachable. The
     RC-WeeklyHygiene signal is logs/weekly_hygiene_*.log, and
     core/log_retention.py deletes logs/*.log* at 14 days - exactly the
     two-interval stale window. The evidence was gone on the same day it
     would first have fired, so the signal could only read FRESH or UNKNOWN.
     The log-backed window is now strictly shorter than retention, and the
     STRICT INEQUALITY is guarded, not just patched.
  7. DELIBERATE DISARMS READ AS ANOMALIES. The three headless-claude tasks the
     operator disabled on 2026-09-11 reported as faults at every session
     start. They are now ACKNOWLEDGED: still printed, still visible, with the
     re-arm precondition attached, but not counted as anomalies. The
     acknowledgement covers the DISARM only - re-enabled and failing, or
     re-enabled and producing nothing, still reports. For RC-InboxResponder
     the polarity is INVERTED: CLAUDE.md requires it to stay disarmed, so
     finding it ENABLED is the anomaly.

Also pinned: 2147946720 (0x800710E0, Win32 4320 "the operator or
administrator has refused the request") is the signature of an
ExecutionTimeLimit kill and is a FAILURE. The ONE narrow suppression kept
from the old code is a currently-Running singleton daemon, where the code is
Task Scheduler correctly refusing a DUPLICATE launch while the boot instance
is alive.

Nothing here shells out to the real Get-ScheduledTask and nothing reads the
live repo artifacts - every case is a synthetic row plus a tmp_path tree.

All authored content here is 7-bit ASCII.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import tools.rc_facts as rc_facts

_DAY = 86400.0
_WEEK = 7 * _DAY

# A row shaped like one element of the widened PowerShell projection.
def _row(name, state="Ready", last_result=0, last_run=None, next_run=None, triggers=None):
    return {
        "name": name,
        "state": state,
        "last_result": last_result,
        "last_run": last_run,
        "next_run": next_run,
        "triggers": triggers,
    }


def _iso(now: float, age_s: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - age_s))


# --------------------------------------------------------------- projection


def test_powershell_projection_carries_last_run_and_next_run():
    """The probe used to project name/state/last_result only and deliberately
    drop LastRunTime, which is why no staleness question could even be asked."""
    cmd = rc_facts.TASK_PROBE_PS
    assert "LastRunTime" in cmd
    assert "NextRunTime" in cmd
    assert "LastTaskResult" in cmd


def test_probe_returns_none_when_powershell_fails(monkeypatch):
    class _P:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(rc_facts.subprocess, "run", lambda *a, **k: _P())
    assert rc_facts._legion_tasks() is None


def test_probe_returns_none_on_unparseable_output(monkeypatch):
    class _P:
        returncode = 0
        stdout = "not json at all"
        stderr = ""

    monkeypatch.setattr(rc_facts.subprocess, "run", lambda *a, **k: _P())
    assert rc_facts._legion_tasks() is None


def test_probe_returns_list_on_success(monkeypatch):
    class _P:
        returncode = 0
        stdout = json.dumps({"name": "RC-Supervisor", "state": "Running", "last_result": 267009})
        stderr = ""

    monkeypatch.setattr(rc_facts.subprocess, "run", lambda *a, **k: _P())
    got = rc_facts._legion_tasks()
    assert isinstance(got, list) and len(got) == 1
    assert got[0]["name"] == "RC-Supervisor"


# ----------------------------------------------------------- classification


def test_running_code_on_long_lived_service_is_not_an_anomaly():
    for name in ("RC-Supervisor", "RC-DaemonSlayer", "RC-LCUAgent", "RC-MissionControl"):
        verdict, _detail = rc_facts.classify_task_result(
            name, "Running", rc_facts.TASK_RESULT_RUNNING, last_run_age_s=3 * _DAY
        )
        assert verdict == rc_facts.VERDICT_OK, name


def test_running_code_on_periodic_task_is_an_anomaly():
    """267009 on something that is supposed to START and FINISH means wedged."""
    verdict, detail = rc_facts.classify_task_result(
        "RC-PostmortemAnalyze", "Running", rc_facts.TASK_RESULT_RUNNING, last_run_age_s=4 * _DAY
    )
    assert verdict == rc_facts.VERDICT_STUCK
    assert "never finished" in detail


def test_service_running_implausibly_long_is_an_anomaly():
    verdict, detail = rc_facts.classify_task_result(
        "RC-Supervisor",
        "Running",
        rc_facts.TASK_RESULT_RUNNING,
        last_run_age_s=rc_facts.SERVICE_RUNNING_IMPLAUSIBLE_S + _DAY,
    )
    assert verdict == rc_facts.VERDICT_STUCK
    assert "RUNNING" in detail


def test_timeout_kill_code_is_a_failure():
    verdict, detail = rc_facts.classify_task_result(
        "RC-RewindCatchup", "Ready", 2147946720
    )
    assert verdict == rc_facts.VERDICT_FAILURE
    assert "0x800710E0" in detail


def test_timeout_kill_suppressed_only_for_a_running_singleton_daemon():
    """Task Scheduler refusing a DUPLICATE launch of a live IgnoreNew daemon."""
    ok, _d = rc_facts.classify_task_result("RC-Phase3-Supervisor", "Running", 2147946720)
    assert ok == rc_facts.VERDICT_OK
    # Same code on the same service while it is NOT running is a real kill.
    bad, _d2 = rc_facts.classify_task_result("RC-Phase3-Supervisor", "Ready", 2147946720)
    assert bad == rc_facts.VERDICT_FAILURE


def test_zero_and_benign_codes_are_ok():
    for code in (0, rc_facts.TASK_RESULT_NOT_RUN, rc_facts.TASK_RESULT_TERMINATED):
        verdict, _d = rc_facts.classify_task_result("RC-RewindCatchup", "Ready", code)
        assert verdict == rc_facts.VERDICT_OK, code


def test_other_nonzero_is_a_failure():
    verdict, detail = rc_facts.classify_task_result("RC-RewindCatchup", "Ready", 2)
    assert verdict == rc_facts.VERDICT_FAILURE
    assert "last_result=2" in detail


def test_daemon_slayer_exit_1_suppressed_only_when_ds_is_alive():
    ok, _d = rc_facts.classify_task_result("RC-DaemonSlayer", "Running", 1, ds_alive=True)
    assert ok == rc_facts.VERDICT_OK
    bad, _d2 = rc_facts.classify_task_result("RC-DaemonSlayer", "Ready", 1, ds_alive=False)
    assert bad == rc_facts.VERDICT_FAILURE


def test_cost_health_watchdog_exit_1_is_by_design():
    verdict, _d = rc_facts.classify_task_result("RC-CostHealthWatchdog", "Ready", 1)
    assert verdict == rc_facts.VERDICT_OK


def test_missing_last_result_is_unknown_not_ok():
    verdict, _d = rc_facts.classify_task_result("RC-RewindCatchup", "Ready", None)
    assert verdict == rc_facts.VERDICT_UNKNOWN


# ------------------------------------------------------------- DISARMED


def test_disabled_weekly_task_surfaces_as_disarmed(tmp_path):
    """An UNACKNOWLEDGED disarm is still an anomaly. RC-WeeklyHygiene cannot
    carry this case any more - it is on the acknowledged roster - so the
    generic arm is pinned with a periodic task that is not."""
    rows = [_row("RC-RewindCatchup", state="Disabled", last_result=0,
                 triggers="MSFT_TaskWeeklyTrigger")]
    lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=time.time())
    blob = "\n".join(lines + anomalies)
    assert "DISARMED" in blob
    assert "RC-RewindCatchup" in blob
    assert any("DISARMED" in a and "RC-RewindCatchup" in a for a in anomalies)


def test_disabled_task_with_only_a_logon_trigger_is_not_disarmed(tmp_path):
    """A service deliberately parked off is not a MISSED periodic run."""
    rows = [_row("RC-LiveFlipWatcher", state="Disabled", last_result=0,
                 triggers="MSFT_TaskLogonTrigger")]
    _lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=time.time())
    assert not [a for a in anomalies if "DISARMED" in a]


def test_disabled_task_with_no_trigger_data_falls_back_to_the_artifact_table(tmp_path):
    """Trigger projection can come back empty; a name in TASK_ARTIFACTS is
    known-periodic regardless, so it must still surface."""
    rows = [_row("RC-PostmortemAnalyze", state="Disabled", last_result=0, triggers=None)]
    _lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=time.time())
    assert any("DISARMED" in a for a in anomalies)


# ------------------------------------------------------- artifact staleness


def _write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def test_artifact_table_covers_the_four_weekly_tasks():
    assert set(rc_facts.TASK_ARTIFACTS) == {
        "RC-PostmortemAnalyze",
        "RC-Phase3-PeriodicAudit",
        "RC-RewindCatchup",
        "RC-WeeklyHygiene",
    }


def test_postmortem_signal_fresh_then_stale_then_missing(tmp_path):
    sig = rc_facts.TASK_ARTIFACTS["RC-PostmortemAnalyze"]
    now = time.time()
    target = tmp_path / "data" / "coaching" / "death_patterns.json"

    _write_json(target, {"generated_at": _iso(now, 2 * _DAY)})
    status, age, _d = rc_facts.artifact_status(sig, tmp_path, now)
    assert status == rc_facts.ARTIFACT_FRESH
    assert 0 <= age < 3 * _DAY

    _write_json(target, {"generated_at": _iso(now, 30 * _DAY)})
    status, age, _d = rc_facts.artifact_status(sig, tmp_path, now)
    assert status == rc_facts.ARTIFACT_STALE

    _write_json(target, {"schema_version": 2})
    status, age, detail = rc_facts.artifact_status(sig, tmp_path, now)
    assert status == rc_facts.ARTIFACT_UNKNOWN
    assert "generated_at" in detail
    assert age is None

    target.unlink()
    status, _age, detail = rc_facts.artifact_status(sig, tmp_path, now)
    assert status == rc_facts.ARTIFACT_UNKNOWN
    assert "absent" in detail


def test_phase3_signal_reads_the_newest_matching_jsonl_record(tmp_path):
    sig = rc_facts.TASK_ARTIFACTS["RC-Phase3-PeriodicAudit"]
    now = time.time()
    q = tmp_path / "agents" / "state" / "task_queue.jsonl"
    q.parent.mkdir(parents=True, exist_ok=True)

    rows = [
        {"ts": _iso(now, 400 * _DAY), "task": {"op": "agent6-full-audit-pass"}},
        # A NEWER record for a DIFFERENT op must not be credited.
        {"ts": _iso(now, 1 * _DAY), "task": {"op": "something-else"}},
        {"ts": _iso(now, 3 * _DAY), "task": {"op": "agent6-full-audit-pass"}},
    ]
    q.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    status, age, _d = rc_facts.artifact_status(sig, tmp_path, now)
    assert status == rc_facts.ARTIFACT_FRESH
    assert 2 * _DAY < age < 4 * _DAY

    # Only the ancient matching record left -> stale.
    q.write_text(json.dumps(rows[0]) + "\n" + json.dumps(rows[1]) + "\n", encoding="utf-8")
    status, _age, _d = rc_facts.artifact_status(sig, tmp_path, now)
    assert status == rc_facts.ARTIFACT_STALE

    # No matching record at all -> UNKNOWN, never silently fresh.
    q.write_text(json.dumps(rows[1]) + "\n", encoding="utf-8")
    status, age, detail = rc_facts.artifact_status(sig, tmp_path, now)
    assert status == rc_facts.ARTIFACT_UNKNOWN
    assert age is None
    assert "agent6-full-audit-pass" in detail


def test_phase3_signal_tolerates_a_corrupt_line(tmp_path):
    sig = rc_facts.TASK_ARTIFACTS["RC-Phase3-PeriodicAudit"]
    now = time.time()
    q = tmp_path / "agents" / "state" / "task_queue.jsonl"
    q.parent.mkdir(parents=True, exist_ok=True)
    good = json.dumps({"ts": _iso(now, _DAY), "task": {"op": "agent6-full-audit-pass"}})
    q.write_text("{not json\n" + good + "\n\n", encoding="utf-8")
    status, _age, _d = rc_facts.artifact_status(sig, tmp_path, now)
    assert status == rc_facts.ARTIFACT_FRESH


def test_rewind_signal_missing_field_is_unknown_not_a_crash(tmp_path):
    """Another slice is concurrently changing when last_run_at is written, so
    a missing or unparseable field must read UNKNOWN and never raise."""
    sig = rc_facts.TASK_ARTIFACTS["RC-RewindCatchup"]
    now = time.time()
    target = tmp_path / "data" / "rewind_catchup.state.json"

    _write_json(target, {"last_run_at": _iso(now, _DAY)})
    assert rc_facts.artifact_status(sig, tmp_path, now)[0] == rc_facts.ARTIFACT_FRESH

    _write_json(target, {"last_run_at": _iso(now, 40 * _DAY)})
    assert rc_facts.artifact_status(sig, tmp_path, now)[0] == rc_facts.ARTIFACT_STALE

    for junk in ({"puuid": "x"}, {"last_run_at": None}, {"last_run_at": "nonsense"},
                 {"last_run_at": ""}, {"last_run_at": []}):
        _write_json(target, junk)
        status, age, _d = rc_facts.artifact_status(sig, tmp_path, now)
        assert status == rc_facts.ARTIFACT_UNKNOWN, junk
        assert age is None

    target.write_text("{ truncated", encoding="utf-8")
    assert rc_facts.artifact_status(sig, tmp_path, now)[0] == rc_facts.ARTIFACT_UNKNOWN


def test_rewind_signal_accepts_an_epoch_timestamp(tmp_path):
    """Defensive: the concurrent slice may write an epoch rather than ISO."""
    sig = rc_facts.TASK_ARTIFACTS["RC-RewindCatchup"]
    now = time.time()
    _write_json(tmp_path / "data" / "rewind_catchup.state.json", {"last_run_at": now - _DAY})
    assert rc_facts.artifact_status(sig, tmp_path, now)[0] == rc_facts.ARTIFACT_FRESH


def test_weekly_hygiene_signal_uses_the_newest_log_file(tmp_path):
    sig = rc_facts.TASK_ARTIFACTS["RC-WeeklyHygiene"]
    now = time.time()
    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    status, _age, detail = rc_facts.artifact_status(sig, tmp_path, now)
    assert status == rc_facts.ARTIFACT_UNKNOWN
    assert "no file" in detail

    old = logs / "weekly_hygiene_2026-01-01.log"
    old.write_text("x", encoding="utf-8")
    import os as _os
    _os.utime(old, (now - 60 * _DAY, now - 60 * _DAY))
    assert rc_facts.artifact_status(sig, tmp_path, now)[0] == rc_facts.ARTIFACT_STALE

    fresh = logs / "weekly_hygiene_2026-09-28.log"
    fresh.write_text("x", encoding="utf-8")
    _os.utime(fresh, (now - 2 * _DAY, now - 2 * _DAY))
    status, age, _d = rc_facts.artifact_status(sig, tmp_path, now)
    assert status == rc_facts.ARTIFACT_FRESH
    assert age < 3 * _DAY


def test_stale_threshold_is_two_intervals_unless_a_reaper_forces_it_shorter():
    assert rc_facts.TASK_ARTIFACTS, "an empty signal table would make this vacuous"
    for name, sig in rc_facts.TASK_ARTIFACTS.items():
        assert sig.interval_s == _WEEK, name
        if _is_log_backed(sig):
            # Two intervals is 14d, which is EXACTLY the log reaper's cutoff,
            # so the two-interval default makes STALE unreachable here.
            assert sig.stale_after_s < 2.0 * sig.interval_s, name
        else:
            assert sig.stale_after_s == 2.0 * sig.interval_s, name


# ------------------------------------- defect 2: the window-collision invariant


def _is_log_backed(sig) -> bool:
    return sig.kind == rc_facts.ARTIFACT_NEWEST_GLOB and sig.path.startswith("logs/")


def test_rc_facts_mirrors_the_live_log_retention_default():
    """rc_facts carries its own copy of the reaper cutoff so the SessionStart
    hook stays import-light. This pins the copy to the real value."""
    from core import log_retention

    assert rc_facts.LOG_RETENTION_MAX_AGE_S == (
        log_retention._DEFAULT_MAX_AGE_DAYS * 86400.0
    )


def test_log_backed_artifact_window_is_strictly_under_log_retention():
    """THE REAL DEFECT-2 BUG, guarded rather than only patched.

    core/log_retention.py deletes logs/*.log* older than 14 days. If a
    log-backed signal's stale window is also 14 days the file is gone before
    it can ever read STALE, so the detector can only report FRESH or UNKNOWN.
    Strictly-less is the invariant; this test FAILS the moment the two windows
    are made equal again.
    """
    log_backed = {n: s for n, s in rc_facts.TASK_ARTIFACTS.items() if _is_log_backed(s)}
    assert log_backed, "no log-backed signal found - this guard would be vacuous"
    for name, sig in log_backed.items():
        assert sig.stale_after_s < rc_facts.LOG_RETENTION_MAX_AGE_S, (
            f"{name}: stale window {sig.stale_after_s}s is not strictly under the "
            f"{rc_facts.LOG_RETENTION_MAX_AGE_S}s log retention - STALE is unreachable"
        )


def test_weekly_hygiene_stale_is_reachable_before_the_reaper_deletes_the_log(tmp_path):
    """Behavioural proof, not just an arithmetic one: a log aged into the band
    between the detector window and the reaper cutoff really reads STALE."""
    sig = rc_facts.TASK_ARTIFACTS["RC-WeeklyHygiene"]
    now = time.time()
    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    f = logs / "weekly_hygiene_2026-09-01.log"
    f.write_text("x", encoding="utf-8")

    age = (sig.stale_after_s + rc_facts.LOG_RETENTION_MAX_AGE_S) / 2.0
    assert sig.stale_after_s < age < rc_facts.LOG_RETENTION_MAX_AGE_S, (
        "the reachable band is empty - the windows collided again"
    )
    os.utime(f, (now - age, now - age))

    status, got_age, _detail = rc_facts.artifact_status(sig, tmp_path, now)
    assert status == rc_facts.ARTIFACT_STALE
    assert got_age is not None and got_age > sig.stale_after_s


# ------------------------------------------------------------- banner shape


def _fresh_world(root: Path, now: float) -> None:
    _write_json(root / "data" / "coaching" / "death_patterns.json",
                {"generated_at": _iso(now, _DAY)})
    _write_json(root / "data" / "rewind_catchup.state.json",
                {"last_run_at": _iso(now, _DAY)})
    q = root / "agents" / "state" / "task_queue.jsonl"
    q.parent.mkdir(parents=True, exist_ok=True)
    q.write_text(json.dumps({"ts": _iso(now, _DAY),
                             "task": {"op": "agent6-full-audit-pass"}}) + "\n",
                 encoding="utf-8")
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    f = logs / "weekly_hygiene_x.log"
    f.write_text("x", encoding="utf-8")
    import os as _os
    _os.utime(f, (now - _DAY, now - _DAY))


def _all_weekly_rows(now: float) -> list[dict]:
    return [
        _row(n, state="Ready", last_result=0, last_run=_iso(now, _DAY),
             triggers="MSFT_TaskWeeklyTrigger")
        for n in sorted(rc_facts.TASK_ARTIFACTS)
    ]


def test_probe_failure_is_loud(tmp_path):
    lines, anomalies = rc_facts.task_health_lines(None, root=tmp_path, now=time.time())
    assert lines, "a failed probe must still print a line"
    assert any("PROBE FAILED" in a for a in anomalies)
    assert any("PROBE FAILED" in ln for ln in lines)


def test_empty_task_list_is_loud_too(tmp_path):
    """Measured, not silent: zero RC-* tasks on Legion is itself an anomaly,
    and it must not read the same as a failed probe."""
    lines, anomalies = rc_facts.task_health_lines([], root=tmp_path, now=time.time())
    assert lines
    assert anomalies
    assert not any("PROBE FAILED" in a for a in anomalies)


def test_healthy_world_prints_no_per_task_roll_call(tmp_path):
    now = time.time()
    _fresh_world(tmp_path, now)
    rows = _all_weekly_rows(now) + [
        _row("RC-Supervisor", state="Running", last_result=rc_facts.TASK_RESULT_RUNNING,
             last_run=_iso(now, 2 * _DAY), triggers="MSFT_TaskLogonTrigger"),
        _row("RC-LCUAgent", state="Running", last_result=rc_facts.TASK_RESULT_RUNNING,
             last_run=_iso(now, 2 * _DAY), triggers="MSFT_TaskLogonTrigger"),
    ]
    lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=now)
    assert anomalies == []
    # One summary line, no per-task roll call - this prints at every session start.
    assert len(lines) == 1
    assert "RC-Supervisor" not in lines[0]
    assert "6" in lines[0]


def test_unhealthy_world_names_only_the_bad_tasks(tmp_path):
    now = time.time()
    _fresh_world(tmp_path, now)
    # Break exactly one artifact and one result code.
    _write_json(tmp_path / "data" / "rewind_catchup.state.json",
                {"last_run_at": _iso(now, 90 * _DAY)})
    rows = _all_weekly_rows(now)
    rows = [r for r in rows if r["name"] != "RC-WeeklyHygiene"] + [
        _row("RC-WeeklyHygiene", state="Disabled", last_result=0,
             triggers="MSFT_TaskWeeklyTrigger"),
        _row("RC-Supervisor", state="Running", last_result=rc_facts.TASK_RESULT_RUNNING,
             last_run=_iso(now, _DAY), triggers="MSFT_TaskLogonTrigger"),
        _row("RC-CleanupScratch", state="Ready", last_result=2147946720,
             last_run=_iso(now, _DAY), triggers="MSFT_TaskDailyTrigger"),
    ]
    lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=now)
    blob = "\n".join(lines + anomalies)
    assert "RC-RewindCatchup" in blob and "STALE" in blob
    assert "RC-WeeklyHygiene" in blob and "DISARMED" in blob
    assert "RC-CleanupScratch" in blob
    # Healthy ones stay out of the banner.
    assert "RC-Supervisor" not in blob
    assert "RC-PostmortemAnalyze" not in blob


def test_a_weekly_task_missing_from_the_probe_is_reported(tmp_path):
    now = time.time()
    _fresh_world(tmp_path, now)
    rows = [r for r in _all_weekly_rows(now) if r["name"] != "RC-PostmortemAnalyze"]
    _lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=now)
    assert any("RC-PostmortemAnalyze" in a and "not registered" in a for a in anomalies)


def test_banner_lines_are_ascii(tmp_path):
    now = time.time()
    rows = [_row("RC-WeeklyHygiene", state="Disabled", last_result=2147946720,
                 triggers="MSFT_TaskWeeklyTrigger")]
    lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=now)
    for s in lines + anomalies:
        assert s.isascii(), s
        assert chr(0x2014) not in s and chr(0x2013) not in s


def test_main_emits_the_probe_failure_anomaly(monkeypatch, tmp_path):
    """End to end through main(): a broken probe must reach the banner."""
    import io
    import sys as _sys

    health = tmp_path / "health.json"
    health.write_text('{"pid": 1, "alive": true, "last_reload_ok": true}', encoding="utf-8")
    monkeypatch.setattr(rc_facts, "_HEALTH", health)
    monkeypatch.setattr(rc_facts, "_APP", tmp_path)
    monkeypatch.setattr(rc_facts, "_port_listening", lambda *a, **k: True)
    monkeypatch.setattr(rc_facts, "_health_all", lambda: {})
    monkeypatch.setattr(rc_facts, "_http_get_json", lambda *a, **k: None)
    monkeypatch.setattr(rc_facts, "_legion_tasks", lambda: None)
    monkeypatch.setattr(rc_facts, "_last_boot_iso", lambda: None)
    monkeypatch.setattr(rc_facts, "_inbox_section", lambda *a, **k: ([], [], set()))
    buf = io.StringIO()
    monkeypatch.setattr(_sys, "stdout", buf)
    assert rc_facts.main(session=None) == 0
    text = buf.getvalue()
    assert "PROBE FAILED" in text
    assert "! Anomalies" in text


# -------------------------------------------- defect 1: one task, one anomaly


def test_a_disarmed_task_reports_one_anomaly_not_two(tmp_path):
    """The state loop and the artifact loop used to BOTH fire for the same
    task: once DISARMED, once "artifact UNKNOWN/STALE". One task with one root
    cause gets one anomaly - the disarm, which is why the artifact is stale.
    """
    now = time.time()
    _fresh_world(tmp_path, now)
    _write_json(tmp_path / "data" / "rewind_catchup.state.json",
                {"last_run_at": _iso(now, 90 * _DAY)})
    rows = [r for r in _all_weekly_rows(now) if r["name"] != "RC-RewindCatchup"]
    rows.append(_row("RC-RewindCatchup", state="Disabled", last_result=0,
                     triggers="MSFT_TaskWeeklyTrigger"))

    _lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=now)
    mine = [a for a in anomalies if "RC-RewindCatchup" in a]
    assert len(mine) == 1, mine
    assert "DISARMED" in mine[0]
    assert "artifact" not in mine[0].lower()


def test_an_acknowledged_disarm_does_not_fire_a_second_artifact_anomaly(tmp_path):
    """Same collision, reached through the acknowledged path. The artifact arm
    must not turn an acknowledged, non-anomalous disarm back into an anomaly.
    """
    now = time.time()
    _fresh_world(tmp_path, now)
    # Delete the hygiene log so the artifact arm WOULD report UNKNOWN.
    for p in (tmp_path / "logs").glob("weekly_hygiene_*.log"):
        p.unlink()
    rows = [r for r in _all_weekly_rows(now) if r["name"] != "RC-WeeklyHygiene"]
    rows.append(_row("RC-WeeklyHygiene", state="Disabled", last_result=0,
                     triggers="MSFT_TaskWeeklyTrigger"))

    _lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=now)
    assert [a for a in anomalies if "RC-WeeklyHygiene" in a] == [], anomalies


# ------------------------------------- defect 3: acknowledged, still VISIBLE


def test_acknowledged_disarm_roster_matches_the_2026_09_11_operator_stop():
    """docs/history_notes.md: "Three headless-claude scheduled tasks were
    disabled in the same wrap: RC-CIWatchdog, RC-WeeklyHygiene,
    RC-InboxResponder." Exactly those three, no silent fourth.
    """
    assert set(rc_facts.ACKNOWLEDGED_DISARMS) == {
        "RC-CIWatchdog",
        "RC-WeeklyHygiene",
        "RC-InboxResponder",
    }
    for name, why in rc_facts.ACKNOWLEDGED_DISARMS.items():
        assert why.strip(), name
        assert "2026-09-11" in why, name
    assert rc_facts.DISARM_REQUIRED_TASKS == frozenset({"RC-InboxResponder"})


def test_an_acknowledged_disarm_is_visible_but_not_an_anomaly(tmp_path):
    rows = [_row("RC-CIWatchdog", state="Disabled", last_result=0,
                 triggers="MSFT_TaskDailyTrigger")]
    lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=time.time())
    assert [a for a in anomalies if "RC-CIWatchdog" in a] == [], anomalies
    mine = [ln for ln in lines if "RC-CIWatchdog" in ln]
    assert len(mine) == 1, lines
    assert "ACKNOWLEDGED" in mine[0]
    assert "2026-09-11" in mine[0]


def test_an_acknowledged_disarm_stays_visible_on_an_otherwise_clean_run(tmp_path):
    """NOT suppression. A clean run normally prints one summary line; an
    acknowledged disarm must still earn a line of its own below it.
    """
    now = time.time()
    _fresh_world(tmp_path, now)
    rows = [r for r in _all_weekly_rows(now) if r["name"] != "RC-WeeklyHygiene"]
    rows.append(_row("RC-WeeklyHygiene", state="Disabled", last_result=0,
                     triggers="MSFT_TaskWeeklyTrigger"))

    lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=now)
    assert anomalies == []
    assert len(lines) >= 2, lines
    assert any("RC-WeeklyHygiene" in ln and "ACKNOWLEDGED" in ln for ln in lines)
    assert "acknowledged" in lines[0]


def test_an_acknowledged_task_re_enabled_and_failing_still_reports_failure(tmp_path):
    """The acknowledgement covers the DISARM, nothing else. Re-armed and
    failing is a different failure and must not be masked.
    """
    now = time.time()
    _fresh_world(tmp_path, now)
    rows = [r for r in _all_weekly_rows(now) if r["name"] != "RC-WeeklyHygiene"]
    rows.append(_row("RC-WeeklyHygiene", state="Ready", last_result=2147946720,
                     last_run=_iso(now, _DAY), triggers="MSFT_TaskWeeklyTrigger"))

    _lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=now)
    mine = [a for a in anomalies if "RC-WeeklyHygiene" in a]
    assert len(mine) == 1, anomalies
    assert "FAILURE" in mine[0]
    assert "ACKNOWLEDGED" not in mine[0]


def test_an_acknowledged_task_re_enabled_with_a_stale_artifact_still_reports_it(tmp_path):
    """The other masking shape: re-armed, exit 0, producing nothing."""
    now = time.time()
    _fresh_world(tmp_path, now)
    for p in (tmp_path / "logs").glob("weekly_hygiene_*.log"):
        p.unlink()
    rows = _all_weekly_rows(now)

    _lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=now)
    assert any("RC-WeeklyHygiene" in a and "artifact" in a for a in anomalies), anomalies


def test_inbox_responder_found_enabled_is_the_anomaly(tmp_path):
    """INVERTED. CLAUDE.md: RC-InboxResponder stays DISARMED until an expiring
    agreement record arms it, so ENABLED is the finding.
    """
    now = time.time()
    _fresh_world(tmp_path, now)
    rows = _all_weekly_rows(now) + [
        _row("RC-InboxResponder", state="Ready", last_result=0,
             last_run=_iso(now, _DAY), triggers="MSFT_TaskDailyTrigger"),
    ]
    _lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=now)
    mine = [a for a in anomalies if "RC-InboxResponder" in a]
    assert len(mine) == 1, anomalies
    assert "ENABLED" in mine[0]
    assert "DISARMED" in mine[0]


def test_inbox_responder_disabled_is_the_required_state_not_an_anomaly(tmp_path):
    now = time.time()
    _fresh_world(tmp_path, now)
    rows = _all_weekly_rows(now) + [
        _row("RC-InboxResponder", state="Disabled", last_result=0,
             triggers="MSFT_TaskDailyTrigger"),
    ]
    lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=now)
    assert [a for a in anomalies if "RC-InboxResponder" in a] == [], anomalies
    assert any("RC-InboxResponder" in ln for ln in lines)


def test_inbox_responder_running_counts_as_enabled_for_the_inversion(tmp_path):
    """Any non-Disabled state is armed, not just Ready."""
    now = time.time()
    _fresh_world(tmp_path, now)
    rows = _all_weekly_rows(now) + [
        _row("RC-InboxResponder", state="Running",
             last_result=rc_facts.TASK_RESULT_RUNNING,
             last_run=_iso(now, _DAY), triggers="MSFT_TaskDailyTrigger"),
    ]
    _lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=now)
    assert any("RC-InboxResponder" in a and "ENABLED" in a for a in anomalies), anomalies


def test_acknowledged_lines_are_ascii(tmp_path):
    rows = [
        _row("RC-CIWatchdog", state="Disabled", last_result=0,
             triggers="MSFT_TaskDailyTrigger"),
        _row("RC-InboxResponder", state="Ready", last_result=0,
             triggers="MSFT_TaskDailyTrigger"),
    ]
    lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=time.time())
    for s in lines + anomalies:
        assert s.isascii(), s
        assert chr(0x2014) not in s and chr(0x2013) not in s


# ------------------------------------------- 8. armed BY an agreement record
#
# CLAUDE.md: "RC-InboxResponder stays DISARMED until an expiring agreement
# record arms it". The operator armed it on 2026-10-02 via
# ops/runtime/inbox_responder_agreement.json, and the inversion above ignored
# that record, so every session start carried a FALSE anomaly. The check now
# asks the RUNNER's own validator (tools/inbox_responder_runner.load_agreement)
# - no second parser - and stays fail-closed: missing, expired or malformed
# still reports ENABLED as the anomaly, and says why.

_COUNTERPARTIES = ["AA", "BB"]


def _valid_agreement(now: float, *, expires_in_s: float = 10 * _DAY) -> dict:
    from tools import inbox_responder_runner as runner

    def _naive(ts: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))

    return {
        "counterparties": list(_COUNTERPARTIES),
        "note": "test arming",
        "window_open": _naive(now - _DAY),
        "window_close": _naive(now + expires_in_s),
        "hop_budget": 8,
        "grammar": runner.GRAMMAR_A5,
        "expires": _naive(now + expires_in_s),
        "model": runner.MODEL,
        "contract_version": runner.CHANNEL_VERSION,
    }


def _write_agreement(root: Path, payload) -> Path:
    p = root / "ops" / "runtime" / "inbox_responder_agreement.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    p.write_text(text, encoding="utf-8")
    return p


def _responder_rows(now: float) -> list[dict]:
    return _all_weekly_rows(now) + [
        _row("RC-InboxResponder", state="Ready", last_result=0,
             last_run=_iso(now, 300), triggers="MSFT_TaskTimeTrigger"),
    ]


def _participants(monkeypatch):
    monkeypatch.setattr(
        rc_facts, "_inbox_participants",
        lambda root: {c: Path(root) / c / "moon_sync_inbox" for c in _COUNTERPARTIES},
    )


def test_inbox_responder_enabled_with_valid_agreement_is_armed_not_anomaly(tmp_path, monkeypatch):
    now = time.time()
    _fresh_world(tmp_path, now)
    _participants(monkeypatch)
    rec = _valid_agreement(now)
    _write_agreement(tmp_path, rec)

    lines, anomalies = rc_facts.task_health_lines(_responder_rows(now), root=tmp_path, now=now)
    assert [a for a in anomalies if "RC-InboxResponder" in a] == [], anomalies
    mine = [ln for ln in lines if "RC-InboxResponder" in ln]
    assert len(mine) == 1, lines
    assert "ARMED by agreement" in mine[0]
    assert f"expires {rec['expires']}" in mine[0]


def test_inbox_responder_stop_flag_is_never_reported_armed(tmp_path, monkeypatch):
    # The runner checks its STOP flag BEFORE the agreement (GATE:stop-pre), so
    # a valid agreement plus the flag is a responder that refuses every tick.
    from tools import inbox_responder_runner as runner

    now = time.time()
    _fresh_world(tmp_path, now)
    _participants(monkeypatch)
    _write_agreement(tmp_path, _valid_agreement(now))
    (tmp_path / "ops" / "runtime" / runner.STOP_FLAG_NAME).write_text("stop", encoding="utf-8")

    armed, detail = rc_facts.inbox_agreement_state(tmp_path, now)
    assert armed is False
    assert "stop" in detail.lower()
    lines, _anomalies = rc_facts.task_health_lines(_responder_rows(now), root=tmp_path, now=now)
    assert not any("ARMED by agreement" in ln for ln in lines), lines


def test_inbox_responder_enabled_with_expired_agreement_is_anomaly(tmp_path, monkeypatch):
    now = time.time()
    _fresh_world(tmp_path, now)
    _participants(monkeypatch)
    rec = _valid_agreement(now - 30 * _DAY, expires_in_s=5 * _DAY)
    _write_agreement(tmp_path, rec)

    _lines, anomalies = rc_facts.task_health_lines(_responder_rows(now), root=tmp_path, now=now)
    mine = [a for a in anomalies if "RC-InboxResponder" in a]
    assert len(mine) == 1, anomalies
    assert "ENABLED" in mine[0] and "DISARMED" in mine[0]
    assert "expired" in mine[0]


def test_inbox_responder_enabled_with_missing_agreement_is_anomaly(tmp_path, monkeypatch):
    now = time.time()
    _fresh_world(tmp_path, now)
    _participants(monkeypatch)

    _lines, anomalies = rc_facts.task_health_lines(_responder_rows(now), root=tmp_path, now=now)
    mine = [a for a in anomalies if "RC-InboxResponder" in a]
    assert len(mine) == 1, anomalies
    assert "ENABLED" in mine[0] and "DISARMED" in mine[0]
    assert "no_agreement" in mine[0]


def test_inbox_responder_enabled_with_malformed_agreement_is_anomaly(tmp_path, monkeypatch):
    now = time.time()
    _fresh_world(tmp_path, now)
    _participants(monkeypatch)
    _write_agreement(tmp_path, "{not json")

    _lines, anomalies = rc_facts.task_health_lines(_responder_rows(now), root=tmp_path, now=now)
    mine = [a for a in anomalies if "RC-InboxResponder" in a]
    assert len(mine) == 1, anomalies
    assert "malformed" in mine[0]


def test_inbox_responder_agreement_naming_unknown_counterparty_is_anomaly(tmp_path, monkeypatch):
    """Structurally valid JSON is not enough: the runner's own validator refuses
    a counterparty the participants map does not carry, and so must this."""
    now = time.time()
    _fresh_world(tmp_path, now)
    monkeypatch.setattr(rc_facts, "_inbox_participants", lambda root: {})
    _write_agreement(tmp_path, _valid_agreement(now))

    _lines, anomalies = rc_facts.task_health_lines(_responder_rows(now), root=tmp_path, now=now)
    mine = [a for a in anomalies if "RC-InboxResponder" in a]
    assert len(mine) == 1, anomalies
    assert "malformed:counterparties" in mine[0]


def test_inbox_responder_agreement_check_crash_fails_closed(tmp_path, monkeypatch):
    now = time.time()
    _fresh_world(tmp_path, now)

    def _boom(root):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(rc_facts, "_inbox_participants", _boom)
    _write_agreement(tmp_path, _valid_agreement(now))

    _lines, anomalies = rc_facts.task_health_lines(_responder_rows(now), root=tmp_path, now=now)
    mine = [a for a in anomalies if "RC-InboxResponder" in a]
    assert len(mine) == 1, anomalies
    assert "ENABLED" in mine[0]


def test_agreement_check_reuses_the_runner_validator():
    """No second parser: rc_facts must route through the runner's load_agreement."""
    src = Path(rc_facts.__file__).read_text(encoding="utf-8")
    assert "load_agreement" in src
    assert "window_close" not in src and "hop_budget" not in src

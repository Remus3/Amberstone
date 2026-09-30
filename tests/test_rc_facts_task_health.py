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
    rows = [_row("RC-WeeklyHygiene", state="Disabled", last_result=0,
                 triggers="MSFT_TaskWeeklyTrigger")]
    lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=time.time())
    blob = "\n".join(lines + anomalies)
    assert "DISARMED" in blob
    assert "RC-WeeklyHygiene" in blob
    assert any("DISARMED" in a and "RC-WeeklyHygiene" in a for a in anomalies)


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


def test_stale_threshold_is_two_scheduled_intervals():
    for sig in rc_facts.TASK_ARTIFACTS.values():
        assert sig.stale_after_s == 2.0 * sig.interval_s
        assert sig.interval_s == _WEEK


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

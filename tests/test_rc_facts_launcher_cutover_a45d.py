"""A45d: rc_facts after the ONLOGON-to-launcher cutover (PACKAGING_PLAN
section 5 step 5).

The cutover (tools/launcher_cutover.ps1 -Apply, 2026-10-31) UNREGISTERED the
seven app tasks; the rc-shell service host (ops/launcher/service_host.py) now
owns their services and there is NO autostart: RC runs only while the operator
has launched the app with --profile dev. So, in the SessionStart banner:

  1. An ABSENT launcher-owned task is the expected state, never an anomaly;
     a REGISTERED one is a second starter beside the host and IS one.
  2. The banner reports the shell host (ops/runtime/launcher_status.json):
     live / cleanly stopped / not launched since boot / gone without a quit.
  3. RC down while nothing is supposed to start it (no app task registered,
     no live host) is reported on one line, not as anomalies. RC down while
     the host is live, or while an app task is still registered, still is.
  4. The DS keepalive hold flag holds nothing once RC-DSKeepalive is not
     registered, so it is no longer an anomaly then.

Synthetic rows and a tmp_path tree only: nothing here probes the machine.
All authored content is 7-bit ASCII.
"""
from __future__ import annotations

import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from tools import rc_facts

ROOT = Path(__file__).resolve().parent.parent
CUTOVER_PS1 = ROOT / "tools" / "launcher_cutover.ps1"

_DAY = 86400.0


def _row(name, state="Ready", last_result=0, triggers=None):
    return {"name": name, "state": state, "last_result": last_result,
            "last_run": None, "next_run": None, "triggers": triggers}


def _utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _status(now: float, *, age_s: float = 2.0, state: str = "running",
            mode: str = "owned", services=None, reason=None) -> dict:
    if services is None:
        services = [
            {"name": "supervisor", "state": "running", "pid": 101, "port": 8888,
             "restarts": 0, "last_error": None},
            {"name": "lcu_agent", "state": "running", "pid": 102, "port": None,
             "restarts": 0, "last_error": None},
        ]
    return {"schema": 1, "host_pid": 4242, "parent_pid": 4241, "profile": "dev",
            "mode": mode, "state": state, "job": True,
            "origin": "https://127.0.0.1:8888", "healthy": True, "reason": reason,
            "services": services, "commands": [], "updated": _utc(now - age_s)}


# ------------------------------------------------ 1. expected-absent tasks


def test_launcher_owned_set_is_exactly_the_cutover_scripts_core_list():
    text = CUTOVER_PS1.read_text(encoding="utf-8")
    m = re.search(r"\$CoreTasks\s*=\s*@\((.*?)\)", text, re.S)
    assert m, "tools/launcher_cutover.ps1 no longer defines $CoreTasks"
    core = set(re.findall(r"'(RC-[A-Za-z0-9-]+)'", m.group(1)))
    assert len(core) == 7, core
    assert set(rc_facts.LAUNCHER_OWNED_TASKS) == core


def test_absent_launcher_owned_tasks_are_expected_not_anomalies(tmp_path):
    now = time.time()
    rows = [_row("RC-MissionControl", state="Running",
                 last_result=rc_facts.TASK_RESULT_RUNNING,
                 triggers="MSFT_TaskLogonTrigger")]
    lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=now)
    assert not any(t in a for a in anomalies for t in rc_facts.LAUNCHER_OWNED_TASKS)
    blob = "\n".join(lines)
    for name in rc_facts.LAUNCHER_OWNED_TASKS:
        assert name not in blob, "absent as expected: no per-task roll call"
    assert "7 moved to the shell host" in lines[0]


def test_a_registered_launcher_owned_task_is_an_anomaly(tmp_path):
    now = time.time()
    rows = [_row("RC-LCUAgent", state="Running",
                 last_result=rc_facts.TASK_RESULT_RUNNING,
                 triggers="MSFT_TaskLogonTrigger")]
    lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=now)
    mine = [a for a in anomalies if "RC-LCUAgent" in a]
    assert len(mine) == 1, anomalies
    assert "shell host" in mine[0] and "cutover" in mine[0]
    assert "6 moved to the shell host" in lines[0]


def test_a_disabled_launcher_owned_task_is_still_an_anomaly(tmp_path):
    # Plan S9: a DISABLED RC-DaemonSlayer makes DsWatchdog raise instead of
    # starting DS, so a disable is no safer than a live registration.
    rows = [_row("RC-DaemonSlayer", state="Disabled", last_result=0)]
    _lines, anomalies = rc_facts.task_health_lines(rows, root=tmp_path, now=time.time())
    assert any("RC-DaemonSlayer" in a for a in anomalies), anomalies


# ------------------------------------------------------- 2. the shell host


def test_no_status_file_is_down_by_design(tmp_path):
    host, lines, anomalies = rc_facts.shell_host_lines(None, None, now=time.time())
    assert host == rc_facts.HOST_DOWN
    assert anomalies == []
    assert "--profile dev" in "\n".join(lines)


def test_a_fresh_owned_host_is_live_and_lists_its_services():
    now = time.time()
    host, lines, anomalies = rc_facts.shell_host_lines(_status(now), None, now=now)
    assert host == rc_facts.HOST_LIVE
    assert anomalies == []
    blob = "\n".join(lines)
    assert "mode=owned" in blob and "pid=4242" in blob
    assert "supervisor=running" in blob and "lcu_agent=running" in blob


def test_a_failed_service_under_a_live_host_is_an_anomaly():
    now = time.time()
    services = [{"name": "hotkey_listener", "state": "failed", "pid": None,
                 "port": None, "restarts": 6, "last_error": "exit code 1"}]
    host, _lines, anomalies = rc_facts.shell_host_lines(
        _status(now, state="failed", services=services), None, now=now)
    assert host == rc_facts.HOST_LIVE
    assert len(anomalies) == 1, anomalies
    assert "hotkey_listener" in anomalies[0] and "FAILED" in anomalies[0]


def test_a_blocked_host_is_an_anomaly():
    now = time.time()
    host, _lines, anomalies = rc_facts.shell_host_lines(
        _status(now, state="blocked", mode="blocked", reason="port held"), None, now=now)
    assert host == rc_facts.HOST_LIVE
    assert any("BLOCKED" in a for a in anomalies), anomalies


def test_a_clean_quit_is_down_not_an_anomaly():
    now = time.time()
    host, lines, anomalies = rc_facts.shell_host_lines(
        _status(now, age_s=3600, state="halted", reason="stdin_stop"), None, now=now)
    assert host == rc_facts.HOST_DOWN
    assert anomalies == []
    assert "stdin_stop" in "\n".join(lines)


def test_a_stale_running_status_from_before_the_last_boot_is_down():
    now = time.time()
    doc = _status(now, age_s=2 * _DAY, state="running")
    host, _lines, anomalies = rc_facts.shell_host_lines(
        doc, None, now=now, last_boot_ts=now - _DAY)
    assert host == rc_facts.HOST_DOWN
    assert anomalies == []


def test_a_stale_running_status_since_the_last_boot_is_a_crash():
    now = time.time()
    doc = _status(now, age_s=600, state="running")
    host, _lines, anomalies = rc_facts.shell_host_lines(
        doc, None, now=now, last_boot_ts=now - _DAY)
    assert host == rc_facts.HOST_CRASHED
    assert len(anomalies) == 1 and "clean quit" in anomalies[0]


def test_an_unreadable_status_is_unmeasured_and_loud():
    host, _lines, anomalies = rc_facts.shell_host_lines(
        None, "JSONDecodeError", now=time.time())
    assert host == rc_facts.HOST_UNKNOWN
    assert anomalies and "UNMEASURED" in anomalies[0]


def test_read_launcher_status_absent_ok_and_corrupt(tmp_path):
    assert rc_facts.read_launcher_status(tmp_path) == (None, None)
    path = tmp_path / "ops" / "runtime" / "launcher_status.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"state": "halted"}), encoding="utf-8")
    assert rc_facts.read_launcher_status(tmp_path) == ({"state": "halted"}, None)
    path.write_text("{not json", encoding="utf-8")
    doc, err = rc_facts.read_launcher_status(tmp_path)
    assert doc is None and err


def test_shell_host_lines_are_ascii():
    now = time.time()
    services = [{"name": "lcu_agent", "state": "failed", "pid": None,
                 "last_error": "boom " + chr(0x2014) + " x"}]
    for doc in (None, _status(now), _status(now, state="failed", services=services),
                _status(now, age_s=600)):
        _h, lines, anomalies = rc_facts.shell_host_lines(doc, None, now=now)
        for s in lines + anomalies:
            assert s.isascii(), s


# ------------------------------------------------------ 3. main() end to end


def _world(tmp_path, monkeypatch, *, tasks, port_up, status=None, alive=False):
    health = tmp_path / "health.json"
    health.write_text(json.dumps({"pid": 1528, "alive": alive, "last_reload_ok": True}),
                      encoding="utf-8")
    if status is not None:
        path = tmp_path / "ops" / "runtime" / "launcher_status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status), encoding="utf-8")
    monkeypatch.setattr(rc_facts, "_HEALTH", health)
    monkeypatch.setattr(rc_facts, "_APP", tmp_path)
    monkeypatch.setattr(rc_facts, "_port_listening", lambda *a, **k: port_up)
    monkeypatch.setattr(rc_facts, "_health_all", dict)
    monkeypatch.setattr(rc_facts, "_http_get_json", lambda *a, **k: None)
    monkeypatch.setattr(rc_facts, "_legion_tasks", lambda: tasks)
    monkeypatch.setattr(rc_facts, "_last_boot_iso", lambda: None)
    monkeypatch.setattr(rc_facts, "_inbox_section", lambda *a, **k: ([], [], set()))
    # The machine-wide slot bucket and the drift-alert channel are LIVE state
    # (a stale lane slot lock read "pid ... not alive" into the anomaly block
    # during the kit v26 suite); this world is synthetic, so both read empty.
    from tools import slot_bucket_audit, upstream_drift_check
    monkeypatch.setattr(slot_bucket_audit, "anomaly_lines", lambda *a, **k: [])
    monkeypatch.setattr(upstream_drift_check, "unacked_alert_lines", lambda *a, **k: [])
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    assert rc_facts.main(session=None) == 0
    return buf.getvalue()


def _anomaly_block(text: str) -> str:
    head = "## ! Anomalies"
    return text.split(head, 1)[1].split("\n\n", 2)[1] if head in text else ""


_MISSION = _row("RC-MissionControl", state="Running",
                last_result=rc_facts.TASK_RESULT_RUNNING, triggers="MSFT_TaskLogonTrigger")


def test_main_rc_down_with_no_host_and_no_app_task_is_by_design(tmp_path, monkeypatch):
    text = _world(tmp_path, monkeypatch, tasks=[_MISSION], port_up=False)
    block = _anomaly_block(text)
    assert "not alive" not in block
    assert "not listening" not in block
    assert "not posting" not in block
    # Still printed, on its own line: nothing is lost, it is just not an alarm.
    assert "dashboard :8888 not listening" in text
    assert "--profile dev" in text


def test_main_rc_down_under_a_live_host_is_still_an_anomaly(tmp_path, monkeypatch):
    now = time.time()
    text = _world(tmp_path, monkeypatch, tasks=[_MISSION], port_up=False,
                  status=_status(now))
    block = _anomaly_block(text)
    assert "dashboard :8888 not listening" in block


def test_main_rc_down_with_an_app_task_still_registered_is_an_anomaly(tmp_path, monkeypatch):
    sup = _row("RC-Supervisor", state="Ready", last_result=0,
               triggers="MSFT_TaskLogonTrigger")
    text = _world(tmp_path, monkeypatch, tasks=[_MISSION, sup], port_up=False)
    block = _anomaly_block(text)
    assert "dashboard :8888 not listening" in block
    assert "RC-Supervisor" in block


def test_main_rc_down_with_an_unmeasured_task_probe_stays_an_anomaly(tmp_path, monkeypatch):
    text = _world(tmp_path, monkeypatch, tasks=None, port_up=False)
    assert "dashboard :8888 not listening" in _anomaly_block(text)


def test_main_reports_rc_up_outside_the_shell_host(tmp_path, monkeypatch):
    text = _world(tmp_path, monkeypatch, tasks=[_MISSION], port_up=True, alive=True)
    assert "outside the shell host" in text
    assert "outside the shell host" not in _anomaly_block(text)


def test_main_prints_the_shell_host_line(tmp_path, monkeypatch):
    now = time.time()
    text = _world(tmp_path, monkeypatch, tasks=[_MISSION], port_up=True, alive=True,
                  status=_status(now))
    assert "- Shell host: pid=4242 mode=owned" in text


# ------------------------------------------------- 4. the DS keepalive hold


def _hold(tmp_path):
    flag = tmp_path / "ops" / "runtime" / "DS_KEEPALIVE_STOP"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_bytes(b"legion_off")


def test_keepalive_hold_is_moot_when_the_keepalive_task_is_not_registered(tmp_path):
    _hold(tmp_path)
    assert rc_facts.ds_keepalive_hold_anomalies(tmp_path, tasks=[_MISSION]) == []


def test_keepalive_hold_still_flags_when_the_task_is_registered(tmp_path):
    _hold(tmp_path)
    rows = [_MISSION, _row("RC-DSKeepalive", state="Running")]
    assert len(rc_facts.ds_keepalive_hold_anomalies(tmp_path, tasks=rows)) == 1


def test_keepalive_hold_still_flags_when_the_task_probe_failed(tmp_path):
    _hold(tmp_path)
    assert len(rc_facts.ds_keepalive_hold_anomalies(tmp_path, tasks=None)) == 1

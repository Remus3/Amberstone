"""MAIN FIX 2026-10-21 1254 item #17 (rc_facts half): the SessionStart probes
must fit inside the hook timeout.

Measured at main 915300765 before the fix: main() ran its live probes one
after another - two port probes (3 attempts x 1.0 s each), two HTTP GETs
(2.5 s each), the scheduled-task PowerShell probe (timeout 8.0 s) and the
last-boot PowerShell probe (2.0 s) - a worst case of about 21 s against the
harness's 8 s SessionStart timeout. main() prints only at its END, so a kill
dropped the whole block, the session checklist included.

The fix runs the probes concurrently under ONE deadline, clamps every probe's
own timeout to that deadline, and reports a probe that did not finish as
UNMEASURED - never as down, never silently as healthy.
"""
import io
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from tools import rc_facts

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "ops" / "claude_settings.example.json"


@pytest.fixture
def release():
    """Hung probes wait on this; teardown lets the daemon threads exit."""
    event = threading.Event()
    yield event
    event.set()


def _world(tmp_path, monkeypatch):
    health = tmp_path / "health.json"
    health.write_text('{"pid": 1, "alive": true, "last_reload_ok": true}',
                      encoding="utf-8")
    monkeypatch.setattr(rc_facts, "_HEALTH", health)
    monkeypatch.setattr(rc_facts, "_APP", tmp_path)
    monkeypatch.setattr(rc_facts, "_inbox_section", lambda *a, **k: ([], [], set()))
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    return buf


def _hang(release, value):
    def probe(*_a, **_k):
        release.wait(30)
        return value
    return probe


def test_main_returns_within_the_budget_when_every_probe_hangs(
        tmp_path, monkeypatch, release):
    buf = _world(tmp_path, monkeypatch)
    monkeypatch.setattr(rc_facts, "PROBE_BUDGET_S", 0.5)
    monkeypatch.setattr(rc_facts, "_port_listening", _hang(release, True))
    monkeypatch.setattr(rc_facts, "_health_all", _hang(release, {}))
    monkeypatch.setattr(rc_facts, "_http_get_json", _hang(release, None))
    monkeypatch.setattr(rc_facts, "_legion_tasks", _hang(release, []))
    monkeypatch.setattr(rc_facts, "_last_boot_iso", _hang(release, None))
    start = time.monotonic()
    assert rc_facts.main(session=None) == 0
    elapsed = time.monotonic() - start
    assert elapsed < 0.5 + rc_facts.PROBE_JOIN_GRACE_S + 1.0, elapsed
    text = buf.getvalue()
    assert "# RC live state" in text, "the block must still print"
    assert "unmeasured" in text
    for name in ("port8888", "port8889", "health_all", "tasks", "last_boot", "state"):
        assert name in text, name
    # Not finished is not DOWN: no listener anomaly for a probe that never answered.
    assert "not listening" not in text


def test_fast_probes_report_exactly_as_before(tmp_path, monkeypatch):
    buf = _world(tmp_path, monkeypatch)
    monkeypatch.setattr(rc_facts, "_port_listening", lambda *a, **k: False)
    monkeypatch.setattr(rc_facts, "_health_all", lambda: {})
    monkeypatch.setattr(rc_facts, "_http_get_json", lambda *a, **k: None)
    monkeypatch.setattr(rc_facts, "_legion_tasks", lambda: [])
    monkeypatch.setattr(rc_facts, "_last_boot_iso", lambda: None)
    assert rc_facts.main(session=None) == 0
    text = buf.getvalue()
    assert "dashboard :8888 not listening" in text
    assert "vision server :8889 not listening" in text
    assert "unmeasured" not in text


def test_a_probe_that_raises_is_unmeasured_not_a_crash(tmp_path, monkeypatch):
    buf = _world(tmp_path, monkeypatch)

    def boom(*_a, **_k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(rc_facts, "_port_listening", lambda *a, **k: True)
    monkeypatch.setattr(rc_facts, "_health_all", lambda: {})
    monkeypatch.setattr(rc_facts, "_http_get_json", lambda *a, **k: None)
    monkeypatch.setattr(rc_facts, "_legion_tasks", boom)
    monkeypatch.setattr(rc_facts, "_last_boot_iso", lambda: None)
    assert rc_facts.main(session=None) == 0
    assert "# RC live state" in buf.getvalue()


# ------------------------------------------------- each probe obeys the deadline

def test_the_task_probe_timeout_is_clamped_under_the_runner(monkeypatch):
    seen = []

    def fake_run(*_a, **kw):
        seen.append(kw["timeout"])
        raise rc_facts.subprocess.TimeoutExpired("powershell.exe", kw["timeout"])

    monkeypatch.setattr(rc_facts.subprocess, "run", fake_run)
    got, late = rc_facts._run_probes({"tasks": rc_facts._legion_tasks}, 1.0)
    assert got == {"tasks": None} and late == []
    assert seen and 0 < seen[0] <= 1.0, seen


def test_a_direct_call_keeps_its_own_timeout(monkeypatch):
    seen = []

    def fake_run(*_a, **kw):
        seen.append(kw["timeout"])
        raise rc_facts.subprocess.TimeoutExpired("powershell.exe", kw["timeout"])

    monkeypatch.setattr(rc_facts.subprocess, "run", fake_run)
    assert rc_facts._legion_tasks() is None
    assert seen == [8.0]


def test_the_http_timeout_is_clamped_under_the_runner(monkeypatch):
    seen = []

    def fake_urlopen(_req, timeout=None, context=None):
        seen.append(timeout)
        raise OSError("synthetic")

    monkeypatch.setattr(rc_facts.urllib.request, "urlopen", fake_urlopen)
    rc_facts._run_probes({"state": lambda: rc_facts._http_get_json("https://x")}, 0.75)
    assert seen and 0 < seen[0] <= 0.75, seen
    seen.clear()
    rc_facts._http_get_json("https://x")
    assert seen == [rc_facts._TIMEOUT]


def test_the_port_probe_stops_retrying_at_the_deadline(monkeypatch):
    timeouts = []

    class SlowSocket:
        def __init__(self, *_a):
            pass

        def settimeout(self, value):
            timeouts.append(value)
            self._t = value

        def connect(self, _addr):
            time.sleep(self._t)
            raise socket.timeout()

        def close(self):
            pass

    monkeypatch.setattr(rc_facts.socket, "socket", SlowSocket)
    start = time.monotonic()
    got, late = rc_facts._run_probes({"port": lambda: rc_facts._port_listening(1)}, 0.6)
    assert time.monotonic() - start < 0.6 + rc_facts.PROBE_JOIN_GRACE_S + 0.5
    assert late == [] and got == {"port": False}
    assert all(0 < t <= 0.6 for t in timeouts), timeouts


# ---------------------------------------------------------------- the numbers

def test_the_budget_fits_inside_the_record_budget():
    assert rc_facts.PROBE_BUDGET_S + rc_facts.PROBE_JOIN_GRACE_S < (
        rc_facts.SESSIONSTART_RECORD_BUDGET_S - 1.0)


def test_the_template_hook_timeout_leaves_room_for_the_budget():
    hooks = json.loads(TEMPLATE.read_text(encoding="utf-8"))["hooks"]["SessionStart"]
    timeouts = [h.get("timeout") for group in hooks for h in group["hooks"]
                if h["command"].rstrip().endswith('rc_facts.py"')]
    assert timeouts, "the SessionStart rc_facts hook is not in the template"
    assert all(t >= rc_facts.SESSIONSTART_RECORD_BUDGET_S + 1.0 for t in timeouts)

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
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests._module_view import ModuleView, bind_module_view, bind_socket_class
from tests._timing_budget import fleet_test_guard
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
    assert elapsed < fleet_test_guard.budget(0.5 + rc_facts.PROBE_JOIN_GRACE_S + 1.0), elapsed
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

def _record_run_timeouts(monkeypatch):
    """rc_facts' subprocess.run records its timeout and times out."""
    seen = []

    def fake_run(*_a, **kw):
        seen.append(kw["timeout"])
        raise rc_facts.subprocess.TimeoutExpired("powershell.exe", kw["timeout"])

    # rc_facts' own names only, never the shared modules (tests/_module_view.py).
    bind_module_view(monkeypatch, rc_facts, "subprocess", run=fake_run)
    return seen


def _record_urlopen_timeouts(monkeypatch):
    """rc_facts' urllib.request.urlopen records its timeout and fails."""
    seen = []

    def fake_urlopen(_req, timeout=None, context=None):
        seen.append(timeout)
        raise OSError("synthetic")

    bind_module_view(monkeypatch, rc_facts, "urllib",
                     request=ModuleView(urllib.request, urlopen=fake_urlopen))
    return seen


def test_the_task_probe_timeout_is_clamped_under_the_runner(monkeypatch):
    seen = _record_run_timeouts(monkeypatch)
    got, late = rc_facts._run_probes({"tasks": rc_facts._legion_tasks}, 1.0)
    assert got == {"tasks": None} and late == []
    assert seen and 0 < seen[0] <= 1.0, seen


def test_a_direct_call_keeps_its_own_timeout(monkeypatch):
    seen = _record_run_timeouts(monkeypatch)
    assert rc_facts._legion_tasks() is None
    assert seen == [8.0]


def test_another_threads_run_and_urlopen_reach_the_real_functions(monkeypatch):
    """Same root cause as the socket case below: a fake bound on the shared
    subprocess / urllib.request module also records - and breaks - every
    other thread's call in the worker (an RC poller's urlopen(timeout=3)),
    so `seen == [8.0]` / `seen == [_TIMEOUT]` read foreign timeouts."""
    go, done, errors = threading.Event(), threading.Event(), []

    def foreign():
        go.wait(5)
        try:
            subprocess.run([sys.executable, "-c", "pass"], timeout=60, check=True)
        except Exception as exc:  # noqa: BLE001 - a faked foreign call is the finding
            errors.append(exc)
        try:
            urllib.request.urlopen("http://127.0.0.1:9/", timeout=0.5)
        except urllib.error.URLError:
            pass  # the REAL urlopen: nothing listens on :9
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        done.set()

    worker = threading.Thread(target=foreign, name="foreign-io-user", daemon=True)
    worker.start()
    run_seen = _record_run_timeouts(monkeypatch)
    url_seen = _record_urlopen_timeouts(monkeypatch)
    go.set()
    assert done.wait(60)
    worker.join(5)
    assert run_seen == [] and url_seen == [], (run_seen, url_seen)
    assert errors == [], errors


def test_the_http_timeout_is_clamped_under_the_runner(monkeypatch):
    seen = _record_urlopen_timeouts(monkeypatch)
    rc_facts._run_probes({"state": lambda: rc_facts._http_get_json("https://x")}, 0.75)
    assert seen and 0 < seen[0] <= 0.75, seen
    seen.clear()
    rc_facts._http_get_json("https://x")
    assert seen == [rc_facts._TIMEOUT]


_REAL_SOCKET = socket.socket


def _probe_a_port_that_never_answers(monkeypatch, budget_s=0.6):
    """Run the port probe under _run_probes against a socket whose connect
    sleeps its whole timeout, and return every timeout the probe set."""
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

    # rc_facts' own `socket` name only: other threads in this worker keep the
    # real module (tests/_module_view.py).
    bind_socket_class(monkeypatch, rc_facts, SlowSocket)
    start = time.monotonic()
    got, late = rc_facts._run_probes({"port": lambda: rc_facts._port_listening(1)},
                                     budget_s)
    assert time.monotonic() - start < fleet_test_guard.budget(
        budget_s + rc_facts.PROBE_JOIN_GRACE_S + 0.5)
    assert late == [] and got == {"port": False}
    assert timeouts, "the probe never opened a socket - the check below is vacuous"
    return timeouts


def test_the_port_probe_stops_retrying_at_the_deadline(monkeypatch):
    timeouts = _probe_a_port_that_never_answers(monkeypatch)
    assert all(0 < t <= 0.6 for t in timeouts), timeouts


def _virtual_clock_and_a_timing_out_socket(monkeypatch):
    """rc_facts' own clock is virtual and moves only inside connect, by the
    timeout the probe set, so a run is deterministic. Returns (clock,
    attempts): attempts holds (start, the probe thread's deadline or None,
    timeout) per connect."""
    clock = [100.0]
    attempts = []

    class TimingOutSocket:
        def __init__(self, *_a):
            self._t = None

        def settimeout(self, value):
            self._t = value

        def connect(self, _addr):
            attempts.append((clock[0], getattr(rc_facts._probe_ctx, "deadline", None),
                             self._t))
            clock[0] += self._t  # the whole timeout elapses, then it times out
            raise socket.timeout()

        def close(self):
            pass

    bind_socket_class(monkeypatch, rc_facts, TimingOutSocket)
    bind_module_view(monkeypatch, rc_facts, "time", monotonic=lambda: clock[0])
    # The runner's join is the one real-time wait left. The virtual clock stops
    # when the probe thread does, so the join returns as that thread ends.
    monkeypatch.setattr(rc_facts, "PROBE_JOIN_GRACE_S", 30.0)
    return clock, attempts


def test_no_port_probe_attempt_starts_after_the_deadline(monkeypatch):
    """RM-802. The timeout bound above cannot see a retry that STARTS after
    the deadline: _PROBE_MIN_TIMEOUT_S floors that retry's timeout at 0.05 s,
    under every bound, so with the _probe_expired() check in _port_listening
    removed all its tests stayed green. On the virtual clock each attempt's
    start is compared to the deadline instead."""
    clock, attempts = _virtual_clock_and_a_timing_out_socket(monkeypatch)
    budget_s = 1.5  # attempt 1 gets 1.0 s, attempt 2 the last 0.5 s, attempt 3 none
    got, late = rc_facts._run_probes({"port": lambda: rc_facts._port_listening(1)},
                                     budget_s)
    assert late == [] and got == {"port": False}
    deadline = 100.0 + budget_s
    assert attempts and all(d == deadline for _s, d, _t in attempts), attempts
    after = [a for a in attempts if a[0] >= deadline]
    assert after == [], f"connect attempt(s) started at or after the deadline: {after}"
    # Not vacuous: the probe ran its clock to the deadline with an attempt to
    # spare, so only the expiry check stands between it and one more connect.
    assert clock[0] >= deadline and len(attempts) == 2, (clock, attempts)


@pytest.mark.parametrize("late_by", [0.0, 0.5], ids=["at", "past"])
def test_a_port_probe_entered_at_or_past_the_deadline_never_connects(
        monkeypatch, late_by):
    """RM-802 follow-up. The test above starts 1.5 s before the deadline, so
    its FIRST attempt is never checked: an expiry check moved after the
    timed-out connect, or skipped on loop pass 0, still passes it. Entered
    with the deadline already reached (earlier work in the probe thread used
    the budget), _port_listening must open no connect at all - "no attempt
    starts after it" (its docstring)."""
    clock, attempts = _virtual_clock_and_a_timing_out_socket(monkeypatch)
    budget_s = 1.0
    deadline = clock[0] + budget_s

    def probe_entered_late():
        clock[0] = deadline + late_by
        return rc_facts._port_listening(1)

    got, late = rc_facts._run_probes({"port": probe_entered_late}, budget_s)
    assert late == [] and got == {"port": False}
    assert attempts == [], f"connect attempt(s) at or past the deadline: {attempts}"
    # Not vacuous: with no deadline (a direct call) the same probe does reach
    # the fake socket, once per attempt.
    assert rc_facts._port_listening(1) is False
    assert [(d, t) for _s, d, t in attempts] == [(None, 1.0)] * 3, attempts


def test_another_threads_socket_is_neither_recorded_nor_faked(monkeypatch):
    """CI run 39877078008 (xdist gw0, linux): [0.5997.., 2.0, 3, 3, 3, ...].
    The probe's one timeout respected the budget; 2.0 and 3 were set by
    sockets OTHER threads in the same worker opened while the fake was bound
    on the process-wide socket module. The fake must reach rc_facts' probe
    only: another thread neither lands in its record nor gets a fake socket."""
    stop = threading.Event()
    opened = []

    def foreign():
        while not stop.is_set():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2.0)
                s.settimeout(3)
                opened.append(type(s))
                s.close()
            except Exception as exc:  # noqa: BLE001 - a broken foreign socket is the finding
                opened.append(exc)
            time.sleep(0.005)

    worker = threading.Thread(target=foreign, name="foreign-socket-user", daemon=True)
    worker.start()
    try:
        before = len(opened)
        timeouts = _probe_a_port_that_never_answers(monkeypatch)
        during = opened[before:]
    finally:
        stop.set()
        worker.join(5)
    assert during, "the foreign thread opened no socket while the fake was bound"
    assert all(0 < t <= 0.6 for t in timeouts), timeouts
    assert all(kind is _REAL_SOCKET for kind in during), during[:5]


# ---------------------------------------------------------------- the numbers

def test_the_budget_fits_inside_the_record_budget():
    assert rc_facts.PROBE_BUDGET_S + rc_facts.PROBE_JOIN_GRACE_S < (
        rc_facts.SESSIONSTART_RECORD_BUDGET_S - 1.0)


def test_the_template_hook_timeout_leaves_room_for_the_budget():
    hooks = json.loads(TEMPLATE.read_text(encoding="utf-8"))["hooks"]["SessionStart"]
    # The no-argument rc_facts line; RM-782 adds a ` || { ... }` shell tail
    # after the script token, so match the token, not the end of the line.
    timeouts = [h.get("timeout") for group in hooks for h in group["hooks"]
                if h["command"].split(" || ", 1)[0].rstrip().endswith('rc_facts.py"')]
    assert timeouts, "the SessionStart rc_facts hook is not in the template"
    assert all(t >= rc_facts.SESSIONSTART_RECORD_BUDGET_S + 1.0 for t in timeouts)

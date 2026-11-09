"""s144 true-audit cycle 76: dashboard/_vision_watchdog.py hardening.

Five findings, each pinned here red-first:

F1 (RM-1218) ``is_vision_pid`` decided "this :8889 holder is a vision
   server, taskkill it" with a SUBSTRING test over the space-joined command
   line, so a foreign listener whose command line merely MENTIONED
   ``moon_vision_server`` (an editor with the file open, a grep, a shell
   running a launch string) or any ``python -m vision_server_<x>`` was killed.
   vision_server/_reap.py dropped the same test in cycle 75; the watchdog now
   uses the SAME structural predicate, moved to the dependency-free
   core/vision_server_argv.py so the RC process never imports vision_server.
F2 the holder was judged a vision server BEFORE the py-spy dump (up to 30 s)
   and killed by bare pid AFTER it, so a holder that exited during the dump
   and whose pid was reused was killed blind. The verdict is re-taken right
   before the kill.
F3 ``find_listener_pid`` logged a failed lookup (psutil missing, AccessDenied)
   at DEBUG only, so the watchdog silently read every hung holder as gone (no
   kill, a co-binding respawn every grace window). It now warns once per
   failure streak.
F4 a NaN / zero / negative / huge / non-number timing value broke the loop:
   ``probe_health`` with a NaN or zero timeout reported a HEALTHY server as
   hung (and the watchdog kills hung servers), a huge or string timeout made
   the "never raises" probe raise, a huge interval raised OverflowError out
   of ``stop.wait`` and ended the watchdog thread, a zero interval was a busy
   loop, and a negative grace disabled the spawn back-off. Values are now
   validated where they enter.
F5 the comment over the old marker tuple claimed "same set as
   vision_server/_reap.py", false since cycle 75.
"""
from __future__ import annotations

import logging
import math
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _wd():
    from dashboard import _vision_watchdog as vw
    return vw


@pytest.fixture(autouse=True)
def _fresh_lookup_state():
    # getattr: the red run against the pre-fix module has no such hook.
    reset = getattr(_wd(), "_reset_lookup_warning", lambda: None)
    reset()
    yield
    reset()


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class _Rec:
    def __init__(self, vision_answers, holder=4242):
        self.vision_answers = list(vision_answers)
        self.vision_calls = 0
        self.holder = holder
        self.kills: list[int] = []
        self.spawns = 0
        self.captures: list[int] = []

    def probe(self, port, timeout_s):
        return "hung"

    def find_holder(self, port):
        return self.holder

    def is_vision(self, pid):
        self.vision_calls += 1
        if self.vision_answers:
            return self.vision_answers.pop(0)
        return True

    def kill(self, pid):
        self.kills.append(pid)
        return True

    def spawn(self, app_dir):
        self.spawns += 1
        return 7777

    def capture(self, pid, app_dir):
        self.captures.append(pid)


def _build(rec, **kw):
    vw = _wd()
    params = dict(interval_s=10.0, timeout_s=1.0, fail_threshold=3,
                  grace_s=60.0, max_grace_s=240.0)
    params.update(kw)
    return vw.VisionWatchdog(
        Path("unused-app-dir"), port=1, probe=rec.probe,
        find_holder=rec.find_holder, is_vision=rec.is_vision, kill=rec.kill,
        spawn=rec.spawn, capture=rec.capture, clock=_Clock(), **params)


def _is_vision_with_cmdline(cmdline):
    vw = _wd()
    proc = mock.Mock()
    proc.cmdline.return_value = cmdline
    with mock.patch("psutil.Process", return_value=proc):
        return vw.is_vision_pid(1)


# -- F1: structural, shared predicate ---------------------------------------------
@pytest.mark.parametrize("cmdline", [
    ["rg.exe", "moon_vision_server"],
    ["Code.exe", "C:/Example App/moon_vision_server.py"],
    ["notepad.exe", "moon_vision_server.py"],
    ["bash.exe", "-c", "pythonw moon_vision_server.py"],
    ["python.exe", "-m", "vision_server_tools"],
    ["python.exe", "-m", "pytest", "tests/test_moon_vision_server.py"],
    ["python.exe", "tools/grep_for.py", "moon_vision_server.py"],
    ["python.exe", "-c", "import moon_vision_server"],
])
def test_a_foreign_holder_that_mentions_the_name_is_not_a_vision_pid(cmdline):
    assert _is_vision_with_cmdline(cmdline) is False


@pytest.mark.parametrize("cmdline", [
    ["pythonw.exe", "C:/Example App/moon_vision_server.py"],
    ["C:\\Program Files\\Python\\python.exe", "-B", "C:\\Example App\\moon_vision_server.py"],
    ["python3", "moon_vision_server.pyw"],
    ["python.exe", "-m", "vision_server"],
])
def test_a_real_vision_launch_is_a_vision_pid(cmdline):
    assert _is_vision_with_cmdline(cmdline) is True


@pytest.mark.parametrize("cmdline", [None, [], "pythonw moon_vision_server.py",
                                     ["pythonw.exe", 5]])
def test_an_unusable_cmdline_is_not_a_vision_pid(cmdline):
    assert _is_vision_with_cmdline(cmdline) is False


def test_an_unreadable_process_is_not_a_vision_pid():
    vw = _wd()
    import psutil
    with mock.patch("psutil.Process", side_effect=psutil.AccessDenied(1)):
        assert vw.is_vision_pid(1) is False


def test_the_watchdog_and_the_reap_share_one_predicate():
    from core import vision_server_argv
    from vision_server import _reap
    vw = _wd()
    assert vw.is_vision_server_argv is vision_server_argv.is_vision_server_argv
    assert _reap.is_vision_server_argv is vision_server_argv.is_vision_server_argv


def test_importing_the_watchdog_does_not_import_vision_server():
    code = ("import sys; import dashboard._vision_watchdog; "
            "print(sorted(m for m in sys.modules "
            "if m == 'vision_server' or m.startswith('vision_server.')))")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(REPO),
                       capture_output=True, text=True, timeout=120,
                       creationflags=_NO_WINDOW, check=False)
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.strip() == "[]"


def test_the_predicate_module_imports_nothing_from_rc():
    src = (REPO / "core" / "vision_server_argv.py").read_text(encoding="utf-8")
    imports = [ln.strip() for ln in src.splitlines()
               if ln.startswith(("import ", "from "))]
    assert imports == ["from __future__ import annotations", "import re"]


# -- F5: no stale marker set or shared-set claim ------------------------------------
def test_the_substring_marker_set_and_its_stale_claim_are_gone():
    src = (REPO / "dashboard" / "_vision_watchdog.py").read_text(encoding="utf-8")
    assert "_MARKERS" not in src
    assert "same set as" not in src
    assert "is_vision_server_argv" in src


# -- F2: the verdict is re-taken right before the kill -------------------------------
def test_a_holder_that_stops_being_a_vision_server_during_the_dump_is_not_killed():
    rec = _Rec([True, False])
    wd = _build(rec)
    results = [wd.tick() for _ in range(3)]
    assert results[-1] == "replaced"
    assert rec.captures == [4242]
    assert rec.kills == []
    assert rec.spawns == 1
    assert rec.vision_calls == 2


def test_a_holder_still_a_vision_server_after_the_dump_is_killed():
    rec = _Rec([True, True])
    wd = _build(rec)
    for _ in range(3):
        wd.tick()
    assert rec.kills == [4242]
    assert rec.vision_calls == 2


def test_a_recheck_that_raises_is_not_a_kill():
    rec = _Rec([True])
    calls = {"n": 0}

    def is_vision(pid):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("psutil fell over")
        return True

    rec.is_vision = is_vision
    wd = _build(rec)
    for _ in range(3):
        wd.tick()
    assert rec.kills == []
    assert rec.spawns == 1


# -- F3: a failed listener lookup is visible ------------------------------------------
def _conn(port, pid):
    import psutil
    return SimpleNamespace(status=psutil.CONN_LISTEN,
                           laddr=SimpleNamespace(port=port), pid=pid)


def _warnings(caplog):
    return [r for r in caplog.records
            if r.name == "rc.web_dashboard" and r.levelno >= logging.WARNING]


def test_a_failed_lookup_warns_once_per_streak(caplog):
    vw = _wd()
    import psutil
    caplog.set_level(logging.DEBUG, logger="rc.web_dashboard")
    with mock.patch("psutil.net_connections",
                    side_effect=psutil.AccessDenied(1)):
        assert vw.find_listener_pid(8889) is None
        assert vw.find_listener_pid(8889) is None
    assert len(_warnings(caplog)) == 1
    assert "AccessDenied" in _warnings(caplog)[0].getMessage()
    with mock.patch("psutil.net_connections", return_value=[_conn(8889, 77)]):
        assert vw.find_listener_pid(8889) == 77
    with mock.patch("psutil.net_connections", side_effect=OSError("boom")):
        assert vw.find_listener_pid(8889) is None
    assert len(_warnings(caplog)) == 2


def test_an_empty_table_is_not_a_failure(caplog):
    vw = _wd()
    caplog.set_level(logging.DEBUG, logger="rc.web_dashboard")
    with mock.patch("psutil.net_connections", return_value=[]):
        assert vw.find_listener_pid(8889) is None
    assert _warnings(caplog) == []


def test_a_missing_psutil_warns(caplog):
    vw = _wd()
    caplog.set_level(logging.DEBUG, logger="rc.web_dashboard")
    with mock.patch.dict(sys.modules, {"psutil": None}):
        assert vw.find_listener_pid(8889) is None
    assert len(_warnings(caplog)) == 1
    assert "psutil" in _warnings(caplog)[0].getMessage()


def test_the_lookup_still_finds_the_listener():
    vw = _wd()
    conns = [_conn(1234, 5), _conn(8889, 0), _conn(8889, 66)]
    with mock.patch("psutil.net_connections", return_value=conns):
        assert vw.find_listener_pid(8889) == 66


# -- F4: timing values are validated where they enter --------------------------------
class _Health(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib handler name
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        pass


@pytest.fixture
def health_port():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Health)
    t = threading.Thread(target=srv.serve_forever, daemon=True,
                         name="s144t076-health")
    t.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(10)


@pytest.mark.parametrize("bad", [float("nan"), 0, 0.0, -1.0, float("inf"),
                                 1e12, 10 ** 400, "3", None, True])
def test_a_bad_probe_timeout_still_probes_a_healthy_server_ok(health_port, bad):
    vw = _wd()
    assert vw.probe_health(health_port, bad) == vw.OK


def test_the_probe_timeout_rule():
    vw = _wd()
    eff = vw.effective_probe_timeout
    assert eff(2.5) == 2.5
    assert eff(1) == 1
    assert eff(vw.MAX_TIMEOUT_S) == vw.MAX_TIMEOUT_S
    assert eff(10 ** 9) == vw.MAX_TIMEOUT_S
    assert eff(10 ** 400) == vw.MAX_TIMEOUT_S
    for bad in (float("nan"), float("inf"), 0, -1.0, "3", None, True):
        assert eff(bad) == vw.TIMEOUT_S, bad


_BAD_POSITIVE = [float("nan"), float("inf"), -float("inf"), 0, 0.0, -5.0,
                 "15", None, True, False]


@pytest.mark.parametrize("bad", _BAD_POSITIVE)
def test_a_bad_interval_falls_back_to_the_default(bad, caplog):
    vw = _wd()
    caplog.set_level(logging.WARNING, logger="rc.web_dashboard")
    wd = _build(_Rec([]), interval_s=bad)
    assert wd.interval_s == vw.INTERVAL_S
    assert any("interval_s" in r.getMessage() for r in _warnings(caplog))


@pytest.mark.parametrize("bad", _BAD_POSITIVE)
def test_a_bad_timeout_falls_back_to_the_default(bad):
    vw = _wd()
    assert _build(_Rec([]), timeout_s=bad).timeout_s == vw.TIMEOUT_S


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, "90",
                                 None, True])
def test_a_bad_grace_falls_back_to_the_default(bad):
    vw = _wd()
    wd = _build(_Rec([]), grace_s=bad, max_grace_s=bad)
    assert wd.grace_s == vw.GRACE_S
    assert wd.current_grace_s == vw.GRACE_S
    assert wd.max_grace_s == vw.MAX_GRACE_S


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "3", None, True,
                                 2.5])
def test_a_bad_fail_threshold_falls_back_to_the_default(bad):
    vw = _wd()
    assert _build(_Rec([]), fail_threshold=bad).fail_threshold == vw.FAIL_THRESHOLD


def test_valid_values_are_kept():
    vw = _wd()
    wd = _build(_Rec([]), interval_s=5.0, timeout_s=0.5, grace_s=0.0,
                max_grace_s=100.0, fail_threshold=2)
    assert (wd.interval_s, wd.timeout_s, wd.grace_s, wd.max_grace_s,
            wd.fail_threshold) == (5.0, 0.5, 0.0, 100.0, 2)
    # Pre-existing contracts: a threshold below 1 is 1, and the cap is never
    # below the base grace.
    assert _build(_Rec([]), fail_threshold=0).fail_threshold == 1
    wd = _build(_Rec([]), grace_s=60.0, max_grace_s=10.0)
    assert wd.max_grace_s == 60.0
    assert vw.INTERVAL_S == 15.0 and vw.TIMEOUT_S == 3.0


def test_huge_values_are_clamped_so_the_loop_wait_cannot_overflow():
    vw = _wd()
    wd = _build(_Rec([]), interval_s=1e300, timeout_s=1e300,
                grace_s=1e300, max_grace_s=1e300)
    assert wd.interval_s == vw.MAX_INTERVAL_S
    assert wd.timeout_s == vw.MAX_TIMEOUT_S
    assert wd.grace_s == vw.MAX_GRACE_CAP_S
    assert wd.max_grace_s == vw.MAX_GRACE_CAP_S
    # An unclamped 1e300 raised OverflowError out of the loop's stop.wait
    # (measured on Windows) and ended the watchdog thread.
    assert math.isfinite(wd.interval_s)


def test_a_negative_grace_no_longer_disables_the_back_off():
    rec = _Rec([])
    rec.holder = None
    rec.probe = lambda port, timeout_s: "down"
    wd = _build(rec, grace_s=-60.0)
    assert wd.tick() == "spawned"
    assert wd.tick() == "grace"
    assert rec.spawns == 1

"""RM-735: the :8889 self-heal must check LIVENESS, periodically.

Before RM-735 ``dashboard/server.py`` ran a one-shot ``connect_ex`` against
:8889 at dashboard start. A wedged server that still held the port (the
session 106 wedge, twice) was never replaced until RC itself restarted, and a
server that died later was never respawned at all.

``dashboard/_vision_watchdog.py`` probes ``GET /health`` with a short timeout
on every tick:
  - ok   -> reset;
  - down (connection refused: nothing listens) -> spawn now;
  - hung (timeout / reset / non-200) -> count; at ``fail_threshold``
    consecutive hung ticks, capture a stack dump of the holder, taskkill it
    (only when it IS a vision server) and spawn a fresh one;
  - after any spawn, a grace window (doubling while nothing comes back ok)
    stops a slow boot from being reaped by the next spawn.

The end-to-end test stands up a FAKE HOLDER that accepts connections and
never answers, and requires the watchdog to replace it within its window.
"""
from __future__ import annotations

import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent


def _wd():
    from dashboard import _vision_watchdog as vw
    return vw


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class _Recorder:
    """Injectable side effects: every call is recorded, nothing real runs."""

    def __init__(self, states, holder=4242, is_vision=True, kill_ok=True):
        self.states = list(states)
        self.holder = holder
        self.vision = is_vision
        self.kill_ok = kill_ok
        self.kills: list[int] = []
        self.spawns = 0
        self.captures: list[int] = []

    def probe(self, port, timeout_s):
        return self.states.pop(0) if self.states else "ok"

    def find_holder(self, port):
        return self.holder

    def is_vision(self, pid):
        return self.vision

    def kill(self, pid):
        self.kills.append(pid)
        return self.kill_ok

    def spawn(self, app_dir):
        self.spawns += 1
        return 7777

    def capture(self, pid, app_dir):
        self.captures.append(pid)
        return None


def _build(rec, clock=None, **kw):
    vw = _wd()
    params = dict(interval_s=10.0, timeout_s=1.0, fail_threshold=3,
                  grace_s=60.0, max_grace_s=240.0)
    params.update(kw)
    return vw.VisionWatchdog(
        Path("unused-app-dir"), port=1, probe=rec.probe,
        find_holder=rec.find_holder, is_vision=rec.is_vision, kill=rec.kill,
        spawn=rec.spawn, capture=rec.capture, clock=clock or _Clock(), **params)


class TickDecisions(unittest.TestCase):
    def test_ok_does_nothing(self) -> None:
        rec = _Recorder(["ok", "ok"])
        wd = _build(rec)
        self.assertEqual([wd.tick(), wd.tick()], ["ok", "ok"])
        self.assertEqual((rec.spawns, rec.kills), (0, []))

    def test_down_spawns_immediately_without_a_kill(self) -> None:
        rec = _Recorder(["down"], holder=None)
        wd = _build(rec)
        self.assertEqual(wd.tick(), "spawned")
        self.assertEqual((rec.spawns, rec.kills), (1, []))

    def test_refused_while_a_vision_holder_listens_counts_as_hung(self) -> None:
        # Measured live 2026-10-10: a suspended holder's accept backlog fills
        # and Windows then REFUSES new connects - the probe reads "down"
        # while a wedged server still owns the port.
        rec = _Recorder(["down", "down", "down"], holder=4242)
        wd = _build(rec)
        self.assertEqual([wd.tick() for _ in range(3)],
                         ["suspect", "suspect", "replaced"])
        self.assertEqual((rec.captures, rec.kills, rec.spawns), ([4242], [4242], 1))

    def test_hung_holder_is_replaced_at_the_threshold_not_before(self) -> None:
        rec = _Recorder(["hung", "hung", "hung"])
        wd = _build(rec)
        self.assertEqual(wd.tick(), "suspect")
        self.assertEqual(wd.tick(), "suspect")
        self.assertEqual(rec.kills, [])
        self.assertEqual(wd.tick(), "replaced")
        self.assertEqual(rec.captures, [4242])
        self.assertEqual(rec.kills, [4242])
        self.assertEqual(rec.spawns, 1)

    def test_an_ok_between_failures_resets_the_count(self) -> None:
        rec = _Recorder(["hung", "hung", "ok", "hung", "hung"])
        wd = _build(rec)
        results = [wd.tick() for _ in range(5)]
        self.assertNotIn("replaced", results)
        self.assertEqual(rec.kills, [])

    def test_a_foreign_holder_is_never_killed(self) -> None:
        rec = _Recorder(["hung"] * 3, holder=5555, is_vision=False)
        wd = _build(rec)
        results = [wd.tick() for _ in range(3)]
        self.assertEqual(results[-1], "foreign")
        self.assertEqual((rec.kills, rec.spawns), ([], 0))

    def test_holder_gone_by_the_threshold_still_respawns(self) -> None:
        rec = _Recorder(["hung"] * 3, holder=None)
        wd = _build(rec)
        results = [wd.tick() for _ in range(3)]
        self.assertEqual(results[-1], "replaced")
        self.assertEqual((rec.kills, rec.spawns), ([], 1))

    def test_grace_after_spawn_suppresses_a_second_spawn(self) -> None:
        clock = _Clock()
        rec = _Recorder(["down", "down", "down"], holder=None)
        wd = _build(rec, clock=clock)
        self.assertEqual(wd.tick(), "spawned")
        clock.t += 30                       # inside the 60 s grace
        self.assertEqual(wd.tick(), "grace")
        self.assertEqual(rec.spawns, 1)
        clock.t += 31                       # grace over, still down
        self.assertEqual(wd.tick(), "spawned")
        self.assertEqual(rec.spawns, 2)

    def test_grace_doubles_while_nothing_comes_back_and_resets_on_ok(self) -> None:
        clock = _Clock()
        rec = _Recorder(["down", "down", "down", "ok", "down"], holder=None)
        wd = _build(rec, clock=clock)
        wd.tick()                           # spawn, grace 60
        clock.t += 61
        wd.tick()                           # spawn, grace 120
        clock.t += 61
        self.assertEqual(wd.tick(), "grace")
        clock.t += 60
        self.assertEqual(wd.tick(), "ok")   # back: grace resets to base
        self.assertEqual(wd.tick(), "spawned")
        self.assertEqual(wd.grace_until - clock.t, 60.0)

    def test_grace_is_capped(self) -> None:
        clock = _Clock()
        rec = _Recorder(["down"] * 10, holder=None)
        wd = _build(rec, clock=clock)
        for _ in range(6):
            wd.tick()
            clock.t += 1000
        self.assertLessEqual(wd.current_grace_s, 240.0)

    def test_a_failed_kill_is_reported_and_still_respawns(self) -> None:
        rec = _Recorder(["hung"] * 3, kill_ok=False)
        wd = _build(rec)
        with self.assertLogs("rc.web_dashboard", level="WARNING") as logs:
            for _ in range(3):
                wd.tick()
        self.assertEqual(rec.spawns, 1)
        self.assertTrue(any("could not kill" in m for m in logs.output), logs.output)


class ProbeClassification(unittest.TestCase):
    def test_refused_is_down(self) -> None:
        vw = _wd()
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                           # nothing listens on it now
        self.assertEqual(vw.probe_health(port, 5.0), vw.DOWN)

    def test_a_listener_that_never_answers_is_hung(self) -> None:
        vw = _wd()
        holder = _SilentHolder()
        try:
            t0 = time.monotonic()
            self.assertEqual(vw.probe_health(holder.port, 0.5), vw.HUNG)
            self.assertLess(time.monotonic() - t0, 3.0)
        finally:
            holder.close()

    def test_a_200_is_ok_and_a_500_is_hung(self) -> None:
        vw = _wd()
        for code, want in ((200, vw.OK), (500, vw.HUNG)):
            srv = _HealthServer(0, code=code)
            try:
                self.assertEqual(vw.probe_health(srv.port, 2.0), want)
            finally:
                srv.close()


class _SilentHolder:
    """Accepts every connection and never answers: the wedge, from outside."""

    def __init__(self, port: int = 0) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", port))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.held: list[socket.socket] = []
        self._stop = False
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def _accept(self) -> None:
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.held.append(conn)

    def close(self) -> None:
        self._stop = True
        for c in self.held:
            c.close()
        self.sock.close()


class _HealthServer:
    def __init__(self, port: int, code: int = 200) -> None:
        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                body = b'{"alive": true}'
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a: object) -> None:
                pass

        self.srv = HTTPServer(("127.0.0.1", port), H)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()


class FakeHolderIsReplacedEndToEnd(unittest.TestCase):
    """Real probes against a real socket; only kill / spawn are stand-ins."""

    def test_a_holder_that_accepts_but_never_answers_is_replaced(self) -> None:
        vw = _wd()
        holder = _SilentHolder()
        port = holder.port
        state = {"healthy": None, "killed": []}

        def kill(pid):
            state["killed"].append(pid)
            holder.close()                  # the holder dies with the kill
            return True

        def spawn(app_dir):
            state["healthy"] = _HealthServer(port)
            return 8888

        wd = vw.VisionWatchdog(
            Path("unused-app-dir"), port=port, interval_s=0.05, timeout_s=0.3,
            fail_threshold=3, grace_s=5.0,
            find_holder=lambda p: 4242 if p == port else None,
            is_vision=lambda pid: pid == 4242, kill=kill, spawn=spawn,
            capture=lambda pid, app_dir: None)
        stop = threading.Event()
        runner = threading.Thread(target=wd.run, args=(stop,), daemon=True)
        t0 = time.monotonic()
        runner.start()
        try:
            # Window: 3 hung probes x (0.3 s timeout + 0.05 s interval) plus the
            # respawn - well under 5 s; a one-shot check never gets there.
            deadline = t0 + 5.0
            while time.monotonic() < deadline:
                if state["healthy"] and vw.probe_health(port, 0.5) == vw.OK:
                    break
                time.sleep(0.05)
            self.assertEqual(state["killed"], [4242], "the hung holder was not killed")
            self.assertIsNotNone(state["healthy"], "no replacement was spawned")
            self.assertEqual(vw.probe_health(port, 1.0), vw.OK)
            self.assertLess(time.monotonic() - t0, 5.0)
        finally:
            stop.set()
            runner.join(timeout=3)
            holder.close()
            if state["healthy"]:
                state["healthy"].close()


class StartupWiring(unittest.TestCase):
    """dashboard/server.py starts the periodic watchdog; the one-shot is gone."""

    SRC = (REPO / "dashboard" / "server.py").read_text(encoding="utf-8")

    def test_start_dashboard_starts_the_watchdog(self) -> None:
        self.assertIn("start_vision_watchdog(app_dir)", self.SRC)

    def test_the_one_shot_connect_probe_is_gone(self) -> None:
        self.assertNotIn('connect_ex(("127.0.0.1", 8889))', self.SRC)

    def test_start_is_idempotent(self) -> None:
        vw = _wd()
        with mock.patch.object(vw, "_RUNNING", None), \
                mock.patch.object(vw.VisionWatchdog, "run", lambda self, stop: None):
            a = vw.start_vision_watchdog(Path("x"))
            b = vw.start_vision_watchdog(Path("x"))
        self.assertIs(a, b)


class RealSideEffects(unittest.TestCase):
    """The default kill / spawn / capture never open a console window."""

    def test_spawn_is_windowless_and_detached_from_rc_stdio(self) -> None:
        vw = _wd()
        with mock.patch.object(vw.subprocess, "Popen") as popen:
            popen.return_value.pid = 99
            self.assertEqual(vw.spawn_vision(REPO), 99)
        args, kwargs = popen.call_args
        self.assertTrue(str(args[0][1]).endswith("moon_vision_server.py"))
        self.assertEqual(kwargs["creationflags"] & 0x08000000, vw._NO_WINDOW & 0x08000000)
        self.assertEqual(kwargs["stdout"], vw.subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], vw.subprocess.DEVNULL)
        self.assertEqual(kwargs["cwd"], str(REPO))

    def test_kill_uses_taskkill_force_by_pid(self) -> None:
        vw = _wd()
        with mock.patch.object(vw.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertTrue(vw.kill_pid(1234))
        cmd = run.call_args.args[0]
        self.assertEqual(cmd, ["taskkill", "/F", "/PID", "1234"])
        self.assertIn("creationflags", run.call_args.kwargs)

    def test_capture_is_skipped_without_py_spy(self) -> None:
        vw = _wd()
        with mock.patch.object(vw.shutil, "which", return_value=None), \
                mock.patch.object(vw.subprocess, "run") as run:
            self.assertIsNone(vw.capture_stack(1234, REPO))
        run.assert_not_called()

    def test_is_vision_matches_the_spawn_markers(self) -> None:
        vw = _wd()
        proc = mock.Mock()
        for cmdline, want in (
                (["pythonw.exe", "repo/moon_vision_server.py"], True),
                (["python", "-m", "vision_server"], True),
                (["python", "web_dashboard.py"], False)):
            proc.cmdline.return_value = cmdline
            with mock.patch("psutil.Process", return_value=proc):
                self.assertIs(vw.is_vision_pid(1), want, cmdline)


if __name__ == "__main__":
    unittest.main()

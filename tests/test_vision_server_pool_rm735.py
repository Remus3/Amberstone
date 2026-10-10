"""RM-735: the :8889 accept loop must never block starting a thread.

THE WEDGE (session 106, twice in ~2h): ``moon_vision_server.py`` held :8889
LISTEN while every client hung in SYN_SENT. py-spy: MainThread parked in
``serve_forever`` -> ``process_request`` -> ``Thread.start()`` ->
``self._started.wait()`` with an OS thread count of 1.

MECHANISM (CPython 3.12 and 3.14 ``threading.py``): ``Thread.start()`` hands
``_bootstrap`` to a new OS thread and then waits on ``_started`` with NO
timeout. ``_started`` is set inside the NEW thread by ``_bootstrap_inner``,
after ``_set_ident`` / ``_set_native_id`` (and ``_set_os_name`` on 3.14). If
the new thread raises before that line - a MemoryError when commit charge is
exhausted is the measured candidate (both wedges sat in a session with
repeated paging-file exhaustion, RM-737) - it dies, ``_started`` is never
set, and ``ThreadingMixIn.process_request`` parks the accept loop forever.
The listen socket stays bound, the backlog fills, clients hang.

These tests arm exactly that fault (``_set_native_id`` raising MemoryError
for every thread started under the patch) and require the server built by
``vision_server.make_server`` to keep answering. Against the pre-RM-735
``ThreadingHTTPServer`` the first test times out (measured red); the fix is a
pre-started worker pool whose accept path only enqueues.
"""
from __future__ import annotations

import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from unittest import mock

import vision_server

_FAULT = "commit charge exhausted (simulated, RM-735)"


def _get(port: int, path: str = "/health", timeout: float = 3.0) -> int:
    with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}", timeout=timeout) as resp:
        resp.read()
        return resp.status


def _serve(srv) -> threading.Thread:
    t = threading.Thread(target=srv.serve_forever, daemon=True,
                         name="rm735-serve")
    t.start()
    return t


def _close(srv, serve: threading.Thread) -> None:
    # Bounded: a wedged accept loop never acknowledges shutdown(), and a
    # teardown that blocks forever would hang the whole run instead of
    # reporting the red.
    stopper = threading.Thread(target=srv.shutdown, daemon=True)
    stopper.start()
    stopper.join(timeout=2)
    srv.server_close()
    serve.join(timeout=2)


def _handler(gate: threading.Event | None = None, boom: bool = False):
    class H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib name)
            if self.path == "/block" and gate is not None:
                gate.wait(10)
            if self.path == "/boom" and boom:
                raise RuntimeError("handler failure (test)")
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a: object) -> None:
            pass

    return H


class AcceptLoopCannotWedgeInThreadStart(unittest.TestCase):
    # Fault seam: threading.Thread._set_native_id runs before _started.set()
    # on every supported CPython (3.12 CI, 3.14 Legion). No skip on purpose:
    # if the seam ever disappears, patch.object raises and this FAILS, so the
    # guard cannot go quietly vacuous (tests/test_skip_condition_hygiene.py).
    def test_a_thread_dying_in_bootstrap_does_not_park_the_accept_loop(self) -> None:
        srv = vision_server.make_server("127.0.0.1", 0)
        port = srv.server_address[1]
        serve = _serve(srv)
        try:
            self.assertEqual(_get(port), 200, "control request before the fault")
            with mock.patch.object(threading.Thread, "_set_native_id",
                                   side_effect=MemoryError(_FAULT)):
                try:
                    status = _get(port, timeout=3)
                except (TimeoutError, urllib.error.URLError, OSError) as exc:
                    self.fail(
                        "/health hung once a new thread died in bootstrap - the "
                        "accept loop is parked in Thread.start() (RM-735 wedge): "
                        f"{exc!r}")
            self.assertEqual(status, 200)
            # And it keeps serving after the fault clears.
            self.assertEqual(_get(port), 200)
        finally:
            _close(srv, serve)

    def test_the_server_starts_no_thread_per_request(self) -> None:
        srv = vision_server.make_server("127.0.0.1", 0)
        port = srv.server_address[1]
        serve = _serve(srv)
        try:
            _get(port)
            started = []
            real_start = threading.Thread.start

            def spy(self, *a, **kw):
                started.append(self.name)
                return real_start(self, *a, **kw)

            with mock.patch.object(threading.Thread, "start", spy):
                for _ in range(5):
                    self.assertEqual(_get(port), 200)
            self.assertEqual(started, [], "a request started a thread")
        finally:
            _close(srv, serve)


class WorkerPoolBehaviour(unittest.TestCase):
    """The pool must keep the properties the per-request threads gave."""

    def _pool(self, handler, **kw):
        from vision_server._pool import PooledHTTPServer
        srv = PooledHTTPServer(("127.0.0.1", 0), handler, **kw)
        return srv, srv.server_address[1], _serve(srv)

    def test_slow_request_does_not_serialize_a_fast_one(self) -> None:
        # S7 (tests/test_vision_server_threading_s7.py) on the pooled class.
        gate = threading.Event()
        srv, port, serve = self._pool(_handler(gate), workers=4)
        try:
            blocked = threading.Thread(
                target=lambda: _get(port, "/block", timeout=10), daemon=True)
            blocked.start()
            time.sleep(0.1)
            t0 = time.monotonic()
            self.assertEqual(_get(port, "/fast"), 200)
            self.assertLess(time.monotonic() - t0, 1.0)
            gate.set()
            blocked.join(timeout=5)
        finally:
            gate.set()
            _close(srv, serve)

    def test_a_full_queue_drops_the_connection_instead_of_blocking(self) -> None:
        gate = threading.Event()
        srv, port, serve = self._pool(_handler(gate), workers=1, queue_size=1)
        try:
            occupy = threading.Thread(
                target=lambda: _get(port, "/block", timeout=10), daemon=True)
            occupy.start()
            time.sleep(0.2)                      # the one worker is now busy
            queued = socket.create_connection(("127.0.0.1", port), timeout=2)
            time.sleep(0.2)                      # ...and the one queue slot full
            dropped = socket.create_connection(("127.0.0.1", port), timeout=2)
            dropped.settimeout(2)
            try:
                self.assertEqual(dropped.recv(1), b"",
                                 "an over-capacity connection must be closed")
            except ConnectionResetError:
                pass                             # a reset is a drop too
            finally:
                dropped.close()
            deadline = time.monotonic() + 2
            while srv.dropped < 1 and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertEqual(srv.dropped, 1)
            gate.set()
            occupy.join(timeout=5)
            queued.close()
            self.assertEqual(_get(port, "/fast"), 200)
        finally:
            gate.set()
            _close(srv, serve)

    def test_a_handler_exception_does_not_kill_the_worker(self) -> None:
        srv, port, serve = self._pool(_handler(boom=True), workers=1)
        try:
            with self.assertRaises((urllib.error.URLError, OSError,
                                    ConnectionError)):
                _get(port, "/boom")
            self.assertEqual(_get(port, "/fast"), 200)
            self.assertEqual(srv.workers_alive, 1)
        finally:
            _close(srv, serve)

    def test_a_handler_bug_is_logged_with_a_traceback(self) -> None:
        # The stdlib handle_error prints to stderr - None under pythonw - so
        # a failing handler used to vanish without a trace.
        srv, port, serve = self._pool(_handler(boom=True), workers=1)
        try:
            with self.assertLogs("moon_vision", level="WARNING") as logs:
                with self.assertRaises((urllib.error.URLError, OSError,
                                        ConnectionError)):
                    _get(port, "/boom")
                deadline = time.monotonic() + 2
                while not logs.records and time.monotonic() < deadline:
                    time.sleep(0.02)
            self.assertTrue(any(r.exc_info for r in logs.records), logs.output)
        finally:
            _close(srv, serve)

    def test_a_peer_that_hangs_up_is_not_a_warning(self) -> None:
        from vision_server._pool import PooledHTTPServer
        srv = PooledHTTPServer(("127.0.0.1", 0), _handler(), workers=1)
        try:
            with self.assertLogs("moon_vision", level="DEBUG") as logs:
                try:
                    raise ConnectionResetError("peer hung up (test)")
                except ConnectionResetError:
                    srv.handle_error(None, ("127.0.0.1", 1))
            self.assertEqual([r.levelname for r in logs.records], ["DEBUG"])
        finally:
            srv.server_close()

    def test_a_silent_client_cannot_pin_a_worker_forever(self) -> None:
        srv, port, serve = self._pool(_handler(), workers=1,
                                      request_timeout_s=0.3)
        try:
            silent = socket.create_connection(("127.0.0.1", port), timeout=2)
            try:
                time.sleep(0.1)                  # the worker is reading it
                t0 = time.monotonic()
                self.assertEqual(_get(port, "/fast", timeout=3), 200)
                self.assertLess(time.monotonic() - t0, 2.0)
            finally:
                silent.close()
        finally:
            _close(srv, serve)

    def test_workers_start_before_the_port_is_bound(self) -> None:
        from vision_server._pool import PooledHTTPServer
        order = []
        real_bind = PooledHTTPServer.server_bind

        def bind(self):
            order.append(("bind", self.workers_alive))
            return real_bind(self)

        with mock.patch.object(PooledHTTPServer, "server_bind", bind):
            srv = PooledHTTPServer(("127.0.0.1", 0), _handler(), workers=3)
        try:
            self.assertEqual(order, [("bind", 3)])
        finally:
            srv.server_close()

    def test_server_close_stops_the_workers(self) -> None:
        srv, port, serve = self._pool(_handler(), workers=3)
        self.assertEqual(srv.workers_alive, 3)
        _close(srv, serve)
        deadline = time.monotonic() + 3
        while srv.workers_alive and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(srv.workers_alive, 0)

    def test_rejects_an_empty_pool(self) -> None:
        from vision_server._pool import PooledHTTPServer
        with self.assertRaises(ValueError):
            PooledHTTPServer(("127.0.0.1", 0), _handler(), workers=0)


class HealthReportsThePool(unittest.TestCase):
    def test_health_carries_the_live_worker_count(self) -> None:
        import json
        srv = vision_server.make_server("127.0.0.1", 0)
        port = srv.server_address[1]
        serve = _serve(srv)
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=3) as resp:
                body = json.loads(resp.read())
            self.assertEqual(body["workers"], srv.workers_alive)
            self.assertGreater(body["workers"], 0)
            self.assertIs(body["alive"], True)
        finally:
            _close(srv, serve)


if __name__ == "__main__":
    unittest.main()

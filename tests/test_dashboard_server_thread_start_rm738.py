"""RM-738 part 1: the :8888 accept loop must survive a request thread that
dies in bootstrap.

THE WEDGE (RM-735, reproduced on :8889 in session 106 and 108): socketserver
``ThreadingMixIn.process_request`` starts one thread per request FROM the
``serve_forever`` thread, and ``Thread.start()`` then waits on ``_started``
with NO timeout. ``_started`` is set inside the NEW thread, after
``_set_ident`` / ``_set_native_id``. A new thread that raises before that line
(MemoryError under commit-charge exhaustion, RM-737) dies, ``_started`` is
never set, and the accept loop parks forever while the listen socket stays
bound: every later client hangs, and the failed request's socket is never
closed.

Both dashboard server classes (``dashboard/server.py``
``_DualStackHTTPServer`` and ``_DualProtocolHTTPServer``) were plain
``ThreadingHTTPServer`` subclasses, so :8888 carried the same wedge. The
dashboard holds long-lived SSE streams (``/api/state-stream``,
``/api/events``) in their request threads and RM-296e relies on a request
blocking only its own thread, so RM-735's fixed pool does not fit here: the
fix keeps one thread per request and bounds only the start handshake.

The fault seam is the RM-735 one (``tests/test_vision_server_pool_rm735.py``):
``threading.Thread._set_native_id`` raising MemoryError. No skip on purpose:
if the seam disappears, ``patch.object`` raises and this FAILS rather than
going quietly vacuous (``tests/test_skip_condition_hygiene.py``).
"""
from __future__ import annotations

import socket
import sys
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler
from unittest import mock

from dashboard import server

_FAULT = "commit charge exhausted (simulated, RM-738)"
_HOST = "::1"
_CLOSED = (ConnectionResetError, ConnectionAbortedError)


def _handler(gate: threading.Event | None = None):
    class H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib name)
            if self.path == "/block" and gate is not None:
                gate.wait(10)
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a: object) -> None:
            pass

    return H


class _PlainDualProtocol(server._DualProtocolHTTPServer):
    """The TLS class with its accept path reduced to a plain accept. The
    peek / wrap / redirect logic is not under test here; the class's
    process_request (its real MRO) is."""

    def __init__(self, server_address, handler_class) -> None:
        super().__init__(server_address, handler_class, ssl_ctx=None)

    def get_request(self) -> tuple:
        return self.socket.accept()


_CLASSES = (server._DualStackHTTPServer, _PlainDualProtocol)


def _get(port: int, path: str = "/", timeout: float = 3.0) -> int:
    with urllib.request.urlopen(
            f"http://[{_HOST}]:{port}{path}", timeout=timeout) as resp:
        resp.read()
        return resp.status


def _raw_request(port: int, timeout: float, path: str = "/") -> bytes:
    """One request on a raw socket; return every byte received before the
    server closed it. A reset counts as a close. A wedge raises TimeoutError."""
    s = socket.create_connection((_HOST, port), timeout=timeout)
    try:
        s.sendall(f"GET {path} HTTP/1.0\r\n\r\n".encode("ascii"))
        chunks = []
        while True:
            try:
                chunk = s.recv(4096)
            except _CLOSED:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        s.close()


def _serve(srv) -> threading.Thread:
    t = threading.Thread(target=srv.serve_forever, daemon=True,
                         name="rm738-serve")
    t.start()
    return t


def _close(srv, serve: threading.Thread) -> None:
    # Bounded: a wedged accept loop never acknowledges shutdown(), and a
    # teardown that blocks forever would hang the run instead of reporting.
    stopper = threading.Thread(target=srv.shutdown, daemon=True)
    stopper.start()
    stopper.join(timeout=2)
    srv.server_close()
    serve.join(timeout=2)


def _chain(exc: BaseException | None) -> list[type]:
    seen: list[type] = []
    while exc is not None and len(seen) < 10:
        seen.append(type(exc))
        exc = exc.__context__
    return seen


class AcceptLoopSurvivesABootstrapDeath(unittest.TestCase):
    def _check(self, cls) -> None:
        srv = cls((_HOST, 0), _handler())
        port = srv.server_address[1]
        serve = _serve(srv)
        bound = srv.thread_start_timeout_s if hasattr(
            srv, "thread_start_timeout_s") else 2.0
        died: list[BaseException | None] = []
        try:
            self.assertEqual(_get(port), 200, "control request before the fault")
            with mock.patch.object(sys, "unraisablehook",
                                   lambda u: died.append(u.exc_value)), \
                 mock.patch.object(threading.Thread, "_set_native_id",
                                   side_effect=MemoryError(_FAULT)), \
                 self.assertLogs("rc.web_dashboard", level="WARNING") as logs:
                try:
                    got = _raw_request(port, timeout=bound + 3)
                except OSError as exc:
                    self.fail(
                        "the request hung once its thread died in bootstrap - "
                        "the :8888 accept loop is parked in Thread.start() "
                        f"(RM-738 wedge), socket left open: {exc!r}")
                deadline = time.monotonic() + 2
                while not died and time.monotonic() < deadline:
                    time.sleep(0.02)
            self.assertTrue(any(MemoryError in _chain(e) for e in died),
                            f"the armed fault never fired: {died!r}")
            self.assertEqual(got, b"", "the failed request must be closed, "
                                       "not answered")
            self.assertTrue(any("RM-738" in r.getMessage()
                                for r in logs.records), logs.output)
            self.assertEqual(srv.start_failures, 1)
            # The accept loop is still running: the next request is served.
            self.assertEqual(_get(port), 200)
        finally:
            _close(srv, serve)

    def test_dual_stack_fallback_server(self) -> None:
        self._check(server._DualStackHTTPServer)

    def test_dual_protocol_tls_server(self) -> None:
        self._check(_PlainDualProtocol)


class GuardedStartDetails(unittest.TestCase):
    def test_both_dashboard_server_classes_route_through_the_guard(self) -> None:
        for cls in (server._DualStackHTTPServer, server._DualProtocolHTTPServer):
            owner = next(k for k in cls.__mro__ if "process_request" in vars(k))
            self.assertIs(owner, server._GuardedThreadStartMixin, cls.__name__)
            # The guard feeds no server_close() join list; that is only
            # equivalent to the stdlib while request threads are daemons.
            self.assertIs(cls.daemon_threads, True, cls.__name__)

    def test_the_start_bound_is_short_and_finite(self) -> None:
        bound = server._GuardedThreadStartMixin.thread_start_timeout_s
        self.assertGreater(bound, 0)
        self.assertLessEqual(bound, 5.0)

    def test_a_thread_that_starts_after_the_bound_does_not_serve(self) -> None:
        # The accept loop gave up and closed the socket; a late bootstrap must
        # then find the connection already owned and leave it alone, never
        # run the handler on a closed socket.
        srv = server._DualStackHTTPServer((_HOST, 0), _handler())
        srv.thread_start_timeout_s = 0.2
        port = srv.server_address[1]
        served = []
        real_finish = srv.finish_request
        srv.finish_request = lambda r, a: (served.append(a), real_finish(r, a))
        real_native = threading.Thread._set_native_id
        late = threading.Event()

        def slow_native(thread) -> None:
            time.sleep(0.6)
            real_native(thread)
            late.set()

        serve = _serve(srv)
        try:
            with mock.patch.object(threading.Thread, "_set_native_id",
                                   slow_native), \
                 self.assertLogs("rc.web_dashboard", level="WARNING"):
                got = _raw_request(port, timeout=3)
            self.assertEqual(got, b"")
            self.assertTrue(late.wait(3), "the slow thread never started")
            time.sleep(0.2)                       # let it reach its claim
            self.assertEqual(served, [], "a late thread served a dropped request")
            self.assertEqual(srv.start_failures, 1)
            self.assertEqual(_get(port), 200)
            self.assertEqual(len(served), 1)
        finally:
            _close(srv, serve)

    def test_a_start_that_raises_is_dropped_and_logged(self) -> None:
        srv = server._DualStackHTTPServer((_HOST, 0), _handler())
        port = srv.server_address[1]
        serve = _serve(srv)
        try:
            with mock.patch.object(
                    threading.Thread, "start",
                    side_effect=RuntimeError("can't start new thread")), \
                 self.assertLogs("rc.web_dashboard", level="WARNING") as logs:
                t0 = time.monotonic()
                got = _raw_request(port, timeout=3)
                self.assertLess(time.monotonic() - t0, 2.0)
            self.assertEqual(got, b"")
            self.assertTrue(any("RM-738" in r.getMessage()
                                for r in logs.records), logs.output)
            self.assertEqual(srv.start_failures, 1)
            self.assertEqual(_get(port), 200)
        finally:
            _close(srv, serve)


class StillOneThreadPerRequest(unittest.TestCase):
    """RM-296e and the SSE streams need a request to block only its own
    thread. More long-lived requests than any fixed pool would hold (RM-735's
    is 16; the two SSE routes cap at 8 each) must not starve a short one."""

    def test_long_lived_requests_do_not_starve_a_short_one(self) -> None:
        gate = threading.Event()
        srv = server._DualStackHTTPServer((_HOST, 0), _handler(gate))
        port = srv.server_address[1]
        serve = _serve(srv)
        held: list[socket.socket] = []
        started: list[str] = []
        real_start = threading.Thread.start

        def spy(thread, *a, **kw):
            started.append(thread.name)
            return real_start(thread, *a, **kw)

        try:
            with mock.patch.object(threading.Thread, "start", spy):
                for _ in range(24):
                    s = socket.create_connection((_HOST, port), timeout=3)
                    s.sendall(b"GET /block HTTP/1.0\r\n\r\n")
                    held.append(s)
                    time.sleep(0.01)
                deadline = time.monotonic() + 3
                while len(started) < 24 and time.monotonic() < deadline:
                    time.sleep(0.02)
                t0 = time.monotonic()
                self.assertEqual(_get(port, "/fast"), 200)
                self.assertLess(time.monotonic() - t0, 1.0)
            self.assertEqual(len(started), 25, "one thread per request")
        finally:
            gate.set()
            for s in held:
                # Drain each answer before closing, so no handler writes into
                # a reset socket during teardown.
                try:
                    while s.recv(4096):
                        pass
                except OSError:
                    pass
                s.close()
            _close(srv, serve)


if __name__ == "__main__":
    unittest.main()

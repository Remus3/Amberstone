"""RM-738 (DS :8860): one failed per-request thread start must not wedge DS.

THE WEDGE (RM-735, reproduced on :8889 in session 108): socketserver's
``ThreadingMixIn.process_request`` starts one thread per request FROM the
``serve_forever`` thread, and ``Thread.start()`` then waits on ``_started``
with NO timeout. ``_started`` is set inside the NEW thread by
``_bootstrap_inner``, after ``_set_ident`` / ``_set_native_id``. A new thread
that raises before that line (MemoryError under commit-charge exhaustion,
RM-737) dies without setting it, and the accept loop parks forever: the
listen socket stays bound, the dead request's socket is never closed, and
every later client hangs.

DS ``_RcThreadingHTTPServer`` (``agents/daemon_slayer/server.py``) is a
plain ``ThreadingHTTPServer`` subclass, so it carried the same wedge. These
tests arm the RM-735 fault (``tests/test_vision_server_pool_rm735.py``:
``_set_native_id`` raising MemoryError) for exactly one request and require:
the dead request's connection is CLOSED (EOF or reset, never a hang), the
next request is served, and a merely slow bootstrap is not served twice.

DS keeps thread-per-request on purpose (unbounded concurrency for the
12-way load the listen-backlog fix was measured under); the fix bounds the
start instead of replacing it with a pool.
"""
from __future__ import annotations

import socket
import sys
import threading
import time
import unittest
import urllib.request
from unittest import mock

from agents.daemon_slayer import server as ds_server
from agents.daemon_slayer.data_loader import DataSnapshot
from tests._timing_budget import fleet_test_guard

_FAULT = "commit charge exhausted (simulated, RM-738)"
_REQUEST = b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"


def _get(port: int, path: str = "/health", timeout: float = 5.0) -> int:
    with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}", timeout=timeout) as resp:
        resp.read()
        return resp.status


def _raw_request(port: int, timeout: float) -> bytes:
    """Send one request; return what the server sent before closing.

    ``b""`` means the server closed the connection without answering. A
    reset is mapped to ``b""`` too (a close is a close). A hang raises
    ``TimeoutError`` - that is the wedge.
    """
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        sock.sendall(_REQUEST)
        chunks = []
        while True:
            try:
                chunk = sock.recv(65536)
            except (ConnectionResetError, ConnectionAbortedError):
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        sock.close()


def _serve(srv) -> threading.Thread:
    t = threading.Thread(target=srv.serve_forever, daemon=True,
                         name="rm738-ds-serve")
    t.start()
    return t


def _close(srv, serve: threading.Thread) -> None:
    # Bounded: a wedged accept loop never acknowledges shutdown(), and a
    # teardown that blocks forever would hang the run instead of reporting red.
    stopper = threading.Thread(target=srv.shutdown, daemon=True)
    stopper.start()
    stopper.join(timeout=2)
    srv.server_close()
    serve.join(timeout=2)


class _Unraisable:
    """Collects what the dying bootstrap thread reports (sys.unraisablehook).

    Proves the fault really fired in a new thread (the test is not vacuous)
    and keeps the expected death out of the run's warnings.
    """

    def __init__(self) -> None:
        self.seen: list[BaseException] = []

    def __call__(self, unraisable) -> None:
        self.seen.append(unraisable.exc_value)


class DsAcceptLoopSurvivesAFailedThreadStart(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _start(self, timeout_s: float):
        srv = ds_server.start_server(host="127.0.0.1", port=0,
                                     snapshot=self.snap)
        # Read per request (not at bind), so an instance value is honoured.
        srv.thread_start_timeout_s = timeout_s
        return srv, srv.server_address[1], _serve(srv)

    # Fault seam: threading.Thread._set_native_id runs before _started.set()
    # on every supported CPython (3.12 CI, 3.14 Legion). No skip on purpose:
    # if the seam disappears, patch.object raises and this FAILS.
    def test_a_thread_dying_in_bootstrap_closes_its_socket_and_the_next_request_is_served(self) -> None:
        srv, port, serve = self._start(timeout_s=0.5)
        try:
            self.assertEqual(_get(port), 200, "control request before the fault")
            hook = _Unraisable()
            with mock.patch.object(sys, "unraisablehook", hook), \
                    mock.patch.object(threading.Thread, "_set_native_id",
                                      side_effect=MemoryError(_FAULT)):
                t0 = time.monotonic()
                try:
                    got = _raw_request(port, timeout=4.0)
                except TimeoutError as exc:
                    self.fail(
                        "the request whose thread died in bootstrap hung - the "
                        "DS accept loop is parked in Thread.start() and its "
                        f"socket is never closed (RM-738 wedge): {exc!r}")
                elapsed = time.monotonic() - t0
            self.assertEqual(got, b"",
                             "the dead request must be closed, not answered")
            self.assertLess(elapsed, fleet_test_guard.budget(3.0))
            self.assertTrue(hook.seen, "the armed fault never fired - vacuous")
            self.assertEqual(srv.thread_start_failures, 1)
            # The accept loop is free: the next request is served normally.
            self.assertEqual(_get(port), 200)
            self.assertEqual(_get(port), 200)
        finally:
            _close(srv, serve)

    def test_repeated_bootstrap_deaths_do_not_wedge_either(self) -> None:
        srv, port, serve = self._start(timeout_s=0.3)
        try:
            hook = _Unraisable()
            with mock.patch.object(sys, "unraisablehook", hook), \
                    mock.patch.object(threading.Thread, "_set_native_id",
                                      side_effect=MemoryError(_FAULT)):
                for _ in range(3):
                    self.assertEqual(_raw_request(port, timeout=4.0), b"")
            self.assertEqual(srv.thread_start_failures, 3)
            self.assertEqual(_get(port), 200)
        finally:
            _close(srv, serve)

    def test_a_synchronous_start_failure_closes_the_socket_and_keeps_serving(self) -> None:
        # Regression pin (green before the fix too: socketserver closes a
        # request whose process_request raises). The override must keep it.
        srv, port, serve = self._start(timeout_s=0.5)
        try:
            with mock.patch.object(threading.Thread, "start",
                                   side_effect=RuntimeError("can't start new thread")):
                self.assertEqual(_raw_request(port, timeout=4.0), b"")
            self.assertEqual(_get(port), 200)
        finally:
            _close(srv, serve)

    def test_a_slow_bootstrap_is_abandoned_once_and_never_served_twice(self) -> None:
        # A thread that boots AFTER the bound must not then run a request
        # whose socket the accept loop already closed.
        srv, port, serve = self._start(timeout_s=0.3)
        real = threading.Thread._set_native_id

        def slow(thread_self) -> None:
            time.sleep(1.0)
            real(thread_self)

        handled: list[object] = []
        try:
            with mock.patch.object(srv, "finish_request",
                                   side_effect=lambda *a: handled.append(a)), \
                    mock.patch.object(srv, "handle_error") as handle_error:
                with mock.patch.object(threading.Thread, "_set_native_id", slow):
                    t0 = time.monotonic()
                    got = _raw_request(port, timeout=4.0)
                    elapsed = time.monotonic() - t0
                    time.sleep(1.4)              # the slow thread now runs
            self.assertEqual(got, b"")
            # Capped under the 1.0 s slow bootstrap, so an unbounded start
            # still fails on a loaded box.
            self.assertLess(elapsed, min(fleet_test_guard.budget(0.9), 0.95),
                            "the start was not bounded")
            self.assertEqual(handled, [], "an abandoned request was served")
            handle_error.assert_not_called()
            self.assertEqual(srv.thread_start_failures, 1)
            self.assertEqual(_get(port), 200)
        finally:
            _close(srv, serve)

    def test_the_default_bound_is_generous(self) -> None:
        # A false abandonment drops a live request (the client reads None as
        # an engine verdict - see _RcThreadingHTTPServer's backlog note), so
        # the default must sit far above any real bootstrap time.
        self.assertGreaterEqual(
            ds_server._RcThreadingHTTPServer.thread_start_timeout_s, 2.0)
        self.assertTrue(ds_server._RcThreadingHTTPServer.daemon_threads)


if __name__ == "__main__":
    unittest.main()

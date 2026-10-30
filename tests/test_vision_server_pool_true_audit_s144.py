"""True-audit (s144 lane 8 cycle 63) of ``vision_server/_pool.py``.

``PooledHTTPServer`` is the :8889 vision server's accept loop and worker
pool (RM-735). ``tests/test_vision_server_pool_rm735.py`` pins the wedge it
exists to prevent; this file pins what the audit found on top of that:

F1  ``server_close`` with every worker busy and a queue smaller than the
    pool put one stop sentinel, waited 1 s for a second slot, gave up, and
    left the other busy workers parked in ``queue.get()`` forever once
    their requests finished - the pool comment's "a queue smaller than the
    pool still drains" held only for IDLE workers.
F2  ``request_timeout_s`` was taken unchecked. 0 makes every connection
    non-blocking (each read raises BlockingIOError), -1 / NaN raise
    ValueError and inf / 1e300 OverflowError at ``settimeout`` - on EVERY
    request, so one bad value is a total :8889 outage that only shows up as
    a warning per request. True was read as a 1 s deadline.
F3  A handler raising a BaseException that is not an Exception (SystemExit
    from a ``sys.exit()`` in handler code) escaped ``except Exception`` and
    ended the worker thread. ``threading.excepthook`` ignores SystemExit, so
    nothing was logged and the pool shrank by one for good.
F4  ``process_request`` after ``server_close`` still enqueued the
    connection. No worker was left to take it, so the socket stayed open
    and the client hung until its own timeout.
F5  ``workers`` / ``queue_size`` were coerced, not validated: ``workers=0``
    raised but ``queue_size=0`` (or negative) was silently clamped to 1,
    ``workers=True`` meant one worker and ``workers=2.5`` meant two.
"""
from __future__ import annotations

import math
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from unittest import mock

from tests._timing_budget import fleet_test_guard
from vision_server._pool import PooledHTTPServer

# The unfixed close blocks a full second on the second sentinel put
# (``put(None, timeout=1.0)``); cap below that so a widened budget still
# tells fixed from broken.
_CLOSE_CAP_S = 0.9


def _get(port: int, path: str = "/fast", timeout: float = 3.0) -> int:
    with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}", timeout=timeout) as resp:
        resp.read()
        return resp.status


def _handler(gate: threading.Event | None = None,
             entered: threading.Semaphore | None = None):
    class H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib name)
            if self.path == "/block":
                if entered is not None:
                    entered.release()
                if gate is not None:
                    gate.wait(10)
            if self.path == "/exit":
                raise SystemExit(3)
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a: object) -> None:
            pass

    return H


def _serve(srv) -> threading.Thread:
    t = threading.Thread(target=srv.serve_forever, daemon=True,
                         name="s144-pool-serve")
    t.start()
    return t


def _stop_serving(srv, serve: threading.Thread) -> None:
    stopper = threading.Thread(target=srv.shutdown, daemon=True)
    stopper.start()
    stopper.join(timeout=2)
    serve.join(timeout=2)


def _wait_for(pred, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _refused_before_anything_started(case: unittest.TestCase, **kw) -> None:
    """Construction with ``kw`` raises ValueError having started no worker
    and bound no port - nothing half-built is left behind."""
    started: list[str] = []
    real_start = threading.Thread.start

    def spy(self, *a, **k):
        started.append(self.name)
        return real_start(self, *a, **k)

    with mock.patch.object(threading.Thread, "start", spy), \
            mock.patch.object(PooledHTTPServer, "server_bind",
                              side_effect=AssertionError("bound")):
        with case.assertRaises(ValueError):
            PooledHTTPServer(("127.0.0.1", 0), _handler(), **kw)
    case.assertEqual(started, [], "a refused construction started workers")


class F1CloseStopsBusyWorkers(unittest.TestCase):
    def test_close_with_every_worker_busy_stops_them_all(self) -> None:
        gate = threading.Event()
        entered = threading.Semaphore(0)
        srv = PooledHTTPServer(("127.0.0.1", 0), _handler(gate, entered),
                               workers=2, queue_size=1)
        port = srv.server_address[1]
        serve = _serve(srv)
        clients = []
        try:
            for _ in range(2):
                c = threading.Thread(
                    target=lambda: _get(port, "/block", timeout=10),
                    daemon=True)
                c.start()
                clients.append(c)
            for _ in range(2):
                self.assertTrue(entered.acquire(timeout=3),
                                "both workers must be inside a request")
            _stop_serving(srv, serve)
            t0 = time.monotonic()
            srv.server_close()
            elapsed = time.monotonic() - t0
            self.assertLess(
                elapsed, min(fleet_test_guard.budget(0.5), _CLOSE_CAP_S),
                "server_close blocked waiting for a queue slot a busy "
                "worker will not free")
            gate.set()
            self.assertTrue(
                _wait_for(lambda: srv.workers_alive == 0),
                f"{srv.workers_alive} worker(s) still parked in queue.get() "
                "after their requests finished")
        finally:
            gate.set()
            for c in clients:
                c.join(timeout=5)
            srv.server_close()

    def test_close_twice_is_harmless(self) -> None:
        srv = PooledHTTPServer(("127.0.0.1", 0), _handler(), workers=3)
        srv.server_close()
        t0 = time.monotonic()
        srv.server_close()
        self.assertLess(time.monotonic() - t0,
                        min(fleet_test_guard.budget(0.5), _CLOSE_CAP_S))
        self.assertTrue(_wait_for(lambda: srv.workers_alive == 0))


class F2RequestTimeoutIsValidated(unittest.TestCase):
    BAD = (0, 0.0, -1, -0.5, math.nan, math.inf, 1e300, True, "60")

    def test_bad_timeouts_are_refused_at_construction(self) -> None:
        for bad in self.BAD:
            with self.subTest(request_timeout_s=bad):
                _refused_before_anything_started(self, workers=2,
                                                 request_timeout_s=bad)

    def test_none_and_positive_timeouts_are_accepted(self) -> None:
        for ok in (None, 0.25, 60, 60.0):
            with self.subTest(request_timeout_s=ok):
                srv = PooledHTTPServer(("127.0.0.1", 0), _handler(),
                                       workers=1, request_timeout_s=ok)
                try:
                    self.assertEqual(srv.request_timeout_s,
                                     None if ok is None else float(ok))
                finally:
                    srv.server_close()

    def test_a_valid_timeout_still_serves(self) -> None:
        srv = PooledHTTPServer(("127.0.0.1", 0), _handler(), workers=1,
                               request_timeout_s=5)
        port = srv.server_address[1]
        serve = _serve(srv)
        try:
            self.assertEqual(_get(port), 200)
        finally:
            _stop_serving(srv, serve)
            srv.server_close()


class F3BaseExceptionDoesNotKillAWorker(unittest.TestCase):
    def test_a_handler_systemexit_is_logged_and_the_worker_survives(self) -> None:
        srv = PooledHTTPServer(("127.0.0.1", 0), _handler(), workers=1)
        port = srv.server_address[1]
        serve = _serve(srv)
        try:
            with self.assertLogs("moon_vision", level="WARNING") as logs:
                with self.assertRaises((urllib.error.URLError, OSError,
                                        ConnectionError)):
                    _get(port, "/exit")
                _wait_for(lambda: bool(logs.records), 2.0)
            self.assertTrue(any(r.exc_info for r in logs.records), logs.output)
            try:
                self.assertEqual(_get(port, "/fast", timeout=3), 200)
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                self.fail(f"the only worker died on SystemExit: {exc!r}")
            self.assertEqual(srv.workers_alive, 1)
        finally:
            _stop_serving(srv, serve)
            srv.server_close()


class F4NoConnectionIsQueuedAfterClose(unittest.TestCase):
    def test_process_request_after_close_closes_the_connection(self) -> None:
        srv = PooledHTTPServer(("127.0.0.1", 0), _handler(), workers=1)
        srv.server_close()
        self.assertTrue(_wait_for(lambda: srv.workers_alive == 0))
        a, b = socket.socketpair()
        try:
            srv.process_request(a, ("127.0.0.1", 1))
            b.settimeout(2)
            try:
                self.assertEqual(b.recv(1), b"")
            except ConnectionResetError:
                pass                             # a reset is a close too
            except TimeoutError:
                self.fail("a connection handed over after server_close was "
                          "queued for a worker that no longer exists")
        finally:
            a.close()
            b.close()

    def test_a_worker_shuts_a_connection_it_dequeues_while_closing(self) -> None:
        # The race behind the accept-path check: a connection enqueued just
        # before closing began is shut by the worker, never served. Driven
        # through the internals because the race window itself is a few
        # bytecodes wide.
        gate = threading.Event()
        entered = threading.Semaphore(0)
        srv = PooledHTTPServer(("127.0.0.1", 0), _handler(gate, entered),
                               workers=1, queue_size=4)
        port = srv.server_address[1]
        serve = _serve(srv)
        a, b = socket.socketpair()
        client = threading.Thread(
            target=lambda: _get(port, "/block", timeout=10), daemon=True)
        try:
            client.start()
            self.assertTrue(entered.acquire(timeout=3))
            srv._queue.put_nowait((a, ("127.0.0.1", 1)))
            srv._closing = True              # closing began after the enqueue
            gate.set()
            b.settimeout(3)
            try:
                self.assertEqual(b.recv(1), b"")
            except ConnectionResetError:
                pass
            except TimeoutError:
                self.fail("a worker left a connection open that it took "
                          "from the queue after closing began")
        finally:
            gate.set()
            client.join(timeout=5)
            _stop_serving(srv, serve)
            srv.server_close()
            a.close()
            b.close()


class F1StopPillSurvivesAFullQueue(unittest.TestCase):
    def test_a_connection_in_the_last_slot_is_shut_to_make_room(self) -> None:
        srv = PooledHTTPServer(("127.0.0.1", 0), _handler(), workers=1,
                               queue_size=1)
        srv.server_close()
        self.assertTrue(_wait_for(lambda: srv.workers_alive == 0))
        self.assertIsNone(srv._queue.get_nowait(), "the pill outlives the pool")
        a, b = socket.socketpair()
        try:
            srv._queue.put_nowait((a, ("127.0.0.1", 1)))   # raced into the slot
            srv._pass_on_stop()
            self.assertIsNone(srv._queue.get_nowait())
            b.settimeout(2)
            try:
                self.assertEqual(b.recv(1), b"")
            except ConnectionResetError:
                pass
            except TimeoutError:
                self.fail("the connection evicted to make room for the pill "
                          "was left open")
        finally:
            a.close()
            b.close()


class F5PoolSizesAreValidated(unittest.TestCase):
    def test_bad_sizes_are_refused(self) -> None:
        cases = (
            {"workers": True}, {"workers": 2.5}, {"workers": "4"},
            {"workers": -1}, {"queue_size": 0}, {"queue_size": -3},
            {"queue_size": True}, {"queue_size": 1.5},
        )
        for kw in cases:
            with self.subTest(**kw):
                _refused_before_anything_started(self, **kw)

    def test_good_sizes_build_the_pool_they_name(self) -> None:
        srv = PooledHTTPServer(("127.0.0.1", 0), _handler(), workers=3,
                               queue_size=1)
        try:
            self.assertEqual(srv.workers_alive, 3)
            self.assertEqual(srv._queue.maxsize, 1)
        finally:
            srv.server_close()


if __name__ == "__main__":
    unittest.main()

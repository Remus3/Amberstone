"""RM-1150: the :8889 worker pool caps the WALL-CLOCK time a connection may
spend sending its request, not just each socket operation.

``request_timeout_s`` is a per socket OPERATION deadline: every ``recv``
gets a fresh window. A peer that trickles one header byte inside every
window is never silent, so it held a worker for as long as it kept
trickling; 16 such connections stalled :8889 until the watchdog replaced
the process. ``request_read_cap_s`` is one budget shared by every read of a
connection. Reads only: a handler's own compute and its response writes are
not under it, so a slow inference call is never cut off.
"""
from __future__ import annotations

import math
import socket
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler
from unittest import mock

from tests._timing_budget import fleet_test_guard
from vision_server import _pool
from vision_server._pool import PooledHTTPServer

_TRICKLE_EVERY_S = 0.2
_OP_TIMEOUT_S = 0.5
_READ_CAP_S = 2.0
# Without the cap the trickler holds the only worker for as long as it
# trickles; it gives up after this, well past every bound asserted below.
_TRICKLE_FOR_S = 12.0
# A /fast request queued behind the trickler: the cap plus slack. The
# client timeout sits below _TRICKLE_FOR_S so the unfixed pool fails it.
_SERVED_WITHIN_S = 4.5
_CLIENT_TIMEOUT_S = 6.0


def _handler():
    class H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib name)
            if self.path == "/slow":
                # Compute past the read cap, after the request is read.
                time.sleep(_READ_CAP_S + 0.6)
            self._reply(b'{"ok": true}')

        def do_POST(self) -> None:  # noqa: N802 (stdlib name)
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            self._reply(b'{"len": %d}' % len(body))

        def _reply(self, body: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a: object) -> None:
            pass

    return H


def _get(port: int, path: str, timeout: float) -> int:
    with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}", timeout=timeout) as resp:
        resp.read()
        return resp.status


class _Trickler(threading.Thread):
    """Sends ``head`` at once, then one byte every _TRICKLE_EVERY_S until
    the server drops the connection or _TRICKLE_FOR_S passes."""

    def __init__(self, port: int, head: bytes) -> None:
        super().__init__(daemon=True, name="rm1150-trickler")
        self.port = port
        self.head = head
        self.dropped_after: float | None = None
        self.stop = threading.Event()

    def run(self) -> None:
        start = time.monotonic()
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as s:
            s.settimeout(_TRICKLE_EVERY_S)
            try:
                s.sendall(self.head)
                while time.monotonic() - start < _TRICKLE_FOR_S \
                        and not self.stop.is_set():
                    try:
                        if s.recv(1024) == b"":
                            break  # the server closed it
                    except TimeoutError:
                        pass
                    s.sendall(b"a")
            except OSError:
                pass  # reset or aborted by the server: dropped
            else:
                if time.monotonic() - start >= _TRICKLE_FOR_S \
                        or self.stop.is_set():
                    return  # never dropped
            self.dropped_after = time.monotonic() - start


def _serve(srv) -> threading.Thread:
    t = threading.Thread(target=srv.serve_forever, daemon=True,
                         name="rm1150-serve")
    t.start()
    return t


class ATricklingPeerIsCapped(unittest.TestCase):
    def _pool(self) -> PooledHTTPServer:
        srv = PooledHTTPServer(("127.0.0.1", 0), _handler(), workers=1,
                               request_timeout_s=_OP_TIMEOUT_S,
                               request_read_cap_s=_READ_CAP_S)
        serve = _serve(srv)

        def stop() -> None:
            stopper = threading.Thread(target=srv.shutdown, daemon=True)
            stopper.start()
            stopper.join(timeout=3)
            serve.join(timeout=3)
            srv.server_close()

        self.addCleanup(stop)
        return srv

    def _assert_capped(self, head: bytes) -> None:
        srv = self._pool()
        port = srv.server_address[1]
        trickler = _Trickler(port, head)
        self.addCleanup(trickler.join, 3)
        self.addCleanup(trickler.stop.set)
        trickler.start()
        time.sleep(3 * _TRICKLE_EVERY_S)  # the trickler holds the worker
        start = time.monotonic()
        status = _get(port, "/fast", _CLIENT_TIMEOUT_S)
        elapsed = time.monotonic() - start
        self.assertEqual(status, 200)
        self.assertLess(elapsed, min(fleet_test_guard.budget(_SERVED_WITHIN_S),
                                     _CLIENT_TIMEOUT_S - 0.5))
        trickler.join(timeout=3)
        self.assertIsNotNone(trickler.dropped_after,
                             "the server never dropped the trickling peer")
        self.assertGreaterEqual(trickler.dropped_after, _READ_CAP_S - 0.3)

    def test_a_trickled_header_is_dropped_and_the_pool_serves_again(self) -> None:
        self._assert_capped(b"GET /fast HTTP/1.0\r\nX-Trickle: ")

    def test_a_trickled_body_is_dropped_and_the_pool_serves_again(self) -> None:
        # The handler's own body read shares the same budget.
        self._assert_capped(b"POST /up HTTP/1.0\r\nContent-Length: 100000\r\n\r\n")

    def test_a_handler_computing_past_the_cap_still_answers(self) -> None:
        srv = self._pool()
        self.assertEqual(_get(srv.server_address[1], "/slow", 8.0), 200)

    def test_a_prompt_post_is_read_whole(self) -> None:
        srv = self._pool()
        body = b"x" * 200_000
        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.server_address[1]}/up", data=body,
            method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.read(), b'{"len": 200000}')


class TheCapIsReadOnly(unittest.TestCase):
    def test_reads_share_one_budget_and_writes_keep_the_operation_deadline(self) -> None:
        a, b = socket.socketpair()
        self.addCleanup(b.close)
        a.settimeout(_OP_TIMEOUT_S)
        capped = _pool._read_capped(a, 0.4)
        self.addCleanup(capped.close)
        b.sendall(b"hi")
        self.assertEqual(capped.recv(16), b"hi")
        # The read shrank the socket deadline to what is left of the cap ...
        self.assertLessEqual(socket.socket.gettimeout(capped), 0.4)
        # ... a write runs under the per-operation deadline again ...
        capped.sendall(b"ok")
        self.assertEqual(socket.socket.gettimeout(capped), _OP_TIMEOUT_S)
        self.assertEqual(b.recv(16), b"ok")
        # ... gettimeout() reports the per-operation deadline even right
        # after a read, so a save / restore round trip (the host gate's
        # body drain) cannot shrink it for good ...
        b.sendall(b"again")
        self.assertEqual(capped.recv(16), b"again")
        self.assertEqual(capped.gettimeout(), _OP_TIMEOUT_S)
        capped.settimeout(capped.gettimeout())
        capped.sendall(b"ok")
        self.assertEqual(socket.socket.gettimeout(capped), _OP_TIMEOUT_S)
        self.assertEqual(b.recv(16), b"ok")
        # ... and once the cap is spent every read fails at once, even a
        # buffered one, instead of waiting another window.
        time.sleep(0.5)
        b.sendall(b"late")
        t0 = time.monotonic()
        with self.assertRaises(TimeoutError):
            capped.recv(16)
        with self.assertRaises(TimeoutError):
            capped.recv_into(bytearray(16))
        self.assertLess(time.monotonic() - t0, fleet_test_guard.budget(0.2))

    def test_no_cap_leaves_the_connection_as_it_is(self) -> None:
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        self.assertIs(_pool._read_capped(a, None), a)

    def test_a_non_socket_request_is_left_as_it_is(self) -> None:
        fake = mock.Mock(spec=["settimeout", "shutdown", "close"])
        self.assertIs(_pool._read_capped(fake, 1.0), fake)


class TheCapIsValidated(unittest.TestCase):
    def test_default_is_the_module_constant(self) -> None:
        srv = PooledHTTPServer(("127.0.0.1", 0), _handler(), workers=1)
        self.addCleanup(srv.server_close)
        self.assertEqual(srv.request_read_cap_s, _pool.DEFAULT_REQUEST_READ_CAP_S)
        self.assertIsNotNone(srv.request_read_cap_s)

    def test_bad_caps_are_refused_before_anything_starts(self) -> None:
        real_start = threading.Thread.start
        for bad in (0, -1, math.nan, math.inf, 1e300, True, "5"):
            with self.subTest(request_read_cap_s=bad):
                started: list[str] = []

                def spy(self, *a, _started=started, **k):
                    _started.append(self.name)
                    return real_start(self, *a, **k)

                with mock.patch.object(threading.Thread, "start", spy), \
                        mock.patch.object(PooledHTTPServer, "server_bind",
                                          side_effect=AssertionError("bound")):
                    with self.assertRaises(ValueError) as ctx:
                        PooledHTTPServer(("127.0.0.1", 0), _handler(),
                                         request_read_cap_s=bad)
                self.assertIn("request_read_cap_s", str(ctx.exception))
                self.assertEqual(started, [])

    def test_none_and_positive_caps_are_kept(self) -> None:
        for ok in (None, 0.25, 7, 3600):
            with self.subTest(request_read_cap_s=ok):
                srv = PooledHTTPServer(("127.0.0.1", 0), _handler(),
                                       workers=1, request_read_cap_s=ok)
                try:
                    self.assertEqual(srv.request_read_cap_s,
                                     None if ok is None else float(ok))
                finally:
                    srv.server_close()


if __name__ == "__main__":
    unittest.main()

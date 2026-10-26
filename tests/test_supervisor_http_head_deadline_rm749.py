"""RM-749: a :8890 supervisor web client that connects and then sends nothing
held its request thread and socket with no time limit.

THE DEFECT (the RM-744 shape, measured on :8888): ``agents/_supervisor_http.py``
``_QuietHandler`` set no deadline and ``_WebServer`` hands it a socket with no
timeout, so ``handle_one_request``'s ``rfile.readline`` blocked for as long
as the client stayed connected. Measured before the fix (in-process,
production ``_WebServer`` + ``_QuietHandler``): an idle client was still open
at 65 s, its request thread alive.

THE FIX: the shared RM-744 ``core.http_head_deadline.HeadDeadlineMixin`` on
``_QuietHandler`` - one TOTAL deadline for the request line plus headers,
removed once the head is parsed, never a class-level ``timeout`` (RM-152).
"""
from __future__ import annotations

import contextlib
import json
import socket
import threading
import time
from pathlib import Path

import pytest

from agents._supervisor_http import _QuietHandler, _WebServer
from tests._timing_budget import fleet_test_guard

_HOST = "127.0.0.1"
_CLOSED = (ConnectionResetError, ConnectionAbortedError)
_TEST_DEADLINE_S = 0.75


@pytest.fixture
def webroot(tmp_path: Path) -> Path:
    root = tmp_path / "webroot"
    root.mkdir()
    (root / "ok.txt").write_bytes(b"public\n")      # bytes: no CRLF on Windows
    return root


@pytest.fixture
def short_head_deadline(monkeypatch: pytest.MonkeyPatch) -> float:
    # raising=False: before the fix the attribute does not exist, and the
    # test must then fail on BEHAVIOUR (the client is never closed).
    monkeypatch.setattr(_QuietHandler, "head_read_timeout_s", _TEST_DEADLINE_S,
                        raising=False)
    return _TEST_DEADLINE_S


def _close(srv, serve: threading.Thread) -> None:
    stopper = threading.Thread(target=srv.shutdown, daemon=True)
    stopper.start()
    stopper.join(timeout=2)
    srv.server_close()
    serve.join(timeout=2)


@contextlib.contextmanager
def _served(webroot: Path, handler=_QuietHandler):
    """The production server class and handler, as start_web_server builds
    them (no supervisor: the routes used here never reach it)."""
    srv = _WebServer((_HOST, 0),
                     lambda *a, **kw: handler(*a, directory=str(webroot), **kw))
    serve = threading.Thread(target=srv.serve_forever, daemon=True,
                             name="rm749-serve")
    serve.start()
    parked: list[socket.socket] = []
    try:
        yield srv.server_address[1], parked
    finally:
        for s in parked:
            with contextlib.suppress(OSError):
                s.close()
        _close(srv, serve)


def _connect(port: int, parked: list) -> socket.socket:
    s = socket.create_connection((_HOST, port), timeout=5)
    parked.append(s)
    return s


def _time_to_close(sock, wait_s: float) -> float:
    sock.settimeout(wait_s)
    t0 = time.monotonic()
    try:
        data = sock.recv(1)
    except _CLOSED:
        data = b""
    except TimeoutError:
        pytest.fail(f"the server still held the connection after "
                    f"{wait_s:.1f}s of client silence: no deadline on the "
                    f"request head (RM-749)")
    assert data == b"", f"an idle client must be closed, not answered: {data!r}"
    return time.monotonic() - t0


def _read_all(sock: socket.socket, wait_s: float = 10.0) -> bytes:
    sock.settimeout(wait_s)
    buf = b""
    while True:
        try:
            chunk = sock.recv(65536)
        except _CLOSED:
            break
        if not chunk:
            break
        buf += chunk
    return buf


def _status(reply: bytes) -> bytes:
    return reply.split(b"\r\n", 1)[0].split(b" ")[1]


# -- the defect ---------------------------------------------------------------

def test_an_idle_client_is_closed_at_the_head_deadline(webroot, short_head_deadline):
    with _served(webroot) as (port, parked):
        s = _connect(port, parked)
        elapsed = _time_to_close(s, wait_s=6.0)
    assert elapsed < fleet_test_guard.budget(short_head_deadline + 3.0), elapsed


def test_a_request_line_with_no_headers_is_closed_at_the_head_deadline(
        webroot, short_head_deadline):
    with _served(webroot) as (port, parked):
        s = _connect(port, parked)
        s.sendall(b"GET /ok.txt HTTP/1.1\r\nHost: 127.0.0.1\r\n")
        elapsed = _time_to_close(s, wait_s=6.0)
    assert elapsed < fleet_test_guard.budget(short_head_deadline + 3.0), elapsed


def test_a_trickling_head_is_cut_at_the_total_deadline(webroot, monkeypatch):
    monkeypatch.setattr(_QuietHandler, "head_read_timeout_s", 1.0, raising=False)
    stop = threading.Event()
    with _served(webroot) as (port, parked):
        s = _connect(port, parked)
        s.sendall(b"GET /ok.txt HTTP/1.1\r\nX-Slow: ")

        def trickle() -> None:
            while not stop.wait(0.2):
                try:
                    s.sendall(b"a")
                except OSError:
                    return

        t = threading.Thread(target=trickle, daemon=True, name="rm749-trickle")
        t.start()
        try:
            elapsed = _time_to_close(s, wait_s=6.0)
        finally:
            stop.set()
            t.join(timeout=2)
    assert 0.5 <= elapsed < fleet_test_guard.budget(3.5), elapsed


# -- legitimate clients the deadline must not touch ---------------------------

def test_a_slow_speaker_inside_the_deadline_is_served(webroot, monkeypatch):
    monkeypatch.setattr(_QuietHandler, "head_read_timeout_s", 3.0, raising=False)
    with _served(webroot) as (port, parked):
        s = _connect(port, parked)
        time.sleep(0.6)
        s.sendall(b"GET /ok.txt HTTP/1.1\r\n")
        time.sleep(0.6)
        s.sendall(b"Host: 127.0.0.1\r\nConnection: close\r\n\r\n")
        reply = _read_all(s)
    assert _status(reply) == b"200", reply[:160]
    assert reply.endswith(b"public\n"), reply[-40:]


def test_a_post_body_slower_than_the_head_deadline_is_still_read(
        webroot, short_head_deadline):
    """The head deadline ends with the head. A body that lands after it is
    still read: "malformed JSON body" needs the bytes (an empty body is the
    "missing 'text'" 400), and a read cut by a leaked deadline ends with no
    reply at all (the stdlib's TimeoutError path)."""
    body = b"{bad"
    with _served(webroot) as (port, parked):
        s = _connect(port, parked)
        s.sendall(b"POST /api/input HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                  b"Content-Type: application/json\r\nConnection: close\r\n"
                  b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n")
        time.sleep(short_head_deadline * 2)
        s.sendall(body)
        reply = _read_all(s)
    head, _, payload = reply.partition(b"\r\n\r\n")
    assert reply, "the body read was cut: no reply (RM-749 deadline leaked)"
    assert _status(reply) == b"400", head
    assert json.loads(payload) == {"error": "malformed JSON body"}


class _Probe(_QuietHandler):
    """Records the socket timeout the route sees, after a pause longer than
    the head deadline."""

    seen: list = []

    def do_GET(self) -> None:  # noqa: N802 (stdlib name)
        time.sleep(_TEST_DEADLINE_S * 2)
        type(self).seen.append(self.connection.gettimeout())
        self._send_json(200, {"ok": True})


def test_the_route_sees_the_socket_timeout_restored(webroot, short_head_deadline):
    _Probe.seen = []
    with _served(webroot, _Probe) as (port, parked):
        s = _connect(port, parked)
        s.sendall(b"GET /rm749 HTTP/1.0\r\n\r\n")
        reply = _read_all(s)
    assert reply.endswith(b'{"ok": true}'), reply[:160]
    assert _Probe.seen == [None], (
        f"the head deadline leaked into the route: socket timeout "
        f"{_Probe.seen!r}, expected [None]")


def test_the_shipped_head_deadline_is_generous_and_finite():
    cap = getattr(_QuietHandler, "head_read_timeout_s", None)
    assert cap is not None, "_QuietHandler has no request-head deadline (RM-749)"
    assert 10.0 <= cap <= 120.0, cap
    # RM-152: never the per-receive, connection-lifetime class-level timeout.
    assert _QuietHandler.timeout is None, _QuietHandler.timeout

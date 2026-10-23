"""RM-748: a :8860 Daemon Slayer client that connects and then sends nothing
held its request thread and socket with no time limit.

THE DEFECT (the RM-744 shape, measured on :8888): ``agents/daemon_slayer/
server.py`` ``Handler`` set no deadline, and ``_RcThreadingHTTPServer``
hands it a socket with no timeout, so ``handle_one_request``'s
``rfile.readline`` blocked for as long as the client stayed connected. Only
the request BODY was deadlined (RM-152, ``_read_body_deadlined``). Measured
before the fix (in-process, production ``start_server``): an idle client was
still open at 65 s, its request thread alive.

THE FIX: the shared RM-744 ``core.http_head_deadline.HeadDeadlineMixin`` on
the DS ``Handler`` - one TOTAL deadline for the request line plus headers,
removed once the head is parsed, never a class-level ``timeout`` (RM-152).
Not an engine change: no ``ENGINE_VERSION`` bump.

Lives in ``tests/`` beside the DS RM-738 server test: it pins a transport
property of the HTTP shell, not an engine number.
"""
from __future__ import annotations

import contextlib
import json
import socket
import threading
import time

import pytest

from agents.daemon_slayer import server as ds_server
from agents.daemon_slayer.data_loader import DataSnapshot

Handler = ds_server.Handler

_HOST = "127.0.0.1"
_CLOSED = (ConnectionResetError, ConnectionAbortedError)
_TEST_DEADLINE_S = 0.75


@pytest.fixture(scope="module")
def snap():
    return DataSnapshot.load()


@pytest.fixture
def short_head_deadline(monkeypatch: pytest.MonkeyPatch) -> float:
    # raising=False: before the fix the attribute does not exist, and the
    # test must then fail on BEHAVIOUR (the client is never closed).
    monkeypatch.setattr(Handler, "head_read_timeout_s", _TEST_DEADLINE_S,
                        raising=False)
    return _TEST_DEADLINE_S


def _close(srv, serve: threading.Thread) -> None:
    stopper = threading.Thread(target=srv.shutdown, daemon=True)
    stopper.start()
    stopper.join(timeout=2)
    srv.server_close()
    serve.join(timeout=2)


@contextlib.contextmanager
def _served(srv):
    serve = threading.Thread(target=srv.serve_forever, daemon=True,
                             name="rm748-serve")
    serve.start()
    parked: list[socket.socket] = []
    try:
        yield srv.server_address[1], parked
    finally:
        for s in parked:
            with contextlib.suppress(OSError):
                s.close()
        _close(srv, serve)


def _ds(snap):
    """The production server, production Handler."""
    return _served(ds_server.start_server(host=_HOST, port=0, snapshot=snap))


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
                    f"request head (RM-748)")
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

def test_an_idle_client_is_closed_at_the_head_deadline(snap, short_head_deadline):
    with _ds(snap) as (port, parked):
        s = _connect(port, parked)
        elapsed = _time_to_close(s, wait_s=6.0)
    assert elapsed < short_head_deadline + 3.0, elapsed


def test_a_request_line_with_no_headers_is_closed_at_the_head_deadline(
        snap, short_head_deadline):
    with _ds(snap) as (port, parked):
        s = _connect(port, parked)
        s.sendall(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n")
        elapsed = _time_to_close(s, wait_s=6.0)
    assert elapsed < short_head_deadline + 3.0, elapsed


def test_a_trickling_head_is_cut_at_the_total_deadline(snap, monkeypatch):
    monkeypatch.setattr(Handler, "head_read_timeout_s", 1.0, raising=False)
    stop = threading.Event()
    with _ds(snap) as (port, parked):
        s = _connect(port, parked)
        s.sendall(b"GET /health HTTP/1.1\r\nX-Slow: ")

        def trickle() -> None:
            while not stop.wait(0.2):
                try:
                    s.sendall(b"a")
                except OSError:
                    return

        t = threading.Thread(target=trickle, daemon=True, name="rm748-trickle")
        t.start()
        try:
            elapsed = _time_to_close(s, wait_s=6.0)
        finally:
            stop.set()
            t.join(timeout=2)
    assert 0.5 <= elapsed < 3.5, elapsed


# -- legitimate clients the deadline must not touch ---------------------------

def test_a_slow_speaker_inside_the_deadline_gets_health(snap, monkeypatch):
    monkeypatch.setattr(Handler, "head_read_timeout_s", 3.0, raising=False)
    with _ds(snap) as (port, parked):
        s = _connect(port, parked)
        time.sleep(0.6)
        s.sendall(b"GET /health HTTP/1.1\r\n")
        time.sleep(0.6)
        s.sendall(b"Host: 127.0.0.1\r\nConnection: close\r\n\r\n")
        reply = _read_all(s)
    head, _, payload = reply.partition(b"\r\n\r\n")
    assert _status(reply) == b"200", head
    assert json.loads(payload)["engine_version"] == ds_server.ENGINE_VERSION


def test_a_post_body_slower_than_the_head_deadline_is_still_read(
        snap, short_head_deadline):
    """The head deadline ends with the head. A body that lands after it (but
    inside the RM-152 body deadline) is still parsed: the unknown-champion
    404 needs the WHOLE body; a body cut by a leaked deadline is a 408."""
    body = b'{"champion": "Notarealchamp", "level": 1}'
    with _ds(snap) as (port, parked):
        s = _connect(port, parked)
        s.sendall(b"POST /stats HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                  b"Content-Type: application/json\r\nConnection: close\r\n"
                  b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n")
        time.sleep(short_head_deadline * 2)
        s.sendall(body)
        reply = _read_all(s)
    head, _, payload = reply.partition(b"\r\n\r\n")
    assert _status(reply) == b"404", head
    assert "error" in json.loads(payload)


class _Probe(Handler):
    """Records the socket timeout the route sees, after a pause longer than
    the head deadline."""

    seen: list = []

    def do_GET(self) -> None:  # noqa: N802 (stdlib name)
        time.sleep(_TEST_DEADLINE_S * 2)
        type(self).seen.append(self.connection.gettimeout())
        self._send_json(200, {"ok": True})


def test_the_route_sees_the_socket_timeout_restored(short_head_deadline):
    _Probe.seen = []
    srv = ds_server._RcThreadingHTTPServer((_HOST, 0), _Probe)
    with _served(srv) as (port, parked):
        s = _connect(port, parked)
        s.sendall(b"GET /rm748 HTTP/1.0\r\n\r\n")
        reply = _read_all(s)
    assert reply.endswith(b'{"ok": true}'), reply[:160]
    assert _Probe.seen == [None], (
        f"the head deadline leaked into the route: socket timeout "
        f"{_Probe.seen!r}, expected [None]")


def test_the_shipped_head_deadline_is_generous_and_finite():
    cap = getattr(Handler, "head_read_timeout_s", None)
    assert cap is not None, "DS Handler has no request-head deadline (RM-748)"
    assert 10.0 <= cap <= 120.0, cap
    # RM-152: never the per-receive, connection-lifetime class-level timeout.
    assert Handler.timeout is None, Handler.timeout

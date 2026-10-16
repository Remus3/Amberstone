"""RM-744: a :8888 client that connects (or completes the TLS handshake) and
then sends nothing held its request thread and socket with no time limit.

THE DEFECT: ``dashboard/server.py`` ``_DualProtocolHTTPServer._negotiate``
puts the wrapped socket back to ``settimeout(None)`` after the handshake, and
``dashboard/_handler.py`` ``Handler`` set no deadline of its own, so
``handle_one_request``'s ``rfile.readline`` blocked for as long as the client
held the connection open. Only the request BODY was deadlined (RM-152,
``_read_body_deadlined``). Measured 2026-10-16 before the fix: an idle
handshaken client was still open after 180 s on the live :8888 and on the
in-process server, its request thread alive the whole time.

WHY NOT A CLASS-LEVEL ``timeout``: RM-152 measured that one (2026-08-04). It
is armed in ``setup()`` for the life of the connection and is PER RECEIVE, so
it aborts a client slow to speak or one whose headers arrive in two packets
with a gap, and a trickler sending one byte per window is never cut.

THE FIX (``core/http_head_deadline.py``): one TOTAL deadline for the request
line plus the headers, recomputed before every socket read so a trickler
cannot re-arm it, and removed (socket timeout restored) the moment the head
is parsed - so the body read, long responses and SSE streams see the socket
exactly as before. The shipped budget is generous (a real head lands in one
packet); the tests lower it on the class.

Teardown closes the parked clients first, then shuts the server down with a
bounded wait.
"""
from __future__ import annotations

import contextlib
import datetime
import ipaddress
import socket
import ssl
import threading
import time

import pytest

from dashboard import server
from dashboard._handler import Handler

_HOST = "::1"
_CLOSED = (ConnectionResetError, ConnectionAbortedError)
_TEST_DEADLINE_S = 0.75


@pytest.fixture
def short_head_deadline(monkeypatch: pytest.MonkeyPatch) -> float:
    # raising=False: before the fix the attribute does not exist, and the
    # test must then fail on BEHAVIOUR (the client is never closed), not on
    # the patch itself.
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
                             name="rm744-serve")
    serve.start()
    parked: list[socket.socket] = []
    try:
        yield srv.server_address[1], parked
    finally:
        for s in parked:
            with contextlib.suppress(OSError):
                s.close()
        _close(srv, serve)


def _plain(handler=Handler):
    """The production no-cert fallback class, real dashboard Handler."""
    return _served(server._DualStackHTTPServer((_HOST, 0), handler))


def _connect(port: int, parked: list) -> socket.socket:
    s = socket.create_connection((_HOST, port), timeout=5)
    parked.append(s)
    return s


def _time_to_close(sock, wait_s: float) -> float:
    """Seconds until the server closes ``sock``; fails if it never does."""
    sock.settimeout(wait_s)
    t0 = time.monotonic()
    try:
        data = sock.recv(1)
    except _CLOSED:
        data = b""
    except (TimeoutError, ssl.SSLError) as exc:
        if isinstance(exc, TimeoutError):
            pytest.fail(f"the server still held the connection after "
                        f"{wait_s:.1f}s of client silence: no deadline on the "
                        f"request head (RM-744)")
        data = b""
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


# -- the defect ---------------------------------------------------------------

def test_an_idle_plain_client_is_closed_at_the_head_deadline(short_head_deadline):
    with _plain() as (port, parked):
        s = _connect(port, parked)
        elapsed = _time_to_close(s, wait_s=6.0)
    assert elapsed < short_head_deadline + 3.0, elapsed


def test_a_request_line_with_no_headers_is_closed_at_the_head_deadline(
        short_head_deadline):
    with _plain() as (port, parked):
        s = _connect(port, parked)
        s.sendall(b"GET /api/ui-version HTTP/1.1\r\nHost: x\r\n")
        elapsed = _time_to_close(s, wait_s=6.0)
    assert elapsed < short_head_deadline + 3.0, elapsed


class _Trickler:
    """Sends ``head`` then one byte every ``every_s``, never ending the head -
    each byte lands well inside any per-receive timeout."""

    def __init__(self, sock: socket.socket, head: bytes, every_s: float) -> None:
        self.sock = sock
        self._every_s = every_s
        self._stop = threading.Event()
        sock.sendall(head)
        self._t = threading.Thread(target=self._run, daemon=True,
                                   name="rm744-trickle")
        self._t.start()

    def _run(self) -> None:
        while not self._stop.wait(self._every_s):
            try:
                self.sock.sendall(b"a")
            except OSError:
                return

    def stop(self) -> None:
        self._stop.set()
        self._t.join(timeout=2)


def test_a_trickling_head_is_cut_at_the_total_deadline(monkeypatch):
    monkeypatch.setattr(Handler, "head_read_timeout_s", 1.0, raising=False)
    with _plain() as (port, parked):
        s = _connect(port, parked)
        trickler = _Trickler(s, b"GET /api/ui-version HTTP/1.1\r\nX-Slow: ",
                             every_s=0.2)
        try:
            elapsed = _time_to_close(s, wait_s=6.0)
        finally:
            trickler.stop()
    # Cut BY the total deadline: the head never completes, so not before it.
    assert 0.5 <= elapsed < 3.5, elapsed


# -- the TLS path (production class, real certificate) ------------------------

def _self_signed(tmp_path):
    pytest.importorskip("cryptography")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "rm744-test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address(_HOST))]),
                critical=False)
            .sign(key, hashes.SHA256()))
    cert_path = tmp_path / "rm744-cert.pem"
    key_path = tmp_path / "rm744-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    return cert_path, key_path


def _tls_server(tmp_path):
    cert_path, key_path = _self_signed(tmp_path)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)      # start_dashboard's shape
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    cctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    cctx.load_verify_locations(cafile=str(cert_path))
    srv = server._DualProtocolHTTPServer((_HOST, 0), Handler, ssl_ctx=ctx)
    return srv, cctx


def test_an_idle_handshaken_tls_client_is_closed_at_the_head_deadline(
        tmp_path, short_head_deadline):
    srv, cctx = _tls_server(tmp_path)
    with _served(srv) as (port, parked):
        raw = _connect(port, parked)
        tls = cctx.wrap_socket(raw, server_hostname=_HOST)
        parked.append(tls)
        elapsed = _time_to_close(tls, wait_s=6.0)
    assert elapsed < short_head_deadline + 3.0, elapsed


def test_a_tls_client_that_speaks_still_gets_200(tmp_path, short_head_deadline):
    srv, cctx = _tls_server(tmp_path)
    with _served(srv) as (port, parked):
        raw = _connect(port, parked)
        tls = cctx.wrap_socket(raw, server_hostname=_HOST)
        parked.append(tls)
        tls.sendall(b"GET /api/ui-version HTTP/1.0\r\n\r\n")
        reply = _read_all(tls)
    assert reply.split(b"\r\n", 1)[0].split(b" ")[1] == b"200", reply[:120]


# -- legitimate clients the deadline must not touch ---------------------------

def test_a_slow_speaker_inside_the_deadline_is_served(monkeypatch):
    """The RM-152 slow-speaker / split-header shape, re-measured against the
    head deadline: silent before the request line, then a gap between the
    request line and the headers, both well inside the budget."""
    monkeypatch.setattr(Handler, "head_read_timeout_s", 3.0, raising=False)
    with _plain() as (port, parked):
        s = _connect(port, parked)
        time.sleep(0.6)
        s.sendall(b"GET /api/ui-version HTTP/1.1\r\n")
        time.sleep(0.6)
        s.sendall(b"Host: x\r\n\r\n")
        reply = _read_all(s)
    assert reply.split(b"\r\n", 1)[0].split(b" ")[1] == b"200", reply[:120]


def test_a_post_body_slower_than_the_head_deadline_is_still_read(
        short_head_deadline):
    """The head deadline ends with the head: a body that arrives after it
    (but inside the RM-152 body deadline) still reaches the route."""
    body = b'{"command":"bogus"}'
    with _plain() as (port, parked):
        s = _connect(port, parked)
        s.sendall(b"POST /api/command HTTP/1.1\r\nHost: x\r\n"
                  b"Content-Type: application/json\r\n"
                  b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n")
        time.sleep(short_head_deadline * 2)
        s.sendall(body)
        reply = _read_all(s)
    status = reply.split(b"\r\n", 1)[0]
    # 400 = the route read the whole body and refused the bogus command
    # (the RM-152 normal-POST shape); a cut body would close with no reply.
    assert status.split(b" ")[1:2] == [b"400"], (
        f"the body read was cut by the head deadline: {status!r}")


class _Probe(Handler):
    """Records the socket timeout the route sees, after a pause longer than
    the head deadline."""

    seen: list = []

    def do_GET(self) -> None:  # noqa: N802 (stdlib name)
        time.sleep(_TEST_DEADLINE_S * 2)
        type(self).seen.append(self.connection.gettimeout())
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_the_route_sees_the_socket_timeout_restored(short_head_deadline):
    _Probe.seen = []
    with _plain(_Probe) as (port, parked):
        s = _connect(port, parked)
        s.sendall(b"GET /rm744 HTTP/1.0\r\n\r\n")
        reply = _read_all(s)
    assert reply.endswith(b"ok"), reply[:120]
    assert _Probe.seen == [None], (
        f"the head deadline leaked into the route: socket timeout "
        f"{_Probe.seen!r}, expected [None] (long responses and SSE streams "
        f"must see the socket as before)")


def test_the_shipped_head_deadline_is_generous_and_finite():
    cap = getattr(Handler, "head_read_timeout_s", None)
    assert cap is not None, "Handler has no request-head deadline (RM-744)"
    assert 10.0 <= cap <= 120.0, cap

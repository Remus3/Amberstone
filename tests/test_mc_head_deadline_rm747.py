"""RM-747: a :8895 Mission Control client that completes the TLS handshake
and then sends nothing held its request thread and socket with no limit.

THE DEFECT (the RM-744 shape, measured on :8888): ``mc/server.py``
``_Server.process_request_thread`` puts the wrapped socket back to
``settimeout(None)`` after its handshake (RM-739), and ``mc/handler.py``
``Handler`` set no deadline of its own, so ``handle_one_request``'s
``rfile.readline`` blocked for as long as the client stayed connected.
Measured before the fix (in-process, production ``_make_server``, a real
self-signed certificate): an idle handshaken client was still open at 65 s.

THE FIX: the shared RM-744 ``core.http_head_deadline.HeadDeadlineMixin`` on
the MC ``Handler`` - one TOTAL deadline for the request line plus headers,
removed once the head is parsed, never a class-level ``timeout`` (RM-152).

Two harnesses. The plain one serves the real ``Handler`` from a stdlib
``ThreadingHTTPServer`` and needs no certificate, so it runs on CI too. The
TLS one is the production ``_make_server`` with a throwaway self-signed
certificate (needs ``cryptography``; CI has none, so it skips there).
"""
from __future__ import annotations

import contextlib
import datetime
import http.server
import ipaddress
import json
import socket
import ssl
import threading
import time

import pytest

from mc.handler import Handler
from tests._timing_budget import fleet_test_guard

_HOST = "127.0.0.1"
_CLOSED = (ConnectionResetError, ConnectionAbortedError)
_TEST_DEADLINE_S = 0.75


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
                             name="rm747-serve")
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
    srv = http.server.ThreadingHTTPServer((_HOST, 0), handler)
    srv.daemon_threads = True
    return _served(srv)


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
    except (TimeoutError, ssl.SSLError) as exc:
        if isinstance(exc, TimeoutError):
            pytest.fail(f"the server still held the connection after "
                        f"{wait_s:.1f}s of client silence: no deadline on the "
                        f"request head (RM-747)")
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


def _status(reply: bytes) -> bytes:
    return reply.split(b"\r\n", 1)[0].split(b" ")[1]


# -- the defect ---------------------------------------------------------------

def test_an_idle_client_is_closed_at_the_head_deadline(short_head_deadline):
    with _plain() as (port, parked):
        s = _connect(port, parked)
        elapsed = _time_to_close(s, wait_s=6.0)
    assert elapsed < fleet_test_guard.budget(short_head_deadline + 3.0), elapsed


def test_a_trickling_head_is_cut_at_the_total_deadline(monkeypatch):
    monkeypatch.setattr(Handler, "head_read_timeout_s", 1.0, raising=False)
    stop = threading.Event()
    with _plain() as (port, parked):
        s = _connect(port, parked)
        s.sendall(b"GET /api/loop-status HTTP/1.1\r\nX-Slow: ")

        def trickle() -> None:
            while not stop.wait(0.2):
                try:
                    s.sendall(b"a")
                except OSError:
                    return

        t = threading.Thread(target=trickle, daemon=True, name="rm747-trickle")
        t.start()
        try:
            elapsed = _time_to_close(s, wait_s=6.0)
        finally:
            stop.set()
            t.join(timeout=2)
    # Cut BY the total deadline: one byte every 0.2 s never re-arms it.
    assert 0.5 <= elapsed < fleet_test_guard.budget(3.5), elapsed


# -- legitimate clients the deadline must not touch ---------------------------

def test_a_slow_speaker_inside_the_deadline_is_served(monkeypatch):
    monkeypatch.setattr(Handler, "head_read_timeout_s", 3.0, raising=False)
    with _plain() as (port, parked):
        s = _connect(port, parked)
        time.sleep(0.6)
        s.sendall(b"GET /rm747-unrouted HTTP/1.1\r\n")
        time.sleep(0.6)
        s.sendall(b"Host: 127.0.0.1\r\nConnection: close\r\n\r\n")
        reply = _read_all(s)
    assert _status(reply) == b"404", reply[:120]


def test_a_post_body_slower_than_the_head_deadline_is_still_read(
        short_head_deadline, monkeypatch):
    """The head deadline ends with the head. An authorised POST whose body
    lands after it still reaches routing: a JSON 404 for an unrouted path. A
    body read cut by a leaked deadline would end in the 500 branch."""
    monkeypatch.setenv("RC_MC_TOKEN", "rm747-test-token")
    body = b'{"action":"noop"}'
    with _plain() as (port, parked):
        s = _connect(port, parked)
        s.sendall(b"POST /rm747-unrouted HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                  b"Authorization: Bearer rm747-test-token\r\n"
                  b"Content-Type: application/json\r\nConnection: close\r\n"
                  b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n")
        time.sleep(short_head_deadline * 2)
        s.sendall(body)
        reply = _read_all(s)
    head, _, payload = reply.partition(b"\r\n\r\n")
    assert _status(reply) == b"404", head
    assert json.loads(payload) == {"ok": False, "error": "not found"}


class _Probe(Handler):
    """Records the socket timeout the route sees, after a pause longer than
    the head deadline."""

    seen: list = []

    def do_GET(self) -> None:  # noqa: N802 (stdlib name)
        time.sleep(_TEST_DEADLINE_S * 2)
        type(self).seen.append(self.connection.gettimeout())
        self._send(200, b"ok", "text/plain")


def test_the_route_sees_the_socket_timeout_restored(short_head_deadline):
    _Probe.seen = []
    with _plain(_Probe) as (port, parked):
        s = _connect(port, parked)
        s.sendall(b"GET /rm747 HTTP/1.0\r\n\r\n")
        reply = _read_all(s)
    assert reply.endswith(b"ok"), reply[:120]
    assert _Probe.seen == [None], (
        f"the head deadline leaked into the route: socket timeout "
        f"{_Probe.seen!r}, expected [None]")


def test_the_shipped_head_deadline_is_generous_and_finite():
    cap = getattr(Handler, "head_read_timeout_s", None)
    assert cap is not None, "MC Handler has no request-head deadline (RM-747)"
    assert 10.0 <= cap <= 120.0, cap
    # RM-152: never the per-receive, connection-lifetime class-level timeout.
    assert Handler.timeout is None, Handler.timeout


# -- the production TLS server ------------------------------------------------

def _self_signed(tmp_path):
    pytest.importorskip("cryptography")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "rm747-test")])
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
    cert_path = tmp_path / "rm747-cert.pem"
    key_path = tmp_path / "rm747-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    return cert_path, key_path


def _tls_server(tmp_path, monkeypatch):
    from mc import server as mod

    cert_path, key_path = _self_signed(tmp_path)
    monkeypatch.setattr(mod, "CERT_PATH", cert_path)
    monkeypatch.setattr(mod, "KEY_PATH", key_path)
    monkeypatch.setattr(mod, "PORT", 0)
    srv = mod._make_server(_HOST, mod._ssl_context())
    cctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    cctx.minimum_version = ssl.TLSVersion.TLSv1_2
    cctx.load_verify_locations(cafile=str(cert_path))
    return srv, cctx


def test_an_idle_handshaken_tls_client_is_closed_at_the_head_deadline(
        tmp_path, monkeypatch, short_head_deadline):
    srv, cctx = _tls_server(tmp_path, monkeypatch)
    with _served(srv) as (port, parked):
        raw = _connect(port, parked)
        tls = cctx.wrap_socket(raw, server_hostname=_HOST)
        parked.append(tls)
        elapsed = _time_to_close(tls, wait_s=6.0)
    assert elapsed < fleet_test_guard.budget(short_head_deadline + 3.0), elapsed


def test_a_tls_client_that_speaks_still_gets_json_404(
        tmp_path, monkeypatch, short_head_deadline):
    srv, cctx = _tls_server(tmp_path, monkeypatch)
    with _served(srv) as (port, parked):
        raw = _connect(port, parked)
        tls = cctx.wrap_socket(raw, server_hostname=_HOST)
        parked.append(tls)
        tls.sendall(b"GET /rm747-unrouted HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        reply = _read_all(tls)
    head, _, payload = reply.partition(b"\r\n\r\n")
    assert _status(reply) == b"404", head
    assert json.loads(payload) == {"ok": False, "error": "not found"}

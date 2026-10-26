"""RM-742: the :8888 dashboard peeked, redirected and TLS-handshook on the
accept thread, so one silent or trickling client stalled every other accept.

THE DEFECT: ``dashboard/server.py`` ``_DualProtocolHTTPServer.get_request``
ran on the ``serve_forever`` thread and, before returning, set a 5.0 s socket
timeout, peeked one byte and either ran ``wrap_socket`` (TLS) or the inline
301 (plain HTTP, 2.0 s per recv, looping to 8 KB). A client that connected
and sent nothing held every other :8888 accept for 5 s (N such clients:
N x 5 s); a plain client trickling one byte at a time held them longer, since
each recv restarted its 2.0 s timeout. Measured live 2026-10-15 before the fix
(``curl -k https://127.0.0.1:8888/api/state``): 0.007-0.016 s alone, 4.8 s
behind one silent TCP client, 14.8 s behind three.

THE FIX (the RM-739 ``mc/server.py`` shape): ``get_request`` is a plain
accept again; the peek, the 301 and the handshake run in
``process_request_thread`` on the request's own RM-738 thread, under ONE total
deadline (``negotiate_deadline_s``) for the whole setup; a failure drops and
logs only that connection.

The first tests need no certificate: a server context with no cert loaded
fails every handshake fast with an alert, so ANY quick outcome on the second
client proves the accept loop reached it; only a timeout is the stall. The
last test makes a throwaway self-signed cert (needs ``cryptography``; CI has
none, so it skips there) and asserts a real, verified 200 while a silent
client holds its connection.

Teardown closes the parked clients FIRST, then shuts the server down with a
bounded wait, so a stalled accept loop reports as a failure, not a hang.
"""
from __future__ import annotations

import contextlib
import datetime
import ipaddress
import json
import logging
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler

import pytest

from dashboard import server
from tests._timing_budget import fleet_test_guard

_HOST = "::1"
_CLIENT_TIMEOUT_S = 2.0
_CLOSED = (ConnectionResetError, ConnectionAbortedError)


class _Hung(AssertionError):
    pass


class _Ok(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (stdlib name)
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a: object) -> None:
        pass


def _close(srv, serve: threading.Thread) -> None:
    # Bounded: a stalled accept loop never acknowledges shutdown().
    stopper = threading.Thread(target=srv.shutdown, daemon=True)
    stopper.start()
    stopper.join(timeout=2)
    srv.server_close()
    serve.join(timeout=2)


@contextlib.contextmanager
def _served(ctx, deadline_s=None):
    """The production class on an ephemeral ``::1`` port. ``deadline_s``
    lowers the setup deadline on this instance only."""
    srv = server._DualProtocolHTTPServer((_HOST, 0), _Ok, ssl_ctx=ctx)
    if deadline_s is not None:
        srv.negotiate_deadline_s = deadline_s
    serve = threading.Thread(target=srv.serve_forever, daemon=True,
                             name="rm742-serve")
    serve.start()
    parked: list[socket.socket] = []
    try:
        yield srv, srv.server_address[1], parked
    finally:
        for s in parked:                     # free whatever is parked first
            with contextlib.suppress(OSError):
                s.close()
        _close(srv, serve)


def _silent(port: int, parked: list) -> socket.socket:
    s = socket.create_connection((_HOST, port), timeout=5)
    parked.append(s)
    time.sleep(0.2)                          # the accept loop takes it first
    return s


class _Trickler:
    """A client that sends ``head`` and then one byte at a time, never
    finishing - each byte lands inside any per-recv timeout. The default head
    is a plain-HTTP request line that never reaches its blank line."""

    def __init__(self, port: int, parked: list, every_s: float,
                 head: bytes = b"GET /") -> None:
        self.sock = socket.create_connection((_HOST, port), timeout=5)
        parked.append(self.sock)
        self._every_s = every_s
        self._stop = threading.Event()
        self.sock.sendall(head)
        self._t = threading.Thread(target=self._run, daemon=True,
                                   name="rm742-trickle")
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


def _no_cert_ctx() -> ssl.SSLContext:
    return ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)


def _insecure_client_ctx() -> ssl.SSLContext:
    cctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    cctx.minimum_version = ssl.TLSVersion.TLSv1_2
    cctx.check_hostname = False
    cctx.verify_mode = ssl.CERT_NONE
    return cctx


def _tls_attempt(port: int, timeout: float = _CLIENT_TIMEOUT_S) -> str:
    """Connect and handshake as a TLS client. Any quick answer returns a
    label; raises _Hung when the server neither answers nor closes."""
    try:
        with socket.create_connection((_HOST, port), timeout=timeout) as raw:
            with _insecure_client_ctx().wrap_socket(raw):
                return "handshake-completed"
    except TimeoutError as exc:
        raise _Hung(f"TLS client not served within {timeout}s while another "
                    f"client holds a connection: connection setup runs on "
                    f"the accept thread (RM-742)") from exc
    except OSError as exc:                   # alert, EOF or reset: served
        return type(exc).__name__


def _read_all(sock: socket.socket) -> bytes:
    buf = b""
    while True:
        try:
            chunk = sock.recv(4096)
        except _CLOSED:
            break
        if not chunk:
            break
        buf += chunk
    return buf


# -- no certificate needed ----------------------------------------------------

def test_a_silent_client_does_not_stall_other_accepts():
    with _served(_no_cert_ctx()) as (_srv, port, parked):
        _silent(port, parked)
        try:
            assert _tls_attempt(port)
            assert _tls_attempt(port)        # and the loop is not parked after
        except _Hung as exc:
            pytest.fail(str(exc))


def test_three_silent_clients_do_not_queue_their_stalls():
    with _served(_no_cert_ctx()) as (_srv, port, parked):
        for _ in range(3):
            _silent(port, parked)
        t0 = time.monotonic()
        try:
            assert _tls_attempt(port)
        except _Hung as exc:
            pytest.fail(str(exc))
        assert time.monotonic() - t0 < fleet_test_guard.budget(1.0)


def test_a_trickling_plain_client_does_not_stall_a_tls_client():
    with _served(_no_cert_ctx()) as (_srv, port, parked):
        trickler = _Trickler(port, parked, every_s=0.5)
        try:
            time.sleep(0.3)                  # the server is reading it now
            try:
                assert _tls_attempt(port)
            except _Hung as exc:
                pytest.fail(str(exc))
        finally:
            trickler.stop()


def test_a_plain_http_client_still_gets_the_301(monkeypatch):
    # RM-772: the 301 echoes only an allowlisted Host; inject the placeholder
    # name (never the live per-host config).
    # RM-819: the cache lives in core.http_host_gate (the shared gate).
    from core import http_host_gate as _host_gate
    from dashboard import _handler
    monkeypatch.setattr(_host_gate, "_allowed_names_cache",
                        _handler.build_allowed_host_names(
                            cfg={"tailnet_name": "rc-host"}, env=""))
    with _served(_no_cert_ctx()) as (_srv, port, _parked):
        with socket.create_connection((_HOST, port),
                                      timeout=_CLIENT_TIMEOUT_S) as raw:
            raw.sendall(b"GET /api/state?x=1 HTTP/1.1\r\n"
                        b"Host: rc-host:8888\r\n"
                        b"User-Agent: rm742\r\n\r\n")
            try:
                reply = _read_all(raw)
            except TimeoutError:
                pytest.fail("plain-HTTP client never got its 301 (RM-742)")
    head, _, body = reply.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    assert lines[0] == b"HTTP/1.1 301 Moved Permanently", lines[0]
    headers = dict(h.split(b": ", 1) for h in lines[1:])
    location = f"https://rc-host:{server.PORT}/api/state?x=1".encode("ascii")
    assert headers[b"Location"] == location, headers
    assert headers[b"Content-Type"] == b"text/html; charset=utf-8", headers
    assert headers[b"Connection"] == b"close", headers
    assert int(headers[b"Content-Length"]) == len(body), (headers, body)
    assert location in body, body


def test_the_setup_deadline_is_total_not_per_receive():
    """A trickler whose bytes each land inside any per-recv timeout is still
    cut at the total deadline (best-effort 301, then close)."""
    with _served(_no_cert_ctx(), deadline_s=1.0) as (_srv, port, parked):
        trickler = _Trickler(port, parked, every_s=0.2)
        try:
            trickler.sock.settimeout(4.0)
            t0 = time.monotonic()
            try:
                reply = _read_all(trickler.sock)
            except TimeoutError:
                pytest.fail("a trickling client was held past the total "
                            "setup deadline (RM-742)")
            elapsed = time.monotonic() - t0
        finally:
            trickler.stop()
    # Cut BY the deadline: the head never completes, so not before it either.
    assert 0.5 <= elapsed < fleet_test_guard.budget(2.5), elapsed
    assert reply.startswith(b"HTTP/1.1 301 "), reply[:80]


def test_a_trickling_tls_handshake_shares_the_total_deadline():
    """The handshake is inside the same deadline: a TLS record header that
    announces a 16 KB ClientHello whose body then trickles in (each byte
    inside any per-read timeout) is still dropped at the deadline."""
    with _served(_no_cert_ctx(), deadline_s=1.0) as (_srv, port, parked):
        trickler = _Trickler(port, parked, every_s=0.2,
                             head=b"\x16\x03\x01\x40\x00")
        try:
            trickler.sock.settimeout(4.0)
            t0 = time.monotonic()
            try:
                reply = _read_all(trickler.sock)
            except TimeoutError:
                pytest.fail("a trickled TLS handshake was held past the total "
                            "setup deadline (RM-742)")
            elapsed = time.monotonic() - t0
        finally:
            trickler.stop()
    # Cut BY the deadline, not by an early record error (the record is
    # well-formed, only incomplete), so not before it either.
    assert 0.5 <= elapsed < fleet_test_guard.budget(2.5), elapsed
    assert not reply.startswith(b"HTTP/"), reply[:80]


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_a_silent_client_is_dropped_at_the_deadline_and_logged():
    log = logging.getLogger("rc.web_dashboard")
    sink = _Records()
    old_level = log.level
    log.addHandler(sink)
    log.setLevel(logging.DEBUG)
    try:
        with _served(_no_cert_ctx(), deadline_s=0.5) as (srv, port, parked):
            silent = _silent(port, parked)
            silent.settimeout(3.0)
            try:
                data = silent.recv(1)
            except _CLOSED:
                data = b""
            except TimeoutError:
                pytest.fail("the silent client was never dropped: no setup "
                            "deadline on the request thread (RM-742)")
            assert data == b"", "a silent client must be closed, not answered"
            assert srv.negotiate_failures == 1
    finally:
        log.removeHandler(sink)
        log.setLevel(old_level)
    msgs = [r.getMessage() for r in sink.records]
    assert any("RM-742" in m for m in msgs), msgs
    # Logged as a dropped connection, never as a raw traceback.
    assert all(r.exc_info is None for r in sink.records), msgs


def test_no_ssl_context_is_a_plain_pass_through():
    """The seam the RM-738 / RM-740 tests stand on: ``ssl_ctx=None`` serves
    the connection as it arrived (plain), with no peek, 301 or wrap."""
    with _served(None) as (_srv, port, _parked):
        with socket.create_connection((_HOST, port),
                                      timeout=_CLIENT_TIMEOUT_S) as raw:
            raw.sendall(b"GET / HTTP/1.0\r\n\r\n")
            reply = _read_all(raw)
    assert reply.startswith(b"HTTP/1.0 200 "), reply[:80]


def test_the_default_setup_deadline_is_short_and_finite():
    cap = server._DualProtocolHTTPServer.negotiate_deadline_s
    assert 0 < cap <= 10, cap


# -- a real certificate, a real 200 -------------------------------------------

def _self_signed(tmp_path):
    pytest.importorskip("cryptography")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "rm742-test")])
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
    cert_path = tmp_path / "rm742-cert.pem"
    key_path = tmp_path / "rm742-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    return cert_path, key_path


def test_a_verified_client_gets_200_while_a_silent_client_holds_on(tmp_path):
    cert_path, key_path = _self_signed(tmp_path)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)      # start_dashboard's shape
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))

    cctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    cctx.minimum_version = ssl.TLSVersion.TLSv1_2
    cctx.load_verify_locations(cafile=str(cert_path))   # verified, never -k

    with _served(ctx) as (_srv, port, parked):
        _silent(port, parked)
        buf = b""
        try:
            with socket.create_connection((_HOST, port),
                                          timeout=_CLIENT_TIMEOUT_S) as raw:
                with cctx.wrap_socket(raw, server_hostname=_HOST) as tls:
                    tls.sendall(b"GET /rm742 HTTP/1.0\r\n\r\n")
                    while True:
                        chunk = tls.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
        except TimeoutError:
            pytest.fail("verified TLS client not served while a silent client "
                        "holds a connection (RM-742)")
    head, _, body = buf.partition(b"\r\n\r\n")
    assert head.split(b" ", 2)[1] == b"200", head
    assert json.loads(body) == {"ok": True}

"""RM-739: one silent TLS client froze Mission Control's :8895 accept loop.

THE DEFECT: mc/server.py ``_make_server`` wrapped the LISTEN socket
(``ctx.wrap_socket(srv.socket, server_side=True)``) with the default
``do_handshake_on_connect=True``. ``SSLSocket.accept()`` then ran the
server-side handshake inline on the ``serve_forever`` thread, on an accepted
socket with no timeout. A client that connects and never sends a ClientHello
parks that bind address's accept loop until it hangs up, and every other
client of that address hangs. RM-738's capped thread start does not reach
it: the handshake ran before ``process_request``.

THE FIX: the listen socket stays plain; each connection's handshake runs on
its own request thread with a deadline (``_Server.tls_handshake_timeout_s``),
and a handshake that fails or runs out of time drops that one connection.

Every server here is built by the production ``_make_server``. The first
tests need no certificate: a real server context with no cert loaded fails
every handshake fast with an alert, so ANY quick outcome on the second
client (alert, EOF, reset, even a completed handshake) proves the accept loop
reached it; only a timeout is the wedge. The last test makes a throwaway
self-signed cert (needs ``cryptography``; CI has none, so it skips there),
loads it through the production ``_ssl_context()`` and asserts a real,
verified JSON 404 while the silent client still holds its connection - the
live acceptance shape from docs/OPERATIONS.md "Mission Control (:8895)".

Teardown closes the silent client FIRST (whatever is parked on it is freed),
then shuts the server down with a bounded wait, so a wedged accept loop
reports as a failure instead of hanging the run.
"""
from __future__ import annotations

import contextlib
import datetime
import ipaddress
import json
import socket
import ssl
import threading
import time

import pytest

_CLIENT_TIMEOUT_S = 2.0


class _Hung(AssertionError):
    pass


def _close(srv) -> None:
    # Bounded, as in tests/test_misc_servers_thread_start_rm738.py: a wedged
    # accept loop never acknowledges shutdown().
    stopper = threading.Thread(target=srv.shutdown, daemon=True)
    stopper.start()
    stopper.join(timeout=2)
    srv.server_close()


@contextlib.contextmanager
def _served_with_silent_client(monkeypatch, ctx, handshake_s=None):
    """Production server on an ephemeral loopback port, plus one raw TCP
    client that connects and never sends a byte. ``handshake_s`` lowers the
    handshake deadline on this instance only (set before the silent client
    connects)."""
    from mc import server as mod

    monkeypatch.setattr(mod, "PORT", 0)
    srv = mod._make_server("127.0.0.1", ctx)
    if handshake_s is not None:
        srv.tls_handshake_timeout_s = handshake_s
    threading.Thread(target=srv.serve_forever, daemon=True,
                     name="rm739-serve").start()
    port = srv.server_address[1]
    silent = None
    try:
        silent = socket.create_connection(("127.0.0.1", port), timeout=5)
        time.sleep(0.2)                      # the accept loop takes it first
        yield srv, port, silent
    finally:
        if silent is not None:
            silent.close()
        _close(srv)


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
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as raw:
            with _insecure_client_ctx().wrap_socket(raw):
                return "handshake-completed"
    except TimeoutError as exc:
        raise _Hung(f"second TLS client not served within {timeout}s while a "
                    f"silent client holds a connection: the handshake runs on "
                    f"the accept loop (RM-739)") from exc
    except OSError as exc:                   # alert, EOF or reset: served
        return type(exc).__name__


# -- no certificate needed ----------------------------------------------------

def test_a_silent_client_does_not_freeze_the_accept_loop(monkeypatch):
    no_cert = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with _served_with_silent_client(monkeypatch, no_cert) as (_srv, port, _s):
        try:
            outcome = _tls_attempt(port)
        except _Hung as exc:
            pytest.fail(str(exc))
        assert outcome, "the second client must get a quick outcome"
        # And again: the loop is not parked after serving one either.
        try:
            assert _tls_attempt(port)
        except _Hung as exc:
            pytest.fail(str(exc))


def test_a_silent_client_is_dropped_at_the_handshake_deadline(monkeypatch):
    """The handshake is bounded, so a silent connection does not pin a
    thread and a socket for as long as the peer likes."""
    no_cert = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with _served_with_silent_client(monkeypatch, no_cert,
                                    handshake_s=0.5) as (_srv, _port, silent):
        silent.settimeout(3.0)
        try:
            data = silent.recv(1)
        except (ConnectionResetError, ConnectionAbortedError):
            data = b""
        except TimeoutError:
            pytest.fail("the silent client was never dropped: no handshake "
                        "deadline (RM-739)")
        assert data == b"", "a silent client must be closed, not answered"


def test_a_plaintext_request_is_never_answered_in_plaintext(monkeypatch):
    """The listen socket is plain now, so TLS is applied per connection.
    Guard the fail-open shape: a control plane that can kill never answers
    HTTP without TLS (needs no cert, so it runs on CI too)."""
    no_cert = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with _served_with_silent_client(monkeypatch, no_cert) as (_srv, port, _s):
        reply = b""
        with socket.create_connection(("127.0.0.1", port),
                                      timeout=_CLIENT_TIMEOUT_S) as raw:
            raw.sendall(b"GET /rm739-unrouted HTTP/1.0\r\n"
                        b"Host: 127.0.0.1\r\n\r\n")
            try:
                while True:
                    chunk = raw.recv(4096)
                    if not chunk:
                        break
                    reply += chunk
            except (ConnectionResetError, ConnectionAbortedError):
                pass
            except TimeoutError:
                pytest.fail("plaintext probe neither refused nor closed "
                            "(RM-739)")
        assert not reply.startswith(b"HTTP/"), reply[:80]


def test_the_default_handshake_deadline_is_short_and_finite():
    from mc import server as mod
    cap = mod._Server.tls_handshake_timeout_s
    assert 0 < cap <= 10, cap


# -- a real certificate, a real JSON 404 ---------------------------------------

def _self_signed(tmp_path):
    pytest.importorskip("cryptography")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "rm739-test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                critical=False)
            .sign(key, hashes.SHA256()))
    cert_path = tmp_path / "rm739-cert.pem"
    key_path = tmp_path / "rm739-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    return cert_path, key_path


def test_a_verified_client_gets_json_404_while_a_silent_client_holds_on(
        tmp_path, monkeypatch):
    from mc import server as mod

    cert_path, key_path = _self_signed(tmp_path)
    monkeypatch.setattr(mod, "CERT_PATH", cert_path)
    monkeypatch.setattr(mod, "KEY_PATH", key_path)
    ctx = mod._ssl_context()

    cctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    cctx.minimum_version = ssl.TLSVersion.TLSv1_2
    cctx.load_verify_locations(cafile=str(cert_path))   # verified, never -k

    with _served_with_silent_client(monkeypatch, ctx) as (_srv, port, _s):
        buf = b""
        try:
            with socket.create_connection(("127.0.0.1", port),
                                          timeout=_CLIENT_TIMEOUT_S) as raw:
                with cctx.wrap_socket(raw, server_hostname="127.0.0.1") as tls:
                    tls.sendall(b"GET /rm739-unrouted HTTP/1.0\r\n"
                                b"Host: 127.0.0.1\r\n\r\n")
                    while True:
                        chunk = tls.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
        except TimeoutError:
            pytest.fail("verified TLS client not served while a silent client "
                        "holds a connection (RM-739)")
    head, _, body = buf.partition(b"\r\n\r\n")
    assert head.split(b" ", 2)[1] == b"404", head
    assert b"application/json" in head, head
    assert json.loads(body) == {"ok": False, "error": "not found"}

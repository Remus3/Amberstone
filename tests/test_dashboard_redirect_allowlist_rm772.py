"""RM-772: the :8888 plain-HTTP 301 built ``Location`` from ANY well-formed
Host, not the RM-759 allowlist.

THE DEFECT: ``dashboard/server.py`` ``_DualProtocolHTTPServer._inline_redirect``
passes the Host value through ``_redirect_host`` (the RM-745 shape check
only) and answers ``Location: https://<host>:<PORT><path>``. The RM-759 gate
(``dashboard._handler.HostAllowlistMixin``) runs in the HTTPS handler, never
on this redirect, so a name this machine does not answer to was redirected
to itself. Measured live 2026-10-23 before the fix: ``GET /p`` with
``Host: rebind.example`` on plain :8888 answered
``Location: https://rebind.example:8888/p``.

THE FIX: a Host the allowlist refuses falls back to the existing
``127.0.0.1`` default; allowed names (loopback, IP literals, this machine's
configured names) still redirect to themselves, spelled as sent.

Every name below is a placeholder; the allowlist is INJECTED and the live
per-host config (``ops/local_hosts.json``) is never read.
"""
from __future__ import annotations

import contextlib
import re
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler

import pytest

from core import http_host_gate as _host_gate
from dashboard import _handler, server

_HOST = "::1"
_CLOSED = (ConnectionResetError, ConnectionAbortedError)

_CFG = {
    "tailnet_name": "rc-host",
    "tailnet_fqdn": "rc-host.example-tailnet.ts.net",
    "cert_sans": ["rc-host", "rc-host.example-tailnet.ts.net", "100.64.0.5",
                  "192.0.2.10"],
}


class _Ok(BaseHTTPRequestHandler):
    def log_message(self, *a: object) -> None:
        pass


@pytest.fixture(autouse=True)
def injected_allowlist(monkeypatch):
    names = _handler.build_allowed_host_names(cfg=_CFG, env="")
    # RM-819: the cache lives in core.http_host_gate (the shared gate).
    monkeypatch.setattr(_host_gate, "_allowed_names_cache", names)
    return names


@pytest.fixture(scope="module")
def port():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)   # no cert: plain path only
    srv = server._DualProtocolHTTPServer((_HOST, 0), _Ok, ssl_ctx=ctx)
    serve = threading.Thread(target=srv.serve_forever, daemon=True,
                             name="rm772-serve")
    serve.start()
    try:
        yield srv.server_address[1]
    finally:
        stopper = threading.Thread(target=srv.shutdown, daemon=True)
        stopper.start()
        stopper.join(timeout=2)
        srv.server_close()
        serve.join(timeout=2)


def _location(port: int, host_value: bytes | None, path: bytes = b"/p") -> bytes:
    head = b"GET " + path + b" HTTP/1.1\r\n"
    if host_value is not None:
        head += b"Host: " + host_value + b"\r\n"
    with socket.create_connection((_HOST, port), timeout=5) as raw:
        raw.sendall(head + b"\r\n")
        buf = b""
        with contextlib.suppress(*_CLOSED):
            while True:
                chunk = raw.recv(4096)
                if not chunk:
                    break
                buf += chunk
    lines = re.split(rb"\r\n", buf.partition(b"\r\n\r\n")[0])
    assert lines[0] == b"HTTP/1.1 301 Moved Permanently", lines
    locs = [ln.split(b": ", 1)[1] for ln in lines[1:]
            if ln.lower().startswith(b"location:")]
    assert len(locs) == 1, lines
    return locs[0]


def _expected(host: str, path: str = "/p") -> bytes:
    return f"https://{host}:{server.PORT}{path}".encode("ascii")


# -- the defect ---------------------------------------------------------------

@pytest.mark.parametrize("host_value", [
    b"rebind.example", b"rebind.example:8888", b"rebind.example.",
    b"localhost.rebind.example", b"127.0.0.1.nip.io",
    b"rc-host.rebind.example", b"evil",
], ids=["name", "name-port", "trailing-dot", "localhost-prefix", "nip-io",
        "suffix-trick", "bare-label"])
def test_a_refused_host_falls_back_to_loopback(port, host_value):
    """Passed before the fix: the foreign name was echoed into Location."""
    assert _location(port, host_value) == _expected("127.0.0.1")


def test_an_unreadable_config_falls_back_to_loopback_names_only(
        port, monkeypatch):
    """The allowlist's own fail-closed path applies to the redirect too: a
    configured name is no longer echoed, IP literals and loopback still are."""
    def _boom(*_a, **_kw):
        raise OSError("per-host config unreadable (RM-772 test)")
    monkeypatch.setattr(_host_gate, "_allowed_names_cache", None)
    monkeypatch.setattr(_host_gate, "build_allowed_host_names", _boom)
    assert _location(port, b"rc-host") == _expected("127.0.0.1")
    assert _location(port, b"localhost") == _expected("localhost")
    assert _location(port, b"192.0.2.7") == _expected("192.0.2.7")


# -- allowed names still redirect to themselves --------------------------------

@pytest.mark.parametrize("host_value, host", [
    (b"127.0.0.1", "127.0.0.1"),
    (b"localhost:8888", "localhost"),
    (b"[::1]:8888", "[::1]"),
    (b"rc-host:8888", "rc-host"),
    (b"RC-HOST", "RC-HOST"),
    (b"rc-host.example-tailnet.ts.net", "rc-host.example-tailnet.ts.net"),
    (b"rc-host.example-tailnet.ts.net.", "rc-host.example-tailnet.ts.net."),
    (b"100.64.0.5:8888", "100.64.0.5"),
    (b"192.0.2.77", "192.0.2.77"),      # any IP literal (a LAN DHCP move)
], ids=["loopback-v4", "localhost", "loopback-v6", "name-port", "upper",
        "fqdn", "fqdn-dot", "tailnet-v4", "lan-v4-unlisted"])
def test_an_allowed_host_still_redirects_to_itself(port, host_value, host):
    assert _location(port, host_value) == _expected(host)


def test_no_host_still_redirects_to_loopback(port):
    assert _location(port, None) == _expected("127.0.0.1")

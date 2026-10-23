"""RM-745: the :8888 plain-HTTP 301 built ``Location`` from the client's own
Host header and request path without neutralising CR / LF.

THE DEFECT: ``dashboard/server.py`` ``_DualProtocolHTTPServer._inline_redirect``
split the request head on ``\\r\\n`` only, so a bare LF (or CR) survived in
the request-line path and inside the Host value, and both went verbatim into
the ``Location:`` header and the HTML body. Measured 2026-10-16 before the
fix, live :8888 and in-process alike: ``Host: rc-host\\nX-Injected: host``
answered ``Location: https://rc-host\\nX-Injected:8888/api/state`` - a client
that ends lines on LF reads an injected ``X-Injected`` header in its OWN
reply (self-only, hence low). Same root cause, same lines: a bracketed IPv6
Host (``[::1]:8888``) was cut at its first colon (``https://[:8888/p``),
and a ``"`` or ``<`` in the path reached the HTML body unescaped.

THE FIX: the host is taken only when it is a plain DNS name, an IPv4
literal or a bracketed IPv6 literal (else the existing ``127.0.0.1``
default); every path byte outside printable ASCII is percent-encoded; the
body escapes the URL for HTML. A normal request still gets the same 301.

No certificate is needed: the plain path runs before any TLS.
"""
from __future__ import annotations

import contextlib
import html
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
_HEADER_NAMES = [b"Location", b"Content-Type", b"Content-Length", b"Connection"]


class _Ok(BaseHTTPRequestHandler):
    def log_message(self, *a: object) -> None:
        pass


@pytest.fixture(autouse=True)
def injected_allowlist(monkeypatch):
    """RM-772: the 301 echoes only a Host the RM-759 allowlist passes, so the
    placeholder names these tests redirect to are injected (never the live
    per-host config)."""
    names = _handler.build_allowed_host_names(
        cfg={"tailnet_name": "rc-host",
             "tailnet_fqdn": "rc-host.example-tailnet.ts.net"}, env="")
    # RM-819: the cache lives in core.http_host_gate (the shared gate).
    monkeypatch.setattr(_host_gate, "_allowed_names_cache", names)


def _close(srv, serve: threading.Thread) -> None:
    stopper = threading.Thread(target=srv.shutdown, daemon=True)
    stopper.start()
    stopper.join(timeout=2)
    srv.server_close()
    serve.join(timeout=2)


@pytest.fixture(scope="module")
def port():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)   # no cert: plain path only
    srv = server._DualProtocolHTTPServer((_HOST, 0), _Ok, ssl_ctx=ctx)
    serve = threading.Thread(target=srv.serve_forever, daemon=True,
                             name="rm745-serve")
    serve.start()
    try:
        yield srv.server_address[1]
    finally:
        _close(srv, serve)


def _redirect(port: int, request: bytes) -> tuple[list[bytes], bytes]:
    """Send ``request`` in plain HTTP; return (head lines split on ANY line
    terminator - CRLF, bare LF or bare CR - and the body)."""
    with socket.create_connection((_HOST, port), timeout=5) as raw:
        raw.sendall(request)
        buf = b""
        with contextlib.suppress(*_CLOSED):
            while True:
                chunk = raw.recv(4096)
                if not chunk:
                    break
                buf += chunk
    head, _, body = buf.partition(b"\r\n\r\n")
    return re.split(rb"\r\n|\n|\r", head), body


def _location(lines: list[bytes]) -> bytes:
    """Assert the head is exactly the 301 status line plus the four expected
    headers (nothing injected), all printable ASCII; return Location."""
    assert lines[0] == b"HTTP/1.1 301 Moved Permanently", lines
    names = [ln.split(b":", 1)[0] for ln in lines[1:]]
    assert names == _HEADER_NAMES, (
        f"the 301 head carries an injected line: {lines!r} (RM-745)")
    for ln in lines:
        assert all(0x20 <= c <= 0x7E for c in ln), (
            f"a control or non-ASCII byte in the 301 head: {ln!r} (RM-745)")
    return lines[1].split(b": ", 1)[1]


def _expected(host: str, path: str) -> bytes:
    return f"https://{host}:{server.PORT}{path}".encode("ascii")


# -- the defect ---------------------------------------------------------------

@pytest.mark.parametrize("host_value", [
    b"rc-host\nX-Injected: host",
    b"rc-host\rX-Injected: host",
    b"rc-host:8888\nX-Injected: host",
], ids=["bare-lf", "bare-cr", "lf-after-port"])
def test_a_line_break_in_host_injects_nothing(port, host_value):
    lines, body = _redirect(
        port, b"GET /api/state HTTP/1.1\r\nHost: " + host_value + b"\r\n\r\n")
    location = _location(lines)
    # An unusable Host falls back to the existing default, never the junk.
    assert location == _expected("127.0.0.1", "/api/state"), location
    assert b"X-Injected" not in body, body


@pytest.mark.parametrize("target, expected_path", [
    (b"/a\nX-Injected:path", "/a%0AX-Injected:path"),
    (b"/a\rX-Injected:path", "/a%0DX-Injected:path"),
    (b"/a\x00b\x1bc\x7fd\te", "/a%00b%1Bc%7Fd%09e"),
], ids=["bare-lf", "bare-cr", "other-controls"])
def test_a_control_byte_in_the_path_is_percent_encoded(port, target,
                                                       expected_path):
    lines, _body = _redirect(
        port, b"GET " + target + b" HTTP/1.1\r\nHost: rc-host:8888\r\n\r\n")
    assert _location(lines) == _expected("rc-host", expected_path)


def test_a_non_ascii_path_is_percent_encoded_not_mangled(port):
    lines, _body = _redirect(
        port, b"GET /caf\xc3\xa9 HTTP/1.1\r\nHost: rc-host\r\n\r\n")
    assert _location(lines) == _expected("rc-host", "/caf%C3%A9")


def test_a_bracketed_ipv6_host_keeps_its_address(port):
    lines, _body = _redirect(
        port, b"GET /p HTTP/1.1\r\nHost: [::1]:8888\r\n\r\n")
    assert _location(lines) == _expected("[::1]", "/p")


@pytest.mark.parametrize("host_value", [
    b"evil.example/x", b"a@evil.example", b"a b", b"[::1", b"[not-v6]:8888",
    b"rc-host:88x", b"caf\xc3\xa9",
], ids=["slash", "userinfo", "space", "open-bracket", "bad-v6", "bad-port",
        "non-ascii"])
def test_a_host_that_is_not_a_plain_host_falls_back_to_the_default(port,
                                                                    host_value):
    lines, _body = _redirect(
        port, b"GET /p HTTP/1.1\r\nHost: " + host_value + b"\r\n\r\n")
    assert _location(lines) == _expected("127.0.0.1", "/p")


def test_the_body_escapes_the_url_for_html(port):
    lines, body = _redirect(
        port, b'GET /a"><b>x&y HTTP/1.1\r\nHost: rc-host\r\n\r\n')
    location = _location(lines)
    assert location == _expected("rc-host", '/a"><b>x&y')
    assert b'"><b>' not in body, body
    escaped = html.escape(location.decode("ascii"), quote=True).encode("ascii")
    assert body.count(escaped) == 2, body


# -- the normal 301 is unchanged ----------------------------------------------

@pytest.mark.parametrize("host_value, host", [
    (b"rc-host:8888", "rc-host"),
    (b"RC-HOST", "RC-HOST"),
    (b"rc-host.example-tailnet.ts.net:8888", "rc-host.example-tailnet.ts.net"),
    (b"192.0.2.7:8888", "192.0.2.7"),
    (b"127.0.0.1", "127.0.0.1"),
], ids=["name-port", "upper", "fqdn", "lan-v4", "loopback"])
def test_a_normal_request_gets_the_same_301(port, host_value, host):
    lines, body = _redirect(
        port, b"GET /api/state?x=1&y=2 HTTP/1.1\r\nHost: " + host_value
        + b"\r\nUser-Agent: rm745\r\n\r\n")
    location = _location(lines)
    assert location == _expected(host, "/api/state?x=1&y=2"), location
    headers = dict(ln.split(b": ", 1) for ln in lines[1:])
    assert int(headers[b"Content-Length"]) == len(body), (headers, body)


def test_no_host_header_still_redirects_to_loopback(port):
    lines, _body = _redirect(port, b"GET /x HTTP/1.0\r\n\r\n")
    assert _location(lines) == _expected("127.0.0.1", "/x")

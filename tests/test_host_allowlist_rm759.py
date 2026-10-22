"""RM-759: a Host-header allowlist on the :8888 dashboard and the :8890
supervisor server (DNS rebinding).

THE DEFECT. Neither server looked at the ``Host`` header. A page on an
attacker's domain whose DNS answer is re-pointed at 127.0.0.1 (DNS
rebinding) is, to the browser, SAME-ORIGIN with ``http://<that domain>:8890``:
it can read every GET response and its POSTs carry ``Origin`` equal to
``Host``, so the same-origin rule (``_same_origin_ok``) passed them as well.
Measured live before the fix (2026-10-22): ``curl --resolve
rebind.example:8890:127.0.0.1 http://rebind.example:8890/api/queue`` -> 200.
:8888 is TLS, so a browser would first stop on the certificate name, but
``curl -k`` with the same rebound name -> 200: the certificate was the only
thing in the way.

THE FIX. Both handlers refuse, with 421 Misdirected Request, any request
whose Host names something other than loopback, an IP literal, or one of
this machine's configured names (``core.local_hosts`` cert SANs and tailnet
names, plus the ``RC_ALLOWED_HOSTS`` env extras). An IP-literal Host can
never be the product of a rebinding - the attack needs a NAME whose answer
changes - so any IP literal passes and a LAN viewer survives a DHCP move. A
missing Host passes (browsers always send one; HTTP/1.0 scripts may not).
``_same_origin_ok`` additionally requires the Origin / Referer hostname to
be allowed, and a parse failure now refuses instead of allowing.

Every name below is a placeholder (rc-host, example-tailnet, 100.64.0.x,
192.0.2.x); the allowlist is INJECTED and the live per-host config
(``ops/local_hosts.json``) is never read.
"""
from __future__ import annotations

import logging
import socket
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from dashboard import _dispatch, _handler
from dashboard._handler import Handler

_HOST = "127.0.0.1"
_CLOSED = (ConnectionResetError, ConnectionAbortedError)

# Placeholder per-host config, in the ops/local_hosts.json shape.
_CFG = {
    "tailnet_name": "rc-host",
    "tailnet_fqdn": "rc-host.example-tailnet.ts.net",
    "tailnet_ipv4": "100.64.0.5",
    "lan_ipv4": "192.0.2.10",
    "cert_sans": ["RC-Host", "rc-host.example-tailnet.ts.net.", "100.64.0.5",
                  "192.0.2.10", 7, None, "  "],
}

_REBOUND = ("rebind.example", "rebind.example.", "localhost.rebind.example",
            "127.0.0.1.nip.io", "rc-host.rebind.example", "evil")


@pytest.fixture(autouse=True)
def injected_allowlist(monkeypatch):
    """The allowlist the servers see, built from placeholder config only."""
    names = _handler.build_allowed_host_names(cfg=_CFG, env="")
    monkeypatch.setattr(_handler, "_allowed_names_cache", names)
    return names


# -- the parse ---------------------------------------------------------------

@pytest.mark.parametrize("value, want", [
    ("127.0.0.1:8888", "127.0.0.1"),
    ("127.0.0.1", "127.0.0.1"),
    ("[::1]:8888", "::1"),
    ("[::1]", "::1"),
    ("::1", "::1"),                       # unbracketed literal, some clients
    ("RC-Host:8888", "rc-host"),
    ("localhost.", "localhost"),
    ("rebind.example:8890", "rebind.example"),
    ("  127.0.0.1:8888  ", "127.0.0.1"),
    ("", ""),
])
def test_host_header_hostname_parses(value, want):
    assert _handler.host_header_hostname(value) == want


@pytest.mark.parametrize("value", [
    "[::1",                 # unclosed bracket
    "[::1]x",               # junk after the bracket
    "[::1]:88a8",           # non-numeric port
    "rc-host:http",         # non-numeric port
    "rc-host:",             # empty port
    "a b",                  # whitespace inside
    "user@rc-host",         # userinfo
    "rc-host/x",            # path
    "rc-host\x1b[31m",      # control bytes
])
def test_host_header_hostname_rejects_malformed(value):
    assert _handler.host_header_hostname(value) is None


def test_allowlist_is_built_from_config_lowercased_and_normalised(
        injected_allowlist):
    assert {"127.0.0.1", "localhost", "::1", "rc-host",
            "rc-host.example-tailnet.ts.net"} <= injected_allowlist
    # Non-strings and blanks are dropped, never str()-ed into a name.
    assert "7" not in injected_allowlist and "none" not in injected_allowlist
    assert "" not in injected_allowlist


def test_env_extras_are_added():
    names = _handler.build_allowed_host_names(
        cfg={}, env=" Extra-Name , other.example-tailnet ,, ")
    assert {"extra-name", "other.example-tailnet"} <= names
    assert {"127.0.0.1", "localhost", "::1"} <= names


def test_absent_config_is_loopback_only():
    names = _handler.build_allowed_host_names(cfg={}, env="")
    assert names == frozenset({"127.0.0.1", "localhost", "::1"})


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "rc-host",
                                  "rc-host.example-tailnet.ts.net",
                                  "100.64.0.5", "192.0.2.10", "192.0.2.77",
                                  "2001:db8::5"])
def test_allowed(host):
    assert _handler.is_allowed_host(host)


@pytest.mark.parametrize("host", ["rebind.example", "localhost.rebind.example",
                                  "127.0.0.1.nip.io", "evil", None])
def test_not_allowed(host):
    assert not _handler.is_allowed_host(host)


# -- the same-origin rule ----------------------------------------------------

def _hdrs(**kw):
    from email.message import Message
    m = Message()
    for k, v in kw.items():
        m[k.replace("_", "-")] = v
    return m


def test_same_origin_refuses_a_rebound_origin_equal_to_host():
    """Passed before the fix: Origin == Host is 'same origin' to the browser."""
    assert not _handler._same_origin_ok(
        _hdrs(Origin="http://rebind.example:8890", Host="rebind.example:8890"))


@pytest.mark.parametrize("origin, host", [
    ("https://127.0.0.1:8888", "127.0.0.1:8888"),
    ("https://[::1]:8888", "[::1]:8888"),
    ("https://localhost:8888", "localhost:8888"),
    ("https://rc-host:8888", "rc-host:8888"),
    ("https://192.0.2.10:8888", "192.0.2.10:8888"),
    ("https://127.0.0.1:8888", "rc-host:8888"),     # loopback script to LAN bind
])
def test_same_origin_still_passes_legitimate_pages(origin, host):
    assert _handler._same_origin_ok(_hdrs(Origin=origin, Host=host))


def test_same_origin_without_origin_or_referer_still_passes():
    assert _handler._same_origin_ok(_hdrs(Host="127.0.0.1:8888"))


def test_same_origin_refuses_an_unparseable_host():
    assert not _handler._same_origin_ok(
        _hdrs(Origin="https://127.0.0.1:8888", Host="[::1"))


def test_same_origin_parse_failure_refuses():
    class _Boom:
        def get(self, *_a, **_kw):
            raise RuntimeError("header parse blew up")
    assert _handler._same_origin_ok(_Boom()) is False


# -- :8888, the real Handler over a real socket ------------------------------

@pytest.fixture
def dashboard(monkeypatch):
    calls: list[tuple] = []

    def _get(h):
        calls.append(("GET", h.path))
        h._send(200, b"ok", "text/plain")
        return True

    def _post(h, payload):
        calls.append(("POST", h.path, payload))
        h._send(200, b"{}", "application/json")
        return True

    monkeypatch.setattr(_dispatch, "dispatch_get", _get)
    monkeypatch.setattr(_dispatch, "dispatch_post", _post)
    srv = ThreadingHTTPServer((_HOST, 0), Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_address[1], calls
    finally:
        srv.shutdown()
        srv.server_close()


def _raw(port: int, payload: bytes, timeout: float = 8.0,
         half_close: bool = False) -> bytes:
    buf = b""
    with socket.create_connection((_HOST, port), timeout=timeout) as s:
        s.sendall(payload)
        if half_close:
            s.shutdown(socket.SHUT_WR)
        while True:
            try:
                chunk = s.recv(65536)
            except _CLOSED:
                break
            if not chunk:
                break
            buf += chunk
    return buf


def _status(reply: bytes) -> int | None:
    if not reply.startswith(b"HTTP/"):
        return None
    return int(reply.split(b"\r\n", 1)[0].split(b" ")[1])


def _get(port: int, host: str | None, path: str = "/api/state") -> bytes:
    head = f"GET {path} HTTP/1.0\r\n"
    if host is not None:
        head += f"Host: {host}\r\n"
    return _raw(port, (head + "\r\n").encode("latin-1"))


@pytest.mark.parametrize("name", _REBOUND)
def test_dashboard_refuses_a_rebound_host(dashboard, name):
    port, calls = dashboard
    reply = _get(port, f"{name}:{port}")
    assert _status(reply) == 421, reply[:200]
    assert b"misdirected_host" in reply
    assert calls == [], "the route ran for a rebound Host"


@pytest.mark.parametrize("host", ["127.0.0.1:{p}", "localhost:{p}", "[::1]:{p}",
                                  "rc-host:8888", "RC-HOST", "100.64.0.5:8888",
                                  "192.0.2.10:8888",
                                  "rc-host.example-tailnet.ts.net:8888"])
def test_dashboard_serves_allowed_hosts(dashboard, host):
    port, calls = dashboard
    reply = _get(port, host.format(p=port))
    assert _status(reply) == 200, reply[:200]
    assert calls == [("GET", "/api/state")]


def test_dashboard_serves_a_request_without_host(dashboard):
    port, calls = dashboard
    assert _status(_get(port, None)) == 200
    assert calls


@pytest.mark.parametrize("first, second", [("127.0.0.1", "rebind.example"),
                                           ("rebind.example", "127.0.0.1")])
def test_dashboard_refuses_a_duplicate_host_with_one_rebound(dashboard, first,
                                                             second):
    """Every Host line is checked, not just the first (Message.get)."""
    port, calls = dashboard
    reply = _raw(port, (f"GET /api/state HTTP/1.0\r\nHost: {first}:{port}\r\n"
                        f"Host: {second}:{port}\r\n\r\n").encode())
    assert _status(reply) == 421, reply[:200]
    assert calls == []


def test_dashboard_serves_a_duplicate_allowed_host(dashboard):
    """http.client's putrequest adds a Host itself; a caller that puts one
    too sends two allowed lines, which must still be served."""
    port, calls = dashboard
    reply = _raw(port, (f"GET /api/state HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n"
                        "Host: 127.0.0.1\r\n\r\n").encode())
    assert _status(reply) == 200, reply[:200]
    assert calls


def test_dashboard_refuses_a_rebound_post_before_dispatch(dashboard):
    """Origin == Host passed the CSRF rule; the Host gate stops it first, and
    the 421 arrives intact (the small body is drained, so no RST)."""
    port, calls = dashboard
    body = b'{"command":"noop"}'
    reply = _raw(port, (f"POST /api/command HTTP/1.0\r\nHost: rebind.example:{port}\r\n"
                        f"Origin: http://rebind.example:{port}\r\n"
                        "Content-Type: text/plain\r\n"
                        f"Content-Length: {len(body)}\r\n\r\n").encode() + body)
    assert _status(reply) == 421, reply[:200]
    assert calls == []


def test_dashboard_allowed_post_still_dispatches(dashboard):
    port, calls = dashboard
    body = b'{"command":"noop"}'
    reply = _raw(port, (f"POST /api/command HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n"
                        f"Origin: https://127.0.0.1:{port}\r\n"
                        f"Content-Length: {len(body)}\r\n\r\n").encode() + body)
    assert _status(reply) == 200, reply[:200]
    assert calls == [("POST", "/api/command", {"command": "noop"})]


def _record_handle_error(srv) -> list:
    """Replace the server's handle_error (socketserver prints a traceback
    there for any exception a handler raises) with a recorder."""
    errors: list = []
    srv.handle_error = lambda request, client_address: errors.append(
        client_address)
    return errors


def _http09(port: int, path: str) -> bytes:
    """A raw HTTP/0.9 request: a two-word request line, no headers at all.

    The write side is half-closed after the request line: Python 3.12's
    ``parse_request`` still reads a header block after a 0.9 line (3.14
    does not), so without EOF a 3.12 server waits for headers until the
    client's recv times out (CI ubuntu 3.12, 2026-10-22)."""
    return _raw(port, f"GET {path}\r\n".encode(), half_close=True)


@pytest.fixture
def dashboard_srv(monkeypatch):
    """The :8888 Handler, with the server object exposed (handle_error)."""
    calls: list[tuple] = []

    def _get(h):
        calls.append(("GET", h.path))
        h._send(200, b"ok", "text/plain")
        return True

    monkeypatch.setattr(_dispatch, "dispatch_get", _get)
    srv = ThreadingHTTPServer((_HOST, 0), Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv, calls
    finally:
        srv.shutdown()
        srv.server_close()


def test_dashboard_refuses_http09_cleanly(dashboard_srv):
    """Python 3.14 sets ``headers = {}`` for HTTP/0.9, which has no Host at
    all: letting it through would be a headerless bypass of the gate, and
    calling ``get_all`` on the dict crashed the handler (empty reply plus a
    traceback via handle_error). Now: connection closed, nothing served."""
    srv, calls = dashboard_srv
    errors = _record_handle_error(srv)
    reply = _http09(srv.server_address[1], "/api/state")
    assert reply == b"", reply[:200]
    assert calls == [], "the route ran for an HTTP/0.9 request"
    assert errors == [], "the handler raised (traceback via handle_error)"


def test_supervisor_refuses_http09_cleanly(supervisor_http):
    errors = _record_handle_error(supervisor_http)
    port = supervisor_http.server_address[1]
    for path in ("/api/queue", "/ok.txt"):
        reply = _http09(port, path)
        assert reply == b"", (path, reply[:200])
    assert supervisor_http.supervisor.scheduler.calls == []
    assert errors == [], "the handler raised (traceback via handle_error)"


def test_refusal_log_names_the_peer_and_is_scrubbed(dashboard):
    port, _calls = dashboard
    records: list[logging.LogRecord] = []

    class _Cap(logging.Handler):
        def emit(self, record):
            records.append(record)

    lg = logging.getLogger("rc.web_dashboard")
    cap, prior = _Cap(), lg.level
    lg.addHandler(cap)
    lg.setLevel(logging.DEBUG)
    try:
        reply = _raw(port, (f"GET /api/state HTTP/1.0\r\n"
                            f"Host: rebind\x1b[31m.example:{port}\r\n\r\n")
                     .encode("latin-1"))
    finally:
        lg.removeHandler(cap)
        lg.setLevel(prior)
    assert _status(reply) == 421
    warnings = [r.getMessage() for r in records if r.levelno >= logging.WARNING]
    assert any("RM-759" in m and _HOST in m for m in warnings), warnings
    for m in warnings:
        assert "\x1b" not in m, m


# -- :8890, the real _WebServer + _QuietHandler ------------------------------

class _Scheduler:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def snapshot(self):
        self.calls.append(("snapshot",))
        return {"ready": 0}

    def file_task(self, **kw):
        self.calls.append(("file_task", kw))
        raise AssertionError("a task was filed (RM-759 test)")


class _Supervisor:
    def __init__(self) -> None:
        self.scheduler = _Scheduler()
        self.warm_agent7 = None


@pytest.fixture
def supervisor_http(tmp_path: Path):
    from agents._supervisor_http import _QuietHandler, _WebServer
    root = tmp_path / "webroot"
    root.mkdir()
    (root / "ok.txt").write_bytes(b"public\n")
    srv = _WebServer((_HOST, 0),
                     lambda *a, **kw: _QuietHandler(*a, directory=str(root), **kw))
    srv.supervisor = _Supervisor()
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv
    finally:
        stopper = threading.Thread(target=srv.shutdown, daemon=True)
        stopper.start()
        stopper.join(timeout=2)
        srv.server_close()
        t.join(timeout=2)


@pytest.mark.parametrize("path", ["/api/queue", "/ok.txt"])
def test_supervisor_refuses_a_rebound_host(supervisor_http, path):
    port = supervisor_http.server_address[1]
    reply = _get(port, f"rebind.example:{port}", path)
    assert _status(reply) == 421, reply[:200]
    assert supervisor_http.supervisor.scheduler.calls == []


@pytest.mark.parametrize("path, body", [("/api/queue", b'"ready"'),
                                        ("/ok.txt", b"public")])
def test_supervisor_serves_loopback(supervisor_http, path, body):
    port = supervisor_http.server_address[1]
    reply = _get(port, f"127.0.0.1:{port}", path)
    assert _status(reply) == 200, reply[:200]
    assert body in reply


def test_supervisor_refuses_a_rebound_post_before_dispatch(supervisor_http):
    port = supervisor_http.server_address[1]
    body = b'{"op":"x","owner_agent":"6"}'
    reply = _raw(port, (f"POST /api/file-task HTTP/1.0\r\nHost: rebind.example:{port}\r\n"
                        f"Origin: http://rebind.example:{port}\r\n"
                        "Content-Type: text/plain\r\n"
                        f"Content-Length: {len(body)}\r\n\r\n").encode() + body)
    assert _status(reply) == 421, reply[:200]
    assert supervisor_http.supervisor.scheduler.calls == []


def test_supervisor_head_is_refused_too(supervisor_http):
    port = supervisor_http.server_address[1]
    reply = _raw(port, f"HEAD /ok.txt HTTP/1.0\r\nHost: rebind.example:{port}\r\n\r\n"
                 .encode())
    assert _status(reply) == 421, reply[:200]
    assert b"misdirected_host" not in reply      # HEAD carries no body

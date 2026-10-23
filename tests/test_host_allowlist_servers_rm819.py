"""RM-819 (a): the RM-759 Host gate on every other RC HTTP server.

THE DEFECT. RM-759 / RM-773 / RM-774 gated only the :8888 dashboard and the
:8890 supervisor server. The other HTTP listeners never looked at the Host
header: the DS engine (``agents/daemon_slayer/server.py``, :8860), Mission
Control (``mc/handler.py``, :8895), the DS + match-DB MCP server
(``tools/ds_matchdb_mcp_server.py``, :8861), the vision server
(``vision_server/_http.py``, :8889) and the replay server
(``tools/replay_session.py``, :8897). A page on an attacker's domain whose
DNS answer is re-pointed at 127.0.0.1 is SAME-ORIGIN, to the browser, with
``http://<that domain>:<port>`` and reads every response a route gives
without a header the page cannot set (DS /health and every DS GET, vision
/health and /monitor, the replay /api/state and allgamedata mirror, an
unauthenticated mc GET). Measured before the fix with these harnesses: a
rebound Host -> 200 on all five.

THE FIX. The gate was lifted from ``dashboard/_handler.py`` to
``core/http_host_gate.py`` (the servers that must not import ``dashboard/``
can take it there, the ``core.log_scrub`` precedent) and each handler lists
``HostAllowlistMixin`` first: 421 for a Host this machine does not answer
to, 400 for a head whose parse lost header lines (RM-773) or a target that
is not origin-form (RM-774), HTTP/0.9 closed - before any route runs.

The route handlers are replaced by recorders in most tests, so the gate is
measured on its own and no route reads live state; one test per server
drives the REAL route. Every name is a placeholder (rc-host, example-tailnet,
100.64.0.x, 192.0.2.x); the allowlist is INJECTED and the live per-host
config (``ops/local_hosts.json``) is never read.
"""
from __future__ import annotations

import contextlib
import http.server
import logging
import socket
import threading
from typing import Callable, Iterator

import pytest

from core import http_host_gate as _host_gate
from core.http_head_deadline import HeadDeadlineMixin

_HOST = "127.0.0.1"
_CLOSED = (ConnectionResetError, ConnectionAbortedError)

_CFG = {
    "tailnet_name": "rc-host",
    "tailnet_fqdn": "rc-host.example-tailnet.ts.net",
    "tailnet_ipv4": "100.64.0.5",
    "lan_ipv4": "192.0.2.10",
    "cert_sans": ["rc-host", "100.64.0.5", "192.0.2.10"],
}

_REBOUND = ("rebind.example", "rebind.example.", "localhost.rebind.example",
            "127.0.0.1.nip.io", "rc-host.rebind.example", "evil")


@pytest.fixture(autouse=True)
def injected_allowlist(monkeypatch):
    names = _host_gate.build_allowed_host_names(cfg=_CFG, env="")
    monkeypatch.setattr(_host_gate, "_allowed_names_cache", names)
    return names


# -- the five servers, each built by its production factory where one exists --

def _ds_server():
    from agents.daemon_slayer import server as ds_server
    from agents.daemon_slayer.data_loader import DataSnapshot
    return ds_server.start_server(host=_HOST, port=0,
                                  snapshot=_ds_snapshot(DataSnapshot))


_DS_SNAP: list = []


def _ds_snapshot(cls):
    if not _DS_SNAP:
        _DS_SNAP.append(cls.load())
    return _DS_SNAP[0]


def _mc_server():
    # mc/server.py's production server is TLS (needs a certificate); the
    # gate lives in the Handler, so a plain server over it measures it.
    from mc.handler import Handler
    srv = http.server.ThreadingHTTPServer((_HOST, 0), Handler)
    srv.daemon_threads = True
    return srv


def _matchdb_server():
    import tools.ds_matchdb_mcp_server as mod
    return mod._MatchDBHTTPServer((_HOST, 0), mod._Handler)


def _vision_server():
    import vision_server
    return vision_server.make_server(_HOST, 0)


def _replay_server():
    from tools import replay_session as rs
    return rs.make_server(rs.ReplayState({}), port=0)


SERVERS: dict[str, Callable] = {
    "ds-8860": _ds_server,
    "mc-8895": _mc_server,
    "matchdb-8861": _matchdb_server,
    "vision-8889": _vision_server,
    "replay-8897": _replay_server,
}

# The logger each server reports a refusal on (its own, never the
# dashboard's); the replay server logs nothing of its own, so the gate's.
LOGGERS = {
    "ds-8860": "daemon_slayer.server",
    "mc-8895": "rc.mc.handler",
    "matchdb-8861": "ds-matchdb-mcp",
    "vision-8889": "moon_vision",
    "replay-8897": "rc.http_host_gate",
}

# One real route per server, answered without a token or a live game, and
# the status it gives an allowed Host.
REAL_ROUTE = {
    "ds-8860": ("/health", 200),
    "mc-8895": ("/no-such-route", 404),
    "matchdb-8861": ("/health", 401),        # bearer-gated: 401 is the route
    "vision-8889": ("/health", 200),
    "replay-8897": ("/api/state", 404),      # no frame yet
}


def _stop(srv, serve: threading.Thread) -> None:
    stopper = threading.Thread(target=srv.shutdown, daemon=True)
    stopper.start()
    stopper.join(timeout=5)
    srv.server_close()
    serve.join(timeout=5)


@contextlib.contextmanager
def _serving(srv) -> Iterator[int]:
    serve = threading.Thread(target=srv.serve_forever, daemon=True,
                             name="rm819-serve")
    serve.start()
    try:
        yield srv.server_address[1]
    finally:
        _stop(srv, serve)


def _recording(monkeypatch, srv) -> list:
    """Replace the server's route handlers with recorders that answer 200."""
    calls: list = []
    cls = srv.RequestHandlerClass

    def _reply(h):
        body = b"ok"
        h.send_response(200)
        h.send_header("Content-Type", "text/plain")
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        if h.command != "HEAD":
            h.wfile.write(body)

    def _get(h):
        calls.append(("GET", h.path))
        _reply(h)

    def _post(h):
        n = int(h.headers.get("Content-Length") or 0)
        body = h.rfile.read(n) if n > 0 else b""
        calls.append(("POST", h.path, body))
        _reply(h)

    monkeypatch.setattr(cls, "do_GET", _get)
    monkeypatch.setattr(cls, "do_HEAD", _get, raising=False)
    monkeypatch.setattr(cls, "do_POST", _post, raising=False)  # replay: GET only
    return calls


@pytest.fixture(params=sorted(SERVERS))
def gated(request, monkeypatch):
    """(name, port, calls) for one server, its routes replaced by recorders."""
    srv = SERVERS[request.param]()
    calls = _recording(monkeypatch, srv)
    with _serving(srv) as port:
        yield request.param, port, calls, srv


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


def _get(port: int, host: str | None, path: str = "/health",
         extra: str = "") -> bytes:
    head = f"GET {path} HTTP/1.0\r\n" + extra
    if host is not None:
        head += f"Host: {host}\r\n"
    return _raw(port, (head + "\r\n").encode("latin-1"))


# -- the gate is the shared one, listed first -----------------------------

def _handler_classes():
    from agents.daemon_slayer.server import Handler as ds
    from mc.handler import Handler as mc
    from tools.ds_matchdb_mcp_server import _Handler as matchdb
    from vision_server._http import Handler as vision
    return {"ds-8860": ds, "mc-8895": mc, "matchdb-8861": matchdb,
            "vision-8889": vision}


@pytest.mark.parametrize("name", sorted(SERVERS))
def test_handler_lists_the_shared_mixin_first(name):
    if name == "replay-8897":
        cls = _replay_server().RequestHandlerClass
    else:
        cls = _handler_classes()[name]
    mro = cls.__mro__
    assert _host_gate.HostAllowlistMixin in mro, f"{name}: no Host gate"
    assert cls.__bases__[0] is _host_gate.HostAllowlistMixin, (
        f"{name}: the gate must be the FIRST base, got {cls.__bases__}")
    if HeadDeadlineMixin in mro:
        assert (mro.index(_host_gate.HostAllowlistMixin)
                < mro.index(HeadDeadlineMixin))
    assert cls.MessageClass is _host_gate.HeadOnlyMessage


def test_dashboard_reexports_the_one_implementation():
    """One gate, not a copy: the dashboard's names ARE the core objects."""
    from dashboard import _handler
    for attr in ("HostAllowlistMixin", "HeadOnlyMessage", "host_header_hostname",
                 "is_allowed_host", "build_allowed_host_names",
                 "head_parse_defect", "request_target_ok"):
        assert getattr(_handler, attr) is getattr(_host_gate, attr), attr
    assert _handler.Handler.host_refusal_log is _handler.log


# -- the refusals -----------------------------------------------------------

@pytest.mark.parametrize("rebound", _REBOUND)
def test_a_rebound_host_is_421_before_any_route(gated, rebound):
    name, port, calls, _srv = gated
    reply = _get(port, f"{rebound}:{port}")
    assert _status(reply) == 421, (name, reply[:200])
    assert b"misdirected_host" in reply, name
    assert calls == [], f"{name}: the route ran for a rebound Host"


@pytest.mark.parametrize("host", ["127.0.0.1:{p}", "localhost:{p}", "[::1]:{p}",
                                  "rc-host:{p}", "RC-HOST",
                                  "rc-host.example-tailnet.ts.net:{p}",
                                  "100.64.0.5:{p}", "192.0.2.77"])
def test_an_allowed_host_still_reaches_the_route(gated, host):
    name, port, calls, _srv = gated
    reply = _get(port, host.format(p=port))
    assert _status(reply) == 200, (name, reply[:200])
    assert calls == [("GET", "/health")], name


def test_a_request_without_host_still_reaches_the_route(gated):
    name, port, calls, _srv = gated
    assert _status(_get(port, None)) == 200, name
    assert calls, name


@pytest.mark.parametrize("first, second", [("127.0.0.1", "rebind.example"),
                                           ("rebind.example", "127.0.0.1")])
def test_every_host_line_is_checked(gated, first, second):
    name, port, calls, _srv = gated
    reply = _raw(port, (f"GET /health HTTP/1.0\r\nHost: {first}:{port}\r\n"
                        f"Host: {second}:{port}\r\n\r\n").encode())
    assert _status(reply) == 421, (name, reply[:200])
    assert calls == [], name


def test_a_rebound_post_is_421_intact_and_never_dispatched(gated):
    """The small body is drained first, so the 421 arrives (no RST)."""
    name, port, calls, _srv = gated
    body = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
    reply = _raw(port, (f"POST /mcp HTTP/1.0\r\nHost: rebind.example:{port}\r\n"
                        f"Origin: http://rebind.example:{port}\r\n"
                        "Content-Type: text/plain\r\n"
                        f"Content-Length: {len(body)}\r\n\r\n").encode() + body)
    assert _status(reply) == 421, (name, reply[:200])
    assert calls == [], name


def test_a_lost_header_line_is_400_rm773(gated):
    """A non-header line ends the stdlib parse; the Host after it was lost
    and the request read as Host-less (RM-773)."""
    name, port, calls, _srv = gated
    reply = _get(port, f"rebind.example:{port}", extra="X-Junk\r\n")
    assert _status(reply) == 400, (name, reply[:200])
    assert b"bad_header_block" in reply, name
    assert calls == [], name


def test_an_absolute_form_target_is_400_rm774(gated):
    """The target's authority replaces Host (RFC 9112 3.2.2)."""
    name, port, calls, _srv = gated
    reply = _raw(port, (f"GET http://rebind.example:{port}/health HTTP/1.0\r\n"
                        f"Host: 127.0.0.1:{port}\r\n\r\n").encode())
    assert _status(reply) == 400, (name, reply[:200])
    assert b"bad_request_target" in reply, name
    assert calls == [], name


def test_http09_is_closed_unserved(gated):
    name, port, calls, srv = gated
    errors: list = []
    srv.handle_error = lambda request, client_address: errors.append(
        client_address)
    reply = _raw(port, b"GET /health\r\n", half_close=True)
    assert reply == b"", (name, reply[:200])
    assert calls == [], name
    assert errors == [], f"{name}: the handler raised"


def test_the_refusal_is_logged_on_the_servers_own_logger_scrubbed(gated):
    name, port, _calls, _srv = gated
    records: list[logging.LogRecord] = []

    class _Cap(logging.Handler):
        def emit(self, record):
            records.append(record)

    lg = logging.getLogger(LOGGERS[name])
    cap, prior = _Cap(), lg.level
    lg.addHandler(cap)
    lg.setLevel(logging.DEBUG)
    try:
        reply = _raw(port, (f"GET /health HTTP/1.0\r\n"
                            f"Host: rebind\x1b[31m.example:{port}\r\n\r\n")
                     .encode("latin-1"))
    finally:
        lg.removeHandler(cap)
        lg.setLevel(prior)
    assert _status(reply) == 421, name
    warnings = [r.getMessage() for r in records if r.levelno >= logging.WARNING]
    assert any("RM-759" in m and _HOST in m for m in warnings), (name, warnings)
    for m in warnings:
        assert "\x1b" not in m, m


# -- the real routes --------------------------------------------------------

@pytest.mark.parametrize("name", sorted(SERVERS))
def test_the_real_route_is_gated_and_still_served(name):
    path, allowed_status = REAL_ROUTE[name]
    with _serving(SERVERS[name]()) as port:
        refused = _get(port, f"rebind.example:{port}", path)
        served = _get(port, f"127.0.0.1:{port}", path)
    assert _status(refused) == 421, (name, refused[:200])
    assert _status(served) == allowed_status, (name, served[:200])

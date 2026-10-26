"""PKG-5 (docs/PACKAGING_PLAN.md, security MUST-FIX M5): the :8888 bind host
and who may drive the control endpoints.

THE DEFECT. ``dashboard/server.py`` binds ``HOST = "::"`` (every interface,
the LAN included) and the control-endpoint gate in ``dashboard/_handler.py``
(``is_control_endpoint`` + the RC_DASH_TOKEN check in ``do_POST``) is inert
because RC_DASH_TOKEN is set nowhere. So any LAN host could POST
``/api/lcu-cmd`` (lock pick, lobby invites: it drives the League client),
``/api/loadout/apply``, ``/api/sr-draft/apply``, ``/api/command``,
``/api/input``, ``/api/analyze`` and every ``/api/decisions/`` writer.

THE FIX, two parts:

1. ``RC_DASH_BIND`` picks the bind host (an IP literal). Unset = today's
   ``"::"`` (Legion unchanged: loopback, tailnet and LAN viewers all keep
   loading the page). The packaged launcher sets it to ``LOOPBACK_BIND``
   (``127.0.0.1``). A value that is not an IP literal fails CLOSED to
   loopback. An IPv4 literal gets an AF_INET listener; the class-level
   AF_INET6 dual-stack default is untouched.
2. With no RC_DASH_TOKEN configured, a control-endpoint POST is served only
   to a peer on loopback, on this same machine (peer address == the address
   the connection arrived on), or on the tailnet (peer AND arrival address
   in 100.64.0.0/10 or fd7a:115c:a1e0::/48), plus any CIDR listed in
   ``RC_DASH_CONTROL_NETS``. Everyone else gets 403. Reads (GETs) and
   non-control POSTs are not gated, so LAN viewers keep the page (the RM-240
   posture). A configured token keeps its exact old behaviour (it is the
   section 3.6 layer for the packaged shell) - no browser caller has to send
   a header, so web/ is untouched.

Every address below is a placeholder (127.0.0.1 / ::1 loopback, 100.64.0.x
tailnet, 192.0.2.x and 2001:db8:: documentation ranges for the LAN); only
ephemeral loopback ports are bound.
"""
from __future__ import annotations

import http.client
import io
import socket
import ssl
import threading

import pytest

from dashboard import _dispatch
from dashboard import _handler
from dashboard import server
from dashboard._handler import Handler

_ENV = ("RC_DASH_TOKEN", "RC_DASH_BIND", "RC_DASH_CONTROL_NETS")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """The machine environment never decides a result here."""
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


# -- 1. the bind host ----------------------------------------------------------

def test_default_bind_is_todays_dual_stack_wildcard():
    assert server.HOST == "::"
    assert server.bind_host({}) == "::"


def test_bind_reads_the_process_environment(monkeypatch):
    monkeypatch.setenv("RC_DASH_BIND", "127.0.0.1")
    assert server.bind_host() == "127.0.0.1"


@pytest.mark.parametrize("value, want", [
    ("127.0.0.1", "127.0.0.1"),
    ("  127.0.0.1  ", "127.0.0.1"),
    ("::1", "::1"),
    ("::", "::"),
    ("0.0.0.0", "0.0.0.0"),
    ("100.64.0.5", "100.64.0.5"),
    ("", "::"),            # empty = unset
    ("   ", "::"),
])
def test_bind_env_values(value, want):
    assert server.bind_host({"RC_DASH_BIND": value}) == want


@pytest.mark.parametrize("value", [
    "rc-host", "localhost", "rc-host.example-tailnet.ts.net",
    "127.0.0.1:8888", "[::1]", "999.1.1.1", "not an address",
])
def test_a_bind_value_that_is_not_an_ip_literal_fails_closed_to_loopback(value):
    assert server.bind_host({"RC_DASH_BIND": value}) == server.LOOPBACK_BIND
    assert server.LOOPBACK_BIND == "127.0.0.1"


def test_class_level_family_stays_dual_stack_v6():
    # tests/test_dashboard_server_dualstack.py pins the same; the per-host
    # family is an INSTANCE attribute only.
    assert server._DualStackHTTPServer.address_family == socket.AF_INET6
    assert server._DualProtocolHTTPServer.address_family == socket.AF_INET6


class _Noop(Handler):
    pass


def test_an_ipv4_loopback_bind_gets_an_af_inet_listener():
    srv = server._DualStackHTTPServer(("127.0.0.1", 0), _Noop)
    try:
        assert srv.socket.family == socket.AF_INET
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()


def test_the_wildcard_bind_is_still_dual_stack():
    srv = server._DualStackHTTPServer(("::", 0), _Noop)
    try:
        assert srv.socket.family == socket.AF_INET6
        assert srv.socket.getsockopt(socket.IPPROTO_IPV6,
                                     socket.IPV6_V6ONLY) == 0
    finally:
        srv.server_close()


def test_build_server_without_a_cert_binds_the_env_host(tmp_path, monkeypatch):
    monkeypatch.setenv("RC_DASH_BIND", "127.0.0.1")
    srv, scheme = server._build_server(tmp_path, _Noop, port=0)
    try:
        assert scheme == "http"
        assert type(srv) is server._DualStackHTTPServer
        assert srv.socket.family == socket.AF_INET
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()


def test_build_server_with_a_cert_binds_the_env_host(tmp_path, monkeypatch):
    tls = tmp_path / "ops" / "tls"
    tls.mkdir(parents=True)
    (tls / "rc.pem").write_text("placeholder", encoding="ascii")
    (tls / "rc-key.pem").write_text("placeholder", encoding="ascii")
    seen = []

    def fake_ctx(cert, key):
        seen.append((cert.name, key.name))
        return ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

    monkeypatch.setattr(server, "_tls_context", fake_ctx)
    monkeypatch.setenv("RC_DASH_BIND", "127.0.0.1")
    srv, scheme = server._build_server(tmp_path, _Noop, port=0)
    try:
        assert seen == [("rc.pem", "rc-key.pem")]
        assert scheme == "https"
        assert type(srv) is server._DualProtocolHTTPServer
        assert srv.socket.family == socket.AF_INET
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()


def test_build_server_default_is_the_dual_stack_wildcard(tmp_path):
    srv, scheme = server._build_server(tmp_path, _Noop, port=0)
    try:
        assert scheme == "http"
        assert srv.socket.family == socket.AF_INET6
    finally:
        srv.server_close()


def test_build_server_returns_none_when_the_port_is_taken(tmp_path):
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    try:
        port = holder.getsockname()[1]
        srv, _scheme = server._build_server(tmp_path, _Noop, host="127.0.0.1",
                                            port=port)
        assert srv is None
    finally:
        holder.close()


# -- 2. the control-peer policy ------------------------------------------------

@pytest.mark.parametrize("peer", [
    "127.0.0.1", "127.8.9.10", "::1", "::ffff:127.0.0.1",
])
def test_loopback_peers_may_control(peer):
    assert server.control_peer_allowed(peer, None, {}) is True
    assert server.control_peer_allowed(peer, "127.0.0.1", {}) is True


@pytest.mark.parametrize("peer, local", [
    ("100.64.0.7", "100.64.0.5"),
    ("::ffff:100.64.0.7", "::ffff:100.64.0.5"),
    ("100.127.255.254", "100.64.0.5"),
    ("fd7a:115c:a1e0::7", "fd7a:115c:a1e0::5"),
])
def test_tailnet_peers_arriving_on_the_tailnet_may_control(peer, local):
    assert server.control_peer_allowed(peer, local, {}) is True


@pytest.mark.parametrize("peer, local", [
    ("100.64.0.7", "192.0.2.5"),        # tailnet-range peer, LAN arrival
    ("100.64.0.7", None),               # arrival address unknown
    ("fd7a:115c:a1e0::7", "2001:db8::5"),
])
def test_a_tailnet_range_peer_needs_a_tailnet_arrival_address(peer, local):
    assert server.control_peer_allowed(peer, local, {}) is False


@pytest.mark.parametrize("peer, local", [
    ("192.0.2.10", "192.0.2.5"),
    ("::ffff:192.0.2.10", "::ffff:192.0.2.5"),
    ("2001:db8::10", "2001:db8::5"),
    ("fe80::10%12", "fe80::5%12"),      # link-local = the LAN segment
    ("100.128.0.1", "100.64.0.5"),      # just past 100.64.0.0/10
    ("100.63.255.255", "100.64.0.5"),   # just before it
    ("10.0.0.10", "10.0.0.5"),
    ("192.0.2.10", None),
])
def test_lan_peers_may_not_control(peer, local):
    assert server.control_peer_allowed(peer, local, {}) is False


@pytest.mark.parametrize("peer, local", [
    ("192.0.2.5", "192.0.2.5"),
    ("::ffff:192.0.2.5", "192.0.2.5"),
    ("192.0.2.5", "::ffff:192.0.2.5"),
    ("fe80::5%12", "fe80::5%12"),
])
def test_this_machine_via_its_own_lan_address_may_control(peer, local):
    assert server.control_peer_allowed(peer, local, {}) is True


@pytest.mark.parametrize("peer", [
    None, "", "rc-host", "not-an-ip", "999.1.1.1", 7, b"127.0.0.1",
])
def test_an_unparseable_peer_is_refused(peer):
    assert server.control_peer_allowed(peer, "127.0.0.1", {}) is False


def test_extra_control_nets_admit_named_lan_ranges():
    env = {"RC_DASH_CONTROL_NETS": " bogus , 192.0.2.0/24 ,, 2001:db8::/32 "}
    assert server.control_peer_allowed("192.0.2.10", "192.0.2.5", env) is True
    assert server.control_peer_allowed("::ffff:192.0.2.10", None, env) is True
    assert server.control_peer_allowed("2001:db8::10", None, env) is True
    assert server.control_peer_allowed("198.51.100.10", None, env) is False


def test_extra_control_nets_read_the_process_environment(monkeypatch):
    monkeypatch.setenv("RC_DASH_CONTROL_NETS", "192.0.2.0/24")
    assert server.control_peer_allowed("192.0.2.10", "192.0.2.5") is True
    monkeypatch.delenv("RC_DASH_CONTROL_NETS")
    assert server.control_peer_allowed("192.0.2.10", "192.0.2.5") is False


# -- 3. the handler gate (no socket: fakes carry the addresses) ----------------

class _Conn:
    """Stands in for the accepted socket: only the arrival address."""

    def __init__(self, local):
        self._local = local

    def getsockname(self):
        return (self._local, 8888)


class _ConnNoName:
    """A connection object that cannot report its local address."""


def _headers(pairs):
    msg = http.client.HTTPMessage()
    for k, v in pairs.items():
        msg[k] = v
    return msg


def _post(path, *, peer="192.0.2.10", local="192.0.2.5", token=None,
          conn=None, body=b"{}"):
    h = Handler.__new__(Handler)
    hdrs = {"Content-Length": str(len(body))}
    if token is not None:
        hdrs["X-RC-Token"] = token
    h.headers = _headers(hdrs)
    h.path = path
    h.rfile = io.BytesIO(body)
    if peer is not None:
        h.client_address = (peer, 50000)
    h.connection = conn if conn is not None else _Conn(local)
    h._csrf_ok = lambda: True
    sent = []
    h._send = lambda code, payload, ctype=None: sent.append((code, payload))
    h.do_POST()
    return sent


@pytest.fixture
def dispatched(monkeypatch):
    calls = []

    def fake(handler, payload):
        calls.append(handler.path)
        handler._send(200, b'{"ok":1}', "application/json")
        return True

    monkeypatch.setattr(_dispatch, "dispatch_post", fake)
    return calls


_CONTROL_PATHS = sorted(_handler._CONTROL_ENDPOINTS) + [
    "/api/decisions/respond_active", "/api/decisions/abc123",
]


def test_the_gated_set_is_the_recorded_membership():
    # RM-296c + RM-240: the peer gate covers exactly the token gate's set.
    assert {"/api/lcu-cmd", "/api/loadout/apply", "/api/sr-draft/apply",
            "/api/command", "/api/input"} <= _handler._CONTROL_ENDPOINTS
    for path in _CONTROL_PATHS:
        assert _handler.is_control_endpoint(path)


@pytest.mark.parametrize("path", _CONTROL_PATHS)
def test_a_lan_peer_is_refused_every_control_endpoint(path, dispatched):
    sent = _post(path)
    assert sent == [(403, b'{"error":"control_peer_refused"}')]
    assert dispatched == []


def test_the_query_string_does_not_bypass_the_gate(dispatched):
    sent = _post("/api/lcu-cmd?x=1")
    assert sent[-1][0] == 403
    assert dispatched == []


@pytest.mark.parametrize("peer, local", [
    ("127.0.0.1", "127.0.0.1"),
    ("::1", "::1"),
    ("::ffff:127.0.0.1", "::ffff:127.0.0.1"),
    ("100.64.0.7", "100.64.0.5"),
    ("fd7a:115c:a1e0::7", "fd7a:115c:a1e0::5"),
    ("192.0.2.5", "192.0.2.5"),
])
def test_loopback_tailnet_and_this_machine_reach_control(peer, local,
                                                         dispatched):
    sent = _post("/api/lcu-cmd", peer=peer, local=local)
    assert sent[-1][0] == 200
    assert dispatched == ["/api/lcu-cmd"]


def test_a_non_control_post_from_the_lan_is_not_gated(dispatched):
    sent = _post("/api/ds-preview")
    assert sent[-1][0] == 200
    assert dispatched == ["/api/ds-preview"]


def test_the_control_nets_opt_in_readmits_a_lan_range(monkeypatch, dispatched):
    monkeypatch.setenv("RC_DASH_CONTROL_NETS", "192.0.2.0/24")
    sent = _post("/api/lcu-cmd")
    assert sent[-1][0] == 200


def test_a_connection_with_no_peer_address_is_refused(dispatched):
    sent = _post("/api/lcu-cmd", peer=None)
    assert sent[-1][0] == 403
    assert dispatched == []


def test_unknown_arrival_address_keeps_loopback_and_drops_tailnet(dispatched):
    assert _post("/api/lcu-cmd", peer="127.0.0.1",
                 conn=_ConnNoName())[-1][0] == 200
    assert _post("/api/lcu-cmd", peer="100.64.0.7",
                 conn=_ConnNoName())[-1][0] == 403


def test_no_socket_means_no_network_peer(dispatched):
    # The _read_body_deadlined convention (dashboard/_handler.py): a handler
    # with no connection is an in-process double, never a served request
    # (socketserver sets client_address and the socket before handle()).
    h = Handler.__new__(Handler)
    h.headers = _headers({"Content-Length": "2"})
    h.path = "/api/lcu-cmd"
    h.rfile = io.BytesIO(b"{}")
    h._csrf_ok = lambda: True
    sent = []
    h._send = lambda code, payload, ctype=None: sent.append((code, payload))
    h.do_POST()
    assert sent[-1][0] == 200


# -- 4. a configured token keeps its exact behaviour ---------------------------

def test_token_set_lan_peer_with_the_token_is_served(monkeypatch, dispatched):
    monkeypatch.setenv("RC_DASH_TOKEN", "s3cret")
    assert _post("/api/lcu-cmd", token="s3cret")[-1][0] == 200


def test_token_set_lan_peer_with_a_wrong_token_is_401(monkeypatch, dispatched):
    monkeypatch.setenv("RC_DASH_TOKEN", "s3cret")
    assert _post("/api/lcu-cmd", token="nope")[-1][0] == 401
    assert dispatched == []


def test_token_set_loopback_without_the_token_is_still_401(monkeypatch,
                                                           dispatched):
    monkeypatch.setenv("RC_DASH_TOKEN", "s3cret")
    assert _post("/api/lcu-cmd", peer="127.0.0.1",
                 local="127.0.0.1")[-1][0] == 401


# -- 5. end to end on a real loopback socket ------------------------------------

def _serve(srv):
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return t


def _raw_post(host, port, path):
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as s:
        s.settimeout(8.0)
        s.connect((host, port))
        hosthdr = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        s.sendall((f"POST {path} HTTP/1.1\r\nHost: {hosthdr}\r\n"
                   "Content-Type: application/json\r\nContent-Length: 2\r\n"
                   "Connection: close\r\n\r\n{}").encode("ascii"))
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    return int(buf.split(b" ", 2)[1])


@pytest.mark.parametrize("bind, connect", [
    ("127.0.0.1", "127.0.0.1"),
    ("::", "127.0.0.1"),       # v4 loopback through the dual-stack wildcard
    ("::", "::1"),
])
def test_a_loopback_client_reaches_control_over_a_real_socket(bind, connect,
                                                              dispatched):
    srv = server._DualStackHTTPServer((bind, 0), Handler)
    t = _serve(srv)
    try:
        status = _raw_post(connect, srv.server_address[1], "/api/lcu-cmd")
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(5)
    assert status == 200
    assert dispatched == ["/api/lcu-cmd"]


def test_a_real_socket_peer_outside_the_policy_is_refused(monkeypatch,
                                                          dispatched):
    # Only loopback can be bound in a test, so the classifier is told the
    # loopback peer is not allowed: proves the served path consults it with
    # the real socket's addresses and refuses before dispatch.
    seen = []

    def deny(peer, local, environ=None):
        seen.append((peer, local))
        return False

    monkeypatch.setattr(_handler, "control_peer_allowed", deny)
    srv = server._DualStackHTTPServer(("127.0.0.1", 0), Handler)
    t = _serve(srv)
    try:
        status = _raw_post("127.0.0.1", srv.server_address[1], "/api/lcu-cmd")
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(5)
    assert status == 403
    assert dispatched == []
    assert seen == [("127.0.0.1", "127.0.0.1")]

"""RM-774: absolute-form request lines (``GET http://<name>/<path>``) passed
the RM-759 Host gate on :8888 and :8890.

THE DEFECT. RFC 9112 section 3.2.2: for an absolute-form target the
target's authority REPLACES Host. ``HostAllowlistMixin`` read only the Host
header, so ``GET http://rebind.example/... HTTP/1.1`` with a loopback Host
(or none, on HTTP/1.0) went past the gate with a foreign authority. Measured
live 2026-10-23 before the fix (raw socket, harmless GETs): the same foreign
name in Host -> 421, as the target's authority -> 404 on both ports (gate
passed; today's route matchers are anchored to ``/``, so nothing matched),
and on :8890 the rootless target ``index.html`` -> 200: the static-file
handler served a target that is not origin-form at all.

THE FIX (decision: refuse, not re-route). Both servers are origin servers
that no in-tree client and no browser addresses in absolute-form, so
``HostAllowlistMixin`` answers 400 to any request target that is not
origin-form (``/...``), keeping asterisk-form for ``OPTIONS *`` only. The
alternative - check the authority against the allowlist and rewrite the
target to origin-form - is RFC's "MUST accept" path but adds a URL parser in
front of every route for a form nothing sends. Reverses if: a real client
of these ports is measured sending absolute-form.

Every name is a placeholder; the allowlist is INJECTED.
"""
from __future__ import annotations

import socket
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from core import http_host_gate as _host_gate
from dashboard import _dispatch, _handler
from dashboard._handler import Handler

_HOST = "127.0.0.1"
_CLOSED = (ConnectionResetError, ConnectionAbortedError)


@pytest.fixture(autouse=True)
def injected_allowlist(monkeypatch):
    names = _handler.build_allowed_host_names(
        cfg={"tailnet_name": "rc-host"}, env="")
    # RM-819: the cache lives in core.http_host_gate (the shared gate).
    monkeypatch.setattr(_host_gate, "_allowed_names_cache", names)


# (request line target, Host header or None). Each is refused.
_NOT_ORIGIN_FORM = {
    "absolute-foreign-loopback-host": ("http://rebind.example:{p}{path}",
                                       "127.0.0.1:{p}"),
    "absolute-foreign-no-host": ("http://rebind.example:{p}{path}", None),
    "absolute-https-foreign": ("https://rebind.example{path}", "127.0.0.1:{p}"),
    "absolute-upper-scheme": ("HTTP://rebind.example{path}", "127.0.0.1:{p}"),
    "absolute-allowed-authority": ("http://127.0.0.1:{p}{path}",
                                   "127.0.0.1:{p}"),
    "absolute-userinfo": ("http://127.0.0.1@rebind.example{path}",
                          "127.0.0.1:{p}"),
    "authority-form": ("rebind.example:443", "127.0.0.1:{p}"),
    "rootless": ("{bare}", "127.0.0.1:{p}"),
    "asterisk-on-get": ("*", "127.0.0.1:{p}"),
}


def _raw(port: int, payload: bytes) -> bytes:
    buf = b""
    with socket.create_connection((_HOST, port), timeout=8) as s:
        s.sendall(payload)
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


def _req(method: str, target: str, host: str | None, port: int,
         path: str) -> bytes:
    target = target.format(p=port, path=path, bare=path.lstrip("/"))
    head = f"{method} {target} HTTP/1.0\r\n"
    if host is not None:
        head += f"Host: {host.format(p=port)}\r\n"
    return (head + "\r\n").encode("ascii")


# -- the predicate ------------------------------------------------------------

@pytest.mark.parametrize("command, target", [
    ("GET", "/"), ("GET", "/api/state?x=1"), ("POST", "/api/command"),
    ("HEAD", "/ok.txt"), ("OPTIONS", "*"), ("OPTIONS", "/api/state"),
])
def test_origin_form_and_options_asterisk_are_accepted(command, target):
    assert _handler.request_target_ok(command, target)


@pytest.mark.parametrize("command, target", [
    ("GET", "http://rebind.example/"), ("GET", "https://127.0.0.1/"),
    ("GET", "rebind.example:443"), ("CONNECT", "rebind.example:443"),
    ("GET", "index.html"), ("GET", "*"), ("GET", ""), ("GET", None),
])
def test_any_other_target_is_refused(command, target):
    assert not _handler.request_target_ok(command, target)


# -- :8888, the real Handler ---------------------------------------------------

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


@pytest.mark.parametrize("name", sorted(_NOT_ORIGIN_FORM))
def test_dashboard_refuses_a_non_origin_form_target(dashboard, name):
    port, calls = dashboard
    target, host = _NOT_ORIGIN_FORM[name]
    reply = _raw(port, _req("GET", target, host, port, "/api/state"))
    assert _status(reply) == 400, (name, reply[:200])
    assert b"bad_request_target" in reply, reply[:300]
    assert calls == [], f"a route ran for target form {name}"


def test_dashboard_refuses_an_absolute_form_post_before_dispatch(dashboard):
    port, calls = dashboard
    body = b'{"command":"noop"}'
    head = (f"POST http://rebind.example:{port}/api/command HTTP/1.0\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            f"Content-Length: {len(body)}\r\n\r\n").encode("ascii")
    assert _status(_raw(port, head + body)) == 400
    assert calls == []


@pytest.mark.parametrize("target, routed", [
    ("/api/state", "/api/state"),
    ("/api/state?x=1", "/api/state?x=1"),
    ("//api/state", "/api/state"),      # the stdlib's own '//' collapse
])
def test_dashboard_still_serves_origin_form(dashboard, target, routed):
    port, calls = dashboard
    reply = _raw(port, _req("GET", target, "127.0.0.1:{p}", port, ""))
    assert _status(reply) == 200, reply[:200]
    assert calls == [("GET", routed)]


def test_options_asterisk_is_not_a_target_refusal(dashboard):
    """``OPTIONS *`` keeps the stdlib's own answer (no do_OPTIONS: 501)."""
    port, _calls = dashboard
    reply = _raw(port, _req("OPTIONS", "*", "127.0.0.1:{p}", port, ""))
    assert _status(reply) == 501, reply[:200]


# -- :8890, the real _WebServer + _QuietHandler -------------------------------

class _Scheduler:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def snapshot(self):
        self.calls.append(("snapshot",))
        return {"ready": 0}


class _Supervisor:
    def __init__(self) -> None:
        self.scheduler = _Scheduler()
        self.warm_agent7 = None


@pytest.fixture
def supervisor(tmp_path: Path):
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


@pytest.mark.parametrize("name", sorted(_NOT_ORIGIN_FORM))
@pytest.mark.parametrize("path", ["/api/queue", "/ok.txt"])
def test_supervisor_refuses_a_non_origin_form_target(supervisor, path, name):
    """Before the fix the rootless ``ok.txt`` was SERVED (200, the file)."""
    port = supervisor.server_address[1]
    target, host = _NOT_ORIGIN_FORM[name]
    reply = _raw(port, _req("GET", target, host, port, path))
    assert _status(reply) == 400, (name, path, reply[:200])
    assert b"public" not in reply
    assert supervisor.supervisor.scheduler.calls == []


def test_supervisor_head_absolute_form_is_refused_without_a_body(supervisor):
    port = supervisor.server_address[1]
    reply = _raw(port, _req("HEAD", "http://rebind.example{path}",
                            "127.0.0.1:{p}", port, "/ok.txt"))
    assert _status(reply) == 400, reply[:200]
    assert b"bad_request_target" not in reply


@pytest.mark.parametrize("path, body", [("/api/queue", b'"ready"'),
                                        ("/ok.txt", b"public")])
def test_supervisor_still_serves_origin_form(supervisor, path, body):
    port = supervisor.server_address[1]
    reply = _raw(port, _req("GET", path, "127.0.0.1:{p}", port, path))
    assert _status(reply) == 200, reply[:200]
    assert body in reply

"""RM-773: a malformed header line before Host made Python drop the Host,
and the RM-759 gate passes a missing Host by design.

THE DEFECT. ``http.client.parse_headers`` hands the header block to the
email feed parser, which stops reading headers at the first line that is not
one (``X-Junk``, ``Host : x``, a NUL or non-ASCII byte in a name) and files it
and EVERY later line as a message body; a bare CR line is read as the
header/body separator with no defect at all; a first header line that starts
with whitespace is dropped. A Host on any such line never reaches
``HostAllowlistMixin``, which then sees no Host and lets the request through.
Measured live 2026-10-23 before the fix, on :8888 (TLS) and :8890 alike:
``GET /`` with ``X-Junk`` then ``Host: rebind.example`` -> 200, while the same
Host on a clean head -> 421; the same for ``Host :``, a leading-space first
line and a bare-CR blank line.

THE FIX. ``HostAllowlistMixin.parse_request`` refuses, with 400 and before the
Host gate, any head whose parse lost or misread part of its header block
(``head_parse_defect``): a header-structure defect on the parsed message, an
envelope (``From ``) line, or any text the parser read as a body. A clean
head is unchanged, including LF-only line ends and the multipart / message
Content-Types whose empty body the parser itself flags.

THE FOLLOW-UP (verifier bypass, 2026-10-23). The block's own Content-Type
steered the parser into a multipart / message parse of the swallowed tail,
which filed a Host as the root's preamble or epilogue (``multipart/mixed;
boundary=x``, a bare CR, then ``Host: rebind.example`` before or after the
``--x`` lines): no defect, no payload, so 200 on both servers. The handlers
now parse heads with ``HeadOnlyMessage`` (no Content-Type while the parse
runs: the block always parses flat) and ``head_parse_defect`` refuses any
structured body, preamble or epilogue, under either message class. Controls:
an empty-bodied multipart / message head is still served, a real multipart
form POST still reaches the POST path and gets that path's own 400, and the
route still sees the real Content-Type.

Every name is a placeholder; the allowlist is INJECTED.
"""
from __future__ import annotations

import http.client
import io
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
_FOREIGN = "rebind.example"


@pytest.fixture(autouse=True)
def injected_allowlist(monkeypatch):
    names = _handler.build_allowed_host_names(
        cfg={"tailnet_name": "rc-host"}, env="")
    monkeypatch.setattr(_handler, "_allowed_names_cache", names)


# Header blocks (after the request line) that lose or misread a line. Each
# carries a foreign Host that a clean head would have 421'd.
_DEFECTIVE = {
    "junk-line": b"X-Junk\r\nHost: {h}\r\n",
    "space-before-colon": b"Host : {h}\r\n",
    "nul-in-name": b"X\x00A: 1\r\nHost: {h}\r\n",
    "latin1-name": b"X\xe9: 1\r\nHost: {h}\r\n",
    "first-line-continuation": b" Host: {h}\r\n",
    "bare-cr-blank-line": b"X-A: 1\r\rHost: {h}\r\n",
    "bare-cr-then-crlf": b"X-A: 1\r\r\nHost: {h}\r\n",
    "empty-name": b": v\r\nHost: {h}\r\n",
    "envelope-first": b"From x\r\nHost: {h}\r\n",
    "envelope-mid": b"X-A: 1\r\nFrom x\r\nHost: {h}\r\n",
    "envelope-last": b"Host: {h}\r\nFrom x\r\n",
    "multipart-bare-cr": (b"Content-Type: multipart/form-data; boundary=zz\r\n"
                          b"X-A: 1\r\rHost: {h}\r\n"),
    "message-bare-cr": (b"Content-Type: message/rfc822\r\n"
                        b"X-A: 1\r\rHost: {h}\r\n"),
    # RM-773 follow-up (verifier bypass, 2026-10-23): a bare CR ends the
    # headers and the Content-Type steers the rest into a multipart parse,
    # which files the Host as the root's PREAMBLE or EPILOGUE - neither a
    # defect nor a payload the first fix looked at (200 instead of 400).
    "multipart-preamble-host": (b"Content-Type: multipart/mixed; boundary=x\r\n"
                                b"\rHost: {h}\r\n--x\r\n--x--\r\n"),
    "multipart-epilogue-host": (b"Content-Type: multipart/mixed; boundary=x\r\n"
                                b"\r--x\r\n--x--\r\nHost: {h}\r\n"),
    "multipart-epilogue-cr-lines": (b"Content-Type: multipart/mixed; boundary=x\r\n"
                                    b"\r\r--x\r\n\r--x--\r\nHost: {h}\r\n"),
    "multipart-nested-preamble": (b"Content-Type: multipart/mixed; boundary=x\r\n"
                                  b"\r--x\r\n"
                                  b"Content-Type: multipart/mixed; boundary=y\r\n"
                                  b"\rHost: {h}\r\n--y\r\n--y--\r\n--x--\r\n"),
    "multipart-nested-epilogue": (b"Content-Type: multipart/mixed; boundary=x\r\n"
                                  b"\r--x\r\n"
                                  b"Content-Type: multipart/mixed; boundary=y\r\n"
                                  b"\r--y\r\n--y--\r\nHost: {h}\r\n--x--\r\n"),
    "multipart-part-continuation": (b"Content-Type: multipart/mixed; boundary=x\r\n"
                                    b"\r--x\r\n Host: {h}\r\n--x--\r\n"),
    "multipart-boundaries-only": (b"Host: {h}\r\n"
                                  b"Content-Type: multipart/mixed; boundary=x\r\n"
                                  b"\r--x\r\n--x--\r\n"),
    "message-nested-multipart-preamble": (
        b"Content-Type: message/rfc822\r\n"
        b"\rContent-Type: multipart/mixed; boundary=y\r\n"
        b"\rHost: {h}\r\n--y\r\n--y--\r\n"),
    "delivery-status-host": (b"Content-Type: message/delivery-status\r\n"
                             b"\rHost: {h}\r\n"),
}

# Clean header blocks that must still parse as clean.
_CLEAN = {
    "plain": b"Host: {h}\r\nUser-Agent: rm773\r\n",
    "lf-only": b"Host: {h}\nUser-Agent: rm773\n",
    "no-headers": b"",
    "obs-fold-in-other-header": b"Host: {h}\r\nX-A: 1\r\n 2\r\n",
    "multipart-content-type": (b"Host: {h}\r\n"
                               b"Content-Type: multipart/form-data; boundary=zz\r\n"),
    "multipart-no-boundary": b"Host: {h}\r\nContent-Type: multipart/mixed\r\n",
    "message-content-type": b"Host: {h}\r\nContent-Type: message/rfc822\r\n",
    "delivery-status-content-type": (b"Host: {h}\r\n"
                                     b"Content-Type: message/delivery-status\r\n"),
    "nested-looking-content-type": (b"Host: {h}\r\n"
                                    b"Content-Type: multipart/mixed; boundary=x\r\n"
                                    b"X-Note: --x\r\n"),
}


def _block(template: bytes, host: str) -> bytes:
    return template.replace(b"{h}", host.encode("ascii"))


def _terminator(template: bytes) -> bytes:
    return b"\n" if template.endswith(b"\n") and not template.endswith(b"\r\n") \
        else b"\r\n"


# -- the classifier ----------------------------------------------------------

def _parse(block: bytes, terminator: bytes, message_class) -> object:
    """The stdlib head parse the handlers run (parse_request's own call)."""
    return http.client.parse_headers(
        io.BytesIO(block + terminator + b"BODY"), _class=message_class)


# The class the handlers parse request heads with, and the stdlib default
# (Content-Type-steered) one: the classifier must hold on both.
_PARSE_CLASSES = {"handler": Handler.MessageClass,
                  "stdlib": http.client.HTTPMessage}


@pytest.mark.parametrize("cls", sorted(_PARSE_CLASSES))
@pytest.mark.parametrize("name", sorted(_DEFECTIVE))
def test_a_defective_block_is_named(name, cls):
    msg = _parse(_block(_DEFECTIVE[name], _FOREIGN), b"\r\n",
                 _PARSE_CLASSES[cls])
    assert _handler.head_parse_defect(msg), (name, cls, msg.defects,
                                             msg.get_payload(), msg.preamble,
                                             msg.epilogue)


@pytest.mark.parametrize("name", sorted(_CLEAN))
def test_a_clean_block_is_clean(name):
    msg = _parse(_block(_CLEAN[name], "127.0.0.1"), _terminator(_CLEAN[name]),
                 Handler.MessageClass)
    assert _handler.head_parse_defect(msg) is None, (name, msg.defects)


def test_both_handlers_parse_heads_with_the_same_class():
    from agents._supervisor_http import _QuietHandler
    assert _QuietHandler.MessageClass is Handler.MessageClass
    assert issubclass(Handler.MessageClass, http.client.HTTPMessage)


@pytest.mark.parametrize("name", ["multipart-preamble-host",
                                  "multipart-nested-preamble",
                                  "message-nested-multipart-preamble"])
def test_the_head_parse_is_never_steered_by_content_type(name):
    """The whole class closed at the root: a header-only block never parses
    into multipart parts or sub-messages, so nothing can hide in a preamble,
    an epilogue or a part - swallowed text is the root's plain payload."""
    msg = _parse(_block(_DEFECTIVE[name], _FOREIGN), b"\r\n",
                 Handler.MessageClass)
    assert isinstance(msg.get_payload(), str), msg.get_payload()
    assert _FOREIGN in msg.get_payload()
    assert msg.preamble is None and msg.epilogue is None


def test_something_that_is_not_a_message_is_left_to_the_host_gate():
    assert _handler.head_parse_defect({}) is None
    assert _handler.head_parse_defect(None) is None


# -- over a real socket: :8888 Handler and :8890 _QuietHandler ---------------

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


@pytest.fixture
def dashboard(monkeypatch):
    calls: list[str] = []

    def _get(h):
        calls.append(h.path)
        h._send(200, b"ok", "text/plain")
        return True

    monkeypatch.setattr(_dispatch, "dispatch_get", _get)
    srv = ThreadingHTTPServer((_HOST, 0), Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_address[1], calls
    finally:
        srv.shutdown()
        srv.server_close()


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


def _request(path: str, block: bytes) -> bytes:
    return b"GET " + path.encode("ascii") + b" HTTP/1.0\r\n" + block + b"\r\n"


def test_the_clean_control_is_421(dashboard):
    """The Host the defective heads carry is one the gate refuses."""
    port, calls = dashboard
    reply = _raw(port, _request("/api/state", _block(b"Host: {h}\r\n",
                                                     _FOREIGN)))
    assert _status(reply) == 421, reply[:200]
    assert calls == []


@pytest.mark.parametrize("name", sorted(_DEFECTIVE))
def test_dashboard_refuses_a_defective_head(dashboard, name):
    """Before the fix: 200 wherever the parse lost the foreign Host (the gate
    saw none), 421 where the Host survived the defect; now 400 for all."""
    port, calls = dashboard
    reply = _raw(port, _request("/api/state", _block(_DEFECTIVE[name], _FOREIGN)))
    assert _status(reply) == 400, (name, reply[:200])
    assert b"bad_header_block" in reply, reply[:300]
    assert calls == [], f"the route ran for a defective head ({name})"


def test_dashboard_refuses_a_defective_head_even_with_an_allowed_host(
        dashboard):
    port, calls = dashboard
    block = b"X-Junk\r\nHost: 127.0.0.1\r\n"
    assert _status(_raw(port, _request("/api/state", block))) == 400
    assert calls == []


@pytest.mark.parametrize("name", sorted(_CLEAN))
def test_dashboard_still_serves_a_clean_head(dashboard, name):
    port, calls = dashboard
    block = _block(_CLEAN[name], f"127.0.0.1:{port}")
    reply = _raw(port, b"GET /api/state HTTP/1.0" + _terminator(_CLEAN[name])
                 + block + _terminator(_CLEAN[name]))
    assert _status(reply) == 200, (name, reply[:200])
    assert calls == ["/api/state"]


@pytest.mark.parametrize("name", sorted(_DEFECTIVE))
@pytest.mark.parametrize("path", ["/api/queue", "/ok.txt"])
def test_supervisor_refuses_a_defective_head(supervisor, path, name):
    port = supervisor.server_address[1]
    reply = _raw(port, _request(path, _block(_DEFECTIVE[name], _FOREIGN)))
    assert _status(reply) == 400, (name, path, reply[:200])
    assert b"public" not in reply
    assert supervisor.supervisor.scheduler.calls == []


@pytest.mark.parametrize("path, body", [("/api/queue", b'"ready"'),
                                        ("/ok.txt", b"public")])
def test_supervisor_still_serves_a_clean_head(supervisor, path, body):
    port = supervisor.server_address[1]
    reply = _raw(port, _request(path, f"Host: 127.0.0.1:{port}\r\n".encode()))
    assert _status(reply) == 200, reply[:200]
    assert body in reply


def test_a_defective_head_post_is_refused_before_dispatch(dashboard,
                                                          monkeypatch):
    port, calls = dashboard
    posted: list = []
    monkeypatch.setattr(_dispatch, "dispatch_post",
                        lambda h, p: posted.append(p) or True)
    body = b'{"command":"noop"}'
    head = (b"POST /api/command HTTP/1.0\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"X-Junk\r\nHost: " + _FOREIGN.encode() + b"\r\n\r\n")
    reply = _raw(port, head + body)
    assert _status(reply) == 400, reply[:200]
    assert posted == [] and calls == []


_BOUND = b"----WebKitFormBoundaryRm773"
_FORM_BODY = (b"--" + _BOUND + b"\r\n"
              b"Content-Disposition: form-data; name=\"a\"\r\n\r\n1\r\n"
              b"--" + _BOUND + b"--\r\n")


def _form_post(port: int, path: str) -> bytes:
    """A real browser-shaped multipart form POST (head + body)."""
    head = (b"POST " + path.encode("ascii") + b" HTTP/1.1\r\n"
            b"Host: 127.0.0.1:" + str(port).encode() + b"\r\n"
            b"Content-Type: multipart/form-data; boundary=" + _BOUND + b"\r\n"
            b"Content-Length: " + str(len(_FORM_BODY)).encode() + b"\r\n"
            b"Connection: close\r\n\r\n")
    return _raw(port, head + _FORM_BODY)


def test_a_real_multipart_form_post_still_reaches_the_post_path(dashboard,
                                                                monkeypatch):
    """Control: the head is clean, so do_POST runs and answers with its OWN
    400 (the body is not JSON) - never the head refusal."""
    port, _calls = dashboard
    posted: list = []
    monkeypatch.setattr(_dispatch, "dispatch_post",
                        lambda h, p: posted.append(p) or True)
    reply = _form_post(port, "/api/command")
    assert _status(reply) == 400, reply[:200]
    assert b"bad_body" in reply, reply[:300]
    assert b"bad_header_block" not in reply
    assert posted == []


def test_a_real_multipart_form_post_still_reaches_the_supervisor_route(
        supervisor):
    port = supervisor.server_address[1]
    reply = _form_post(port, "/api/file-task")
    assert _status(reply) == 400, reply[:200]
    assert b"bad_header_block" not in reply, reply[:300]
    assert b"JSON" in reply, reply[:300]


def test_the_route_sees_the_real_content_type(dashboard, monkeypatch):
    """The head parse ignores Content-Type; the route, after it, does not."""
    port, _calls = dashboard
    seen: list = []

    def _get(h):
        seen.append((h.headers.get_content_type(), h.headers.get_boundary()))
        h._send(200, b"ok", "text/plain")
        return True

    monkeypatch.setattr(_dispatch, "dispatch_get", _get)
    reply = _raw(port, _request(
        "/api/state", f"Host: 127.0.0.1:{port}\r\n"
        "Content-Type: multipart/form-data; boundary=zz\r\n".encode()))
    assert _status(reply) == 200, reply[:200]
    assert seen == [("multipart/form-data", "zz")]


def test_the_refusal_is_logged_scrubbed(dashboard):
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
        reply = _raw(port, _request("/api/\x1b[31mstate",
                                    b"X-Junk\r\nHost: " + _FOREIGN.encode()
                                    + b"\r\n"))
    finally:
        lg.removeHandler(cap)
        lg.setLevel(prior)
    assert _status(reply) == 400
    warnings = [r.getMessage() for r in records if r.levelno >= logging.WARNING]
    assert any("RM-773" in m and _HOST in m for m in warnings), warnings
    for m in warnings:
        assert "\x1b" not in m, m

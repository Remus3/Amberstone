# arch: s144 true-audit S144-T-689 - the :8895 Mission Control handler frames every POST body it acts on | section=tests | frozen=no
"""s144 true-audit (S144-T-689): `mc/handler.py` request framing and reply guard.

Measured on the real `mc.handler.Handler` on an ephemeral loopback port before
the fix (cycle s144t259):

  F1  a chunked POST was dispatched with `{}`: the declared body was never read
      (no Content-Length) and the route ran as though the client had sent an
      empty object - the defect the :8888 dashboard closed in LEDGER 1279, never
      carried to this sibling. Any Transfer-Encoding is now 411: RFC 9112 6.3
      says it overrides Content-Length, so the body cannot be framed here.
  F2  `int()` framed the body, so `Content-Length: 1_0` read 10 bytes (PEP 515
      underscores), and `+5` / ` 5` were accepted too. RFC 9110 8.6 is
      1*DIGIT; anything else is 400.
  F3  two Content-Length lines that disagree (2 and 9) were framed by the
      FIRST; RFC 9112 6.3 makes that unrecoverable, so 400.
  F4  a body shorter than its Content-Length pinned the handler thread with
      no reply for as long as the client held the socket (measured 4.0 s, the
      probe's own limit) - RM-152's dashboard fix, never carried here. Now one
      absolute deadline, 408.
  F5  a body that ENDED short (client closed early) was parsed as whatever
      arrived, so a truncated body that happened to be valid JSON ran a route.
  F6  invalid UTF-8 was silently replaced with U+FFFD and dispatched; JSON is
      UTF-8 (RFC 8259 8.1), so it is 400.
  F7  a route that raised AFTER its reply began got a SECOND status line on
      the same connection (`200 ...{"ok": true}HTTP/1.0 500 ...`).
  F8  a client hang-up on Windows raises ConnectionAbortedError (WinError
      10053), which `_send` did not treat as a hang-up: it was logged as a
      server fault, a 500 was written to the dead socket, and that second
      write escaped `do_POST` into socketserver's stderr traceback.
"""
from __future__ import annotations

import io
import json
import logging
import socket
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TOKEN = "s144t259-test-token"
_AUTH = b"Host: 127.0.0.1\r\nAuthorization: Bearer " + _TOKEN.encode() + b"\r\n"


@pytest.fixture
def served(monkeypatch):
    """A real Handler on 127.0.0.1:0 with stub routes; yields (port, reached)."""
    from mc import handler, routes

    monkeypatch.setenv("RC_MC_TOKEN", _TOKEN)
    reached: list = []

    def _ok(h, payload=None):
        reached.append(payload)
        h._send_json(200, {"ok": True})

    def _late_raise(h, payload=None):
        h._send_json(200, {"ok": True})
        raise RuntimeError("route failed after its reply began")

    monkeypatch.setattr(routes, "POST_ROUTES", [
        (lambda p: p == "/late", _late_raise), (lambda p: True, _ok)])
    monkeypatch.setattr(routes, "GET_ROUTES", [
        (lambda p: p == "/late", _late_raise), (lambda p: True, _ok)])
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler.Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, name="mc-test-srv",
                         daemon=True)
    t.start()
    try:
        yield srv.server_address[1], reached
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(5)


def _raw(port: int, req: bytes, wait: float = 5.0) -> bytes:
    """Send ``req``; return every byte until the server closes (or ``wait``)."""
    s = socket.create_connection(("127.0.0.1", port), timeout=wait)
    try:
        s.sendall(req)
        out = b""
        while True:
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                return out + b"<<TIMEOUT>>"
            if not chunk:
                return out
            out += chunk
    finally:
        s.close()


def _status(resp: bytes) -> int:
    return int(resp.split(b" ", 2)[1])


def _body(resp: bytes) -> dict:
    return json.loads(resp.split(b"\r\n\r\n", 1)[1].decode("utf-8"))


# -- control: a well-framed POST still reaches its route --------------------

def test_control_well_framed_post_reaches_route(served):
    port, reached = served
    resp = _raw(port, b"POST /x HTTP/1.1\r\n" + _AUTH
                + b'Content-Length: 8\r\n\r\n{"a": 1}')
    assert _status(resp) == 200
    assert reached == [{"a": 1}]


def test_control_identical_duplicate_content_length_is_accepted(served):
    port, reached = served
    resp = _raw(port, b"POST /x HTTP/1.1\r\n" + _AUTH
                + b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}")
    assert _status(resp) == 200
    assert reached == [{}]


def test_control_unauthenticated_chunked_post_is_still_401(served):
    """The bearer gate stays FIRST: framing errors are not an oracle."""
    port, reached = served
    resp = _raw(port, b"POST /x HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n")
    assert _status(resp) == 401
    assert reached == []


# -- F1 chunked / any Transfer-Encoding ---------------------------------------

@pytest.mark.parametrize("te_lines", [
    pytest.param(b"Transfer-Encoding: chunked\r\n", id="chunked"),
    pytest.param(b"Transfer-Encoding: identity\r\nTransfer-Encoding: chunked\r\n",
                 id="identity-then-chunked"),
    pytest.param(b"Transfer-Encoding: gzip, chunked\r\n", id="gzip-chunked"),
    pytest.param(b"Content-Length: 7\r\nTransfer-Encoding: chunked\r\n",
                 id="te-overrides-cl"),
    pytest.param(b"Content-Length: 7\r\nTransfer-Encoding: \r\n",
                 id="te-empty-value"),
    pytest.param(b"transfer-encoding: chunked\r\n", id="te-lower-case-name"),
])
def test_f1_transfer_encoding_is_411_and_no_route_runs(served, te_lines):
    port, reached = served
    resp = _raw(port, b"POST /x HTTP/1.1\r\n" + _AUTH + te_lines
                + b'\r\n7\r\n{"a":1}\r\n0\r\n\r\n')
    assert _status(resp) == 411
    assert _body(resp) == {"ok": False, "error": "length required"}
    assert reached == []


# -- F2 / F3 Content-Length grammar ------------------------------------------

@pytest.mark.parametrize("value", [
    pytest.param(b"1_0", id="pep515-underscore"),
    pytest.param(b"+2", id="plus-sign"),
    pytest.param(b"-1", id="negative"),
    pytest.param(b"0x2", id="hex"),
    pytest.param(b"2.0", id="decimal"),
    pytest.param(b"two", id="word"),
    pytest.param(b"", id="empty"),
])
def test_f2_non_digit_content_length_is_400(served, value):
    port, reached = served
    resp = _raw(port, b"POST /x HTTP/1.1\r\n" + _AUTH
                + b"Content-Length: " + value + b"\r\n\r\n{}")
    assert _status(resp) == 400
    assert _body(resp) == {"ok": False, "error": "invalid content-length"}
    assert reached == []


def test_f3_conflicting_duplicate_content_length_is_400(served):
    port, reached = served
    resp = _raw(port, b"POST /x HTTP/1.1\r\n" + _AUTH
                + b"Content-Length: 2\r\nContent-Length: 9\r\n\r\n{}")
    assert _status(resp) == 400
    assert _body(resp) == {"ok": False, "error": "invalid content-length"}
    assert reached == []


# -- F4 body read deadline ------------------------------------------------------

def test_f4_stalled_body_is_408_within_the_deadline(served, monkeypatch):
    from mc import handler

    monkeypatch.setattr(handler, "_BODY_READ_TIMEOUT_S", 0.5)
    port, reached = served
    t0 = time.monotonic()
    resp = _raw(port, b"POST /x HTTP/1.1\r\n" + _AUTH
                + b"Content-Length: 100\r\n\r\n{", wait=5.0)
    elapsed = time.monotonic() - t0
    assert b"<<TIMEOUT>>" not in resp
    assert _status(resp) == 408
    assert _body(resp) == {"ok": False, "error": "body read timeout"}
    assert elapsed < 3.0
    assert reached == []


def test_f4_deadline_is_absolute_not_per_chunk(served, monkeypatch):
    """A trickle client cannot re-arm the budget one byte at a time."""
    from mc import handler

    monkeypatch.setattr(handler, "_BODY_READ_TIMEOUT_S", 0.6)
    port, reached = served
    s = socket.create_connection(("127.0.0.1", port), timeout=5.0)
    resp = b""
    try:
        s.sendall(b"POST /x HTTP/1.1\r\n" + _AUTH
                  + b"Content-Length: 50\r\n\r\n")
        t0 = time.monotonic()
        # One byte every 0.1 s: 49 of the 50 declared bytes would take 4.9 s,
        # far past the 0.6 s budget. Read between sends, because once the
        # server closes, a further send can draw a reset that discards the
        # reply still unread in this socket's buffer.
        s.settimeout(0.1)
        for _ in range(49):
            if time.monotonic() - t0 > 3.0:
                break
            try:
                s.sendall(b" ")
            except OSError:
                break
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            resp += chunk
            if b"\r\n\r\n" in resp:
                break
        elapsed = time.monotonic() - t0
    finally:
        s.close()
    assert elapsed < 3.0
    assert _status(resp) == 408
    assert reached == []


def test_f4_socket_timeout_is_restored_after_the_body(monkeypatch):
    from mc import handler

    class Sock:
        def __init__(self):
            self.t = None
            self.history = []

        def gettimeout(self):
            return self.t

        def settimeout(self, v):
            self.history.append(v)
            self.t = v

    h = handler.Handler.__new__(handler.Handler)
    h.connection = Sock()
    h.rfile = io.BytesIO(b"abcd")
    assert handler._read_body_deadlined(h, 4) == b"abcd"
    assert h.connection.t is None
    assert h.connection.history[-1] is None
    assert any(isinstance(v, float) and v > 0 for v in h.connection.history)


# -- F5 / F6 body content --------------------------------------------------------

def _fake_post(monkeypatch, body: bytes, declared=None, route=None):
    from mc import handler, routes

    monkeypatch.setenv("RC_MC_TOKEN", _TOKEN)
    reached: list = []

    def _default_route(h, payload):
        reached.append(payload)
        h._send_json(200, {"ok": True})

    monkeypatch.setattr(routes, "POST_ROUTES",
                        [(lambda p: True, route or _default_route)])

    class Fake:
        path = "/api/loop-control"

        def __init__(self):
            self.sent = []
            self.headers = {
                "Authorization": "Bearer " + _TOKEN,
                "Content-Length": str(len(body) if declared is None else declared),
            }
            self.rfile = io.BytesIO(body)

        def _send(self, code, raw, ctype, cache_control=None):
            self.sent.append((code, raw, ctype))

        _send_json = handler.Handler._send_json

    f = Fake()
    handler.Handler.do_POST(f)
    return f, reached


def test_f5_body_shorter_than_declared_is_400_even_if_valid_json(monkeypatch):
    f, reached = _fake_post(monkeypatch, b"{}", declared=10)
    assert reached == []
    assert len(f.sent) == 1
    code, raw, _ = f.sent[0]
    assert code == 400
    assert json.loads(raw) == {"ok": False, "error": "incomplete body"}


def test_f6_invalid_utf8_body_is_400_not_replaced(monkeypatch):
    f, reached = _fake_post(monkeypatch, b'{"key": "\xff\xfe"}')
    assert reached == []
    code, raw, _ = f.sent[0]
    assert code == 400
    assert json.loads(raw) == {"ok": False, "error": "invalid json"}


def test_control_utf8_body_round_trips(monkeypatch):
    f, reached = _fake_post(monkeypatch, '{"k": "caf\u00e9"}'.encode())
    assert reached == [{"k": "caf\u00e9"}]
    assert f.sent[0][0] == 200


# -- F7 one reply per request ---------------------------------------------------

@pytest.mark.parametrize("verb", ["GET", "POST"])
def test_f7_route_raising_after_its_reply_writes_no_second_status(served, verb):
    port, _reached = served
    req = (verb.encode() + b" /late HTTP/1.1\r\n" + _AUTH
           + (b"Content-Length: 2\r\n\r\n{}" if verb == "POST" else b"\r\n"))
    resp = _raw(port, req)
    assert resp.count(b"HTTP/1.") == 1
    assert _status(resp) == 200
    assert _body(resp) == {"ok": True}


@pytest.mark.parametrize("verb", ["GET", "POST"])
def test_control_route_raising_before_reply_is_still_500(served, monkeypatch,
                                                          verb):
    from mc import routes

    def _boom(h, payload=None):
        raise RuntimeError("before any reply")

    monkeypatch.setattr(routes, "POST_ROUTES", [(lambda p: True, _boom)])
    monkeypatch.setattr(routes, "GET_ROUTES", [(lambda p: True, _boom)])
    port, _reached = served
    req = (verb.encode() + b" /x HTTP/1.1\r\n" + _AUTH
           + (b"Content-Length: 2\r\n\r\n{}" if verb == "POST" else b"\r\n"))
    resp = _raw(port, req)
    assert resp.count(b"HTTP/1.") == 1
    assert _status(resp) == 500
    assert _body(resp) == {"ok": False, "error": "internal error"}


# -- F8 client hang-up ------------------------------------------------------------

@pytest.mark.parametrize("exc_type", [
    ConnectionAbortedError, ConnectionResetError, BrokenPipeError])
def test_f8_send_swallows_every_hangup_on_the_body_write(exc_type):
    from mc import handler

    class W:
        def write(self, b):
            raise exc_type("client went away")

    h = handler.Handler.__new__(handler.Handler)
    h.send_response = lambda *a, **k: None
    h.send_header = lambda *a, **k: None
    h.end_headers = lambda: None
    h.wfile = W()
    h._send(200, b"{}", "application/json")  # must not raise


@pytest.mark.parametrize("verb", ["GET", "POST"])
@pytest.mark.parametrize("exc_type", [
    ConnectionAbortedError, ConnectionResetError, BrokenPipeError])
def test_f8_hangup_is_not_a_server_fault(monkeypatch, caplog, verb, exc_type):
    """A hang-up is logged at DEBUG, no 500 is attempted, nothing escapes."""
    from mc import handler, routes

    monkeypatch.setenv("RC_MC_TOKEN", _TOKEN)

    def _gone(h, payload=None):
        raise exc_type("client went away")

    monkeypatch.setattr(routes, "POST_ROUTES", [(lambda p: True, _gone)])
    monkeypatch.setattr(routes, "GET_ROUTES", [(lambda p: True, _gone)])

    class Fake:
        path = "/x"

        def __init__(self):
            self.sent = []
            self.headers = {"Authorization": "Bearer " + _TOKEN,
                            "Content-Length": "2"}
            self.rfile = io.BytesIO(b"{}")

        def _send(self, code, raw, ctype, cache_control=None):
            self.sent.append(code)

        _send_json = handler.Handler._send_json

    f = Fake()
    with caplog.at_level(logging.DEBUG, logger="rc.mc.handler"):
        getattr(handler.Handler, "do_" + verb)(f)
    assert f.sent == []
    assert f.close_connection is True
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_f8_a_failing_500_write_does_not_escape(monkeypatch):
    """The fault reply itself hitting a dead socket stays inside do_GET."""
    from mc import handler, routes

    def _boom(h):
        raise RuntimeError("route bug")

    monkeypatch.setattr(routes, "GET_ROUTES", [(lambda p: True, _boom)])

    class Fake:
        path = "/x"

        def _send(self, code, raw, ctype, cache_control=None):
            raise ConnectionAbortedError("dead socket")

        _send_json = handler.Handler._send_json

    f = Fake()
    handler.Handler.do_GET(f)  # must not raise
    assert f.close_connection is True

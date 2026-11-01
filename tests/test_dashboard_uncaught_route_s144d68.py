# arch: RM-1288 guard - an exception no route catches answers 500 on :8888 | section=tests | frozen=no
"""RM-1288: a route exception that nothing catches must not close the socket.

Measured on the real Handler over a real socket before the fix:
`do_GET` and `do_POST` call `_dispatch.dispatch_get` / `dispatch_post` with no
try, so an exception raised by any route function unwound out of the handler.
`socketserver` then logs it to stderr (nothing under pythonw) and closes the
connection with no HTTP reply, which a browser reports as a network failure
and a script as an empty read.

The contract pinned here:
- an uncaught route failure on a GET or a POST is 500 JSON with the fixed
  `internal error - see logs` line, never the exception text;
- if the route had already begun its reply (a status line went out), nothing
  more is written - a second status line would corrupt the first reply - and
  the connection is closed;
- a client that went away mid-reply (a ConnectionError) is not answered and
  not logged as a failure;
- the server keeps serving the next request.
"""
from __future__ import annotations

import json
import socket
import threading
from http.server import ThreadingHTTPServer

import pytest

import core.http_host_gate as host_gate
import dashboard._handler as handler_mod
from dashboard._errors import GENERIC_ERROR
from dashboard._handler import Handler

_SECRET = "synthetic-secret-in-the-route-exception"
_HOST = b"Host: 127.0.0.1\r\n"
_GET = b"GET /api/anything HTTP/1.1\r\n" + _HOST + b"\r\n"
_POST = (b"POST /api/anything HTTP/1.1\r\n" + _HOST
         + b"Content-Length: 2\r\n\r\n{}")


@pytest.fixture
def served(monkeypatch):
    monkeypatch.setattr(host_gate, "_allowed_names_cache", host_gate._LOOPBACK_NAMES)
    monkeypatch.delenv("RC_DASH_TOKEN", raising=False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _reply(port: int, raw: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(raw)
        sock.settimeout(10)
        out = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                return out
            out += chunk


def _status_and_body(raw: bytes) -> tuple[int, bytes]:
    head, _, body = raw.partition(b"\r\n\r\n")
    return int(head.split(b"\r\n")[0].split()[1]), body


def _boom(*_a, **_k):
    raise RuntimeError(_SECRET)


@pytest.mark.parametrize(("name", "request_bytes"),
                         [("dispatch_get", _GET), ("dispatch_post", _POST)])
def test_an_uncaught_route_failure_answers_500_with_the_fixed_line(
        served, monkeypatch, name, request_bytes):
    monkeypatch.setattr(handler_mod._dispatch, name, _boom)
    raw = _reply(served, request_bytes)
    assert raw, "the connection closed with no reply"
    status, body = _status_and_body(raw)
    assert status == 500
    assert json.loads(body) == {"error": GENERIC_ERROR}
    assert _SECRET.encode() not in raw


@pytest.mark.parametrize(("name", "request_bytes"),
                         [("dispatch_get", _GET), ("dispatch_post", _POST)])
def test_a_failure_after_the_reply_began_writes_nothing_more(
        served, monkeypatch, name, request_bytes):
    def _half_done(handler, *_a):
        handler._send(200, b"first", "text/plain")
        raise RuntimeError(_SECRET)

    monkeypatch.setattr(handler_mod._dispatch, name, _half_done)
    raw = _reply(served, request_bytes)
    assert raw.count(b"HTTP/1.") == 1
    status, body = _status_and_body(raw)
    assert status == 200
    assert body == b"first"
    assert _SECRET.encode() not in raw


def test_a_failure_after_a_streamed_head_writes_nothing_more(served, monkeypatch):
    def _streaming(handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        raise RuntimeError(_SECRET)

    monkeypatch.setattr(handler_mod._dispatch, "dispatch_get", _streaming)
    raw = _reply(served, _GET)
    assert raw.count(b"HTTP/1.") == 1
    assert _status_and_body(raw)[0] == 200
    assert _SECRET.encode() not in raw


def test_a_client_that_went_away_is_not_answered_or_logged_as_a_failure(
        served, monkeypatch, caplog):
    def _gone(*_a, **_k):
        raise BrokenPipeError(_SECRET)

    monkeypatch.setattr(handler_mod._dispatch, "dispatch_get", _gone)
    with caplog.at_level("WARNING"):
        assert _reply(served, _GET) == b""
    assert not [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")
                and "route" in r.getMessage().lower()]


def test_the_server_serves_the_next_request_after_an_uncaught_failure(
        served, monkeypatch):
    calls = []

    def _once(handler):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError(_SECRET)
        handler._send(200, b"fine", "text/plain")
        return True

    monkeypatch.setattr(handler_mod._dispatch, "dispatch_get", _once)
    assert _status_and_body(_reply(served, _GET))[0] == 500
    assert _status_and_body(_reply(served, _GET)) == (200, b"fine")


def test_the_failure_is_logged_with_a_scrubbed_path(served, monkeypatch, caplog):
    monkeypatch.setattr(handler_mod._dispatch, "dispatch_get", _boom)
    with caplog.at_level("WARNING"):
        _reply(served, b"GET /api/x%1b[31m HTTP/1.1\r\n" + _HOST + b"\r\n")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "uncaught route failure" in text
    assert "\x1b" not in text

"""Lane 8 true-audit of ``core/http_host_gate.py`` (s144 cycle 69).

The gate every RC HTTP server runs (RM-759 / RM-773 / RM-774 / RM-819 /
RM-825) was audited for what happens AFTER it decides to refuse:

F1  The refusal log line was unbounded. ``_note_host_refusal`` logged
    ``repr()`` of EVERY Host line and of the whole request target, and the
    stdlib admits 100 header lines of 64 KiB each, so ONE refused request
    wrote a 5.4 MB log line (measured). The 1-in-100 sampling bounds the
    line COUNT, not its size: a rebinding page looping on the gate grew
    ``logs/`` by megabytes per hundred requests.
F2  ``_refuse_head`` guarded only the body write. A client that resets
    before the status line is written made ``end_headers`` raise
    ``ConnectionResetError`` out of ``parse_request``, i.e. an unsampled
    traceback through socketserver's ``handle_error`` per request.
F3  The per-server refusal counter was a bare read-modify-write from every
    handler thread of a ThreadingHTTPServer, so concurrent refusals lost
    counts (the logged ``count=`` understated and the 1 / every-100th
    sampling drifted).
F4  ``BaseHTTPRequestHandler.parse_request`` answers ``Expect:
    100-continue`` BEFORE it returns to the gate, so an HTTP/1.1 handler
    invited the body upload of a request the gate then refused (421 / 400).
    No in-tree server speaks HTTP/1.1 today, so this was latent; the mixin
    is the shared gate and must not depend on that.

Every name is a placeholder; the allowlist is injected and the live
per-host config is never read.
"""
from __future__ import annotations

import http.client
import io
import logging
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core import http_host_gate as gate

_HOST = "127.0.0.1"


@pytest.fixture(autouse=True)
def injected_allowlist(monkeypatch):
    names = gate.build_allowed_host_names(cfg={}, env="rc-host")
    monkeypatch.setattr(gate, "_allowed_names_cache", names)
    return names


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@pytest.fixture
def capture():
    lg = logging.getLogger("test.http_host_gate.s144")
    cap = _Capture()
    prior = (lg.propagate, lg.level)
    lg.addHandler(cap)
    lg.propagate = False
    lg.setLevel(logging.DEBUG)
    try:
        yield lg, cap
    finally:
        lg.removeHandler(cap)
        lg.propagate = prior[0]
        lg.setLevel(prior[1])


def _handler_class(logger, protocol="HTTP/1.0"):
    class _H(gate.HostAllowlistMixin, BaseHTTPRequestHandler):
        host_refusal_log = logger
        protocol_version = protocol

        def log_message(self, *args):
            pass

        def do_GET(self):
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _H


@pytest.fixture
def serve():
    servers = []

    def _start(handler_cls):
        srv = ThreadingHTTPServer((_HOST, 0), handler_cls)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return srv.server_address[1]

    yield _start
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def _exchange(port, head: bytes, timeout=5.0) -> bytes:
    with socket.create_connection((_HOST, port), timeout=timeout) as s:
        s.sendall(head)
        chunks = []
        while True:
            try:
                data = s.recv(65536)
            except (ConnectionResetError, ConnectionAbortedError):
                break
            if not data:
                break
            chunks.append(data)
        return b"".join(chunks)


def _wait_for(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


# -- F1: the refusal log line is bounded ---------------------------------------

def test_f1_huge_host_lines_log_a_bounded_line(serve, capture):
    lg, cap = capture
    port = serve(_handler_class(lg))
    head = (b"GET /x HTTP/1.1\r\n"
            + b"".join(b"Host: evil" + b"a" * 60000 + b"\r\n"
                       for _ in range(90))
            + b"\r\n")
    reply = _exchange(port, head)
    assert reply.startswith(b"HTTP/1.0 421 ")
    assert _wait_for(lambda: cap.messages)
    (line,) = cap.messages
    assert len(line) < 2048, len(line)
    assert "evilaaa" in line            # still names what was refused
    assert "chars cut" in line or "more" in line


def test_f1_huge_request_target_logs_a_bounded_line(serve, capture):
    lg, cap = capture
    port = serve(_handler_class(lg))
    head = (b"GET /" + b"p" * 60000 + b" HTTP/1.1\r\n"
            b"Host: rebind.example\r\n\r\n")
    reply = _exchange(port, head)
    assert reply.startswith(b"HTTP/1.0 421 ")
    assert _wait_for(lambda: cap.messages)
    (line,) = cap.messages
    assert len(line) < 2048, len(line)
    assert "rebind.example" in line
    assert "/ppp" in line


def test_f1_control_byte_field_is_bounded_and_escaped():
    # A field of control bytes is bounded and carries no raw control byte.
    text = gate._log_field("\x1b" * 100000)
    assert len(text) < 2048
    assert "\x1b" not in text


def test_f1_short_fields_are_logged_whole():
    assert gate._log_field(["rebind.example:8888"]) == \
        "['rebind.example:8888']"
    assert gate._log_field("/api/state") == "'/api/state'"


def test_f1_many_host_lines_are_trimmed_before_the_repr(capture,
                                                        monkeypatch):
    # The output alone cannot tell a trimmed list from a whole one (the
    # field cap hides the difference), so the repr's INPUT is pinned: the
    # point is never to render a 100-line, 64 KiB-a-line head in memory.
    lg, cap = capture
    seen = []
    real = gate._log_field

    def spy(value):
        seen.append(value)
        return real(value)

    monkeypatch.setattr(gate, "_log_field", spy)
    h = _bare_handler(_handler_class(lg))
    h.headers = http.client.parse_headers(io.BytesIO(
        b"".join(b"Host: evil%d.example" % i + b"x" * 1000 + b"\r\n"
                 for i in range(90))
        + b"\r\n"))
    h._note_host_refusal("misdirected Host refused (421)")
    (line,) = cap.messages
    assert "evil0.example" in line
    assert "evil89.example" not in line
    more = 90 - gate._LOG_MAX_HOST_LINES
    assert f"(+{more} more lines)" in line
    (hosts,) = [v for v in seen if isinstance(v, list)]
    assert len(hosts) == gate._LOG_MAX_HOST_LINES
    assert all(len(v) <= gate._LOG_FIELD_CAP + 1 for v in hosts)


# -- F2: a reset peer never raises out of the refusal --------------------------

class _ResetWriter:
    def write(self, data):
        raise ConnectionResetError("peer reset")

    def flush(self):
        pass


def _bare_handler(cls, **attrs):
    h = cls.__new__(cls)
    h.wfile = _ResetWriter()
    h.rfile = io.BytesIO(b"")
    h.command = "GET"
    h.path = "/"
    h.request_version = "HTTP/1.1"
    h.requestline = "GET / HTTP/1.1"
    h.client_address = (_HOST, 1)
    h.headers = http.client.parse_headers(io.BytesIO(b"\r\n"))
    h.server = None
    for key, value in attrs.items():
        setattr(h, key, value)
    return h


@pytest.mark.parametrize("command", ["GET", "HEAD", "POST"])
def test_f2_refusal_to_a_reset_peer_does_not_raise(capture, command):
    lg, _cap = capture
    h = _bare_handler(_handler_class(lg), command=command)
    h._refuse_head(421, "Misdirected Request", "misdirected_host")
    assert h.close_connection is True


def test_f2_reset_peer_refusal_through_parse_request(capture):
    lg, _cap = capture
    cls = _handler_class(lg)
    h = _bare_handler(cls)
    h.rfile = io.BytesIO(b"Host: rebind.example\r\n\r\n")
    h.raw_requestline = b"GET / HTTP/1.1\r\n"
    assert h.parse_request() is False
    assert h.close_connection is True


# -- F3: the refusal counter loses no count under concurrency ------------------

class _SlowCounterServer:
    """A server whose counter read yields, so an unlocked read-modify-write
    interleaves deterministically."""

    def __init__(self):
        self._n = 0

    @property
    def host_refusals(self):
        n = self._n
        time.sleep(0.002)
        return n

    @host_refusals.setter
    def host_refusals(self, value):
        self._n = value


def test_f3_concurrent_refusals_count_every_one(capture):
    lg, _cap = capture
    cls = _handler_class(lg)
    server = _SlowCounterServer()
    threads_n, per_thread = 4, 15

    def worker():
        for _ in range(per_thread):
            h = _bare_handler(cls, server=server)
            h._note_host_refusal("misdirected Host refused (421)")

    threads = [threading.Thread(target=worker) for _ in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert server._n == threads_n * per_thread


def test_f3_first_refusal_is_logged_once(capture):
    lg, cap = capture
    cls = _handler_class(lg)
    server = _SlowCounterServer()
    for _ in range(3):
        _bare_handler(cls, server=server)._note_host_refusal("x")
    assert len(cap.messages) == 1
    assert "count=1" in cap.messages[0]


# -- F4: no 100 Continue for a request the gate refuses ------------------------

@pytest.mark.parametrize("request_line, host, status", [
    (b"GET / HTTP/1.1", b"rebind.example", b"421"),
    (b"GET http://rebind.example/ HTTP/1.1", b"127.0.0.1", b"400"),
])
def test_f4_refused_head_gets_no_100_continue(serve, capture, request_line,
                                              host, status):
    lg, _cap = capture
    port = serve(_handler_class(lg, protocol="HTTP/1.1"))
    head = (request_line + b"\r\nHost: " + host
            + b"\r\nExpect: 100-continue\r\nContent-Length: 0\r\n\r\n")
    reply = _exchange(port, head)
    assert b"100 Continue" not in reply
    assert reply.startswith(b"HTTP/1.1 " + status + b" ")


def test_f4_allowed_head_still_gets_100_continue(serve, capture):
    lg, _cap = capture
    port = serve(_handler_class(lg, protocol="HTTP/1.1"))
    head = (b"GET / HTTP/1.1\r\nHost: rc-host:8888\r\n"
            b"Expect: 100-continue\r\nContent-Length: 0\r\n"
            b"Connection: close\r\n\r\n")
    reply = _exchange(port, head)
    assert reply.startswith(b"HTTP/1.1 100 Continue\r\n")
    assert b"HTTP/1.1 200 " in reply

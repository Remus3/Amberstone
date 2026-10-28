"""Lane 8 true-audit (s144) of core/http_head_deadline.py.

Drives ``HeadDeadlineMixin`` on a bare ``BaseHTTPRequestHandler`` over a real
loopback socket pair, so the stdlib's own ``handle_one_request`` /
``parse_request`` / ``TimeoutError`` path runs exactly as in the four servers
that adopt it (:8888, :8895, :8860, :8890).

Findings pinned here (each red before the fix):

1. A cap the socket layer cannot take - NaN, infinity, or a finite value past
   the platform limit (measured on Windows: about 2147482 s, a C ``int`` of
   milliseconds) - raised ``ValueError`` / ``OverflowError`` out of the first
   socket read. That is not ``TimeoutError``, so the stdlib does not catch
   it: every request on the server died with a traceback and no reply. A
   non-number cap raised ``TypeError`` before the head was read at all, and a
   zero or negative cap timed out EVERY request before a byte was read.
2. A handler with ``rbufsize = 0`` (an unbuffered ``rfile``, which
   ``StreamRequestHandler`` makes a raw ``SocketIO``) was skipped by
   ``setup()``: its head was silently UNBOUNDED.
3. ``setup()`` re-buffered the stream at ``io.DEFAULT_BUFFER_SIZE`` whatever
   ``rbufsize`` the handler asked for.
"""
from __future__ import annotations

import contextlib
import io
import logging
import math
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace

import pytest

from core import http_head_deadline as hhd
from core.http_head_deadline import HeadDeadlineMixin


class _Handler(HeadDeadlineMixin, BaseHTTPRequestHandler):
    """A minimal adopter: one GET route, quiet logs, records what it saw."""

    protocol_version = "HTTP/1.1"
    head_read_timeout_s = 0.5
    peek_body = False
    seen: dict = {}

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        rfile = self.rfile
        if self.peek_body:
            # Only when a body was sent: a peek on an empty buffer would
            # block on the socket.
            type(self).seen["peek_len"] = (
                len(rfile.peek()) if isinstance(rfile, io.BufferedReader)
                else None)
        type(self).seen["route_timeout"] = self.connection.gettimeout()
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args) -> None:
        type(self).seen.setdefault("log", []).append(fmt % args)


@contextlib.contextmanager
def _serve(handler_cls):
    """Run one handler instance on the server end of a loopback pair.

    Yields ``(client_socket, outcome)``; ``outcome["error"]`` holds anything
    the handler raised out of its constructor (setup / handle / finish).
    """
    handler_cls.seen = {}
    srv, cli = socket.socketpair()
    outcome: dict = {"error": None}

    def run() -> None:
        try:
            handler_cls(srv, ("127.0.0.1", 0), SimpleNamespace())
        except BaseException as e:  # noqa: BLE001 - the test inspects it
            outcome["error"] = e
        finally:
            with contextlib.suppress(OSError):
                srv.close()

    t = threading.Thread(target=run, daemon=True, name="s144-head-deadline")
    t.start()
    try:
        yield cli, outcome
    finally:
        with contextlib.suppress(OSError):
            cli.close()
        t.join(timeout=5)
    assert not t.is_alive(), "handler thread did not end"


def _time_to_close(sock: socket.socket, wait_s: float) -> float | None:
    """Seconds until the peer closes (EOF / reset), None if still open."""
    sock.settimeout(wait_s)
    t0 = time.monotonic()
    try:
        while sock.recv(4096):
            pass
    except TimeoutError:
        return None
    except OSError:
        pass
    return time.monotonic() - t0


def _get(sock: socket.socket, body: bytes = b"") -> bytes:
    length = b"Content-Length: %d\r\n" % len(body) if body else b""
    sock.sendall(b"GET /x HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                 b"Connection: close\r\n" + length + b"\r\n" + body)
    sock.settimeout(5)
    buf = b""
    with contextlib.suppress(OSError):
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
    return buf


# -- characterization: the shipped contract -----------------------------------

def test_an_idle_client_is_closed_at_the_head_deadline():
    with _serve(_Handler) as (cli, outcome):
        elapsed = _time_to_close(cli, wait_s=4.0)
    assert elapsed is not None and 0.3 <= elapsed < 3.0, elapsed
    assert outcome["error"] is None
    assert any("timed out" in m for m in _Handler.seen.get("log", []))


def test_a_prompt_request_is_served_and_the_route_sees_its_timeout_back():
    with _serve(_Handler) as (cli, outcome):
        reply = _get(cli)
    assert reply.startswith(b"HTTP/1.1 200"), reply
    assert outcome["error"] is None
    # socketpair sockets are blocking (None); the head's per-read timeout is
    # gone by the time the route runs.
    assert _Handler.seen["route_timeout"] is None


def test_an_idle_keep_alive_client_is_closed_after_its_first_request():
    with _serve(_Handler) as (cli, outcome):
        cli.sendall(b"GET /x HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        cli.settimeout(5)
        first = cli.recv(4096)
        assert first.startswith(b"HTTP/1.1 200"), first
        elapsed = _time_to_close(cli, wait_s=4.0)
    assert elapsed is not None and elapsed < 3.0, elapsed
    assert outcome["error"] is None


def test_a_none_cap_disables_the_deadline_and_leaves_the_socket_alone():
    class H(_Handler):
        head_read_timeout_s = None

    with _serve(H) as (cli, outcome):
        reply = _get(cli)
    assert reply.startswith(b"HTTP/1.1 200"), reply
    assert outcome["error"] is None
    assert H.seen["route_timeout"] is None


# -- finding 1: a cap the socket layer cannot take ----------------------------

@pytest.mark.parametrize("cap", [float("nan"), float("inf"), 1e12, "30"],
                         ids=["nan", "inf", "huge", "str"])
def test_an_unusable_cap_never_breaks_a_normal_request(cap):
    class H(_Handler):
        head_read_timeout_s = cap

    with _serve(H) as (cli, outcome):
        reply = _get(cli)
    assert outcome["error"] is None, repr(outcome["error"])
    assert reply.startswith(b"HTTP/1.1 200"), reply


@pytest.mark.parametrize("cap", [0, 0.0, -5.0], ids=["zero", "zero-f", "neg"])
def test_a_non_positive_cap_does_not_refuse_every_request(cap, monkeypatch):
    monkeypatch.setattr(hhd, "HEAD_READ_TIMEOUT_S", 3.0)

    class H(_Handler):
        head_read_timeout_s = cap

    with _serve(H) as (cli, outcome):
        reply = _get(cli)
    assert outcome["error"] is None, repr(outcome["error"])
    assert reply.startswith(b"HTTP/1.1 200"), reply


@pytest.mark.parametrize("cap", [float("nan"), -1.0, "30", True],
                         ids=["nan", "neg", "str", "bool"])
def test_an_unusable_cap_falls_back_to_the_bounded_default(cap, monkeypatch):
    # Fail toward the bound: a typo never leaves the head unbounded.
    monkeypatch.setattr(hhd, "HEAD_READ_TIMEOUT_S", 0.5)

    class H(_Handler):
        head_read_timeout_s = cap

    with _serve(H) as (cli, outcome):
        elapsed = _time_to_close(cli, wait_s=4.0)
    assert outcome["error"] is None, repr(outcome["error"])
    # Lower bound: the head got the default's time, not an already-spent
    # deadline (a negative cap used to refuse at once).
    assert elapsed is not None and 0.3 <= elapsed < 3.0, elapsed


def test_effective_cap_table(monkeypatch):
    monkeypatch.setattr(hhd, "HEAD_READ_TIMEOUT_S", 30.0)
    eff = hhd.effective_head_cap
    assert eff(None) is None
    assert eff(float("inf")) is None          # "no deadline", said literally
    assert eff(12.5) == 12.5
    assert eff(7) == 7.0
    assert eff(1e12) == hhd.MAX_HEAD_READ_TIMEOUT_S
    assert eff(10 ** 400) == hhd.MAX_HEAD_READ_TIMEOUT_S  # float() overflows
    for bad in (float("nan"), 0, 0.0, -1.0, float("-inf"), -(10 ** 400),
                "30", True, [1]):
        assert eff(bad) == 30.0, bad
    # The clamp sits well inside what every platform's socket layer takes.
    socket.socket().settimeout(hhd.MAX_HEAD_READ_TIMEOUT_S)
    assert math.isfinite(hhd.MAX_HEAD_READ_TIMEOUT_S)


def test_an_unusable_cap_is_warned_once_not_per_request(monkeypatch, caplog):
    monkeypatch.setattr(hhd, "HEAD_READ_TIMEOUT_S", 3.0)
    monkeypatch.setattr(hhd, "_WARNED", set())

    class H(_Handler):
        head_read_timeout_s = -2.0

    with caplog.at_level(logging.WARNING, logger=hhd.__name__):
        for _ in range(2):
            with _serve(H) as (cli, _outcome):
                _get(cli)
    hits = [r for r in caplog.records
            if r.name == hhd.__name__ and "head_read_timeout_s" in r.getMessage()]
    assert len(hits) == 1, [r.getMessage() for r in hits]
    assert "H" in hits[0].getMessage()


# -- finding 2: an unbuffered handler was silently unbounded ------------------

def test_an_unbuffered_handler_is_bounded_too():
    class H(_Handler):
        rbufsize = 0

    with _serve(H) as (cli, outcome):
        elapsed = _time_to_close(cli, wait_s=3.0)
    assert outcome["error"] is None, repr(outcome["error"])
    assert elapsed is not None and elapsed < 2.5, elapsed


def test_an_unbuffered_handler_still_serves_a_request():
    class H(_Handler):
        rbufsize = 0

    with _serve(H) as (cli, outcome):
        reply = _get(cli)
    assert outcome["error"] is None, repr(outcome["error"])
    assert reply.startswith(b"HTTP/1.1 200"), reply
    assert H.seen["route_timeout"] is None


# -- finding 3: the handler's buffer size is honoured -------------------------

def test_the_handlers_rbufsize_is_kept():
    class H(_Handler):
        rbufsize = 16
        peek_body = True

    with _serve(H) as (cli, outcome):
        # One send: head + a 200-byte body. A 16-byte buffer holds at most
        # 16 unread body bytes once the head is parsed.
        reply = _get(cli, body=b"p" * 200)
    assert outcome["error"] is None, repr(outcome["error"])
    assert reply.startswith(b"HTTP/1.1 200"), reply
    assert H.seen["peek_len"] is not None and H.seen["peek_len"] <= 16

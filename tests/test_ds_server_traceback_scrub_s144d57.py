"""RM-1279: the DS server logger renders tracebacks scrubbed and clipped.

``agents/daemon_slayer/server.py`` logs every exception that reaches the
``do_GET`` / ``do_POST`` 500 catch-all with ``_log.exception``. RM-1278
scrubbed and clipped the MESSAGE (the request path), but the traceback was
left to the stdlib formatter, and the ``daemon_slayer.server`` logger carried
no ``core.log_scrub.ScrubFilter`` (the RM-811 backstop the :8888 dashboard,
Mission Control and the match-DB MCP server install). So an exception whose
text held a newline forged a whole log line, an ESC reached the console raw,
and a 100k-character exception text was one 100k-character line. The logger
now carries the filter: the traceback goes through ``scrub_traceback`` (one
scrubbed line for the exception text, every line capped at MAX_LINE_CHARS).
"""
from __future__ import annotations

import logging

import pytest

from agents.daemon_slayer import server
from core import log_scrub

_FMT = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
# Control characters by code point, so the source stays 7-bit ASCII.
_ESC, _NEL, _LS = chr(0x1B), chr(0x85), chr(0x2028)
_FORGED = "2026-10-31 00:00:00 daemon_slayer.server ERROR forged line"


class _Cap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def cap():
    lg = logging.getLogger("daemon_slayer.server")
    handler = _Cap()
    prior = lg.level
    lg.addHandler(handler)
    lg.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        lg.removeHandler(handler)
        lg.setLevel(prior)


def _boom(text: str):
    def _route(*_a, **_k):
        raise RuntimeError(text)
    return _route


def _handler(path: str) -> tuple[server.Handler, list[int]]:
    h = object.__new__(server.Handler)
    h.path = path
    h.client_address = ("127.0.0.1", 50000)
    sent: list[int] = []
    h._send_error = lambda status, message, detail=None: sent.append(status)
    h._drain_request_body = lambda: None
    h._read_json_body = lambda: {}
    return h, sent


def _unhandled_text(cap: _Cap) -> str:
    (rec,) = [r for r in cap.records
              if r.getMessage().startswith("unhandled error in ")]
    return _FMT.format(rec)


def _drive(monkeypatch, cap, verb: str, text: str) -> str:
    if verb == "GET":
        monkeypatch.setattr(server, "_route_health", _boom(text))
        h, sent = _handler("/health")
        h.do_GET()
    else:
        monkeypatch.setitem(server._POST_ROUTES, "/dps", _boom(text))
        h, sent = _handler("/dps")
        h.do_POST()
    assert sent == [500]
    return _unhandled_text(cap)


def test_server_logger_carries_the_scrub_filter():
    lg = logging.getLogger("daemon_slayer.server")
    assert any(isinstance(f, log_scrub.ScrubFilter) for f in lg.filters)


@pytest.mark.parametrize("verb", ["GET", "POST"])
def test_exception_text_cannot_forge_a_log_line(monkeypatch, cap, verb):
    out = _drive(monkeypatch, cap, verb, "bad id\n" + _FORGED)
    assert not any(line.startswith(_FORGED) for line in out.split("\n"))
    assert "RuntimeError: bad id" in out


@pytest.mark.parametrize("verb", ["GET", "POST"])
def test_exception_text_controls_are_escaped(monkeypatch, cap, verb):
    out = _drive(monkeypatch, cap, verb, "x" + _ESC + "[31m" + _NEL + _LS + "y")
    for ch in (_ESC, _NEL, _LS):
        assert ch not in out


@pytest.mark.parametrize("verb", ["GET", "POST"])
def test_huge_exception_text_is_clipped(monkeypatch, cap, verb):
    out = _drive(monkeypatch, cap, verb, "Z" * 100_000)
    longest = max(len(line) for line in out.split("\n"))
    assert longest <= log_scrub.MAX_LINE_CHARS + 40, longest
    assert "chars cut]" in out
    assert "RuntimeError: " + "Z" * 64 in out  # the head is kept


def test_traceback_keeps_its_frames(monkeypatch, cap):
    out = _drive(monkeypatch, cap, "GET", "plain failure")
    assert "Traceback (most recent call last):" in out
    assert "in do_GET" in out
    assert out.rstrip().endswith("RuntimeError: plain failure")


def test_clean_message_is_left_as_is(cap):
    # Backslashes in an already-scrubbed message are not doubled again:
    # the filter only escapes controls (scrub_controls is idempotent).
    server._log.warning("engine rejected request (%d): %s", 404, "a\\x1bb")
    (rec,) = cap.records
    assert rec.getMessage() == "engine rejected request (404): a\\x1bb"
    assert rec.exc_text is None

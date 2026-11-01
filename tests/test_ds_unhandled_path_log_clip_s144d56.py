"""RM-1278: the DS request path is bounded and scrubbed in every log line.

``agents/daemon_slayer/server.py`` ``Handler.do_GET`` / ``do_POST`` log the
request path in their 500 catch-all (``unhandled error in GET|POST %s``).
The client types that path, up to http.server's 65536-character request
line, and the line logged it whole and unscrubbed: a client that reset the
connection while a 404 for a 60k-character route was being written left a
60k-character ERROR line, control characters included. The path is now
scrubbed with ``core.log_scrub.scrub_log`` and clipped like RM-1277's
engine-reject line. The DEBUG access-log line (``log_message``, already
scrubbed by RM-321 / RM-825) is clipped too: it carries the request line.
"""
from __future__ import annotations

import logging

import pytest

from agents.daemon_slayer import server
from core import log_scrub

_MARGIN = 160  # the fixed prefix and the cut marker


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


def _handler(path: str) -> tuple[server.Handler, list[int]]:
    """A Handler whose 404 write raises, as a client reset does mid-reply.

    The OSError reaches the catch-all, which logs the path and answers 500.
    """
    h = object.__new__(server.Handler)
    h.path = path
    h.client_address = ("127.0.0.1", 50000)
    sent: list[int] = []

    def _send_error(status: int, message: str, detail=None) -> None:
        sent.append(status)
        if status == 404:
            raise ConnectionResetError("client reset")

    h._send_error = _send_error
    h._drain_request_body = lambda: None
    return h, sent


def _unhandled(cap: _Cap, verb: str) -> list[str]:
    return [r.getMessage() for r in cap.records
            if r.getMessage().startswith(f"unhandled error in {verb} ")]


@pytest.mark.parametrize("verb", ["GET", "POST"])
def test_huge_path_in_catch_all_is_clipped(cap, verb):
    h, sent = _handler("/" + "A" * 60_000)
    getattr(h, f"do_{verb}")()
    assert sent == [404, 500]
    (line,) = _unhandled(cap, verb)
    assert len(line) <= log_scrub.MAX_LINE_CHARS + _MARGIN, len(line)
    assert "chars cut]" in line
    assert "/" + "A" * 64 in line  # the head of the path is kept


@pytest.mark.parametrize("verb", ["GET", "POST"])
def test_catch_all_path_is_scrubbed(cap, verb):
    h, sent = _handler("/nope\x1b[31m\x85FAKE")
    getattr(h, f"do_{verb}")()
    assert sent == [404, 500]
    (line,) = _unhandled(cap, verb)
    assert "\x1b" not in line and "\x85" not in line
    assert "chars cut" not in line


@pytest.mark.parametrize("verb", ["GET", "POST"])
def test_short_path_is_logged_unchanged(cap, verb):
    h, _ = _handler("/no-such-route")
    getattr(h, f"do_{verb}")()
    (line,) = _unhandled(cap, verb)
    assert line == f"unhandled error in {verb} /no-such-route"


def test_cut_count_is_exact(cap):
    path = "/" + "Q" * (log_scrub.MAX_LINE_CHARS + 776)
    h, _ = _handler(path)
    h.do_GET()
    (line,) = _unhandled(cap, "GET")
    assert line.endswith("[... 777 chars cut]"), line[-60:]


def test_access_log_line_is_clipped(cap):
    h, _ = _handler("/")
    h.log_message('"%s" %s %s', "GET /" + "B" * 60_000 + " HTTP/1.1",
                  "404", "-")
    (rec,) = [r for r in cap.records if r.levelno == logging.DEBUG]
    line = rec.getMessage()
    assert len(line) <= log_scrub.MAX_LINE_CHARS + _MARGIN, len(line)
    assert "chars cut]" in line


def test_short_access_log_line_unchanged_and_scrubbed(cap):
    h, _ = _handler("/")
    h.log_message('"%s" %s %s', "GET /x\x1bY HTTP/1.1", "200", "-")
    (rec,) = [r for r in cap.records if r.levelno == logging.DEBUG]
    line = rec.getMessage()
    assert line.startswith("127.0.0.1 - ")
    assert "\x1b" not in line and "chars cut" not in line

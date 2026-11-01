"""RM-1277: the DS engine-reject log line is bounded.

``agents/daemon_slayer/server.py`` ``_engine_reject`` (RM-838 (d)) answers an
engine ``KeyError`` / ``ValueError`` with a fixed line and logs the exception
text, scrubbed, at WARNING. The text can echo a client-typed value: an unknown
champion id inside a 1 MiB body (``_MAX_POST_BYTES``) was one ~1M-character
log line, and a 401-digit ``level`` was echoed digit for digit. The scrubbed
text is now clipped to ``core.log_scrub.MAX_LINE_CHARS`` with the same
``[... N chars cut]`` marker the traceback renderer uses (RM-825 (d)).
"""
from __future__ import annotations

import logging

import pytest

from agents.daemon_slayer import server
from core import log_scrub

_MARGIN = 160  # the fixed prefix, the type name and the cut marker


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


def _reject_lines(cap: _Cap) -> list[str]:
    return [r.getMessage() for r in cap.records
            if r.getMessage().startswith("engine rejected request")]


@pytest.mark.parametrize("exc_type,status", [(KeyError, 404), (ValueError, 422)])
def test_huge_exception_text_is_clipped(cap, exc_type, status):
    err = server._engine_reject(status, exc_type("Z" * 300_000))
    assert err.status == status
    assert err.message == server._ENGINE_REJECT_MSG[status]
    (line,) = _reject_lines(cap)
    assert len(line) <= log_scrub.MAX_LINE_CHARS + _MARGIN, len(line)
    assert exc_type.__name__ in line
    assert "chars cut]" in line
    assert "Z" * 64 in line  # the head of the text is kept


def test_clip_counts_the_scrubbed_text_not_the_raw_text(cap):
    # 2000 ESC characters scrub to 8000 characters of "\x1b": short raw,
    # long logged. The bound is on what reaches the log.
    server._engine_reject(422, ValueError("\x1b" * 2000))
    (line,) = _reject_lines(cap)
    assert "\x1b" not in line
    assert len(line) <= log_scrub.MAX_LINE_CHARS + _MARGIN, len(line)
    assert "chars cut]" in line


def test_cut_count_is_exact(cap):
    text = "Q" * (log_scrub.MAX_LINE_CHARS + 777)
    server._engine_reject(422, ValueError(text))
    (line,) = _reject_lines(cap)
    assert line.endswith("[... 777 chars cut]"), line[-60:]


@pytest.mark.parametrize("n", [0, 1, log_scrub.MAX_LINE_CHARS])
def test_text_at_or_under_the_cap_is_unchanged(cap, n):
    text = "r" * n
    server._engine_reject(422, ValueError(text))
    (line,) = _reject_lines(cap)
    assert line == f"engine rejected request (422): ValueError: {text}"
    assert "chars cut" not in line


def test_short_text_still_scrubbed(cap):
    server._engine_reject(404, KeyError("Ahri\x1b[31m\r\nFAKE"))
    (line,) = _reject_lines(cap)
    assert "\x1b" not in line and "\r" not in line and "\n" not in line
    assert "chars cut" not in line


def test_route_with_huge_unknown_champion_logs_a_bounded_line(cap):
    from agents.daemon_slayer.data_loader import DataSnapshot

    cache = server._SnapshotCache()
    cache.set(DataSnapshot.load())
    prior = server._CACHE
    server._CACHE = cache
    try:
        with pytest.raises(server._ApiError) as ei:
            server._route_stats({"champion": "Nope" * 100_000, "level": 11})
    finally:
        server._CACHE = prior
    assert ei.value.status == 404
    (line,) = _reject_lines(cap)
    assert len(line) <= log_scrub.MAX_LINE_CHARS + _MARGIN, len(line)
    assert "chars cut]" in line

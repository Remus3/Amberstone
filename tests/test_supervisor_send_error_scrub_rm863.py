# arch: RM-863 - the supervisor _send_error log line is scrubbed | section=tests | frozen=no
"""RM-863 (a): ``agents/_supervisor_http.py`` ``_QuietHandler._send_error``
logs the cause through ``core.log_scrub.scrub_log``.

Measured at main 6c7269ed8, before the fix: ``_send_error`` logged
``log.warning("%s: %s", public_msg, exc)`` - the raw exception text - and
the ``supervisor`` logger has no scrub filter, so an exception whose text
carried a client's control characters (a terminal escape, a CR/LF that forges
a log line, U+2028) reached the log as is. The wire body was already the
fixed ``public_msg`` (tests/test_p2w2_ds_h.py); this row is the log half,
the RM-853 dispatcher idiom: the cause once, scrubbed, with its type name.
"""
from __future__ import annotations

import json
import logging

import pytest

from core.log_scrub import scrub_log

SECRET_PATH = r"C:\Example Repo\data\secret_rm863.db"
_CONTROL_CHARS = ("\x1b", "\r", "\n", "\x85", "\x7f", "\u2028")


def _evil(marker: str) -> str:
    """Text with a marker, a filesystem path and control characters."""
    return f"{marker} at {SECRET_PATH} \x1b[31m\r\nFAKE-LINE\x85\x7f\u2028"


class _Cap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def cap():
    """A capturing handler on the supervisor logger, isolated from its real
    handlers (they write files) and from any filter, so a filter can never
    mask a call site that stopped scrubbing."""
    from agents._supervisor_common import log
    saved = (list(log.handlers), list(log.filters), log.propagate, log.level)
    c = _Cap()
    log.handlers = [c]
    log.filters = []
    log.propagate = False
    log.setLevel(logging.DEBUG)
    try:
        yield c
    finally:
        log.handlers, log.filters, log.propagate = saved[:3]
        log.setLevel(saved[3])


class _Handler:
    """Just enough of the request handler for ``_send_error``."""

    def __init__(self) -> None:
        self.responses: list[tuple[int, dict]] = []

    def _send_json(self, status: int, body: dict) -> None:
        self.responses.append((status, body))


def _send_error(status: int, public_msg: str, exc=None) -> _Handler:
    from agents._supervisor_http import _QuietHandler
    h = _Handler()
    _QuietHandler._send_error(h, status, public_msg, exc)
    return h


def test_the_logged_cause_carries_no_control_character(cap):
    exc = OSError(_evil("RM863-CAUSE"))
    _send_error(502, "vision server unreachable", exc)
    assert len(cap.records) == 1, "the cause is logged exactly once"
    text = cap.records[0].getMessage()
    for ch in _CONTROL_CHARS:
        assert ch not in text, f"the logged cause carries {ch!r}: {text!r}"


def test_the_cause_is_still_logged_scrubbed_with_its_type(cap):
    exc = LookupError(_evil("RM863-TYPED"))
    _send_error(500, "minimap crop failed", exc)
    (rec,) = cap.records
    text = rec.getMessage()
    assert "minimap crop failed" in text
    assert "LookupError" in text, "the type name rides on the line"
    assert scrub_log(str(exc)) in text, "the cause goes through scrub_log"
    assert "RM863-TYPED" in text, "the operator can still diagnose"
    assert rec.levelno == logging.WARNING
    # A raw exc_info would be rendered unscrubbed by the file handlers.
    assert rec.exc_info is None


def test_the_wire_body_is_still_the_public_message_only(cap):
    exc = RuntimeError(_evil("RM863-WIRE"))
    h = _send_error(400, "malformed JSON body", exc)
    assert h.responses == [(400, {"error": "malformed JSON body"})]
    raw = json.dumps(h.responses)
    assert "RM863-WIRE" not in raw and "Example Repo" not in raw


def test_no_cause_logs_nothing(cap):
    h = _send_error(411, "chunked request bodies are not supported")
    assert cap.records == []
    assert h.responses == [(411, {"error": "chunked request bodies are not supported"})]


def test_a_backslash_cannot_forge_a_scrubbed_escape(cap):
    """scrub_log escapes the backslash too (injective), so a client that
    types the literal characters of an escape cannot produce a line equal to
    a scrubbed real control character."""
    _send_error(500, "x", ValueError("\x1b"))
    _send_error(500, "x", ValueError("\\x1b"))
    first, second = (r.getMessage() for r in cap.records)
    assert first != second

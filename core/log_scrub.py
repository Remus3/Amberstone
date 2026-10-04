"""Control-character escaping for HTTP access-log records (RM-321).

``BaseHTTPRequestHandler.log_message`` ends with
``message.translate(self._control_char_table)``, which maps C0, DEL and the C1
range to ``\\xHH`` so a request target cannot inject terminal escapes into a
log a human later reads with ``cat`` / ``tail``. That table lives INSIDE the
method, so every override of ``log_message`` silently loses it.

This is the shared helper an override calls instead. It lives in ``core`` so
servers that are deliberately decoupled from ``dashboard/`` (``mc/``, the
vision server, the MCP server) can use it; ``dashboard._handler._scrub_log``
delegates here.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler

# Borrowed from the stdlib rather than re-rolled so it tracks any future
# widening of the table; the fallback covers a Python that drops the private
# attribute and is asserted equivalent by tests.
CONTROL_CHAR_TABLE = getattr(BaseHTTPRequestHandler, "_control_char_table", None)
SCRUB_RANGES = tuple(range(0x00, 0x20)) + tuple(range(0x7F, 0xA0))

_UNSET = object()


def scrub_log(text: str, table=_UNSET) -> str:
    """Escape control characters so a request cannot inject into a log."""
    if table is _UNSET:
        table = CONTROL_CHAR_TABLE
    if table is not None:
        return text.translate(table)
    # The backslash escape keeps the mapping injective: without it a client
    # could type the literal six characters `\x1b[31m` and produce a line
    # byte-identical to a scrubbed real ESC. The stdlib table does the same.
    return "".join(
        f"\\x{ord(ch):02x}" if ord(ch) in SCRUB_RANGES
        else ("\\\\" if ch == "\\" else ch)
        for ch in text
    )

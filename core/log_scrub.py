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

RM-811 residuals add the logger-wide backstop. ``scrub_log`` at a call site
is the precise fix, but the sweep measured 244 dashboard / mc call sites
logging exception text with no scrub, and a new route adds another. So:

- ``scrub_controls`` escapes the control characters ONLY (backslashes stay
  as they are), so it is idempotent over its own output and over
  ``scrub_log``'s: a backstop that runs after a per-site scrub never
  double-escapes it, and a Windows path in a server message stays readable.
- ``scrub_traceback`` renders an exception the way ``traceback`` does, but
  each exception's own text (message, notes, SyntaxError detail) is put
  through ``scrub_log`` onto ONE line, while the frame lines keep their line
  structure (they are the server's own source, control-escaped only). A
  client's text in an exception can no longer start a line of the log.
- ``ScrubFilter`` / ``install_scrub_filter`` attach both to a logger: a
  record whose formatted message holds a control character is rewritten
  through ``scrub_controls``, and a record carrying ``exc_info`` gets its
  ``exc_text`` pre-rendered through ``scrub_traceback`` (the stdlib
  ``Formatter`` uses a set ``exc_text`` instead of formatting the raw
  traceback). A record with neither is passed on untouched.

s144 true-audit cycle 108 (RM-1383) adds secret redaction to the
backstop. ``redact_secrets`` replaces a key-shaped token (an Anthropic
``sk-ant-`` key, a Riot ``RGAPI-`` key) and the value of a header-shaped
credential (``X-RC-Token``, ``X-Riot-Token``, ``X-Api-Key``,
``Authorization``, and the ``ANTHROPIC_API_KEY`` / ``RIOT_API_KEY`` /
``RC_DASH_TOKEN`` / ``RC_VISION_TOKEN`` env names) with ``[redacted]``. The filter
applies it to every record's message, to the traceback it renders (frame
lines included) and to an ``exc_text`` a caller already set. A record that
cannot be formatted keeps going to the handler's error path unless the
reprs that path prints hold a secret; then it becomes one redacted,
control-escaped line. ``scrub_log`` stays a pure, injective control-character
escaper: its output is pinned exactly, and the filter runs after it on
every installed logger.
"""
from __future__ import annotations

import builtins
import logging
import re
import traceback
from http.server import BaseHTTPRequestHandler

# RM-825 (c): the stdlib table stops at C1, so these reached a log raw:
# U+2028 / U+2029 (a line break to a log viewer and to str.splitlines) and
# the bidi embedding / override controls and isolates (U+202A..U+202E,
# U+2066..U+2069) plus the bidi marks (U+061C, U+200E, U+200F), which
# reorder the text a terminal shows. Escaped as ``\\uHHHH``; the backslash
# escape keeps that injective too.
EXTRA_SCRUB = ((0x061C, 0x200E, 0x200F, 0x2028, 0x2029)
               + tuple(range(0x202A, 0x202F)) + tuple(range(0x2066, 0x206A)))
# s144 true-audit: a lone surrogate (U+D800..U+DFFF; ``json.loads`` makes
# one out of a client's ``"\\ud800"``) is no control character, but RC's
# file handler encodes UTF-8 strictly, so ``emit`` raised UnicodeEncodeError
# and the WHOLE record was lost - a client could erase its own log line.
# Escaped as ``\\uHHHH`` like the extras, so every scrub's output encodes.
SURROGATES = tuple(range(0xD800, 0xE000))
# The ONE range table (dashboard._handler re-exports it, RM-825).
SCRUB_RANGES = (tuple(range(0x20)) + tuple(range(0x7F, 0xA0))
                + EXTRA_SCRUB + SURROGATES)


def _escape(cp: int) -> str:
    return f"\\x{cp:02x}" if cp <= 0xFF else f"\\u{cp:04x}"


# Borrowed from the stdlib rather than re-rolled so it tracks any future
# widening of the table, then widened by EXTRA_SCRUB and SURROGATES; the
# fallback covers a Python that drops the private attribute and is asserted
# equivalent by tests.
_STDLIB_TABLE = getattr(BaseHTTPRequestHandler, "_control_char_table", None)
CONTROL_CHAR_TABLE = (None if _STDLIB_TABLE is None else
                      {**_STDLIB_TABLE,
                       **{c: _escape(c) for c in EXTRA_SCRUB + SURROGATES}})

_UNSET = object()

# Control characters only - no backslash entry, which is what makes
# scrub_controls idempotent.
_CONTROLS_ONLY = {c: _escape(c) for c in SCRUB_RANGES}

# RM-825 (d): the longest rendered traceback line. A client's text in an
# exception message is put onto ONE line, so without a cap a 100k-character
# message was one 100k-character log line. A longer line keeps its first
# MAX_LINE_CHARS characters and a "[... N chars cut]" marker.
MAX_LINE_CHARS = 4096

_CAUSE = ("\nThe above exception was the direct cause of the following "
          "exception:\n\n")
_CONTEXT = ("\nDuring handling of the above exception, another exception "
            "occurred:\n\n")
# Exception-group rendering bounds, the stdlib's own defaults. Looked up
# rather than named: the builtin is 3.11+, and an empty tuple makes the
# isinstance test plain False on an older interpreter.
_MAX_GROUP_WIDTH = 15
_MAX_GROUP_DEPTH = 10
_GROUP_TYPE = getattr(builtins, "BaseExceptionGroup", ())


# RM-1383: the secret shapes a log line must never carry. False
# positives are acceptable, a missed key is not. The Anthropic floor of 8
# characters after the prefix matches tools/credential_patterns.py (a test
# pins the parity); core does not import tools.
REDACTED = "[redacted]"
# A header- or env-shaped credential: the name (anywhere, so a prefixed
# env name such as ``MY_ANTHROPIC_API_KEY`` matches), its separator, an
# optional auth scheme, then the value. The separator is ``:`` or ``=``
# with an optional quote either side, or a quoted comma (a header list of
# ``(name, value)`` tuples); a quote may be escaped (JSON inside a string)
# and a value quote may carry a ``b`` prefix (a bytes repr, the usual form
# of a raw header list). It never crosses a line, so a name ending one line
# cannot eat a word of the next. Run FIRST, so ``ANTHROPIC_API_KEY=sk-ant-``
# keys become one ``[redacted]``. A second pass replaces ``[redacted]``
# with itself, so the redaction is idempotent.
_Q = r"\\?[\"']"
_HEADER_SECRET = re.compile(
    r"(?i)(x-rc-token|x-riot-token|x-api-key|authorization|"
    r"anthropic_api_key|riot_api_key|rc_dash_token|rc_vision_token)"
    rf"((?:{_Q})?[ \t]*[:=][ \t]*(?:b?{_Q})?|{_Q}[ \t]*,[ \t]*b?{_Q})"
    r"((?:bearer|basic|token|digest|negotiate|apikey)[ \t]+)?"
    r"[^\s\"',;{}()\\]+")
_KEY_SECRETS = (
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "sk-ant-" + REDACTED),
    (re.compile(r"RGAPI-[A-Za-z0-9\-]{8,}"), "RGAPI-" + REDACTED),
)


def _header_sub(m: re.Match) -> str:
    return f"{m[1]}{m[2]}{m[3] or ''}{REDACTED}"


def redact_secrets(text: str) -> str:
    """Replace every secret shape above with ``[redacted]``. Idempotent;
    any other text, control characters included, is left as it is."""
    text = _HEADER_SECRET.sub(_header_sub, text)
    for pattern, marker in _KEY_SECRETS:
        text = pattern.sub(marker, text)
    return text


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
        _escape(ord(ch)) if ord(ch) in _CONTROLS_ONLY
        else ("\\\\" if ch == "\\" else ch)
        for ch in text
    )


def scrub_controls(text: str) -> str:
    """Escape C0, DEL and C1 as ``\\xHH`` and the RM-825 extras and lone
    surrogates as ``\\uHHHH``; leave every other character, backslashes
    included, as it is. Idempotent (see the module docstring)."""
    return text.translate(_CONTROLS_ONLY)


def _cap_line(line: str) -> str:
    if len(line) <= MAX_LINE_CHARS:
        return line
    return (f"{line[:MAX_LINE_CHARS]} [... "
            f"{len(line) - MAX_LINE_CHARS} chars cut]")


def _exception_text(exc: BaseException) -> str:
    """The ``ExcType: message`` part (with notes), scrubbed onto one line."""
    try:
        text = "".join(traceback.format_exception_only(exc))
    except Exception:  # noqa: BLE001 - a broken __str__ / __notes__
        text = f"{type(exc).__name__}: <exception text unavailable>"
    return scrub_log(redact_secrets(text.rstrip("\n"))) + "\n"


def _frames(tb) -> list[str]:
    out: list[str] = []
    for frame in traceback.format_tb(tb):
        out.append("\n".join(scrub_controls(redact_secrets(part))
                             for part in frame.split("\n")))
    return out


def _render(exc: BaseException, tb, seen: set[int], depth: int) -> list[str]:
    # Newest first, each paired with the separator printed AFTER it (between
    # it and the newer exception), then emitted oldest first - the stdlib's
    # order. `seen` stops a __cause__ / __context__ cycle.
    chain: list[tuple[BaseException, object, str | None]] = []
    e: BaseException | None = exc
    sep: str | None = None
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        chain.append((e, tb if e is exc else e.__traceback__, sep))
        if e.__cause__ is not None:
            e, sep = e.__cause__, _CAUSE
        elif e.__context__ is not None and not e.__suppress_context__:
            e, sep = e.__context__, _CONTEXT
        else:
            e = None
    out: list[str] = []
    for e, e_tb, after in reversed(chain):
        if e_tb is not None:
            out.append("Traceback (most recent call last):\n")
            out.extend(_frames(e_tb))
        out.append(_exception_text(e))
        if isinstance(e, _GROUP_TYPE):
            out.extend(_render_group(e, seen, depth))
        if after:
            out.append(after)
    return out


def _render_group(group: BaseException, seen: set[int],
                  depth: int) -> list[str]:
    if depth >= _MAX_GROUP_DEPTH:
        return ["  | ... (exception group nested too deep)\n"]
    out: list[str] = []
    subs = list(group.exceptions)
    for i, sub in enumerate(subs[:_MAX_GROUP_WIDTH], 1):
        out.append(f"  +---------------- {i} ----------------\n")
        body = "".join(_render(sub, sub.__traceback__, seen, depth + 1))
        # The body's only newlines are structural (every exception text in
        # it is already one line), so prefixing each one is safe.
        out.extend(f"  | {line}\n" for line in body.rstrip("\n").split("\n"))
    if len(subs) > _MAX_GROUP_WIDTH:
        out.append(f"  +---------------- ... and "
                   f"{len(subs) - _MAX_GROUP_WIDTH} more exceptions\n")
    return out


def scrub_traceback(exc: BaseException, tb=_UNSET) -> str:
    """``exc`` rendered as a traceback that no client text can break out of.

    ``tb`` overrides the outermost exception's traceback (a logging
    ``exc_info`` triple carries its own); by default ``exc.__traceback__``.
    The result ends in a newline, as ``traceback.format_exception`` does.
    Every line is at most ``MAX_LINE_CHARS`` plus the cut marker (RM-825).
    """
    if tb is _UNSET:
        tb = exc.__traceback__
    text = "".join(_render(exc, tb, set(), 0))
    return "\n".join(_cap_line(line) for line in text.split("\n"))


class ScrubFilter(logging.Filter):
    """The log-injection backstop for one logger (module docstring).

    Never drops a record and never raises: a message that cannot be
    formatted is left for the handler's own error path, and a traceback that
    cannot be rendered falls back to its exception type alone - never to
    the raw traceback.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception as fmt_exc:  # noqa: BLE001 - handler reports it
            msg = None
            # RM-1383: Handler.handleError prints the format error's
            # traceback and the reprs of the raw msg and args. Without a
            # secret in any of them the record is left for that error path,
            # as before; with one it is replaced by one redacted,
            # control-escaped line that formats.
            _replace_unformattable_secret(record, fmt_exc)
        if msg is not None:
            clean = scrub_controls(redact_secrets(msg))
            if clean != msg:
                record.msg, record.args = clean, ()
        exc_info = record.exc_info
        if (isinstance(exc_info, tuple) and len(exc_info) == 3
                and isinstance(exc_info[1], BaseException)
                and not record.exc_text):
            try:
                text = scrub_traceback(exc_info[1], exc_info[2])
            except Exception:  # noqa: BLE001
                # The type name is data too: a class built at runtime can
                # carry an ESC or a newline, so it is scrubbed like the rest.
                text = (f"{scrub_log(redact_secrets(type(exc_info[1]).__name__))} "
                        "(traceback could not be rendered)")
            record.exc_text = text.rstrip("\n")
        elif isinstance(record.exc_text, str) and record.exc_text:
            # A caller rendered it already; its line structure is theirs,
            # so only the secrets are removed (RM-1383).
            record.exc_text = redact_secrets(record.exc_text)
        return True


UNFORMATTABLE = "log record could not be formatted (secret redacted): "


def _replace_unformattable_secret(record: logging.LogRecord,
                                  fmt_exc: BaseException) -> None:
    # Redacting the template or the args in place is NOT safe: a redaction
    # can eat a ``%s`` and turn the bad record into one that formats with
    # its raw, unescaped args (measured by the cycle-108 verifier). The
    # whole record is rendered once, the way handleError prints it: the
    # format error (its whole chain - an arg's __str__ can raise one that
    # quotes a key) and the reprs.
    try:
        error = "".join(traceback.format_exception(fmt_exc))
    except Exception:  # noqa: BLE001 - a broken __str__ / __notes__
        error = type(fmt_exc).__name__
    try:
        raw = f"msg={record.msg!r} args={record.args!r}"
    except Exception:  # noqa: BLE001 - a broken __repr__; nothing to print
        raw = None
    if raw is None:
        if redact_secrets(error) == error:
            return
        raw = "msg=<repr unavailable> args=<repr unavailable>"
    elif redact_secrets(raw) == raw and redact_secrets(error) == error:
        return
    record.msg = (UNFORMATTABLE + scrub_controls(redact_secrets(raw))
                  + " error=" + _exception_text(fmt_exc).rstrip("\n"))
    record.args = ()


def install_scrub_filter(*loggers: logging.Logger | str) -> None:
    """Attach one ``ScrubFilter`` to each logger (a name or a Logger).
    Idempotent: a logger that already carries one is left as it is.

    A logger's filters see only the records created on THAT logger, not a
    child's, so each name a package logs on is installed explicitly (the
    package guard enumerates them from source)."""
    for logger_or_name in loggers:
        lg = (logging.getLogger(logger_or_name) if isinstance(logger_or_name, str)
              else logger_or_name)
        if not any(isinstance(f, ScrubFilter) for f in lg.filters):
            lg.addFilter(ScrubFilter())

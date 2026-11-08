"""Shared CRLF text-layer harness for the RM-481 LF appender guards.

**Why this exists.** On Windows a text-mode write whose ``newline`` is None (the
default) turns every "\\n" into "\\r\\n"; on hosted-Linux CI it does not, so a
test asserting that an appender writes LF bytes is vacuous there unless
something reproduces the Windows translation. Six modules (s144p186, s144p190
through s144p194) each carried a private copy of a harness that wrapped
``builtins.open`` / ``io.open`` and injected ``newline="\\r\\n"`` - but only when
the call passed FEWER THAN THREE positional arguments after ``mode`` and no
``newline=`` keyword.

``pathlib.Path.open`` (3.11 through 3.14; CI pins 3.12, measured on 3.14.4)
calls ``io.open(self, mode, buffering, encoding, errors, newline)``: FOUR
positional arguments after ``mode``, ``newline`` among them. The copies skipped
that call, so on Linux a ``Path.open("a")`` append - and ``Path.write_text``,
which routes through it - was never translated. Nearly every appender those
modules guard writes through ``Path.open``, so their LF assertions passed on
Linux whether or not the appender pinned ``newline=``. On Windows the native
text layer produced the CRLF the harness should have, so the ``Path.open``
positive controls passed locally and went red only on CI run 42427610342
("harness missed Path.open" / "harness failed to force CRLF") - the control was
right; the harness was blind.

This harness reads ``newline`` from wherever the caller put it (keyword, or the
sixth positional of ``open()``) and records every write it forced, so a positive
control asserts the patch was HIT for its own file instead of inferring it from
bytes the host's text layer might have produced on its own.
"""
from __future__ import annotations

import builtins
import io
import os

# open(file, mode, buffering, encoding, errors, newline, closefd, opener):
# the index of ``newline`` among the positional arguments that FOLLOW mode.
_NEWLINE_POS = 3
_WRITE_CHARS = "wax+"


class CrlfTextLayer:
    """What the harness forced, so a positive control can prove it was hit."""

    def __init__(self) -> None:
        self.forced: list[str] = []

    def forced_for(self, path) -> bool:
        """True when a text-mode write to ``path`` was forced to CRLF."""
        return os.fspath(path) in self.forced


def _label(file) -> str:
    if isinstance(file, (str, bytes, os.PathLike)):
        name = os.fspath(file)
        return name.decode("utf-8", "replace") if isinstance(name, bytes) else name
    return repr(file)  # a file descriptor (os.fdopen) has no path


def _is_text_write(mode) -> bool:
    return (isinstance(mode, str) and "b" not in mode
            and any(c in mode for c in _WRITE_CHARS))


def install_crlf_text_layer(monkeypatch) -> CrlfTextLayer:
    """Reproduce the Windows LF -> CRLF text translation on every OS.

    Patches ``builtins.open`` (bare ``open``) and ``io.open`` (the route
    ``pathlib.Path.open`` and ``os.fdopen`` take); a write-capable text-mode open
    whose ``newline`` is None - by keyword, by omission, or positionally - gets
    ``newline="\\r\\n"``. An explicit ``newline=`` ("\\n", "") is left alone,
    exactly as Windows leaves it alone. Returns the record of forced writes.
    """
    orig_open = builtins.open
    layer = CrlfTextLayer()

    def _open(file, mode="r", *args, **kwargs):
        if _is_text_write(mode):
            if len(args) > _NEWLINE_POS:
                if args[_NEWLINE_POS] is None:
                    args = (*args[:_NEWLINE_POS], "\r\n",
                            *args[_NEWLINE_POS + 1:])
                    layer.forced.append(_label(file))
            elif kwargs.get("newline") is None:
                kwargs["newline"] = "\r\n"
                layer.forced.append(_label(file))
        return orig_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _open)
    monkeypatch.setattr(io, "open", _open)
    return layer

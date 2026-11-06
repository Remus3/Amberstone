"""RM-481 residual (s144, RM-1707): logging file handlers write LF.

The stdlib ``FileHandler._open`` calls ``open(path, mode, encoding=..., errors=...)``
with no ``newline=``, so on Windows every record the handler emits ends in
CRLF - the same family of defect RM-1701..RM-1706 closed for hand-written
text-mode appenders. ``core.log_rotation`` now carries LF-writing handlers
(``LFFileHandler``, ``LFRotatingFileHandler``; ``SafeRotatingFileHandler``
inherits the second) and these writers build them instead of the stdlib ones:

- agents/_supervisor_common.py (supervisor.log);
- tools/ds_keepalive.py (ds_keepalive.log);
- tools/hotkey_listener.py (hotkey_listener.log);
- scripts/rewind_catchup.py (rewind_catchup.log);
- core/log_rotation.py ``SafeRotatingFileHandler`` (lcu_agent.log).

CI is Linux, where the text layer does not translate, so the behaviour tests run
under a harness that forces CRLF on any text-mode open that passes no
``newline=``; a positive control proves the stdlib handler bites under it.
Excluded by ownership: core/log_setup.py (frozen daily handler) and the
launcher / supervisor files.
"""
from __future__ import annotations

import ast
import builtins
import io
import logging
import logging.handlers

import pytest

from core import log_rotation
from tests._repo_walk import REPO_ROOT

_CONVERTED = (
    "agents/_supervisor_common.py",
    "tools/ds_keepalive.py",
    "tools/hotkey_listener.py",
    "scripts/rewind_catchup.py",
)
_STDLIB_FILE_HANDLERS = {"FileHandler", "RotatingFileHandler",
                         "TimedRotatingFileHandler", "WatchedFileHandler"}


def _stdlib_handler_calls(src: str) -> list[int]:
    """Line numbers of calls that construct a stdlib file handler."""
    out: list[int] = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
        if name in _STDLIB_FILE_HANDLERS:
            out.append(node.lineno)
    return out


def test_detector_controls():
    assert _stdlib_handler_calls("import logging\nlogging.FileHandler('a')\n") == [2]
    assert _stdlib_handler_calls("from logging.handlers import RotatingFileHandler\n"
                                 "RotatingFileHandler('a')\n") == [2]
    assert _stdlib_handler_calls("from core.log_rotation import LFFileHandler\n"
                                 "LFFileHandler('a')\n") == []


@pytest.mark.parametrize("rel", _CONVERTED)
def test_converted_module_builds_no_stdlib_file_handler(rel):
    path = REPO_ROOT / rel
    assert path.is_file(), f"{rel} missing - the scan would be vacuous"
    found = _stdlib_handler_calls(path.read_bytes().decode("utf-8"))
    assert found == [], (
        f"{rel}: stdlib file handler writes CRLF records on Windows "
        f"(use core.log_rotation.LF* handlers; lines {found})")


@pytest.fixture
def crlf_text_layer(monkeypatch):
    """Reproduce the Windows LF -> CRLF text translation on every OS."""
    orig_open = builtins.open

    def _open(file, mode="r", *args, **kwargs):
        if ("b" not in mode and any(c in mode for c in "wax+")
                and len(args) < 3 and kwargs.get("newline") is None):
            kwargs["newline"] = "\r\n"
        return orig_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _open)
    monkeypatch.setattr(io, "open", _open)


def _emit_two(handler: logging.Handler, name: str) -> None:
    # A bare Logger is not registered with the manager, so nothing leaks into
    # the NOW-7 logger-leak gate.
    lg = logging.Logger(name, logging.INFO)
    lg.addHandler(handler)
    try:
        lg.info("first")
        lg.info("second")
    finally:
        lg.removeHandler(handler)
        handler.close()


def test_positive_control_stdlib_file_handler_writes_crlf(tmp_path, crlf_text_layer):
    target = tmp_path / "control.log"
    _emit_two(logging.FileHandler(target, encoding="utf-8"), "s144p196.control")
    assert target.read_bytes().count(b"\r\n") == 2, "harness failed to force CRLF"


def test_lf_file_handler_writes_lf(tmp_path, crlf_text_layer):
    target = tmp_path / "plain.log"
    _emit_two(log_rotation.LFFileHandler(target, encoding="utf-8"), "s144p196.plain")
    raw = target.read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2


def test_lf_rotating_file_handler_writes_lf(tmp_path, crlf_text_layer):
    target = tmp_path / "rot.log"
    h = log_rotation.LFRotatingFileHandler(
        target, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    _emit_two(h, "s144p196.rot")
    raw = target.read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2


def test_safe_rotating_handler_writes_lf(tmp_path, crlf_text_layer):
    target = tmp_path / "safe.log"
    h = log_rotation.rotating_file_handler(target)
    assert isinstance(h, logging.handlers.RotatingFileHandler)
    _emit_two(h, "s144p196.safe")
    raw = target.read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2


def test_lf_handlers_keep_their_stdlib_bases():
    assert issubclass(log_rotation.LFFileHandler, logging.FileHandler)
    assert issubclass(log_rotation.LFRotatingFileHandler,
                      logging.handlers.RotatingFileHandler)
    assert issubclass(log_rotation.SafeRotatingFileHandler,
                      log_rotation.LFRotatingFileHandler)


def test_delayed_open_also_writes_lf(tmp_path, crlf_text_layer):
    target = tmp_path / "delay.log"
    h = log_rotation.LFFileHandler(target, encoding="utf-8", delay=True)
    _emit_two(h, "s144p196.delay")
    assert b"\r" not in target.read_bytes()

"""RM-481 residual (s144, RM-1708): seven more logging file handlers write LF.

RM-1707 added ``LFFileHandler`` / ``LFRotatingFileHandler`` to
``core.log_rotation`` (the stdlib ``FileHandler._open`` passes no ``newline=``,
so every record is CRLF on Windows) and converted the writers that already
import ``core``. These seven were the next group, each with the repo root
importable at the handler's build site:

- agents/agent2_backend/ws_server.py ``_build_logger`` (agent2 logs);
- scripts/repair_tft_match_rows.py ``_logfile`` (apply log);
- scripts/data_pipeline.py (data_pipeline.log, module level);
- mission_control.py ``_setup_logging`` (mission_control-<date>.log);
- tools/daemon_slayer_extract.py and tools/daemon_slayer_abilities_extract.py
  ``_configure_logging`` (the DS extractor logs);
- vision_server/_config.py (moon_vision_server.log; the module already imports
  ``core.vision_token``, so ``core`` is importable there).

Deferred, not forgotten (RM-1710): tools/liveclient_relay.py,
tools/phase_watcher.py, tools/screen_agent.py - they run as scripts with
``tools/`` as sys.path[0] and no repo-root insertion, and two cite-symbol tests
pin liveclient_relay's current handler line.

CI is Linux, where the text layer does not translate, so the behaviour tests
run under a harness that forces CRLF on any text-mode open that passes no
``newline=``; this module's own positive control proves the stdlib handler
bites under it (s154 C1b: it used to lean on RM-1707's control in another
module). The source scan also requires an LF handler to be PRESENT, so
deleting the handler outright cannot pass it.
"""
from __future__ import annotations

import contextlib
import importlib
import logging

import pytest

from tests._crlf_text_layer import install_crlf_text_layer
from tests._repo_walk import REPO_ROOT
from tests.test_log_handlers_lf_s144p196 import _emit_two, _stdlib_handler_calls

_CONVERTED = (
    "agents/agent2_backend/ws_server.py",
    "scripts/repair_tft_match_rows.py",
    "scripts/data_pipeline.py",
    "mission_control.py",
    "tools/daemon_slayer_extract.py",
    "tools/daemon_slayer_abilities_extract.py",
    "vision_server/_config.py",
)


@pytest.mark.parametrize("rel", _CONVERTED)
def test_converted_module_builds_an_lf_handler_and_no_stdlib_one(rel):
    path = REPO_ROOT / rel
    assert path.is_file(), f"{rel} missing - the scan would be vacuous"
    src = path.read_bytes().decode("utf-8")
    assert _stdlib_handler_calls(src) == [], (
        f"{rel}: stdlib file handler writes CRLF records on Windows "
        f"(use core.log_rotation.LF* handlers; lines {_stdlib_handler_calls(src)})")
    assert "from core.log_rotation import" in src, f"{rel} does not import the LF handler"
    assert "LFFileHandler(" in src or "LFRotatingFileHandler(" in src, (
        f"{rel} builds no LF handler - the scan above would pass with no file log at all")


@pytest.fixture
def crlf_text_layer(monkeypatch):
    """Reproduce the Windows LF -> CRLF text translation on every OS (the shared
    harness, tests/_crlf_text_layer.py; a handler built under it binds it)."""
    return install_crlf_text_layer(monkeypatch)


def test_positive_control_stdlib_file_handler_writes_crlf(tmp_path, crlf_text_layer):
    target = tmp_path / "control.log"
    _emit_two(logging.FileHandler(target, encoding="utf-8"), "s144p197.control")
    assert crlf_text_layer.forced_for(target), "harness missed the FileHandler open"
    assert target.read_bytes().count(b"\r\n") == 2, "harness failed to force CRLF"


def test_ws_server_build_logger_writes_lf(tmp_path, crlf_text_layer):
    ws = importlib.import_module("agents.agent2_backend.ws_server")
    name = "s144p197.ws_server"
    target = tmp_path / "ws.log"
    lg = ws._build_logger(name, target)
    try:
        lg.info("first")
        lg.info("second")
    finally:
        for h in list(lg.handlers):
            lg.removeHandler(h)
            h.close()
        logging.Logger.manager.loggerDict.pop(name, None)
    raw = target.read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2


def test_repair_tft_logfile_writes_lf(tmp_path, crlf_text_layer):
    mod = importlib.import_module("scripts.repair_tft_match_rows")
    with contextlib.ExitStack() as stack:
        stack.enter_context(mod._logfile(tmp_path))
        logging.getLogger().info("first")
        logging.getLogger().info("second")
    raw = (tmp_path / "logs" / mod.LOG_NAME).read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") >= 2

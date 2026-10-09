"""anthropic 1.11 renamed its HTTP transport loggers to httpx2 / httpcore2.

`core/log_setup.setup()` quiets the noisy third-party transport loggers to
WARNING (DEBUG only in debug mode). Before this fix the list named only the
old `httpx` / `httpcore` names, so after the anthropic 0.96 -> 1.11 bump every
request line from the renamed loggers reached the root DEBUG file handler.
Operator grant 2026-10-09: add `httpx2` and `httpcore2` next to the old names.

setup() mutates process-global logging state (root handlers, root level,
sys.excepthook, threading.excepthook, the once-only flag), so the fixture
snapshots and restores all of it.
"""

from __future__ import annotations

import logging
import sys
import threading

import pytest

from core import log_setup

_NAMES = ("httpx", "httpcore", "httpx2", "httpcore2")
# Every logger setup() sets a level on, so the fixture restores all of them.
_TOUCHED = _NAMES + ("urllib3", "anthropic._base_client")


@pytest.fixture
def isolated_setup(tmp_path):
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_root_level = root.level
    saved_levels = {n: logging.getLogger(n).level for n in _TOUCHED}
    saved_hook = sys.excepthook
    saved_thread_hook = threading.excepthook
    saved_flag = log_setup._root_logger_configured
    log_setup._root_logger_configured = False
    for n in _NAMES:
        logging.getLogger(n).setLevel(logging.NOTSET)
    try:
        yield tmp_path
    finally:
        for h in list(root.handlers):
            if h not in saved_handlers:
                root.removeHandler(h)
                h.close()
        root.setLevel(saved_root_level)
        for n, lvl in saved_levels.items():
            logging.getLogger(n).setLevel(lvl)
        sys.excepthook = saved_hook
        threading.excepthook = saved_thread_hook
        log_setup._root_logger_configured = saved_flag


@pytest.mark.parametrize("name", ["httpx2", "httpcore2", "httpx", "httpcore"])
def test_transport_loggers_quieted_to_warning(isolated_setup, name):
    log_setup.setup(isolated_setup, debug=False)
    assert logging.getLogger(name).level == logging.WARNING


@pytest.mark.parametrize("name", ["httpx2", "httpcore2"])
def test_renamed_loggers_verbose_in_debug_mode(isolated_setup, name):
    log_setup.setup(isolated_setup, debug=True)
    assert logging.getLogger(name).level == logging.DEBUG


def test_renamed_logger_debug_line_does_not_reach_file(isolated_setup):
    log_setup.setup(isolated_setup, debug=False)
    logging.getLogger("httpx2").debug("HTTP Request: POST sentinel-w-i")
    for h in logging.getLogger().handlers:
        h.flush()
    text = "".join(
        p.read_text(encoding="utf-8") for p in (isolated_setup / "logs").glob("*.log")
    )
    assert "sentinel-w-i" not in text

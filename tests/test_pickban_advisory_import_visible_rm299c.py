"""RM-299c: a non-ImportError raised while importing the DS CC registry must
be VISIBLE (a WARNING), not a silent `return None`.

cc_conditional reads the REQUIRED cc_conditional_registry.json at import, so a
moved or malformed data file raises FileNotFoundError / JSONDecodeError - the
broad swallow then killed the cleanse advisory with no log line at any level.
"""
from __future__ import annotations

import builtins
import json
import logging
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dashboard.routes_pickban as pb  # noqa: E402

_real_import = builtins.__import__


def _raising(exc):
    def fake(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agents.daemon_slayer" and "cc_conditional" in (fromlist or ()):
            raise exc
        return _real_import(name, globals, locals, fromlist, level)
    return fake


@pytest.mark.parametrize("exc", [
    FileNotFoundError("cc_conditional_registry.json"),
    json.JSONDecodeError("bad", "x", 0),
    KeyError("primary"),
])
def test_data_failure_at_import_is_logged(exc, caplog):
    pb._ADVISORY_IMPORT_WARNED.clear()
    caplog.set_level(logging.DEBUG, logger="rc.web_dashboard")
    with mock.patch("builtins.__import__", _raising(exc)):
        out = pb._compose_cleanse_advisory((1, 2, 3), (4, 14))
    assert out is None
    warns = [r for r in caplog.records if r.levelno == logging.WARNING
             and "cleanse advisory disabled" in r.getMessage()]
    assert warns, "a data failure at import still dies silently"
    assert type(exc).__name__ in warns[0].getMessage()


def test_repeat_failures_do_not_spam(caplog):
    pb._ADVISORY_IMPORT_WARNED.clear()
    caplog.set_level(logging.DEBUG, logger="rc.web_dashboard")
    with mock.patch("builtins.__import__", _raising(FileNotFoundError("x"))):
        for _ in range(5):
            pb._compose_cleanse_advisory((1,), (4, 14))
    warns = [r for r in caplog.records if r.levelno == logging.WARNING
             and "cleanse advisory disabled" in r.getMessage()]
    assert len(warns) == 1

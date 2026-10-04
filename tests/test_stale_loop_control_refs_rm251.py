"""RM-251(a): Mission Control S10 Task 9 de-registered POST /api/loop-control
from the :8888 dispatch table (it lives on the Mission Control server now),
but the :8888 control-auth set and the auto-accept trust-model prose still
named it. A dead literal in an auth set reads as coverage that does not
exist on this surface.
"""
from __future__ import annotations

from pathlib import Path

import dashboard._handler as dash_handler

_ROOT = Path(__file__).resolve().parent.parent


def test_control_set_does_not_name_an_unrouted_path():
    assert "/api/loop-control" not in dash_handler._CONTROL_ENDPOINTS
    # Positive control: the live control members are still there.
    assert {"/api/command", "/api/input", "/api/analyze",
            "/api/lcu-cmd"} <= dash_handler._CONTROL_ENDPOINTS


def test_auto_accept_prose_no_longer_cites_it_as_a_peer():
    src = (_ROOT / "dashboard" / "routes_auto_accept.py").read_text(encoding="utf-8")
    assert "/api/loop-control" not in src

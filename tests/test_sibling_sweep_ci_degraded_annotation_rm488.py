"""RM-488: CI's sweep is armed with nothing (the names live in gitignored
per-host config and the RC_MOON_SYNC_REPOS secret is unset), so its green is
PARTIAL. Arming it is an operator settings act; what the code can do is stop
the green from LOOKING complete - a run-summary warning annotation.
"""
from __future__ import annotations

from types import SimpleNamespace

from tools import sibling_name_sweep as sweep
from tools import sibling_sweep_ci as ci


def _cfg(mode):
    return SimpleNamespace(mode=mode)


def test_degraded_under_actions_emits_a_warning_annotation():
    line = ci.degraded_annotation(_cfg(sweep.MODE_DEGRADED), {"GITHUB_ACTIONS": "true"})
    assert line and line.startswith("::warning ")
    assert "PARTIAL" in line


def test_armed_run_emits_no_annotation():
    armed = getattr(sweep, "MODE_ARMED", "armed")
    assert ci.degraded_annotation(_cfg(armed), {"GITHUB_ACTIONS": "true"}) is None


def test_local_degraded_run_emits_no_workflow_command():
    assert ci.degraded_annotation(_cfg(sweep.MODE_DEGRADED), {}) is None

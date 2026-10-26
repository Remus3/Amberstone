"""One handle on the kit's ``fleet_test_guard`` for wall-clock tests (MAIN
ORDER 2026-10-26 0300, U5 item 1).

A timing test writes its upper bound for an idle box and scales it:

    from tests._timing_budget import fleet_test_guard
    assert elapsed < fleet_test_guard.budget(2.0)

``budget(seconds)`` is seconds x the live suite-gate slot holders (1..4,
kit v16), so the bound widens only while other suites share the CPU. Lower
bounds stay raw. Where the unfixed code path takes a FINITE time that a
widened bound would admit, cap it below that time,
``min(fleet_test_guard.budget(x), cap)``, so the test still tells fixed from
broken. ``tests/test_timing_bounds_use_budget_u5.py`` fails on any raw bound.

The module is the one ``tests/conftest.py`` already loaded by file path (kept
in ``sys.modules["fleet_test_guard"]``), so ``ops/fleet_kit`` never goes on
``sys.path``; loaded the same way here if this is imported first.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_KIT_FILE = Path(__file__).resolve().parent.parent / "ops" / "fleet_kit" / "fleet_test_guard.py"


def _load():
    cached = sys.modules.get("fleet_test_guard")
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location("fleet_test_guard", _KIT_FILE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fleet_test_guard"] = mod
    spec.loader.exec_module(mod)
    return mod


fleet_test_guard = _load()

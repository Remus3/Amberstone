"""Shared pytest config for the agent3 suite.

1. Ensure the project root is on sys.path.
2. Defensive asyncio isolation (s236): several agent3 tests
   (test_auto_analyze / test_round12 / test_round17 /
   test_warm_ui_watchdog) drive their loop body with a bare
   ``asyncio.run()``. ``asyncio.run()`` raises
   "cannot be called from a running event loop" whenever asyncio's
   per-thread running-loop slot is set - and a prior suite in the
   full triplet (notably a ``tests/`` ``unittest.IsolatedAsyncioTestCase``
   class) can, under full-suite load, leave that slot populated even
   though no loop is actually spinning. The result: those tests pass
   in isolation but fail in the triplet. Clearing the stale slot
   before + after each test makes the suite immune to upstream
   loop-state leakage regardless of which test leaks it (same
   process-global isolation pattern as the s223 tests/conftest.py
   autouse fixture).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _clear_running_loop() -> None:
    # asyncio.events._set_running_loop is a stable CPython internal
    # (>=3.5.3, used by CPython's own test harness). getattr-guarded so
    # a future rename degrades to a no-op instead of erroring the suite.
    setter = getattr(asyncio.events, "_set_running_loop", None)
    if setter is not None:
        setter(None)


@pytest.fixture(autouse=True)
def _isolate_asyncio_running_loop():
    _clear_running_loop()
    yield
    _clear_running_loop()

"""Shared pytest config for the agent3 suite.

1. Ensure the project root is on sys.path.
2. No asyncio running-loop handling here, on purpose (RM-1974c). An
   autouse fixture used to clear asyncio's main-thread running-loop
   marker before and after every agent3 test so the bare
   ``asyncio.run()`` calls in test_auto_analyze / test_round12 /
   test_round17 / test_warm_ui_watchdog could start. That marker is
   not stale: it is the live loop of the tests/snapshot_panels session
   browser, which Playwright's sync API keeps there between calls. Once
   an agent3 module ran in an xdist worker that already held that
   browser, the next snapshot test's first Playwright call never
   returned (LEDGER 2064, RM-1974 (c)). Those tests now drive their
   coroutines through ``tests._asyncio_isolation.run_coro`` (a fresh
   loop on its own thread), and tests/test_asyncio_isolation_guard.py
   fails on any marker write or bare ``asyncio.run()`` in this suite.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# RM-812: agents/_supervisor_common.py binds LOG_ROOT (logs/agents/) from this
# at IMPORT, so it is set here, before any test module imports the supervisor.
# The ephemeral-dispatch tests (test_supervisor_stub.py) otherwise appended
# agent6.log / task-<id>.log to the live logs/agents/. Mirrors tests/conftest.py.
# In a combined run with tests/, tests/conftest.py sets it unconditionally when
# it is imported, so its dir wins even if this one ran first; a module that
# bound LOG_ROOT before that keeps this dir. Both are tmp (RM-828 (e)).
# RM-828 (d): the dir this conftest creates (never a preset one) is removed at
# pytest_unconfigure and at interpreter exit.
_CREATED_LOG_DIR = None
if not (os.environ.get("RC_PHASE3_LOG_DIR") or "").strip():
    from tests import _suite_tmp_cleanup

    _CREATED_LOG_DIR = tempfile.mkdtemp(prefix="rc-agent3-agent-logs-")
    os.environ["RC_PHASE3_LOG_DIR"] = _CREATED_LOG_DIR
    _suite_tmp_cleanup.remove_dir_at_exit(_CREATED_LOG_DIR)


def pytest_unconfigure(config):
    if _CREATED_LOG_DIR is not None:
        from tests import _suite_tmp_cleanup

        _suite_tmp_cleanup.remove_dir(_CREATED_LOG_DIR)


@pytest.fixture(autouse=True)
def _stop_scheduler_compactors(monkeypatch):
    """RM-983: stop every agent1 Scheduler compactor thread a test starts
    (4 to 11 per file were left alive, some built by InputParser /
    UIFeedback for the caller). Mirrors tests/conftest.py."""
    from tests import _scheduler_compactor_guard
    started = _scheduler_compactor_guard.track(monkeypatch)
    yield
    _scheduler_compactor_guard.stop(started)


@pytest.fixture(autouse=True)
def _isolate_agent6_reports(tmp_path, monkeypatch):
    """L-03: FAILED stubs from failure-path tests must not land in the live
    agent6 reports dir."""
    from agents import _supervisor_ephemeral as se
    monkeypatch.setattr(se, "AGENT6_REPORTS_DIR", tmp_path / "agent6_reports")


@pytest.fixture(autouse=True)
def _fake_headless_route(monkeypatch, tmp_path_factory):
    """Fake open proxy route for the ephemeral-spawn stubs (operator contract
    2026-10-02; mirrors `fake_headless_route` in tests/conftest.py). Never the
    live URL, never a real probe or registry read."""
    from ops.loop import headless_env
    monkeypatch.setattr(headless_env, "_read_user_var", lambda name: "http://127.0.0.1:65530")
    monkeypatch.setattr(headless_env, "_probe", lambda host, port, timeout: None)
    monkeypatch.setattr(headless_env, "REFUSAL_LOG",
                        tmp_path_factory.getbasetemp() / "headless_route.log")
    # FLEET-KIT-v1: the spawn goes through ops/loop/fleet_route.py into the
    # vendored kit, which writes budget / status / usage under its root. A
    # fresh tmp root per test keeps the live ops/loop/control/ untouched and
    # the kit's run budget from carrying between tests; a fake exe keeps PATH
    # out of the verdict.
    from ops.loop import fleet_route
    monkeypatch.setattr(fleet_route, "ROOT", tmp_path_factory.mktemp("fleet_kit_root"))
    monkeypatch.setattr(fleet_route, "_exe_source", lambda: "claude-fake.exe")
    # MAIN 1327 item 1.1: production launches through the kit's own `_run`;
    # the stubs here patch `subprocess.run`, so forward the launch to it at
    # call time (mirrors tests/conftest.py).
    import subprocess as _sp

    monkeypatch.setattr(fleet_route, "_launch", lambda argv, **kw: _sp.run(argv, **kw))

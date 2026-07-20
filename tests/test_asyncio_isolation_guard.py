"""RM-100 follow-up guard: exactly ONE off-main-thread coroutine runner.

Five near-identical local ``_run_coro`` / ``_run_poll_loop`` copies had
accreted as a workaround for the snapshot_panels ProactorEventLoop marker
(see tests/_asyncio_isolation.py for the root cause). They are consolidated
into that module. This file fails if a sixth copy is hand-rolled instead of
imported, and pins the behaviour the callers depend on.
"""
from __future__ import annotations

import ast
import asyncio
import threading
from pathlib import Path

import pytest

from tests._asyncio_isolation import run_coro, run_coro_capturing_thread

_TESTS_DIR = Path(__file__).resolve().parent
_BANNED_LOCAL_RUNNERS = {"_run_coro", "_run_poll_loop"}


def test_no_local_coroutine_runner_copies_remain():
    """No test file re-defines a local off-thread coroutine runner.

    Import ``run_coro`` from tests._asyncio_isolation instead of hand-rolling
    a sixth copy.
    """
    offenders = []
    for path in sorted(_TESTS_DIR.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in _BANNED_LOCAL_RUNNERS:
                offenders.append(f"{path.relative_to(_TESTS_DIR)}:{node.lineno} {node.name}")
    assert not offenders, (
        "local coroutine-runner copies found - import run_coro from "
        "tests._asyncio_isolation instead:\n  " + "\n  ".join(offenders)
    )


def test_run_coro_returns_value_off_the_main_thread():
    main_ident = threading.get_ident()

    async def _work():
        return threading.get_ident()

    worker_ident = run_coro(_work())
    assert worker_ident != main_ident


def test_run_coro_reraises_worker_exception():
    """The isolation must not become a swallow - real failures still surface."""
    class _Boom(Exception):
        pass

    async def _work():
        raise _Boom("propagated")

    with pytest.raises(_Boom):
        run_coro(_work())


def test_run_coro_reraises_base_exception():
    """A non-Exception BaseException escapes `except Exception` and must
    still reach the caller (the shape test_lcu_loop_resilience pins)."""
    class _Boom(BaseException):
        pass

    async def _work():
        raise _Boom("propagated")

    with pytest.raises(_Boom):
        run_coro(_work())


def test_run_coro_times_out_on_a_hung_coroutine():
    async def _hang():
        await asyncio.Event().wait()

    with pytest.raises(TimeoutError):
        run_coro(_hang(), timeout=0.2)


def test_run_coro_capturing_thread_stamps_the_loop_thread():
    box: dict = {}

    async def _work():
        return threading.get_ident()

    inner = run_coro_capturing_thread(_work(), box)
    assert box["loop_thread"] == inner
    assert box["loop_thread"] != threading.get_ident()

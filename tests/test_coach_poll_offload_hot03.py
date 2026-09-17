"""HOT-03 (2026-07-09): coach _poll_loop offloads _poll_tick to a thread.

``coaches/_base_coach.py`` :: ``_poll_loop`` used to call ``self._poll_tick()``
synchronously on the shared AppLoop thread every 1.5s. _poll_tick does blocking
disk IO (load_json + safe_write, and safe_write has a time.sleep in its
PermissionError retry), so a Defender/AV lock race could stall the event loop.

The fix mirrors the existing ``_run_vision`` offload: ``await
asyncio.to_thread(self._poll_tick)``. These tests prove the tick now runs on a
worker thread (not the loop thread) and that _poll_loop routes through
asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from coaches import _base_coach
from coaches._base_coach import BaseCoach
from tests._asyncio_isolation import run_coro_capturing_thread


class _StubCoach(BaseCoach):
    _MODE_NAME = "aram"

    def _blank_artifact_data(self) -> dict:
        return {}

    def _parse_raw_state(self, raw: dict) -> dict:
        return raw

    def _run_coach(self, state: dict) -> None:
        pass

    def _run_vision(self) -> None:
        pass


def _bare_coach() -> _StubCoach:
    # __new__ skips __init__ so no poll/vision threads or Anthropic client spin
    # up; _poll_loop only touches _running + _poll_tick + _MODE_NAME.
    c = _StubCoach.__new__(_StubCoach)
    c._running = True
    return c


class _StopLoop(Exception):
    """Sentinel raised from the patched sleep to break the poll loop once."""


# RM-464: ``_base_coach.asyncio`` IS the process-wide asyncio module, so a bare
# ``_base_coach.asyncio.sleep = raiser`` makes EVERY coroutine in the process -
# any other thread's event loop included - raise _StopLoop on its next sleep
# (and a bare to_thread fake runs every other loop's blocking work inline). The
# fakes below are TASK-scoped: they act only when the current task is the one
# driving ``target`` (run_until_complete wraps the coroutine itself in a Task),
# and delegate to the real callable everywhere else.

def _task_scoped(target, fake, real):
    async def _shim(*a, **k):
        task = asyncio.current_task()
        if task is not None and task.get_coro() is target:
            return await fake(*a, **k)
        return await real(*a, **k)

    return _shim


def _assert_outside_control(real_to_thread_patched: bool) -> None:
    """Armed control, run INSIDE the patched window on a different task and a
    different loop thread: asyncio.sleep must really sleep (no _StopLoop) and,
    when to_thread is patched too, really offload to a worker thread."""
    async def _control():
        await asyncio.sleep(0)
        return await asyncio.to_thread(threading.get_ident)

    box: dict = {}
    try:
        worker = run_coro_capturing_thread(_control(), box)
    except _StopLoop as exc:  # pragma: no cover - only a widened fake gets here
        raise AssertionError("patched asyncio.sleep did not delegate outside the target task") from exc
    if real_to_thread_patched and worker == box["loop_thread"]:
        raise AssertionError("patched asyncio.to_thread did not delegate outside the target task")


def test_poll_tick_runs_off_the_loop_thread() -> None:
    coach = _bare_coach()
    box: dict = {}
    seen: dict = {}

    def _recording_tick() -> None:
        seen["tick_thread"] = threading.get_ident()

    # Shadow the method with a recorder; _poll_loop calls self._poll_tick.
    coach._poll_tick = _recording_tick  # type: ignore[method-assign]

    async def _fake_sleep(*_a, **_k):
        # End the loop after the first iteration (the tick has already run).
        raise _StopLoop

    target = coach._poll_loop()
    orig_sleep = _base_coach.asyncio.sleep
    _base_coach.asyncio.sleep = _task_scoped(target, _fake_sleep, orig_sleep)  # type: ignore[assignment]
    try:
        _assert_outside_control(real_to_thread_patched=False)
        with pytest.raises(_StopLoop):
            run_coro_capturing_thread(target, box)
    finally:
        _base_coach.asyncio.sleep = orig_sleep  # type: ignore[assignment]

    assert "tick_thread" in seen, "_poll_tick never executed"
    assert seen["tick_thread"] != box["loop_thread"], (
        "poll tick ran on the loop thread - the to_thread offload is gone"
    )


def test_poll_loop_routes_through_to_thread() -> None:
    coach = _bare_coach()
    called: dict = {}

    def _tick() -> None:
        called["ran"] = True

    coach._poll_tick = _tick  # type: ignore[method-assign]

    async def _fake_to_thread(fn, *args, **kwargs):
        called["target"] = fn
        return fn(*args, **kwargs)

    async def _fake_sleep(*_a, **_k):
        raise _StopLoop

    target = coach._poll_loop()
    orig_tt = _base_coach.asyncio.to_thread
    orig_sleep = _base_coach.asyncio.sleep
    _base_coach.asyncio.to_thread = _task_scoped(target, _fake_to_thread, orig_tt)  # type: ignore[assignment]
    _base_coach.asyncio.sleep = _task_scoped(target, _fake_sleep, orig_sleep)  # type: ignore[assignment]
    try:
        _assert_outside_control(real_to_thread_patched=True)
        with pytest.raises(_StopLoop):
            run_coro_capturing_thread(target, {})
    finally:
        _base_coach.asyncio.to_thread = orig_tt  # type: ignore[assignment]
        _base_coach.asyncio.sleep = orig_sleep  # type: ignore[assignment]

    assert called.get("ran") is True, "_poll_tick was not invoked"
    assert called.get("target") is coach._poll_tick, (
        "_poll_loop did not pass _poll_tick to asyncio.to_thread"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

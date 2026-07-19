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


def _run_poll_loop(coach: _StubCoach, box: dict) -> None:
    """Drive ``coach._poll_loop()`` on a dedicated thread.

    Records that thread's ident in ``box["loop_thread"]`` and re-raises the
    worker's exception on the caller, so ``pytest.raises`` still sees the
    _StopLoop sentinel.

    Why not a bare ``asyncio.run()`` on the main thread: the Playwright sync
    fixtures in ``tests/snapshot_panels`` (the only Playwright driver under
    tests/) leave a greenlet-backed ProactorEventLoop marked running on the
    MAIN thread for the rest of the session, because playwright.sync_api
    never clears the marker. ``asyncio.run()`` refuses to start when the
    calling thread already has a loop marked, so in a single-process full
    suite these two tests raised "asyncio.run() cannot be called from a
    running event loop" while passing alone - the nightly job runs `pytest
    tests/ agents/daemon_slayer/tests/` in ONE process, the push `check` job
    never does. The marker is NOT stale (clearing it from a conftest teardown
    hangs Playwright's next call), so the loop has to move off the main
    thread instead. This is the same immunity the three sibling asyncio-suite
    files already adopt for this exact polluter class (item 401, cycle-7 obs
    tests): tests/test_p2w1_core_f.py, tests/test_p2w2_ds_h.py and
    tests/test_lcu_loop_resilience.py, each via a local ``_run_coro``.

    Reading the loop thread's ident from INSIDE the worker keeps the
    off-the-loop-thread assertion honest: comparing the tick thread against
    the main thread would pass even if the to_thread offload were deleted.
    """
    def _worker() -> None:
        box["loop_thread"] = threading.get_ident()
        try:
            asyncio.run(coach._poll_loop())
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            box["err"] = exc

    t = threading.Thread(target=_worker)
    t.start()
    t.join()
    if "err" in box:
        raise box["err"]


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

    orig_sleep = _base_coach.asyncio.sleep
    _base_coach.asyncio.sleep = _fake_sleep  # type: ignore[assignment]
    try:
        with pytest.raises(_StopLoop):
            _run_poll_loop(coach, box)
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

    orig_tt = _base_coach.asyncio.to_thread
    orig_sleep = _base_coach.asyncio.sleep
    _base_coach.asyncio.to_thread = _fake_to_thread  # type: ignore[assignment]
    _base_coach.asyncio.sleep = _fake_sleep  # type: ignore[assignment]
    try:
        with pytest.raises(_StopLoop):
            _run_poll_loop(coach, {})
    finally:
        _base_coach.asyncio.to_thread = orig_tt  # type: ignore[assignment]
        _base_coach.asyncio.sleep = orig_sleep  # type: ignore[assignment]

    assert called.get("ran") is True, "_poll_tick was not invoked"
    assert called.get("target") is coach._poll_tick, (
        "_poll_loop did not pass _poll_tick to asyncio.to_thread"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

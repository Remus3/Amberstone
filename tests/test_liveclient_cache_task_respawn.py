"""Regression: the liveclient_cache async poll task must self-heal after it ends.

Root cause of the recurring "overlay stays on the dashboard in-game" bug: when RC
restarts mid-game, the AppLoop-spawned ``_loop_async`` poll task can be cancelled /
end, and the module left ``_task`` pointing at the finished task forever. Both the
idempotent guard in ``start()`` and the auto-start in ``get()`` keyed off
``_task is not None``, so a finished-but-non-None task blocked EVERY respawn: the
cache froze at its last ``_snapshot``, ``Snapshot.age_s`` grew past the 5s bound,
``dashboard._liveclient.liveclient_summary()`` collapsed to ``{}``, and the Electron
view-router (which flips to the in-game overlay only when ``liveclient`` is present)
never left the dashboard even though Riot's :2999 was serving full game data.

The fix treats a finished task as dead: ``start()`` / ``get()`` respawn it, and a
done-callback clears ``_task`` when the loop ends. These tests pin that self-heal
with a fake task (no real event loop), plus the guard semantics.
"""
from __future__ import annotations

import unittest

from core import liveclient_cache as lc


class _FakeTask:
    """Stand-in for the asyncio.Task returned by AppLoop.spawn_task."""

    def __init__(self, done: bool = True, cancelled: bool = False, exc=None) -> None:
        self._done = done
        self._cancelled = cancelled
        self._exc = exc
        self.cancel_called = False
        self.callback = None

    def done(self) -> bool:
        return self._done

    def cancelled(self) -> bool:
        return self._cancelled

    def exception(self):
        if self._cancelled:
            raise AssertionError("exception() on a cancelled task raises in asyncio")
        return self._exc

    def cancel(self) -> None:
        self.cancel_called = True

    def add_done_callback(self, cb) -> None:
        self.callback = cb


class _FakeSched:
    """Fake AppLoop: records spawn_task calls, closes the coro, returns a live task."""

    def __init__(self) -> None:
        self.spawned = 0
        self.last_task = None

    def spawn_task(self, coro):
        self.spawned += 1
        try:
            coro.close()  # avoid "coroutine was never awaited" warning
        except Exception:  # noqa: BLE001
            pass
        self.last_task = _FakeTask(done=False)  # a fresh, ALIVE task
        return self.last_task


class _TaskRespawnBase(unittest.TestCase):
    def setUp(self) -> None:
        # Snapshot + restore module globals so tests never leak into the real cache.
        self._saved = (lc._task, lc._thread)
        lc._task = None
        lc._thread = None
        lc._stop.clear()

    def tearDown(self) -> None:
        lc._task, lc._thread = self._saved
        lc._stop.clear()


class TaskAliveSemantics(_TaskRespawnBase):
    def test_none_task_is_not_alive(self) -> None:
        lc._task = None
        self.assertFalse(lc._task_alive())

    def test_running_task_is_alive(self) -> None:
        lc._task = _FakeTask(done=False)
        self.assertTrue(lc._task_alive())

    def test_finished_task_is_not_alive(self) -> None:
        # The exact freeze condition: a done task must read as dead.
        lc._task = _FakeTask(done=True)
        self.assertFalse(lc._task_alive())


class StartRespawnsFinishedTask(_TaskRespawnBase):
    def test_start_early_returns_on_a_live_task(self) -> None:
        sched = _FakeSched()
        lc._task = _FakeTask(done=False)
        with _patched_loop(sched):
            lc.start()
        self.assertEqual(sched.spawned, 0, "must not respawn a still-running task")

    def test_start_respawns_a_finished_task(self) -> None:
        # REGRESSION: pre-fix start() early-returned because _task was non-None.
        sched = _FakeSched()
        lc._task = _FakeTask(done=True)
        with _patched_loop(sched):
            lc.start()
        self.assertEqual(sched.spawned, 1, "a finished task must be respawned")
        self.assertIs(lc._task, sched.last_task)
        self.assertTrue(lc._task_alive())

    def test_start_registers_done_callback(self) -> None:
        sched = _FakeSched()
        lc._task = None
        with _patched_loop(sched):
            lc.start()
        self.assertIsNotNone(sched.last_task.callback, "done-callback must be wired")


class GetRespawnsFinishedTask(_TaskRespawnBase):
    def test_get_respawns_when_task_finished(self) -> None:
        # REGRESSION: pre-fix get() only restarted when _task was None.
        sched = _FakeSched()
        lc._task = _FakeTask(done=True)
        with _patched_loop(sched):
            lc.get()
        self.assertEqual(sched.spawned, 1)
        self.assertTrue(lc._task_alive())


class DoneCallbackClearsTask(_TaskRespawnBase):
    def test_callback_clears_current_task(self) -> None:
        fake = _FakeTask(done=True)
        lc._task = fake
        lc._on_task_done(fake)
        self.assertIsNone(lc._task, "the finished task must be cleared so get() respawns")

    def test_callback_does_not_clear_a_newer_task(self) -> None:
        # If start() already respawned, the OLD task's callback must not null the new one.
        old = _FakeTask(done=True)
        new = _FakeTask(done=False)
        lc._task = new
        lc._on_task_done(old)
        self.assertIs(lc._task, new)

    def test_callback_tolerates_cancelled_task(self) -> None:
        # A cancelled task (the mid-game RC-restart path) must not raise in the callback.
        cancelled = _FakeTask(done=True, cancelled=True)
        lc._task = cancelled
        lc._on_task_done(cancelled)  # must not raise
        self.assertIsNone(lc._task)


def _patched_loop(sched):
    """Context manager patching app._loop.get_loop to return the fake scheduler.

    start() imports get_loop lazily from app._loop, so patch it there.
    """
    import contextlib
    import app._loop as loop_mod

    @contextlib.contextmanager
    def _cm():
        orig = loop_mod.get_loop
        loop_mod.get_loop = lambda: sched
        try:
            yield
        finally:
            loop_mod.get_loop = orig

    return _cm()


if __name__ == "__main__":
    unittest.main()

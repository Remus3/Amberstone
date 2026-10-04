"""RM-198: BaseCoachWorker lifecycle failures must be OBSERVABLE.

(a) restart() while the old thread will not exit used to return silently and
    rebind self._thread, so is_alive() / health_pulse() only ever saw the new
    generation and the wedged one became invisible.
(b) _run_safe logged a crash and recorded nothing, so health_pulse() of a dead
    worker carried no error field and read healthy apart from a stale pulse.

Spies here RECORD; none raises an AssertionError inside _run, because
_run_safe catches Exception and a raising spy would pass either way.
"""

import threading

from core.base_worker import BaseCoachWorker


class _Wedged(BaseCoachWorker):
    """_run blocks on a test-controlled Event and ignores stop + generation."""

    _restart_join_timeout_s = 0.05

    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self.entered = []

    def _run(self, my_gen):
        self.entered.append(my_gen)
        self.release.wait(5.0)


class _Crashing(BaseCoachWorker):
    def _run(self, my_gen):
        raise RuntimeError(f"boom-{my_gen}")


def test_restart_surfaces_a_stranded_generation():
    w = _Wedged()
    w.start()
    old = w._thread
    try:
        w.restart()
        pulse = w.health_pulse()
        assert old.is_alive(), "precondition: the old generation is wedged"
        assert pulse["generation"] == 2
        assert pulse["stranded_generations"] == [1]
    finally:
        w.release.set()
        w.stop()
        w.join(2.0)
        old.join(2.0)


def test_clean_restart_strands_nothing():
    # Positive control: a generation that exits on stop is not reported.
    class _Polite(BaseCoachWorker):
        def _run(self, my_gen):
            self._stop_event.wait(5.0)

    w = _Polite()
    w.start()
    old = w._thread
    w.restart()
    old.join(2.0)
    try:
        assert w.health_pulse()["stranded_generations"] == []
    finally:
        w.stop()
        w.join(2.0)


def test_stranded_generation_clears_once_it_finally_exits():
    w = _Wedged()
    w.start()
    old = w._thread
    w.restart()
    assert w.health_pulse()["stranded_generations"] == [1]
    w.release.set()
    old.join(2.0)
    w.join(2.0)
    assert w.health_pulse()["stranded_generations"] == []


def test_crash_is_recorded_in_health_pulse():
    w = _Crashing()
    before = w.health_pulse()
    assert before["crash_count"] == 0
    assert before["last_error"] is None
    w.start()
    w.join(2.0)
    pulse = w.health_pulse()
    assert pulse["alive"] is False
    assert pulse["crash_count"] == 1
    assert "boom-1" in pulse["last_error"]
    assert pulse["died_ts"] > 0.0


def test_lifecycle_surface_is_unchanged():
    # Frozen callers (app/_remediation.py, app/_game_lifecycle.py) use these.
    for name in ("start", "stop", "restart", "join", "is_alive", "pulse_ts"):
        assert hasattr(BaseCoachWorker, name)
    keys = set(_Crashing().health_pulse())
    assert {"alive", "generation", "pulse_ts", "last_success_ts"} <= keys

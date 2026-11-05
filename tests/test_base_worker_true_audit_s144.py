"""s144 true-audit cycle 65: core/base_worker.py lifecycle hardening.

F1 start() over a still-running generation rebound self._thread and recorded
   nothing, so a wedged previous generation was invisible (the RM-198 class,
   reached through start() instead of restart(); _game_lifecycle.start_game_poll
   calls start() on every game).
F2 start() incremented and re-read self._generation without a lock, so two
   concurrent start() calls could both read the same generation and spawn two
   threads that each believe they are current - neither is ever superseded.
F3 restart() called from inside the worker's own thread joined the current
   thread: RuntimeError, no new generation started.
F4 SystemExit out of _run escaped _run_safe; threading.excepthook ignores
   SystemExit silently, so the worker died with no log and no crash record.
F5 last_success_ts took any value; the RM-357 monotonic-clock guard covered
   pulse_ts only, so a wall-clock success stamp reached health.json.
F6 an exception whose str() raises made _run_safe's own handler raise: the
   crash was counted but last_error / died_ts stayed unset and no log line was
   written.

Spies here RECORD; none raises an AssertionError inside _run, because
_run_safe catches the exception and a raising spy would pass either way.
"""

import logging
import threading
import time

from core.base_worker import BaseCoachWorker
from tests._timing_budget import fleet_test_guard


class _Wedged(BaseCoachWorker):
    """_run blocks on a test-controlled Event and ignores stop + generation."""

    _restart_join_timeout_s = 0.05

    def __init__(self):
        super().__init__()
        self.release = threading.Event()

    def _run(self, my_gen):
        self.release.wait(5.0)


class _Polite(BaseCoachWorker):
    def _run(self, my_gen):
        while not self._stop_event.is_set() and my_gen == self._generation:
            self._stop_event.wait(0.01)


# -- F1 ---------------------------------------------------------------------

def test_start_over_a_live_generation_surfaces_it_as_stranded():
    w = _Wedged()
    w.start()
    old = w._thread
    try:
        w.start()
        assert old.is_alive(), "precondition: generation 1 is wedged"
        pulse = w.health_pulse()
        assert pulse["generation"] == 2
        assert pulse["stranded_generations"] == [1]
    finally:
        w.release.set()
        w.stop()
        w.join(2.0)
        old.join(2.0)
    assert w.health_pulse()["stranded_generations"] == []


def test_start_after_the_old_generation_exited_strands_nothing():
    # Positive control for F1: a finished thread is not reported.
    w = _Polite()
    w.start()
    old = w._thread
    w.stop()
    old.join(2.0)
    w.start()
    try:
        assert w.health_pulse()["stranded_generations"] == []
    finally:
        w.stop()
        w.join(2.0)


# -- F2 ---------------------------------------------------------------------

class _RacyGen(_Polite):
    """Widens the read-modify-write window on `_generation`.

    Every read of `_generation` by a starter thread waits (bounded) for the
    other starter to reach a read too, so without a lifecycle lock both
    starters read the same value before either stores the bump. With the lock
    the second starter cannot enter start() until the first has finished, so
    the first wait times out (breaking the barrier) and both proceed in turn.
    Worker threads reading `_generation` never touch the barrier.
    """

    def __init__(self):
        self._both = threading.Barrier(2, timeout=0.3)
        super().__init__()

    @property
    def _generation(self):
        value = self.__dict__.get("_gen_value", 0)
        if threading.current_thread().name.startswith("starter-"):
            # Read FIRST, then wait: both starters hold the same stale value.
            try:
                self._both.wait()
            except threading.BrokenBarrierError:
                pass
        return value

    @_generation.setter
    def _generation(self, value):
        self.__dict__["_gen_value"] = value


def test_concurrent_starts_never_share_a_generation():
    w = _RacyGen()
    spawned = []
    real_thread = threading.Thread

    def _spy(*args, **kwargs):
        t = real_thread(*args, **kwargs)
        spawned.append(kwargs.get("args"))
        return t

    starters = [
        real_thread(target=w.start, name=f"starter-{i}") for i in range(2)
    ]
    threading.Thread = _spy
    try:
        for s in starters:
            s.start()
        for s in starters:
            s.join(5.0)
    finally:
        threading.Thread = real_thread
        w.stop()
    gens = sorted(a[0] for a in spawned)
    assert gens == [1, 2], f"two starts must own two generations, got {gens}"


# -- F3 ---------------------------------------------------------------------

class _SelfRestarting(BaseCoachWorker):
    _restart_join_timeout_s = 0.05

    def __init__(self):
        super().__init__()
        self.ran = []

    def _run(self, my_gen):
        self.ran.append(my_gen)
        if my_gen == 1:
            self.restart()
            return
        self._stop_event.wait(5.0)


def test_restart_from_inside_the_worker_starts_the_next_generation():
    w = _SelfRestarting()
    w.start()
    deadline = time.monotonic() + fleet_test_guard.budget(3.0)
    while 2 not in w.ran and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        assert w.ran[:2] == [1, 2]
        pulse = w.health_pulse()
        assert pulse["crash_count"] == 0, pulse["last_error"]
        assert pulse["generation"] == 2
        assert pulse["alive"] is True
    finally:
        w.stop()
        w.join(2.0)


# -- F4 ---------------------------------------------------------------------

class _Exits(BaseCoachWorker):
    def _run(self, my_gen):
        raise SystemExit(3)


def test_system_exit_out_of_run_is_recorded_and_logged(caplog):
    w = _Exits()
    with caplog.at_level(logging.ERROR, logger="rc.base_worker"):
        w.start()
        w.join(2.0)
    pulse = w.health_pulse()
    assert pulse["alive"] is False
    assert pulse["crash_count"] == 1
    assert "SystemExit" in pulse["last_error"]
    assert pulse["died_ts"] > 0.0
    assert any("gen=1" in r.getMessage() for r in caplog.records)


# -- F5 ---------------------------------------------------------------------

def test_wall_clock_last_success_reads_as_never():
    w = _Polite()
    w.last_success_ts = time.time()
    assert w.health_pulse()["last_success_ts"] == 0.0


def test_monotonic_last_success_is_kept():
    w = _Polite()
    stamp = time.monotonic()
    w.last_success_ts = stamp
    assert w.health_pulse()["last_success_ts"] == stamp


def test_junk_last_success_reads_as_never():
    w = _Polite()
    for junk in (None, "abc", float("nan"), float("inf"), -1.0):
        w.last_success_ts = junk
        assert w.last_success_ts == 0.0, junk


# -- F6 ---------------------------------------------------------------------

class _Unprintable(Exception):
    def __str__(self):
        raise ValueError("no text")


class _CrashesUnprintably(BaseCoachWorker):
    def _run(self, my_gen):
        raise _Unprintable


def test_unprintable_exception_still_records_the_crash(caplog):
    w = _CrashesUnprintably()
    with caplog.at_level(logging.ERROR, logger="rc.base_worker"):
        w.start()
        w.join(2.0)
    pulse = w.health_pulse()
    assert pulse["crash_count"] == 1
    assert pulse["last_error"] is not None
    assert "_Unprintable" in pulse["last_error"]
    assert pulse["died_ts"] > 0.0
    assert any("crashed" in r.getMessage() for r in caplog.records)


def test_last_error_stays_capped():
    class _Long(BaseCoachWorker):
        def _run(self, my_gen):
            raise RuntimeError("x" * 5000)

    w = _Long()
    w.start()
    w.join(2.0)
    assert len(w.health_pulse()["last_error"]) <= 300

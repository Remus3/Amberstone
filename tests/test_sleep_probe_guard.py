"""Guard: the sleep probe must be thread-scoped, and stay that way.

Locks the fix for the 2026-08-01 CI failure where
`test_retries_permissionerror_twice_then_succeeds` asserted
``mock_sleep.call_count == 2`` against an implementation hard-bounded at 2 and
CI observed **21378**. Root cause: a module doing ``import time`` shares the ONE
global time module, so ``patch("mod.time.sleep")`` is process-wide and every
thread's sleep is tallied.

These tests fail if anyone reverts `record_sleeps` to a bare global mock.
"""
from __future__ import annotations

import threading
import time

from tests._sleep_probe import record_sleeps, thread_scoped


class TestRecordSleepsIsThreadScoped:
    def test_records_calling_thread_sleeps(self):
        with record_sleeps() as sleeps:
            time.sleep(0.06)
            time.sleep(0.06)
        assert sleeps == [0.06, 0.06]

    def test_does_not_record_other_threads(self):
        """THE regression. A background thread must not enter the list."""
        started = threading.Event()
        stop = threading.Event()

        def busy():
            started.set()
            while not stop.is_set():
                time.sleep(0.001)

        t = threading.Thread(target=busy, daemon=True)
        with record_sleeps() as sleeps:
            t.start()
            started.wait(timeout=2)
            # Let the background thread iterate many times. Under the old bare
            # mock this alone drove the count into the thousands.
            threading.Event().wait(0.25)
            stop.set()
            t.join(timeout=2)
            observed = list(sleeps)

        assert observed == [], f"background thread leaked into the probe: {observed[:5]}"

    def test_other_threads_get_a_real_sleep_not_a_busy_spin(self):
        """The old mock returned instantly for every thread, so background
        loops span. Passing through to the real sleep is what keeps the count
        from exploding - and what makes the leak non-destructive."""
        elapsed = []

        def timed():
            start = time.perf_counter()
            time.sleep(0.05)
            elapsed.append(time.perf_counter() - start)

        t = threading.Thread(target=timed, daemon=True)
        with record_sleeps():
            t.start()
            t.join(timeout=2)

        assert elapsed, "worker thread did not finish"
        assert elapsed[0] >= 0.02, (
            f"other thread was short-circuited ({elapsed[0]:.4f}s) - it should "
            "receive the real time.sleep"
        )

    def test_restores_time_sleep(self):
        real = time.sleep
        with record_sleeps():
            assert time.sleep is not real
        assert time.sleep is real

    def test_restores_even_on_exception(self):
        real = time.sleep
        try:
            with record_sleeps():
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert time.sleep is real


class TestThreadScoped:
    def test_calling_thread_gets_the_side_effect(self):
        wrapped = thread_scoped(lambda a: f"fault:{a}", lambda a: f"real:{a}")
        assert wrapped("x") == "fault:x"

    def test_other_thread_gets_the_passthrough(self):
        wrapped = thread_scoped(lambda a: f"fault:{a}", lambda a: f"real:{a}")
        out = []
        t = threading.Thread(target=lambda: out.append(wrapped("x")), daemon=True)
        t.start()
        t.join(timeout=2)
        assert out == ["real:x"], "fault injector escaped into another thread"

    def test_raising_side_effect_does_not_escape_the_thread(self):
        def always_fail(src, dst):
            raise PermissionError("always")

        wrapped = thread_scoped(always_fail, lambda src, dst: "ok")
        out = []
        t = threading.Thread(target=lambda: out.append(wrapped("a", "b")), daemon=True)
        t.start()
        t.join(timeout=2)
        assert out == ["ok"], "PermissionError injector leaked into another thread"

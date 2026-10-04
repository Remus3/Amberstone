r"""RM-369: the two `main()` argument tests must pass WITH a live driver
holding `Global\RC_QUEUE_LOOP_DRIVER`, and a SEPARATE test must still prove
`main()` refuses when that mutex is held.

The seam fix (`singleton=contextlib.nullcontext`) already landed in
tests/test_queue_loop.py; this file supplies the acceptance's missing proof:
the real mutex is HELD (from another thread - Windows mutexes are recursive
per thread, so a same-thread hold would prove nothing) for the duration of
each assertion. If a real lane-10 driver already holds it, the precondition
is met by that driver instead. Windows-only: winmutex fails open elsewhere.
"""
from __future__ import annotations

import contextlib
import importlib
import sys
import threading

import pytest

qloop = importlib.import_module("ops.loop.queue_loop")

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="named mutexes are Windows-only")


@contextlib.contextmanager
def _driver_mutex_held():
    """Hold DRIVER_MUTEX from a helper thread until the block exits."""
    acquired = threading.Event()
    release = threading.Event()
    state = {}

    def _holder():
        try:
            with qloop.winmutex.hold(qloop.DRIVER_MUTEX, timeout=0.0):
                state["mine"] = True
                acquired.set()
                release.wait(30)
        except qloop.winmutex.MutexTimeout:
            state["mine"] = False      # a live driver already holds it
            acquired.set()

    t = threading.Thread(target=_holder, daemon=True)
    t.start()
    assert acquired.wait(10), "holder thread never reported"
    try:
        yield state
    finally:
        release.set()
        t.join(10)


def _fake_run_loop(seen):
    def run_loop(**kw):
        seen.update(kw)
        return {"cycles_run": 0, "stopped_by": "max_cycles", "records": []}
    return run_loop


def test_main_refuses_while_the_real_mutex_is_held(monkeypatch):
    seen = {}
    monkeypatch.setattr(qloop, "run_loop", _fake_run_loop(seen))
    with _driver_mutex_held():
        rc = qloop.main(["--once"])          # REAL singleton, no seam
    assert rc == qloop.EXIT_ALREADY_RUNNING
    assert seen == {}, "a refused driver must not reach run_loop"


def test_argument_tests_pass_with_a_live_holder(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(qloop, "run_loop", _fake_run_loop(seen))
    with _driver_mutex_held():
        rc = qloop.main(["--cycles", "3", "--settle", "7",
                         "--control-dir", str(tmp_path / "c"),
                         "--reports-dir", str(tmp_path / "r")],
                        singleton=contextlib.nullcontext)
        assert rc == 0
        assert seen["max_cycles"] == 3
        seen.clear()
        assert qloop.main(["--once", "--cycles", "50"],
                          singleton=contextlib.nullcontext) == 0
        assert seen["max_cycles"] == 1

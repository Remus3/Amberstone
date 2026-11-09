"""tests/test_resource_manager_hardening_s144.py

Lane-8 (true-audit) hardening of core/resource_manager.py, s144 cycle 221.

F1 deadlock: the SIGINT / SIGTERM handler runs shutdown() on the main
   thread, and shutdown() takes self._lock. With a plain Lock, a signal that
   lands while the main thread is inside register() / set_remediation_hook()
   (both called on the main thread by main.py) blocks forever on Ctrl+C or a
   console close.
F2 a failed RSS probe read as healthy: _rss_mb() returned 0.0 when it could
   not measure, and 0.0 is "below the limit", so a broken probe silently
   wiped a sustained-breach streak and logged "Memory: 0 MB" forever. A
   non-finite or negative sample also reached the gate, and NaN counted as a
   BREACH (nan <= limit is False), so garbage could arm a restart.
F3 a watchdog that cannot measure was silent: probe errors were logged at
   DEBUG, below the live INFO level.
F4 the watchdog outlived shutdown(): it slept a whole interval (60 s live)
   before noticing, and a sustained breach could still fire the remediation
   hook (restart_game_poll) in the middle of teardown.
F5 the module docstring still recited the pre-RM-146 300 / 500 MB ceilings
   and claimed the hook was never wired (main.py wires it).

Every test runs without a live RC: hooks are stubs, RSS is stubbed.
"""
from __future__ import annotations

import logging
import math
import signal
import sys
import threading
import time
from pathlib import Path

import pytest

import core.resource_manager as rmod
from tests._timing_budget import fleet_test_guard
from core.resource_manager import (
    ResourceManager,
    _LIMIT_MB,
    _MEM_SUSTAINED_SAMPLES,
    _WARN_MB,
)


@pytest.fixture(autouse=True)
def _restore_signal_handlers():
    """ResourceManager installs process-wide SIGINT / SIGTERM handlers;
    put pytest's back so a later Ctrl+C is not routed to a dead instance."""
    prev = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    yield
    for s, h in prev.items():
        signal.signal(s, h)


@pytest.fixture
def rm(tmp_path: Path) -> ResourceManager:
    inst = ResourceManager(tmp_path)
    yield inst
    inst._shutdown_done = True


# -- F1: shutdown re-entered on the thread that holds the lock ---------------

def test_shutdown_reentered_while_lock_held_does_not_deadlock(rm):
    """What the signal handler does when SIGINT lands inside register()."""
    done = threading.Event()

    def _body():
        with rm._lock:          # main thread mid-register()
            rm.shutdown()       # signal handler -> shutdown() on same thread
        done.set()

    t = threading.Thread(target=_body, daemon=True, name="s144-reentry")
    t.start()
    assert done.wait(fleet_test_guard.budget(5.0)), "shutdown() deadlocked on its own lock"
    assert rm._shutdown_done is True


def test_signal_handler_inside_register_completes(rm):
    """End to end through _signal_handler: it shuts down and exits 0."""
    result: dict = {}

    def _body():
        with rm._lock:
            try:
                rm._signal_handler(signal.SIGINT, None)
            except SystemExit as exc:
                result["code"] = exc.code

    t = threading.Thread(target=_body, daemon=True, name="s144-sig")
    t.start()
    t.join(fleet_test_guard.budget(5.0))
    assert not t.is_alive(), "signal handler deadlocked inside register()"
    assert result.get("code") == 0


def test_construction_off_main_thread_does_not_raise(tmp_path):
    """signal.signal raises ValueError off the main thread; must degrade."""
    box: dict = {}

    def _body():
        try:
            box["rm"] = ResourceManager(tmp_path)
        except Exception as exc:  # noqa: BLE001 - the assertion target
            box["exc"] = exc

    t = threading.Thread(target=_body, name="s144-ctor")
    t.start()
    t.join(fleet_test_guard.budget(5.0))
    assert "exc" not in box, box.get("exc")
    box["rm"]._shutdown_done = True


# -- F2: a failed or garbage sample is NOT a healthy sample ------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, None])
def test_garbage_sample_never_arms_or_fires(rm, bad):
    calls: list[int] = []
    rm.set_remediation_hook(lambda: calls.append(1) or {"ok": True})
    for _ in range(_MEM_SUSTAINED_SAMPLES * 3):
        assert rm._mem_remediation_step(bad) is False
    assert calls == []
    assert rm._mem_breach_streak == 0


def test_garbage_sample_does_not_wipe_a_real_streak(rm):
    """A probe that could not measure says nothing about memory: it must
    neither advance nor reset a streak of real breaches."""
    calls: list[int] = []
    rm.set_remediation_hook(lambda: calls.append(1) or {"ok": True})
    over = _LIMIT_MB + 80.0
    for _ in range(_MEM_SUSTAINED_SAMPLES - 1):
        rm._mem_remediation_step(over)
    rm._mem_remediation_step(float("nan"))
    rm._mem_remediation_step(None)
    assert rm._mem_breach_streak == _MEM_SUSTAINED_SAMPLES - 1
    assert rm._mem_remediation_step(over) is True
    assert calls == [1]


@pytest.mark.skipif(sys.platform != "win32", reason="ctypes psapi fallback")
def test_rss_probe_failure_returns_none_not_zero(monkeypatch):
    """psutil absent and GetProcessMemoryInfo failing must read as UNKNOWN."""
    import ctypes

    class _FailingPsapi:
        @staticmethod
        def GetProcessMemoryInfo(*_a):  # the Win32 export name
            return 0  # FALSE: the call failed, the struct is untouched

    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(ctypes.windll, "psapi", _FailingPsapi(), raising=False)
    assert ResourceManager._rss_mb() is None


@pytest.mark.skipif(sys.platform != "win32", reason="ctypes psapi fallback")
def test_rss_ctypes_fallback_still_measures(monkeypatch):
    """Positive control for the test above: the real fallback reads > 0."""
    monkeypatch.setitem(sys.modules, "psutil", None)
    val = ResourceManager._rss_mb()
    assert isinstance(val, float) and math.isfinite(val) and val > 0.0


def test_rss_psutil_path_measures():
    val = ResourceManager._rss_mb()
    assert isinstance(val, float) and val > 0.0


# -- F3: an unmeasurable watchdog is visible at the live INFO level ----------

def test_unmeasurable_sample_logs_a_warning_once_per_outage(rm, caplog,
                                                            monkeypatch):
    seen: list = []
    real_step = rm._mem_remediation_step

    def _counting_step(v):
        seen.append(v)
        return real_step(v)

    monkeypatch.setattr(rm, "_mem_remediation_step", _counting_step)
    monkeypatch.setattr(rm, "_rss_mb", lambda: None)
    with caplog.at_level(logging.INFO, logger="rc.resources"):
        for _ in range(4):
            rm._watchdog_tick()
    warns = [r for r in caplog.records
             if r.levelno >= logging.WARNING and "unmeasur" in r.message.lower()]
    assert len(warns) == 1, [r.message for r in caplog.records]
    assert seen == [], "an unknown sample must not reach the gate"


def test_probe_exception_logs_a_warning(rm, caplog, monkeypatch):
    def _boom():
        raise OSError("access denied")

    monkeypatch.setattr(rm, "_rss_mb", _boom)
    with caplog.at_level(logging.INFO, logger="rc.resources"):
        rm._watchdog_tick()
        rm._watchdog_tick()
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warns) == 1
    assert "OSError" in warns[0].getMessage()


def test_recovery_after_outage_is_logged_and_rearms(rm, caplog, monkeypatch):
    values = iter([None, None, _WARN_MB - 10.0, None])
    monkeypatch.setattr(rm, "_rss_mb", lambda: next(values))
    with caplog.at_level(logging.INFO, logger="rc.resources"):
        for _ in range(4):
            rm._watchdog_tick()
    warns = [r for r in caplog.records
             if r.levelno >= logging.WARNING and "unmeasur" in r.message.lower()]
    # Two separate outages -> two warnings; one recovery line between them.
    assert len(warns) == 2
    assert any("measurable again" in r.message for r in caplog.records)


# -- F4: shutdown stops the watchdog promptly and disarms remediation --------

def test_shutdown_wakes_and_stops_the_watchdog(tmp_path, monkeypatch):
    rm = ResourceManager(tmp_path)
    monkeypatch.setattr(rm, "_rss_mb", lambda: 100.0)
    rm.start_memory_watchdog(interval_s=30.0)
    wd = rm._watchdog
    assert wd is not None and wd.is_alive()
    time.sleep(0.2)  # let it enter its interval wait
    t0 = time.monotonic()
    rm.shutdown()
    # Capped under the unfixed 30 s interval, so a widened bound still tells fixed from broken.
    wd.join(min(fleet_test_guard.budget(5.0), 25.0))
    assert not wd.is_alive(), "watchdog still sleeping out its 30 s interval"
    assert time.monotonic() - t0 < min(fleet_test_guard.budget(5.0), 25.0)


def test_no_remediation_after_shutdown(rm):
    calls: list[int] = []
    rm.set_remediation_hook(lambda: calls.append(1) or {"ok": True})
    rm.shutdown()
    for _ in range(_MEM_SUSTAINED_SAMPLES * 2):
        assert rm._mem_remediation_step(_LIMIT_MB + 300.0) is False
    assert calls == []


def test_watchdog_tick_still_feeds_the_gate_post_gc(rm, monkeypatch):
    """Characterization kept from the old loop: a breach sample is followed
    by gc and the POST-GC reading is what the gate sees."""
    readings = iter([_LIMIT_MB + 200.0, _LIMIT_MB + 150.0])
    seen: list = []
    monkeypatch.setattr(rm, "_rss_mb", lambda: next(readings))
    monkeypatch.setattr(rm, "_mem_remediation_step",
                        lambda v: seen.append(v) or False)
    rm._watchdog_tick()
    assert seen == [_LIMIT_MB + 150.0]


# -- F5: the docstring states the live thresholds ----------------------------

def test_module_docstring_states_live_thresholds():
    doc = rmod.__doc__ or ""
    assert f"{_WARN_MB} MB" in doc
    assert f"{_LIMIT_MB} MB" in doc
    assert "300 MB" not in doc and "500 MB" not in doc
    assert "stays None until something wires it" not in doc

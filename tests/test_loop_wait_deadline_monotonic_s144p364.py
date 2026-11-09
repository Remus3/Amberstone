"""S144-P-364 - the loop's file-wait seam measures its deadline on the monotonic clock.

``ops/loop/loop_controller.py`` ``wait_for`` / ``wait_gone`` poll for a handshake file until a deadline, and
``ops/loop/executor.py`` (ahk channel) builds that deadline: 120 s for the AHK bridge to type the directive and
``cycle_deadline_sec`` (5400 s by default) for ``claude.done``. Both ends measured it on ``time.time()``, so a
system clock step (NTP correction, manual change, VM resume) cut a 90-minute cycle wait short or stretched a
120 s one for hours. The seam is now ``time.monotonic()`` at both ends, changed together (the two ends share
the deadline value, so converting one alone would compare an epoch against an uptime).

Measured 2026-11-08 on the old code: with the wall clock stepped back to 0.0, ``wait_for`` on an already
expired deadline polled until the harness killed it; with it stepped forward a far-future one returned at once.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class _SteppedClock:
    """The real ``time`` module with ``time.time()`` pinned (a stepped system clock) and ``sleep`` counted."""

    def __init__(self, wall: float, max_sleeps: int = 50):
        self._wall = wall
        self.sleeps = 0
        self._max = max_sleeps

    def time(self) -> float:
        return self._wall

    def sleep(self, _s: float) -> None:
        self.sleeps += 1
        if self.sleeps > self._max:
            raise AssertionError("the wait kept polling: its deadline is read from the stepped wall clock")

    def __getattr__(self, name):
        return getattr(time, name)


@pytest.fixture
def lc(monkeypatch, tmp_path):
    mod = importlib.import_module("ops.loop.loop_controller")
    monkeypatch.setattr(mod, "log", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "CTL", tmp_path)
    monkeypatch.setitem(mod.CFG, "poll_sec", 0)
    return mod


def test_wait_for_expires_on_the_monotonic_deadline_when_the_wall_clock_steps_back(lc, monkeypatch, tmp_path):
    clock = _SteppedClock(wall=0.0)
    monkeypatch.setattr(lc, "time", clock)
    assert lc.wait_for(tmp_path / "never", time.monotonic() - 1.0) is False
    assert clock.sleeps == 0


def test_wait_gone_expires_on_the_monotonic_deadline_when_the_wall_clock_steps_back(lc, monkeypatch, tmp_path):
    (tmp_path / "ready").write_text("x", encoding="utf-8")
    clock = _SteppedClock(wall=0.0)
    monkeypatch.setattr(lc, "time", clock)
    assert lc.wait_gone(tmp_path / "ready", time.monotonic() - 1.0) is False
    assert clock.sleeps == 0


def test_wait_for_keeps_waiting_when_the_wall_clock_steps_forward(lc, monkeypatch, tmp_path):
    """A wall clock stepped far ahead must not end a wait whose monotonic deadline is still open."""
    clock = _SteppedClock(wall=time.time() + 10 * 365 * 86400.0, max_sleeps=3)
    monkeypatch.setattr(lc, "time", clock)
    target = tmp_path / "claude.done"
    real_sleep = clock.sleep

    def _sleep(s):
        real_sleep(s)
        if clock.sleeps == 2:
            target.write_text("x", encoding="utf-8")

    clock.sleep = _sleep  # type: ignore[method-assign]
    assert lc.wait_for(target, time.monotonic() + 600.0) is True


def _executor_module():
    spec = importlib.util.spec_from_file_location("rc_loop_executor_p364", ROOT / "ops" / "loop" / "executor.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_executor_builds_every_wait_deadline_on_the_monotonic_clock(tmp_path: Path):
    executor = _executor_module()
    gone: list[float] = []
    done: list[float] = []
    calls = {"n": 0}

    def wait_for(_p, d, watch_bridge=False):
        done.append(d)
        calls["n"] += 1
        return calls["n"] > 1  # miss once -> exercises the stall-recovery deadline too

    def wait_gone(_p, d):
        gone.append(d)
        return True

    ex = executor.build(
        {"channel": "ahk", "cycle_deadline_sec": 5400}, tmp_path,
        log=lambda m: None, stop=lambda m: None, awrite=lambda p, t: None,
        wait_for=wait_for, wait_gone=wait_gone, rjson=lambda p, d=None: {"sha": "a" * 40},
        stall_action=lambda n: "recover", stall_recovery_directive=lambda c: "recover")
    ex.run(1, "body", "fixed")

    assert len(gone) == 2 and len(done) == 2
    now = time.monotonic()
    for d, span in [(gone[0], 120), (done[0], 5400), (gone[1], 120), (done[1], 5400)]:
        assert abs(d - (now + span)) < 30, f"deadline {d} is not now(monotonic) + {span}"

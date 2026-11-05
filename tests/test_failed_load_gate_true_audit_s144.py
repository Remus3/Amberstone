"""s144 true-audit cycle 130 - core/failed_load_gate.FailedLoadGate.

The gate is the RM-439 shape behind 27 fail-soft loaders: after a failed load
the loader serves its empty value WITHOUT caching it and retries once the
backoff window has passed. Every finding below is a way the window could
silently stop ending, which re-creates exactly the defect RM-439 removed (a
failure cached for the process lifetime), or stop existing (a disk parse on
every hot-path call).

  RM-1613  a NaN or infinite retry_after_s: ``elapsed >= nan`` is always
              False, so the gate never allowed a retry again.
  RM-1614  a negative, bool, string or non-number retry_after_s was taken
              silently (a negative one disables the backoff; True read as 1 s;
              "5" read as 5 s; a huge int raised OverflowError).
  RM-1615  assigning retry_after_s after construction bypassed every check.
  RM-1616  a clock that read EARLIER than the recorded failure (a test clock
              restored, a stepped clock) held the gate shut until the clock
              caught up - with the 1_000_000 s test clock, up to 11 days.

The clock is advanced by patching ``time.monotonic``; no disk, no network.
"""
from __future__ import annotations

import math
import threading
import time
from fractions import Fraction

import pytest

from core.failed_load_gate import DEFAULT_RETRY_AFTER_S, FailedLoadGate


class _Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(time, "monotonic", c)
    return c


# -- characterization (pins the shipped contract before the hardening) -------

def test_default_window_and_fresh_gate_attempts(clock):
    gate = FailedLoadGate()
    assert gate.retry_after_s == DEFAULT_RETRY_AFTER_S == 5.0
    assert gate.should_attempt() is True


def test_streak_warns_once_and_window_is_honoured(clock):
    gate = FailedLoadGate(retry_after_s=5.0)
    assert gate.record_failure() is True
    assert gate.should_attempt() is False
    clock.advance(4.999)
    assert gate.should_attempt() is False
    clock.advance(0.001)
    assert gate.should_attempt() is True          # boundary is inclusive
    assert gate.record_failure() is False         # same streak, no re-warn
    assert gate.should_attempt() is False         # failure re-opens the window
    gate.record_success()
    assert gate.should_attempt() is True
    assert gate.record_failure() is True          # a new streak warns again


def test_reset_ends_the_window_and_the_streak(clock):
    gate = FailedLoadGate(retry_after_s=60.0)
    gate.record_failure()
    gate.reset()
    assert gate.should_attempt() is True
    assert gate.record_failure() is True


def test_zero_window_retries_immediately(clock):
    gate = FailedLoadGate(retry_after_s=0)
    assert gate.retry_after_s == 0.0
    assert isinstance(gate.retry_after_s, float)
    gate.record_failure()
    assert gate.should_attempt() is True


@pytest.mark.parametrize("value", [1, 2.5, Fraction(3, 2), 300])
def test_finite_non_negative_reals_are_accepted_as_float(clock, value):
    gate = FailedLoadGate(retry_after_s=value)
    assert gate.retry_after_s == float(value)
    assert type(gate.retry_after_s) is float


def test_concurrent_failures_warn_exactly_once(clock):
    gate = FailedLoadGate(retry_after_s=5.0)
    firsts = []
    barrier = threading.Barrier(16)

    def worker():
        barrier.wait()
        firsts.append(gate.record_failure())

    threads = [threading.Thread(target=worker, name=f"gate-{i}") for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert sorted(firsts) == [False] * 15 + [True]


# -- RM-1613: a non-finite window wedged the gate shut forever ------------

@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, "nan", "inf"])
def test_non_finite_window_is_refused(value):
    with pytest.raises((ValueError, TypeError)):
        FailedLoadGate(retry_after_s=value)


# -- RM-1614: negative / bool / text / non-number / overflowing window ----

@pytest.mark.parametrize("value", [-0.001, -5, -1e300])
def test_negative_window_is_refused(value):
    with pytest.raises(ValueError):
        FailedLoadGate(retry_after_s=value)


@pytest.mark.parametrize("value", [True, False, "5", b"5", None, [5], {"s": 5}, 5j])
def test_non_real_window_is_refused(value):
    with pytest.raises(TypeError):
        FailedLoadGate(retry_after_s=value)


def test_overflowing_int_window_is_a_value_error_not_overflow():
    with pytest.raises(ValueError):
        FailedLoadGate(retry_after_s=10 ** 400)


# -- RM-1615: assignment after construction is validated too --------------

@pytest.mark.parametrize("value", [math.nan, math.inf, -1.0, True, "5", None])
def test_assignment_is_validated_and_leaves_the_old_window(value):
    gate = FailedLoadGate(retry_after_s=7.0)
    with pytest.raises((ValueError, TypeError)):
        gate.retry_after_s = value
    assert gate.retry_after_s == 7.0


def test_valid_assignment_takes_effect(clock):
    gate = FailedLoadGate(retry_after_s=60.0)
    gate.record_failure()
    gate.retry_after_s = 1
    assert type(gate.retry_after_s) is float
    clock.advance(1.0)
    assert gate.should_attempt() is True


def test_no_instance_dict_so_a_typo_cannot_shadow_the_window():
    gate = FailedLoadGate()
    with pytest.raises(AttributeError):
        gate.retry_after = 1.0  # type: ignore[attr-defined]


# -- RM-1616: a clock reading before the recorded failure ------------------

def test_clock_behind_the_failure_does_not_hold_the_gate_shut(clock):
    gate = FailedLoadGate(retry_after_s=60.0)
    gate.record_failure()
    assert gate.should_attempt() is False
    clock.now -= 3600.0     # e.g. a patched clock restored to the real one
    assert gate.should_attempt() is True
    # The retry that follows re-opens a window on the clock now in force.
    assert gate.record_failure() is False
    assert gate.should_attempt() is False
    clock.advance(60.0)
    assert gate.should_attempt() is True


def test_non_finite_clock_reading_does_not_wedge_the_gate(clock):
    gate = FailedLoadGate(retry_after_s=60.0)
    gate.record_failure()
    clock.now = math.nan
    assert gate.should_attempt() is True

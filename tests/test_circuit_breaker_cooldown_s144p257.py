"""RM-1756 - CircuitBreaker.record_restart: the cooldown reset after a trip.

The reset condition was three nested/anded tests (tripped, a trip time, cooldown elapsed); the RM-1756 merge
into one ``if`` must keep each operand meaningful. This pins the behaviour with a fake clock.
"""
from __future__ import annotations

import pytest

from ops import rc_self_monitor as rsm


@pytest.fixture
def clock(monkeypatch):
    state = {"t": 1000.0}
    monkeypatch.setattr(rsm.time, "monotonic", lambda: state["t"])
    return state


def _trip(cb, clock):
    for _ in range(cb.max_restarts):
        assert cb.record_restart() is True
    assert cb.record_restart() is False
    assert cb.tripped is True


def test_a_trip_refuses_until_the_cooldown_elapses(clock):
    cb = rsm.CircuitBreaker(max_restarts=2, window_s=120.0, cooldown_s=300.0)
    _trip(cb, clock)
    clock["t"] += 299.0
    assert cb.record_restart() is False
    assert cb.tripped is True


def test_the_cooldown_resets_the_breaker(clock):
    cb = rsm.CircuitBreaker(max_restarts=2, window_s=120.0, cooldown_s=300.0)
    _trip(cb, clock)
    clock["t"] += 300.0
    assert cb.record_restart() is True
    assert cb.tripped is False
    assert len(cb._restart_times) == 1


def test_a_tripped_breaker_without_a_trip_time_never_self_resets(clock):
    cb = rsm.CircuitBreaker(max_restarts=2, window_s=120.0, cooldown_s=300.0)
    cb.tripped = True
    cb._trip_time = None
    clock["t"] += 10_000.0
    assert cb.record_restart() is False
    assert cb.tripped is True


def test_an_untripped_breaker_is_not_reset(clock):
    cb = rsm.CircuitBreaker(max_restarts=5, window_s=120.0, cooldown_s=0.0)
    assert cb.record_restart() is True
    assert cb.record_restart() is True
    assert len(cb._restart_times) == 2

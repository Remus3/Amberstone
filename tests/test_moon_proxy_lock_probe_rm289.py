"""RM-289: core/moon_proxy.py must not hold its instance lock across the
5 s /health probe.

``is_available()`` used to take ``self._lock`` and call ``self._ping()``
(a ``urlopen`` with ``CONNECT_TTL = 5.0``) while still holding it, so
every vision-extracting coach thread serialized behind the probe while
``:8889`` was wedged. The probe is now computed OUTSIDE the lock and
published under it; callers arriving mid-refresh are served the last
known availability.

The lock probe runs from a SECOND thread: ``self._lock`` is a plain
``threading.Lock``, so a same-thread acquire would deadlock rather than
prove anything.
"""
from __future__ import annotations

import threading
import time

import pytest

from core import moon_proxy as mp


def _slow_proxy(result: bool, entered: threading.Event, release: threading.Event):
    proxy = mp.MoonProxy()

    def _ping() -> bool:
        entered.set()
        assert release.wait(5.0), "test harness: release never set"
        return result

    proxy._ping = _ping  # type: ignore[method-assign]
    return proxy


def test_lock_not_held_during_slow_ping():
    entered, release = threading.Event(), threading.Event()
    proxy = _slow_proxy(True, entered, release)
    worker = threading.Thread(target=proxy.is_available, daemon=True)
    worker.start()
    try:
        assert entered.wait(5.0), "probe never started"
        got = []
        prober = threading.Thread(
            target=lambda: got.append(proxy._lock.acquire(timeout=1.0)),
            daemon=True,
        )
        prober.start()
        prober.join(3.0)
        assert got == [True], "self._lock is held across the network probe"
        proxy._lock.release()
    finally:
        release.set()
        worker.join(5.0)
    assert proxy._available is True


def test_concurrent_caller_served_last_known_without_waiting():
    entered, release = threading.Event(), threading.Event()
    proxy = _slow_proxy(False, entered, release)
    proxy._available = True          # last known: up
    proxy._last_check = time.monotonic() - mp.CHECK_TTL - 1  # refresh due
    worker = threading.Thread(target=proxy.is_available, daemon=True)
    worker.start()
    try:
        assert entered.wait(5.0)
        t0 = time.monotonic()
        assert proxy.is_available() is True   # last known, not blocked
        assert time.monotonic() - t0 < 1.0
    finally:
        release.set()
        worker.join(5.0)
    # The refresh result is published once the probe finishes.
    assert proxy._available is False
    assert proxy.is_available() is False


def test_success_resets_fail_count_and_ttl_caches():
    calls = []
    proxy = mp.MoonProxy()
    proxy._fail_count = 3

    def _ping() -> bool:
        calls.append(1)
        return True

    proxy._ping = _ping  # type: ignore[method-assign]
    assert proxy.is_available() is True
    assert proxy._fail_count == 0
    assert proxy.is_available() is True
    assert len(calls) == 1, "second call inside CHECK_TTL must use the cache"


def test_ping_exception_does_not_wedge_refresh():
    proxy = mp.MoonProxy()

    def _boom() -> bool:
        raise RuntimeError("unexpected")

    proxy._ping = _boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        proxy.is_available()
    # The in-flight flag must be cleared so a later call can refresh.
    proxy._ping = lambda: True  # type: ignore[method-assign]
    proxy._last_check = 0.0
    assert proxy.is_available() is True

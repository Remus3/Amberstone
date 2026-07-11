"""Regression: the minimap_dots CV must not block the /api/state hot path.

The native full-res minimap grab + blob detect can take ~2s; landing it
synchronously on the state-build path stalled every poller (2026-07-11: the
in-game overlay poll timed out at 1500ms and the HUD never flipped in). So
``current_minimap_dots(background=True)`` serves the cached value immediately
and recomputes on a daemon thread (stale-while-revalidate). The default
(``background=False``) path stays synchronous and byte-identical to before.

ASCII only (repo hard rule).
"""
from __future__ import annotations

import threading
import time

import pytest

import core.minimap_blob_detect as mbd

_RECT = {"x": 10, "y": 10, "w": 200, "h": 200}
_RECT_SIG = (10, 10, 200, 200)


@pytest.fixture(autouse=True)
def _reset_dots_state():
    """Isolate the module-level dots cache + refresh flag per test."""
    saved = dict(mbd._dots_cache)
    mbd._dots_cache.update(wall=0.0, rect=None, dots=[], good_wall=0.0)
    with mbd._refresh_lock:
        mbd._refreshing = False
    yield
    mbd._dots_cache.clear()
    mbd._dots_cache.update(saved)
    with mbd._refresh_lock:
        mbd._refreshing = False


def _wait_until(pred, timeout=3.0, step=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return bool(pred())


def test_background_true_does_not_block_on_slow_compute(monkeypatch):
    """A slow CV recompute runs off the caller's thread; the hot-path call
    returns immediately (well under the compute time)."""
    seen = {"thread": None}
    slow_s = 0.5

    def _slow_compute(rect, roster):
        seen["thread"] = threading.current_thread().name
        time.sleep(slow_s)
        now = time.time()
        mbd._dots_cache.update(
            wall=now, rect=_RECT_SIG,
            dots=[{"team": "ORDER", "x_frac": 0.5, "y_frac": 0.5}],
            good_wall=now,
        )
        return mbd._dots_cache["dots"]

    monkeypatch.setattr(mbd, "_compute_and_cache_dots", _slow_compute)

    t0 = time.time()
    out = mbd.current_minimap_dots(_RECT, background=True)
    elapsed = time.time() - t0

    assert elapsed < 0.2, f"hot path blocked {elapsed:.3f}s (should be ~0)"
    assert out == []  # empty cache -> serve [] until the background pass lands
    assert _wait_until(lambda: seen["thread"] is not None)
    assert seen["thread"] != threading.main_thread().name
    assert _wait_until(lambda: mbd._dots_cache["dots"])


def test_background_true_serves_fresh_cache_without_recompute(monkeypatch):
    sentinel = [{"team": "CHAOS", "x_frac": 0.7, "y_frac": 0.3}]
    now = time.time()
    mbd._dots_cache.update(wall=now, rect=_RECT_SIG, dots=sentinel, good_wall=now)
    called = {"n": 0}
    monkeypatch.setattr(
        mbd, "_compute_and_cache_dots",
        lambda r, ro: called.__setitem__("n", called["n"] + 1) or [],
    )
    out = mbd.current_minimap_dots(_RECT, ttl_s=1.5, background=True)
    assert out == sentinel
    assert called["n"] == 0  # fresh cache -> no recompute, no spawn


def test_background_true_serves_last_good_while_revalidating(monkeypatch):
    """Stale but same-rect cache: serve last-good now, refresh behind."""
    last_good = [{"team": "ORDER", "x_frac": 0.4, "y_frac": 0.6}]
    mbd._dots_cache.update(wall=0.0, rect=_RECT_SIG, dots=last_good,
                           good_wall=time.time())
    fired = threading.Event()
    monkeypatch.setattr(mbd, "_compute_and_cache_dots",
                        lambda r, ro: (fired.set(), [])[1])
    out = mbd.current_minimap_dots(_RECT, background=True)
    assert out == last_good
    assert fired.wait(2.0)


def test_default_path_is_synchronous(monkeypatch):
    """background=False (default) computes inline on the calling thread."""
    sentinel = [{"team": "ORDER", "x_frac": 0.1, "y_frac": 0.2}]
    where = {"thread": None}

    def _compute(rect, roster):
        where["thread"] = threading.current_thread().name
        return sentinel

    monkeypatch.setattr(mbd, "_compute_and_cache_dots", _compute)
    out = mbd.current_minimap_dots(_RECT)  # default background=False
    assert out == sentinel
    assert where["thread"] == threading.main_thread().name


def test_only_one_background_refresh_in_flight(monkeypatch):
    """A second stale call while a refresh runs does not spawn a 2nd worker."""
    started = []
    release = threading.Event()

    def _blocking(rect, roster):
        started.append(threading.current_thread().name)
        release.wait(2.0)
        return []

    monkeypatch.setattr(mbd, "_compute_and_cache_dots", _blocking)
    mbd.current_minimap_dots(_RECT, background=True)
    mbd.current_minimap_dots(_RECT, background=True)  # in-flight -> no-op
    assert _wait_until(lambda: len(started) >= 1)
    time.sleep(0.15)
    release.set()
    assert len(started) == 1

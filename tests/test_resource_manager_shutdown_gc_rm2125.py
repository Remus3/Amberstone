"""RM-2125: shutdown() must not run a full-heap gc.collect() on its critical path.

Measured 2026-11-26 in a scratch subprocess (801 MB RSS, ~4.07M gc-tracked
objects, 3 CPU-burning threads): shutdown() median 0.461 s / max 0.516 s with
the full collect, 0.000 s without it - the collect was ~100 percent of
shutdown time, and a busy CI worker timed the whole of shutdown() at 5.17 s.
Moving the collect to a daemon thread was measured NOT to help (a collect
holds the GIL, so the caller still stalled), so the fix bounds it to the young
generations; interpreter finalization collects the old generation anyway.

The stand-in makes a full collection (no argument, or generation 2) cost 5 s
and a young one free, so a sleep that releases the GIL cannot make an
off-thread full collect look fixed.
"""

from __future__ import annotations

import time

import core.resource_manager as rmmod
from core.resource_manager import ResourceManager


def _install(monkeypatch) -> list[int]:
    calls: list[int] = []

    def fake_collect(generation: int = 2) -> int:
        calls.append(generation)
        if generation >= 2:
            time.sleep(5.0)
        return 0

    monkeypatch.setattr(rmmod.gc, "collect", fake_collect)
    return calls


def test_full_heap_collect_does_not_block_shutdown(tmp_path, monkeypatch):
    calls = _install(monkeypatch)
    rm = ResourceManager(tmp_path)
    t0 = time.monotonic()
    rm.shutdown()
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, f"shutdown() blocked {elapsed:.2f}s on a full gc.collect"
    assert 2 not in calls


def test_shutdown_still_collects_young_garbage(tmp_path, monkeypatch):
    calls = _install(monkeypatch)
    ResourceManager(tmp_path).shutdown()
    assert calls and all(g < 2 for g in calls), calls

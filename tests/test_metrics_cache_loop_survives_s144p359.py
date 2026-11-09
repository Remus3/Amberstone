"""S144-P-359 - the MetricsCache refresh loops survive a refresh that raises.

``MetricsCache._loop`` (daemon-thread fallback) and ``_loop_async`` (AppLoop task) called ``self._refresh()``
bare. ``_refresh`` isolates each reader, so today nothing escapes it, but the loop itself had no guard: the
first exception from a future reader change, from ``MetricsSummary()`` or from the summary swap would end the
thread (or the task) silently and every consumer of ``get_summary()`` would read a frozen summary from then
on, with nothing in the log. Same defect class as the hotkey listener's decision-refresh thread (S144-P-358).
Each loop now catches Exception per pass, logs it and goes on to the next interval.
"""
from __future__ import annotations

import asyncio
import logging
import threading

from core.metrics_cache import MetricsCache
from tests._asyncio_isolation import run_coro

_INTERVAL_S = 0.01
_PASSES = 4


def _flaky_refresh(cache: MetricsCache, done: threading.Event):
    calls = {"n": 0}

    def refresh() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("synthetic refresh fault")
        if calls["n"] >= _PASSES:
            done.set()

    cache._refresh = refresh  # type: ignore[method-assign]
    return calls


def test_thread_loop_keeps_refreshing_after_a_raise(tmp_path, caplog):
    cache = MetricsCache(tmp_path, refresh_interval_s=_INTERVAL_S)
    done = threading.Event()
    calls = _flaky_refresh(cache, done)
    worker = threading.Thread(target=cache._loop, daemon=True)
    with caplog.at_level(logging.WARNING, logger="core.metrics_cache"):
        worker.start()
        reached = done.wait(timeout=10)
        cache._stop_event.set()
        worker.join(timeout=10)
    assert reached, f"the loop ended after the first raise (calls={calls['n']})"
    assert not worker.is_alive()
    assert any("synthetic refresh fault" in r.getMessage() or r.exc_info for r in caplog.records)


def test_async_loop_keeps_refreshing_after_a_raise(tmp_path, caplog):
    cache = MetricsCache(tmp_path, refresh_interval_s=_INTERVAL_S)
    done = threading.Event()
    calls = _flaky_refresh(cache, done)

    async def drive() -> None:
        task = asyncio.ensure_future(cache._loop_async())
        for _ in range(1000):
            if done.is_set():
                break
            await asyncio.sleep(_INTERVAL_S)
        cache._stop_event.set()
        await asyncio.wait_for(task, timeout=10)

    with caplog.at_level(logging.WARNING, logger="core.metrics_cache"):
        run_coro(drive())
    assert done.is_set(), f"the task ended after the first raise (calls={calls['n']})"
    assert any("synthetic refresh fault" in r.getMessage() or r.exc_info for r in caplog.records)

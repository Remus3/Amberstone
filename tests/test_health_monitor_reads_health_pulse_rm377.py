"""RM-377: `BaseCoachWorker.health_pulse()` had ZERO production callers;
`app/_health_monitor.py` read raw attributes, so every RM-198 field
(stranded generations, crash count, last error) would have shipped inert.

Decision (a), under this run's frozen-file grant: `get_health_state()` reads
the worker through `health_pulse()` - the ONE seam - and surfaces the RM-198
fields. Reachability probe, not a scan: a recording spy proves the consumer
calls the method and that its values flow out.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

from app._health_monitor import HealthMonitor
from core.base_worker import BaseCoachWorker


class _Worker(BaseCoachWorker):
    def _run(self, my_gen):  # pragma: no cover - never started
        pass


def _app(worker):
    return SimpleNamespace(mode="sr", _tft_mode=False, _aram_mode=False,
                           _arena_mode=False, _was_in_game=True,
                           _sr_aram_worker=worker, _overlay_visible=False)


def test_consumer_reads_through_health_pulse():
    w = _Worker()
    calls = []
    real = w.health_pulse

    def spy():
        calls.append(1)
        return real()

    w.health_pulse = spy
    HealthMonitor(_app(w)).get_health_state()
    assert calls == [1]


def test_rm198_fields_reach_the_health_state():
    w = _Worker()
    w.pulse_ts = time.monotonic()
    w.crash_count = 2
    w.last_error = "gen=3 RuntimeError: boom"
    state = HealthMonitor(_app(w)).get_health_state()
    assert state["game_poll_worker_alive"] is True
    assert state["game_poll_worker_crash_count"] == 2
    assert state["game_poll_worker_last_error"] == "gen=3 RuntimeError: boom"
    assert state["game_poll_worker_stranded_generations"] == []


def test_no_worker_path_keeps_legacy_shape():
    app = _app(None)
    app._poll_worker_pulse_ts = 0.0
    state = HealthMonitor(app).get_health_state()
    assert state["game_poll_worker_alive"] is False
    assert state["game_poll_worker_crash_count"] == 0

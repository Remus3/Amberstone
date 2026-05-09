# arch: vision server stats + log ring | section=vision | frozen=no
"""Stats tracking for vision/coach/ocr/upload calls.

Split out of moon_vision_server.py during Phase 2.4. Owns:
- ``_stats`` dict (per-kind call/error/latency/byte counters).
- ``_log_ring`` (rolling 80-entry request log).
- ``_latency_ring`` (rolling 60-entry latency series for sparkline).
- ``_record(kind, ms, ok, tokens)`` — the single mutator.
- ``get_stats()`` — snapshot for the /stats endpoint.

Sibling modules (``_frame``, ``_relay``) directly mutate ``_stats[kind]["bytes"]``
under ``_stats_lock`` to record upload byte totals. Keep that contract — moving
those mutations behind setters would just create indirection.
"""
from __future__ import annotations

import collections
import sys
import threading
import time

from ._config import COACH_MODEL, VISION_MODEL, _START_TIME, api_key_present

_stats_lock = threading.Lock()
_stats: dict = {
    "vision":            {"calls": 0, "errors": 0, "total_ms": 0, "tokens_est": 0},
    "coach":             {"calls": 0, "errors": 0, "total_ms": 0, "tokens_est": 0},
    "ocr":               {"calls": 0, "errors": 0, "total_ms": 0},
    "frame_upload":      {"calls": 0, "errors": 0, "total_ms": 0, "bytes": 0},
    "liveclient_upload": {"calls": 0, "errors": 0, "total_ms": 0, "bytes": 0},
    "lcu_upload":        {"calls": 0, "errors": 0, "total_ms": 0},
}
_log_ring = collections.deque(maxlen=80)
_latency_ring = collections.deque(maxlen=60)


def _record(kind: str, ms: int, ok: bool = True, tokens: int = 0) -> None:
    ts = time.strftime("%H:%M:%S")
    with _stats_lock:
        s = _stats.setdefault(kind, {"calls": 0, "errors": 0, "total_ms": 0})
        s["calls"] += 1
        s["total_ms"] += ms
        if not ok:
            s["errors"] += 1
        if tokens:
            s["tokens_est"] = s.get("tokens_est", 0) + tokens
        _log_ring.append({"ts": ts, "kind": kind, "ms": ms, "ok": ok})
        _latency_ring.append({"kind": kind, "ms": ms, "ts": time.time()})


def get_stats() -> dict:
    with _stats_lock:
        stats_copy = {k: dict(v) for k, v in _stats.items()}
        log_copy = [dict(x) for x in list(_log_ring)[-30:]]
        lat_copy = [dict(x) for x in list(_latency_ring)]
        return {
            "uptime_s":     int(time.time() - _START_TIME),
            "stats":        stats_copy,
            "log":          log_copy,
            "latency_60":   lat_copy,
            "python":       sys.version.split()[0],
            "vision_model": VISION_MODEL,
            "coach_model":  COACH_MODEL,
            "api_key_ok":   api_key_present(),
        }

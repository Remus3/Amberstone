"""GET /api/perf-curve - per-minute averaged performance curve (read-only).

Serves core.perf_curve.compute_perf_curve over the LOCAL rewind_history.db:
the tracked player's average cumulative gold (or creep score) at each game
minute, split win vs loss, per mode. Computed entirely over the operator's own
corpus (no global / Riot / Claude dependency); the panel polls this thin HTTP
surface.

Request shape:
  GET /api/perf-curve[?mode=sr|aram|arena][&metric=gold|cs][&champion=64]

  mode     : sr | aram | arena. Default aram (the ARAM-dominant corpus).
             Anything else -> 400.
  metric   : gold | cs. Default gold. Anything else -> 400.
  champion : optional Riot integer champion id to filter to one champion.
             Non-int -> 400. Omitted -> null.

Response is compute_perf_curve(...)'s dict plus cached (bool) and
elapsed_ms (int).

Cache: 5min in-process keyed by (mode, metric, champion) - mirrors
routes_duration_winrate so a re-polling panel does not turn the corpus scan
into a DB hot loop.

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad mode / metric / champion -> 400 with a short clear error
  - any other exception -> 500 structured error; the raw text is logged.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import perf_curve
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 256
_CACHE_EVICT = 64


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _parse_mode(raw: str) -> tuple[str, str | None]:
    if not raw:
        return (perf_curve.DEFAULT_MODE, None)
    if raw not in perf_curve.VALID_MODES:
        return ("", f"mode must be one of {', '.join(perf_curve.VALID_MODES)}")
    return (raw, None)


def _parse_metric(raw: str) -> tuple[str, str | None]:
    if not raw:
        return (perf_curve.DEFAULT_METRIC, None)
    if raw not in perf_curve.VALID_METRICS:
        return ("", f"metric must be one of {', '.join(perf_curve.VALID_METRICS)}")
    return (raw, None)


def _parse_champion(raw: str) -> tuple[int | None, str | None]:
    if not raw:
        return (None, None)
    try:
        return (int(raw), None)
    except ValueError:
        return (None, f"champion must be an integer, got {raw!r}")


def _serve_perf_curve(h) -> None:
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        mode_raw = (qs.get("mode") or [""])[0].strip()
        metric_raw = (qs.get("metric") or [""])[0].strip()
        champ_raw = (qs.get("champion") or [""])[0].strip()

        mode, err = _parse_mode(mode_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return
        metric, err = _parse_metric(metric_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return
        champion, err = _parse_champion(champ_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return

        key = (mode, metric, champion)
        now = time.time()
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached and (now - cached[0]) < _CACHE_TTL_S:
                payload = dict(cached[1])
                payload["cached"] = True
                payload["elapsed_ms"] = int((time.time() - t0) * 1000)
                h._send(200, json.dumps(payload).encode("utf-8"),
                        "application/json")
                return

        payload = perf_curve.compute_perf_curve(
            mode=mode, champion=champion, metric=metric)
        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)

        cacheable = dict(payload)
        cacheable.pop("cached", None)
        cacheable.pop("elapsed_ms", None)
        _cache_put(key, now, cacheable)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/perf-curve: %s", exc)
        try:
            h._send(500, json.dumps(
                {"ok": False, "error": "internal error - see logs"})
                .encode("utf-8"), "application/json")
        except Exception:
            pass


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/perf-curve"), _serve_perf_curve),
]

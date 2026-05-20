# arch: ward-coverage heat strip backend | section=dashboard | frozen=no
"""GET /api/ward-heat - rolling-window ward placements + uncovered lanes.

UX research recommended a "Ward-Coverage Heat Strip" panel (UX-3 in
the pitch deck) - a 24px horizontal band below the active-match
minimap showing the last 90 seconds of ward placements per lane
(top/mid/bot/jg), colored by ward type. This module is the BACKEND
half - it does NOT render anything; the canvas is a separate UX
follow-up.

Request shape:
  GET /api/ward-heat[?window_s=90]

  window_s : optional float, rolling-window length in seconds. Default
             90. Range-clamped to [5, 600] to keep the response cheap
             and the cache key small.

Response shape:
  {
    "ok":     true,
    "now_s":  <unix epoch seconds, when this snapshot was taken>,
    "window_s": 90,
    "wards":  [
      {"ts": 1755..., "side": "ally", "lane": "mid", "ward_type": "yellow"},
      ...
    ],
    "counts": {
      "ally":  {"top": 3, "mid": 2, "bot": 0, "jg": 1, "unknown": 0},
      "enemy": {"top": 0, "mid": 1, "bot": 0, "jg": 0, "unknown": 0}
    },
    "lanes_uncovered_ally":  ["bot"],
    "lanes_uncovered_enemy": ["top", "bot", "jg"],
    "buffer_size":           7,
    "cached":                false,
    "elapsed_ms":            1
  }

Cache:
  2-second response cache keyed by ``window_s``. The dashboard ticks
  at ~500ms; a 2s cache cuts the recompute load 4x without making the
  UX-3 strip look stale (90s of dots, 2s freshness on the head).

Event source status:
  The producer side (who calls ``core.ward_events.record_ward``) is
  intentionally not wired in this slice. The Live Client event stream
  does NOT expose WARD_PLACED - never has - so a future task will add
  either an inventory-delta watcher on allPlayers.items or an OCR pass
  over the minimap. Until then, this route returns an empty rolling
  window and the rest of the UX-3 stack is designable against the
  contract above.

Failure modes:
  - window_s not numeric or out of range -> 400 with a clear error
  - any unexpected exception -> 500 + structured error, never raises
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import ward_events
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# Cache parameters.
_CACHE_TTL_S = 2.0
_WINDOW_MIN_S = 5.0
_WINDOW_MAX_S = 600.0
_DEFAULT_WINDOW_S = 90.0

# Cache: (window_s,) -> (cached_at, payload).
_CACHE: dict[tuple[float], tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()


def _parse_window(qs: dict) -> tuple[float, str | None]:
    """Parse / validate the ``window_s`` query param.

    Returns ``(window_s, error)``. ``error`` is None on success;
    otherwise a short user-facing message and the route should 400.
    """
    raw = (qs.get("window_s") or [""])[0].strip()
    if not raw:
        return _DEFAULT_WINDOW_S, None
    try:
        val = float(raw)
    except ValueError:
        return 0.0, f"window_s must be numeric, got {raw!r}"
    if val < _WINDOW_MIN_S or val > _WINDOW_MAX_S:
        return 0.0, (
            f"window_s must be in [{_WINDOW_MIN_S:.0f}, {_WINDOW_MAX_S:.0f}], "
            f"got {val}"
        )
    return val, None


def _build_payload(window_s: float, now_s: float) -> dict:
    """Pull the rolling-window snapshot from ``core.ward_events`` and
    shape it for the response. No HTTP / I/O here so it's trivially
    testable on its own."""
    wards = ward_events.recent_wards(now_s=now_s, window_s=window_s)
    counts = ward_events.counts_by_lane(now_s=now_s, window_s=window_s)
    # The 'uncovered lane' semantic uses a 60s window per UX-3 spec.
    # Clamp to MIN(window_s, 60) so a caller asking for window_s=30 still
    # sees the uncovered list relative to their own narrower view.
    uncovered_window = min(window_s, 60.0)
    return {
        "ok":       True,
        "now_s":    round(now_s, 3),
        "window_s": window_s,
        "wards":    wards,
        "counts":   counts,
        "lanes_uncovered_ally":  ward_events.lanes_uncovered(
            "ally",  now_s=now_s, window_s=uncovered_window),
        "lanes_uncovered_enemy": ward_events.lanes_uncovered(
            "enemy", now_s=now_s, window_s=uncovered_window),
        "buffer_size": ward_events.buffer_size(),
    }


def _serve_ward_heat(h) -> None:
    """GET /api/ward-heat - route entry point."""
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        window_s, err = _parse_window(qs)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err}).encode("utf-8"),
                    "application/json")
            return

        cache_key = (window_s,)
        now = time.time()
        with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached and (now - cached[0]) < _CACHE_TTL_S:
                payload = dict(cached[1])
                payload["cached"] = True
                payload["elapsed_ms"] = int((time.time() - t0) * 1000)
                h._send(200, json.dumps(payload).encode("utf-8"),
                        "application/json")
                return

        payload = _build_payload(window_s, now)
        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)

        with _CACHE_LOCK:
            # Cache the payload WITHOUT the per-request fields so a cache
            # hit always reports its own elapsed_ms + cached=True.
            cacheable = dict(payload)
            cacheable.pop("cached", None)
            cacheable.pop("elapsed_ms", None)
            _CACHE[cache_key] = (now, cacheable)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/ward-heat: %s", exc)
        try:
            h._send(500, json.dumps({"ok": False, "error": str(exc)[:200]})
                    .encode("utf-8"), "application/json")
        except Exception:
            # Even the error-send failed - swallow so the dispatch loop
            # doesn't take the whole handler down.
            pass


def _reset_caches() -> None:
    """Test-only: clear the response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/ward-heat"), _serve_ward_heat),
]

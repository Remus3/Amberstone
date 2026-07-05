"""GET /api/snowball-elasticity - win-rate by team gold differential (read-only).

Serves core.snowball_elasticity.compute_snowball_elasticity over the LOCAL
rewind_history.db timeline: the tracked player's win % bucketed by TEAM gold
lead at ~10min and ~20min checkpoints. Computed entirely over the operator's own
SR corpus (no global / Riot / Claude dependency); the Build Insights panel polls
this thin HTTP surface.

Request shape:
  GET /api/snowball-elasticity

  No query params today - the surface is SR-only (the gold-lead-at-checkpoint
  signal is meaningless in ARAM / Arena). A ``mode`` param is accepted but
  inert, for symmetry with sibling routes.

Response is compute_snowball_elasticity()'s dict plus cached (bool) and
elapsed_ms (int).

Cache: 5min in-process - mirrors routes_duration_winrate so a re-polling panel
does not turn the ~680k-row timeline scan into a DB hot loop.

Failure modes (a raw exception string is NEVER leaked to the client):
  - any exception -> 500 structured error; the raw text is logged.
"""
from __future__ import annotations

import json
import logging
import threading
import time

from core import snowball_elasticity
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_CACHE_TTL_S = 300.0
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()


def _serve_snowball_elasticity(h) -> None:
    t0 = time.time()
    try:
        key = "sr"
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

        payload = snowball_elasticity.compute_snowball_elasticity()
        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)

        cacheable = dict(payload)
        cacheable.pop("cached", None)
        cacheable.pop("elapsed_ms", None)
        with _CACHE_LOCK:
            _CACHE[key] = (now, cacheable)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/snowball-elasticity: %s", exc)
        try:
            h._send(500, json.dumps(
                {"ok": False, "error": "internal error - see logs"})
                .encode("utf-8"), "application/json")
        except Exception:  # noqa: BLE001
            pass


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/snowball-elasticity"), _serve_snowball_elasticity),
]

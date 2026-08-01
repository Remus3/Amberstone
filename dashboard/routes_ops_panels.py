# arch: ops panels backend (seam map / drift strip / gated queue) | section=dashboard | frozen=no
"""GET /api/ops/{seam-map,drift-strip,gated-queue} - ADDENDUM A concepts 3/4/5.

Thin dashboard wire over ``core.ops_panels``. NO compute lives here: every
number is derived in that module so it stays testable without a server, and
this file only parses nothing, caches briefly and serialises.

All three are cheap disk reads, but they are read on every dashboard poll, so
each response is cached for ``_TTL`` seconds. The cache is deliberately short:
these panels exist to show DRIFT, and a long TTL would make the panel itself a
source of staleness - the exact failure it is meant to surface.

Fail-soft contract, matching the sibling route modules: a missing file yields
``ok: False`` plus a reason at HTTP 200 rather than a 500, so one broken data
source degrades one card instead of blanking the dashboard.
"""
from __future__ import annotations

import json
import logging
import threading
import time

from dashboard._dispatch import equals

from core import ops_panels

log = logging.getLogger(__name__)

_TTL = 15.0
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()


def _cached(key: str, fn) -> dict:
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and (now - hit[0]) < _TTL:
            return dict(hit[1], cached=True)
    payload = fn()
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
    return dict(payload, cached=False)


def _serve(h, key: str, fn) -> None:
    t0 = time.time()
    try:
        payload = _cached(key, fn)
    except Exception:                      # noqa: BLE001 - never 500 a panel
        log.exception("ops panel %s failed", key)
        payload = {"ok": False, "reason": "panel computation failed"}
    payload["elapsed_ms"] = int((time.time() - t0) * 1000)
    h._send(200, json.dumps(payload).encode("utf-8"), "application/json")


def _serve_seam_map(h) -> None:
    """GET /api/ops/seam-map"""
    _serve(h, "seam-map", ops_panels.compute_seam_map)


def _serve_drift_strip(h) -> None:
    """GET /api/ops/drift-strip"""
    _serve(h, "drift-strip", ops_panels.compute_drift_strip)


def _serve_gated_queue(h) -> None:
    """GET /api/ops/gated-queue"""
    _serve(h, "gated-queue", ops_panels.compute_gated_queue)


GET_ROUTES = [
    (equals("/api/ops/seam-map"), _serve_seam_map),
    (equals("/api/ops/drift-strip"), _serve_drift_strip),
    (equals("/api/ops/gated-queue"), _serve_gated_queue),
]

POST_ROUTES: list = []

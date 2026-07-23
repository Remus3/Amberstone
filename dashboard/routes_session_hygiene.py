"""GET /api/session-hygiene - deterministic tilt / readiness analytics (read-only).

Serves core.session_hygiene.compute_session_hygiene over the LOCAL
rewind_history.db: the tracked player's own win-rate conditioned on session
context (position in session, hour, weekday, rust, same-champ requeue) plus a
bounded 0-100 "Should I Queue" readiness odds-shift. Computed entirely over
the operator's own corpus (no global / Riot / Claude dependency) - the
Haiku-to-ZERO north star. The panel polls this thin HTTP surface.

Request shape:
  GET /api/session-hygiene[?queue=450[,420]]

  queue : optional comma-separated queue-id filter (e.g. 450 for ARAM,
          420 for ranked solo). Any non-int token -> 400. Omitted -> all games.

Response is compute_session_hygiene(...)'s dict plus cached (bool) and
elapsed_ms (int).

Cache: 5min in-process keyed by the queue tuple - mirrors
routes_duration_winrate so a re-polling panel does not turn the corpus scan
into a DB hot loop. now_ms is NOT part of the key: readiness is
context-at-request, so a fresh compute on cache miss reads the wall clock and
a cached hit is at most 5min stale, which is well within the 2h session gap.

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad queue token -> 400 with a short clear error
  - any other exception -> 500 structured error; the raw text is logged.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import session_hygiene
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 64
_CACHE_EVICT = 16


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _parse_queue(raw: str):
    """('' , None) when omitted; (tuple, None) when valid; (None, err) on a
    bad token."""
    if not raw:
        return (None, None)
    ids = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            ids.append(int(tok))
        except ValueError:
            return (None, f"queue must be integers, got {tok!r}")
    return (tuple(ids), None)


def _serve_session_hygiene(h) -> None:
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        queue_raw = (qs.get("queue") or [""])[0].strip()

        queue_ids, err = _parse_queue(queue_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return

        key = (queue_ids,)
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

        payload = session_hygiene.compute_session_hygiene(queue_ids=queue_ids)
        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)

        cacheable = dict(payload)
        cacheable.pop("cached", None)
        cacheable.pop("elapsed_ms", None)
        _cache_put(key, now, cacheable)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/session-hygiene: %s", exc)
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
    (equals("/api/session-hygiene"), _serve_session_hygiene),
]

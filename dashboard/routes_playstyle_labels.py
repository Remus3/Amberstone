"""GET /api/playstyle-labels - deterministic per-champion playstyle fingerprint
(read-only).

Serves core.playstyle_labels.compute_playstyle_labels over the LOCAL
rewind_history.db: for each champion the tracked player has enough games on, a
set of SELF-RELATIVE VERDICT labels (dies more/less than your own norm,
kill-focused, team-involved, consistent / coinflip) plus the honest WR.
Computed entirely over the operator's own corpus (no global / Riot / Claude
dependency) - the Haiku-to-ZERO north star. The snapshot card polls this thin
HTTP surface.

Request shape:
  GET /api/playstyle-labels[?queue=450[,420]][&min_games=5]

  queue     : optional comma-separated queue-id filter. Non-int token -> 400.
  min_games : optional games floor for surfacing WR + labels. Non-int -> 400.

Response is compute_playstyle_labels(...)'s dict plus cached (bool) and
elapsed_ms (int).

Cache: 5min in-process keyed by (queue tuple, min_games) - mirrors
routes_duration_winrate so a re-polling card does not turn the corpus scan
into a DB hot loop.

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad queue / min_games token -> 400 with a short clear error
  - any other exception -> 500 structured error; the raw text is logged.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import playstyle_labels
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


def _parse_min_games(raw: str):
    if not raw:
        return (playstyle_labels.MIN_GAMES, None)
    try:
        val = int(raw)
    except ValueError:
        return (None, f"min_games must be an integer, got {raw!r}")
    if val < 1:
        return (None, "min_games must be >= 1")
    return (val, None)


def _serve_playstyle_labels(h) -> None:
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        queue_raw = (qs.get("queue") or [""])[0].strip()
        min_raw = (qs.get("min_games") or [""])[0].strip()

        queue_ids, err = _parse_queue(queue_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return
        min_games, err = _parse_min_games(min_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return

        key = (queue_ids, min_games)
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

        payload = playstyle_labels.compute_playstyle_labels(
            min_games=min_games, queue_ids=queue_ids)
        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)

        cacheable = dict(payload)
        cacheable.pop("cached", None)
        cacheable.pop("elapsed_ms", None)
        _cache_put(key, now, cacheable)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/playstyle-labels: %s", exc)
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
    (equals("/api/playstyle-labels"), _serve_playstyle_labels),
]

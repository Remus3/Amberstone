"""GET /api/duration-winrate - win-rate-by-game-length curve (read-only).

Serves core.duration_winrate.compute_duration_winrate over the LOCAL
rewind_history.db: the tracked player's win % bucketed by match duration, per
mode. Computed entirely over the operator's own corpus (no global / Riot /
Claude dependency); the panel polls this thin HTTP surface.

Request shape:
  GET /api/duration-winrate[?mode=sr|aram|arena][&champion=64]

  mode     : sr | aram | arena. Default aram (the ARAM-dominant corpus).
             Anything else -> 400.
  champion : optional Riot integer champion id to filter to one champion.
             Non-int -> 400. Omitted -> null.

Response is compute_duration_winrate(...)'s dict plus cached (bool) and
elapsed_ms (int).

Cache: 5min in-process keyed by (mode, champion) - mirrors routes_player_profile
so a re-polling panel does not turn the corpus scan into a DB hot loop.

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad mode / champion -> 400 with a short clear error
  - any other exception -> 500 structured error; the raw text is logged.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import duration_winrate
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
        return (duration_winrate.DEFAULT_MODE, None)
    if raw not in duration_winrate.VALID_MODES:
        return ("", f"mode must be one of {', '.join(duration_winrate.VALID_MODES)}")
    return (raw, None)


def _parse_champion(raw: str) -> tuple[int | None, str | None]:
    if not raw:
        return (None, None)
    try:
        return (int(raw), None)
    except ValueError:
        return (None, f"champion must be an integer, got {raw!r}")


def _serve_duration_winrate(h) -> None:
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        mode_raw = (qs.get("mode") or [""])[0].strip()
        champ_raw = (qs.get("champion") or [""])[0].strip()

        mode, err = _parse_mode(mode_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return
        champion, err = _parse_champion(champ_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return

        key = (mode, champion)
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

        payload = duration_winrate.compute_duration_winrate(
            mode=mode, champion=champion)
        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)

        cacheable = dict(payload)
        cacheable.pop("cached", None)
        cacheable.pop("elapsed_ms", None)
        _cache_put(key, now, cacheable)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/duration-winrate: %s", exc)
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
    (equals("/api/duration-winrate"), _serve_duration_winrate),
]

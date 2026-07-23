"""GET /api/patch-impact - what this patch changed for the champions you play.

Serves core.patch_impact.compute_patch_impact: the cross-patch Daemon Slayer
snapshot diff (RM-110) intersected with the tracked player's own
rewind_history.db play counts. Fully local - no Riot, no Claude, no network.

Request shape:
  GET /api/patch-impact[?mode=sr|aram|arena][&top=12][&min_games=5]
                       [&old=16.13.1][&new=16.14.1]

  mode      : sr | aram | arena. Default aram (the ARAM-dominant corpus).
              Anything else -> 400.
  top       : 1..50 champions to return, default 12. Non-int / out of range -> 400.
  min_games : 1..500 games before a champion counts as yours, default 5.
  old / new : optional patch pair. BOTH are validated against the snapshot dirs
              actually on disk - an unknown name is a 400, never a path handed
              to the diff tool (its _resolve() would happily take a directory).

Response is compute_patch_impact(...)'s dict plus cached (bool) and elapsed_ms
(int).

Cache: 5min in-process keyed by (mode, top, min_games, old, new) - the diff
walks two full snapshots, so a re-polling panel must not re-run it per tick.

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad mode / top / min_games / patch name -> 400 with a short clear error
  - any other exception -> 500 structured error; the raw text is logged.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import patch_impact
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 128
_CACHE_EVICT = 32

MAX_TOP = 50
MAX_MIN_GAMES = 500


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _parse_mode(raw: str) -> tuple[str, str | None]:
    if not raw:
        return (patch_impact.DEFAULT_MODE, None)
    if raw not in patch_impact.VALID_MODES:
        return ("", f"mode must be one of {', '.join(patch_impact.VALID_MODES)}")
    return (raw, None)


def _parse_int(raw: str, name: str, default: int, hi: int) -> tuple[int, str | None]:
    if not raw:
        return (default, None)
    try:
        value = int(raw)
    except ValueError:
        return (0, f"{name} must be an integer, got {raw!r}")
    if not (1 <= value <= hi):
        return (0, f"{name} must be between 1 and {hi}, got {value}")
    return (value, None)


def _parse_patch(raw: str, name: str, known: list) -> tuple[str | None, str | None]:
    if not raw:
        return (None, None)
    if raw not in known:
        return (None, f"{name} is not a snapshot on disk")
    return (raw, None)


def _serve_patch_impact(h) -> None:
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        mode, err = _parse_mode((qs.get("mode") or [""])[0].strip())
        if not err:
            top, err = _parse_int((qs.get("top") or [""])[0].strip(), "top",
                                  patch_impact.DEFAULT_TOP_N, MAX_TOP)
        if not err:
            min_games, err = _parse_int(
                (qs.get("min_games") or [""])[0].strip(), "min_games",
                patch_impact.DEFAULT_MIN_GAMES, MAX_MIN_GAMES)
        known = patch_impact.available_patches()
        if not err:
            old, err = _parse_patch((qs.get("old") or [""])[0].strip(),
                                    "old", known)
        if not err:
            new, err = _parse_patch((qs.get("new") or [""])[0].strip(),
                                    "new", known)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return

        key = (mode, top, min_games, old, new)
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

        payload = patch_impact.compute_patch_impact(
            mode=mode, old_patch=old, new_patch=new, top_n=top,
            min_games=min_games)
        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)

        cacheable = dict(payload)
        cacheable.pop("cached", None)
        cacheable.pop("elapsed_ms", None)
        _cache_put(key, now, cacheable)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/patch-impact: %s", exc)
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
    (equals("/api/patch-impact"), _serve_patch_impact),
]

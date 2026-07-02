"""GET /api/player-profile - longitudinal 8-axis GPI radar (read-only).

Serves the already-shipped ``core.player_gpi.compute_gpi`` over the LOCAL
rewind_history.db. The compute is the Aggregator-C-profile-style longitudinal
skill profile (8 axes, self-relative scoring); this route is the thin
read-only HTTP surface the radar panel polls.

Request shape:
  GET /api/player-profile[?mode=sr|aram|arena][&window=20][&champion=64]

  mode     : sr | aram | arena. Default sr. Anything else -> 400.
  window   : recent-game window, int 1..100. Default 20. Non-int or
             out-of-range -> 400.
  champion : optional champion id (Riot integer ``key``) to filter the
             history to one champion. Non-int -> 400. Omitted -> null.

Response is ``compute_gpi(...)``'s dict plus ``champions`` (the operator's
played-champion pool for ``mode`` as ``[{champion_id, n_games}, ...]`` newest
first - powers the per-champion drilldown selector), ``cached`` (bool) and
``elapsed_ms`` (int). See ``core.player_gpi._empty`` for the axis shape.
The compute dict includes ``this_match`` (newest filtered game scored per
axis vs the full history; null when insufficient) - it passes through here
untouched, cache included.

Cache: 5min in-process LRU keyed by (mode, window, champion). The compute
is a full scan + percentile pass over the rewind db; a panel that re-polls
on a timer would otherwise turn that into a DB hot loop.

Failure modes (a raw exception string is NEVER leaked to the client):
  - bad mode / window / champion -> 400 with a short clear error
  - compute raised (db unavailable) -> 503 structured error
  - any other exception -> 500 structured error; the raw text is logged.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from core import draft_elo_db, player_gpi
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

_VALID_MODES = ("sr", "aram", "arena")
_WINDOW_MIN = 1
_WINDOW_MAX = 100

_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
# Mirror routes_draft_elo: TTL only gates serving, so cap + drop-oldest
# keeps the dict bounded across long uptimes.
_CACHE_MAX = 256
_CACHE_EVICT = 64


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(),
                             key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _parse_mode(raw: str) -> tuple[str, str | None]:
    if not raw:
        return ("sr", None)
    if raw not in _VALID_MODES:
        return ("", f"mode must be one of {', '.join(_VALID_MODES)}")
    return (raw, None)


def _parse_window(raw: str) -> tuple[int, str | None]:
    if not raw:
        return (player_gpi.DEFAULT_WINDOW, None)
    try:
        w = int(raw)
    except ValueError:
        return (0, f"window must be an integer, got {raw!r}")
    if w < _WINDOW_MIN or w > _WINDOW_MAX:
        return (0, f"window must be {_WINDOW_MIN}..{_WINDOW_MAX}, got {w}")
    return (w, None)


def _parse_champion(raw: str) -> tuple[int | None, str | None]:
    if not raw:
        return (None, None)
    try:
        return (int(raw), None)
    except ValueError:
        return (None, f"champion must be an integer, got {raw!r}")


def _compute(mode: str, window: int, champion: int | None) -> dict:
    # One RO connection shared by the GPI compute + the champion-pool list so a
    # single uncached request opens the db once. compute_gpi/list_champions both
    # leave a caller-supplied conn open (own=False); the route owns the close.
    conn = draft_elo_db.open_ro()
    try:
        payload = player_gpi.compute_gpi(
            mode=mode, window=window, champion=champion, conn=conn)
        payload["champions"] = player_gpi.list_champions(mode, conn=conn)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    return payload


def _serve_player_profile(h) -> None:
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        mode_raw = (qs.get("mode") or [""])[0].strip()
        window_raw = (qs.get("window") or [""])[0].strip()
        champ_raw = (qs.get("champion") or [""])[0].strip()

        mode, err = _parse_mode(mode_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return
        window, err = _parse_window(window_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return
        champion, err = _parse_champion(champ_raw)
        if err:
            h._send(400, json.dumps({"ok": False, "error": err})
                    .encode("utf-8"), "application/json")
            return

        key = (mode, window, champion)
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

        try:
            payload = _compute(mode, window, champion)
        except Exception as exc:  # noqa: BLE001
            log.warning("api/player-profile compute: %s", exc)
            h._send(503, json.dumps(
                {"ok": False, "error": "rewind history unavailable"}
            ).encode("utf-8"), "application/json")
            return

        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)

        cacheable = dict(payload)
        cacheable.pop("cached", None)
        cacheable.pop("elapsed_ms", None)
        _cache_put(key, now, cacheable)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/player-profile: %s", exc)
        try:
            # Raw exception text stays in the log only.
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
    (equals("/api/player-profile"), _serve_player_profile),
]

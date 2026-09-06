# arch: player-scouting backend (rank fan-out) | section=dashboard | frozen=no
"""POST /api/scouting - per-player solo-queue rank for a roster of puuids.

RC 2.0 E9 player-scouting backend (phase 1: ranks only). Given a
champ-select or live roster's puuids, return each player's solo-queue
rank via the Riot Web API (ADR-006, core/riot_api.py). NO web render this
pass - this is JSON-only; the champ-select UI consumes it in a later
pass. Mains / tags are FUTURE.

Why POST: the roster is a list of up to 10 puuids supplied by the caller
(the LCU agent already forwards the champ-select roster). A POST body is
the natural carrier and avoids a giant query string.

Rate-limit awareness (Riot Personal-tier 20/s + 100/2min, ADR-006):
  - core.riot_api owns the dual token bucket + a 5-min TTL rank cache, so
    repeat lookups of the same puuid inside 5 min cost zero API calls.
  - This route adds a small per-puuid result cache (TTL) so a re-poll of
    the same roster is served entirely locally.
  - The fan-out is CAPPED at 10 distinct puuids per request (a full
    lobby) so a malformed / oversized body can never blow the bucket.
  - Each puuid is resolved independently; one failure fails THAT player
    soft to "unranked + error", never the whole batch.

Response:
  {
    "ok":      true,
    "players": [
      {"puuid": "...", "ranked": true,  "tier": "DIAMOND",
       "division": "IV", "lp": 12, "queue": "RANKED_SOLO_5x5",
       "wins": 40, "losses": 35, "win_rate_pct": 53,
       "display": "DIAMOND IV 12 LP", "cached": false},
      {"puuid": "...", "ranked": false, "tier": null, ...,
       "display": "Unranked", "cached": false}
    ],
    "capped":    false,   # true when the request exceeded the 10-cap
    "elapsed_ms": 12
  }

Degraded (Riot key absent): {"ok": false, "reason": "riot_key_unconfigured",
"players": []} with HTTP 200 - the dashboard renders a friendly empty
state, never a raw error (see CLAUDE.md Error Handling).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional

from core import riot_api
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# Hard cap on the per-request fan-out (a full 5v5 lobby is 10 players).
_MAX_FANOUT = 10

# Per-puuid result cache. core.riot_api already TTL-caches the raw
# League-V4 entries for 5 min; this caches the *shaped* result so a roster
# re-poll is fully local. Keyed by puuid -> (cached_at, shaped_dict).
_RANK_TTL_S = 300.0
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
# Bound the cache (puuids are unbounded over a long uptime). Drop-oldest.
_CACHE_MAX = 512
_CACHE_EVICT = 128


def _reset_cache_for_tests() -> None:
    """Test-only: clear the scouting result cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _cache_get(puuid: str, now: float) -> Optional[dict]:
    with _CACHE_LOCK:
        hit = _CACHE.get(puuid)
        if hit and (now - hit[0]) < _RANK_TTL_S:
            return hit[1]
    return None


def _cache_put(puuid: str, now: float, shaped: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[puuid] = (now, shaped)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)


def _unranked(puuid: str, *, error: bool = False) -> dict:
    """Graceful per-player unranked dict. Never fabricates a rank."""
    out = {
        "puuid": puuid,
        "ranked": False,
        "tier": None,
        "division": None,
        "lp": None,
        "queue": None,
        "wins": None,
        "losses": None,
        "win_rate_pct": None,
        "display": "Unranked",
        "cached": False,
    }
    if error:
        out["error"] = True
    return out


def _shape_rank(puuid: str, entries: Any) -> dict:
    """Shape a League-V4 entry list into a per-player scouting dict.

    Picks the solo-queue entry (falling back to highest-tier ranked
    entry) via core.riot_api.pick_solo_rank. An empty / None list, or an
    entry with no tier, yields the graceful unranked dict.
    """
    if not entries:
        return _unranked(puuid)
    entry = riot_api.pick_solo_rank(entries)
    if not isinstance(entry, dict):
        return _unranked(puuid)
    tier = str(entry.get("tier") or "").strip().upper()
    if not tier or tier in ("NONE", "UNRANKED"):
        return _unranked(puuid)
    division = str(entry.get("rank") or "").strip().upper()
    lp = entry.get("leaguePoints")
    lp = int(lp) if isinstance(lp, (int, float)) else 0
    wins = int(entry.get("wins") or 0)
    losses = int(entry.get("losses") or 0)
    total = wins + losses
    return {
        "puuid": puuid,
        "ranked": True,
        "tier": tier,
        "division": division or None,
        "lp": lp,
        "queue": str(entry.get("queueType") or "").upper() or None,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(100.0 * wins / total) if total > 0 else None,
        # format_rank_entry gives "DIAMOND IV 12 LP".
        "display": riot_api.format_rank_entry(entry) or "Unranked",
        "cached": False,
    }


def _scout_one(puuid: str, now: float) -> dict:
    """Resolve one puuid's rank, cache-first, fail-soft.

    A raised exception from the Riot layer fails THIS player to
    unranked-with-error so the batch always completes. The guard covers
    the SHAPE as well as the fetch: _shape_rank coerces the League-V4
    wire fields bare (``int(entry.get("wins") or 0)`` and its losses
    twin) and calls back into riot_api for pick_solo_rank /
    format_rank_entry, so a malformed entry raised from there. Callers
    build the batch with a list comprehension, so an escape cost every
    OTHER player's rank too, not just this one (RM-349 sibling).
    """
    cached = _cache_get(puuid, now)
    if cached is not None:
        out = dict(cached)
        out["cached"] = True
        return out
    try:
        entries = riot_api.get_summoner_rank(puuid)
        shaped = _shape_rank(puuid, entries)
    except Exception as exc:  # noqa: BLE001 - one bad player must not break batch
        log.warning("api/scouting: rank resolve failed for a player: %s", exc)
        return _unranked(puuid, error=True)
    try:
        _cache_put(puuid, now, dict(shaped))
    except Exception as exc:  # noqa: BLE001 - a cache write must not cost a good row
        log.warning("api/scouting: rank cache write failed for a player: %s", exc)
    return shaped


def _extract_puuids(body: Any) -> list[str]:
    """Pull a clean, de-duped, order-preserving puuid list from the body."""
    if not isinstance(body, dict):
        return []
    raw = body.get("puuids")
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        p = item.strip()
        if not p or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _serve_scouting(h, body) -> None:
    """POST /api/scouting - route entry point."""
    t0 = time.time()
    try:
        if not riot_api.is_configured():
            payload = {
                "ok": False,
                "reason": "riot_key_unconfigured",
                "players": [],
                "elapsed_ms": int((time.time() - t0) * 1000),
            }
            h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
            return

        puuids = _extract_puuids(body)
        capped = len(puuids) > _MAX_FANOUT
        puuids = puuids[:_MAX_FANOUT]

        now = time.time()
        players = [_scout_one(p, now) for p in puuids]

        payload = {
            "ok": True,
            "players": players,
            "capped": capped,
            "elapsed_ms": int((time.time() - t0) * 1000),
        }
        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/scouting: %s", exc)
        try:
            # Raw exception text stays in the log only (Error Handling rule).
            h._send(500, json.dumps(
                {"ok": False, "error": "internal error - see logs",
                 "players": []}).encode("utf-8"), "application/json")
        except Exception:  # noqa: BLE001
            pass


GET_ROUTES: list = []
POST_ROUTES = [
    (equals("/api/scouting"), _serve_scouting),
]

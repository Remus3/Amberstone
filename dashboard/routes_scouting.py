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

Each player row also carries ``opening`` (RM-613, additive): the
core.opening_tendency metrics for that puuid from the local timeline DB
(each metric a shrunk rate dict or the '-' thin-sample sentinel), or None
when that computation failed.

Degraded (Riot key absent): {"ok": false, "reason": "riot_key_unconfigured",
"players": []} with HTTP 200 - the dashboard renders a friendly empty
state, never a raw error (see CLAUDE.md Error Handling).

Input contract (S144-T-592; this route is not a control endpoint, so a LAN
peer reaches it):
  - a puuid is one ``[A-Za-z0-9_-]{1,128}`` token after strip(); anything
    else is skipped exactly like a non-string entry - never fetched, echoed
    or cached. The walk over ``puuids`` stops once the cap is known.
  - a League-V4 entry whose tier, rank, leaguePoints, wins or losses has the
    wrong type or range (bool, negative, fractional, non-finite, a string
    count, markup) fails THAT player soft to unranked-with-error and is not
    cached; an ABSENT field keeps its old meaning (lp / counts 0, division
    None). A junk queueType reads as absent. A non-list entries value is an
    error, not "Unranked".
  - an opening-tendency result that is not a dict, or a per-player value
    that is not a dict of strict-JSON data (no NaN / inf), reads None for
    that row; the response body is always strict JSON.
  - cache ages and elapsed_ms use monotonic clocks; failure logs name the
    exception type only.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from typing import Any, Optional

from core import opening_tendency, riot_api
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

# One Riot puuid is 78 url-safe base64 characters; 128 is the same bound
# core/sgp_client.py uses for the same identifier.
_PUUID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
# League-V4 tier / division / queue tokens. The tier is NOT checked against
# a fixed ladder (Riot added EMERALD in 2023); it only has to be a plain
# upper-case word.
_TIER_RE = re.compile(r"[A-Z]{1,20}")
_DIVISION_RE = re.compile(r"[IVX]{1,4}")
_QUEUE_RE = re.compile(r"[A-Z0-9_]{1,40}")
# Wins, losses and LP far above anything real (and inside a JS safe int).
_MAX_COUNT = 1_000_000


class _BadEntryError(ValueError):
    """A League-V4 field with the wrong type or range (message = its name)."""


def _finite_clock(now: Any) -> Optional[float]:
    """``now`` as a finite float, else None (bool refused)."""
    if isinstance(now, bool) or not isinstance(now, (int, float)):
        return None
    try:
        now = float(now)
    except OverflowError:
        return None
    return now if math.isfinite(now) else None


def _reset_cache_for_tests() -> None:
    """Test-only: clear the scouting result cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _cache_get(puuid: str, now: float) -> Optional[dict]:
    """A cached shaped row younger than _RANK_TTL_S, else None. An entry
    stamped AFTER ``now`` (a clock that stepped back) is a miss, not fresh."""
    now = _finite_clock(now)
    if now is None:
        return None
    with _CACHE_LOCK:
        hit = _CACHE.get(puuid)
        if hit and 0.0 <= (now - hit[0]) < _RANK_TTL_S:
            return hit[1]
    return None


def _cache_put(puuid: str, now: float, shaped: dict) -> None:
    now = _finite_clock(now)
    if now is None:
        return
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


def _rate_limited(puuid: str) -> dict:
    """Per-player dict for a Riot rate limit. Same keys as `_unranked` plus
    `rate_limited: True`; `display` is a friendly message, never the raw
    status. Deliberately NOT cached, so the next poll re-asks Riot."""
    out = _unranked(puuid)
    out["rate_limited"] = True
    out["display"] = "Rate limited - retrying"
    return out


def _shape_rank(puuid: str, entries: Any) -> dict:
    """Shape a League-V4 entry list into a per-player scouting dict.

    Picks the solo-queue entry (falling back to highest-tier ranked
    entry) via core.riot_api.pick_solo_rank. An empty / None list, or an
    entry with no tier, yields the graceful unranked dict.

    Raises _BadEntryError when entries is not a list or a rank field has the
    wrong type or range; _scout_one turns that into unranked-with-error
    and does not cache it. Absent fields keep their old meaning.
    """
    if entries is None:
        return _unranked(puuid)
    if not isinstance(entries, list):
        raise _BadEntryError("entries")
    if not entries:
        return _unranked(puuid)
    entry = riot_api.pick_solo_rank(entries)
    if not isinstance(entry, dict):
        return _unranked(puuid)
    tier = _token(entry, "tier", _TIER_RE)
    if not tier or tier in ("NONE", "UNRANKED"):
        return _unranked(puuid)
    division = _token(entry, "rank", _DIVISION_RE)
    lp = _count(entry, "leaguePoints")
    wins = _count(entry, "wins")
    losses = _count(entry, "losses")
    total = wins + losses
    queue = entry.get("queueType")
    queue = queue.strip().upper() if isinstance(queue, str) else ""
    # format_rank_entry gives "DIAMOND IV 12 LP"; it is handed only the
    # validated fields, so it can neither raise on nor echo a junk value.
    # An absent leaguePoints still renders without the LP part.
    display = riot_api.format_rank_entry({
        "tier": tier,
        "rank": division,
        "leaguePoints": None if entry.get("leaguePoints") is None else lp,
    })
    return {
        "puuid": puuid,
        "ranked": True,
        "tier": tier,
        "division": division or None,
        "lp": lp,
        "queue": queue if _QUEUE_RE.fullmatch(queue) else None,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(100.0 * wins / total) if total > 0 else None,
        "display": display or "Unranked",
        "cached": False,
    }


def _token(entry: dict, key: str, pattern: "re.Pattern[str]") -> str:
    """A League-V4 text field stripped and upper-cased; "" when absent or
    blank. Any other type, or text the pattern refuses, raises _BadEntryError."""
    value = entry.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _BadEntryError(key)
    value = value.strip().upper()
    if value and not pattern.fullmatch(value):
        raise _BadEntryError(key)
    return value


def _count(entry: dict, key: str) -> int:
    """A League-V4 non-negative integer (wins / losses / leaguePoints); 0
    when absent. A bool, string, fractional, non-finite, negative or
    implausibly large value raises _BadEntryError."""
    value = entry.get(key)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _BadEntryError(key)
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise _BadEntryError(key)
        value = int(value)
    if not 0 <= value <= _MAX_COUNT:
        raise _BadEntryError(key)
    return int(value)


def _scout_one(puuid: str, now: float) -> dict:
    """Resolve one puuid's rank, cache-first, fail-soft.

    A raised exception from the Riot layer fails THIS player to
    unranked-with-error so the batch always completes. The guard covers
    the SHAPE as well as the fetch: _shape_rank raises _BadEntryError on a
    malformed League-V4 field (S144-T-592) and calls back into riot_api
    for pick_solo_rank / format_rank_entry, either of which can raise on
    a malformed entry; such a row is never cached. Callers
    build the batch with a list comprehension, so an escape cost every
    OTHER player's rank too, not just this one (RM-349 sibling).
    """
    cached = _cache_get(puuid, now)
    if cached is not None:
        out = dict(cached)
        out["cached"] = True
        return out
    try:
        with riot_api.track_outcomes() as scope:
            entries = riot_api.get_summoner_rank(puuid)
        if entries is None and scope.rate_limited:
            # A throttle is not an answer about the player. Shaping it as
            # "Unranked" fabricated a rank, and caching it pinned the
            # fabrication for _RANK_TTL_S. Raw outcome goes to the log only.
            log.info("api/scouting: Riot API rate limited (outcomes=%s)",
                     ",".join(scope.outcomes))
            return _rate_limited(puuid)
        shaped = _shape_rank(puuid, entries)
    except Exception as exc:  # noqa: BLE001 - one bad player must not break batch
        log.warning("api/scouting: rank resolve failed for a player: %s",
                    type(exc).__name__)
        return _unranked(puuid, error=True)
    try:
        _cache_put(puuid, now, dict(shaped))
    except Exception as exc:  # noqa: BLE001 - a cache write must not cost a good row
        log.warning("api/scouting: rank cache write failed for a player: %s",
                    type(exc).__name__)
    return shaped


def _extract_puuids(body: Any) -> list[str]:
    """Pull a clean, de-duped, order-preserving puuid list from the body.

    Only a str matching _PUUID_RE after strip() is kept; anything else is
    skipped. The walk stops at _MAX_FANOUT + 1 kept puuids - enough for the
    caller to know the request was capped - so a long list is never read to
    its end.
    """
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
        if not _PUUID_RE.fullmatch(p) or p in seen:
            continue
        seen.add(p)
        out.append(p)
        if len(out) > _MAX_FANOUT:
            break
    return out


def _strict_json_copy(value: Any) -> Optional[dict]:
    """A private copy of one player's opening metrics, or None when it is
    not a dict of strict-JSON data (a NaN / inf would put a bare NaN token
    in the body, which JSON.parse refuses)."""
    if not isinstance(value, dict):
        return None
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError, RecursionError):
        return None


def _attach_opening(players: list, puuids: list[str]) -> None:
    """RM-613: additive per-player ``opening`` field (core.opening_tendency).

    Local rewind_history.db read only - zero Riot API calls, so it does not
    touch the rank rate limit. Runs over the already-CAPPED puuid list. A
    failure sets ``opening: None`` on every row and never costs a rank. The
    field is added to the per-request copies, never to the rank cache.
    """
    try:
        by_puuid = opening_tendency.opening_tendencies(puuids)
    except Exception as exc:  # noqa: BLE001 - opening is best-effort
        log.warning("api/scouting: opening tendencies failed: %s",
                    type(exc).__name__)
        by_puuid = {}
    if not isinstance(by_puuid, dict):
        log.warning("api/scouting: opening tendencies returned %s, not a dict",
                    type(by_puuid).__name__)
        by_puuid = {}
    for row in players:
        row["opening"] = _strict_json_copy(by_puuid.get(row.get("puuid")))


def _elapsed_ms(t0: float) -> int:
    return max(0, int((time.perf_counter() - t0) * 1000))


def _json_body(payload: dict) -> bytes:
    """Strict JSON: a non-finite float raises instead of emitting NaN."""
    return json.dumps(payload, allow_nan=False).encode("utf-8")


def _serve_scouting(h, body) -> None:
    """POST /api/scouting - route entry point."""
    t0 = time.perf_counter()
    try:
        if not riot_api.is_configured():
            payload = {
                "ok": False,
                "reason": "riot_key_unconfigured",
                "players": [],
                "elapsed_ms": _elapsed_ms(t0),
            }
            h._send(200, _json_body(payload), "application/json")
            return

        puuids = _extract_puuids(body)
        capped = len(puuids) > _MAX_FANOUT
        puuids = puuids[:_MAX_FANOUT]

        # Monotonic: a wall clock stepped back must not keep a cached row
        # past its TTL (the cache also refuses an entry stamped later).
        now = time.monotonic()
        players = [_scout_one(p, now) for p in puuids]
        _attach_opening(players, puuids)

        payload = {
            "ok": True,
            "players": players,
            "capped": capped,
            "elapsed_ms": _elapsed_ms(t0),
        }
        h._send(200, _json_body(payload), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/scouting: request failed: %s", type(exc).__name__)
        try:
            # Raw exception text stays out of the body and the log.
            h._send(500, _json_body(
                {"ok": False, "error": "internal error - see logs",
                 "players": []}), "application/json")
        except Exception:  # noqa: BLE001
            pass


GET_ROUTES: list = []
POST_ROUTES = [
    (equals("/api/scouting"), _serve_scouting),
]

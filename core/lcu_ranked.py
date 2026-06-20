# arch: LCU ranked-stats read for the rank-identity header | section=core | frozen=no
"""Read the local player's ranked tier / division / LP from the LCU.

RC 2.0 E9 (rank-identity header). Single source for the operator's own
solo-queue rank, used by the dashboard home header. The operator plays
mostly ARAM / Arena / event modes, so solo-queue rank is frequently
STALE or UNRANKED - the graceful "Unranked" state is a first-class path
here and we NEVER fabricate a rank when one is absent.

Endpoint (verified against the canonical LCU swagger, 2026-06-20):

  GET /lol-ranked/v1/current-ranked-stats  ->  LolRankedRankedStats
    queueMap            : object keyed by queue type
                          (RANKED_SOLO_5x5, RANKED_FLEX_SR, ...)
    highestRankedEntry  : LolRankedRankedQueueStats

  Per-queue entry (LolRankedRankedQueueStats):
    queueType (str)  tier (str)  division (str)  leaguePoints (int)
    wins (int)  losses (int)  isProvisional (bool)

  Unranked queues report tier "NONE" (or "") and division "NA".

This reads the *local* client over the LCU (no Riot Web API, no key) -
that is the cheap, always-current source for the operator's own rank.
The Riot Web API path (core/riot_api.py) is reserved for scouting OTHER
players (ADR-006); this module is local-only.

Soft-fail invariants:
  - ``lcu`` is None, or its ``_request`` returns None / a non-dict -> the
    caller gets ``None`` (LCU not reachable; the home builder then renders
    the graceful "Unranked" placeholder rather than a missing key).
  - A reachable client with an unranked / empty queueMap -> a dict with
    ``ranked = False`` and ``display = "Unranked"`` (definitively unranked,
    distinct from "could not read").
"""
from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger("rc.lcu.ranked")

RANKED_STATS_ENDPOINT = "/lol-ranked/v1/current-ranked-stats"

# Queue we surface in the identity header. Solo is the canonical "rank".
_SOLO_QUEUE = "RANKED_SOLO_5x5"

# Tier strings the LCU uses to mean "no rank in this queue".
_UNRANKED_TIERS = {"", "NONE", "UNRANKED"}


def _empty(provisional: bool = False, games: int = 0) -> dict:
    """The graceful unranked identity dict.

    ``ranked`` False with every rank field None so a consumer can splat
    it without guessing. ``display`` is a short ASCII header string.
    """
    if provisional:
        display = f"Placements ({int(games)} played)"
    else:
        display = "Unranked"
    return {
        "ranked": False,
        "provisional": bool(provisional),
        "tier": None,
        "division": None,
        "lp": None,
        "queue": None,
        "wins": int(games) if provisional else None,
        "losses": None,
        "win_rate_pct": None,
        "display": display,
    }


def _format_display(tier: str, division: str, lp: int) -> str:
    """"PLATINUM II 47 LP" - tier, optional division, LP. ASCII only.

    Apex tiers (MASTER / GRANDMASTER / CHALLENGER) have no meaningful
    division ("NA"/"I"); we drop a "NA" division but keep a real one.
    """
    parts = [tier]
    div = (division or "").strip().upper()
    if div and div != "NA":
        parts.append(div)
    parts.append(f"{int(lp)} LP")
    return " ".join(parts)


def parse_ranked_stats(payload: Any) -> Optional[dict]:
    """Parse a current-ranked-stats payload into the identity dict.

    Returns None when ``payload`` is not a dict (caller treats as
    "could not read"). Returns the graceful unranked dict when the
    payload is well-formed but the solo queue is absent / unranked.
    Split out from the LCU read so it is trivially unit-testable.
    """
    if not isinstance(payload, dict):
        return None
    queue_map = payload.get("queueMap")
    if not isinstance(queue_map, dict):
        # A reachable client that gave us no queue map - treat as unranked.
        return _empty()
    entry = queue_map.get(_SOLO_QUEUE)
    if not isinstance(entry, dict):
        return _empty()

    tier = str(entry.get("tier") or "").strip().upper()
    wins = int(entry.get("wins") or 0)
    losses = int(entry.get("losses") or 0)
    provisional = bool(entry.get("isProvisional"))

    if tier in _UNRANKED_TIERS:
        # Surface placement progress if mid-placements, else plain unranked.
        if provisional and (wins + losses) > 0:
            return _empty(provisional=True, games=wins + losses)
        return _empty()

    division = str(entry.get("division") or "").strip().upper()
    lp = int(entry.get("leaguePoints") or 0)
    total = wins + losses
    win_rate_pct = round(100.0 * wins / total) if total > 0 else None

    return {
        "ranked": True,
        "provisional": provisional,
        "tier": tier,
        "division": division or None,
        "lp": lp,
        "queue": _SOLO_QUEUE,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": win_rate_pct,
        "display": _format_display(tier, division, lp),
    }


def read_ranked_identity(lcu: Any) -> Optional[dict]:
    """Read the operator's solo-queue rank identity via the LCU.

    ``lcu`` is an ``lcu.lcu_client.LcuClient`` (or any object exposing the
    same ``_request(method, endpoint)`` contract). Returns:

      * the parsed identity dict (``ranked`` True/False) on a successful
        read, or
      * ``None`` when the client is missing / not connected / errored -
        the home builder maps this to the graceful "Unranked" placeholder.

    Never raises - any unexpected error fails soft to ``None``.
    """
    if lcu is None:
        return None
    try:
        payload = lcu._request("GET", RANKED_STATS_ENDPOINT)
    except Exception as exc:  # noqa: BLE001 - read must never fault caller
        log.debug("read_ranked_identity: LCU read failed: %s", exc)
        return None
    if payload is None:
        return None
    return parse_ranked_stats(payload)


__all__ = [
    "RANKED_STATS_ENDPOINT",
    "parse_ranked_stats",
    "read_ranked_identity",
]

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
  - A dict with no ``queueMap`` object (an empty 2xx body, an error-shaped
    body, a renamed field) is also ``None``: "could not read", never
    "definitively unranked".
  - A reachable client with an unranked / empty queueMap -> a dict with
    ``ranked = False`` and ``display = "Unranked"`` (definitively unranked,
    distinct from "could not read").

Wire validation (s144 true-audit). The payload is bytes RC did not author,
and the header renders ``display`` and puts ``tier`` in a data attribute:
  - ``tier`` must be a str that is, after trimming spaces and upper-casing,
    1-16 ASCII letters; a null / absent tier is unranked, as before. Any
    other value means the rank cannot be named, so the parse is ``None``
    (could not read). An unknown but well-formed tier
    is kept - Riot added EMERALD in 2023 and will add more.
  - ``division`` is kept only when it is I / II / III / IV; "NA", junk and
    any division on an apex tier (MASTER / GRANDMASTER / CHALLENGER, which
    the client reports as "I") are dropped from the dict and the display.
  - ``leaguePoints`` / ``wins`` / ``losses`` are counts: an int (never a
    bool) or an integral finite float, 0..100000. A null or empty value is
    0 (the historical ``or 0`` absorb, kept). Any other value drops THAT
    field to None and nothing else - the tier and division survive, and the
    win rate is reported only when both counts are good.
  - ``isProvisional`` is provisional only when it is the JSON ``true``.
  - Every dropped value and every could-not-read is warned once per streak
    on ``rc.lcu.ranked``, naming the field and the value's TYPE only, never
    the value; a clean read ends the streak.
"""
from __future__ import annotations

import logging
import math
import re
import threading
from typing import Any, Optional

log = logging.getLogger("rc.lcu.ranked")

RANKED_STATS_ENDPOINT = "/lol-ranked/v1/current-ranked-stats"

# Queue we surface in the identity header. Solo is the canonical "rank".
_SOLO_QUEUE = "RANKED_SOLO_5x5"

# Tier strings the LCU uses to mean "no rank in this queue".
_UNRANKED_TIERS = {"", "NONE", "UNRANKED"}

# A nameable tier: a short ASCII word. Checked AFTER the isascii test,
# because str.upper() maps some non-ASCII letters to ASCII ones.
_TIER_RE = re.compile(r"[A-Z]{1,16}")
_DIVISIONS = frozenset({"I", "II", "III", "IV"})
_APEX_TIERS = frozenset({"MASTER", "GRANDMASTER", "CHALLENGER"})

# Ceiling for a count field. Real LP tops out in the low thousands and a
# season is a few thousand games at most; anything past this is junk.
_MAX_COUNT = 100_000

_warn_lock = threading.Lock()
_warned_key: Optional[tuple] = None


def _reset_warnings() -> None:
    """Forget the current warn streak (tests)."""
    global _warned_key
    with _warn_lock:
        _warned_key = None


def _note(reasons: list) -> None:
    """Warn once per streak of identical problems; a clean read ends it."""
    global _warned_key
    key = tuple(reasons) if reasons else None
    with _warn_lock:
        if key == _warned_key:
            return
        _warned_key = key
    if key is not None:
        log.warning("rank identity: %s (warned once per streak)",
                    "; ".join(key))


def _type_name(value: Any) -> str:
    return type(value).__name__


def _count(value: Any) -> tuple:
    """(int or None, dropped) for a leaguePoints / wins / losses value.

    None and an empty str / list / dict are 0 (the historical ``or 0``).
    """
    if value is None:
        return 0, False
    if isinstance(value, bool):
        return None, True
    if isinstance(value, int):
        return (value, False) if 0 <= value <= _MAX_COUNT else (None, True)
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer() and 0 <= value <= _MAX_COUNT:
            return int(value), False
        return None, True
    if isinstance(value, (str, list, dict, tuple)) and len(value) == 0:
        return 0, False
    return None, True


def _tier(value: Any) -> Optional[str]:
    """The upper-cased tier, "" for unranked, or None when unnameable.

    A null / absent tier is unranked, as it always was (``or ""``)."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return None
    text = value.strip(" ")
    if not text.isascii():
        return None
    text = text.upper()
    if text in _UNRANKED_TIERS:
        return ""
    return text if _TIER_RE.fullmatch(text) else None


def _division(value: Any, tier: str) -> tuple:
    """(division or None, dropped). Apex tiers and "NA" carry none."""
    if value is None:
        return None, False
    if not isinstance(value, str) or not value.isascii():
        return None, True
    text = value.strip(" ").upper()
    if text in ("", "NA") or tier in _APEX_TIERS:
        return None, False
    if text in _DIVISIONS:
        return text, False
    return None, True


def _empty(provisional: bool = False, wins: Optional[int] = None,
           losses: Optional[int] = None) -> dict:
    """The graceful unranked identity dict.

    ``ranked`` False with every rank field None so a consumer can splat
    it without guessing. ``display`` is a short ASCII header string. A
    placements entry keeps its real wins and losses (each None if junk).
    """
    if provisional:
        played = (wins or 0) + (losses or 0)
        display = f"Placements ({played} played)"
    else:
        display = "Unranked"
        wins = losses = None
    return {
        "ranked": False,
        "provisional": bool(provisional),
        "tier": None,
        "division": None,
        "lp": None,
        "queue": None,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": None,
        "display": display,
    }


def _format_display(tier: str, division: Optional[str], lp: Optional[int]) -> str:
    """"PLATINUM II 47 LP" - tier, optional division, optional LP. ASCII
    only, because every part was validated before it got here."""
    parts = [tier]
    if division:
        parts.append(division)
    if lp is not None:
        parts.append(f"{lp} LP")
    return " ".join(parts)


def _parse(payload: Any) -> tuple:
    """(identity dict or None, list of warn reasons). Never raises."""
    if not isinstance(payload, dict):
        return None, []
    queue_map = payload.get("queueMap")
    if not isinstance(queue_map, dict):
        return None, [f"queueMap is {_type_name(queue_map)}, not an object"]
    entry = queue_map.get(_SOLO_QUEUE)
    if not isinstance(entry, dict):
        if entry is None:
            return _empty(), []
        return _empty(), [f"{_SOLO_QUEUE} entry is {_type_name(entry)}"]

    reasons: list = []
    raw_tier = entry.get("tier")
    tier = _tier(raw_tier)
    if tier is None:
        return None, [f"tier unreadable ({_type_name(raw_tier)})"]

    counts = {}
    for field in ("leaguePoints", "wins", "losses"):
        raw = entry.get(field)
        counts[field], dropped = _count(raw)
        if dropped:
            reasons.append(f"{field} dropped ({_type_name(raw)})")
    wins, losses = counts["wins"], counts["losses"]

    raw_flag = entry.get("isProvisional")
    provisional = raw_flag is True
    if raw_flag is not None and not isinstance(raw_flag, bool):
        reasons.append(f"isProvisional ignored ({_type_name(raw_flag)})")

    if tier == "":
        # Surface placement progress if mid-placements, else plain unranked.
        if provisional and (wins or 0) + (losses or 0) > 0:
            return _empty(provisional=True, wins=wins, losses=losses), reasons
        return _empty(), reasons

    raw_div = entry.get("division")
    division, dropped = _division(raw_div, tier)
    if dropped:
        reasons.append(f"division dropped ({_type_name(raw_div)})")

    lp = counts["leaguePoints"]
    win_rate_pct = None
    if wins is not None and losses is not None and wins + losses > 0:
        win_rate_pct = round(100.0 * wins / (wins + losses))

    return {
        "ranked": True,
        "provisional": provisional,
        "tier": tier,
        "division": division,
        "lp": lp,
        "queue": _SOLO_QUEUE,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": win_rate_pct,
        "display": _format_display(tier, division, lp),
    }, reasons


def parse_ranked_stats(payload: Any) -> Optional[dict]:
    """Parse a current-ranked-stats payload into the identity dict.

    Returns None when ``payload`` is not a dict, has no ``queueMap``
    object, or names a tier that cannot be read (caller treats all three
    as "could not read"). Returns the graceful unranked dict when the
    payload is well-formed but the solo queue is absent / unranked. A junk
    division or count drops that field only (module docstring). Pure and
    silent - ``read_ranked_identity`` does the warning. Never raises.
    """
    return _parse(payload)[0]


def read_ranked_identity(lcu: Any) -> Optional[dict]:
    """Read the operator's solo-queue rank identity via the LCU.

    ``lcu`` is an ``lcu.lcu_client.LcuClient`` (or any object exposing the
    same ``_request(method, endpoint)`` contract). Returns:

      * the parsed identity dict (``ranked`` True/False) on a successful
        read, or
      * ``None`` when the client is missing / not connected / errored, or
        the payload could not be read - the home builder maps this to the
        graceful "Unranked" placeholder.

    Never raises - any unexpected error fails soft to ``None``. That covers
    the PARSE as well as the read: the sole consumer assigns the rank field
    before its own try block, so an escape here costs the whole home
    payload rather than one degraded field (RM-349). The parse validates
    every wire field itself now; the except around it is a backstop.

    A not-connected client (``_request`` returns None) is the normal state
    while League is closed and is never warned. A raising read, an
    unreadable payload and every dropped field are warned once per streak,
    naming exception and value TYPES only - an exception message can quote
    a request header, and a wire value is not RC's text.
    """
    if lcu is None:
        return None
    try:
        payload = lcu._request("GET", RANKED_STATS_ENDPOINT)
    except Exception as exc:  # noqa: BLE001 - read must never fault caller
        _note([f"LCU read raised {_type_name(exc)}"])
        return None
    if payload is None:
        return None
    try:
        result, reasons = _parse(payload)
    except Exception as exc:  # noqa: BLE001 - parse must never fault caller
        result, reasons = None, [f"ranked payload parse raised {_type_name(exc)}"]
    if result is None and not reasons:
        reasons = [f"ranked payload is {_type_name(payload)}, not an object"]
    _note(reasons)
    return result


__all__ = [
    "RANKED_STATS_ENDPOINT",
    "parse_ranked_stats",
    "read_ranked_identity",
]

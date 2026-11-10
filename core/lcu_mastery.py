# arch: key-free champion mastery for any PUUID via the LCU | section=core | frozen=no
"""Key-free champion mastery for ANY player, straight from the client.

RC already reads the LOCAL player's mastery from the LCU
(``/lol-champion-mastery/v1/local-player/champion-mastery``). Every OTHER
party member currently goes through Riot's Champion-Mastery-V4 web API, which
costs three things this module does not:

  - a dev key, and the policy weight that comes with it
  - rate-limit budget on a live champ-select path
  - a PUUID resolution round trip that is a known 400 source once a stored
    PUUID has rotated

The client serves the same rows per-PUUID, locally, with none of that.

TRAP, recorded because it nearly cost a broken module: a 2024 plugin
(reviewed, MIT, operator-cleared) fetched mastery from
``/lol-collections/v1/inventories/{accountId}/champion-mastery`` keyed by the
legacy ``accountId``. That route is ABSENT from the current LCU surface.
Lifting it verbatim would have shipped a dead call that fails only at
runtime, against a live client. The live route is keyed by PUUID, and a test
asserts we build that one.

Kill switch: ``RC_LCU_MASTERY=0`` sends callers back to the web-API path.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable

_log = logging.getLogger(__name__)

# (method, endpoint) -> parsed JSON or None. The frozen lcu/lcu_client.py owns
# lockfile discovery, auth and rotation; this module never re-implements them.
# It concatenates the endpoint onto its base URL UNQUOTED, so anything this
# module puts into a route must already be a single safe path segment.
LcuRequest = Callable[[str, str], Any]

# A real PUUID is 78 characters of [A-Za-z0-9_-]. The alphabet is the trust
# boundary: "/", "?", "#", "%", "." and whitespace would re-target the read at
# another LCU route. The length cap leaves headroom over 78 without letting an
# arbitrary blob into a URL. Padding is stripped first; \Z (not $) makes the
# match cover the whole remaining string.
_PUUID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_COUNT_RE = re.compile(r"[0-9]{1,6}\Z")

# Upper bound for a top-N request: above the champion roster, so a larger
# count means "all of them" and is clamped rather than refused.
MAX_COUNT = 500


def lcu_mastery_enabled() -> bool:
    """False only when the operator sets RC_LCU_MASTERY=0."""
    return os.environ.get("RC_LCU_MASTERY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _clean_puuid(puuid: Any) -> str | None:
    """A stripped PUUID in the PUUID alphabet, or None."""
    if not isinstance(puuid, str):
        return None
    puuid = puuid.strip()
    return puuid if _PUUID_RE.match(puuid) else None


def _clean_count(count: Any) -> int | None:
    """A count in [1, MAX_COUNT], or None for junk / < 1.

    Accepts an int (never a bool; a larger int clamps to MAX_COUNT) or a
    string of one to six ASCII digits, padding allowed (a longer digit string
    is refused). A float, a sign, a non-ASCII digit or None is refused.
    """
    if isinstance(count, bool):
        return None
    if isinstance(count, str):
        text = count.strip()
        if not _COUNT_RE.match(text):
            return None
        count = int(text)
    if not isinstance(count, int) or count < 1:
        return None
    # int() so an int subclass (its own __format__) never reaches the URL.
    return min(int(count), MAX_COUNT)


def mastery_route(puuid: str) -> str:
    """Full mastery list for ``puuid``. PUUID-keyed, not accountId-keyed.

    Raises ValueError for a PUUID outside the PUUID alphabet.
    """
    clean = _clean_puuid(puuid)
    if clean is None:
        raise ValueError("puuid is not a PUUID")
    return f"/lol-champion-mastery/v1/{clean}/champion-mastery"


def top_route(puuid: str, count: int) -> str:
    """Top-N mastery rows for ``puuid``.

    Raises ValueError for a bad PUUID or a count ``_clean_count`` refuses;
    an int count above MAX_COUNT is clamped to it.
    """
    clean_count = _clean_count(count)
    if clean_count is None:
        raise ValueError("count is not a positive integer")
    return f"{mastery_route(puuid)}/top?count={clean_count}"


def normalize(payload: Any) -> list[dict]:
    """Client rows -> RC shape, sorted by points descending.

    Tolerates every malformed shape rather than raising: this sits on a live
    champ-select path where a partial client response must degrade, not throw.
    A row needs a positive int championId (a bool is not an id); a level or
    points value that is not a non-negative int (bool included) reads as 0. A
    champion listed twice keeps its highest-points row, once.
    """
    if not isinstance(payload, list):
        return []
    best: dict[int, dict] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        champion_id = item.get("championId")
        if type(champion_id) is not int or champion_id <= 0:
            continue
        row = {
            "champion_id": champion_id,
            "level": _as_int(item.get("championLevel")),
            "points": _as_int(item.get("championPoints")),
        }
        kept = best.get(champion_id)
        if kept is None or row["points"] > kept["points"]:
            best[champion_id] = row
    rows = list(best.values())
    rows.sort(key=lambda row: row["points"], reverse=True)
    return rows


def _as_int(value: Any) -> int:
    """A non-negative int, else 0 (a bool, float, string or negative is 0)."""
    return value if type(value) is int and value >= 0 else 0


def top_masteries(lcu_request: LcuRequest, puuid: str, count: int = 1) -> list[dict]:
    """Top ``count`` mastery rows for ``puuid``. Returns [] on any fault.

    Tries the dedicated top route first, then falls back to the full list and
    slices it, so a client build missing the top route still answers.

    A PUUID outside the PUUID alphabet, or a count that is not a positive
    integer, answers [] WITHOUT calling the client: the PUUID is a URL path
    segment, and a negative count would slice ``rows[:-n]`` (every row but the
    last n) instead of the top n.

    BOTH calls are GET. Both routes are reads, and the fallback below is the
    reason the verb matters more than it looks: a non-GET verb answers 405/404,
    ``normalize`` maps that non-list body to ``[]``, the falsy check falls
    through, and the full-list GET silently supplies the answer. The fast path
    would then never succeed against a real client while every caller, and
    every test, still saw correct rows - a guaranteed-failing round trip on a
    champ-select path, indistinguishable from the legitimate "this client build
    has no top route" case the fallback exists for.
    """
    clean_puuid = _clean_puuid(puuid)
    clean_count = _clean_count(count)
    if clean_puuid is None or clean_count is None:
        return []

    try:
        rows = normalize(lcu_request("GET", top_route(clean_puuid, clean_count)))
        if rows:
            return rows[:clean_count]
        rows = normalize(lcu_request("GET", mastery_route(clean_puuid)))
        return rows[:clean_count]
    except Exception as exc:  # noqa: BLE001 - a live panel degrades, never throws
        # The type only: the message can carry the endpoint, and the endpoint
        # carries the PUUID.
        _log.info("LCU mastery lookup failed (%s)", type(exc).__name__)
        return []

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
from typing import Any, Callable

_log = logging.getLogger(__name__)

# (method, endpoint) -> parsed JSON or None. The frozen lcu/lcu_client.py owns
# lockfile discovery, auth and rotation; this module never re-implements them.
LcuRequest = Callable[[str, str], Any]


def lcu_mastery_enabled() -> bool:
    """False only when the operator sets RC_LCU_MASTERY=0."""
    return os.environ.get("RC_LCU_MASTERY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def mastery_route(puuid: str) -> str:
    """Full mastery list for ``puuid``. PUUID-keyed, not accountId-keyed."""
    return f"/lol-champion-mastery/v1/{puuid}/champion-mastery"


def top_route(puuid: str, count: int) -> str:
    """Top-N mastery rows for ``puuid``."""
    return f"/lol-champion-mastery/v1/{puuid}/champion-mastery/top?count={int(count)}"


def normalize(payload: Any) -> list[dict]:
    """Client rows -> RC shape, sorted by points descending.

    Tolerates every malformed shape rather than raising: this sits on a live
    champ-select path where a partial client response must degrade, not throw.
    """
    if not isinstance(payload, list):
        return []
    rows: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        champion_id = item.get("championId")
        if not isinstance(champion_id, int):
            continue
        rows.append({
            "champion_id": champion_id,
            "level": _as_int(item.get("championLevel")),
            "points": _as_int(item.get("championPoints")),
        })
    rows.sort(key=lambda row: row["points"], reverse=True)
    return rows


def _as_int(value: Any) -> int:
    return value if isinstance(value, int) else 0


def top_masteries(lcu_request: LcuRequest, puuid: str, count: int = 1) -> list[dict]:
    """Top ``count`` mastery rows for ``puuid``. Returns [] on any fault.

    Tries the dedicated top route first, then falls back to the full list and
    slices it, so a client build missing the top route still answers.

    BOTH calls are GET. Both routes are reads, and the fallback below is the
    reason the verb matters more than it looks: a non-GET verb answers 405/404,
    ``normalize`` maps that non-list body to ``[]``, the falsy check falls
    through, and the full-list GET silently supplies the answer. The fast path
    would then never succeed against a real client while every caller, and
    every test, still saw correct rows - a guaranteed-failing round trip on a
    champ-select path, indistinguishable from the legitimate "this client build
    has no top route" case the fallback exists for.
    """
    if not puuid or not str(puuid).strip():
        return []
    puuid = str(puuid).strip()

    try:
        rows = normalize(lcu_request("GET", top_route(puuid, count)))
        if rows:
            return rows[:count]
        rows = normalize(lcu_request("GET", mastery_route(puuid)))
        return rows[:count]
    except Exception:  # noqa: BLE001 - a live panel degrades, never throws
        _log.info("LCU mastery lookup failed for %s", puuid[:8])
        return []

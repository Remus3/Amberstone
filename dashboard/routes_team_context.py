# arch: GET /api/team-context + POST /api/team-context/refresh | section=dashboard | frozen=no
"""Team-context routes for the FU02 champ-select 5+5 enrichment panel.

This module is the **panel stub** for FU02. The Riot API fan-out
(`core/riot_api.py`) hasn't shipped yet — until it does, the GET endpoint
returns whatever the most recent POST stored, and the POST is a passive
sink. Dashboard polls GET, renders skeleton rows when fields are empty.

Wire shape:
  POST /api/team-context/refresh  ← Game-PC LCU agent on ChampSelect
                                    transition. Body is the 10-player
                                    roster + queue_id. Bearer-auth via
                                    cross-Claude bridge token (same
                                    posture as routes_health_peer).
  GET  /api/team-context           ← Dashboard poll. No auth (loopback /
                                    Tailnet-only, served by HTTPS dashboard).

Storage: in-memory dict guarded by a Lock — single-process. The cache
survives RC reload because it's reset on supervisor restart, which is the
desired lifetime for a per-game enrichment payload.

Soft-fail invariants:
  - GET on cold cache returns `{"team_context": null}` (empty object,
    HTTP 200). Dashboard treats null as "not in champ-select".
  - POST with malformed body → 400; partial bodies (some fields missing)
    are stored as-is, schema validation is the caller's responsibility.
  - Auth failure → 401, no payload mutation.

Once `core/riot_api.py` ships (FU02 main work), this module gains
priority-1 dispatch (mastery + rank) on POST and priority-2 background
fan-out (mains + streak + recent winrate). The dashboard panel + payload
shape stays stable across that transition.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from core import bridge as _bridge
from dashboard._dispatch import equals

log = logging.getLogger("rc.routes_team_context")

# Module-level cache of the latest team_context payload. None when no
# champ-select has fired since RC boot. _state_builder reads this via
# get_team_context() to splice into /api/state.
_LOCK = threading.Lock()
_CACHE: dict[str, Any] | None = None
_CACHE_TS: float = 0.0

# Hard cap on stored roster size. The LCU agent forwards exactly 10
# players in champ-select; anything bigger is malformed.
_MAX_ROSTER = 10


def get_team_context() -> dict[str, Any] | None:
    """Return the latest stored team_context dict, or None if cache empty.
    Used by `dashboard._state_builder.build_state()` to splice into
    `/api/state.coach.team_context` during champ-select."""
    with _LOCK:
        return _CACHE


def _store(payload: dict[str, Any]) -> None:
    global _CACHE, _CACHE_TS
    with _LOCK:
        _CACHE = payload
        _CACHE_TS = time.time()


def _clear() -> None:
    """Reset the cache. Exposed for tests; not wired to a route yet."""
    global _CACHE, _CACHE_TS
    with _LOCK:
        _CACHE = None
        _CACHE_TS = 0.0


def _skeleton_entry(slot: dict[str, Any]) -> dict[str, Any]:
    """Build a TeamContextEntry-shaped dict from an LCU roster slot.

    Until the Riot API fan-out lands, the only fields we can populate
    from the LCU payload itself are puuid, summoner_name, team_id, and
    locked_champion. The rest stay at their soft-fail defaults so the
    dashboard renders skeleton rows.
    """
    return {
        "puuid":             str(slot.get("puuid") or ""),
        "summoner_name":     str(slot.get("summoner_name") or ""),
        "team_id":           int(slot.get("team_id") or 0),
        "locked_champion":   str(slot.get("locked_champion") or ""),
        "rank":              "",
        "mastery_on_locked": 0,
        "w_l_streak_7":      [0, 0],
        "mains":             [],
        "win_rate_recent":   0.0,
    }


def _serve_refresh_post(h, body) -> None:
    """POST /api/team-context/refresh — receive 10-player roster from
    Game-PC LCU agent on ChampSelect transition.

    Body shape:
        {
          "queue_id": 420,
          "roster": [
            {"puuid": "...", "summoner_name": "...", "team_id": 100,
             "locked_champion": "Camille"},
            ...
          ]
        }

    Auth: same Bearer secret as /api/bridge/inbox.
    """
    if not _bridge.is_configured():
        h._send(503, b'{"error":"bridge_not_configured"}', "application/json")
        return

    auth = (h.headers.get("Authorization") or "").strip()
    expected = "Bearer " + _bridge.shared_secret()
    if auth != expected:
        log.warning("team-context auth reject from %s", h.client_address[0])
        h._send(401, b'{"error":"unauthorized"}', "application/json")
        return

    if not isinstance(body, dict):
        h._send(400, b'{"error":"body_must_be_object"}', "application/json")
        return

    roster = body.get("roster") or []
    if not isinstance(roster, list):
        h._send(400, b'{"error":"roster_must_be_list"}', "application/json")
        return
    if len(roster) > _MAX_ROSTER:
        h._send(400,
                json.dumps({"error": "roster_too_large",
                            "max": _MAX_ROSTER,
                            "got": len(roster)}).encode(),
                "application/json")
        return

    queue_id = int(body.get("queue_id") or 0)
    allies: list[dict[str, Any]] = []
    enemies: list[dict[str, Any]] = []
    for slot in roster:
        if not isinstance(slot, dict):
            continue
        entry = _skeleton_entry(slot)
        # team_id 100=blue=allies-by-convention. The LCU agent stamps
        # this from `myTeam`/`theirTeam`; treat 100 as allies, 200 as
        # enemies. Anything else falls into allies as a soft default
        # so the dashboard still renders SOMETHING.
        if entry["team_id"] == 200:
            enemies.append(entry)
        else:
            allies.append(entry)

    payload = {
        "allies":       allies,
        "enemies":      enemies,
        "refreshed_at": time.strftime("%Y-%m-%dT%H:%M:%S",
                                      time.gmtime()) + "Z",
        "partial":      True,    # FU02 fan-out flips this to False
        "queue_id":     queue_id,
    }
    _store(payload)
    log.info("team-context refresh: queue=%d allies=%d enemies=%d",
             queue_id, len(allies), len(enemies))
    h._send(200, json.dumps({"ok": True,
                             "stored": {"allies": len(allies),
                                        "enemies": len(enemies)}}).encode(),
            "application/json")


def _serve_get(h) -> None:
    """GET /api/team-context — dashboard poll.

    Returns `{"team_context": <obj|null>, "age_s": <float>}`. Age is
    computed from the last successful refresh; null cache → age=null.
    """
    with _LOCK:
        cache = _CACHE
        ts = _CACHE_TS
    if cache is None:
        body = {"team_context": None, "age_s": None}
    else:
        body = {"team_context": cache,
                "age_s":         round(max(0.0, time.time() - ts), 1)}
    h._send(200, json.dumps(body).encode(), "application/json")


GET_ROUTES = [
    (equals("/api/team-context"),         _serve_get),
]

POST_ROUTES = [
    (equals("/api/team-context/refresh"), _serve_refresh_post),
]

# arch: GET /api/team-context + POST /api/team-context/refresh | section=dashboard | frozen=no
"""Team-context routes for the FU02 champ-select 5+5 enrichment panel.

Wire shape:
  POST /api/team-context/refresh  ← Game-PC LCU agent on ChampSelect
                                    transition. Body is the 10-player
                                    roster + queue_id. Bearer-auth via
                                    cross-Claude bridge token (same
                                    posture as routes_health_peer).
  GET  /api/team-context           ← Dashboard poll. No auth (loopback /
                                    Tailnet-only, served by HTTPS dashboard).

Storage: in-memory dict guarded by a Lock - single-process. The cache
survives RC reload because it's reset on supervisor restart, which is the
desired lifetime for a per-game enrichment payload.

Soft-fail invariants:
  - GET on cold cache returns `{"team_context": null}` (empty object,
    HTTP 200). Dashboard treats null as "not in champ-select".
  - POST with malformed body → 400; partial bodies (some fields missing)
    are stored as-is, schema validation is the caller's responsibility.
  - Auth failure → 401, no payload mutation.

Fan-out (FU02 main):
  After the skeleton roster is stored, the POST handler dispatches a
  background worker that calls `core.riot_api` to enrich each entry.
  Priority-1 (mastery + rank) fires first - those land in <30s of
  champ-select start under the 100/2min rate limit. Priority-2
  (mains + winrate + W/L streak) fires after, paced through the
  remaining ~60s of champ-select. The dashboard polls /api/state and
  re-renders as each field arrives - no blocking on full enrichment.

  Dispatch is via a module-level `_FANOUT_DISPATCHER` callable so tests
  can replace it with a no-op without monkey-patching `core.riot_api`.
  The default dispatcher checks `core.riot_api.is_configured()` first;
  if the API key is missing, the fan-out is skipped (skeleton-only).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

from core import bridge as _bridge
from dashboard._dispatch import equals

log = logging.getLogger("rc.routes_team_context")

# Module-level cache of the latest team_context payload. None when no
# champ-select has fired since RC boot. _state_builder reads this via
# get_team_context() to splice into /api/state.
_LOCK = threading.Lock()
_CACHE: Optional[dict] = None
_CACHE_TS: float = 0.0

# Hard cap on stored roster size. The LCU agent forwards exactly 10
# players in champ-select; anything bigger is malformed.
_MAX_ROSTER = 10

# Tracks the in-flight fan-out worker so a re-POST during the same
# champ-select doesn't spawn parallel duplicates. None when idle.
_WORKER: Optional[threading.Thread] = None
# Ranked-queue gate: queue IDs where summoner names must NOT be sent to
# the dashboard until loading-screen flag flips. Match-V5 docs queue
# list - Ranked Solo (420), Ranked Flex (440). The render layer also
# enforces this; backend blanking is defense in depth.
_RANKED_BLANK_QUEUES = frozenset({420, 440})


def get_team_context() -> Optional[dict]:
    """Return the latest stored team_context dict, or None if cache empty.
    Used by `dashboard._state_builder.build_state()` to splice into
    `/api/state.coach.team_context` during champ-select."""
    with _LOCK:
        return _CACHE


def _store(payload: dict) -> None:
    global _CACHE, _CACHE_TS
    with _LOCK:
        _CACHE = payload
        _CACHE_TS = time.time()


def _clear() -> None:
    """Reset the cache + cancel any in-flight worker reference. Tests
    rely on this to isolate cases."""
    global _CACHE, _CACHE_TS, _WORKER
    with _LOCK:
        _CACHE = None
        _CACHE_TS = 0.0
        _WORKER = None


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def _as_int(value: Any, default: int = 0) -> int:
    """Best-effort int coercion. Cycle-8 audit: a non-numeric queue_id /
    team_id in the (authed) refresh body used to raise ValueError out of
    the handler - the dispatcher has no catch-all, so the caller saw a
    connection reset instead of the documented soft-fail."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _update_entry(team: str, puuid: str, **fields: Any) -> None:
    """Mutate a single entry in the live cache by team + puuid.

    `team` is one of "allies"/"enemies". Atomically takes the lock,
    bumps `refreshed_at`, applies the supplied fields, and releases.
    Called by the fan-out worker as each Riot API response lands.
    """
    if not fields:
        return
    global _CACHE, _CACHE_TS
    with _LOCK:
        if _CACHE is None:
            return
        entries = _CACHE.get(team)
        if not isinstance(entries, list):
            return
        for entry in entries:
            if isinstance(entry, dict) and entry.get("puuid") == puuid:
                entry.update(fields)
                _CACHE["refreshed_at"] = _now_iso()
                _CACHE_TS = time.time()
                return


def _mark_complete() -> None:
    """Flip partial=False once the fan-out worker drains. Caller is
    responsible for ensuring this is only called when ALL priority tiers
    have completed (or been skipped)."""
    global _CACHE, _CACHE_TS
    with _LOCK:
        if _CACHE is None:
            return
        _CACHE["partial"] = False
        _CACHE["refreshed_at"] = _now_iso()
        _CACHE_TS = time.time()


def _skeleton_entry(slot: dict, blank_names: bool = False) -> dict:
    """Build a TeamContextEntry-shaped dict from an LCU roster slot.

    Initial population covers the fields the LCU payload already carries
    (puuid, summoner_name, team_id, locked_champion). Riot API enrichment
    (rank, mastery, mains, winrate, streak) lands later via the fan-out
    worker, which mutates each entry in place.

    When `blank_names` is True (ranked queues 420/440), summoner_name is
    forced empty regardless of what the LCU payload supplied - keeps the
    Riot-policy compliance gate visible at the storage layer too.
    """
    name = "" if blank_names else str(slot.get("summoner_name") or "")
    return {
        "puuid":             str(slot.get("puuid") or ""),
        "summoner_name":     name,
        "team_id":           _as_int(slot.get("team_id") or 0),
        "locked_champion":   str(slot.get("locked_champion") or ""),
        "rank":              "",
        "mastery_on_locked": 0,
        "w_l_streak_7":      [0, 0],
        "mains":             [],
        "win_rate_recent":   0.0,
    }


# ── Riot API fan-out ────────────────────────────────────────────────────

# Number of recent matches to scan for mains / winrate / streak.
# Personal-tier ceiling makes 20 the practical max - 10 players × 20
# matches × ~1 cache-miss per call ≈ 200 calls in a cold cache, well
# under the 100/2min × full-window budget once paced.
_RECENT_MATCH_DEPTH = 20
# Max time the fan-out worker spends cumulatively before giving up. Champ
# select itself runs ~95s including loading screen; the worker exits
# whenever the dashboard moves out of ChampSelect (no signal yet, so a
# wall clock is the cheap guard).
_FANOUT_DEADLINE_S = 180.0


def _enrich_priority_1(entry: dict, locked_champion_id: Optional[int]) -> None:
    """Priority-1 fan-out for one entry: mastery + rank.

    Both calls are TTL-cached (5 min) so re-firing the same lobby twice
    is free. Each result mutates the live cache via `_update_entry`.
    """
    from core import riot_api

    puuid = entry.get("puuid") or ""
    if not puuid:
        return
    team = "allies" if int(entry.get("team_id") or 0) != 200 else "enemies"

    # League-V4 rank. Empty list = unranked; we still want to flag the
    # entry as "looked up" so the skeleton "-" is replaced with the
    # actual rank string ("UNRANKED" sentinel left blank for now;
    # render shows skel placeholder when rank == "").
    entries = riot_api.get_summoner_rank(puuid)
    if entries is not None:
        solo = riot_api.pick_solo_rank(entries)
        rank_str = riot_api.format_rank_entry(solo) if solo else ""
        _update_entry(team, puuid, rank=rank_str)

    # Champion-Mastery-V4 on the locked champion. Skipped when the
    # player hasn't locked yet (championId 0).
    if locked_champion_id and locked_champion_id > 0:
        m = riot_api.get_champion_mastery(puuid, locked_champion_id)
        if isinstance(m, dict):
            mastery_pts = int(m.get("championPoints") or 0)
            _update_entry(team, puuid, mastery_on_locked=mastery_pts)


def _enrich_priority_2(entry: dict) -> None:
    """Priority-2 fan-out: recent-matches → mains / winrate / W/L streak."""
    from core import riot_api

    puuid = entry.get("puuid") or ""
    if not puuid:
        return
    team = "allies" if int(entry.get("team_id") or 0) != 200 else "enemies"

    match_ids = riot_api.get_recent_matches(puuid, count=_RECENT_MATCH_DEPTH)
    if not match_ids:
        return
    summary = riot_api.summarize_recent(puuid, match_ids)
    _update_entry(
        team, puuid,
        mains=summary.get("mains") or [],
        win_rate_recent=float(summary.get("win_rate_recent") or 0.0),
        w_l_streak_7=summary.get("w_l_streak_7") or [0, 0],
    )


# Map the locked-champion name (LCU payload key) → numeric ID. The LCU
# agent posts `locked_champion` as the champion's display name string;
# Champion-Mastery-V4 needs the numeric ID. The mapping is loaded from
# data/ddragon at module-import time and refreshed on miss. Soft-fail -
# missing IDs just skip the mastery call for that entry.
_CHAMP_NAME_TO_ID_CACHE: Optional[dict] = None


def _champ_name_to_id(name: str) -> Optional[int]:
    """Resolve champion display name → Riot champion ID. Returns None
    on any miss; caller skips the mastery call."""
    global _CHAMP_NAME_TO_ID_CACHE
    if not name:
        return None
    if _CHAMP_NAME_TO_ID_CACHE is None:
        from pathlib import Path
        ddragon_root = Path(__file__).resolve().parent.parent / "data" / "ddragon"
        candidates = list(ddragon_root.glob("*/data/en_US/champion.json"))
        if not candidates:
            _CHAMP_NAME_TO_ID_CACHE = {}
            return None
        try:
            with candidates[-1].open("r", encoding="utf-8") as f:
                doc = json.load(f)
            mapping = {}
            for cdef in (doc.get("data") or {}).values():
                cname = str(cdef.get("name") or "").strip()
                ckey = cdef.get("key")
                if cname and ckey:
                    try:
                        mapping[cname.lower()] = int(ckey)
                    except (TypeError, ValueError):
                        continue
            _CHAMP_NAME_TO_ID_CACHE = mapping
        except (OSError, ValueError, KeyError) as exc:
            log.debug("champ-name lookup load failed: %s", exc)
            _CHAMP_NAME_TO_ID_CACHE = {}
            return None
    return _CHAMP_NAME_TO_ID_CACHE.get(name.lower())


def _fanout_worker(allies: list, enemies: list, queue_id: int) -> None:
    """Fan-out worker - runs in a daemon thread.

    Walks the roster twice: priority-1 across all players first, then
    priority-2. The rate limiter inside `core.riot_api` provides natural
    back-pressure; the worker simply keeps requesting until the bucket
    has room.
    """
    deadline = time.monotonic() + _FANOUT_DEADLINE_S
    everyone = list(allies) + list(enemies)
    log.info("team-context fan-out start: queue=%d roster=%d",
             queue_id, len(everyone))

    # Priority-1 - mastery + rank for every entry. Tight loop, no pacing
    # - short bucket (20/s) handles 20 calls in ~1s.
    for entry in everyone:
        if time.monotonic() >= deadline:
            log.warning("team-context fan-out priority-1 hit deadline")
            return
        try:
            cid = _champ_name_to_id(entry.get("locked_champion") or "")
            _enrich_priority_1(entry, cid)
        except Exception as exc:    # noqa: BLE001 - must not kill the worker
            log.warning("team-context priority-1 entry failed: %s", exc)

    # Priority-2 - recent matches per player. Cold-cache cost is heavy
    # (each player = 1 list call + ≤20 match-detail calls); the long
    # bucket (100/120s) gates this naturally so we don't have to add
    # explicit sleeps.
    for entry in everyone:
        if time.monotonic() >= deadline:
            log.warning("team-context fan-out priority-2 hit deadline")
            break
        try:
            _enrich_priority_2(entry)
        except Exception as exc:    # noqa: BLE001
            log.warning("team-context priority-2 entry failed: %s", exc)

    _mark_complete()
    log.info("team-context fan-out done: queue=%d", queue_id)


def _default_dispatch_fanout(allies: list, enemies: list, queue_id: int) -> None:
    """Default fan-out dispatcher - spawns a daemon thread iff the
    Riot API is configured. Tests override _FANOUT_DISPATCHER to skip
    real network work."""
    try:
        from core import riot_api
    except ImportError:
        log.debug("team-context fan-out skipped: core.riot_api unavailable")
        return
    if not riot_api.is_configured():
        log.info("team-context fan-out skipped: riot_api not configured")
        return
    global _WORKER
    # If a previous worker is still alive, leave it; the entries it
    # populates will land in the same cache. Re-issuing here would
    # double the API call cost without changing the dashboard render.
    with _LOCK:
        if _WORKER is not None and _WORKER.is_alive():
            log.debug("team-context fan-out: prior worker still running, skip")
            return
        t = threading.Thread(
            target=_fanout_worker,
            args=(list(allies), list(enemies), int(queue_id)),
            name="rc-team-context-fanout",
            daemon=True,
        )
        _WORKER = t
    t.start()


# Pluggable dispatcher - tests replace this to assert call shape without
# spawning real network work. The route handler always dispatches via
# this module-level reference.
_FANOUT_DISPATCHER: Callable[[list, list, int], None] = _default_dispatch_fanout


def _serve_refresh_post(h, body) -> None:
    """POST /api/team-context/refresh - receive 10-player roster from
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

    queue_id = _as_int(body.get("queue_id") or 0)
    blank_names = queue_id in _RANKED_BLANK_QUEUES
    allies: list = []
    enemies: list = []
    for slot in roster:
        if not isinstance(slot, dict):
            continue
        entry = _skeleton_entry(slot, blank_names=blank_names)
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
        "refreshed_at": _now_iso(),
        "partial":      True,    # flipped to False by _mark_complete()
        "queue_id":     queue_id,
    }
    _store(payload)
    log.info("team-context refresh: queue=%d allies=%d enemies=%d",
             queue_id, len(allies), len(enemies))

    # Dispatch the Riot-API fan-out. Default dispatcher spawns a daemon
    # thread iff `core.riot_api.is_configured()`; tests swap in a no-op.
    # Failure here MUST NOT break the route - the skeleton is already
    # stored, the dashboard renders just fine without enrichment.
    try:
        _FANOUT_DISPATCHER(allies, enemies, queue_id)
    except Exception as exc:    # noqa: BLE001
        log.warning("team-context fan-out dispatch failed: %s", exc)

    h._send(200, json.dumps({"ok": True,
                             "stored": {"allies": len(allies),
                                        "enemies": len(enemies)}}).encode(),
            "application/json")


def _serve_get(h) -> None:
    """GET /api/team-context - dashboard poll.

    Returns `{"team_context": <obj|null>, "age_s": <float>}`. Age is
    computed from the last successful refresh; null cache → age=null.
    """
    with _LOCK:
        cache = _CACHE
        ts = _CACHE_TS
    if cache is None:
        body: dict = {"team_context": None, "age_s": None}
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

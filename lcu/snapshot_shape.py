"""Full LCU snapshot shaping, decoupled from any LCU transport.

Extracted verbatim from ``tools/lcu_agent.capture_state()`` (2026-07-20,
RC2 RM-03 E12 lever L3). ``lcu/champ_select_shape.py`` already lifted the
champ-select sub-shape; this module lifts the REST of the snapshot (phase,
ready-check, lobby members, cherry-augment probe, game_id, mastery) so the
dashboard's ``build_state`` can source the whole payload from an in-process
``LcuClient`` instead of round-tripping ``tools/lcu_agent`` through the
:8889 relay. ONE implementation, driven by whichever transport the caller
injects, keeps the agent-posted payload and the in-process payload byte
identical.

The only dependency is an injected request callable with the agent's
contract::

    request(method: str, path: str, body: dict | None = None)
        -> (payload: object, err: str | None)

so this module holds no connection, no lockfile, and no agent globals
(CONFIG / TOKEN / _lcu). It imports nothing beyond the stdlib +
``lcu.champ_select_shape`` and is importable from the dashboard process
without dragging in the agent's push loops.

Two per-process caches live here (moved verbatim from the agent): the
per-summoner-id lookup cache and the mastery cache. They are shared by
every caller in a process, exactly as they were when they lived on the
agent module. ``shape_snapshot`` is the top-level entry; the underscore
helpers are re-exported from ``tools/lcu_agent`` so the existing agent
tests that patch / call them by their agent names keep working.
"""
from __future__ import annotations

import time
from typing import Callable

from lcu.champ_select_shape import shape_champ_select
# RM-367: the single in-package answer to "does this gameflow body name a
# phase". Owned by lcu_pregame (RM-347), which documents the rule; a near-copy
# here is the private-copy drift class, so this imports rather than restates.
from lcu.lcu_pregame import _phase_or_none


# -- Lobby members forwarding ------------------------------------------------
#
# s170 (2026-05-11): the dashboard's view-lobby panel (_lobbyViewRefresh +
# _renderTop8 in web/js/main.js) expects state["lobby"].members[] with a
# rich shape (riot_id, is_leader, position_preferences, etc.). The agent
# was only forwarding queueId + game_mode + map_id; everything member-shaped
# in the panel was running on placeholders. This block extracts what LCU
# already publishes on /lol-lobby/v2/lobby + the local matchmaking search
# endpoint. Legion enriches with rank / games-with-me / online status -
# the agent is forwarder-only.

# queue_id -> human-readable name. Dashboard falls back to ("queue " + id)
# when queue_name is missing, so this map is best-effort. Common queues
# the operator sees; extend as needed.
_LOBBY_QUEUE_NAMES = {
    400: "Normal Draft",
    420: "Ranked Solo/Duo",
    430: "Normal Blind",
    440: "Ranked Flex",
    450: "ARAM",
    480: "Swiftplay",
    490: "Quickplay",
    700: "Clash",
    720: "Clash ARAM",
    830: "Co-op vs AI Intro",
    840: "Co-op vs AI Beginner",
    850: "Co-op vs AI Intermediate",
    900: "URF",
    920: "Poro King",
    1020: "One for All",
    1090: "TFT Normal",
    1100: "TFT Ranked",
    1110: "TFT Tutorial",
    1130: "TFT Hyper Roll",
    1160: "TFT Double Up",
    1300: "Nexus Blitz",
    1400: "Ultimate Spellbook",
    1750: "Arena",  # Arena 3x6 (CHERRY mapId 30). Was 1700/1710 pre-16.10 - retired from live LCU /lol-game-queues/v1/queues catalog 2026-05-24 (#89 verification).
    1810: "Swarm",
    1820: "Swarm (Solo)",
    1830: "Swarm (Duo)",
    1840: "Swarm (Trio)",
    1850: "Swarm (Quad)",
    1900: "URF",
    2400: "ARAM Mayhem",  # KIWI gameMode - queueId confirmed s220 (920 = Poro King). Brawl (2300) retired from rotation s214.
}


# Per-summoner-id cache for `/lol-summoner/v1/summoners/{id}` lookups.
# Current LCU builds frequently return empty gameName/tagLine on
# `/lol-lobby/v2/lobby` members, so we enrich by summoner-id. TTL is
# 10 min because riot-id changes are rare (and would re-fire on next
# capture cycle anyway since cache is per-process).
_SUMMONER_LOOKUP_TTL_S = 600.0
# The TTL alone bounded FRESHNESS, never SIZE: an expired entry was re-fetched
# but never removed, so the dict grew monotonically for the life of the
# process. The dashboard runs for days across many lobbies, and every distinct
# lobby member ever seen kept a row. Evict on insert (2026-08-31, lane 8
# cycle 35): drop everything already past its TTL, and if that is still not
# enough, drop the oldest rows until the cap holds.
_SUMMONER_LOOKUP_CACHE_MAX = 256
_summoner_lookup_cache: dict = {}  # {sid: {"data": {...}, "fetched_at": float}}


def _coerce_int(value, default: int = 0) -> int:
    """Best-effort int cast for a field LCU supplies, never raising.

    The League client changes field TYPES between builds (the Riot ID
    migration alone re-typed several), so every int-cast over an LCU value
    needs the same guard. This module already applied it by hand in some
    places and not others - ``_slim_lobby_member`` guarded ``summonerId``
    while ``_resolve_local_summoner_id`` cast the SAME field bare, and the
    mastery loop guarded ``championId`` while leaving its six siblings
    exposed. One helper so the guard cannot be forgotten again.

    OverflowError is caught alongside TypeError/ValueError and is NOT
    theoretical: ``json.loads`` accepts the non-standard ``Infinity``
    literal unless a ``parse_constant`` is supplied, and neither transport
    supplies one (``tools/lcu_agent.py:222``, ``lcu/lcu_client.py:197``).
    ``int(float("inf"))`` raises OverflowError, which is an ArithmeticError
    and so is caught by neither of the other two arms.
    """
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _prune_summoner_lookup_cache(now: float) -> None:
    """Keep ``_summoner_lookup_cache`` under ``_SUMMONER_LOOKUP_CACHE_MAX``."""
    if len(_summoner_lookup_cache) < _SUMMONER_LOOKUP_CACHE_MAX:
        return
    for sid, row in list(_summoner_lookup_cache.items()):
        if now - row.get("fetched_at", 0.0) >= _SUMMONER_LOOKUP_TTL_S:
            _summoner_lookup_cache.pop(sid, None)
    if len(_summoner_lookup_cache) < _SUMMONER_LOOKUP_CACHE_MAX:
        return
    # Materialise with list() BEFORE sorting: this cache is process-global
    # and the dashboard reaches it from more than one handler thread, so
    # iterating the live dict could raise "dictionary changed size during
    # iteration". pop(sid, None) is likewise tolerant of a racing eviction.
    for sid, _row in sorted(list(_summoner_lookup_cache.items()),
                            key=lambda kv: kv[1].get("fetched_at", 0.0)):
        if len(_summoner_lookup_cache) < _SUMMONER_LOOKUP_CACHE_MAX:
            break
        _summoner_lookup_cache.pop(sid, None)


def _lookup_summoner_by_id(request: Callable[..., tuple], sid: int):
    """Fetch summoner profile by summonerId; cached with TTL.

    Returns the LCU summoner dict (with gameName/tagLine/summonerName/
    summonerLevel/puuid) or None when unreachable. Quiet failure -
    callers must tolerate missing data and emit empty strings.
    """
    # Coerce HERE rather than trusting callers. ``sid`` is interpolated into
    # the request path below, and ``tools/lcu_agent.py:254`` re-exports this
    # helper with an unenforced ``sid: int`` annotation and no coercion of
    # its own - a string argument would build
    # ``/lol-summoner/v1/summoners/../../<anything>`` and the transport
    # concatenates it raw (``tools/lcu_agent.py:210``). That re-export has
    # zero non-test callers today, so the containment was ACCIDENTAL rather
    # than enforced; this makes it intrinsic.
    sid = _coerce_int(sid, default=0)
    if not sid:
        return None
    cached = _summoner_lookup_cache.get(sid)
    now = time.time()
    if cached and (now - cached.get("fetched_at", 0)) < _SUMMONER_LOOKUP_TTL_S:
        return cached.get("data")
    payload, err = request("GET", f"/lol-summoner/v1/summoners/{sid}")
    if not isinstance(payload, dict):
        return None
    _prune_summoner_lookup_cache(now)
    _summoner_lookup_cache[sid] = {"data": payload, "fetched_at": now}
    return payload


def _reset_summoner_lookup_cache_for_tests() -> None:
    _summoner_lookup_cache.clear()


def _slim_lobby_member(request: Callable[..., tuple], m, *,
                       local_summoner_id: int | None = None,
                       enrich: bool = False) -> dict | None:
    """Distil one LCU lobby-member entry into the dashboard's wire shape.

    LCU fields vary by client version - older builds emit ``summonerName``
    only; newer builds emit ``gameName`` + ``tagLine``. We forward both so
    Legion's panel can pick whichever it prefers and so the riot_id
    composition (``GameName#TagLine``) is available when possible.

    When ``local_summoner_id`` is supplied, ``is_self`` is computed by
    matching ``summonerId``. This is more reliable than LCU's
    ``isLocalMember`` flag which is unset on current client builds.

    When ``enrich=True`` and names are missing, fetch them via
    ``/lol-summoner/v1/summoners/{summonerId}``. Off by default to keep
    the function pure for unit tests; capture_state passes True.

    Returns None when ``m`` isn't a dict so the caller can drop garbage
    without a try/except.
    """
    if not isinstance(m, dict):
        return None
    game_name = str(m.get("gameName") or "")
    tag_line  = str(m.get("tagLine") or "")
    summ_name = str(m.get("summonerName") or "")
    sid = _coerce_int(m.get("summonerId") or 0)
    lvl = _coerce_int(m.get("summonerLevel") or 0)

    # s170.1: enrich missing names via per-summoner lookup. Current LCU
    # builds frequently leave gameName/tagLine empty on lobby members.
    if enrich and sid and not (game_name and tag_line):
        prof = _lookup_summoner_by_id(request, sid)
        if isinstance(prof, dict):
            game_name = game_name or str(prof.get("gameName") or "")
            tag_line  = tag_line  or str(prof.get("tagLine") or "")
            summ_name = summ_name or str(prof.get("displayName") or prof.get("internalName") or "")
            if not lvl:
                lvl = _coerce_int(prof.get("summonerLevel") or 0)

    if game_name and tag_line:
        riot_id = f"{game_name}#{tag_line}"
    else:
        riot_id = summ_name

    # is_self: prefer summoner-id match (reliable on current LCU builds);
    # fall back to the LCU ``isLocalMember`` flag (works on older builds).
    # _coerce_int, not int(): this helper is re-exported through
    # tools/lcu_agent and its docstring promises totality over garbage, so
    # the comparison must not raise on a caller-supplied bad id either. A
    # local id that cannot be parsed falls back to the isLocalMember flag
    # rather than silently marking every member "not me".
    _local_sid = (None if local_summoner_id is None
                  else _coerce_int(local_summoner_id, default=0))
    if _local_sid and sid:
        is_self = (sid == _local_sid)
    else:
        is_self = bool(m.get("isLocalMember"))

    return {
        "puuid":          str(m.get("puuid") or ""),
        "summoner_id":    sid,
        "summoner_name":  summ_name or game_name,
        "game_name":      game_name,
        "tag_line":       tag_line,
        "riot_id":        riot_id,
        "is_leader":      bool(m.get("isLeader")),
        "is_self":        is_self,
        "is_owner":       bool(m.get("isOwner")),
        "summoner_level": lvl,
        "ready":          bool(m.get("ready")),
        "position_preferences": {
            "first_preference":  str(m.get("firstPositionPreference") or "UNSELECTED").upper(),
            "second_preference": str(m.get("secondPositionPreference") or "UNSELECTED").upper(),
        },
    }


def _derive_search_state(phase: str, search_payload) -> str:
    """Map LCU phase + matchmaking-search response into the three states the
    dashboard understands: ``Idle`` / ``Searching`` / ``MatchFound``.

    The matchmaking-search endpoint (/lol-matchmaking/v1/search) returns
    ``{searchState: "Invalid"|"Searching"|"AwaitingMatch"|"Found"}`` when
    reachable; we prefer it when available because phase=Lobby can still
    mean "queueing" on the LCU side between the dodge-recovery and the
    actual ChampSelect dispatch. Fall back to phase mapping otherwise.
    """
    if isinstance(search_payload, dict):
        ss = str(search_payload.get("searchState") or "").lower()
        if ss in ("searching", "awaitingmatch"):
            return "Searching"
        if ss in ("found", "matchfound"):
            return "MatchFound"
    if phase == "Matchmaking":
        return "Searching"
    if phase == "ReadyCheck":
        return "MatchFound"
    return "Idle"


# -- LCU mastery cache -------------------------------------------------------
#
# Priority 8 (2026-05-10): pull the operator's full champion-mastery list
# directly from LCU at /lol-collections/v1/inventories/<sid>/champion-mastery.
# Free + instant, no Riot Web API rate limit, no PUUID lookup needed.
# Refreshed lazily - first capture after ChampSelect entry, then at most
# once every MASTERY_TTL_S to avoid spamming LCU.

MASTERY_TTL_S = 300.0  # 5 min - mastery doesn't shift faster than that

_mastery_cache: dict = {
    "summoner_id": None,
    "data": None,
    "fetched_at": 0.0,
}


def _resolve_local_summoner_id(request: Callable[..., tuple]) -> int | None:
    """Get the local player's summonerId from /lol-summoner/v1/current-summoner.

    Cached in ``_mastery_cache["summoner_id"]`` after the first successful
    resolve - League's current-summoner doesn't change between client
    sessions, so a single hit per process boot is enough.
    """
    cached = _mastery_cache.get("summoner_id")
    if cached:
        return cached
    me, err = request("GET", "/lol-summoner/v1/current-summoner")
    if not isinstance(me, dict):
        return None
    sid = me.get("summonerId")
    if not sid:
        return None
    # Guarded because the docstring promises "or None", and because an
    # unguarded int() here raised straight out of shape_snapshot: the agent
    # then skipped the whole /upload-lcu post for the tick and the
    # in-process path returned None and fell back to the relay silently.
    # _slim_lobby_member already guards this SAME field.
    sid_int = _coerce_int(sid, default=0)
    if not sid_int:
        return None
    _mastery_cache["summoner_id"] = sid_int
    return sid_int


def _maybe_refresh_mastery(request: Callable[..., tuple]) -> dict | None:
    """Fetch + cache mastery once per MASTERY_TTL_S.

    Returns ``{championId: {level, points, last_play_time}}`` or None when
    LCU isn't reachable or the response shape is unexpected. Quiet failure
    is fine - callers degrade to Riot Web fan-out for teammates anyway.
    """
    now = time.time()
    if (
        _mastery_cache.get("data") is not None
        and now - _mastery_cache.get("fetched_at", 0.0) < MASTERY_TTL_S
    ):
        return _mastery_cache["data"]
    sid = _resolve_local_summoner_id(request)
    if not sid:
        return None
    # 2026-05-11: the legacy /lol-collections/v1/inventories/<sid>/champion-mastery
    # path returns 404 on current LCU builds. The replacement endpoint is
    # /lol-champion-mastery/v1/local-player/champion-mastery, which serves the
    # local player's mastery without needing a sid/puuid path param. summonerId
    # is still resolved above so we can surface it on state["lcu"]["summoner_id"]
    # for downstream consumers.
    payload, err = request(
        "GET",
        "/lol-champion-mastery/v1/local-player/champion-mastery",
    )
    if not isinstance(payload, list):
        return None
    out: dict = {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        cid = entry.get("championId")
        if cid is None:
            continue
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            continue
        # Every one of these was a BARE int() while championId above was
        # guarded, so a single mistyped field raised and cost the caller the
        # entire snapshot - not just this champion's row. An unparseable
        # value now coerces to the same 0 an ABSENT field already got from
        # the `or 0`, so "unknown" keeps one meaning.
        out[cid] = {
            "level":          _coerce_int(entry.get("championLevel", 0) or 0),
            "points":         _coerce_int(entry.get("championPoints", 0) or 0),
            "last_play_time": _coerce_int(entry.get("lastPlayTime", 0) or 0),
            "points_since_last_level": _coerce_int(
                entry.get("championPointsSinceLastLevel", 0) or 0
            ),
            "points_until_next_level": _coerce_int(
                entry.get("championPointsUntilNextLevel", 0) or 0
            ),
            "chest_granted": bool(entry.get("chestGranted", False)),
            "tokens_earned": _coerce_int(entry.get("tokensEarned", 0) or 0),
        }
    _mastery_cache["data"] = out
    _mastery_cache["fetched_at"] = now
    return out


def _reset_mastery_cache_for_tests() -> None:
    _mastery_cache["summoner_id"] = None
    _mastery_cache["data"] = None
    _mastery_cache["fetched_at"] = 0.0


# -- Full snapshot assembly --------------------------------------------------


def shape_snapshot(request: Callable[..., tuple], config,
                   *, enrich: bool = True) -> dict:
    """Assemble the LCU snapshot for the dashboard from ``request``.

    Reproduces ``tools/lcu_agent.capture_state()``'s PURE assembly exactly:
    the gameflow phase, the cs_debug breadcrumb, ready-check + lobby for the
    queueing phases, champ-select via ``shape_champ_select``, the Arena
    cherry-augment probe + game_id for the in-game phases, and the local
    player's mastery for session-relevant phases. ``ts`` is stamped at the
    END so consumers see when capture finished.

    Deliberately does NOT emit ``config`` or ``lcu_port`` - those are
    caller-owned (the agent's process config, the transport's port). The
    ``config`` argument is accepted for call-site symmetry with the agent
    (``shape_snapshot(lcu_request, CONFIG)``) and reserved for future use.
    """
    state: dict = {}
    phase, _ = request("GET", "/lol-gameflow/v1/gameflow-phase")
    # RM-367: an empty, quote-only or whitespace-only body names no phase, so
    # it is reported as None - a falsy no-phase joining the path the consumers
    # already handle - and never as the "" it used to land as. NOT "Unknown":
    # that value is TRUTHY, and both arms of the runtime view router that
    # branch on a falsy phase (web/js/main.js:711 s209 sticky-guard, :728
    # item-281 in-game promotion, off `const phase = lcu && lcu.phase` at
    # :629) would be silently disarmed by it. None keeps them firing exactly
    # as "" did, and dashboard/_cs_retention.py:114 already treats both as
    # "unknown, do not act on it" - its _CLEAR_PHASES holds the *string*
    # "None", a REAL idle phase, which is why that one must survive intact.
    # The predicate is RM-347's, deliberately imported rather than copied.
    if isinstance(phase, str):
        state["phase"] = _phase_or_none(phase)
    elif isinstance(phase, bytes):
        state["phase"] = _phase_or_none(phase.decode())
    else:
        # Left as-is by RM-367: a non-str/non-bytes body is a different
        # question from an empty one, and its truthiness is filed, not fixed
        # here. The unguarded .decode() above is likewise RM-293's, not this
        # row's.
        state["phase"] = "Unknown"

    # KNOWN-BUG diagnostic breadcrumb (2026-05-17): the operator's
    # ARAM / ARAM Mayhem / Arena champ-select view kept rendering blank.
    # raw_phase is the unmodified gameflow-phase string - capturing it
    # every cycle lets a `/api/state` curl during the next live
    # no-draft champ-select reveal exactly what phase Mayhem reports
    # during its bench window. Enriched below with the champ-select
    # session shape when that block runs.
    state["cs_debug"] = {"raw_phase": state["phase"], "ts": time.time()}

    if state["phase"] in ("ReadyCheck", "Matchmaking", "Lobby"):
        rc, _ = request("GET", "/lol-matchmaking/v1/ready-check")
        if isinstance(rc, dict):
            state["ready_check"] = {
                "state":          rc.get("state"),
                "playerResponse": rc.get("playerResponse"),
                "timer":          rc.get("timer"),
            }
        # 2026-05-09 (FU02 follow-up): capture the lobby queueId so the
        # dashboard can pre-flip mode_key (Arena / ARAM / SR / TFT) before
        # the LiveClient mode flag goes live. Without this, sitting in an
        # Arena party lobby leaves the dashboard on the generic client view.
        # s170 (2026-05-11): also forward members[] + local_member +
        # is_leader + party_type + search_state so view-lobby panel
        # (_lobbyViewRefresh + _renderTop8) can render real data instead
        # of running on placeholders.
        lob, _ = request("GET", "/lol-lobby/v2/lobby")
        if isinstance(lob, dict):
            gconf = lob.get("gameConfig") or {}
            qid = gconf.get("queueId")
            try:
                qid_int = int(qid) if qid is not None else 0
            except (TypeError, ValueError):
                qid_int = 0
            raw_members = lob.get("members") or []
            # s170.1: resolve local summoner-id so is_self can be computed
            # by id-match (current LCU's ``isLocalMember`` is unreliable).
            # The resolver is cached after first call.
            _local_sid = _resolve_local_summoner_id(request)
            members = [m for m in
                       (_slim_lobby_member(request, rm,
                                           local_summoner_id=_local_sid,
                                           enrich=enrich)
                        for rm in raw_members)
                       if m is not None]
            local_member = next((m for m in members if m.get("is_self")), None)
            # /lol-matchmaking/v1/search may 404 when not actively queueing -
            # that's fine, _derive_search_state falls back to phase mapping.
            search, _ = request("GET", "/lol-matchmaking/v1/search")
            # E11 R3: the view reads lobby.party_size + lobby.max_party_size
            # (web/js/main.js). party_size = live member count; max_party_size
            # = gameConfig.maxLobbySize (0 when absent -> dashboard "Party -").
            try:
                _max_party = int(gconf.get("maxLobbySize") or 0)
            except (TypeError, ValueError):
                _max_party = 0
            state["lobby"] = {
                "queue_id":       qid_int,
                "queue_name":     _LOBBY_QUEUE_NAMES.get(qid_int, ""),
                "is_custom":      bool(gconf.get("isCustom")),
                "game_mode":      gconf.get("gameMode") or "",
                "map_id":         gconf.get("mapId") or 0,
                "party_id":       str(lob.get("partyId") or ""),
                "party_type":     str(lob.get("partyType") or "open").lower(),
                "can_search":     bool(lob.get("canStartActivity")),
                "is_leader":      bool(local_member and local_member.get("is_leader")),
                "search_state":   _derive_search_state(state["phase"], search),
                "members":        members,
                "local_member":   local_member,
                "party_size":     len(members),
                "max_party_size": _max_party,
            }

    # RC2 L3: the shaping lives in lcu/champ_select_shape so the dashboard
    # can build the identical payload straight from an in-process client
    # instead of round-tripping the agent through the :8889 relay.
    _cs = shape_champ_select(request, state["phase"])
    state["cs_debug"].update(_cs.get("cs_debug", {}))
    if "champ_select" in _cs:
        state["champ_select"] = _cs["champ_select"]

    # Capture Riot game_id from gameflow session when a game is live.
    # Used by Legion's DS calibration pipeline for post-game correlation.
    state["cherry_augment_open"] = False
    if state["phase"] in ("GameStart", "InProgress"):
        gflow, _ = request("GET", "/lol-gameflow/v1/session")
        if isinstance(gflow, dict):
            # `.get("gameData", {})` hands back the DEFAULT only when the key
            # is ABSENT. LCU routinely emits a present-and-NULL sub-object,
            # and `None.get(...)` then raised AttributeError straight out of
            # shape_snapshot, costing the whole snapshot for the tick. The
            # `_gq` read below was already isinstance-guarded; its parent
            # was not.
            gdata = gflow.get("gameData")
            if not isinstance(gdata, dict):
                gdata = {}
            gid = str(gdata.get("gameId") or "")
            if gid and gid != "0":
                state["game_id"] = gid
            # D6 (2026-07-04): observe the Arena/Cherry augment picker so a
            # force_scan can be bumped when it opens (seeds augment_shadow.jsonl
            # / anvil_shadow.jsonl). Gated to Arena queues - the endpoint 404s
            # elsewhere - reusing the SAME queue-id set as the arena_teams block
            # above (1700/1710 legacy aliases, 1750 = live CHERRY). Derive the
            # queue id from the gameflow session already in hand (the champ-
            # select queue_id local is not in scope during InProgress).
            _gq = gdata.get("queue", {})
            _gq_id = _gq.get("id", 0) if isinstance(_gq, dict) else 0
            if _gq_id in (1700, 1710, 1750):
                aug, _aug_err = request(
                    "GET", "/lol-cherry-game-intra-event/v1/augments")
                avail = aug.get("available") if isinstance(aug, dict) else None
                # available[] non-empty == the augment picker is up.
                state["cherry_augment_open"] = bool(
                    isinstance(avail, list) and avail)

    # Priority 8 (2026-05-10): include LCU mastery for the local player as
    # soon as we're in a session-relevant phase. Cached at MASTERY_TTL_S so
    # the lobby + champ-select loops don't hammer LCU. Legion's
    # team-context route can prefer this number for the operator and fall
    # back to Riot Web mastery for teammates/enemies.
    if state["phase"] in (
        "Lobby", "Matchmaking", "ReadyCheck",
        "ChampSelect", "GameStart", "InProgress", "WaitingForStats",
    ):
        # 2026-05-11 live-fix: write mastery + summoner_id at the TOP level of
        # the snapshot. Legion's bridge handler wraps the entire agent state
        # as ``legion_state["lcu"]`` on POST, so the desired dashboard path
        # ``state["lcu"]["mastery"]`` resolves correctly.
        mastery = _maybe_refresh_mastery(request)
        if mastery is not None:
            state["mastery"] = mastery
            sid = _mastery_cache.get("summoner_id")
            if sid:
                state["summoner_id"] = sid

    state["ts"] = time.time()
    return state

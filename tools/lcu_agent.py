"""
lcu_agent.py - Legion-local LCU agent (relocated 2026-05-29, ADR-011).

Runs Legion-local (1-PC consolidation, ADR-011). Reads the LCU lockfile, polls
champ-select / gameflow / ready-check, and pushes state to the in-process
vision server. Also drains the dashboard command queue (auto-accept, bench
swap, summoner-spell change, lock pick, reroll) and executes them via LCU.

Registered as the RC-LCUAgent ONLOGON task (Legion-neutral task name).

Endpoints used (all Legion-local now):
  POST http://192.168.8.230:8889/upload-lcu        - push state snapshot
  GET  http://192.168.8.230:8889/lcu-cmd-pending   - drain command queue
  POST http://192.168.8.230:8889/lcu-cmd-done      - report results

The agent maintains a local config (auto_accept on/off, summoner override,
etc.) that's mirrored from dashboard via 'set_config' command. Default is
auto_accept=off (s171, 2026-05-12) - previously True, which meant the
dashboard's Auto Accept toggle was visual-only and the agent silently
accepted every queue pop regardless of the UI state. The toggle now
pushes set_config + auto_accept on click.

# Threading (2026-04-25)

Three independent loops run in daemon threads so a slow capture_state()
during in-game (LCU is sluggish when League is busy) can't make us miss
the 12s ready-check accept window:

  - _state_push_loop  - full snapshot + post to Legion (cadence: INTERVAL)
  - _auto_features_loop - ready-check accept + summoner override
                          (cadence: AUTO_INTERVAL, must be << 12s)
  - _cmd_poll_loop    - drain Legion's command queue (cadence: CMD_INTERVAL)
"""
import base64
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

# The agent is launched as ``python tools/lcu_agent.py`` (RC-LCUAgent
# ONLOGON task), so sys.path[0] is tools/ and the repo's own packages are
# invisible. The champ-select shaping lives in lcu/ because the dashboard
# has to build the same payload from an in-process client (RC2 L3); this
# keeps ONE implementation instead of a drifting agent-side copy.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lcu.champ_select_shape import shape_champ_select  # noqa: E402

LEGION = "http://192.168.8.230:8889"
# Legion's HTTPS dashboard. Distinct from LEGION (vision relay :8889);
# carries the FU02 team-context refresh route + bearer-auth peer surfaces.
LEGION_DASHBOARD = "https://192.168.8.230:8888"
# AUDIT (cycle-restore 2026-04-25): token resolver - env -> config file -> fallback.
import os as _os_tok
from pathlib import Path as _Path_tok
def _resolve_auth_token() -> str:
    env = _os_tok.environ.get("RC_VISION_TOKEN")
    if env: return env.strip()
    # 1-PC consolidation (item 215): the agent now runs Legion-local, so it
    # must read the SAME canonical token the vision server + dashboard use
    # (core.vision_token -> config/vision_token.txt). Without this the agent
    # fell through to the legacy hardcoded fallback, which no longer matches
    # the rotated config token -> every /upload-lcu POST 401s silently ->
    # the relay caches no LCU snapshot -> the lobby/champ-select UI never
    # updates. Canonical config path wins; tools-sibling stays for back-compat.
    here = _Path_tok(__file__).resolve().parent
    for cand in (here.parent / "config" / "vision_token.txt",
                 here / "vision_token.txt"):
        try:
            if cand.exists():
                line = cand.read_text(encoding="utf-8").splitlines()[0].strip()
                if line: return line
        except OSError: pass
    return "8e8f131e212b329438218eca27372dde"

TOKEN  = _resolve_auth_token()
INTERVAL      = 1.0   # state-push cadence (slow during in-game; OK)
AUTO_INTERVAL = 0.5   # ready-check / summoner-override poll cadence
CMD_INTERVAL  = 0.5   # Legion command-queue drain cadence (idle)
# RC2 E7a: after draining a batch that held a latency-sensitive command
# (bench_swap / reroll / accept_ready), re-poll FAST instead of waiting
# the full CMD_INTERVAL, so a freshly-clicked ARAM bench swap is not
# stuck behind a 0.5s idle wait. Empty/idle drains still sleep the full
# CMD_INTERVAL (no busy-spin).
BENCH_CMD_FAST_INTERVAL = 0.1
LATENCY_SENSITIVE_CMDS = {"bench_swap", "reroll", "accept_ready"}
# RC2 E7 TODO-1: a fast command DRAIN (above) only fires the LCU POST
# quickly - the swapped champ still didn't reach /api/state until the next
# _state_push_loop tick (up to INTERVAL=1.0s away, a separate thread). This
# event lets the cmd loop WAKE the state-push loop the instant a
# latency-sensitive batch is drained, so the new pick/bench reflects in
# ~BENCH_CMD_FAST_INTERVAL. Only _state_push_loop ever calls capture_state(),
# so the cmd loop merely sets this flag - no new cross-thread capture race.
_swap_wake = threading.Event()
# Min seconds between team-context POSTs while still in champ-select.
# The route is idempotent - re-posting just refreshes the cache, but no
# point hammering it on every 1s state-push cycle.
TEAM_CONTEXT_REPOST_S = 3.0

LOCKFILE_PATHS = [
    Path(r"C:\Riot Games\League of Legends\lockfile"),
    Path(r"C:\Riot Games\League of Legends (PBE)\lockfile"),
    Path(r"D:\Riot Games\League of Legends\lockfile"),
]

# In-memory config; mutated by 'set_config' commands from dashboard.
CONFIG = {
    "auto_accept":     False,
    "summoner_override": False,
    "summoner_d":      4,    # default Flash
    "summoner_f":      32,   # default Snowball (ARAM)
}

_ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE
try: _ssl_ctx.set_ciphers("ALL:@SECLEVEL=0")
except ssl.SSLError: pass

_lcu = {"port": None, "auth": None, "header": None}
_lcu_lock = threading.Lock()  # guards _lcu dict updates across threads
_session_state = {"phase": None, "last_summoner_set_for": None,
                  "last_accepted_check_id": None}


# -- Lockfile / connection ---------------------------------------------------

def read_lockfile() -> tuple[str | None, str | None]:
    for p in LOCKFILE_PATHS:
        if p.exists():
            try:
                # Format: name:pid:port:password:protocol
                parts = p.read_text(encoding="utf-8").strip().split(":")
                if len(parts) >= 5:
                    return parts[2], parts[3]
            except Exception:  # noqa: BLE001
                pass
    return None, None


def ensure_lcu_conn() -> bool:
    port, pwd = read_lockfile()
    if not port or not pwd:
        with _lcu_lock:
            if _lcu["port"] is not None:
                print("[lcu] lockfile gone - client closed", flush=True)
            _lcu["port"] = _lcu["auth"] = _lcu["header"] = None
        return False
    with _lcu_lock:
        if port != _lcu["port"] or pwd != _lcu["auth"]:
            token = base64.b64encode(f"riot:{pwd}".encode()).decode()
            _lcu["port"] = port
            _lcu["auth"] = pwd
            _lcu["header"] = f"Basic {token}"
            print(f"[lcu] connected port={port}", flush=True)
    return True


def lcu_request(method: str, path: str, body: dict | None = None) -> tuple[object, str | None]:
    if not _lcu["port"]:
        return None, "no_lcu"
    url = f"https://127.0.0.1:{_lcu['port']}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": _lcu["header"], "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    try:
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, context=_ssl_ctx, timeout=2) as r:
            raw = r.read()
            if not raw:
                return None, None
            try:
                return json.loads(raw), None
            except Exception:  # noqa: BLE001
                return raw, None
    except urllib.error.HTTPError as e:
        return None, f"http {e.code}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}"


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
_summoner_lookup_cache: dict = {}  # {sid: {"data": {...}, "fetched_at": float}}


def _lookup_summoner_by_id(sid: int):
    """Fetch summoner profile by summonerId; cached with TTL.

    Returns the LCU summoner dict (with gameName/tagLine/summonerName/
    summonerLevel/puuid) or None when unreachable. Quiet failure -
    callers must tolerate missing data and emit empty strings.
    """
    if not sid:
        return None
    cached = _summoner_lookup_cache.get(sid)
    now = time.time()
    if cached and (now - cached.get("fetched_at", 0)) < _SUMMONER_LOOKUP_TTL_S:
        return cached.get("data")
    payload, err = lcu_request("GET", f"/lol-summoner/v1/summoners/{sid}")
    if not isinstance(payload, dict):
        return None
    _summoner_lookup_cache[sid] = {"data": payload, "fetched_at": now}
    return payload


def _reset_summoner_lookup_cache_for_tests() -> None:
    _summoner_lookup_cache.clear()


def _slim_lobby_member(m, *, local_summoner_id: int | None = None,
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
    try:
        sid = int(m.get("summonerId") or 0)
    except (TypeError, ValueError):
        sid = 0
    try:
        lvl = int(m.get("summonerLevel") or 0)
    except (TypeError, ValueError):
        lvl = 0

    # s170.1: enrich missing names via per-summoner lookup. Current LCU
    # builds frequently leave gameName/tagLine empty on lobby members.
    if enrich and sid and not (game_name and tag_line):
        prof = _lookup_summoner_by_id(sid)
        if isinstance(prof, dict):
            game_name = game_name or str(prof.get("gameName") or "")
            tag_line  = tag_line  or str(prof.get("tagLine") or "")
            summ_name = summ_name or str(prof.get("displayName") or prof.get("internalName") or "")
            if not lvl:
                try:
                    lvl = int(prof.get("summonerLevel") or 0)
                except (TypeError, ValueError):
                    pass

    if game_name and tag_line:
        riot_id = f"{game_name}#{tag_line}"
    else:
        riot_id = summ_name

    # is_self: prefer summoner-id match (reliable on current LCU builds);
    # fall back to the LCU ``isLocalMember`` flag (works on older builds).
    if local_summoner_id is not None and sid:
        is_self = (sid == int(local_summoner_id))
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
# Refreshed lazily - first capture_state() after ChampSelect entry, then
# at most once every MASTERY_TTL_S to avoid spamming LCU.

MASTERY_TTL_S = 300.0  # 5 min - mastery doesn't shift faster than that

_mastery_cache: dict = {
    "summoner_id": None,
    "data": None,
    "fetched_at": 0.0,
}


def _resolve_local_summoner_id() -> int | None:
    """Get the local player's summonerId from /lol-summoner/v1/current-summoner.

    Cached in ``_mastery_cache["summoner_id"]`` after the first successful
    resolve - League's current-summoner doesn't change between client
    sessions, so a single hit per agent boot is enough.
    """
    cached = _mastery_cache.get("summoner_id")
    if cached:
        return cached
    me, err = lcu_request("GET", "/lol-summoner/v1/current-summoner")
    if not isinstance(me, dict):
        return None
    sid = me.get("summonerId")
    if not sid:
        return None
    _mastery_cache["summoner_id"] = int(sid)
    return int(sid)


def _maybe_refresh_mastery() -> dict | None:
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
    sid = _resolve_local_summoner_id()
    if not sid:
        return None
    # 2026-05-11: the legacy /lol-collections/v1/inventories/<sid>/champion-mastery
    # path returns 404 on current LCU builds. The replacement endpoint is
    # /lol-champion-mastery/v1/local-player/champion-mastery, which serves the
    # local player's mastery without needing a sid/puuid path param. summonerId
    # is still resolved above so we can surface it on state["lcu"]["summoner_id"]
    # for downstream consumers.
    payload, err = lcu_request(
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
        out[cid] = {
            "level":          int(entry.get("championLevel", 0) or 0),
            "points":         int(entry.get("championPoints", 0) or 0),
            "last_play_time": int(entry.get("lastPlayTime", 0) or 0),
            "points_since_last_level": int(
                entry.get("championPointsSinceLastLevel", 0) or 0
            ),
            "points_until_next_level": int(
                entry.get("championPointsUntilNextLevel", 0) or 0
            ),
            "chest_granted": bool(entry.get("chestGranted", False)),
            "tokens_earned": int(entry.get("tokensEarned", 0) or 0),
        }
    _mastery_cache["data"] = out
    _mastery_cache["fetched_at"] = now
    return out


def _reset_mastery_cache_for_tests() -> None:
    _mastery_cache["summoner_id"] = None
    _mastery_cache["data"] = None
    _mastery_cache["fetched_at"] = 0.0


# -- State capture -----------------------------------------------------------


def _local_in_progress_action(sess: dict, action_type: str) -> dict | None:
    """Find the local cell's in-progress action of the given type (pick|ban)
    in ``session.actions``. Returns the raw action dict or None.

    Mirrors the walk done by the ``lock_pick`` handler. The intent setters
    PATCH this same action with ``completed: false`` so the in-game UI
    reflects the dashboard pick/ban hover (no actual lock).
    """
    try:
        local_cell = int(sess.get("localPlayerCellId", -1))
    except (TypeError, ValueError):
        return None
    if local_cell < 0:
        return None
    for group in sess.get("actions") or []:
        if not isinstance(group, list):
            continue
        for action in group:
            if not isinstance(action, dict):
                continue
            try:
                actor_cell = int(action.get("actorCellId", -2))
            except (TypeError, ValueError):
                continue
            if actor_cell != local_cell:
                continue
            if action.get("type") != action_type:
                continue
            if action.get("completed"):
                continue
            if not action.get("isInProgress"):
                continue
            return action
    return None


def capture_state() -> dict:
    """Snapshot LCU state for the dashboard. ts is set at the END so
    consumers see when capture finished (post lands ~immediately after),
    not when capture started - which during in-game can be 8-11s earlier
    because LCU calls run slow under League CPU pressure."""
    state = {"config": dict(CONFIG)}
    if not ensure_lcu_conn():
        state["phase"] = "Offline"
        state["ts"] = time.time()
        return state
    state["lcu_port"] = _lcu["port"]
    phase, _ = lcu_request("GET", "/lol-gameflow/v1/gameflow-phase")
    if isinstance(phase, str):
        state["phase"] = phase.strip('"')
    elif isinstance(phase, bytes):
        state["phase"] = phase.decode().strip('"')
    else:
        state["phase"] = "Unknown"

    # KNOWN-BUG diagnostic breadcrumb (2026-05-17): the operator's
    # ARAM / ARAM Mayhem / Arena champ-select view kept rendering blank.
    # raw_phase is the unmodified gameflow-phase string - capturing it
    # every cycle lets a `/api/state` curl during the next live
    # no-draft champ-select reveal exactly what phase Mayhem reports
    # during its bench window (the open question: does it ever report
    # "ChampSelect", or flip straight to "InProgress"?). Free - phase
    # is already fetched. Enriched below with the champ-select session
    # shape when that block runs. Rides the existing 1s push -> cached
    # on the in-process vision server -> no separate console / screen
    # capture needed to root-cause the remaining uncertainty.
    state["cs_debug"] = {"raw_phase": state["phase"], "ts": time.time()}

    if state["phase"] in ("ReadyCheck", "Matchmaking", "Lobby"):
        rc, _ = lcu_request("GET", "/lol-matchmaking/v1/ready-check")
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
        lob, _ = lcu_request("GET", "/lol-lobby/v2/lobby")
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
            _local_sid = _resolve_local_summoner_id()
            members = [m for m in
                       (_slim_lobby_member(rm,
                                           local_summoner_id=_local_sid,
                                           enrich=True)
                        for rm in raw_members)
                       if m is not None]
            local_member = next((m for m in members if m.get("is_self")), None)
            # /lol-matchmaking/v1/search may 404 when not actively queueing -
            # that's fine, _derive_search_state falls back to phase mapping.
            search, _ = lcu_request("GET", "/lol-matchmaking/v1/search")
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
    # instead of round-tripping this agent through the :8889 relay.
    _cs = shape_champ_select(lcu_request, state["phase"])
    state["cs_debug"].update(_cs.get("cs_debug", {}))
    if "champ_select" in _cs:
        state["champ_select"] = _cs["champ_select"]

    # Capture Riot game_id from gameflow session when a game is live.
    # Used by Legion's DS calibration pipeline for post-game correlation.
    state["cherry_augment_open"] = False
    if state["phase"] in ("GameStart", "InProgress"):
        gflow, _ = lcu_request("GET", "/lol-gameflow/v1/session")
        if isinstance(gflow, dict):
            gid = str(gflow.get("gameData", {}).get("gameId") or "")
            if gid and gid != "0":
                state["game_id"] = gid
            # D6 (2026-07-04): observe the Arena/Cherry augment picker so a
            # force_scan can be bumped when it opens (seeds augment_shadow.jsonl
            # / anvil_shadow.jsonl). Gated to Arena queues - the endpoint 404s
            # elsewhere - reusing the SAME queue-id set as the arena_teams block
            # above (1700/1710 legacy aliases, 1750 = live CHERRY). Derive the
            # queue id from the gameflow session already in hand (the champ-
            # select queue_id local is not in scope during InProgress).
            _gq = gflow.get("gameData", {}).get("queue", {})
            _gq_id = _gq.get("id", 0) if isinstance(_gq, dict) else 0
            if _gq_id in (1700, 1710, 1750):
                aug, _aug_err = lcu_request(
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
        # the agent's state. Legion's bridge handler wraps the entire agent
        # state as ``legion_state["lcu"]`` on POST, so the desired dashboard
        # path ``state["lcu"]["mastery"]`` resolves correctly. The previous
        # ``state.setdefault("lcu", {})["mastery"] = ...`` pattern produced
        # ``state["lcu"]["lcu"]["mastery"]`` (double-nested).
        mastery = _maybe_refresh_mastery()
        if mastery is not None:
            state["mastery"] = mastery
            sid = _mastery_cache.get("summoner_id")
            if sid:
                state["summoner_id"] = sid

    state["ts"] = time.time()
    return state


# -- Command execution -------------------------------------------------------

def _resolve_invitee_summoner_id(rid: str, sid, puuid: str):
    """Resolve a lobby-invite target to an LCU summonerId.

    Riot removed ``/lol-summoner/v1/summoners/by-name`` in the Riot ID
    migration - it 404s on current clients - which silently broke every
    Top 8 / friends-list invite (the dashboard only had a "Name#TAG" to
    resolve from). Resolution order, most reliable first:

      1. explicit summonerId (caller already had it)
      2. puuid -> /lol-summoner/v1/summoners-by-puuid-cached/{puuid}
      3. Name#TAG -> scan /lol-chat/v1/friends (invite targets ARE
         friends; that resource carries gameName/gameTag/summonerId on
         current builds) matching gameName#gameTag or the legacy name
      4. legacy /lol-summoner/v1/summoners/by-name (ancient builds only)

    Returns ``(summoner_id: int | None, how: str)`` where ``how`` names
    the path that resolved (or the miss) for the result envelope + logs.
    """
    try:
        sid_int = int(sid or 0)
    except (TypeError, ValueError):
        sid_int = 0
    if sid_int > 0:
        return sid_int, "summoner_id"

    puuid = str(puuid or "").strip()
    if puuid:
        looked, _ = lcu_request(
            "GET", f"/lol-summoner/v1/summoners-by-puuid-cached/{puuid}")
        if isinstance(looked, dict) and looked.get("summonerId"):
            return int(looked["summonerId"]), "puuid"

    rid = str(rid or "").strip()
    if not rid:
        return None, "no_identifier"
    want_name, _, want_tag = rid.partition("#")
    want_name = want_name.strip().lower()
    want_tag = want_tag.strip().lower()

    friends, _ = lcu_request("GET", "/lol-chat/v1/friends")
    if isinstance(friends, list):
        for fr in friends:
            if not isinstance(fr, dict):
                continue
            gn = str(fr.get("gameName") or "").strip().lower()
            tg = str(fr.get("gameTag") or fr.get("tagLine") or "").strip().lower()
            legacy = str(fr.get("name") or "").strip().lower()
            if want_tag and gn:
                matched = (gn == want_name and tg == want_tag)
            elif gn:
                matched = (gn == want_name)
            else:
                matched = False
            if not matched and legacy:
                matched = (legacy == want_name)
            if matched and fr.get("summonerId"):
                return int(fr["summonerId"]), "friends"

    if "#" in rid:
        nm, _, tg = rid.partition("#")
        looked, _ = lcu_request(
            "GET", f"/lol-summoner/v1/summoners/by-name/{nm}-{tg}")
        if not isinstance(looked, dict):
            looked, _ = lcu_request(
                "GET", f"/lol-summoner/v1/summoners/by-name/{nm}")
        if isinstance(looked, dict) and looked.get("summonerId"):
            return int(looked["summonerId"]), "by_name"

    return None, "unresolved"


def execute_command(cmd: dict) -> dict:
    name = cmd.get("cmd", "")
    if name == "set_config":
        for k in ("auto_accept", "summoner_override", "summoner_d", "summoner_f"):
            if k in cmd:
                CONFIG[k] = cmd[k]
        print(f"[cmd] config -> {CONFIG}", flush=True)
        return {"ok": True, "config": dict(CONFIG)}
    if name == "apply_item_set":
        # Push a custom item set (Phase 2).
        # 2026-05-23 (item 164): replace-by-uid (NOT wipe-all-RC) so 4
        # build variants + 1 build-order set can coexist as 5 RC- prefixed
        # entries in the in-game item-shop dropdown. Pre-fix behavior
        # wiped every RC- set each call, leaving only the last push
        # visible mid-match. Optional `replace_all_rc=True` preserves
        # legacy behavior for callers that explicitly want it.
        set_uid = str(cmd.get("set_uid") or "RC-Auto")
        title   = str(cmd.get("title")   or "RC: Auto")
        champ_id = int(cmd.get("champion_id") or 0)
        blocks   = cmd.get("blocks") or []
        if not blocks and cmd.get("items"):
            blocks = [{"type": "Build", "items": cmd["items"]}]
        if not blocks:
            return {"ok": False, "err": "no items"}
        me, err = lcu_request("GET", "/lol-summoner/v1/current-summoner")
        if not isinstance(me, dict):
            return {"ok": False, "err": err or "no summoner"}
        sid = me.get("summonerId")
        aid = me.get("accountId")
        if not sid:
            return {"ok": False, "err": "no summoner id"}
        cur, _ = lcu_request("GET", f"/lol-item-sets/v1/item-sets/{sid}/sets")
        if not isinstance(cur, dict):
            cur = {"accountId": aid, "itemSets": []}
        sets = list(cur.get("itemSets") or [])
        if bool(cmd.get("replace_all_rc", False)):
            sets = [s for s in sets if not str(s.get("uid", "")).startswith("RC-")]
        else:
            sets = [s for s in sets if str(s.get("uid", "")) != set_uid]
        sets.insert(0, {
            "uid": set_uid, "title": title, "type": "custom",
            "map": "any", "mode": "any",
            "associatedChampions": [champ_id] if champ_id else [],
            "associatedMaps": [], "preferredItemSlots": [],
            "blocks": blocks, "sortrank": 0,
        })
        body = {"accountId": aid, "itemSets": sets,
                "timestamp": int(time.time() * 1000)}
        _, err = lcu_request("PUT", f"/lol-item-sets/v1/item-sets/{sid}/sets", body)
        if err:
            return {"ok": False, "err": err}
        return {"ok": True, "set_uid": set_uid, "title": title}
    if name == "apply_item_sets_batch":
        # 2026-05-23 (item 164): push MULTIPLE RC item sets in one PUT.
        # `sets` is a list of {set_uid, title, champion_id, blocks}. Each
        # entry replaces any existing matching-uid set; non-matching RC-
        # sets are preserved unless they appear in this batch. The PUT
        # collapses N round-trips into 1, useful for "push all 4 build
        # variants + build order at champ-select lock-in".
        batch = cmd.get("sets") or []
        if not isinstance(batch, list) or not batch:
            return {"ok": False, "err": "no sets in batch"}
        me, err = lcu_request("GET", "/lol-summoner/v1/current-summoner")
        if not isinstance(me, dict):
            return {"ok": False, "err": err or "no summoner"}
        sid = me.get("summonerId")
        aid = me.get("accountId")
        if not sid:
            return {"ok": False, "err": "no summoner id"}
        cur, _ = lcu_request("GET", f"/lol-item-sets/v1/item-sets/{sid}/sets")
        if not isinstance(cur, dict):
            cur = {"accountId": aid, "itemSets": []}
        sets = list(cur.get("itemSets") or [])
        new_uids = set()
        new_sets = []
        for entry in batch:
            if not isinstance(entry, dict):
                continue
            set_uid = str(entry.get("set_uid") or "")
            if not set_uid:
                continue
            blocks = entry.get("blocks") or []
            if not blocks and entry.get("items"):
                blocks = [{"type": "Build", "items": entry["items"]}]
            if not blocks:
                continue
            title    = str(entry.get("title") or set_uid)
            champ_id = int(entry.get("champion_id") or 0)
            new_uids.add(set_uid)
            new_sets.append({
                "uid": set_uid, "title": title, "type": "custom",
                "map": "any", "mode": "any",
                "associatedChampions": [champ_id] if champ_id else [],
                "associatedMaps": [], "preferredItemSlots": [],
                "blocks": blocks, "sortrank": 0,
            })
        if not new_sets:
            return {"ok": False, "err": "no valid sets after filter"}
        # Replace by-uid (overwrites matching entries; preserves the rest).
        sets = [s for s in sets if str(s.get("uid", "")) not in new_uids]
        sets = new_sets + sets  # new sets first so they appear on top in client
        body = {"accountId": aid, "itemSets": sets,
                "timestamp": int(time.time() * 1000)}
        _, err = lcu_request("PUT", f"/lol-item-sets/v1/item-sets/{sid}/sets", body)
        if err:
            return {"ok": False, "err": err}
        return {"ok": True, "set_uids": sorted(new_uids), "count": len(new_sets)}
    if name == "delete_stale_rc_item_sets":
        # Wipe stale RC- item-sets that don't match the current
        # {champion, mode}. Operator-reported issue (item 188 Slice B):
        # the in-game item-shop dropdown was showing 20+ stale RC- sets
        # after a session of switching champions + modes. Per item 178
        # collapse + item 179 ARAM/Arena collapse, each
        # `_csvMaybePushBuildsToLCU` call pushes up to 4 sets with uid
        # `RC-<champion>-<mode>-<path>`; 4 paths * 3 modes (SR/ARAM/Arena)
        # = 12 sets per champion. Cycling through 2-3 champion picks per
        # session accumulates 24-36 stale RC- entries. apply_item_set +
        # apply_item_sets_batch deliberately preserve other RC- sets
        # (replace-by-uid only) so this wipe handler is the deliberate
        # garbage collector wired as a PRE-PUSH step.
        #
        # Wipe scope: DELETE every set whose uid starts with "RC-" AND
        # does NOT match `RC-<active_champion>-<active_mode>-*`. The
        # current-champion-current-mode-* sets survive so the apply
        # batch right after this call doesn't need to re-push them
        # (idempotence). Operator's own custom sets (no RC- prefix) are
        # ALWAYS preserved.
        active_champ = str(cmd.get("active_champion") or "").strip()
        active_mode  = str(cmd.get("active_mode")     or "").strip()
        if not active_champ or not active_mode:
            return {"ok": False, "err": "active_champion + active_mode required"}
        keep_prefix = f"RC-{active_champ}-{active_mode}-"
        me, err = lcu_request("GET", "/lol-summoner/v1/current-summoner")
        if not isinstance(me, dict):
            return {"ok": False, "err": err or "no summoner"}
        sid = me.get("summonerId")
        aid = me.get("accountId")
        if not sid:
            return {"ok": False, "err": "no summoner id"}
        cur, _ = lcu_request("GET", f"/lol-item-sets/v1/item-sets/{sid}/sets")
        if not isinstance(cur, dict):
            cur = {"accountId": aid, "itemSets": []}
        sets_before = list(cur.get("itemSets") or [])
        kept = []
        wiped_uids = []
        for s in sets_before:
            if not isinstance(s, dict):
                continue
            uid = str(s.get("uid", ""))
            # Preserve any set that is not an RC- managed set.
            if not uid.startswith("RC-"):
                kept.append(s)
                continue
            # RC- managed: keep only if uid matches the active scope.
            if uid.startswith(keep_prefix):
                kept.append(s)
                continue
            wiped_uids.append(uid)
        if not wiped_uids:
            # Nothing to wipe; short-circuit PUT to save a round-trip.
            return {"ok": True, "wiped_uids": [], "wiped_count": 0,
                    "kept_count": len(kept)}
        body = {"accountId": aid, "itemSets": kept,
                "timestamp": int(time.time() * 1000)}
        _, err = lcu_request("PUT", f"/lol-item-sets/v1/item-sets/{sid}/sets", body)
        if err:
            return {"ok": False, "err": err}
        return {"ok": True, "wiped_uids": sorted(wiped_uids),
                "wiped_count": len(wiped_uids), "kept_count": len(kept)}
    if name == "apply_runes":
        # Push a full rune page (Phase 2). Caller resolves keystone +
        # tree names to perk IDs server-side and sends raw IDs here so
        # the agent stays dumb. Body shape:
        #   {cmd: "apply_runes", page_name: "RC: Lulu ARAM",
        #    primary_id: 8200, sub_id: 8300, perk_ids: [9 ints]}
        page_name  = str(cmd.get("page_name", "RC: Auto"))
        primary_id = int(cmd.get("primary_id", 0))
        sub_id     = int(cmd.get("sub_id", 0))
        perk_ids   = cmd.get("perk_ids") or []
        if not primary_id or not sub_id or len(perk_ids) != 9:
            return {"ok": False, "err": "bad rune ids"}
        # Item 210 2026-05-27 fix: broaden the DELETE filter so RC's
        # apply_runes path can reclaim slots from RC-authored pages that
        # used legacy naming conventions. With the operator's 3-slot
        # account cap, a pre-fix filter that only matched "RC: " left the
        # legacy "RC " / "RC-" pages in place, so POST /lol-perks/v1/pages
        # returned 4xx "max owned page count reached" and silently failed
        # the rune push for the entire champ select. Matching all three
        # 3-char prefixes covers every RC-authored variant + future drift.
        #
        # OPEN1 (item 210 follow-up, 2026-06-17): the live page-name
        # producers are now UNIFIED on the "RC: " prefix -
        #   - "RC: <champ> <identity> (<MODE>)"  loadout_resolver.py + routes_loadout.py
        #   - "RC: <champ> <key> (SR)"           routes_sr_draft.py
        #   - "RC: Auto"                         this agent's default
        # The lone divergent holdout is the FROZEN lcu/lcu_client.py
        # (_RC_PAGE_PREFIX = "RC - "), left as-is by OPEN1 and harmless
        # precisely because this filter still reclaims it (its name starts
        # "RC "). Keep the 3-prefix match - do NOT narrow it back to
        # "RC: " only. tests/test_rc_page_name_prefix_unified.py guards it.
        pages, _ = lcu_request("GET", "/lol-perks/v1/pages")
        if isinstance(pages, list):
            for pg in pages:
                nm = str(pg.get("name", ""))
                if (isinstance(pg, dict) and pg.get("isDeletable")
                        and nm[:3] in ("RC ", "RC:", "RC-")):
                    pid = pg.get("id")
                    if pid:
                        lcu_request("DELETE", f"/lol-perks/v1/pages/{pid}")
        body = {"name": page_name, "primaryStyleId": primary_id,
                "subStyleId": sub_id, "selectedPerkIds": list(perk_ids),
                "current": True, "isRecommendationOverride": False}
        resp, err = lcu_request("POST", "/lol-perks/v1/pages", body)
        if err is not None or not isinstance(resp, dict):
            return {"ok": False, "err": err or "no page id"}
        new_id = resp.get("id")
        if not new_id:
            return {"ok": False, "err": "no page id returned"}
        lcu_request("PUT", "/lol-perks/v1/currentpage", {"id": new_id})
        return {"ok": True, "page_id": new_id, "name": page_name}
    if name == "reroll":
        # ARAM reroll - POST /lol-champ-select/v1/session/my-selection/reroll.
        # Costs 1 reroll point; LCU returns 204 on success.
        r, err = lcu_request("POST", "/lol-champ-select/v1/session/my-selection/reroll")
        return {"ok": err is None, "err": err}
    if name == "accept_ready":
        r, err = lcu_request("POST", "/lol-matchmaking/v1/ready-check/accept")
        return {"ok": err is None, "err": err}
    if name == "bench_swap":
        # Accept both championId (canonical) and champion_id (legacy
        # snake_case) so older JS payloads keep working.
        cid = int(cmd.get("championId", cmd.get("champion_id", 0)))
        if cid <= 0: return {"ok": False, "err": "no champ"}
        r, err = lcu_request("POST", f"/lol-champ-select/v1/session/bench/swap/{cid}")
        return {"ok": err is None, "err": err}
    if name == "set_summoners":
        d = int(cmd.get("d", 0)); f = int(cmd.get("f", 0))
        body = {"spell1Id": d, "spell2Id": f}
        r, err = lcu_request("PATCH", "/lol-champ-select/v1/session/my-selection", body)
        return {"ok": err is None, "err": err}
    if name == "set_summoner_spell":
        # Per-slot push from the champ-select summoner-spell strip
        # (2026-05-23 item 165). Body shape: {slot: 1|2, spellId: N}.
        # Reads current my-cell pair from the session, replaces the
        # targeted slot, and PATCHes /my-selection with the new pair
        # so the partner slot stays intact across rapid D / F clicks.
        try:
            slot = int(cmd.get("slot", 0))
        except (TypeError, ValueError):
            slot = 0
        try:
            spell_id = int(cmd.get("spellId", 0))
        except (TypeError, ValueError):
            spell_id = 0
        if slot not in (1, 2):
            return {"ok": False, "err": "slot must be 1 or 2"}
        if spell_id <= 0:
            return {"ok": False, "err": "no spellId"}
        sess, _ = lcu_request("GET", "/lol-champ-select/v1/session")
        if not isinstance(sess, dict):
            return {"ok": False, "err": "no session"}
        my_cell = sess.get("localPlayerCellId", -1)
        cur_d, cur_f = 0, 0
        for player in (sess.get("myTeam") or []):
            if isinstance(player, dict) and player.get("cellId") == my_cell:
                cur_d = int(player.get("spell1Id", 0) or 0)
                cur_f = int(player.get("spell2Id", 0) or 0)
                break
        new_d = spell_id if slot == 1 else cur_d
        new_f = spell_id if slot == 2 else cur_f
        # No-op if the targeted slot already holds the requested spell.
        if (slot == 1 and cur_d == spell_id) or (slot == 2 and cur_f == spell_id):
            return {"ok": True, "spell1Id": new_d, "spell2Id": new_f, "noop": True}
        body = {"spell1Id": new_d, "spell2Id": new_f}
        _, err = lcu_request("PATCH", "/lol-champ-select/v1/session/my-selection", body)
        if err is not None:
            return {"ok": False, "err": err}
        return {"ok": True, "spell1Id": new_d, "spell2Id": new_f}
    if name in ("set_ban_intent", "set_pick_intent"):
        # PATCH the local cell's in-progress ban|pick action with the
        # requested champion id but ``completed: false`` so the in-game
        # client UI mirrors the dashboard's hover state without locking.
        # The lock itself stays a separate ``lock_pick`` flow.
        cid = int(cmd.get("championId", 0))
        if cid <= 0:
            return {"ok": False, "err": "no championId"}
        action_type = "ban" if name == "set_ban_intent" else "pick"
        sess, _ = lcu_request("GET", "/lol-champ-select/v1/session")
        if not isinstance(sess, dict):
            return {"ok": False, "err": "no session"}
        action = _local_in_progress_action(sess, action_type)
        if action is None:
            return {"ok": False, "err": f"no in-progress {action_type} for local cell"}
        aid = action.get("id")
        if aid is None:
            return {"ok": False, "err": "no action id"}
        body = {"championId": cid, "completed": False}
        _, err = lcu_request("PATCH",
            f"/lol-champ-select/v1/session/actions/{aid}", body)
        if err is not None:
            return {"ok": False, "err": err}
        return {"ok": True, "action_id": aid, "championId": cid}
    if name == "request_position_swap":
        # Send a lane-swap offer to the cell. Mirror of trade_request -
        # resolve cell_id -> swap id via session.positionSwaps[]. LCU
        # returns 204 on success; any other state means the offer is
        # busy / invalid / already-sent on the receiving side.
        cell_id = int(cmd.get("cell_id", -1))
        if cell_id < 0:
            return {"ok": False, "err": "no cell_id"}
        sess, _ = lcu_request("GET", "/lol-champ-select/v1/session")
        if not isinstance(sess, dict):
            return {"ok": False, "err": "no session"}
        target = next((e for e in (sess.get("positionSwaps") or [])
                       if isinstance(e, dict) and e.get("cellId") == cell_id),
                      None)
        if not target:
            return {"ok": False, "err": "no position-swap slot for that cell"}
        st = str(target.get("state") or "").upper()
        if st == "BUSY":
            return {"ok": False, "err": "swap busy"}
        if st == "INVALID":
            return {"ok": False, "err": "swap invalid"}
        swap_id = target.get("id")
        if swap_id is None:
            return {"ok": False, "err": "no swap id"}
        _, err = lcu_request("POST",
            f"/lol-champ-select/v1/session/position-swaps/{swap_id}/request")
        if err is not None:
            return {"ok": False, "err": err}
        return {"ok": True, "swap_id": swap_id, "cell_id": cell_id}
    if name == "request_pick_order_swap":
        # Pick-order swap (Nth-pick reorder). Same shape as position-swap
        # but a different LCU collection + endpoint.
        cell_id = int(cmd.get("cell_id", -1))
        if cell_id < 0:
            return {"ok": False, "err": "no cell_id"}
        sess, _ = lcu_request("GET", "/lol-champ-select/v1/session")
        if not isinstance(sess, dict):
            return {"ok": False, "err": "no session"}
        target = next((e for e in (sess.get("pickOrderSwaps") or [])
                       if isinstance(e, dict) and e.get("cellId") == cell_id),
                      None)
        if not target:
            return {"ok": False, "err": "no pick-order-swap slot for that cell"}
        st = str(target.get("state") or "").upper()
        if st == "BUSY":
            return {"ok": False, "err": "swap busy"}
        if st == "INVALID":
            return {"ok": False, "err": "swap invalid"}
        swap_id = target.get("id")
        if swap_id is None:
            return {"ok": False, "err": "no swap id"}
        _, err = lcu_request("POST",
            f"/lol-champ-select/v1/session/pick-order-swaps/{swap_id}/request")
        if err is not None:
            return {"ok": False, "err": err}
        return {"ok": True, "swap_id": swap_id, "cell_id": cell_id}
    if name == "set_augment_intent":
        # Arena/Cherry augment selection. Item 187 Slice E scaffold (research-
        # only); item 188 Slice C wires the actual PATCH chain. Cherry's REST
        # surface is undocumented + version-volatile, so we try a priority
        # chain of 4 candidate endpoints; first 2xx wins; all 4 missing -> a
        # full error envelope with each attempt's status so the operator can
        # see at a glance which surface the live LCU is exposing this patch.
        # Live verification gated on a real Arena 1750 champ-select augment
        # phase (see docs/CHERRY_AUGMENT_SCAFFOLD_NOTES.md for the recipe).
        #
        # Endpoint priority chain (first 2xx wins):
        #   1. PATCH /lol-cherry-game-intra-event/v1/augment-select
        #         - item 187 Slice E primary guess; intra-event is the
        #           live-game phase surface Cherry uses for round-by-round
        #           augment picks (rounds 1-4 = silver/gold/prismatic).
        #   2. PATCH /lol-cherry/v1/augment-select
        #         - shorter namespace fallback; older patches sometimes use
        #           the bare /lol-cherry/v1/* tree.
        #   3. PATCH /lol-cherry-summoner/v1/augments
        #         - summoner-scoped fallback; if the live surface exposes
        #           augment selection under the per-summoner namespace.
        #   4. POST  /lol-cherry-game-intra-event/v1/augment-select
        #         - method-fallback in case the surface expects POST not
        #           PATCH; mirrors item 180's queueId fallback discovery.
        aug_id = int(cmd.get("augment_id", 0))
        slot = int(cmd.get("slot", 0))
        if aug_id <= 0:
            return {"ok": False, "err": "no augment_id"}
        if slot < 0 or slot > 3:
            return {"ok": False, "err": f"bad slot {slot} (want 0-3)"}
        body = {"augmentId": aug_id, "slotIndex": slot}
        attempts = (
            ("PATCH", "/lol-cherry-game-intra-event/v1/augment-select"),
            ("PATCH", "/lol-cherry/v1/augment-select"),
            ("PATCH", "/lol-cherry-summoner/v1/augments"),
            ("POST",  "/lol-cherry-game-intra-event/v1/augment-select"),
        )
        tried = []
        for method, path in attempts:
            resp, err = lcu_request(method, path, body)
            if err is None:
                print(f"[cmd] set_augment_intent augment={aug_id} slot={slot} "
                      f"-> {method} {path} ok", flush=True)
                return {"ok": True, "augment_id": aug_id, "slot": slot,
                        "endpoint": f"{method} {path}", "resp": resp}
            tried.append(f"{method} {path} -> {err}")
        print(f"[cmd] set_augment_intent augment={aug_id} slot={slot} "
              f"FAIL all 4 endpoints", flush=True)
        return {"ok": False, "err": "augment_intent_all_endpoints_failed",
                "augment_id": aug_id, "slot": slot, "tried": tried}
    if name == "trade_request":
        cell_id = int(cmd.get("cell_id", -1))
        if cell_id < 0:
            return {"ok": False, "err": "no cell_id"}
        sess, _ = lcu_request("GET", "/lol-champ-select/v1/session")
        if not isinstance(sess, dict):
            return {"ok": False, "err": "no session"}
        trades = sess.get("trades") or []
        target = next((t for t in trades
                       if isinstance(t, dict) and t.get("cellId") == cell_id),
                      None)
        if not target:
            return {"ok": False, "err": "no trade slot for that cell"}
        st = str(target.get("state") or "").upper()
        if st == "BUSY":
            return {"ok": False, "err": "trade busy"}
        if st == "INVALID":
            return {"ok": False, "err": "trade invalid"}
        trade_id = target.get("id")
        if trade_id is None:
            return {"ok": False, "err": "no trade id"}
        _, err = lcu_request("POST",
            f"/lol-champ-select/v1/session/trades/{trade_id}/request")
        if err is not None:
            return {"ok": False, "err": err}
        return {"ok": True, "trade_id": trade_id, "cell_id": cell_id}
    if name == "accept_trade":
        cell_id = int(cmd.get("cell_id", -1))
        if cell_id < 0:
            return {"ok": False, "err": "no cell_id"}
        sess, _ = lcu_request("GET", "/lol-champ-select/v1/session")
        if not isinstance(sess, dict):
            return {"ok": False, "err": "no session"}
        target = next((t for t in (sess.get("trades") or [])
                       if isinstance(t, dict) and t.get("cellId") == cell_id),
                      None)
        if not target:
            return {"ok": False, "err": "no trade slot"}
        st = str(target.get("state") or "").upper()
        if st != "RECEIVED":
            return {"ok": False, "err": f"trade not RECEIVED (state={st})"}
        trade_id = target.get("id")
        if trade_id is None:
            return {"ok": False, "err": "no trade id"}
        _, err = lcu_request("POST",
            f"/lol-champ-select/v1/session/trades/{trade_id}/accept")
        if err is not None:
            return {"ok": False, "err": err}
        return {"ok": True, "trade_id": trade_id, "cell_id": cell_id}
    if name == "decline_trade":
        cell_id = int(cmd.get("cell_id", -1))
        if cell_id < 0:
            return {"ok": False, "err": "no cell_id"}
        sess, _ = lcu_request("GET", "/lol-champ-select/v1/session")
        if not isinstance(sess, dict):
            return {"ok": False, "err": "no session"}
        target = next((t for t in (sess.get("trades") or [])
                       if isinstance(t, dict) and t.get("cellId") == cell_id),
                      None)
        if not target:
            return {"ok": False, "err": "no trade slot"}
        trade_id = target.get("id")
        if trade_id is None:
            return {"ok": False, "err": "no trade id"}
        _, err = lcu_request("POST",
            f"/lol-champ-select/v1/session/trades/{trade_id}/decline")
        if err is not None:
            return {"ok": False, "err": err}
        return {"ok": True, "trade_id": trade_id, "cell_id": cell_id}
    if name == "start_matchmaking":
        # Begin queueing for the current lobby. Leader-only; LCU returns
        # 400 if a non-leader calls it.
        _, err = lcu_request("POST", "/lol-lobby/v2/lobby/matchmaking/search")
        return {"ok": err is None, "err": err}
    if name == "cancel_matchmaking":
        _, err = lcu_request("DELETE", "/lol-lobby/v2/lobby/matchmaking/search")
        return {"ok": err is None, "err": err}
    if name == "change_queue_type":
        # Re-create the lobby on a different queue. JS sends queue_id
        # (snake_case); LCU body wants queueId.
        qid = int(cmd.get("queue_id", 0))
        if qid <= 0:
            return {"ok": False, "err": "no queue_id"}
        _, err = lcu_request("POST", "/lol-lobby/v2/lobby", {"queueId": qid})
        return {"ok": err is None, "err": err}
    if name == "lock_pick":
        cid = int(cmd.get("championId", 0))
        # Need to know action ID - fetch session first
        sess, _ = lcu_request("GET", "/lol-champ-select/v1/session")
        if not isinstance(sess, dict): return {"ok": False, "err": "no session"}
        # 2026-05-09 (s155): cast to int explicitly - some LCU builds emit
        # actorCellId / localPlayerCellId as JSON strings depending on the
        # patch, which made the equality check silently miss.
        try:
            local_cell = int(sess.get("localPlayerCellId", -1))
        except (TypeError, ValueError):
            local_cell = -1
        # Walk every pick action for the local cell. Track BOTH the pending
        # action id (the one we'd PATCH) AND whether the user is already
        # locked on the requested champion - the dashboard lock button can
        # race the in-game lock button (user clicks one then the other; or
        # apply_runes/apply_item_set serialize ahead of lock_pick and push
        # us past the active-pick window). If the LCU already shows the
        # pick completed on the same champion, return success so the UI
        # doesn't surface a phantom failure.
        pending_aid = None
        already_locked = False
        for group in sess.get("actions", []):
            for action in group:
                try:
                    actor_cell = int(action.get("actorCellId", -2))
                except (TypeError, ValueError):
                    continue
                if actor_cell != local_cell:
                    continue
                if action.get("type") != "pick":
                    continue
                if action.get("completed", False):
                    if int(action.get("championId", 0)) == cid:
                        already_locked = True
                elif pending_aid is None:
                    pending_aid = action.get("id")
        if already_locked:
            return {"ok": True, "err": None, "note": "already locked"}
        if pending_aid is None:
            return {"ok": False, "err": "no pending pick action"}
        body = {"championId": cid, "completed": True}
        r, err = lcu_request("PATCH",
            f"/lol-champ-select/v1/session/actions/{pending_aid}", body)
        return {"ok": err is None, "err": err}
    # -- Phase B lobby controls (s171) ---------------------------------
    if name == "lobby.set_position_prefs":
        # PATCH the local member's role preferences. LCU body shape:
        #   {"firstPreference": "TOP|JUNGLE|MIDDLE|BOTTOM|UTILITY|FILL",
        #    "secondPreference": same set or "UNSELECTED"}
        # Dashboard sends snake_case primary/secondary; map to LCU's
        # camelCase + UPPERCASE positions.
        _MAP = {
            "TOP": "TOP", "JG": "JUNGLE", "JUNGLE": "JUNGLE",
            "MID": "MIDDLE", "MIDDLE": "MIDDLE",
            "BOT": "BOTTOM", "ADC": "BOTTOM", "BOTTOM": "BOTTOM",
            "SUP": "UTILITY", "SUPP": "UTILITY", "UTILITY": "UTILITY",
            "FILL": "FILL", "UNSELECTED": "UNSELECTED", "": "UNSELECTED",
        }
        prim = _MAP.get(str(cmd.get("primary") or cmd.get("first") or "").upper())
        sec  = _MAP.get(str(cmd.get("secondary") or cmd.get("second") or "").upper())
        if prim is None: prim = "FILL"
        if sec  is None: sec  = "UNSELECTED"
        body = {"firstPreference": prim, "secondPreference": sec}
        _, err = lcu_request("PUT", "/lol-lobby/v2/lobby/members/localMember/position-preferences", body)
        return {"ok": err is None, "err": err,
                "primary": prim, "secondary": sec}
    if name == "lobby.set_party_type":
        # Toggle lobby visibility between "open" (joinable by friends)
        # and "closed" (invite-only).
        pt = str(cmd.get("party_type") or "closed").lower()
        if pt not in ("open", "closed"):
            return {"ok": False, "err": "party_type must be open|closed"}
        _, err = lcu_request("PUT", "/lol-lobby/v2/lobby/partyType",
                             {"partyType": pt})
        return {"ok": err is None, "err": err, "party_type": pt}
    if name == "lobby.invite_player":
        # POST a lobby invitation. LCU accepts an array of invitee
        # descriptors - we send one. The dashboard provides a riot_id
        # ("Name#TAG") and/or summoner_id/puuid; resolution lives in
        # _resolve_invitee_summoner_id because Riot's by-name endpoint is
        # dead and a friends-scan is the reliable Top 8 / friends path.
        rid = str(cmd.get("riot_id") or "").strip()
        sid_in = cmd.get("summoner_id")
        puuid = str(cmd.get("puuid") or "").strip()
        if not rid and not sid_in and not puuid:
            return {"ok": False,
                    "err": "riot_id, summoner_id or puuid required"}
        sid, how = _resolve_invitee_summoner_id(rid, sid_in, puuid)
        if not sid:
            return {"ok": False,
                    "err": f"could not resolve summoner: {rid or puuid}"}
        body = [{"toSummonerId": int(sid)}]
        _, err = lcu_request("POST", "/lol-lobby/v2/lobby/invitations", body)
        return {"ok": err is None, "err": err,
                "riot_id": rid, "summoner_id": sid, "resolved_via": how}
    if name == "lobby.promote_leader":
        # Hand party leadership to another member. Resolve riot_id (or
        # summoner_id) -> member_id by walking the current lobby members
        # list. LCU rejects if caller isn't the current leader (400).
        rid = str(cmd.get("riot_id") or "").strip()
        sid = cmd.get("summoner_id")
        if not rid and not sid:
            return {"ok": False, "err": "riot_id or summoner_id required"}
        lob, _ = lcu_request("GET", "/lol-lobby/v2/lobby")
        if not isinstance(lob, dict):
            return {"ok": False, "err": "no lobby session"}
        target_sid = sid
        if not target_sid and rid:
            want_name, _, want_tag = rid.partition("#")
            for m in (lob.get("members") or []):
                if not isinstance(m, dict): continue
                gn = (m.get("gameName") or "").strip()
                tag = (m.get("tagLine") or "").strip()
                # Match by riot_id (Name#TAG) or summoner-internal-name.
                if (gn.lower() == want_name.lower()
                        and (not want_tag or tag.lower() == want_tag.lower())):
                    target_sid = m.get("summonerId")
                    break
                if (m.get("summonerInternalName") or "").lower() == rid.lower():
                    target_sid = m.get("summonerId")
                    break
        if not target_sid:
            return {"ok": False, "err": f"member not found: {rid}"}
        # LCU endpoint promotes via POST to .../members/{sid}/promote.
        _, err = lcu_request("POST",
            f"/lol-lobby/v2/lobby/members/{target_sid}/promote")
        return {"ok": err is None, "err": err,
                "riot_id": rid, "summoner_id": target_sid}
    if name == "lobby.kick_member":
        # Kick a party member. Same resolver pattern as promote_leader.
        # Leader-only on LCU; non-leader callers get 400.
        rid = str(cmd.get("riot_id") or "").strip()
        sid = cmd.get("summoner_id")
        if not rid and not sid:
            return {"ok": False, "err": "riot_id or summoner_id required"}
        lob, _ = lcu_request("GET", "/lol-lobby/v2/lobby")
        if not isinstance(lob, dict):
            return {"ok": False, "err": "no lobby session"}
        target_sid = sid
        if not target_sid and rid:
            want_name, _, want_tag = rid.partition("#")
            for m in (lob.get("members") or []):
                if not isinstance(m, dict): continue
                gn = (m.get("gameName") or "").strip()
                tag = (m.get("tagLine") or "").strip()
                if (gn.lower() == want_name.lower()
                        and (not want_tag or tag.lower() == want_tag.lower())):
                    target_sid = m.get("summonerId")
                    break
                if (m.get("summonerInternalName") or "").lower() == rid.lower():
                    target_sid = m.get("summonerId")
                    break
        if not target_sid:
            return {"ok": False, "err": f"member not found: {rid}"}
        _, err = lcu_request("POST",
            f"/lol-lobby/v2/lobby/members/{target_sid}/kick")
        return {"ok": err is None, "err": err,
                "riot_id": rid, "summoner_id": target_sid}
    if name == "lobby.create_practice_tool":
        # Practice Tool uses queueId 3140 (Multiplayer Practice Tool
        # Custom, PRACTICETOOL gameMode) + customGameLobby config.
        # 2026-05-24 (#89): queueId was previously omitted - newer LCU
        # builds reject the body with 500 INVALID_LOBBY without an
        # explicit queueId. Live capture via in-client Practice Tool
        # create -> /lol-lobby/v2/lobby GET confirmed queueId:3140 +
        # gameMode:PRACTICETOOL + mapId:11. teamSize:1 is fine (the
        # live lobby's gameConfig reports teamSize:5 + numPlayersPerTeam:5
        # post-create but the create body's teamSize:1 is accepted).
        body = {
            "queueId": 3140,
            "isCustom": True,
            "customGameLobby": {
                "configuration": {
                    "gameMode": "PRACTICETOOL",
                    "gameMutator": "",
                    "gameServerRegion": "",
                    "mapId": 11,
                    "mutators": {"id": 1},
                    "spectatorPolicy": "AllAllowed",
                    "teamSize": 1,
                },
                "lobbyName": "RC Practice Tool",
                "lobbyPassword": "",
            },
        }
        _, err = lcu_request("POST", "/lol-lobby/v2/lobby", body)
        return {"ok": err is None, "err": err}
    return {"ok": False, "err": f"unknown cmd: {name}"}


def auto_features() -> None:
    """Apply config-driven automatic actions. Called on its own thread at
    AUTO_INTERVAL cadence so it stays responsive even when capture_state
    is mid-flight on the state-push thread."""
    if not _lcu["port"]:
        return
    # Auto-accept ready-check pops
    if CONFIG.get("auto_accept"):
        rc, _ = lcu_request("GET", "/lol-matchmaking/v1/ready-check")
        if isinstance(rc, dict) and rc.get("state") == "InProgress":
            pr = rc.get("playerResponse", "")
            if pr in ("None", None, ""):
                lcu_request("POST", "/lol-matchmaking/v1/ready-check/accept")
                print("[auto] queue accepted", flush=True)
    # Auto-set summoner spells in champ select if override enabled
    if CONFIG.get("summoner_override"):
        sess, _ = lcu_request("GET", "/lol-champ-select/v1/session")
        if isinstance(sess, dict):
            local_cell = sess.get("localPlayerCellId", -1)
            my_pick = next((p for p in sess.get("myTeam", [])
                            if p.get("cellId") == local_cell), None)
            if my_pick:
                cur_d = my_pick.get("spell1Id")
                cur_f = my_pick.get("spell2Id")
                want_d = int(CONFIG["summoner_d"])
                want_f = int(CONFIG["summoner_f"])
                key = f"{want_d}-{want_f}"
                if (cur_d, cur_f) != (want_d, want_f) and \
                        _session_state["last_summoner_set_for"] != key:
                    body = {"spell1Id": want_d, "spell2Id": want_f}
                    r, err = lcu_request("PATCH",
                        "/lol-champ-select/v1/session/my-selection", body)
                    if err is None:
                        _session_state["last_summoner_set_for"] = key
                        print(f"[auto] summoners -> D={want_d} F={want_f}", flush=True)


# -- Legion HTTP -------------------------------------------------------------

def post(path: str, data: dict) -> dict:
    req = urllib.request.Request(
        f"{LEGION}{path}",
        data=json.dumps(data).encode(),
        method="POST",
        headers={"X-RC-Token": TOKEN, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read())


def get(path: str) -> dict:
    req = urllib.request.Request(f"{LEGION}{path}",
                                  headers={"X-RC-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read())


# -- Team-context refresh (FU02) ---------------------------------------------

# SSL ctx for Legion's HTTPS dashboard (mkcert self-signed). Bearer auth
# is the actual identity gate; TLS here is just transport confidentiality.
_dash_ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_dash_ssl_ctx.check_hostname = False
_dash_ssl_ctx.verify_mode = ssl.CERT_NONE

# Lazy cache of championId -> display name, sourced from LCU's
# /lol-game-data/assets/v1/champion-summary.json. Populated once per
# agent boot. The route's _champ_name_to_id() reverses the lookup via
# ddragon, so we send Riot's canonical English name here and let the
# server side handle alt-name quirks.
_CHAMP_NAME_CACHE: dict = {}
_CHAMP_NAME_CACHE_LOADED = False


def _maybe_load_champion_names():
    """Populate _CHAMP_NAME_CACHE from LCU static data. Single-shot -
    once a non-empty mapping lands, never re-fetches. Soft-fails on
    network/parse errors; caller may retry next cycle."""
    global _CHAMP_NAME_CACHE_LOADED
    if _CHAMP_NAME_CACHE_LOADED:
        return
    if not _lcu["port"]:
        return
    data, err = lcu_request(
        "GET", "/lol-game-data/assets/v1/champion-summary.json")
    if err is not None or not isinstance(data, list):
        return
    for entry in data:
        if not isinstance(entry, dict):
            continue
        cid = entry.get("id")
        name = entry.get("name") or ""
        if isinstance(cid, int) and cid > 0 and name:
            _CHAMP_NAME_CACHE[cid] = str(name)
    if _CHAMP_NAME_CACHE:
        _CHAMP_NAME_CACHE_LOADED = True
        print(f"[lcu] loaded {len(_CHAMP_NAME_CACHE)} champion names",
              flush=True)


def _champion_name_for(cid) -> str:
    """Display name for a champion id, or "" when unknown. Empty is
    correct for the route - better a blank cell than a numeric id."""
    try:
        cid = int(cid or 0)
    except (TypeError, ValueError):
        return ""
    if cid <= 0:
        return ""
    return _CHAMP_NAME_CACHE.get(cid, "")


# Edge-detection state for the POST. Lives at module scope so all worker
# threads share the same view (only state-push thread writes it).
_team_context_state = {
    "last_phase":           None,    # phase from prior cycle
    "last_picks_signature": None,    # sorted (cellId, championId) tuples
    "last_post_at":         0.0,     # monotonic ts of last successful POST
}


def _picks_signature(cs: dict) -> tuple:
    """Stable signature over (cellId, championId) for both teams. The
    edge-trigger refires the POST whenever someone locks/swaps so the
    server-side mastery enrichment picks up the new champion id."""
    def _flat(team_arr):
        out = []
        for s in team_arr or []:
            if isinstance(s, dict):
                out.append((s.get("cellId"), s.get("championId", 0)))
        return tuple(sorted(out, key=lambda x: (x[0] is None, x[0])))
    return (_flat(cs.get("my_team")), _flat(cs.get("their_team")))


def _build_team_context_body(cs: dict) -> dict:
    """Translate champ_select snapshot -> /api/team-context/refresh body.
    Stamps team_id (100=ally side via myTeam, 200=enemy via theirTeam)
    and resolves locked-champion display name via _CHAMP_NAME_CACHE."""
    roster = []
    for slot in cs.get("my_team") or []:
        if not isinstance(slot, dict):
            continue
        roster.append({
            "puuid":           slot.get("puuid") or "",
            "summoner_name":   slot.get("summonerName") or "",
            "team_id":         100,
            "locked_champion": _champion_name_for(slot.get("championId")),
        })
    for slot in cs.get("their_team") or []:
        if not isinstance(slot, dict):
            continue
        roster.append({
            "puuid":           slot.get("puuid") or "",
            "summoner_name":   slot.get("summonerName") or "",
            "team_id":         200,
            "locked_champion": _champion_name_for(slot.get("championId")),
        })
    return {"queue_id": int(cs.get("queue_id") or 0), "roster": roster}


def post_team_context_refresh(body: dict) -> tuple[bool, str]:
    """POST roster snapshot to Legion's team-context endpoint. Returns
    (ok, detail). Never raises - a dashboard-offline / network error
    surfaces as (False, "<reason>"). The route is local-only and
    unauthenticated since the cross-Claude bridge was decommissioned
    (ADR-012), so no bearer is sent."""
    url = f"{LEGION_DASHBOARD}/api/team-context/refresh"
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Content-Type":  "application/json",
            "User-Agent":    "rc-lcu-agent/0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=4.0,
                                     context=_dash_ssl_ctx) as r:
            r.read()
        return (True, "ok")
    except urllib.error.HTTPError as exc:
        return (False, f"http_{exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return (False, f"network: {type(exc).__name__}")


def _maybe_refresh_team_context(state: dict) -> None:
    """Edge-triggered POST to /api/team-context/refresh. Called once per
    state-push cycle by `_state_push_loop`; no-op when not in
    champ-select or when nothing has changed since the last successful
    POST. Rate-limited to TEAM_CONTEXT_REPOST_S between re-fires."""
    phase = state.get("phase") or ""
    cs = state.get("champ_select") or {}
    prev_phase = _team_context_state["last_phase"]
    _team_context_state["last_phase"] = phase

    if phase != "ChampSelect" or not cs:
        # Reset edge-detect signatures when leaving CS so the next entry
        # always re-fires the initial POST.
        if prev_phase == "ChampSelect":
            _team_context_state["last_picks_signature"] = None
            _team_context_state["last_post_at"] = 0.0
        return

    # Champion-name cache may not be loaded yet on the first cycles
    # post-boot; retry until LCU returns the static data.
    _maybe_load_champion_names()

    sig = _picks_signature(cs)
    is_entry = (prev_phase != "ChampSelect")
    sig_changed = (sig != _team_context_state["last_picks_signature"])

    if not (is_entry or sig_changed):
        return
    if not is_entry:
        age = time.monotonic() - _team_context_state["last_post_at"]
        if age < TEAM_CONTEXT_REPOST_S:
            return  # rate-limit during locking flurry

    body = _build_team_context_body(cs)
    ok, detail = post_team_context_refresh(body)
    if ok:
        _team_context_state["last_picks_signature"] = sig
        _team_context_state["last_post_at"] = time.monotonic()
        print(f"[team-context] refresh OK queue={body['queue_id']} "
              f"roster={len(body['roster'])} entry={is_entry}",
              flush=True)
    else:
        # Don't latch sig on failure - next cycle will retry.
        print(f"[team-context] refresh failed: {detail}", flush=True)


# -- s219 Post Game Review: LCU match-detail auto-ingest ---------------------
#
# Edge-triggers on phase transition INTO EndOfGame. Fetches the operator's
# puuid + latest gameId + full /lol-match-history/v1/games/{gameId} payload,
# then POSTs to Legion's /api/last-match/ingest endpoint so the Post Game
# Review page is instant when the operator opens it.
#
# Tracked state survives the loop iteration so we only fire once per game
# end (until phase leaves EndOfGame OR a new gameId appears). The
# last_game_id_ingested ALSO persists to disk (INGEST_STATE_FILE) so an
# agent crash right at game end is recovered on next agent boot via
# _recover_missed_ingest().

_post_match_ingest_state = {
    "last_phase":             None,    # phase from prior cycle
    "last_game_id_ingested":  None,    # gameId we successfully shipped
    "last_post_at":           0.0,     # monotonic ts of last POST attempt
    "startup_recovery_done":  False,   # one-shot per agent boot
}

# Minimum interval between ingest POSTs even if EndOfGame re-fires.
POST_MATCH_INGEST_RATE_LIMIT_S = 10.0

_APP_DIR_LCU = Path(__file__).resolve().parent.parent   # repo root (Legion 1-PC)

# D6 edge-latch: bump force_scan exactly on the OFF->ON transition of the
# Cherry augment picker, deduped within a round, re-armed when it closes so
# each Arena round (1-4) fires once. Only the state-push thread touches this.
_augment_scan_state = {"was_open": False}


def _write_force_scan_marker() -> None:
    """Bump data/force_scan.json (tmp+replace, standalone - the agent cannot
    import core.polled_json). Payload matches dashboard/_writers.force_vision_scan
    and core.hotkeys: {"force": <ts>}."""
    p = _APP_DIR_LCU / "data" / "force_scan.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps({"force": time.time()}), encoding="utf-8")
    tmp.replace(p)


def _maybe_force_augment_scan(state: dict) -> None:
    """Edge-triggered force_scan bump on the Cherry augment picker opening.
    Fires ONLY on the False->True transition of state['cherry_augment_open'] so
    the free-running ~20s vision scan is pulled forward to OCR the transient
    augment panel before it closes (D6). Deduped while open; re-arms on close."""
    open_now = bool(state.get("cherry_augment_open"))
    was = _augment_scan_state["was_open"]
    _augment_scan_state["was_open"] = open_now
    if open_now and not was:
        _write_force_scan_marker()
        print("[augment-scan] force_scan bumped (Cherry picker opened)",
              flush=True)

# Persisted state path. Survives agent restart so a crash right at game end
# doesn't cause the next boot to miss the ingest.
INGEST_STATE_FILE = Path(os.environ.get(
    "RC_AGENT_STATE_FILE",
    "C:/RC-Agent/agent_state.json"
))


def _load_ingest_state() -> None:
    """Restore last_game_id_ingested from disk on agent boot. Safe to call
    even if the file is missing or malformed - empty state means
    everything will look uningested + recovery will fire."""
    try:
        if not INGEST_STATE_FILE.exists():
            return
        data = json.loads(INGEST_STATE_FILE.read_text(encoding="utf-8"))
        gid = data.get("last_game_id_ingested")
        if gid is not None:
            _post_match_ingest_state["last_game_id_ingested"] = gid
            print(f"[ingest-state] restored last_game_id_ingested={gid} "
                  f"from {INGEST_STATE_FILE}", flush=True)
    except (OSError, ValueError) as exc:
        print(f"[ingest-state] load failed (continuing fresh): {exc}",
              flush=True)


def _save_ingest_state() -> None:
    """Atomic write of the persisted ingest state. Called after each
    successful POST + after startup recovery."""
    try:
        INGEST_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = INGEST_STATE_FILE.with_suffix(INGEST_STATE_FILE.suffix + ".tmp")
        payload = {
            "last_game_id_ingested": _post_match_ingest_state["last_game_id_ingested"],
            "saved_at":              time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, INGEST_STATE_FILE)
    except OSError as exc:
        print(f"[ingest-state] save failed: {exc}", flush=True)


def _recover_missed_ingest() -> None:
    """One-shot startup check: fetch latest LCU gameId and POST ingest if
    it doesn't match our persisted last_game_id_ingested. Handles the
    "agent crashed right at game end" case where the agent died
    before /api/last-match/ingest was POSTed. Also catches "agent was
    offline when game ended" - operator restarts agent later, we
    auto-recover.

    Skipped silently when LCU is unreachable (operator hasn't launched
    League yet) - the regular state-push loop will retry as soon as
    LCU comes up. Skipped silently when latest gameId matches the
    persisted one (already shipped)."""
    if _post_match_ingest_state["startup_recovery_done"]:
        return
    try:
        # Probe LCU reachability - silent return if not up yet.
        summ, status = lcu_request("GET", "/lol-summoner/v1/current-summoner")
        if not isinstance(summ, dict):
            return
        puuid = (summ.get("puuid") or "").strip()
        if not puuid:
            return
        # Latest match summary.
        ml, _ = lcu_request("GET",
            f"/lol-match-history/v1/products/lol/{puuid}/matches"
            f"?begIndex=0&endIndex=1")
        if not isinstance(ml, dict):
            return
        games = (ml.get("games") or {}).get("games") or []
        if not games:
            _post_match_ingest_state["startup_recovery_done"] = True
            return
        gid = games[0].get("gameId")
        if not gid:
            _post_match_ingest_state["startup_recovery_done"] = True
            return
        last = _post_match_ingest_state["last_game_id_ingested"]
        if last == gid:
            print(f"[ingest-recovery] latest gameId={gid} matches persisted "
                  f"- no recovery needed", flush=True)
            _post_match_ingest_state["startup_recovery_done"] = True
            return
        # Mismatch - fetch full detail + POST.
        detail, _ = lcu_request("GET", f"/lol-match-history/v1/games/{gid}")
        if not isinstance(detail, dict):
            print(f"[ingest-recovery] couldn't fetch detail for gameId={gid}; "
                  f"will retry via EndOfGame path", flush=True)
            return
        ok, status = post_last_match_ingest(puuid, detail)
        if ok:
            _post_match_ingest_state["last_game_id_ingested"] = gid
            _post_match_ingest_state["last_post_at"] = time.monotonic()
            _save_ingest_state()
            _post_match_ingest_state["startup_recovery_done"] = True
            print(f"[ingest-recovery] shipped gameId={gid} on agent boot "
                  f"(persisted={last!r}, latest={gid}) - crash-recovery "
                  f"path engaged", flush=True)
        else:
            print(f"[ingest-recovery] POST failed: {status}; will retry "
                  f"via EndOfGame path", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[ingest-recovery] error (non-fatal): {exc}", flush=True)


def _fetch_latest_match_for_ingest():
    """Returns (puuid, gameId, match_detail_dict) or (None, None, None)
    on any failure. Never raises - caller treats triple-None as 'try
    again later'."""
    summ, _ = lcu_request("GET", "/lol-summoner/v1/current-summoner")
    if not isinstance(summ, dict):
        return (None, None, None)
    puuid = (summ.get("puuid") or "").strip()
    if not puuid:
        return (None, None, None)
    # Latest 1 match summary - gives us the gameId.
    ml, _ = lcu_request("GET",
        f"/lol-match-history/v1/products/lol/{puuid}/matches"
        f"?begIndex=0&endIndex=1")
    if not isinstance(ml, dict):
        return (None, None, None)
    games = (ml.get("games") or {}).get("games") or []
    if not games:
        return (None, None, None)
    gid = games[0].get("gameId")
    if not gid:
        return (None, None, None)
    # Full detail (the actual goldmine - 10 participants + teams + items + runes).
    detail, _ = lcu_request("GET", f"/lol-match-history/v1/games/{gid}")
    if not isinstance(detail, dict):
        return (None, None, None)
    return (puuid, gid, detail)


def post_last_match_ingest(tracked_puuid: str, match_detail: dict) -> tuple[bool, str]:
    """POST the LCU match detail to Legion. Returns (ok, detail).
    No auth header - /api/last-match/ingest is LAN-trust only for now
    (matches existing convention for /upload-lcu)."""
    url = f"{LEGION_DASHBOARD}/api/last-match/ingest"
    body = json.dumps({
        "tracked_puuid": tracked_puuid,
        "match_detail":  match_detail,
    }).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent":   "rc-lcu-agent/0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0,
                                     context=_dash_ssl_ctx) as r:
            r.read()
        return (True, "ok")
    except urllib.error.HTTPError as exc:
        return (False, f"http_{exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return (False, f"network: {type(exc).__name__}")


def _maybe_ingest_last_match(state: dict) -> None:
    """Edge-triggered POST to /api/last-match/ingest on EndOfGame entry.
    Called once per state-push cycle by `_state_push_loop`; no-op when
    not in EndOfGame or when we already shipped this game's detail.
    Rate-limited by POST_MATCH_INGEST_RATE_LIMIT_S between attempts to
    avoid hammering LCU + Legion if EndOfGame re-fires.

    Also retries the one-shot startup crash-recovery here so it gets a
    chance to run even when LCU was offline at agent boot time."""
    # Retry the crash-recovery if it hasn't successfully completed yet
    # (e.g. LCU wasn't running at boot, only came up later).
    if not _post_match_ingest_state.get("startup_recovery_done"):
        _recover_missed_ingest()

    phase = state.get("phase") or ""
    prior = _post_match_ingest_state["last_phase"]
    _post_match_ingest_state["last_phase"] = phase

    # We fire on (transition INTO EndOfGame) OR (sitting in EndOfGame and
    # haven't ingested yet - covers agent-restart-mid-EOG). Once shipped,
    # the gameId guard prevents re-fire.
    if phase != "EndOfGame":
        return
    now = time.monotonic()
    since_last = now - _post_match_ingest_state["last_post_at"]
    if since_last < POST_MATCH_INGEST_RATE_LIMIT_S:
        return

    puuid, gid, detail = _fetch_latest_match_for_ingest()
    if not (puuid and gid and detail):
        # LCU may not have finalized the match record yet - try again
        # next cycle. Don't update last_post_at so we don't back off.
        return
    if _post_match_ingest_state["last_game_id_ingested"] == gid:
        # Already shipped this game's detail this session.
        return

    _post_match_ingest_state["last_post_at"] = now
    ok, status = post_last_match_ingest(puuid, detail)
    if ok:
        _post_match_ingest_state["last_game_id_ingested"] = gid
        _save_ingest_state()  # persist for crash-recovery on next boot
        print(f"[last-match-ingest] shipped gameId={gid} "
              f"(transition {prior!r} -> EndOfGame)", flush=True)
    else:
        print(f"[last-match-ingest] POST failed: {status} "
              f"(gameId={gid}; will retry next cycle)", flush=True)


# -- Worker loops (one per concern) ------------------------------------------

def _state_push_loop():
    """Full snapshot + post to Legion. Slow OK during in-game.
    Backoff exponent capped at 6 (ie. 64s nominal, clamped to 30s) so we
    don't compute 2**huge_int after hours of failures."""
    consecutive_fail = 0
    while True:
        # E7 TODO-1: consume any pending swap-wake at the top so a swap that
        # lands DURING this capture/post still forces a fresh capture next
        # pass (the event stays set through the wait() below).
        _swap_wake.clear()
        try:
            state = capture_state()
            try:
                post("/upload-lcu", state)
                consecutive_fail = 0
            except Exception as e:  # noqa: BLE001
                consecutive_fail += 1
                print(f"  [push err {consecutive_fail}x] {e}", flush=True)
            # FU02 last-mile: edge-fire team-context refresh on
            # ChampSelect entry + on lock/swap. Independent of the
            # vision-relay push above - failure here MUST NOT bump
            # consecutive_fail or affect the upload-lcu cadence.
            try:
                _maybe_refresh_team_context(state)
            except Exception as e:  # noqa: BLE001
                print(f"  [team-context err] {e}", flush=True)
            # s219 Post Game Review: edge-fire LCU match-detail ingest
            # on EndOfGame transition so the Post Game Review page is
            # instant. Same isolation as team-context above.
            try:
                _maybe_ingest_last_match(state)
            except Exception as e:  # noqa: BLE001
                print(f"  [last-match-ingest err] {e}", flush=True)
            # D6: edge-fire a force_scan when the Arena/Cherry augment picker
            # opens so vision OCRs the transient panel before it closes.
            # Same isolation as the neighbours - MUST NOT affect the push cadence.
            try:
                _maybe_force_augment_scan(state)
            except Exception as e:  # noqa: BLE001
                print(f"  [augment-scan err] {e}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[state loop err] {e}", flush=True)
        # E7 TODO-1: wake early when the cmd loop drained a latency-sensitive
        # batch (bench swap / reroll / accept) so the new pick reflects in
        # ~BENCH_CMD_FAST_INTERVAL; an idle wait still times out at the
        # normal cadence (identical to the old sleep when no swap fires).
        if consecutive_fail >= 3:
            exp = min(consecutive_fail - 2, 6)
            _swap_wake.wait(timeout=min(30.0, INTERVAL * (2 ** exp)))
        else:
            _swap_wake.wait(timeout=INTERVAL)


def _auto_features_loop():
    """Ready-check + summoner-override poll. Stays at AUTO_INTERVAL cadence
    independent of state-push cycle so the 12s ready-check window never
    closes on us - auto_features makes its OWN /ready-check GET (cheap;
    LCU responds in ~50ms during queue, even with League busy)."""
    while True:
        try:
            ensure_lcu_conn()
            auto_features()
        except Exception as e:  # noqa: BLE001
            print(f"[auto loop err] {e}", flush=True)
        time.sleep(AUTO_INTERVAL)


def drain_once(get_fn, post_fn, exec_fn):
    """Drain ONE /lcu-cmd-pending batch. Returns (processed, fast).

    ``processed`` = number of queued commands handled this pass.
    ``fast`` = True iff the drained batch held a latency-sensitive command
    (bench_swap / reroll / accept_ready) - the caller then re-polls at
    BENCH_CMD_FAST_INTERVAL instead of the full CMD_INTERVAL so a fresh
    ARAM bench swap is not stuck behind a 0.5s idle wait.

    CONTRACT (preserved from _cmd_poll_loop): every command posts a
    definitive /lcu-cmd-done result back even when execute_command RAISES,
    so /api/lcu-cmd-result flows never hang. A failing result POST is
    swallowed (the loop keeps draining). ``fast`` is driven by the command
    TYPE, not by success, so a failed latency-sensitive cmd still re-polls
    fast (the next click should not eat the idle wait either)."""
    pending = get_fn("/lcu-cmd-pending")
    items = pending.get("commands", []) if isinstance(pending, dict) else []
    processed = 0
    fast = False
    for item in items:
        cid = item.get("id")
        cmd = item.get("cmd") or {}
        if cmd.get("cmd") in LATENCY_SENSITIVE_CMDS:
            fast = True
        try:
            result = exec_fn(cmd)
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "err": f"{type(exc).__name__}: {exc}"}
            print(f"  [cmd-exc] {cmd.get('cmd')} -> {result}", flush=True)
        else:
            print(f"  [cmd] {cmd.get('cmd')} -> {result}", flush=True)
        try:
            post_fn("/lcu-cmd-done", {"id": cid, "result": result})
        except Exception:  # noqa: BLE001
            pass
        processed += 1
    return processed, fast


def _signal_state_refresh(fast: bool, processed: int) -> bool:
    """RC2 E7 TODO-1: wake _state_push_loop immediately after a
    latency-sensitive drain so a freshly swapped champ reflects in
    /api/state in ~BENCH_CMD_FAST_INTERVAL rather than the full INTERVAL.

    Wakes ONLY when a latency-sensitive batch actually moved a command
    (``fast and processed``). Returns True iff the wake was signalled."""
    if fast and processed:
        _swap_wake.set()
        return True
    return False


def _cmd_poll_loop():
    """Drain Legion's command queue. Posts results back even on exception
    so dashboard flows always see a definitive ok/err. Re-polls FAST after
    a latency-sensitive batch (RC2 E7a) and wakes the state-push loop
    (E7 TODO-1), full idle sleep otherwise."""
    while True:
        fast = False
        _processed = 0
        try:
            _processed, fast = drain_once(get, post, execute_command)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"  [cmd-poll err] {e}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"  [cmd-poll err] {e}", flush=True)
        _signal_state_refresh(fast, _processed)
        time.sleep(BENCH_CMD_FAST_INTERVAL if fast else CMD_INTERVAL)


def loop() -> None:
    print(f"lcu agent -> {LEGION} state={INTERVAL}s auto={AUTO_INTERVAL}s cmd={CMD_INTERVAL}s",
          flush=True)
    # s219: restore persisted ingest state + one-shot crash-recovery for
    # a missed EndOfGame POST. Both no-op gracefully if LCU isn't up yet
    # (the state-push loop's normal EndOfGame trigger handles the live
    # case once League comes online).
    _load_ingest_state()
    _recover_missed_ingest()
    for fn in (_state_push_loop, _auto_features_loop, _cmd_poll_loop):
        threading.Thread(target=fn, daemon=True, name=fn.__name__).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    try: loop()
    except KeyboardInterrupt: sys.exit(0)

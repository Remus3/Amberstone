"""
gamepc_lcu_agent.py - Game-PC agent that bridges the LCU API to Legion.

Runs on Game-PC (192.168.8.237). Reads the LCU lockfile, polls champ-select /
gameflow / ready-check, and pushes state to Legion's vision server. Also polls
Legion for queued commands (auto-accept, bench swap, summoner-spell change,
lock pick, reroll) and executes them via LCU.

Deploy on Game-PC (one time):
  1. Copy this file to C:\\RC-Agent\\
  2. py -m pip install (none - stdlib only)
  3. py C:\\RC-Agent\\gamepc_lcu_agent.py
  4. (optional) schtasks /Create /TN "RC-LCU" /SC ONLOGON /F /RL HIGHEST /TR "py C:\\RC-Agent\\gamepc_lcu_agent.py"

Endpoints used on Legion:
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
    cfg = _Path_tok(__file__).resolve().parent / "vision_token.txt"
    try:
        if cfg.exists():
            line = cfg.read_text(encoding="utf-8").splitlines()[0].strip()
            if line: return line
    except OSError: pass
    return "8e8f131e212b329438218eca27372dde"

def _resolve_bridge_secret() -> str:
    """Resolve the cross-Claude bridge bearer secret used to auth to
    Legion's :8888/api/team-context/refresh route. Lookup order:

      1. RC_BRIDGE_SECRET env var
      2. bridge_secret.txt sibling file (single line)
      3. local_paths.json sibling file ({"bridge_shared_secret": "..."})

    Returns "" when nothing is configured. Callers MUST treat empty as
    "skip the POST" - there is no historical default to fall back to,
    and an unauthenticated POST would 401 anyway.
    """
    env = _os_tok.environ.get("RC_BRIDGE_SECRET")
    if env: return env.strip()
    here = _Path_tok(__file__).resolve().parent
    txt = here / "bridge_secret.txt"
    try:
        if txt.exists():
            line = txt.read_text(encoding="utf-8").splitlines()[0].strip()
            if line: return line
    except OSError: pass
    cfg = here / "local_paths.json"
    try:
        if cfg.exists():
            data = json.loads(cfg.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                secret = data.get("bridge_shared_secret") or ""
                return str(secret).strip()
    except (OSError, ValueError): pass
    return ""

TOKEN  = _resolve_auth_token()
BRIDGE_SECRET = _resolve_bridge_secret()    # "" → team-context POST skipped
INTERVAL      = 1.0   # state-push cadence (slow during in-game; OK)
AUTO_INTERVAL = 0.5   # ready-check / summoner-override poll cadence
CMD_INTERVAL  = 0.5   # Legion command-queue drain cadence
# Min seconds between team-context POSTs while still in champ-select.
# The route is idempotent - re-posting just refreshes the cache, but no
# point hammering it on every 1s state-push cycle.
TEAM_CONTEXT_REPOST_S = 3.0

# ARAM-family queue IDs. Mirror of the aram keys in
# core/queue_modes.QUEUE_ID_TO_MODE_KEY (this agent runs standalone on
# Game-PC and can't import core.*, so it's a hand-kept mirror - keep
# the two in sync). 2400 = ARAM Mayhem (KIWI gameMode); its absence
# here is why is_aram was False for Mayhem → the dashboard's
# _csvDetectMode fell through to "sr" and the bench / quick-swap UI
# never rendered (KNOWN BUG 2026-05-17).
_ARAM_QUEUE_IDS = frozenset({450, 720, 920, 2400})

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

def read_lockfile():
    for p in LOCKFILE_PATHS:
        if p.exists():
            try:
                # Format: name:pid:port:password:protocol
                parts = p.read_text(encoding="utf-8").strip().split(":")
                if len(parts) >= 5:
                    return parts[2], parts[3]
            except Exception:
                pass
    return None, None


def ensure_lcu_conn():
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


def lcu_request(method, path, body=None):
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
            except Exception:
                return raw, None
    except urllib.error.HTTPError as e:
        return None, f"http {e.code}"
    except Exception as e:
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

# queue_id → human-readable name. Dashboard falls back to ("queue " + id)
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
    1700: "Arena",
    1710: "Arena (no AFK)",
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

def _active_round(sess: dict) -> dict | None:
    """Distil session.actions[] into ``{type, cell_ids}`` for the round
    currently on the clock, or None when no action is in progress.

    LCU `session.actions` is array-of-arrays: each inner array is a "round"
    (one ban round, one pick round, etc.). Within a round an action has
    fields including ``actorCellId``, ``type`` (pick|ban), ``championId``,
    ``completed`` (bool), ``isInProgress`` (bool). The cells currently on
    the clock are the in-progress entries; the round's type is the action
    type they share (ban or pick). Used by the dashboard to highlight the
    active border on ally + enemy slots.
    """
    actions = sess.get("actions") or []
    for group in actions:
        if not isinstance(group, list):
            continue
        in_progress = [a for a in group
                       if isinstance(a, dict) and a.get("isInProgress")]
        if not in_progress:
            continue
        # Group should be homogeneous (all bans or all picks). Pick the
        # type from the first in-progress entry and collect its cells.
        kind = "ban" if str(in_progress[0].get("type", "")) == "ban" else "pick"
        cell_ids = [a.get("actorCellId") for a in in_progress
                    if str(a.get("type", "")) == kind
                    and a.get("actorCellId") is not None]
        return {"type": kind, "cell_ids": cell_ids}
    return None


def _swap_entries(arr) -> list[dict]:
    """Slim ``positionSwaps`` / ``pickOrderSwaps`` for the agent push.

    Each LCU entry carries id + cellId + state (AVAILABLE / SENT / RECEIVED /
    ACCEPTED / DECLINED / BUSY / INVALID). The dashboard only needs those
    three fields to render and the handlers below look them up by cell_id
    on swap requests.
    """
    out = []
    for e in arr or []:
        if not isinstance(e, dict):
            continue
        out.append({
            "id":     e.get("id"),
            "cellId": e.get("cellId"),
            "state":  e.get("state"),
        })
    return out


def _arena_teams(sess: dict) -> list[dict]:
    """Distil ``additionalSubteamData`` for the dashboard's Arena enemies
    pane (TEAM 2 / TEAM 3 / TEAM 4 stacked cards).

    LCU emits one entry per sub-team in 2v2v2v2; we forward id, name, an
    ``is_me`` flag (subteam id matches the local cell's subteam id), and
    a slim members list (cellId + championId only - the dashboard already
    has summoner names in ``my_team``/``their_team``).

    Returns an empty list when the session is not in a subteamed queue
    or when LCU has not yet populated the field (pre-reveal).
    """
    raw = sess.get("additionalSubteamData") or []
    if not isinstance(raw, list) or not raw:
        return []
    my_subteam = None
    try:
        local_cell = int(sess.get("localPlayerCellId", -1))
    except (TypeError, ValueError):
        local_cell = -1
    if local_cell >= 0:
        for tm in raw:
            if not isinstance(tm, dict):
                continue
            members = tm.get("members") or []
            if any(isinstance(m, dict) and int(m.get("cellId", -2)) == local_cell
                   for m in members):
                my_subteam = tm.get("subteamId") or tm.get("id")
                break
    out = []
    for tm in raw:
        if not isinstance(tm, dict):
            continue
        sid = tm.get("subteamId") or tm.get("id")
        cells = []
        for m in tm.get("members") or []:
            if not isinstance(m, dict):
                continue
            cells.append({
                "cellId":     m.get("cellId"),
                "championId": m.get("championId", 0),
            })
        out.append({
            "id":    sid,
            "name":  tm.get("name") or f"Team {sid}",
            "is_me": (my_subteam is not None and sid == my_subteam),
            "cells": cells,
        })
    return out


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


def capture_state():
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
    # shape when that block runs. Rides the existing 1s push → cached
    # on Legion's vision server → no Game-PC console / screen capture
    # needed to root-cause the remaining uncertainty.
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
            state["lobby"] = {
                "queue_id":     qid_int,
                "queue_name":   _LOBBY_QUEUE_NAMES.get(qid_int, ""),
                "is_custom":    bool(gconf.get("isCustom")),
                "game_mode":    gconf.get("gameMode") or "",
                "map_id":       gconf.get("mapId") or 0,
                "party_id":     str(lob.get("partyId") or ""),
                "party_type":   str(lob.get("partyType") or "open").lower(),
                "can_search":   bool(lob.get("canStartActivity")),
                "is_leader":    bool(local_member and local_member.get("is_leader")),
                "search_state": _derive_search_state(state["phase"], search),
                "members":      members,
                "local_member": local_member,
            }

    if state["phase"] in ("ChampSelect", "GameStart", "InProgress"):
        sess, _ = lcu_request("GET", "/lol-champ-select/v1/session")
        # KNOWN-BUG diagnostic enrichment: did /lol-champ-select/v1/
        # session even return a dict for this mode? For KIWI / Mayhem
        # the open question is whether the agent ever sees a populated
        # champ-select session at all. The full queue object (id /
        # mapId / gameMode / type) is the robust signal a future
        # is_aram could key off instead of a brittle queue-id list -
        # capture its real shape live rather than guessing it now.
        state["cs_debug"]["cs_session_is_dict"] = isinstance(sess, dict)
        if isinstance(sess, dict):
            _q = (sess.get("gameData", {}).get("queue", {})
                  if "gameData" in sess else {})
            state["cs_debug"]["queue_obj"] = {
                "id":       _q.get("id"),
                "mapId":    _q.get("mapId"),
                "gameMode": _q.get("gameMode"),
                "type":     _q.get("type"),
                "category": _q.get("category"),
            }
            state["cs_debug"]["bench_len"] = len(
                sess.get("benchChampions", []) or [])
        if isinstance(sess, dict):
            local_cell = sess.get("localPlayerCellId", -1)
            my_pick = next((p for p in sess.get("myTeam", [])
                            if p.get("cellId") == local_cell), None)
            queue_id = (sess.get("gameData", {}).get("queue", {}).get("id", 0)
                        if "gameData" in sess else 0)
            # 2026-05-09 (s154): /lol-champ-select/v1/session frequently omits
            # gameData during BAN_PICK, leaving queue_id=0. The dashboard's
            # sr_draft gate (is_sr_draft_queue) then evaluates False and the
            # entire DS engine-profile chooser block stays hidden - no champion
            # hints during draft. Fall back to /lol-gameflow/v1/session, which
            # carries gameData.queue.id reliably from queue-pop onward.
            if not queue_id:
                gf, _ = lcu_request("GET", "/lol-gameflow/v1/session")
                if isinstance(gf, dict):
                    queue_id = (gf.get("gameData", {}).get("queue", {})
                                .get("id", 0) or 0)
            # 2026-04-25: include full myTeam + theirTeam arrays so the
            # dashboard can run cold-start adaptation lookups during
            # champ-select (champion + matchup history) without waiting
            # for the game to start.
            def _team_picks(team_arr):
                out = []
                for p in team_arr or []:
                    if not isinstance(p, dict): continue
                    # s171 hover fix: championId is 0 until lock; the
                    # hovered champ lives in championPickIntent. Surface
                    # both so the dashboard can render hover state and
                    # locked state distinctly, and ``championId`` falls
                    # back to the intent so legacy renderers that read
                    # only championId still see the hover.
                    cid_locked = p.get("championId", 0) or 0
                    cid_intent = p.get("championPickIntent", 0) or 0
                    cid_effective = cid_locked or cid_intent
                    out.append({
                        "cellId":      p.get("cellId"),
                        "championId":  cid_effective,
                        "champion_pick_intent": cid_intent,
                        "champion_locked": cid_locked,
                        "summonerId":  p.get("summonerId"),
                        "summonerName": p.get("summonerInternalName") or p.get("displayName") or "",
                        # FU02 team-context refresh needs PUUIDs to fan out
                        # to Riot Web API. theirTeam may carry empty puuid
                        # before reveal in some queue types - that's fine,
                        # the route's worker skips entries with no puuid.
                        "puuid":       p.get("puuid") or "",
                        "completed":   p.get("completed", False),
                        "assignedPosition": p.get("assignedPosition") or "",
                        # s166 Phase 3 step 4: per-player summoner-spell ids
                        # so the Loading view can render the D/F icons next
                        # to each summoner. 0/0 when not yet picked.
                        "summoners":   [p.get("spell1Id", 0),
                                        p.get("spell2Id", 0)],
                    })
                return out
            # s171 hover fix: my_champion = locked OR hovered. The lock
            # button visibility on the dashboard depends on this - if
            # the operator is hovering Vayne, my_champion should be 67
            # so the lock button activates.
            _my_locked = (my_pick or {}).get("championId", 0) or 0
            _my_intent = (my_pick or {}).get("championPickIntent", 0) or 0
            # s171.3: my_completed needs to come from the actions array,
            # not myTeam[i]. myTeam[i] doesn't have a 'completed' field
            # in LCU's schema - it's always returning False here, which
            # made the dashboard show "HOVERING" forever even after lock.
            # The true lock state is sess.actions[N][M].completed for
            # the local cell's pick action with type == "pick".
            _my_done = False
            for group in sess.get("actions", []) or []:
                if not isinstance(group, list): continue
                for action in group:
                    if not isinstance(action, dict): continue
                    if action.get("type") != "pick": continue
                    try: actor = int(action.get("actorCellId", -2))
                    except (TypeError, ValueError): continue
                    try: local = int(local_cell) if local_cell is not None else -1
                    except (TypeError, ValueError): local = -1
                    if actor != local: continue
                    if action.get("completed"):
                        _my_done = True
                        break
                if _my_done: break
            state["champ_select"] = {
                "queue_id":     queue_id,
                "is_aram":      queue_id in _ARAM_QUEUE_IDS,
                "is_brawl":     queue_id == 480,
                # s171.3: local_cell exposed so the dashboard's role
                # resolver (_csvResolveRole) can find my_team[i] by
                # cellId == local_cell to read assignedPosition. Without
                # this the role stays "-" and the P&B fetch never fires.
                "local_cell":   local_cell if isinstance(local_cell, int) else -1,
                "my_champion":  _my_locked or _my_intent,
                "my_champion_locked":  _my_locked,
                "my_champion_intent":  _my_intent,
                "my_completed": _my_done,
                "my_summoners": [
                    (my_pick or {}).get("spell1Id", 0),
                    (my_pick or {}).get("spell2Id", 0),
                ],
                "bench": [c.get("championId") for c in sess.get("benchChampions", [])
                          if isinstance(c, dict)],
                "phase": (sess.get("timer") or {}).get("phase"),
                "my_team":     _team_picks(sess.get("myTeam")),
                "their_team":  _team_picks(sess.get("theirTeam")),
                "trades": [
                    {"id": t.get("id"), "cellId": t.get("cellId"),
                     "state": t.get("state")}
                    for t in (sess.get("trades") or [])
                    if isinstance(t, dict)
                ],
                # Swap candidate lists. Mirror trades - slim id/cellId/state
                # so the dashboard can render the SWAP popup and the
                # request_position_swap / request_pick_order_swap handlers
                # below resolve cell_id → swap id without a 2nd LCU GET.
                "position_swaps":   _swap_entries(sess.get("positionSwaps")),
                "pick_order_swaps": _swap_entries(sess.get("pickOrderSwaps")),
                # Active round (cells on the clock + pick|ban). Drives the
                # ally/enemy gold (pick) / red (ban) active border in the
                # Champ Select view.
                "active_round": _active_round(sess),
            }
            # Arena (2v2v2v2 / Cherry) extras. LCU surfaces sub-team
            # rosters via ``additionalSubteamData`` (id, name, intro
            # animation, members[cellId, championId]); the dashboard
            # consumes ``arena_teams`` as a flat list. Augment intent +
            # options need /lol-cherry/v1/* discovery against a live
            # Arena game - until then we only forward the subteam roster
            # so allies + enemies render correctly; augments stays an
            # empty scaffold and ``set_augment_intent`` no-ops.
            if queue_id in (1700, 1710):
                state["champ_select"]["arena_teams"] = _arena_teams(sess)
                state["champ_select"]["augments"] = {
                    "my_slots":      ["", "", ""],
                    "options":       [],
                    "current_round": 0,
                }
    # Capture Riot game_id from gameflow session when a game is live.
    # Used by Legion's DS calibration pipeline for post-game correlation.
    if state["phase"] in ("GameStart", "InProgress"):
        gflow, _ = lcu_request("GET", "/lol-gameflow/v1/session")
        if isinstance(gflow, dict):
            gid = str(gflow.get("gameData", {}).get("gameId") or "")
            if gid and gid != "0":
                state["game_id"] = gid

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

def execute_command(cmd):
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
        pages, _ = lcu_request("GET", "/lol-perks/v1/pages")
        if isinstance(pages, list):
            for pg in pages:
                if (isinstance(pg, dict) and pg.get("isDeletable")
                        and str(pg.get("name", "")).startswith("RC: ")):
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
        # resolve cell_id → swap id via session.positionSwaps[]. LCU
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
        # Arena/Cherry augment selection. The dashboard's augment chooser
        # fires this with ``augment_id`` for the active round slot. The
        # exact LCU endpoint (under /lol-cherry/v1/*) needs to be confirmed
        # against a live Arena lobby - Cherry's REST surface isn't well
        # documented. Until then, queue it as a no-op so the agent doesn't
        # crash on unknown-cmd and the dashboard surfaces "not yet wired"
        # rather than a phantom error.
        aug_id = int(cmd.get("augment_id", 0))
        if aug_id <= 0:
            return {"ok": False, "err": "no augment_id"}
        print(f"[cmd] set_augment_intent augment={aug_id} (no-op - "
              "LCU /lol-cherry/v1/* endpoint TBD)", flush=True)
        return {"ok": False, "err": "augment_intent_unsupported",
                "note": "needs /lol-cherry/v1/* discovery vs. live Arena",
                "augment_id": aug_id}
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
    # ── Phase B lobby controls (s171) ─────────────────────────────────
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
        # descriptors - we send one. The dashboard provides riot_id
        # ("Name#TAG") which is converted to summoner_id via lookup.
        rid = str(cmd.get("riot_id") or "").strip()
        sid = cmd.get("summoner_id")
        if not rid and not sid:
            return {"ok": False, "err": "riot_id or summoner_id required"}
        if not sid and rid and "#" in rid:
            name_, _, tag = rid.partition("#")
            # /lol-summoner/v1/summoners/by-name/<name>#<tag> on newer
            # builds; older builds use /lol-summoner/v1/summoners/by-name/<name>
            # without the tag. Try both, prefer the by-name+tag path.
            looked, _ = lcu_request("GET",
                f"/lol-summoner/v1/summoners/by-name/{name_}-{tag}")
            if not isinstance(looked, dict):
                looked, _ = lcu_request("GET",
                    f"/lol-summoner/v1/summoners/by-name/{name_}")
            if isinstance(looked, dict):
                sid = looked.get("summonerId")
        if not sid:
            return {"ok": False, "err": f"could not resolve summoner: {rid}"}
        body = [{"toSummonerId": int(sid)}]
        _, err = lcu_request("POST", "/lol-lobby/v2/lobby/invitations", body)
        return {"ok": err is None, "err": err,
                "riot_id": rid, "summoner_id": sid}
    if name == "lobby.promote_leader":
        # Hand party leadership to another member. Resolve riot_id (or
        # summoner_id) → member_id by walking the current lobby members
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
        # Practice Tool uses queue_id 0 + customGameLobby config.
        # The minimal create payload - Riot does most of the work.
        body = {
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
            "isCustom": True,
        }
        _, err = lcu_request("POST", "/lol-lobby/v2/lobby", body)
        return {"ok": err is None, "err": err}
    return {"ok": False, "err": f"unknown cmd: {name}"}


def auto_features():
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

def post(path, data):
    req = urllib.request.Request(
        f"{LEGION}{path}",
        data=json.dumps(data).encode(),
        method="POST",
        headers={"X-RC-Token": TOKEN, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read())


def get(path):
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

# Lazy cache of championId → display name, sourced from LCU's
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
    "warned_no_secret":     False,   # one-shot log gate
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
    """Translate champ_select snapshot → /api/team-context/refresh body.
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


def post_team_context_refresh(body: dict):
    """POST roster snapshot to Legion's team-context endpoint. Returns
    (ok, detail). Never raises - bridge auth missing or dashboard
    offline both surface as (False, "<reason>")."""
    if not BRIDGE_SECRET:
        return (False, "no_bridge_secret")
    url = f"{LEGION_DASHBOARD}/api/team-context/refresh"
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {BRIDGE_SECRET}",
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

    # Bridge secret missing - warn once, never spam the log.
    if not BRIDGE_SECRET:
        if not _team_context_state["warned_no_secret"]:
            print("[team-context] bridge secret unset - skipping refresh "
                  "POST. Set RC_BRIDGE_SECRET env or drop bridge_secret.txt.",
                  flush=True)
            _team_context_state["warned_no_secret"] = True
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
# last_game_id_ingested ALSO persists to disk (INGEST_STATE_FILE) so a
# Game-PC crash right at game end is recovered on next agent boot via
# _recover_missed_ingest().

_post_match_ingest_state = {
    "last_phase":             None,    # phase from prior cycle
    "last_game_id_ingested":  None,    # gameId we successfully shipped
    "last_post_at":           0.0,     # monotonic ts of last POST attempt
    "startup_recovery_done":  False,   # one-shot per agent boot
}

# Minimum interval between ingest POSTs even if EndOfGame re-fires.
POST_MATCH_INGEST_RATE_LIMIT_S = 10.0

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
    "Game-PC crashed right at game end" case where the agent died
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
    except Exception as exc:
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


def post_last_match_ingest(tracked_puuid: str, match_detail: dict):
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
              f"(transition {prior!r} → EndOfGame)", flush=True)
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
        try:
            state = capture_state()
            try:
                post("/upload-lcu", state)
                consecutive_fail = 0
            except Exception as e:
                consecutive_fail += 1
                print(f"  [push err {consecutive_fail}x] {e}", flush=True)
            # FU02 last-mile: edge-fire team-context refresh on
            # ChampSelect entry + on lock/swap. Independent of the
            # vision-relay push above - failure here MUST NOT bump
            # consecutive_fail or affect the upload-lcu cadence.
            try:
                _maybe_refresh_team_context(state)
            except Exception as e:
                print(f"  [team-context err] {e}", flush=True)
            # s219 Post Game Review: edge-fire LCU match-detail ingest
            # on EndOfGame transition so the Post Game Review page is
            # instant. Same isolation as team-context above.
            try:
                _maybe_ingest_last_match(state)
            except Exception as e:
                print(f"  [last-match-ingest err] {e}", flush=True)
        except Exception as e:
            print(f"[state loop err] {e}", flush=True)
        if consecutive_fail >= 3:
            exp = min(consecutive_fail - 2, 6)
            time.sleep(min(30.0, INTERVAL * (2 ** exp)))
        else:
            time.sleep(INTERVAL)


def _auto_features_loop():
    """Ready-check + summoner-override poll. Stays at AUTO_INTERVAL cadence
    independent of state-push cycle so the 12s ready-check window never
    closes on us - auto_features makes its OWN /ready-check GET (cheap;
    LCU responds in ~50ms during queue, even with League busy)."""
    while True:
        try:
            ensure_lcu_conn()
            auto_features()
        except Exception as e:
            print(f"[auto loop err] {e}", flush=True)
        time.sleep(AUTO_INTERVAL)


def _cmd_poll_loop():
    """Drain Legion's command queue. Posts results back even on exception
    so dashboard flows always see a definitive ok/err."""
    while True:
        try:
            pending = get("/lcu-cmd-pending")
            items = pending.get("commands", []) if isinstance(pending, dict) else []
            for item in items:
                cid = item.get("id")
                cmd = item.get("cmd") or {}
                try:
                    result = execute_command(cmd)
                except Exception as exc:
                    result = {"ok": False, "err": f"{type(exc).__name__}: {exc}"}
                    print(f"  [cmd-exc] {cmd.get('cmd')} -> {result}", flush=True)
                else:
                    print(f"  [cmd] {cmd.get('cmd')} -> {result}", flush=True)
                try:
                    post("/lcu-cmd-done", {"id": cid, "result": result})
                except Exception:
                    pass
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"  [cmd-poll err] {e}", flush=True)
        except Exception as e:
            print(f"  [cmd-poll err] {e}", flush=True)
        time.sleep(CMD_INTERVAL)


def loop():
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

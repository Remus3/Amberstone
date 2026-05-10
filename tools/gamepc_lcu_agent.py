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
auto_accept=on so existing behaviour is preserved without explicit setup.

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
    "skip the POST" — there is no historical default to fall back to,
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
# The route is idempotent — re-posting just refreshes the cache, but no
# point hammering it on every 1s state-push cycle.
TEAM_CONTEXT_REPOST_S = 3.0

LOCKFILE_PATHS = [
    Path(r"C:\Riot Games\League of Legends\lockfile"),
    Path(r"C:\Riot Games\League of Legends (PBE)\lockfile"),
    Path(r"D:\Riot Games\League of Legends\lockfile"),
]

# In-memory config; mutated by 'set_config' commands from dashboard.
CONFIG = {
    "auto_accept":     True,
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


# -- State capture -----------------------------------------------------------

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

    if state["phase"] in ("ReadyCheck", "Matchmaking", "Lobby"):
        rc, _ = lcu_request("GET", "/lol-matchmaking/v1/ready-check")
        if isinstance(rc, dict):
            state["ready_check"] = {
                "state":          rc.get("state"),
                "playerResponse": rc.get("playerResponse"),
                "timer":          rc.get("timer"),
            }

    if state["phase"] in ("ChampSelect", "GameStart", "InProgress"):
        sess, _ = lcu_request("GET", "/lol-champ-select/v1/session")
        if isinstance(sess, dict):
            local_cell = sess.get("localPlayerCellId", -1)
            my_pick = next((p for p in sess.get("myTeam", [])
                            if p.get("cellId") == local_cell), None)
            queue_id = (sess.get("gameData", {}).get("queue", {}).get("id", 0)
                        if "gameData" in sess else 0)
            # 2026-04-25: include full myTeam + theirTeam arrays so the
            # dashboard can run cold-start adaptation lookups during
            # champ-select (champion + matchup history) without waiting
            # for the game to start.
            def _team_picks(team_arr):
                out = []
                for p in team_arr or []:
                    if not isinstance(p, dict): continue
                    out.append({
                        "cellId":      p.get("cellId"),
                        "championId":  p.get("championId", 0),
                        "summonerId":  p.get("summonerId"),
                        "summonerName": p.get("summonerInternalName") or p.get("displayName") or "",
                        # FU02 team-context refresh needs PUUIDs to fan out
                        # to Riot Web API. theirTeam may carry empty puuid
                        # before reveal in some queue types — that's fine,
                        # the route's worker skips entries with no puuid.
                        "puuid":       p.get("puuid") or "",
                        "completed":   p.get("completed", False),
                        "assignedPosition": p.get("assignedPosition") or "",
                    })
                return out
            state["champ_select"] = {
                "queue_id":     queue_id,
                "is_aram":      queue_id in (450, 920),
                "my_champion":  (my_pick or {}).get("championId", 0),
                "my_completed": (my_pick or {}).get("completed", False),
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
                "local_cell": local_cell,
            }
    # Capture Riot game_id from gameflow session when a game is live.
    # Used by Legion's DS calibration pipeline for post-game correlation.
    if state["phase"] in ("GameStart", "InProgress"):
        gflow, _ = lcu_request("GET", "/lol-gameflow/v1/session")
        if isinstance(gflow, dict):
            gid = str(gflow.get("gameData", {}).get("gameId") or "")
            if gid and gid != "0":
                state["game_id"] = gid

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
        # Push a custom item set (Phase 2). Replaces any existing RC-
        # prefixed item set; preserves the user other item sets.
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
        sets = [s for s in sets if not str(s.get("uid", "")).startswith("RC-")]
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
        cid = int(cmd.get("championId", 0))
        if cid <= 0: return {"ok": False, "err": "no champ"}
        r, err = lcu_request("POST", f"/lol-champ-select/v1/session/bench/swap/{cid}")
        return {"ok": err is None, "err": err}
    if name == "set_summoners":
        d = int(cmd.get("d", 0)); f = int(cmd.get("f", 0))
        body = {"spell1Id": d, "spell2Id": f}
        r, err = lcu_request("PATCH", "/lol-champ-select/v1/session/my-selection", body)
        return {"ok": err is None, "err": err}
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
        local_cell = sess.get("localPlayerCellId", -1)
        for group in sess.get("actions", []):
            for action in group:
                if (action.get("actorCellId") == local_cell
                        and action.get("type") == "pick"
                        and not action.get("completed", False)):
                    aid = action.get("id")
                    body = {"championId": cid, "completed": True}
                    r, err = lcu_request("PATCH",
                        f"/lol-champ-select/v1/session/actions/{aid}", body)
                    return {"ok": err is None, "err": err}
        return {"ok": False, "err": "no pending pick action"}
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
    """Populate _CHAMP_NAME_CACHE from LCU static data. Single-shot —
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
    correct for the route — better a blank cell than a numeric id."""
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
    (ok, detail). Never raises — bridge auth missing or dashboard
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

    # Bridge secret missing — warn once, never spam the log.
    if not BRIDGE_SECRET:
        if not _team_context_state["warned_no_secret"]:
            print("[team-context] bridge secret unset — skipping refresh "
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
        # Don't latch sig on failure — next cycle will retry.
        print(f"[team-context] refresh failed: {detail}", flush=True)


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
            # vision-relay push above — failure here MUST NOT bump
            # consecutive_fail or affect the upload-lcu cadence.
            try:
                _maybe_refresh_team_context(state)
            except Exception as e:
                print(f"  [team-context err] {e}", flush=True)
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
    for fn in (_state_push_loop, _auto_features_loop, _cmd_poll_loop):
        threading.Thread(target=fn, daemon=True, name=fn.__name__).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    try: loop()
    except KeyboardInterrupt: sys.exit(0)

"""
web_dashboard.py — Read-only HTTP dashboard for iPad extended display.

Serves a single-page dark-theme dashboard at :8888 designed for an iPad
mirrored to Game-PC via Duet (1180x820 logical, retina). Polls coaching
artifact JSON files at 500ms cadence — same as the tkinter overlays.

Architecture:
- Daemon thread; embedded in RC main process
- Read-only: scrapes data/*.json + ops/runtime/health.json
- No auth (LAN-only)
- Mode-adaptive: routes data based on health.json.mode
"""
import json
import logging
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_log = logging.getLogger("rc.web_dashboard")

PORT = 8888
HOST = "0.0.0.0"

# AUDIT (2026-04-22): vision bearer token routed through core.vision_token
# for rotation support (env / config file / legacy default).
try:
    from core.vision_token import get_vision_token as _get_vision_token
    _VISION_TOKEN = _get_vision_token()
except ImportError:
    _VISION_TOKEN = "8e8f131e212b329438218eca27372dde"

_APP_DIR: Path = Path(__file__).parent

# 2026-05-01 (slice 2B): pure-builder helpers + their shared
# read-only sqlite cache live under `dashboard/`. We re-bind them
# to the original underscored names so route handlers and module-
# level callers (`_diagnostics_cached`, `_build_state`) keep working
# without churn.
from dashboard._context import (  # noqa: E402
    DB_CONN_LOCAL as _DB_CONN_LOCAL,
    read_json as _read_json,
    ro_conn as _ro_conn,
)
from dashboard.builders import (  # noqa: E402
    SESSION_GAP_S,
    _agg_session,
    _build_diagnostics,
    _group_sessions,
    _home_last_build,
    _home_streaks,
    _home_tonight_pick,
    _home_trends_14d,
    _load_match_rows,
    _ts_to_epoch,
)

# 2026-05-01 (slice 2C): static-asset support helpers + the
# legacy_index/manifest/icon byte loaders moved into dashboard/_static.py.
# Re-bind under the original underscored names for any in-process callers.
from dashboard._static import (  # noqa: E402
    compute_asset_hash as _compute_asset_hash,
    icon_svg_bytes as _icon_svg_bytes,
    inject_asset_hash as _inject_asset_hash,
    legacy_index_html as _legacy_index_html,
    manifest_bytes as _manifest_bytes,
    resolve_safe_icon as _resolve_safe_icon,
)
from dashboard import _dispatch  # noqa: E402

# ── Haiku-backed build preview for champions not in CHAMPION_BUILDS ────
# Cached by (champion, frozenset(enemies), role, mode) for 10 minutes.
_PREVIEW_BUILD_CACHE: dict = {}
_PREVIEW_BUILD_TTL = 600   # seconds


def _champ_select_brief_via_coach(champ: str, enemies: list, allies: list,
                                   role: str, mode: str) -> dict:
    """Ask Haiku for a unified champ-select brief: build path + runes + ally
    notes. One API call per unique context. Returns dict with build, runes,
    ally_notes. Cached aggressively."""
    key = (champ, frozenset(enemies), frozenset(allies), role, mode)
    now = time.time()
    cached = _PREVIEW_BUILD_CACHE.get(key)
    if cached and (now - cached["ts"]) < _PREVIEW_BUILD_TTL:
        return cached["brief"]
    empty = {"build": [], "runes": {}, "ally_notes": ""}
    try:
        key_path = Path(_APP_DIR) / "API-Key-Claude.txt"
        api_key = key_path.read_text(encoding="utf-8").strip() if key_path.exists() else ""
        if not api_key.startswith("sk-ant-"):
            return empty
        import anthropic as _a
        client = _a.Anthropic(api_key=api_key)
        aram_note = ""
        if mode.upper() in ("ARAM", "KIWI"):
            aram_note = (
                "This is ARAM — no lane phase, single mid lane, can't recall to "
                "base. Prioritize items that complete fast, sustain (BT/Shieldbow "
                "for squishy carries, Spirit Visage for AP bruisers). Skip Teleport. "
                "Prefer one early tank/sustain item over pure damage for mid-game "
                "fights. Item path should reflect the constant-combat pacing."
            )
        prompt = (
            f"You are a League champ-select advisor. Return STRICT JSON only.\n\n"
            f"CHAMPION: {champ}\n"
            f"MODE: {mode}\n"
            f"ROLE: {role or 'default'}\n"
            f"ENEMIES: {', '.join(enemies) if enemies else '(unknown)'}\n"
            f"ALLIES: {', '.join(allies) if allies else '(unknown)'}\n"
            f"{aram_note}\n\n"
            f"Output JSON with this exact shape (no markdown, no commentary):\n"
            f'{{\n'
            f'  "build": ["item1", ..., "item7"],\n'
            f'  "runes": {{\n'
            f'    "keystone": "Keystone name",\n'
            f'    "primary_tree": "Precision|Domination|Sorcery|Resolve|Inspiration",\n'
            f'    "secondary_tree": "same set, different from primary",\n'
            f'    "shards": ["Adaptive|Attack Speed|Ability Haste",\n'
            f'               "Adaptive|Armor|Magic Resist|Move Speed|Health Scaling",\n'
            f'               "Armor|Magic Resist|Health|Tenacity and Slow Resist"]\n'
            f'  }},\n'
            f'  "ally_notes": "ONE sentence: who on my team is the main carry/engage and '
            f'what my priority is in teamfights."\n'
            f'}}\n\n'
            f"Rules:\n"
            f"- 'build' = 7 entries in purchase order (6 legendaries + boots slotted realistically).\n"
            f"- Item names must match League in-game spelling exactly.\n"
            f"- Avoid redundant items (e.g. no Lord Dominik's AND Mortal Reminder).\n"
            f"- Consider enemy threats for item choices (armor/MR/heal/burst).\n"
            f"- For runes, return the keystone + trees + 3 shards the champ actually runs.\n"
            f"- 'ally_notes' = empty string if ALLIES is unknown."
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # Strip any stray code fences
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            data = json.loads(text)
        except Exception:
            # Best-effort salvage: find first { ... last }
            a, b = text.find("{"), text.rfind("}")
            if a != -1 and b > a:
                try: data = json.loads(text[a:b+1])
                except Exception: data = {}
            else:
                data = {}
        brief = {
            "build":      data.get("build") or [],
            "runes":      data.get("runes") or {},
            "ally_notes": (data.get("ally_notes") or "")[:300],
        }
        _PREVIEW_BUILD_CACHE[key] = {"ts": now, "brief": brief}
        if len(_PREVIEW_BUILD_CACHE) > 200:
            oldest = sorted(_PREVIEW_BUILD_CACHE.items(), key=lambda x: x[1]["ts"])[:100]
            for k, _ in oldest:
                _PREVIEW_BUILD_CACHE.pop(k, None)
        return brief
    except Exception as exc:
        _log.warning("_champ_select_brief_via_coach(%s): %s", champ, exc)
        return empty

# ── Cross-Claude bridge ─────────────────────────────────────────────────
# Lightweight in-memory message log so Legion Claude and Game-PC Claude can
# leave notes for each other. Read via GET /api/bridge?since=<ts>; post via
# POST /api/bridge {source, summary, kind?, id?, target?, body?, in_reply_to?}.
# Last 100 messages retained.
#
# Schema (2026-04-24): the original {source, summary} form is preserved as
# `kind: "note"` (default) for back-compat with existing Stop/UserPromptSubmit
# hooks. Additional kinds:
#   kind: "task"   — a job dispatched to the other side. Carries `id` (uuid),
#                    `target` ("legion" | "gamepc"), and `body` (free-form
#                    JSON the receiver knows how to execute, typically
#                    {prompt, command, timeout_s, context}).
#   kind: "result" — a response to a task. Same fields, plus
#                    `in_reply_to: <task-id>` so the originator can pair it.
# Server doesn't interpret task/result content — that's the Claude on the
# other side. It just stores + filters by kind/target so the polling
# script can ask "give me pending tasks targeted at me".
import collections as _collections
_bridge_lock = threading.Lock()
_bridge_log: _collections.deque = _collections.deque(maxlen=100)
# 2026-04-25: persist bridge entries to JSONL so RC restart doesn't wipe
# the cross-Claude conversation. Hydrated at module import time below.
_BRIDGE_LOG_PATH = Path(__file__).resolve().parent / "ops" / "runtime" / "bridge_log.jsonl"
_BRIDGE_LOG_DISK_MAX = 1000  # rotate JSONL when it exceeds this many entries


def _bridge_hydrate_from_disk() -> None:
    """Replay the most recent up-to-100 entries from the JSONL backup
    into the in-memory deque. Called once at import. Resilient to a
    truncated or partially-written tail line."""
    if not _BRIDGE_LOG_PATH.exists():
        return
    try:
        lines = _BRIDGE_LOG_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    # Re-rotate on disk if too long — trim to last 1000.
    if len(lines) > _BRIDGE_LOG_DISK_MAX:
        try:
            tmp = _BRIDGE_LOG_PATH.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(lines[-_BRIDGE_LOG_DISK_MAX:]) + "\n",
                           encoding="utf-8")
            tmp.replace(_BRIDGE_LOG_PATH)
            lines = lines[-_BRIDGE_LOG_DISK_MAX:]
        except OSError:
            pass
    for line in lines[-100:]:
        try:
            entry = json.loads(line)
            if isinstance(entry, dict) and "ts" in entry and "summary" in entry:
                _bridge_log.append(entry)
        except Exception:
            pass  # tolerate a torn final write


# AUDIT 2026-04-28 (deferred-low-value): every Nth append, check the
# JSONL size and trim if it has crept past _BRIDGE_LOG_DISK_MAX. The
# original rotation only ran at startup; between RC restarts the file
# could grow unbounded.
_BRIDGE_ROTATE_INTERVAL = 100
_bridge_writes_since_rotate = 0


def _bridge_maybe_rotate(force: bool = False) -> None:
    """Trim bridge_log.jsonl to the last _BRIDGE_LOG_DISK_MAX lines if it
    has grown past that. Called periodically from _bridge_post; safe to
    call from any thread (caller should already hold _bridge_lock or
    accept the rare two-rotates-collide case as harmless)."""
    try:
        if not _BRIDGE_LOG_PATH.exists():
            return
        # Cheap line count via a single read. The file is JSONL bounded
        # at ~1 MB at the trim point — affordable.
        text = _BRIDGE_LOG_PATH.read_text(encoding="utf-8")
        lines = text.splitlines()
        if len(lines) <= _BRIDGE_LOG_DISK_MAX and not force:
            return
        keep = lines[-_BRIDGE_LOG_DISK_MAX:]
        tmp = _BRIDGE_LOG_PATH.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
        tmp.replace(_BRIDGE_LOG_PATH)
        _log.info("bridge log rotated: %d → %d lines",
                  len(lines), len(keep))
    except OSError as exc:
        _log.debug("bridge rotate failed: %s", exc)


def _bridge_post(source: str, summary: str, *,
                 kind: str = "note", entry_id: str | None = None,
                 target: str | None = None,
                 body: dict | None = None,
                 in_reply_to: str | None = None) -> dict:
    global _bridge_writes_since_rotate
    entry = {
        "ts":      time.time(),
        "source":  (source or "unknown")[:40],
        "summary": (summary or "")[:2000],
        "kind":    (kind or "note")[:20],
    }
    if entry_id:    entry["id"]          = str(entry_id)[:80]
    if target:      entry["target"]      = str(target)[:40]
    if body is not None: entry["body"]   = body
    if in_reply_to: entry["in_reply_to"] = str(in_reply_to)[:80]
    with _bridge_lock:
        _bridge_log.append(entry)
        try:
            _BRIDGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_BRIDGE_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            _log.debug("bridge JSONL append failed: %s", exc)
        _bridge_writes_since_rotate += 1
        if _bridge_writes_since_rotate >= _BRIDGE_ROTATE_INTERVAL:
            _bridge_writes_since_rotate = 0
            _bridge_maybe_rotate()
    return entry


_bridge_hydrate_from_disk()


def _bridge_since(since_ts: float, limit: int = 20, *,
                  kind: str | None = None,
                  target: str | None = None) -> list:
    with _bridge_lock:
        items = [e for e in _bridge_log if e["ts"] > since_ts]
    if kind:
        items = [e for e in items if e.get("kind", "note") == kind]
    if target:
        items = [e for e in items if e.get("target") == target]
    return items[-limit:]




_MODE_TO_FILE = {
    "aram":  "data/aram_coaching_data.json",
    "arena": "data/arena_coaching_data.json",
    "brawl": "data/brawl_coaching_data.json",
    "tft":   "data/tft_coaching_data.json",
    # SR + client share the root coaching_data.json
    "game":  "coaching_data.json",
    "client": "coaching_data.json",
    "sr":    "coaching_data.json",
}


# 30 s TTL cache for /api/diagnostics — see handler comment.
_DIAG_CACHE: dict = {"payload": b"", "expires": 0.0}
_DIAG_TTL_S = 30.0
_DIAG_LOCK = threading.Lock()


def _diagnostics_cached() -> bytes:
    """Cached encoder for /api/diagnostics. Single-flight: while one
    thread is rebuilding, others wait briefly for the result rather
    than each running their own ~2 s rebuild."""
    now = time.time()
    cur = _DIAG_CACHE
    if cur.get("payload") and now < cur.get("expires", 0):
        return cur["payload"]
    with _DIAG_LOCK:
        # Re-check inside the lock (another thread may have rebuilt).
        cur = _DIAG_CACHE
        if cur.get("payload") and time.time() < cur.get("expires", 0):
            return cur["payload"]
        payload = json.dumps(_build_diagnostics()).encode("utf-8")
        _DIAG_CACHE["payload"] = payload
        _DIAG_CACHE["expires"] = time.time() + _DIAG_TTL_S
    return payload


def _atomic_write_json(rel: str, data: dict) -> None:
    p = _APP_DIR / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)


def _set_pregame(text: str) -> None:
    """Write user-supplied text into root coaching_data.json.pregame field.
    Coach reads this on next poll cycle. Atomic write to avoid mid-read.
    Holds the shared coaching_data_lock so a coach R-M-W in another thread
    can't clobber this update (NOTE-003 fix)."""
    from core.coaching_data_lock import coaching_data_lock
    with coaching_data_lock():
        data = _read_json("coaching_data.json")
        data["pregame"] = text
        _atomic_write_json("coaching_data.json", data)


def _force_vision_scan() -> None:
    """Trigger BaseCoach._vision_loop forced scan (matches Ctrl+Tab hotkey)."""
    import time as _t
    _atomic_write_json("data/force_scan.json", {"force": _t.time()})


def _lcu_summary() -> dict:
    """Read latest LCU snapshot pushed by gamepc_lcu_agent.py.
    Returns {} if relay isn't running or last push is stale (>5s)."""
    try:
        import urllib.request as _ur, time as _t
        req = _ur.Request("http://127.0.0.1:8889/latest-lcu",
                          headers={"X-RC-Token": _VISION_TOKEN})
        with _ur.urlopen(req, timeout=1) as r:
            wrap = json.loads(r.read())
        if "error" in wrap:
            return {}
        if (_t.time() - wrap.get("ts", 0)) > 5:
            return {}
        return wrap.get("data", {}) or {}
    except Exception:
        return {}


def _liveclient_summary() -> dict:
    """Pull a few derived fields from the latest Live Client snapshot
    cached on the vision server. Used to fill dashboard placeholders that
    aren't in coach output (game_time, kda, hp/mana, level, gold, cs).
    Also computes the SR build path + owned-items list for the icon
    display."""
    out: dict = {}
    try:
        import urllib.request as _ur, time as _t
        req = _ur.Request(
            "http://127.0.0.1:8889/latest-liveclient",
            headers={"X-RC-Token": _VISION_TOKEN},
        )
        with _ur.urlopen(req, timeout=1) as r:
            wrap = json.loads(r.read())
        if "error" in wrap:
            return {}
        if (_t.time() - wrap.get("ts", 0)) > 5:
            return {}
        d = wrap.get("data", {})
        ap = d.get("activePlayer") or {}
        gd = d.get("gameData") or {}
        cs = ap.get("championStats") or {}
        me_name = ap.get("summonerName", "")
        me_pl = next(
            (p for p in (d.get("allPlayers") or [])
             if p.get("summonerName") == me_name),
            None,
        )
        gt = gd.get("gameTime", 0)
        out["game_time_s"] = int(gt)
        mm, ss = divmod(int(gt), 60)
        out["game_time"] = f"{mm}:{ss:02d}"
        out["level"] = ap.get("level")
        out["gold"]  = int(ap.get("currentGold", 0))
        out["hp"]    = int(cs.get("currentHealth", 0))
        out["hp_max"]   = int(cs.get("maxHealth", 0))
        out["mana"]  = int(cs.get("resourceValue", 0))
        out["mana_max"] = int(cs.get("resourceMax", 0))
        owned_items: list = []
        enemy_team: list = []
        if me_pl:
            s = me_pl.get("scores") or {}
            out["kda"] = f'{s.get("kills",0)}/{s.get("deaths",0)}/{s.get("assists",0)}'
            out["cs"]  = s.get("creepScore", 0)
            out["champion"] = me_pl.get("championName")
            owned_items = [it.get("displayName", "") for it in (me_pl.get("items") or [])]
            my_team = me_pl.get("team")
            enemy_team = [p.get("championName", "") for p in (d.get("allPlayers") or [])
                          if p.get("team") and p.get("team") != my_team]
        out["game_mode"] = gd.get("gameMode")
        out["owned_items"] = owned_items
        out["enemy_team"]  = enemy_team

        # Build path + boots phase via item_advisor (works for SR/Practice;
        # ARAM/Arena/Brawl have their own flows but this fallback is OK).
        try:
            import sys as _sys
            from pathlib import Path as _P
            _sys.path.insert(0, str(_P(__file__).parent))
            from item_advisor import (
                resolve_build, boots_phase, endgame_boots_swap_target,
                is_redundant,
            )
            champ = out.get("champion", "")
            if champ:
                build = resolve_build(champ, enemy_team, owned_items)
                norm_owned = {x.lower().strip() for x in owned_items}
                build_lc = {x.lower().strip() for x in build}
                items_view = []
                # 1. Owned items first (green) — skip trinket since it never sells.
                for it in owned_items:
                    if not it: continue
                    if it.lower().strip() in {"farsight alteration", "stealth ward",
                                              "oracle lens", "scrying orb",
                                              "warding totem"}:
                        continue
                    items_view.append({"name": it, "owned": True, "next": False})
                # 2. Suggested next items (not owned). Skip exclusion-redundant ones.
                for it in build:
                    if it.lower().strip() in norm_owned:
                        continue
                    redundant, _why = is_redundant(it, owned_items)
                    if redundant:
                        continue
                    items_view.append({"name": it, "owned": False, "next": True})
                out["sr_items"] = items_view[:9]  # cap at 9 for grid sanity
                out["sr_boots_phase"] = boots_phase(
                    out.get("level") or 1,
                    out.get("gold") or 0,
                    sum(1 for x in owned_items if x),
                    owned_items,
                )
                if out["sr_boots_phase"] in ("consider_sell", "sell_for_quest"):
                    swap = endgame_boots_swap_target(champ, enemy_team, owned_items)
                    if swap and swap[0]:
                        out["sr_boots_swap"] = {"item": swap[0], "reason": swap[1]}
        except Exception:
            pass
    except Exception:
        return {}
    return out


def _build_state() -> dict:
    health = _read_json("ops/runtime/health.json")
    # mode resolution: prefer specific mode flag from health, fall back to .mode
    mode_key = "client"
    if health.get("aram_mode"):  mode_key = "aram"
    elif health.get("arena_mode"): mode_key = "arena"
    elif health.get("tft_mode"):   mode_key = "tft"
    elif health.get("has_game"):   mode_key = "game"
    else:                          mode_key = health.get("mode", "client")

    coach_file = _MODE_TO_FILE.get(mode_key, "coaching_data.json")
    coach = _read_json(coach_file)

    # Overlay live API fields onto coach data so the dashboard placeholders
    # (game_time, kda, level, gold, hp, mana, cs) populate immediately.
    # Coach values win when present (e.g. coach computes win_pct from comp).
    lc = _liveclient_summary()
    if lc:
        for k, v in lc.items():
            if coach.get(k) in (None, "", 0):
                coach[k] = v

    return {
        "mode_key": mode_key,
        "coach_source": coach_file,
        "health": {
            "alive":          health.get("alive"),
            "pid":            health.get("pid"),
            "mode":           health.get("mode"),
            "has_game":       health.get("has_game"),
            "ui_pulse_age_s": health.get("ui_pulse_age_s"),
            "game_poll_age_s": health.get("game_poll_worker_age_s"),
        },
        "coach": coach,
        "liveclient": lc,
        "lcu": _lcu_summary(),
    }


_SIM_STATES_PATH = Path(__file__).resolve().parent / "data" / "sim_states.json"
_SIM_STATES_CACHE: dict | None = None


def _sim_states() -> dict:
    global _SIM_STATES_CACHE
    if _SIM_STATES_CACHE is None:
        _SIM_STATES_CACHE = json.loads(_SIM_STATES_PATH.read_text(encoding="utf-8"))
    return _SIM_STATES_CACHE




# Paths that only the agents supervisor (:8890) implements. :8888 proxies
# GETs for these so the new dashboard, when accessed via :8888, gets full
# side-panel data without having to know about port 8890.
_SUPERVISOR_PROXY_PATHS = (
    "/api/activity",
    "/api/adaptation",
    "/api/advisories",
    "/api/day-of-week",
    "/api/digest",
    "/api/duration",
    "/api/env",
    "/api/insight-card",
    "/api/locked-champion",
    "/api/minimap-crop",
    "/api/queue",
    "/api/session",
    "/api/session-games",
    "/api/sim",           # matches /api/sim, /api/sim/<name>, /api/sim/_manifest
    "/api/task",          # /api/task/<id>
    "/api/time-of-day",
    "/api/trending",
)
_SUPERVISOR_ORIGIN = "http://127.0.0.1:8890"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        _log.debug("HTTP " + fmt, *a)

    def _proxy_to_supervisor(self):
        """Forward the current GET to 127.0.0.1:8890 and stream the
        response back. Body is read in full first so we can set a proper
        Content-Length; requests here return <100KB (minimap PNG is the
        biggest) so memory cost is negligible."""
        import urllib.request as _ur
        import urllib.error as _ue
        url = _SUPERVISOR_ORIGIN + self.path
        try:
            req = _ur.Request(url, method=self.command)
            # Pass through conditional headers the dashboard might send.
            for h in ("If-None-Match", "If-Modified-Since", "Accept"):
                v = self.headers.get(h)
                if v:
                    req.add_header(h, v)
            with _ur.urlopen(req, timeout=4) as r:
                body = r.read()
                ctype = r.headers.get("Content-Type", "application/octet-stream")
                self._send(r.status, body, ctype)
        except _ue.HTTPError as e:
            # Forward the non-2xx response — 404 from supervisor should
            # still look like 404 to the dashboard, not 500 here.
            try:
                body = e.read() or b""
            except Exception:
                body = b""
            ctype = e.headers.get("Content-Type", "application/json") if e.headers else "application/json"
            self._send(e.code, body, ctype)
        except Exception as exc:
            _log.debug("proxy %s: %s", self.path, exc)
            self._send(502, b'{"error":"supervisor_unreachable"}', "application/json")

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # AUDIT 2026-04-29: Strict-Transport-Security so any browser that
        # touches the dashboard once over HTTPS never falls back to plain
        # HTTP for this origin again — eliminates the original Game-PC
        # "http://… not connecting" symptom permanently. 1-year max-age is
        # standard. We don't include preload / includeSubDomains because
        # this is LAN-only and we don't own the rest of the IP space.
        # Only set when the connection itself is TLS — when wrap_socket
        # is in play, the underlying request socket has an .cipher() attr.
        try:
            sock = self.connection
            if hasattr(sock, "cipher") and callable(sock.cipher):
                self.send_header("Strict-Transport-Security", "max-age=31536000")
        except Exception:
            pass
        self.end_headers()
        try: self.wfile.write(body)
        except Exception: pass

    def do_GET(self):
        # Slice 2C (2026-05-01): all GET routes live in dashboard/routes_*.
        # Anything that doesn't match a registered route either falls
        # through to the agents-supervisor proxy (:8890) for routes that
        # only exist there, or returns 404.
        if _dispatch.dispatch_get(self):
            return
        if any(self.path == p or self.path.startswith(p + "?") or self.path.startswith(p + "/")
               for p in _SUPERVISOR_PROXY_PATHS):
            # 2026-04-23: forward routes that only exist on the agents
            # supervisor (:8890) through :8888 so the new dashboard's
            # side panels (adaptation, activity, env, minimap-crop,
            # locked-champion, etc.) populate when accessed via 8888.
            self._proxy_to_supervisor()
        else:
            self._send(404, b"not found", "text/plain")

    def _csrf_ok(self) -> bool:
        """AUDIT 2026-04-28 (deferred-low-value): same-origin guard for
        POST endpoints. RC is LAN-only so cross-site CSRF is mitigated by
        threat model, but a misbehaving / compromised tab on Legion could
        still cross-origin-POST into 8888. Browsers send Origin (and
        Referer) on cross-origin POSTs; non-browser clients (curl, our
        own scripts) typically send neither and are allowed.

        Rule: if Origin or Referer is present, its hostname must match
        the request's Host header — OR the origin must itself be a local
        loopback address (127.0.0.1 / localhost) coming from a script on
        the same machine. Absent both headers → allow (script caller).
        """
        try:
            origin  = self.headers.get("Origin", "") or ""
            referer = self.headers.get("Referer", "") or ""
            if not origin and not referer:
                return True
            host = (self.headers.get("Host", "") or "").strip().lower()
            if not host:
                return False
            host_h, _, _ = host.partition(":")
            from urllib.parse import urlparse
            local_aliases = {"127.0.0.1", "localhost", "::1"}
            for src in (origin, referer):
                if not src:
                    continue
                # "null" Origin is what some sandboxed iframes / file://
                # contexts send. Treat as cross-origin.
                if src == "null":
                    return False
                p = urlparse(src)
                src_hp = (p.hostname or "").lower()
                if not src_hp:
                    return False
                # Same hostname is fine (port may differ — e.g. dashboard
                # opened via localhost vs LAN IP from same machine).
                if src_hp == host_h:
                    continue
                # Origin from local loopback when request host is the LAN
                # bind is also fine — script callers, dev probes.
                if src_hp in local_aliases and host_h not in local_aliases:
                    continue
                if host_h in local_aliases and src_hp in local_aliases:
                    continue
                # Anything else: reject.
                return False
            return True
        except Exception:
            # Don't block POSTs on parse errors — fail open with a log.
            _log.debug("csrf_ok parse failed; allowing")
            return True

    def do_POST(self):
        # 2026-04-27 audit: cap POST body at 1 MiB. RC is LAN-only and the
        # legitimate inputs (chat text, /api/bridge messages) are tiny —
        # an unbounded read on Content-Length: 999999999 would let a LAN
        # attacker (or a misbehaving tab) allocate a multi-GB buffer per
        # request. Also: don't echo the exception message back to the
        # client, since urllib/json error strings can leak file paths or
        # unrelated headers.
        # AUDIT 2026-04-28 (deferred-low-value): same-origin CSRF guard.
        # Browser-driven cross-origin POSTs (Origin/Referer mismatch) are
        # rejected with 403; script callers without those headers pass.
        if not self._csrf_ok():
            _log.warning("do_POST CSRF reject path=%s origin=%r referer=%r host=%r",
                         self.path,
                         self.headers.get("Origin"),
                         self.headers.get("Referer"),
                         self.headers.get("Host"))
            self._send(403, b'{"error":"cross_origin"}', "application/json")
            return
        _MAX_POST_BYTES = 1 << 20
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > _MAX_POST_BYTES:
                self._send(413, b'{"error":"payload_too_large"}', "application/json")
                return
            body = self.rfile.read(n) if n else b""
            payload = json.loads(body.decode("utf-8", errors="replace")) if body else {}
        except Exception as exc:
            _log.debug("do_POST bad_body: %s", exc)
            self._send(400, b'{"error":"bad_body"}', "application/json")
            return

        # Slice 2C (2026-05-01): dispatcher tries each migrated POST
        # route first; falls through to the legacy elif chain below.
        if _dispatch.dispatch_post(self, payload):
            return

        if self.path == "/api/analyze":
            # Dashboard's "Analyze Now" button — forward POST to the
            # supervisor at :8890. Was silently 404ing because the GET-only
            # supervisor proxy didn't list /api/analyze and there was no
            # POST forwarder. Synchronous: returns supervisor's response.
            try:
                import urllib.request as _ur
                req = _ur.Request(
                    "http://127.0.0.1:8890/api/analyze",
                    data=json.dumps(payload or {}).encode(),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with _ur.urlopen(req, timeout=30) as r:
                    body = r.read()
                    ctype = r.headers.get("Content-Type", "application/json")
                self._send(200, body, ctype)
            except Exception as exc:
                _log.warning("api/analyze: %s", exc)
                self._send(500, json.dumps({"error": str(exc)}).encode(),
                           "application/json")
        elif self.path == "/api/experimental/get":
            # Body: {champion, mode}. Returns current experimental build
            # (auto-generates if none exists yet). Caller is expected to
            # then hit /api/loadout/apply with variant=experimental.
            try:
                from coaches import experimental_builder as eb
                champ = (payload.get("champion") or "").strip()
                if not champ:
                    self._send(400, b'{"error":"champion required"}', "application/json"); return
                cur = eb.get_current(champ)
                if not cur:
                    api_key = ""
                    try:
                        api_key = (Path(__file__).parent / "API-Key-Claude.txt").read_text(encoding="utf-8").strip()
                    except Exception: pass
                    cur = eb.generate(champ, api_key)
                self._send(200, json.dumps({
                    "ok": bool(cur), "champion": champ,
                    "current": cur,
                    "history": eb.get_history(champ),
                }).encode(), "application/json")
            except Exception as exc:
                _log.warning("api/experimental/get: %s", exc)
                self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
        elif self.path == "/api/experimental/adapt":
            # Manual trigger: regenerate the next iteration via Haiku,
            # informed by full history.
            try:
                from coaches import experimental_builder as eb
                champ = (payload.get("champion") or "").strip()
                if not champ:
                    self._send(400, b'{"error":"champion required"}', "application/json"); return
                api_key = ""
                try:
                    api_key = (Path(__file__).parent / "API-Key-Claude.txt").read_text(encoding="utf-8").strip()
                except Exception: pass
                new = eb.adapt(champ, api_key)
                self._send(200, json.dumps({
                    "ok": bool(new), "champion": champ, "current": new,
                }).encode(), "application/json")
            except Exception as exc:
                _log.warning("api/experimental/adapt: %s", exc)
                self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
        elif self.path == "/api/experimental/mark":
            # Body: {champion, mode}. Drop a marker file so postgame
            # performance_tracker can attribute the result to this iter.
            try:
                from coaches import experimental_builder as eb
                champ = (payload.get("champion") or "").strip()
                mode = (payload.get("mode") or "aram").strip()
                if not champ:
                    self._send(400, b'{"error":"champion required"}', "application/json"); return
                eb.mark_active(champ, mode)
                self._send(200, b'{"ok":true}', "application/json")
            except Exception as exc:
                _log.warning("api/experimental/mark: %s", exc)
                self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
        elif self.path == "/api/aram-analyze":
            # Body: {my_champion, my_team[], their_team[], bench[],
            #        current_variant, mode}
            # Pulls variant list for current champion+mode from loadouts,
            # builds compact summaries, calls aram_team_analyzer.
            try:
                from coaches import aram_team_analyzer
                from coaches.loadout_resolver import _load_loadouts, list_variants, _normalize_mode
                my_champ = (payload.get("my_champion") or "").strip()
                if not my_champ:
                    self._send(400, b'{"error":"my_champion required"}', "application/json"); return
                mode = (payload.get("mode") or "aram").strip()
                mode_key = _normalize_mode(mode)
                # Build compact variant summaries for the analyzer prompt.
                # Each: "{keystone}/{primary} → {first 4 items}"
                loadouts = _load_loadouts().get("champions", {}) or {}
                champ_data = loadouts.get(my_champ) or {}
                all_variants = champ_data.get("variants") or {}
                variant_summaries = []
                for vinfo in list_variants(my_champ, mode):
                    vkey = vinfo["key"]
                    v = all_variants.get(vkey) or {}
                    runes = v.get("runes") or {}
                    items = (v.get("items") or [])[:4]
                    summary = (
                        f"{runes.get('keystone','?')}/{runes.get('primary','?')} → "
                        + (", ".join(items) if items else "(no items)")
                    )
                    variant_summaries.append({
                        "key":     vkey,
                        "label":   vinfo.get("label") or vkey,
                        "summary": summary,
                    })
                api_key = ""
                try:
                    from pathlib import Path as _P
                    api_key = (_P(__file__).parent / "API-Key-Claude.txt").read_text(encoding="utf-8").strip()
                except Exception:
                    pass
                state = {
                    "my_champion":     my_champ,
                    "my_team":         payload.get("my_team")    or [],
                    "their_team":      payload.get("their_team") or [],
                    "bench":           payload.get("bench")      or [],
                    "current_variant": payload.get("current_variant") or "",
                    "variants":        variant_summaries,
                }
                result = aram_team_analyzer.analyze(state, api_key)
                self._send(200, json.dumps(result).encode(), "application/json")
            except Exception as exc:
                _log.warning("api/aram-analyze: %s", exc)
                self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
        elif self.path.startswith("/api/loadout/list"):
            # GET-style query in POST body for symmetry: {champion, mode}.
            # Returns [{key, label, is_default}, ...] for variants visible
            # in this mode for this champion.
            try:
                from coaches.loadout_resolver import list_variants, default_variant
                champ = (payload.get("champion") or "").strip()
                mode  = (payload.get("mode")     or "sr").strip()
                if not champ:
                    self._send(400, b'{"error":"champion required"}', "application/json"); return
                vs = list_variants(champ, mode)
                df = default_variant(champ, mode)
                self._send(200, json.dumps({
                    "champion": champ, "mode": mode,
                    "variants": vs, "default": df,
                }).encode(), "application/json")
            except Exception as exc:
                _log.warning("api/loadout/list: %s", exc)
                self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
        elif self.path == "/api/loadout/apply":
            # Body: {champion, variant, mode, push_runes?, push_items?, push_summoners?}.
            # Defaults: push everything that the variant declares.
            # Resolves the variant to LCU command payloads and queues them
            # one-by-one through /api/lcu-cmd. Returns immediately; results
            # come back via the LCU command queue (best-effort).
            try:
                from coaches.loadout_resolver import resolve
                import urllib.request as _ur
                champ   = (payload.get("champion") or "").strip()
                variant = (payload.get("variant")  or "").strip()
                mode    = (payload.get("mode")     or "sr").strip()
                push_runes = payload.get("push_runes",   True)
                push_items = payload.get("push_items",   True)
                push_summ  = payload.get("push_summoners", True)
                if not champ or not variant:
                    self._send(400, b'{"error":"champion+variant required"}', "application/json"); return
                resolved = resolve(champ, variant, mode)
                if not resolved.get("ok"):
                    self._send(404, json.dumps(resolved).encode(), "application/json"); return
                queued = []
                def _enqueue(cmd_obj):
                    if not cmd_obj: return
                    try:
                        req = _ur.Request(
                            "http://127.0.0.1:8889/lcu-cmd",
                            data=json.dumps(cmd_obj).encode(),
                            method="POST",
                            headers={"X-RC-Token": _VISION_TOKEN,
                                     "Content-Type": "application/json"},
                        )
                        with _ur.urlopen(req, timeout=2) as r:
                            r.read()
                        queued.append(cmd_obj.get("cmd"))
                    except Exception as exc:
                        _log.warning("loadout enqueue %s: %s",
                                     cmd_obj.get("cmd"), exc)
                if push_runes: _enqueue(resolved.get("rune_cmd"))
                if push_items: _enqueue(resolved.get("item_cmd"))
                if push_summ:  _enqueue(resolved.get("summ_cmd"))
                # Pull item IDs back out of item_cmd.blocks for UI rendering
                # (frontend needs IDs to load /data/ddragon/<v>/img/item/<id>.png).
                item_ids = []
                if resolved.get("item_cmd"):
                    for blk in resolved["item_cmd"].get("blocks", []):
                        for it in blk.get("items", []):
                            iid = it.get("id")
                            if iid: item_ids.append(str(iid))
                self._send(200, json.dumps({
                    "ok": True,
                    "champion": champ, "variant": variant, "mode": resolved.get("mode"),
                    "label":    resolved.get("label"),
                    "queued":   queued,
                    "raw_items": resolved.get("raw_items", []),
                    "item_ids":  item_ids,
                }).encode(), "application/json")
            except Exception as exc:
                _log.warning("api/loadout/apply: %s", exc)
                self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
        elif self.path == "/api/lcu-cmd":
            # Forward command to vision server's LCU queue.
            # Body: {cmd: "accept_ready"} or {cmd:"set_config", auto_accept:true}
            # Validate at the dashboard edge so a malformed body never
            # reaches the LCU agent on Game-PC.
            _LCU_ALLOWED_CMDS = {
                "accept_ready", "set_config", "bench_swap",
                "set_summoners", "lock_pick", "reroll",
                "apply_runes", "apply_item_set",
                "trade_request", "accept_trade", "decline_trade",
                # Lobby actions (2026-04-26): start/cancel matchmaking
                # from the dashboard's Find Match button + change queue
                # type from the lobby dropdown. LCU restricts these to
                # the lobby leader; the UI gates the controls on
                # lobby.is_leader before sending.
                "start_matchmaking", "cancel_matchmaking",
                "change_queue_type",
            }
            cmd_name = (payload.get("cmd") or "").strip()
            if cmd_name not in _LCU_ALLOWED_CMDS:
                self._send(400,
                    json.dumps({"error": "unknown_lcu_cmd",
                                "cmd": cmd_name,
                                "allowed": sorted(_LCU_ALLOWED_CMDS)}).encode(),
                    "application/json")
                return
            try:
                import urllib.request as _ur
                req = _ur.Request(
                    "http://127.0.0.1:8889/lcu-cmd",
                    data=json.dumps(payload).encode(),
                    method="POST",
                    headers={"X-RC-Token": _VISION_TOKEN,
                             "Content-Type": "application/json"},
                )
                with _ur.urlopen(req, timeout=2) as r:
                    body = r.read()
                self._send(200, body, "application/json")
            except Exception as exc:
                _log.warning("api/lcu-cmd: %s", exc)
                self._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")


class _DualProtocolHTTPServer(ThreadingHTTPServer):
    """Accept BOTH plain HTTP and TLS on the same port (proposal: 2026-04-28
    Game-PC fix). Stdlib wrap_socket() over the listen socket forces every
    accept() into a TLS handshake — a plaintext `http://` request from a
    LAN host then connects, never receives bytes back, and times out.

    This server peeks the first byte per connection:
      * 0x16 (TLS ClientHello)  → wrap in the TLS context, hand off as TLS
      * anything else           → emit an inline 301 to https://<host>:8888,
                                   close, raise OSError so the framework
                                   skips the slot.
    """

    def __init__(self, server_address, handler_class, *, ssl_ctx):
        super().__init__(server_address, handler_class)
        self._ssl_ctx = ssl_ctx

    def get_request(self):
        sock, addr = self.socket.accept()
        try:
            import socket as _socket
            sock.settimeout(5.0)
            first = sock.recv(1, _socket.MSG_PEEK)
        except (OSError, ValueError):
            try: sock.close()
            except OSError: pass
            raise
        if first == b"\x16":
            # TLS ClientHello — wrap and hand off. Wrap can raise on a
            # malformed handshake; that's a normal scanner / probe and
            # should be silently dropped.
            try:
                wrapped = self._ssl_ctx.wrap_socket(sock, server_side=True)
                wrapped.settimeout(None)
                return wrapped, addr
            except OSError as exc:
                try: sock.close()
                except OSError: pass
                raise OSError(f"TLS handshake failed: {exc}")
        # Plain HTTP — answer with a 301 inline + close.
        try:
            self._inline_redirect(sock)
        except OSError:
            pass
        finally:
            try: sock.close()
            except OSError: pass
        # Tell socketserver to skip this slot. It catches OSError quietly.
        raise OSError("plain HTTP redirected to HTTPS")

    def _inline_redirect(self, sock) -> None:
        """Read enough of the request to extract Host + path, send a 301,
        close. Best-effort — scanner/garbage traffic just gets a generic
        redirect to /."""
        sock.settimeout(2.0)
        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 8192:
            try:
                chunk = sock.recv(4096)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            buf += chunk
        path = "/"
        host = "192.168.8.230"
        try:
            head, _, _ = buf.partition(b"\r\n\r\n")
            lines = head.split(b"\r\n")
            if lines:
                req = lines[0].decode("ascii", errors="replace").split(" ")
                if len(req) >= 2 and req[1].startswith("/"):
                    # cap path length to keep the Location header sane
                    path = req[1][:512]
            for h in lines[1:]:
                lo = h.lower()
                if lo.startswith(b"host:"):
                    raw = h.split(b":", 1)[1].decode("ascii", errors="replace").strip()
                    # Strip the existing port; we always redirect to PORT.
                    host = raw.split(":", 1)[0] or host
                    break
        except (UnicodeDecodeError, ValueError):
            pass
        location = f"https://{host}:{PORT}{path}"
        body = (
            b"<!doctype html><meta charset=utf-8>"
            b"<title>RC dashboard \xe2\x86\x92 HTTPS</title>"
            b"<p>RC dashboard requires HTTPS. Open "
            b"<a href=\"" + location.encode("utf-8") + b"\">"
            + location.encode("utf-8") + b"</a>.</p>"
        )
        resp = (
            b"HTTP/1.1 301 Moved Permanently\r\n"
            b"Location: " + location.encode("utf-8") + b"\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
            b"Connection: close\r\n\r\n"
        ) + body
        try:
            sock.sendall(resp)
        except OSError:
            pass


def start_dashboard(app_dir: Path) -> None:
    """Launch the dashboard HTTP(S) server in a daemon thread. Idempotent-ish.
    If ops/tls/rc.pem + rc-key.pem exist (mkcert-issued), serves TLS via
    _DualProtocolHTTPServer (HTTP requests get a 301 to HTTPS on the same
    port); otherwise falls back to plain HTTP."""
    global _APP_DIR
    _APP_DIR = Path(app_dir)

    cert_path = _APP_DIR / "ops" / "tls" / "rc.pem"
    key_path  = _APP_DIR / "ops" / "tls" / "rc-key.pem"
    scheme = "http"
    srv = None
    if cert_path.exists() and key_path.exists():
        try:
            import ssl
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
            srv = _DualProtocolHTTPServer((HOST, PORT), _Handler, ssl_ctx=ctx)
            scheme = "https"
        except Exception as exc:
            _log.warning("TLS setup failed, falling back to HTTP: %s", exc)
            srv = None
    if srv is None:
        try:
            srv = ThreadingHTTPServer((HOST, PORT), _Handler)
        except OSError as exc:
            _log.warning("Dashboard port %d unavailable: %s", PORT, exc)
            return

    t = threading.Thread(target=srv.serve_forever, daemon=True, name="WebDashboard")
    t.start()
    if scheme == "https":
        _log.info("Web dashboard on https://%s:%d/  (HTTP requests on the "
                  "same port 301-redirect)  (iPad: https://192.168.8.230:%d/)",
                  HOST, PORT, PORT)
    else:
        _log.info("Web dashboard on http://%s:%d/  (no TLS cert)", HOST, PORT)

    # Vision tracker: derives fog-of-war state from Live Client position
    # freshness, writes data/vision_state.json. Consumed by the minimap
    # overlay layer and (later) by coach prompt builders.
    try:
        from core.vision_tracker import get_tracker
        get_tracker().start_background()
    except Exception as exc:
        _log.warning("vision_tracker failed to start: %s", exc)

    # Decision detector: surfaces coachable moments (objective contest,
    # etc.) to the dashboard Coach panel + records the player's choice.
    try:
        from core.decision_detector import get_loop
        get_loop().start_background()
    except Exception as exc:
        _log.warning("decision_detector failed to start: %s", exc)

"""ds_matchdb_mcp_server.py - local MCP server exposing the Daemon Slayer
build engine and the match-history database to a local Claude / agent.

Speaks the MCP JSON-RPC protocol over HTTP on port 8861. Localhost-only by
default (127.0.0.1): it proxies the local Daemon Slayer engine on :8860 and
reads the local data/match_history.db - no cross-machine surface, unlike
the legacy cross-machine MCP server (retired with the 1-PC consolidation,
ADR-011) which bound 0.0.0.0 for a cross-host LAN.
Bearer auth is kept anyway (defense in depth + the same token chain so one
RC_MCP_TOKEN covers both RC MCP servers).

Why this server exists
----------------------
The DS engine (:8860) and the match DB are RC-internal infrastructure
reachable today only from inside the running dashboard process. A local
agent doing build research, calibration, or post-game analysis had no
first-class way to ask "rank items for Vayne in this matchup" or "what is
my ARAM grade trend" without re-deriving the call shapes by hand. This
wraps the already-tested core helpers as MCP tools so the agent can.

Tools exposed:
  ds_health()
      Is the Daemon Slayer engine reachable on :8860; returns its /health
      payload (engine_version, patch, champion/item counts) when up.

  ds_rank_items(champion, archetype="", level=11, owned_item_ids=[],
                mode="SR", target_armor=0, target_mr=0, target_max_hp=0,
                target_bonus_hp=0, top=8)
      Rank items for the champion via the right per-archetype scorer
      (carry/bruiser/tank/mage/assassin/enchanter). Blank archetype is
      auto-resolved from the champion (same default the coaches use).
      Returns {ok, scorer, archetype, ranked, fell_back}.

  ds_build_order(champion, archetype="", level=11, owned_item_ids=[],
                 mode="SR", target_armor=0, target_mr=0, target_max_hp=0,
                 target_bonus_hp=0, slots=6)
      Contextual, match-specific ordered build via greedy forward
      selection with the cross-family unique-passive no-double rule
      enforced engine-side. Returns the BuildOrderResult dict.

  ds_archetype_for(champion)
      The merged archetype pick {primary, secondary, source} for a
      champion (operator override else DDragon-tag default).

  match_recent(mode="", limit=20)
      Recent match rows, optionally filtered by mode (SR/ARAM/ARENA/
      BRAWL/TFT).

  match_mode_stats(mode, limit=20)
      Aggregate stats for a mode over recent games (avg K/D, cs/min,
      gold/min, grade distribution).

  match_tft_comps(which="best", min_games=2, limit=10)
      TFT comps ranked best- or worst-first by average placement.

  match_tft_streak(limit=10)
      Recent TFT placement summary (avg place, top4 count/pct, wins).

Run locally:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/ds_matchdb_mcp_server.py
  (or via the boot launcher tools/start_ds_matchdb_mcp.py)

Schedule at logon for persistence:
  schtasks /Create /TN "RC-DS-MatchDB-MCP" /SC ONLOGON /RL HIGHEST /F ^
    /TR "pythonw C:\\Riot Commander\\tools\\start_ds_matchdb_mcp.py"

Configure local Claude Code .mcp.json (or settings.json mcpServers):
  {
    "mcpServers": {
      "ds-matchdb": {
        "type": "http",
        "url": "http://127.0.0.1:8861/mcp",
        "headers": { "Authorization": "Bearer <token-from --show-token>" }
      }
    }
  }
"""
from __future__ import annotations

import argparse
import concurrent.futures
import http.server
import json
import logging
import math
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path
from urllib.request import urlopen

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Tools here import core.* - pin cwd + sys.path before those imports so a
# scheduled-task launch (cwd = C:\Windows\System32) still resolves them
# and any cwd-relative data lookups land in the project root.
os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.archetype_picks import get_archetype_for as _get_archetype_for  # noqa: E402
from core.build_order import plan_build_order as _plan_build_order  # noqa: E402
from core.daemon_slayer_client import (  # noqa: E402
    is_engine_up as _is_engine_up,
    rank_for_primary_archetype as _rank_for_primary_archetype,
)
from core.match_db import MatchDB  # noqa: E402

HOST = "127.0.0.1"
PORT = 8861
PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "ds-matchdb-mcp"
SERVER_VERSION = "0.1.0"

# -- Hung-tool watchdog -----------------------------------------------------
# Every tool handler runs under a bounded timeout enforced by a single
# shared thread pool (NOT one thread per call - a bounded executor so a
# burst of calls cannot explode the thread count). On timeout the caller
# gets a structured MCP error result instead of a hung connection; the
# server stays responsive to the next request. The timed-out future is
# abandoned (we never read its result), so a slow handler cannot corrupt
# the response of a later call.
#
# Default is deliberately generous (a backstop, not a latency throttle):
# the underlying core helpers (engine HTTP, sqlite) already carry their
# own short timeouts, so this only trips on a genuine hang.
DISPATCH_TIMEOUT_S = float(os.environ.get("RC_MCP_DISPATCH_TIMEOUT_S", "45"))
# Per-tool overrides for handlers that legitimately run long and govern
# themselves with a tighter internal timeout. The watchdog must sit
# ABOVE that internal ceiling so it never preempts the tool's own
# bound (no double-wrapping / no shortening). ds-matchdb tools are all
# fast, so this is empty here; the legacy cross-machine MCP server used it for
# run_powershell (subprocess timeout, own 600 s ceiling).
TOOL_TIMEOUT_OVERRIDES: dict[str, float] = {}
# Bounded worker pool. max_workers caps concurrent in-flight handlers;
# the ThreadingHTTPServer already serialises per-connection so this is a
# safety ceiling, not the primary concurrency model.
_DISPATCH_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=8, thread_name_prefix="mcp-dispatch")

DS_HEALTH_URL = "http://127.0.0.1:8860/health"
_MATCH_DB_PATH = _PROJECT_ROOT / "data" / "match_history.db"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ds-matchdb-mcp")

_START = time.time()


# -- Safe JSON serialization ------------------------------------------------
# DS-scorer output is the payload of ds_rank_items / ds_build_order. A scorer
# can return a non-finite float (NaN / inf - a 0/0 ratio, an unbounded score),
# and json.dumps defaults to allow_nan=True, which emits the BARE tokens
# ``NaN`` / ``Infinity``. Those are invalid JSON for a strict JSON-RPC client
# and for JS JSON.parse. The dashboard DS routes already guard this with
# ``math.isfinite(v) else None``; this is the MCP server's equivalent: try the
# strict path, and only if it trips rewrite non-finite floats to None and
# re-dump. Finite payloads pay nothing (the strict dump succeeds first try).
def _finite_only(obj):
    """Recursively replace non-finite floats with None (containers rebuilt,
    scalars passed through). Only called on the cold path after a strict dump
    has already rejected the payload."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _finite_only(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_finite_only(v) for v in obj]
    return obj


def _json_dumps_safe(obj, **kwargs) -> str:
    """json.dumps that never emits a bare NaN / Infinity token.

    Forces allow_nan=False; on the resulting ValueError (a non-finite float is
    present) it sanitizes those floats to None and re-dumps. ``default`` stays
    the caller's (e.g. ``default=str``) for non-JSON objects."""
    kwargs.pop("allow_nan", None)
    try:
        return json.dumps(obj, allow_nan=False, **kwargs)
    except ValueError:
        return json.dumps(_finite_only(obj), allow_nan=False, **kwargs)


# -- Auth token resolution (mirrors the legacy MCP server / the screen agent) ----
def _resolve_token() -> str:
    env = os.environ.get("RC_MCP_TOKEN")
    if env:
        return env.strip()
    here = Path(__file__).resolve().parent
    for name in ("mcp_token.txt", "vision_token.txt"):
        p = here / name
        if p.exists():
            try:
                v = p.read_text(encoding="utf-8").splitlines()[0].strip()
                if v:
                    return v
            except OSError:
                pass
    # Lane 8 cycle 14: this chain ended in the constant retired by the
    # 2026-04-28 audit and never consulted the canonical source at
    # config/vision_token.txt - the exact divergent-lookup-chain shape that
    # caused the item-242 and item-243 silent-401 outages. Fall through to the
    # canonical resolver instead of a dead literal.
    from core.vision_token import get_vision_token

    return get_vision_token()


AUTH_TOKEN = _resolve_token()


# -- Lazy MatchDB singleton -------------------------------------------------
# MatchDB.__init__ opens a sqlite connection + runs schema, so build it on
# first match-tool use rather than at import time. WAL + per-thread conns
# (see core/match_db.py) make a process-wide instance safe across the
# ThreadingHTTPServer worker threads.
_match_db: MatchDB | None = None
_match_db_lock = threading.Lock()


def _get_match_db() -> MatchDB | None:
    """Return the shared MatchDB, or None if the db file is absent.

    Absent file is a soft error (returned to the caller as a dict), not an
    exception - the match DB is operator-data infrastructure that may not
    exist on a fresh checkout.
    """
    global _match_db
    if not _MATCH_DB_PATH.exists():
        return None
    if _match_db is None:
        with _match_db_lock:
            if _match_db is None:
                _match_db = MatchDB(_MATCH_DB_PATH)
    return _match_db


def _resolve_archetype(champion: str, archetype: str) -> str:
    """Blank archetype -> the champion's resolved primary (the same default
    the coaches use via dispatch_for_coach). Never raises."""
    a = (archetype or "").strip().lower()
    if a:
        return a
    try:
        return (_get_archetype_for(str(champion)).get("primary")
                or "carry").strip().lower() or "carry"
    except Exception:  # noqa: BLE001
        return "carry"


# -- Tool implementations ---------------------------------------------------
def tool_ds_health() -> dict:
    up = bool(_is_engine_up(timeout=1.0))
    out: dict = {"engine_up": up, "url": DS_HEALTH_URL}
    if not up:
        out["error"] = "daemon slayer engine unreachable on :8860"
        return out
    try:
        with urlopen(DS_HEALTH_URL, timeout=1.5) as resp:
            out["health"] = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        out["health_error"] = f"{type(exc).__name__}: {exc}"
    return out


def tool_ds_rank_items(champion: str, archetype: str = "", level: int = 11,
                        owned_item_ids: list | None = None, mode: str = "SR",
                        target_armor: float = 0.0, target_mr: float = 0.0,
                        target_max_hp: float = 0.0, target_bonus_hp: float = 0.0,
                        top: int = 8) -> dict:
    if not champion or not str(champion).strip():
        return {"error": "champion required"}
    arch = _resolve_archetype(champion, archetype)
    out = _rank_for_primary_archetype(
        str(champion), arch,
        level=int(level),
        item_ids=[str(i) for i in (owned_item_ids or []) if i],
        mode=str(mode),
        target_armor=float(target_armor),
        target_mr=float(target_mr),
        target_max_hp=float(target_max_hp),
        target_bonus_hp=float(target_bonus_hp),
        top=int(top),
    )
    if out is None:
        return {"error": "daemon slayer engine unreachable on :8860",
                "engine_up": False, "champion": str(champion),
                "archetype": arch}
    return out


def tool_ds_build_order(champion: str, archetype: str = "", level: int = 11,
                         owned_item_ids: list | None = None, mode: str = "SR",
                         target_armor: float = 0.0, target_mr: float = 0.0,
                         target_max_hp: float = 0.0,
                         target_bonus_hp: float = 0.0,
                         slots: int = 6) -> dict:
    if not champion or not str(champion).strip():
        return {"error": "champion required"}
    arch = _resolve_archetype(champion, archetype)
    res = _plan_build_order(
        str(champion), arch,
        level=int(level),
        owned_item_ids=[str(i) for i in (owned_item_ids or []) if i],
        mode=str(mode),
        target_armor=float(target_armor),
        target_mr=float(target_mr),
        target_max_hp=float(target_max_hp),
        target_bonus_hp=float(target_bonus_hp),
        slots=int(slots),
    )
    if res is None:
        return {"error": "daemon slayer engine unreachable on :8860",
                "engine_up": False, "champion": str(champion),
                "archetype": arch}
    return res.to_dict()


def tool_ds_archetype_for(champion: str) -> dict:
    if not champion or not str(champion).strip():
        return {"error": "champion required"}
    return _get_archetype_for(str(champion))


def tool_match_recent(mode: str = "", limit: int = 20) -> dict:
    db = _get_match_db()
    if db is None:
        return {"error": "match_history.db not found",
                "path": str(_MATCH_DB_PATH)}
    cap = max(1, min(int(limit), 200))
    rows = db.get_recent(str(mode or ""), cap)
    return {"mode": str(mode or ""), "count": len(rows), "matches": rows}


def tool_match_mode_stats(mode: str, limit: int = 20) -> dict:
    if not mode or not str(mode).strip():
        return {"error": "mode required (SR/ARAM/ARENA/BRAWL/TFT)"}
    db = _get_match_db()
    if db is None:
        return {"error": "match_history.db not found",
                "path": str(_MATCH_DB_PATH)}
    cap = max(1, min(int(limit), 200))
    stats = db.get_mode_stats(str(mode), cap)
    return {"mode": str(mode), "stats": stats}


def tool_match_tft_comps(which: str = "best", min_games: int = 2,
                          limit: int = 10) -> dict:
    db = _get_match_db()
    if db is None:
        return {"error": "match_history.db not found",
                "path": str(_MATCH_DB_PATH)}
    w = (which or "best").strip().lower()
    if w not in ("best", "worst"):
        return {"error": "which must be 'best' or 'worst'", "got": which}
    cap = max(1, min(int(limit), 50))
    mg = max(1, int(min_games))
    comps = (db.get_best_comps(mg, cap) if w == "best"
             else db.get_worst_comps(mg, cap))
    return {"which": w, "min_games": mg, "count": len(comps),
            "comps": comps}


def tool_match_tft_streak(limit: int = 10) -> dict:
    db = _get_match_db()
    if db is None:
        return {"error": "match_history.db not found",
                "path": str(_MATCH_DB_PATH)}
    cap = max(1, min(int(limit), 100))
    return {"streak": db.get_tft_streak(cap)}


TOOL_FUNCS = {
    "ds_health":         tool_ds_health,
    "ds_rank_items":     tool_ds_rank_items,
    "ds_build_order":    tool_ds_build_order,
    "ds_archetype_for":  tool_ds_archetype_for,
    "match_recent":      tool_match_recent,
    "match_mode_stats":  tool_match_mode_stats,
    "match_tft_comps":   tool_match_tft_comps,
    "match_tft_streak":  tool_match_tft_streak,
}


_CHAMP = {"type": "string", "description": "Champion name (DDragon id or display name)"}
_ARCH = {"type": "string",
         "description": "carry|bruiser|tank|mage|assassin|enchanter; "
                        "blank = auto-resolve from champion",
         "default": ""}
_LEVEL = {"type": "integer", "default": 11, "minimum": 1, "maximum": 18}
_OWNED = {"type": "array", "items": {"type": "string"},
          "description": "Item ids already owned (build so far)",
          "default": []}
_MODE = {"type": "string", "default": "SR",
         "description": "SR|ARAM|ARENA|BRAWL"}
_TA = {"type": "number", "default": 0, "description": "Target armor (0 = no signal)"}
_TM = {"type": "number", "default": 0, "description": "Target MR (0 = no signal)"}
_THP = {"type": "number", "default": 0, "description": "Target max HP (0 = no signal)"}
_TBHP = {"type": "number", "default": 0,
         "description": "Target bonus HP (0 = no signal)"}

TOOLS_SCHEMA = [
    {
        "name": "ds_health",
        "description": ("Check whether the Daemon Slayer engine (:8860) is "
                        "reachable; returns its /health payload when up."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ds_rank_items",
        "description": ("Rank items for a champion via the right "
                        "per-archetype scorer (carry/bruiser/tank/mage/"
                        "assassin/enchanter). Accounts for owned items + "
                        "enemy defenses; enforces the unique-passive "
                        "no-double rule. Engine-down returns an error dict."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "champion": _CHAMP,
                "archetype": _ARCH,
                "level": _LEVEL,
                "owned_item_ids": _OWNED,
                "mode": _MODE,
                "target_armor": _TA,
                "target_mr": _TM,
                "target_max_hp": _THP,
                "target_bonus_hp": _TBHP,
                "top": {"type": "integer", "default": 8, "minimum": 1,
                        "maximum": 30},
            },
            "required": ["champion"],
        },
    },
    {
        "name": "ds_build_order",
        "description": ("Contextual, match-specific ordered build via greedy "
                        "forward selection. Each slot is re-ranked vs the "
                        "accumulated build + enemy context; cross-family "
                        "unique-passive no-double rule enforced engine-side."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "champion": _CHAMP,
                "archetype": _ARCH,
                "level": _LEVEL,
                "owned_item_ids": _OWNED,
                "mode": _MODE,
                "target_armor": _TA,
                "target_mr": _TM,
                "target_max_hp": _THP,
                "target_bonus_hp": _TBHP,
                "slots": {"type": "integer", "default": 6, "minimum": 1,
                          "maximum": 6},
            },
            "required": ["champion"],
        },
    },
    {
        "name": "ds_archetype_for",
        "description": ("Resolved archetype pick {primary, secondary, "
                        "source} for a champion (operator override else "
                        "DDragon-tag default)."),
        "inputSchema": {
            "type": "object",
            "properties": {"champion": _CHAMP},
            "required": ["champion"],
        },
    },
    {
        "name": "match_recent",
        "description": ("Recent match rows from match_history.db, optionally "
                        "filtered by mode."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "default": "",
                         "description": "SR|ARAM|ARENA|BRAWL|TFT; blank = all"},
                "limit": {"type": "integer", "default": 20, "minimum": 1,
                          "maximum": 200},
            },
        },
    },
    {
        "name": "match_mode_stats",
        "description": ("Aggregate stats for a mode over recent games "
                        "(avg K/D, cs/min, gold/min, grade distribution)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string",
                         "description": "SR|ARAM|ARENA|BRAWL|TFT"},
                "limit": {"type": "integer", "default": 20, "minimum": 1,
                          "maximum": 200},
            },
            "required": ["mode"],
        },
    },
    {
        "name": "match_tft_comps",
        "description": ("TFT comps ranked best- or worst-first by average "
                        "placement; only comps played >= min_games."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "which": {"type": "string", "enum": ["best", "worst"],
                          "default": "best"},
                "min_games": {"type": "integer", "default": 2, "minimum": 1},
                "limit": {"type": "integer", "default": 10, "minimum": 1,
                          "maximum": 50},
            },
        },
    },
    {
        "name": "match_tft_streak",
        "description": ("Recent TFT placement summary (avg place, top4 "
                        "count/pct, wins, raw placements)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10, "minimum": 1,
                          "maximum": 100},
            },
        },
    },
]


# -- MCP protocol handlers --------------------------------------------------
def handle_initialize(_params: dict) -> dict:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities":    {"tools": {"listChanged": False}},
        "serverInfo":      {"name": SERVER_NAME, "version": SERVER_VERSION},
    }


def handle_tools_list(_params: dict) -> dict:
    return {"tools": TOOLS_SCHEMA}


def _timeout_for(name: str) -> float:
    """Per-tool dispatch timeout: a long-running tool can opt into a
    higher ceiling via TOOL_TIMEOUT_OVERRIDES so this watchdog never
    preempts the tool's own internal bound."""
    return float(TOOL_TIMEOUT_OVERRIDES.get(name, DISPATCH_TIMEOUT_S))


def _dispatch_tool(name: str, fn, args: dict) -> dict:
    """Run one tool handler under the bounded-pool watchdog.

    Returns the raw handler result dict on success, or a structured MCP
    error dict (always carrying ``isError``) on bad args / handler
    exception / timeout. Never raises, never blocks past the per-tool
    timeout: on timeout the future is abandoned (its thread keeps running
    in the bounded pool but its result is discarded so it cannot corrupt
    a later response) and a structured error is returned immediately so
    the server stays responsive.
    """
    timeout_s = _timeout_for(name)
    fut = _DISPATCH_POOL.submit(fn, **args)
    try:
        return fut.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        # Best-effort cancel (a thread already executing cannot be
        # force-killed in CPython; cancel() only helps if still queued).
        # Either way we abandon the future and return now - the pool is
        # bounded so a stuck worker degrades throughput but never
        # explodes the thread count or wedges the server.
        fut.cancel()
        log.warning("tool %s exceeded dispatch timeout %.1fs - abandoned",
                    name, timeout_s)
        return {"isError": True,
                "content": [{"type": "text",
                             "text": f"tool '{name}' timed out after "
                                     f"{timeout_s:.0f}s (dispatch watchdog); "
                                     f"abandoned to keep server responsive"}],
                "_timeout": True}
    except TypeError as e:
        return {"isError": True,
                "content": [{"type": "text", "text": f"bad arguments: {e}"}]}
    except Exception as e:  # noqa: BLE001
        return {"isError": True,
                "content": [{"type": "text",
                             "text": f"{type(e).__name__}: {e}\n"
                                     + traceback.format_exc(limit=3)}]}


def handle_tools_call(params: dict) -> dict:
    name = params.get("name", "")
    args = params.get("arguments", {}) or {}
    fn = TOOL_FUNCS.get(name)
    if not fn:
        return {"isError": True,
                "content": [{"type": "text", "text": f"unknown tool: {name}"}]}
    result = _dispatch_tool(name, fn, args)
    # Structured error envelopes (bad args / exception / timeout) are
    # already MCP-shaped - pass them straight through.
    if isinstance(result, dict) and result.get("isError"):
        return result
    text = _json_dumps_safe(result, indent=2, default=str)
    return {"content": [{"type": "text", "text": text}]}


METHOD_HANDLERS = {
    "initialize":  handle_initialize,
    "tools/list":  handle_tools_list,
    "tools/call":  handle_tools_call,
    "ping":        lambda p: {},
}


# -- HTTP server ------------------------------------------------------------
class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = f"{SERVER_NAME}/{SERVER_VERSION}"

    def log_message(self, fmt: str, *a: object) -> None:
        log.info("HTTP " + fmt, *a)

    def _send(self, status: int, body: bytes,
              ctype: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:  # noqa: BLE001
            pass

    def _check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth != f"Bearer {AUTH_TOKEN}":
            self._send(401, b'{"error":"unauthorized"}')
            return False
        return True

    def do_GET(self) -> None:
        if self.path.startswith("/health"):
            if not self._check_auth():
                return
            body = json.dumps({"alive": True,
                               "uptime_s": int(time.time() - _START),
                               "tools": list(TOOL_FUNCS.keys())}).encode()
            self._send(200, body)
            return
        self._send(404, b'{"error":"not found"}')

    def do_POST(self) -> None:
        if not self.path.startswith("/mcp"):
            self._send(404, b'{"error":"not found"}')
            return
        if not self._check_auth():
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except Exception:  # noqa: BLE001
            n = 0
        # Lane 8, 2026-08-03: a NEGATIVE Content-Length makes
        # `self.rfile.read(n) if n else b""` read to EOF, pinning a
        # ThreadingHTTPServer worker until the client goes away. Third
        # instance of this defect in the tree - see vision_server/_http.py
        # (LEDGER 1177) and dashboard/_handler.py. Lower severity here (this
        # binds loopback at :8861 and _check_auth runs first) but the same
        # bug, so it is closed in the same sweep rather than left as the one
        # that got away.
        if n < 0:
            self._send_jsonrpc(None, error=(-32600, "Invalid Content-Length"))
            return
        raw = self.rfile.read(n) if n else b""
        try:
            req = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:  # noqa: BLE001
            self._send_jsonrpc(None, error=(-32700, f"Parse error: {e}"))
            return
        is_notification = "id" not in req
        method = req.get("method", "")
        rid = req.get("id")
        params = req.get("params", {}) or {}
        if is_notification:
            log.info("notification: %s", method)
            self._send(202, b"")
            return
        handler = METHOD_HANDLERS.get(method)
        if not handler:
            self._send_jsonrpc(rid, error=(-32601, f"method not found: {method}"))
            return
        try:
            result = handler(params)
        except Exception as e:  # noqa: BLE001
            log.warning("handler %s raised: %s", method, e)
            self._send_jsonrpc(rid, error=(-32603, f"{type(e).__name__}: {e}"))
            return
        self._send_jsonrpc(rid, result=result)

    def _send_jsonrpc(self, rid, result=None, error=None):
        env = {"jsonrpc": "2.0", "id": rid}
        if error is not None:
            code, message = error
            env["error"] = {"code": code, "message": message}
        else:
            env["result"] = result
        self._send(200, _json_dumps_safe(env, default=str).encode())


def serve_forever(host: str = HOST, port: int = PORT) -> int:
    """Bind + serve. Returns an int exit code (mirrors
    agents.daemon_slayer.server.serve_forever so the launcher contract
    matches tools/start_daemon_slayer.py)."""
    # Connect-probe preflight: if another instance already serves, exit
    # cleanly instead of crashing with OSError 10048.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        probe.connect(("127.0.0.1", port))
        probe.close()
        log.warning("port %d already serving - another ds-matchdb-mcp "
                    "instance is running; exiting cleanly", port)
        return 0
    except (ConnectionRefusedError, socket.timeout, OSError):
        pass
    finally:
        try:
            probe.close()
        except Exception:  # noqa: BLE001
            pass
    log.info("ds-matchdb-mcp listening on %s:%d (tools=%d, token=...%s)",
             host, port, len(TOOL_FUNCS), AUTH_TOKEN[-4:])
    try:
        srv = http.server.ThreadingHTTPServer((host, port), _Handler)
    except OSError as e:
        log.error("bind %s:%d failed: %s", host, port, e)
        return 1
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log.info("stopped")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=HOST)
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--show-token", action="store_true",
                   help="print token and exit (for client config setup)")
    args = p.parse_args()
    if args.show_token:
        print(AUTH_TOKEN)
        return 0
    return serve_forever(args.host, args.port)


if __name__ == "__main__":
    sys.exit(main())

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

Schedule at logon for persistence (PowerShell; runs as the current user).
RM-404: this was a caret-continued `schtasks /Create`, which PowerShell
splits into two commands with ZERO parse errors - the /TR payload was
silently dropped. Register-ScheduledTask takes the executable and its
arguments as SEPARATE parameters, so no continuation escaping arises.
Pinned by tests/test_scheduled_task_docstring_commands.py.

  Register-ScheduledTask -TaskName "RC-DS-MatchDB-MCP" -Force -RunLevel Highest `
    -Trigger (New-ScheduledTaskTrigger -AtLogOn) `
    -Action (New-ScheduledTaskAction -Execute "pythonw.exe" -Argument '"<repo>\\tools\\start_ds_matchdb_mcp.py"')

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
import inspect
import json
import logging
import math
import os
import sys
import threading
import time
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
from core.http_host_gate import HostAllowlistMixin  # noqa: E402
from core.log_scrub import install_scrub_filter, scrub_log  # noqa: E402
from core.match_db import MatchDB  # noqa: E402
from core.port_handoff import (  # noqa: E402
    LIVE as _HANDOFF_LIVE,
    POLL_S as _DEFAULT_HANDOFF_POLL_S,
    STUCK as _HANDOFF_STUCK,
    WINDOW_S as _DEFAULT_HANDOFF_WINDOW_S,
    await_port as _await_port,
    health_answers as _health_answers,
    json_check as _json_check,
)

HOST = "127.0.0.1"
PORT = 8861
# Session 129: how long a start waits for a predecessor that still holds the
# port (core/port_handoff.py). Module-level so a test can shorten it.
_HANDOFF_WINDOW_S = _DEFAULT_HANDOFF_WINDOW_S
_HANDOFF_POLL_S = _DEFAULT_HANDOFF_POLL_S
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
# RM-811 residuals: the log-injection backstop (core/log_scrub.py). Above all
# it renders an exc_info traceback with each exception's text scrubbed onto
# one line - a tool that raised on the client's arguments used to write that
# text, CR/LF and escapes included, into the log verbatim.
install_scrub_filter(log)

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


def _db_path_label() -> str:
    """The db path a db-missing reply names: repo-relative, never absolute.

    RM-770 sibling: the absolute path names the checkout's directory, the same
    leak as the traceback frames, and the relative form tells a caller as much.
    """
    try:
        return _MATCH_DB_PATH.relative_to(_PROJECT_ROOT).as_posix()
    except ValueError:
        return _MATCH_DB_PATH.name


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
        # RM-770 sibling: the exception text stays in the log.
        log.warning("ds health read failed: %s: %s", type(exc).__name__,
                    scrub_log(str(exc)))
        out["health_error"] = type(exc).__name__
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
                "path": _db_path_label()}
    cap = max(1, min(int(limit), 200))
    rows = db.get_recent(str(mode or ""), cap)
    return {"mode": str(mode or ""), "count": len(rows), "matches": rows}


def tool_match_mode_stats(mode: str, limit: int = 20) -> dict:
    if not mode or not str(mode).strip():
        return {"error": "mode required (SR/ARAM/ARENA/BRAWL/TFT)"}
    db = _get_match_db()
    if db is None:
        return {"error": "match_history.db not found",
                "path": _db_path_label()}
    cap = max(1, min(int(limit), 200))
    stats = db.get_mode_stats(str(mode), cap)
    return {"mode": str(mode), "stats": stats}


def tool_match_tft_comps(which: str = "best", min_games: int = 2,
                          limit: int = 10) -> dict:
    db = _get_match_db()
    if db is None:
        return {"error": "match_history.db not found",
                "path": _db_path_label()}
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
                "path": _db_path_label()}
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
    # RM-770: bind BEFORE dispatch, so "bad arguments" means the caller's
    # arguments. A TypeError raised INSIDE a tool used to land in the same
    # branch and was echoed as caller error; it is a tool failure now and
    # takes the fixed-message path below. A non-mapping `arguments` raised
    # out of `submit(fn, **args)`, outside this function's try.
    if not isinstance(args, dict):
        return {"isError": True,
                "content": [{"type": "text",
                             "text": "bad arguments: arguments must be an "
                                     "object"}]}
    try:
        inspect.signature(fn).bind(**args)
    except TypeError as e:
        # The bind message names only the caller's own keyword or the
        # missing parameter.
        return {"isError": True,
                "content": [{"type": "text", "text": f"bad arguments: {e}"}]}
    except ValueError:
        pass    # no introspectable signature: the call itself decides
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
    except Exception as e:  # noqa: BLE001
        # RM-770: this answered with the exception text plus
        # traceback.format_exc(limit=3), whose frames name the checkout's
        # absolute file paths. Per RM-760a the exception text and the
        # traceback stay in the log; the client gets a fixed message.
        # RM-811 residuals: the logger's ScrubFilter renders this traceback
        # (frames kept, every exception's text scrubbed onto one line);
        # guarded by tests/test_log_scrub_residuals_rm811b.py.
        log.warning("tool %s raised %s", name, type(e).__name__,
                    exc_info=True)
        return {"isError": True,
                "content": [{"type": "text",
                             "text": f"tool '{name}' failed: "
                                     f"{type(e).__name__} "
                                     "(details in the server log)"}]}


def handle_tools_call(params: dict) -> dict:
    name = params.get("name", "")
    args = params.get("arguments", {}) or {}
    # RM-769 sibling: an unhashable (list / dict) name raised TypeError here,
    # surfacing as -32603; a non-string name is simply an unknown tool.
    fn = TOOL_FUNCS.get(name) if isinstance(name, str) else None
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
def _valid_id(rid) -> bool:
    """A JSON-RPC 2.0 id: a string, a finite number (never a bool), or null."""
    if rid is None or isinstance(rid, str):
        return True
    if isinstance(rid, bool):
        return False
    if isinstance(rid, int):
        return True
    return isinstance(rid, float) and math.isfinite(rid)


class _Handler(HostAllowlistMixin, http.server.BaseHTTPRequestHandler):
    server_version = f"{SERVER_NAME}/{SERVER_VERSION}"
    # RM-819: the shared RM-759 Host gate (core/http_host_gate.py), FIRST so
    # it runs on the parsed head: a Host this machine does not answer to is
    # 421 before any route (DNS rebinding; the MCP transport spec asks a
    # local server to guard against it); a head whose parse lost lines
    # (RM-773) or a target that is not origin-form (RM-774) is 400; HTTP/0.9
    # is closed. The bearer still gates every route.
    host_refusal_log = log

    def log_message(self, fmt: str, *a: object) -> None:
        # RM-321: an override loses the stdlib's control-character escaping;
        # scrub the formatted record and name the peer.
        log.info("HTTP %s %s", self.address_string(), scrub_log(fmt % a))

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
        # RM-760a: the parser's own text (positions, codec detail) is logged,
        # never returned; ValueError covers JSONDecodeError, UnicodeDecodeError
        # and the 4300-digit int limit, RecursionError covers deep nesting.
        try:
            req = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, RecursionError) as e:
            log.warning("parse error: %s: %s", type(e).__name__,
                        scrub_log(str(e)))
            self._send_jsonrpc(None, error=(-32700, "Parse error"))
            return
        if not isinstance(req, dict):
            self._send_jsonrpc(None, error=(-32600, "Invalid Request"))
            return
        is_notification = "id" not in req
        method = req.get("method", "")
        rid = req.get("id")
        # RM-811 residuals: JSON-RPC 2.0 section 4 - an id is a string, a
        # number or null. An object / array / boolean id (or the NaN /
        # Infinity json.loads accepts) used to be echoed in an ordinary
        # reply; it is an invalid request, answered with id null, checked
        # before the notification branch like the method check below.
        if not is_notification and not _valid_id(rid):
            self._send_jsonrpc(None, error=(-32600, "Invalid Request"))
            return
        # RM-811: an omitted or null params is the empty object; anything
        # else that is not an object is checked below (-32602). The old
        # `or {}` turned [] / 0 / "" into {} and let "x" / [1] / 5 reach a
        # handler's params.get(), which raised and answered -32603.
        params = req.get("params")
        if params is None:
            params = {}
        # RM-769: JSON-RPC 2.0 requires a string `method`. A list or dict is
        # unhashable, so METHOD_HANDLERS.get() below raised TypeError out of
        # do_POST and dropped the connection with no reply. Checked BEFORE the
        # notification branch: the spec answers an invalid request even
        # without an id (id null).
        if not isinstance(method, str):
            self._send_jsonrpc(rid, error=(-32600, "Invalid Request"))
            return
        if is_notification:
            # RM-811: the method is the client's text (RM-321 class).
            log.info("notification: %s", scrub_log(method))
            self._send(202, b"")
            return
        handler = METHOD_HANDLERS.get(method)
        if not handler:
            self._send_jsonrpc(rid, error=(-32601, f"method not found: {method}"))
            return
        # RM-811: JSON-RPC 2.0 section 4.2 - params, when present, is a
        # structured value, and every method here takes named params, so a
        # non-object is -32602 Invalid params (it used to raise inside the
        # handler and answer -32603 Internal error).
        if not isinstance(params, dict):
            self._send_jsonrpc(rid, error=(-32602, "Invalid params"))
            return
        try:
            result = handler(params)
        except Exception as e:  # noqa: BLE001
            # RM-760a: the exception text stays in the log, not the reply.
            # RM-811: scrubbed - it can carry the client's own text.
            log.warning("handler %s raised: %s: %s", scrub_log(method),
                        type(e).__name__, scrub_log(str(e)))
            self._send_jsonrpc(rid, error=(-32603, "Internal error"))
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


class _CappedStartEvent(threading.Event):
    """``Thread._started`` with a ceiling on the wait ``Thread.start()`` makes."""

    def __init__(self, cap_s: float) -> None:
        super().__init__()
        self._cap_s = cap_s

    def wait(self, timeout: float | None = None) -> bool:
        if timeout is None or timeout > self._cap_s:
            timeout = self._cap_s
        return super().wait(timeout)


class _RequestThread(threading.Thread):
    """RM-738: a per-request thread whose ``start()`` cannot park the accept loop.

    ``Thread.start()`` waits on ``self._started`` with no timeout, and only the
    NEW thread sets it (``_bootstrap_inner``, after ``_set_native_id``). A
    thread that dies in bootstrap - MemoryError under commit-charge
    exhaustion, RM-735 / RM-737 - would park ``serve_forever`` for good. Here
    that wait is capped; a thread not started by then is abandoned and the
    server drops the connection. One that starts late sees the abandon in
    ``run()`` and returns without touching the dropped socket.
    """

    def __init__(self, server: "_MatchDBHTTPServer", request, client_address) -> None:
        super().__init__(daemon=server.daemon_threads)
        self._started = _CappedStartEvent(server.thread_start_timeout_s)
        self._job: tuple | None = (server, request, client_address)
        self._gate = threading.Lock()
        self._outcome: str | None = None        # "claimed" | "abandoned"

    def run(self) -> None:
        with self._gate:
            if self._outcome is not None:
                return
            self._outcome = "claimed"
            job, self._job = self._job, None
        server, request, client_address = job
        server.process_request_thread(request, client_address)

    def abandon_if_unstarted(self) -> bool:
        if self._started.is_set():
            return False
        with self._gate:
            if self._outcome is not None:
                return False
            self._outcome = "abandoned"
            self._job = None
            return True


class _MatchDBHTTPServer(http.server.ThreadingHTTPServer):
    """ThreadingHTTPServer whose per-request thread start is capped (RM-738)."""

    # A thread start normally takes well under a millisecond. RM-740 (d),
    # measured 2026-10-14 under a gated -n 8 suite: max 25 ms, 157 ms with a
    # GIL-busy thread in the process; 2.0 s (~13x) is KEPT - a larger cap
    # only parks the accept loop longer behind a start that truly died.
    # tests/test_rm740d_thread_start_caps.py pins both.
    thread_start_timeout_s = 2.0
    thread_start_failures = 0

    def process_request(self, request, client_address) -> None:
        # ThreadingMixIn.process_request with a capped start. The stdlib's
        # _threads bookkeeping is not carried: it never holds daemon threads.
        t = _RequestThread(self, request, client_address)
        start_error: Exception | None = None
        try:
            t.start()
        except Exception as exc:  # noqa: BLE001 - e.g. "can't start new thread"
            # RM-740 (b): a start that raises is a failed start too - dropped,
            # counted and logged here, never left to escape to handle_error.
            # No traceback kept: it would pin this frame (and the request).
            # abandon_if_unstarted() still arbitrates: a thread that did
            # come up before the raise owns its request.
            start_error = exc.with_traceback(None)
        if not t.abandon_if_unstarted():
            return
        # Count and log BEFORE the close (the dashboard's order), so a client
        # that has seen its connection dropped can rely on both.
        self.thread_start_failures += 1
        try:
            if self.thread_start_failures == 1 or self.thread_start_failures % 100 == 0:
                why = (f"did not start within {self.thread_start_timeout_s:.1f}s"
                       if start_error is None else f"start raised {start_error!r}")
                log.warning("request thread %s - dropped connection #%d "
                            "from %s (RM-738)", why,
                            self.thread_start_failures, client_address)
        except Exception:  # noqa: BLE001 - logging can fail under the same memory pressure
            pass
        self.shutdown_request(request)


def holder_is_matchdb(host: str = HOST, port: int = PORT) -> bool:
    """True when ``host:port`` answers ``/health`` as THIS server.

    The bearer token is ours and the body has this server's shape
    (``alive`` true, a ``tools`` list): a 401, a foreign 200 or no answer
    is not a live ds-matchdb-mcp instance.
    """
    return _health_answers(
        host, port, headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        check=_json_check(lambda d: d.get("alive") is True
                          and isinstance(d.get("tools"), list)))


def serve_forever(host: str = HOST, port: int = PORT) -> int:
    """Bind + serve. Returns an int exit code (mirrors
    agents.daemon_slayer.server.serve_forever so the launcher contract
    matches tools/start_daemon_slayer.py)."""
    # Port hand-off preflight (session 129). This was a one-shot connect
    # probe: "something answers now" meant exit 0, so a start racing a
    # predecessor that was still exiting skipped, the predecessor died, and
    # nothing listened. Now: wait up to _HANDOFF_WINDOW_S for the port to
    # free; exit 0 only if a live instance still holds it after that.
    h = _await_port(host, port, holder_live=lambda: holder_is_matchdb(host, port),
                    window_s=_HANDOFF_WINDOW_S, poll_s=_HANDOFF_POLL_S)
    if h.state == _HANDOFF_LIVE:
        log.warning("port %d already serving - another ds-matchdb-mcp "
                    "instance is running; exiting cleanly", port)
        return 0
    if h.state == _HANDOFF_STUCK:
        log.error("port %d still bound after %.0fs by a holder that does not "
                  "answer as ds-matchdb-mcp - not started", port, h.waited_s)
        return 1
    if h.waited_s >= _HANDOFF_POLL_S:
        log.info("port %d released by its previous holder after %.1fs",
                 port, h.waited_s)
    log.info("ds-matchdb-mcp listening on %s:%d (tools=%d, token=...%s)",
             host, port, len(TOOL_FUNCS), AUTH_TOKEN[-4:])
    try:
        srv = _MatchDBHTTPServer((host, port), _Handler)
    except OSError as e:
        log.error("bind %s:%d failed: %s", host, port, scrub_log(str(e)))
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

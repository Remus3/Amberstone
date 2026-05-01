"""State / health / version routes.

Slice 2C (2026-05-01): handlers carved out of web_dashboard._Handler.
Group 2 — state-shaped GETs that the dashboard polls frequently.

Each route receives the BaseHTTPRequestHandler (`h`) as its sole
argument and uses `h._send(code, body, ctype)` to write the response.
Module-level GET_ROUTES is consumed by `dashboard._dispatch`.
"""
import hashlib
import json
import logging
import os
import time
import urllib.request
from urllib.parse import parse_qs, urlparse

from dashboard._context import APP_DIR, read_json
from dashboard._dispatch import equals, prefix
from dashboard._writers import (
    atomic_write_json,
    force_vision_scan,
    set_pregame,
)

log = logging.getLogger("rc.web_dashboard")


# /api/state cache — populated lazily on first hit; declared at module
# scope so the request handler can rebind it. 1.0 s TTL absorbs
# high-frequency dashboard polls (5+ tabs polling tightly would
# otherwise duplicate the vision-relay round-trip in _build_state).
_STATE_CACHE_PAYLOAD: bytes | None = None
_STATE_CACHE_TS: float = 0.0


def _serve_state(h) -> None:
    global _STATE_CACHE_PAYLOAD, _STATE_CACHE_TS
    try:
        from web_dashboard import _build_state
        now = time.time()
        if _STATE_CACHE_PAYLOAD is not None and (now - _STATE_CACHE_TS) < 1.0:
            payload = _STATE_CACHE_PAYLOAD
        else:
            payload = json.dumps(_build_state()).encode("utf-8")
            _STATE_CACHE_PAYLOAD = payload
            _STATE_CACHE_TS = now
        h._send(200, payload, "application/json")
    except Exception as exc:
        log.warning("api/state: %s", exc)
        h._send(500, b'{"error":"state_build_failed"}', "application/json")


def _serve_sim_state(h) -> None:
    try:
        from web_dashboard import _sim_states
        qs = parse_qs(urlparse(h.path).query)
        scenario = (qs.get("scenario") or ["aram_blitz"])[0]
        state = _sim_states().get(scenario)
        if not state:
            h._send(404, b'{"error":"unknown_scenario"}', "application/json"); return
        h._send(200, json.dumps(state).encode(), "application/json")
    except Exception as exc:
        log.warning("api/sim-state: %s", exc)
        h._send(500, b'{"error":"sim_state_failed"}', "application/json")


def _serve_health(h) -> None:
    d = read_json("ops/runtime/health.json")
    # AUDIT 2026-04-28: stamp the canonical RC app version.
    try:
        from core.version import version_string as _vs
        d["rc_version"] = _vs()
    except Exception:
        d["rc_version"] = ""
    h._send(200, json.dumps(d).encode("utf-8"), "application/json")


def _serve_health_all(h) -> None:
    # Consolidated rollup: RC health + vision-server health +
    # supervisor PID lock view + cost-banner state. One green/
    # yellow/red dot for the dashboard top-right.
    try:
        rollup = {"rc": read_json("ops/runtime/health.json")}
        try:
            with urllib.request.urlopen("http://127.0.0.1:8889/health", timeout=2) as r:
                rollup["vision"] = json.loads(r.read())
        except Exception as e:
            rollup["vision"] = {"alive": False, "error": str(e)[:120]}
        try:
            sup = read_json("ops/runtime/supervisor.pid")
            # AUDIT 2026-04-29: also surface oslock state — when the
            # .oslock sidecar exists, the OS-level msvcrt byte-range
            # lock is held by the supervisor process.
            oslock_path = APP_DIR / "ops" / "runtime" / "supervisor.pid.oslock"
            rollup["supervisor"] = {
                "pid":       sup.get("pid"),
                "run_id":    sup.get("run_id"),
                "locked_at": sup.get("locked_at"),
                "oslock_present": oslock_path.exists(),
            }
        except Exception as e:
            rollup["supervisor"] = {"error": str(e)[:120]}
        try:
            from core.version import version_string as _vs
            rollup["rc_version"] = _vs()
        except Exception:
            rollup["rc_version"] = ""
        try:
            from core.cost_tracker import get_tracker as _gt
            rollup["cost"] = {"banner": _gt().banner_state(),
                              "today_usd": _gt().daily_spend().get("total_usd", 0.0)}
        except Exception as e:
            rollup["cost"] = {"error": str(e)[:120]}
        rc_ok = bool(rollup.get("rc", {}).get("alive"))
        vis_ok = bool(rollup.get("vision", {}).get("alive"))
        cost_ok = rollup.get("cost", {}).get("banner") != "over"
        if not rc_ok or not vis_ok:
            rollup["status"] = "red"
        elif not cost_ok or rollup.get("cost", {}).get("banner") == "warn":
            rollup["status"] = "yellow"
        else:
            rollup["status"] = "green"
        h._send(200, json.dumps(rollup).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/health/all: %s", exc)
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")


def _serve_ui_version(h) -> None:
    # Auto-reload signal: hash the mtimes of the css/js/html we serve
    # from web/. Dashboard polls and reloads when the hash changes.
    try:
        web_root = APP_DIR / "web"
        files = [web_root / "index.html",
                 web_root / "css" / "dashboard.css",
                 web_root / "js" / "dashboard.js",
                 web_root / "js" / "sim.js"]
        sig = ":".join(f"{f.name}={int(f.stat().st_mtime_ns)}"
                       for f in files if f.exists())
        digest = hashlib.sha1(sig.encode()).hexdigest()[:12]
        h._send(200, json.dumps({"v": digest}).encode(), "application/json")
    except Exception as exc:
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


def _serve_asset_stamp(h) -> None:
    # 2026-04-30: hot-reload signal. Returns the max mtime across the
    # dashboard's static assets so a tiny client poller can detect file
    # changes and refresh without the user alt-tabbing to hit Ctrl+F5.
    try:
        root = APP_DIR / "web"
        files = ["index.html", "css/dashboard.css", "js/dashboard.js"]
        stamp = max(os.path.getmtime(root / f) for f in files
                    if (root / f).exists())
        h._send(200, json.dumps({"mtime": stamp}).encode(),
                "application/json")
    except Exception as exc:
        log.debug("asset-stamp: %s", exc)
        h._send(200, b'{"mtime":0}', "application/json")


# ── POST handlers (slice 2C-7a) ──────────────────────────────────────


def _serve_input_post(h, payload) -> None:
    text = (payload.get("text") or "").strip()
    if not text:
        h._send(400, b'{"error":"empty_text"}', "application/json"); return
    try:
        set_pregame(text)
        log.info("dashboard input: %d chars accepted", len(text))
        h._send(200, b'{"ok":true}', "application/json")
    except Exception as exc:
        log.warning("api/input write: %s", exc)
        h._send(500, b'{"error":"write_failed"}', "application/json")


def _serve_command_post(h, payload) -> None:
    cmd = (payload.get("command") or "").strip().lower()
    try:
        if cmd == "force_vision":
            force_vision_scan()
        elif cmd == "refresh":
            # Touch coaching_data.json to bump mtime; coaches re-emit.
            # Held under the shared coaching_data_lock so a coach
            # R-M-W in another thread can't clobber the read+rewrite
            # cycle (NOTE-003 fix).
            from core.coaching_data_lock import coaching_data_lock
            with coaching_data_lock():
                d = read_json("coaching_data.json")
                atomic_write_json("coaching_data.json", d)
        elif cmd == "clear_pregame":
            set_pregame("")
        else:
            h._send(400, b'{"error":"unknown_command"}', "application/json"); return
        log.info("dashboard command: %s", cmd)
        h._send(200, b'{"ok":true}', "application/json")
    except Exception as exc:
        log.warning("api/command %s: %s", cmd, exc)
        h._send(500, b'{"error":"command_failed"}', "application/json")


# /api/console-error server-side throttle (10 Hz cap, all clients combined).
# Migrated from web_dashboard._CE_LAST_TS/_CE_DROPPED in slice 2C-7a — nothing
# outside this handler reads the counters.
_CE_LAST_TS: float = 0.0
_CE_DROPPED: int   = 0


def _serve_analyze_post(h, payload) -> None:
    # Dashboard's "Analyze Now" button — forward POST to the supervisor
    # at :8890. Synchronous: returns supervisor's response. timeout=30
    # because analysis runs are multi-second (default 4 would lop them off).
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
        h._send(200, body, ctype)
    except Exception as exc:
        log.warning("api/analyze: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(),
                "application/json")


def _serve_console_error_post(h, payload) -> None:
    # Receives browser-side JS errors from the dashboard
    # (window.onerror, unhandledrejection, console.error). Lands
    # them in RC's log so JS exceptions are visible without the
    # user having to open DevTools. Body shape:
    #   {kind, message, source, lineno, colno, stack, url, ts}
    # Server-side throttle: cap at 10 Hz across ALL clients to
    # prevent a runaway error loop in a misbehaving tab from
    # flooding the daily log. Drops are silent (the client's own
    # `dropped_since_last` field surfaces the count anyway).
    global _CE_LAST_TS, _CE_DROPPED
    _now_ce = time.time()
    if _now_ce - _CE_LAST_TS < 0.1:
        _CE_DROPPED += 1
        h._send(200, b'{"ok":true,"throttled":true}', "application/json")
        return
    _CE_LAST_TS = _now_ce
    if _CE_DROPPED:
        log.info("client-console: %d previously throttled", _CE_DROPPED)
        _CE_DROPPED = 0
    try:
        kind  = (payload.get("kind") or "error")[:30]
        msg   = (payload.get("message") or "")[:600]
        src   = (payload.get("source") or "")[:200]
        line  = int(payload.get("lineno") or 0)
        col   = int(payload.get("colno") or 0)
        stack = (payload.get("stack") or "")[:1500]
        url   = (payload.get("url") or "")[:300]
        ua    = h.headers.get("User-Agent", "")[:80]
        log.warning(
            "client-console %s | %s:%d:%d | %s | url=%s | ua=%s%s",
            kind, src, line, col, msg, url, ua,
            ("\n  stack: " + stack) if stack else "",
        )
        h._send(200, b'{"ok":true}', "application/json")
    except Exception as exc:
        h._send(500, json.dumps({"error": str(exc)}).encode(),
                "application/json")


# ── route table ──────────────────────────────────────────────────────

# Order: prefix("/api/sim-state") sits before equals matchers that
# touch the same /api/state* surface, but they're disjoint paths so
# first-match-wins semantics don't bite. The /api/ui-version handler
# uses prefix() because the legacy do_GET used `startswith`.
GET_ROUTES = [
    (equals("/api/state"),         _serve_state),
    (prefix("/api/sim-state"),     _serve_sim_state),
    (equals("/api/health"),        _serve_health),
    (equals("/api/health/all"),    _serve_health_all),
    (prefix("/api/ui-version"),    _serve_ui_version),
    (equals("/api/asset-stamp"),   _serve_asset_stamp),
]

POST_ROUTES = [
    (equals("/api/input"),          _serve_input_post),
    (equals("/api/command"),        _serve_command_post),
    (equals("/api/console-error"),  _serve_console_error_post),
    (equals("/api/analyze"),        _serve_analyze_post),
]

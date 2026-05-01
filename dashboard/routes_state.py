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

POST_ROUTES: list = []

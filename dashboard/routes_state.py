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
import threading
import time
import urllib.request
from urllib.parse import parse_qs, urlparse

from dashboard._bridge_log import gamepc_result_age_s
from dashboard._context import APP_DIR, read_json
from dashboard._dispatch import equals, prefix
from dashboard._state_builder import build_state, sim_states
from dashboard._writers import (
    atomic_write_json,
    force_vision_scan,
    set_pregame,
)

# Bridge watchdog thresholds (seconds since last gamepc result).
# Below WARN: green. WARN..ALERT: yellow. >= ALERT: red.
# 600s/3600s match the existing rc_facts.py threshold (1hr) for the
# alert level and the 10-min audit recommendation for the warn level.
_BRIDGE_WARN_S = 600
_BRIDGE_ALERT_S = 3600

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
        now = time.time()
        if _STATE_CACHE_PAYLOAD is not None and (now - _STATE_CACHE_TS) < 1.0:
            payload = _STATE_CACHE_PAYLOAD
        else:
            payload = json.dumps(build_state()).encode("utf-8")
            _STATE_CACHE_PAYLOAD = payload
            _STATE_CACHE_TS = now
        h._send(200, payload, "application/json")
    except Exception as exc:
        log.warning("api/state: %s", exc)
        h._send(500, b'{"error":"state_build_failed"}', "application/json")


# /api/state-stream SSE — Tier 4 #16 (2026-05-01). Pushes /api/state
# payload on change + heartbeat every _SSE_HEARTBEAT_S so the dashboard
# can skip its dedicated LCU poller and HTTP-fallback /api/state polls
# while a stream is connected. EventSource on the client auto-reconnects
# on disconnect, so we cap connection lifetime at _SSE_MAX_DURATION_S
# to keep dispatcher threads from accumulating across long sessions.
_SSE_TICK_S         = 1.0     # how often we re-build state to compare
_SSE_HEARTBEAT_S    = 15.0    # max idle gap before a forced emit
_SSE_MAX_DURATION_S = 600.0   # close + let client reconnect after 10min
_SSE_MAX_SUBSCRIBERS = 8      # cap concurrent open streams
_sse_count = 0
_sse_count_lock = threading.Lock()


def _serve_state_stream(h) -> None:
    """Long-lived SSE response. Streams /api/state payloads as `data: …\\n\\n`
    events whenever the JSON hash changes, plus a periodic heartbeat so a
    dead connection drops within ~15s instead of accumulating silently."""
    global _sse_count
    with _sse_count_lock:
        if _sse_count >= _SSE_MAX_SUBSCRIBERS:
            h._send(503, b'{"error":"too_many_subscribers"}', "application/json")
            return
        _sse_count += 1
    try:
        # Send the SSE response headers manually — `_send` sets a
        # Content-Length, which would terminate the response after
        # the first chunk.
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-store")
        h.send_header("Connection", "close")  # one-shot per connection
        h.send_header("X-Accel-Buffering", "no")
        try:
            sock = h.connection
            if hasattr(sock, "cipher") and callable(sock.cipher):
                h.send_header("Strict-Transport-Security", "max-age=31536000")
        except Exception:
            pass
        h.end_headers()

        last_hash: bytes | None = None
        last_emit = 0.0
        start = time.time()
        # Suggested retry delay if the connection drops (browsers honor this).
        try:
            h.wfile.write(b"retry: 2000\n\n")
            h.wfile.flush()
        except OSError:
            return

        while time.time() - start < _SSE_MAX_DURATION_S:
            try:
                payload = json.dumps(build_state())
            except Exception as exc:
                log.warning("state-stream build: %s", exc)
                payload = "{}"
            ph = hashlib.md5(payload.encode("utf-8")).digest()
            now = time.time()
            if ph != last_hash or (now - last_emit) >= _SSE_HEARTBEAT_S:
                line = ("data: " + payload + "\n\n").encode("utf-8")
                try:
                    h.wfile.write(line)
                    h.wfile.flush()
                except (OSError, ConnectionError):
                    return  # client disconnected
                last_hash = ph
                last_emit = now
            time.sleep(_SSE_TICK_S)
    finally:
        with _sse_count_lock:
            _sse_count -= 1


def _serve_sim_state(h) -> None:
    try:
        qs = parse_qs(urlparse(h.path).query)
        scenario = (qs.get("scenario") or ["aram_blitz"])[0]
        state = sim_states().get(scenario)
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
            with urllib.request.urlopen("http://127.0.0.1:8893/health", timeout=2) as r:
                ds_data = json.loads(r.read())
                rollup["daemon_slayer"] = {**ds_data, "alive": ds_data.get("status") == "ok"}
        except Exception as e:
            rollup["daemon_slayer"] = {"alive": False, "error": str(e)[:120]}
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
        try:
            age = gamepc_result_age_s()
            if age is None:
                bridge_status = "unknown"
            elif age < _BRIDGE_WARN_S:
                bridge_status = "green"
            elif age < _BRIDGE_ALERT_S:
                bridge_status = "yellow"
            else:
                bridge_status = "red"
            rollup["bridge"] = {
                "age_s":   round(age, 1) if age is not None else None,
                "status":  bridge_status,
                "warn_s":  _BRIDGE_WARN_S,
                "alert_s": _BRIDGE_ALERT_S,
            }
        except Exception as e:
            rollup["bridge"] = {"error": str(e)[:120], "status": "unknown"}
        # (2026-05-03) Peer bridge_watcher heartbeats — published by the
        # sidecar tools/bridge_watcher_health_publisher.py on each peer
        # via POST /api/health/peer/<node>. Stale = no heartbeat in 5+
        # minutes. No-data = peer hasn't been deployed yet.
        try:
            peers = {}
            for node in ("gamepc", "peer"):
                rec_path = APP_DIR / "ops" / "runtime" / "peer_health" / f"{node}.json"
                if not rec_path.exists():
                    peers[node] = {"status": "no_data"}
                    continue
                rec = json.loads(rec_path.read_text(encoding="utf-8"))
                recv = rec.get("received_at") or 0
                age_s = max(0.0, time.time() - recv)
                hb = rec.get("heartbeat") or {}
                peers[node] = {
                    "age_s":          round(age_s, 1),
                    "stale":          age_s > 300,
                    "watcher_alive":  bool(hb.get("alive")),
                    "watcher_pid":    hb.get("pid"),
                    "queue_depth":    hb.get("queue_depth"),
                    "auto_ok":        hb.get("auto_ok_since_boot"),
                    "auto_err":       hb.get("auto_err_since_boot"),
                    "escalations":    hb.get("escalations_since_boot"),
                    "tokens_today_usd": hb.get("tokens_used_today_usd"),
                }
            rollup["peers"] = peers
        except Exception as e:
            rollup["peers"] = {"error": str(e)[:120]}
        rc_ok = bool(rollup.get("rc", {}).get("alive"))
        vis_ok = bool(rollup.get("vision", {}).get("alive"))
        ds_ok = bool(rollup.get("daemon_slayer", {}).get("alive"))
        cost_ok = rollup.get("cost", {}).get("banner") != "over"
        # Bridge silence does not flip overall to red — RC + coaching keep
        # working without it. Cap the bridge contribution at yellow so a
        # dead bridge auto-flow doesn't drown out actual RC/vision down
        # signals.
        bridge_status = (rollup.get("bridge") or {}).get("status")
        bridge_degraded = bridge_status in ("yellow", "red")
        if not rc_ok or not vis_ok:
            rollup["status"] = "red"
        elif (not cost_ok
              or not ds_ok
              or rollup.get("cost", {}).get("banner") == "warn"
              or bridge_degraded):
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


def _serve_ds_preview_post(h, payload) -> None:
    """POST {champion, mode, level?, items?} → DS rank_for() top picks.
    Used by the champ-select overlay to show DS-computed build recommendations
    with item icons before the game starts."""
    try:
        from core.daemon_slayer_client import rank_for
        champion = str(payload.get("champion") or "").strip()
        if not champion:
            h._send(400, json.dumps({"error": "champion required"}).encode(), "application/json")
            return
        mode = str(payload.get("mode") or "SR").upper()
        level = int(payload.get("level") or 6)
        level = max(1, min(18, level))
        items = [str(i) for i in (payload.get("items") or []) if i]
        rows = rank_for(champion=champion, level=level, item_ids=items,
                        mode=mode, top=8, sort_by="delta", timeout=2.0)
        if rows is None:
            h._send(503, json.dumps({"ok": False, "error": "DS engine unavailable"}).encode(),
                    "application/json")
            return
        result = [{"item_id": r.item_id, "item_name": r.item_name,
                   "delta_dps": round(r.delta_dps, 1), "gold": r.gold}
                  for r in rows]
        h._send(200, json.dumps({"ok": True, "ranked": result}).encode(), "application/json")
    except Exception as exc:
        log.warning("ds-preview: %s", exc)
        h._send(500, json.dumps({"error": str(exc)}).encode(), "application/json")


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
    (equals("/api/state-stream"),  _serve_state_stream),
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
    (equals("/api/ds-preview"),     _serve_ds_preview_post),
]

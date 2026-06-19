"""State / health / version routes.

Slice 2C (2026-05-01): handlers carved out of web_dashboard._Handler.
Group 2 - state-shaped GETs that the dashboard polls frequently.

Each route receives the BaseHTTPRequestHandler (`h`) as its sole
argument and uses `h._send(code, body, ctype)` to write the response.
Module-level GET_ROUTES is consumed by `dashboard._dispatch`.
"""
import hashlib
import json
from dashboard._errors import send_error
import logging
import os
import threading
import time
import urllib.request

from dashboard._bridge_log import gamepc_result_age_s
from dashboard._context import APP_DIR, read_json
from dashboard._dispatch import equals, prefix
from dashboard._state_builder import build_state
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

# Peer bridge health-publisher staleness (Audit7 H-01, 2026-05-18).
# Each peer POSTs its watcher heartbeat ~every 60s to /api/health/peer.
# WARN (300s = 5 missed posts) preserves the prior hardcoded `stale`
# boundary; ALERT (1800s = 30 min silent) is "publisher almost
# certainly dead while the bridge task loop may still be alive" - the
# false-confidence shape the audit flagged. <=WARN green, <=ALERT
# yellow, >ALERT red.
_PEER_HEALTH_WARN_S = 300
_PEER_HEALTH_ALERT_S = 1800


def _peer_health_status(age_s: float) -> str:
    """Graded peer health-publisher status from heartbeat age (seconds).
    <=WARN green * <=ALERT yellow * >ALERT red. Pure - unit-tested."""
    if age_s <= _PEER_HEALTH_WARN_S:
        return "green"
    if age_s <= _PEER_HEALTH_ALERT_S:
        return "yellow"
    return "red"

log = logging.getLogger("rc.web_dashboard")


# /api/state cache - populated lazily on first hit; declared at module
# scope so the request handler can rebind it. 1.0 s TTL absorbs
# high-frequency dashboard polls (5+ tabs polling tightly would
# otherwise duplicate the vision-relay round-trip in _build_state).
_STATE_CACHE_PAYLOAD: bytes | None = None
_STATE_CACHE_TS: float = 0.0

# S7 instrumentation (2026-06-10, operator report "champ select updates
# slow"): a build_state() that creeps past the SSE tick stretches every
# update the dashboard sees, but nothing logged the cost. One WARN per
# slow build (rare by construction) names the phase so the next slow
# champ select self-diagnoses from the log.
_SLOW_BUILD_WARN_S = 0.25


def _timed_build_state() -> dict:
    t0 = time.monotonic()
    state = build_state()
    elapsed = time.monotonic() - t0
    if elapsed >= _SLOW_BUILD_WARN_S:
        phase = ""
        try:
            phase = (state.get("lcu") or {}).get("phase") or ""
        except Exception:  # noqa: BLE001
            pass
        log.warning("state-build slow: %dms phase=%s",
                    int(elapsed * 1000), phase or "?")
    return state


def _state_payload_cached() -> bytes:
    """Serialized /api/state payload behind the shared 1.0s TTL cache.

    Cycle-8 audit (slice B): previously only _serve_state used the TTL
    cache while every SSE subscriber re-ran a full build_state() per 1s
    tick - N tabs duplicated the LCU/liveclient round-trips + the
    deterministic compute N times per second. Both paths share this
    helper now; the SSE tick (1.0s) equals the TTL so freshness is
    unchanged. Unlocked on purpose: a concurrent rebuild is benign
    (last-write-wins, both payloads valid) and cheaper than serializing
    the hot path. Raises on build failure - callers keep their own
    degradation (500 for /api/state, "{}" event for SSE)."""
    global _STATE_CACHE_PAYLOAD, _STATE_CACHE_TS
    now = time.time()
    if _STATE_CACHE_PAYLOAD is not None and (now - _STATE_CACHE_TS) < 1.0:
        return _STATE_CACHE_PAYLOAD
    payload = json.dumps(_timed_build_state()).encode("utf-8")
    _STATE_CACHE_PAYLOAD = payload
    _STATE_CACHE_TS = now
    return payload


def _serve_state(h) -> None:
    try:
        payload = _state_payload_cached()
        h._send(200, payload, "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/state: %s", exc)
        h._send(500, b'{"error":"state_build_failed"}', "application/json")


# /api/state-stream SSE - Tier 4 #16 (2026-05-01). Pushes /api/state
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
    """Long-lived SSE response. Streams /api/state payloads as `data: ...\\n\\n`
    events whenever the JSON hash changes, plus a periodic heartbeat so a
    dead connection drops within ~15s instead of accumulating silently."""
    global _sse_count
    with _sse_count_lock:
        if _sse_count >= _SSE_MAX_SUBSCRIBERS:
            h._send(503, b'{"error":"too_many_subscribers"}', "application/json")
            return
        _sse_count += 1
    try:
        # Send the SSE response headers manually - `_send` sets a
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
        except Exception:  # noqa: BLE001
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
            # Cycle-8 audit (slice B): go through the shared 1.0s TTL
            # payload cache so N subscribers + the HTTP poller dedupe to
            # one build_state() per second instead of N+1.
            try:
                payload = _state_payload_cached()
            except Exception as exc:  # noqa: BLE001
                log.warning("state-stream build: %s", exc)
                payload = b"{}"
            ph = hashlib.md5(payload).digest()
            now = time.time()
            if ph != last_hash or (now - last_emit) >= _SSE_HEARTBEAT_S:
                line = b"data: " + payload + b"\n\n"
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


def _serve_health(h) -> None:
    d = read_json("ops/runtime/health.json")
    # AUDIT 2026-04-28: stamp the canonical RC app version.
    try:
        from core.version import version_string as _vs
        d["rc_version"] = _vs()
    except Exception:  # noqa: BLE001
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
        except Exception as e:  # noqa: BLE001
            rollup["vision"] = {"alive": False, "error": str(e)[:120]}
        try:
            with urllib.request.urlopen("http://127.0.0.1:8893/health", timeout=2) as r:
                ds_data = json.loads(r.read())
                rollup["daemon_slayer"] = {**ds_data, "alive": ds_data.get("status") == "ok"}
        except Exception as e:  # noqa: BLE001
            rollup["daemon_slayer"] = {"alive": False, "error": str(e)[:120]}
        try:
            sup = read_json("ops/runtime/supervisor.pid")
            # AUDIT 2026-04-29: also surface oslock state - when the
            # .oslock sidecar exists, the OS-level msvcrt byte-range
            # lock is held by the supervisor process.
            oslock_path = APP_DIR / "ops" / "runtime" / "supervisor.pid.oslock"
            rollup["supervisor"] = {
                "pid":       sup.get("pid"),
                "run_id":    sup.get("run_id"),
                "locked_at": sup.get("locked_at"),
                "oslock_present": oslock_path.exists(),
            }
        except Exception as e:  # noqa: BLE001
            rollup["supervisor"] = {"error": str(e)[:120]}
        try:
            from core.version import version_string as _vs
            rollup["rc_version"] = _vs()
        except Exception:  # noqa: BLE001
            rollup["rc_version"] = ""
        try:
            from core.cost_tracker import get_tracker as _gt
            rollup["cost"] = {"banner": _gt().banner_state(),
                              "today_usd": _gt().daily_spend().get("total_usd", 0.0)}
        except Exception as e:  # noqa: BLE001
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
            # gamepc_result_age_s only tracks kind=result + source=gamepc
            # entries, NOT generic bridge activity. Prior schema exposed
            # this as bridge.age_s which was misleading; renamed to
            # bridge.gamepc_result_age_s 2026-05-20. legion_daemon block
            # surfaces the new Legion-side autonomous /process-bridge-tasks
            # sentinel (tools/legion_bridge_daemon.py) symmetrically.
            bridge_block = {
                "gamepc_result_age_s": round(age, 1) if age is not None else None,
                "status":              bridge_status,
                "warn_s":              _BRIDGE_WARN_S,
                "alert_s":             _BRIDGE_ALERT_S,
            }
            ld_path = APP_DIR / "ops" / "runtime" / "legion_bridge_daemon_health.json"
            if ld_path.exists():
                try:
                    ld = json.loads(ld_path.read_text(encoding="utf-8"))
                    last_check = ld.get("last_check_ts") or 0
                    bridge_block["legion_daemon"] = {
                        "status":                  ld.get("status"),
                        "pid":                     ld.get("pid"),
                        "invocations_since_boot":  ld.get("invocations_since_boot"),
                        "last_task_ts":            ld.get("last_task_ts"),
                        "last_check_age_s":        round(max(0.0, time.time() - last_check), 1) if last_check else None,
                    }
                except Exception as _e:  # noqa: BLE001
                    bridge_block["legion_daemon"] = {"error": str(_e)[:120]}
            else:
                bridge_block["legion_daemon"] = {"status": "no_data"}
            rollup["bridge"] = bridge_block
        except Exception as e:  # noqa: BLE001
            rollup["bridge"] = {"error": str(e)[:120], "status": "unknown"}
        # (2026-05-03) Peer bridge_watcher heartbeats - published by the
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
                peer_status = _peer_health_status(age_s)
                peers[node] = {
                    "age_s":          round(age_s, 1),
                    "stale":          age_s > _PEER_HEALTH_WARN_S,
                    "status":         peer_status,
                    "watcher_alive":  bool(hb.get("alive")),
                    "watcher_pid":    hb.get("pid"),
                    "queue_depth":    hb.get("queue_depth"),
                    "auto_ok":        hb.get("auto_ok_since_boot"),
                    "auto_err":       hb.get("auto_err_since_boot"),
                    "escalations":    hb.get("escalations_since_boot"),
                    "tokens_today_usd": hb.get("tokens_used_today_usd"),
                }
            rollup["peers"] = peers
        except Exception as e:  # noqa: BLE001
            rollup["peers"] = {"error": str(e)[:120]}
        rc_ok = bool(rollup.get("rc", {}).get("alive"))
        vis_ok = bool(rollup.get("vision", {}).get("alive"))
        ds_ok = bool(rollup.get("daemon_slayer", {}).get("alive"))
        cost_ok = rollup.get("cost", {}).get("banner") != "over"
        # Bridge silence does not flip overall to red - RC + coaching keep
        # working without it. Cap the bridge contribution at yellow so a
        # dead bridge auto-flow doesn't drown out actual RC/vision down
        # signals.
        bridge_status = (rollup.get("bridge") or {}).get("status")
        bridge_degraded = bridge_status in ("yellow", "red")
        # Audit7 H-01: a stale peer health-publisher is an observability
        # gap, not an RC outage - cap at yellow (same philosophy as
        # bridge silence) so the primary top-right dot flips instead of
        # staying falsely green while a publisher is dead for hours.
        peers_block = rollup.get("peers") or {}
        peer_degraded = any(
            isinstance(v, dict) and v.get("status") in ("yellow", "red")
            for v in peers_block.values()
        )
        if not rc_ok or not vis_ok:
            rollup["status"] = "red"
        elif (not cost_ok
              or not ds_ok
              or rollup.get("cost", {}).get("banner") == "warn"
              or bridge_degraded
              or peer_degraded):
            rollup["status"] = "yellow"
        else:
            rollup["status"] = "green"
        h._send(200, json.dumps(rollup).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/health/all: %s", exc)
        send_error(h, exc)


def _serve_ui_version(h) -> None:
    # Auto-reload signal: hash the mtimes of the css/js/html we serve
    # from web/. Dashboard polls and reloads when the hash changes.
    #
    # s171.8: defer to dashboard._static.compute_asset_hash so the
    # auto-reload poller agrees with inject_asset_hash on what counts
    # as a watched asset. The previous 4-file allow-list silently
    # excluded js/main.js + js/panels/* + css/panels/*, which meant
    # edits to ESM panel modules and per-panel CSS never triggered
    # the auto-reload - operator's browser served stale champ_select.js
    # through the entire s164 -> s171.7 window.
    try:
        from dashboard._static import compute_asset_hash
        digest = compute_asset_hash()
        h._send(200, json.dumps({"v": digest}).encode(), "application/json")
    except Exception as exc:  # noqa: BLE001
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(), "application/json")


def _serve_asset_stamp(h) -> None:
    # 2026-04-30: hot-reload signal. Returns the max mtime across the
    # dashboard's static assets so a tiny client poller can detect file
    # changes and refresh without the user alt-tabbing to hit Ctrl+F5.
    try:
        root = APP_DIR / "web"
        files = ["index.html", "css/dashboard.css", "js/main.js"]
        stamp = max(os.path.getmtime(root / f) for f in files
                    if (root / f).exists())
        h._send(200, json.dumps({"mtime": stamp}).encode(),
                "application/json")
    except Exception as exc:  # noqa: BLE001
        log.debug("asset-stamp: %s", exc)
        h._send(200, b'{"mtime":0}', "application/json")


# -- POST handlers (slice 2C-7a) --------------------------------------


def _serve_input_post(h, payload) -> None:
    text = (payload.get("text") or "").strip()
    if not text:
        h._send(400, b'{"error":"empty_text"}', "application/json"); return
    try:
        set_pregame(text)
        log.info("dashboard input: %d chars accepted", len(text))
        h._send(200, b'{"ok":true}', "application/json")
    except Exception as exc:  # noqa: BLE001
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
        elif cmd == "screen_read":
            # s240: on-demand VLM coach. Non-blocking - writes a pending
            # marker + spawns the Sonnet pass on a daemon thread; the
            # result lands on /api/state.screen_read for the dashboard
            # pill. In-flight dedupe lives in trigger_screen_read().
            from dashboard._screen_read import trigger_screen_read
            trigger_screen_read()
        else:
            h._send(400, b'{"error":"unknown_command"}', "application/json"); return
        log.info("dashboard command: %s", cmd)
        h._send(200, b'{"ok":true}', "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/command %s: %s", cmd, exc)
        h._send(500, b'{"error":"command_failed"}', "application/json")


# /api/console-error server-side throttle (10 Hz cap, all clients combined).
# Migrated from web_dashboard._CE_LAST_TS/_CE_DROPPED in slice 2C-7a - nothing
# outside this handler reads the counters.
_CE_LAST_TS: float = 0.0
_CE_DROPPED: int   = 0


def _serve_ds_preview_post(h, payload) -> None:
    """POST {champion, mode, level?, items?, archetype?} -> DS top picks.
    Used by the champ-select overlay + in-game active-match panel.

    s171.4 (2026-05-12): in-game requests now pull live enemy itemization
    from the liveclient relay and compute target_armor / target_mr /
    target_max_hp from those items. Previously the DS rank used a fixed
    armor=0 / mr=0 / hp=0 baseline, so picks didn't shift when enemies
    bought defensive items (operator complaint: "DS dps increase items
    were always the same"). The fallback is the s170 mode/level scaled
    curve from compute_enemy_stats - used for champ-select (no game
    yet) and when the relay is unreachable.

    s182 (2026-05-13): routes through rank_for_primary_archetype() so the
    scorer matches the operator's chosen archetype. Optional ``archetype``
    field in the payload overrides the persisted pick (CS picker UI uses
    it for hover preview without committing). Response gains ``scorer`` +
    ``archetype`` siblings so the dashboard can label the unit correctly.
    """
    try:
        from core.daemon_slayer_client import rank_for_primary_archetype
        from core.archetype_picks import canonical_champion_id, get_archetype_for
        champion = str(payload.get("champion") or "").strip()
        if not champion:
            h._send(400, json.dumps({"error": "champion required"}).encode(), "application/json")
            return
        # 2026-06-10: the active-match panel sends the coach payload's
        # champion verbatim - a Live Client DISPLAY name ("Tahm Kench").
        # DS registries key canonical DDragon ids; without the bridge the
        # rank silently 0.0-misses every multi-word champion. Canonical
        # ids (champ-select callers) pass through unchanged.
        champion = canonical_champion_id(champion) or champion
        mode = str(payload.get("mode") or "SR").upper()
        level = int(payload.get("level") or 6)
        level = max(1, min(18, level))
        items = [str(i) for i in (payload.get("items") or []) if i]

        # s182: caller override wins; otherwise resolve from the persisted
        # pick (or DDragon-tag default). Empty string -> falls through to
        # carry inside the dispatcher.
        archetype = str(payload.get("archetype") or "").strip().lower()
        if not archetype:
            archetype = (get_archetype_for(champion).get("primary") or "carry").lower()

        # s171.4: derive target stats from live enemy items when possible.
        # Fallback to mode/level curve. Override path: caller passed
        # explicit target_* fields in body (used by champ-select preview).
        tgt = _resolve_ds_target_stats(payload, mode=mode, level=level)

        out = rank_for_primary_archetype(
            champion=champion, archetype=archetype, level=level,
            item_ids=items, mode=mode, top=8, sort_by="delta", timeout=2.0,
            target_armor=tgt["target_armor"],
            target_mr=tgt["target_mr"],
            target_max_hp=tgt["target_max_hp"],
            target_bonus_hp=tgt["target_bonus_hp"],
        )
        if out is None:
            h._send(503, json.dumps({"ok": False, "error": "DS engine unavailable"}).encode(),
                    "application/json")
            return
        scorer = str(out.get("scorer") or "dps")
        ranked_in = list(out.get("ranked") or [])

        def _delta(row: dict) -> float:
            # Bruiser's hybrid scorer surfaces three separate fields; for
            # the dashboard's existing "+Ndps" tile we display the
            # hybrid_delta_pct as a percentage. All other scorers ship a
            # unified `delta` key (carry: delta_dps; tank: delta_ehp;
            # mage: delta_ability_dps; assassin: delta_burst; enchanter:
            # delta_hps). Falls back to delta_dps for legacy compatibility.
            if scorer == "hybrid":
                return float(row.get("hybrid_delta_pct", 0.0)) * 100.0
            return float(row.get("delta", row.get("delta_dps", 0.0)))

        # s183: stamp `scorer` per-row so the dashboard's build chooser
        # (which caches just the rows, not the response envelope) can map
        # each row's delta to the correct unit suffix. Mirrors the
        # `display_rows` shape from coach_integration.archetype_dispatch.
        result = [{"item_id": r.get("item_id", ""),
                   "item_name": r.get("item_name", ""),
                   "delta_dps": round(_delta(r), 1),
                   "gold": int(r.get("gold", 0) or 0),
                   "scorer": scorer}
                  for r in ranked_in]
        # s171.6: defensive-pick ranker. Computes the enemy team's
        # threat profile (AD/AP/burst/tank) and recommends defensive
        # items keyed to the threat. Cheap - pure stat math, no
        # network. Skipped when no enemy champions resolvable.
        threat = None
        defensive = []
        try:
            from core.defensive_picks import (
                compute_threat_profile, recommend_defensive_items,
            )
            enemy_names = _resolve_enemy_champions(payload)
            if enemy_names:
                threat = compute_threat_profile(enemy_names, enemy_items=None)
                defensive = recommend_defensive_items(
                    threat, my_champion=champion,
                    my_owned_items=items, top_n=4,
                )
        except Exception as exc:  # noqa: BLE001
            log.debug("ds-preview defensive resolve: %s", exc)
        h._send(200, json.dumps({
            "ok": True, "ranked": result,
            "scorer":       scorer,
            "archetype":    archetype,
            "target_stats": tgt,
            "threat":       threat,
            "defensive":    defensive,
        }).encode(), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("ds-preview: %s", exc)
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(), "application/json")


def _resolve_enemy_champions(payload: dict) -> list:
    """Resolve enemy champion names for the defensive-pick ranker.
    Priority:
      1. payload["enemies"] - explicit list of names (champ-select
         what-if exploration).
      2. live liveclient relay - pull non-active-team champion names
         from data.allPlayers[i].championName.
      3. empty list (skip the defensive ranker).
    """
    explicit = payload.get("enemies") or payload.get("enemy_champions")
    if isinstance(explicit, list) and explicit:
        return [str(x) for x in explicit if x]
    try:
        from core.enemy_aware_stats import active_player_team
        from core.liveclient_cache import get as _lc_get
        snap = _lc_get()
        if snap.data is None or snap.age_s >= 8.0:
            return []
        my_team = active_player_team(snap.data)
        if not my_team:
            return []
        players = (snap.data or {}).get("allPlayers") or []
        return [str(p.get("championName") or "")
                for p in players
                if isinstance(p, dict)
                and p.get("team") != my_team
                and p.get("championName")]
    except Exception as exc:  # noqa: BLE001
        log.debug("_resolve_enemy_champions: %s", exc)
        return []


def _enemy_champions_for_target(liveclient_data: dict, exclude_team) -> list:
    """Enemy champion names positionally aligned with
    ``enemy_aware_stats.enemy_items_from_liveclient``.

    MUST mirror that function's player iteration exactly so
    ``enemy_champions[i]`` is the champion whose items are
    ``enemy_items[i]``: same ``allPlayers`` order, skip non-dict, skip
    ``exclude_team``, one entry per remaining player. A missing
    ``championName`` yields ``""`` (the base layer treats unknown as
    zero base, degrading to item-only for that one enemy).
    """
    if not isinstance(liveclient_data, dict):
        return []
    out: list = []
    for p in (liveclient_data.get("allPlayers") or []):
        if not isinstance(p, dict):
            continue
        if exclude_team and p.get("team") == exclude_team:
            continue
        out.append(str(p.get("championName") or ""))
    return out


def _resolve_ds_target_stats(payload: dict, mode: str, level: int) -> dict:
    """Pick the right target_armor / target_mr / target_max_hp source.

    Priority:
      1. Explicit ``target_armor`` / ``target_mr`` / etc. in the request
         body - caller has pre-computed (e.g. champ-select preview with
         a synthetic profile).
      2. Live enemy items from the liveclient relay (in-game).
      3. ``compute_enemy_stats(mode, level)`` mode/level scaled curve
         (s170) - used when no live data + no explicit overrides.

    Returns a dict with the 4 target_* float fields plus diagnostic
    ``source`` / ``n_enemies`` / ``aggregator`` keys for the caller's
    debug payload.
    """
    # Path 1: explicit override.
    if any(k in payload for k in
           ("target_armor", "target_mr", "target_max_hp", "target_bonus_hp")):
        # P1-L21: coerce defensively. The bare ``float(... or 0.0)`` form
        # handled None / 0 / "" but raised ValueError on a non-numeric
        # string (a malformed champ-select synthetic profile would 500
        # the whole /api/ds-preview + /api/build-order call). A garbage
        # override degrades to a sane 0.0 for that field instead - the
        # same graceful-degrade contract paths 2 and 3 already honor.
        def _f(key: str) -> float:
            try:
                return float(payload.get(key) or 0.0)
            except (TypeError, ValueError):
                return 0.0
        return {
            "target_armor":    _f("target_armor"),
            "target_mr":       _f("target_mr"),
            "target_max_hp":   _f("target_max_hp"),
            "target_bonus_hp": _f("target_bonus_hp"),
            "n_enemies":       0,
            "source":          "explicit-override",
            "aggregator":      "-",
        }
    # Path 2: live enemy items from the relay.
    try:
        from core.enemy_aware_stats import (
            compute_target_stats_from_items, enemy_items_from_liveclient,
            active_player_team,
        )
        from core.liveclient_cache import get as _lc_get
        snap = _lc_get()
        if snap.data is not None and snap.age_s < 8.0:
            my_team = active_player_team(snap.data)
            enemy_team = "ORDER" if my_team == "CHAOS" else ("CHAOS" if my_team == "ORDER" else None)
            # ``enemy_items_from_liveclient(data, exclude_team=my_team)``
            # filters to opponents.
            enemy_items = enemy_items_from_liveclient(snap.data, exclude_team=my_team)
            if enemy_items:
                # P1-L4 fix: pass the enemy champions + level so the
                # champion base resist/HP-by-level is added (the engine
                # treats target_* as absolute, not an item-only delta).
                # _enemy_champions_for_target aligns names positionally
                # with enemy_items (same exclude_team filter + slot
                # order); a name-resolution miss degrades to item-only
                # for that enemy, never raises.
                enemy_champs = _enemy_champions_for_target(snap.data, my_team)
                stats = compute_target_stats_from_items(
                    enemy_items, aggregator="avg",
                    enemy_champions=enemy_champs or None,
                    level=int(level) if enemy_champs else None,
                )
                if stats.get("n_enemies", 0) > 0:
                    return stats
    except Exception as exc:  # noqa: BLE001
        log.debug("ds-preview live-enemy-items resolve: %s", exc)

    # Path 3: fallback to compute_enemy_stats curve.
    try:
        from coach_integration.enemy_stats import compute_enemy_stats
        es = compute_enemy_stats(mode=mode.lower(), level=int(level))
        return {
            "target_armor":    float(getattr(es, "armor",    0.0) or 0.0),
            "target_mr":       float(getattr(es, "mr",       0.0) or 0.0),
            "target_max_hp":   float(getattr(es, "max_hp",   0.0) or 0.0),
            "target_bonus_hp": float(getattr(es, "bonus_hp", 0.0) or 0.0),
            "n_enemies":       0,
            "source":          "mode-level-curve",
            "aggregator":      "-",
        }
    except Exception as exc:  # noqa: BLE001
        log.debug("ds-preview mode-level-curve resolve: %s", exc)

    # Last resort.
    return {
        "target_armor": 0.0, "target_mr": 0.0,
        "target_max_hp": 0.0, "target_bonus_hp": 0.0,
        "n_enemies": 0, "source": "default-zero", "aggregator": "-",
    }


def _serve_analyze_post(h, payload) -> None:
    # Dashboard's "Analyze Now" button - forward POST to the supervisor
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
    except Exception as exc:  # noqa: BLE001
        log.warning("api/analyze: %s", exc)
        send_error(h, exc)


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
    except Exception as exc:  # noqa: BLE001
        send_error(h, exc)


def _serve_build_order_post(h, payload) -> None:
    """POST {champion, mode, level?, items?, archetype?, slots?, enemies?}
    -> a contextual, match-specific ORDERED build.

    Sibling of /api/ds-preview but returns a *sequence* instead of a flat
    ranked list: core.build_order.plan_build_order iterates the same
    per-archetype scorer, appending each pick so later slots re-rank
    against the accumulated build + enemy context. The unique-passive
    no-double rule (Trinity Force + Essence Reaver invalid together;
    also lifeline / immolate families) is enforced engine-side via the
    iterate-with-accumulated-item_ids design - no two same-passive items
    can appear in the order. Read-only; the UI seam the dashboard build
    chooser will consume.
    """
    try:
        from core.archetype_picks import get_archetype_for
        from core.build_order import plan_build_order

        champion = str(payload.get("champion") or "").strip()
        if not champion:
            h._send(400, json.dumps({"error": "champion required"}).encode(),
                     "application/json")
            return
        mode = str(payload.get("mode") or "SR").upper()
        level = max(1, min(18, int(payload.get("level") or 11)))
        items = [str(i) for i in (payload.get("items") or []) if i]
        slots = max(1, min(6, int(payload.get("slots") or 6)))

        archetype = str(payload.get("archetype") or "").strip().lower()
        if not archetype:
            archetype = (get_archetype_for(champion).get("primary") or "carry").lower()

        tgt = _resolve_ds_target_stats(payload, mode=mode, level=level)

        res = plan_build_order(
            champion, archetype, level=level, owned_item_ids=items,
            mode=mode, slots=slots, timeout=2.0,
            target_armor=tgt["target_armor"],
            target_mr=tgt["target_mr"],
            target_max_hp=tgt["target_max_hp"],
            target_bonus_hp=tgt["target_bonus_hp"],
        )
        if res is None:
            h._send(503, json.dumps(
                {"ok": False, "error": "DS engine unavailable"}).encode(),
                "application/json")
            return
        out = res.to_dict()
        out["ok"] = True
        out["target_stats"] = tgt
        h._send(200, json.dumps(out).encode(), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("build-order: %s", exc)
        send_error(h, exc)


# -- route table ------------------------------------------------------

# The /api/ui-version handler uses prefix() because the legacy do_GET
# used `startswith`.
GET_ROUTES = [
    (equals("/api/state"),         _serve_state),
    (equals("/api/state-stream"),  _serve_state_stream),
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
    (equals("/api/build-order"),    _serve_build_order_post),
]

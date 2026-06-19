# arch: bridge watcher daemon - classify -> action loop | section=bridge | frozen=no
"""bridge_watcher.py - silent cross-Claude bridge poller (MVP).

Phase 0 per BRIDGE_WATCHER_PLAN.md S11:
  - Polls /api/bridge every 15s (configurable)
  - Classifies each new envelope via bridge_watcher_classify.classify()
  - Escalates work to ops/runtime/bridge_inbox_pending.json
  - Logs ack-only items
  - Writes heartbeat to ops/runtime/bridge_watcher_health.json
  - Dedupes by envelope id (or composite ts+source when id absent)

NOT in scope for MVP (later phases):
  - Auto-action lane (claude --print spawning)
  - Per-node config file
  - Push notifications
  - Token cap enforcement

Operator drains escalations via the existing /process-bridge-tasks
slash command. Watcher does NOT post results to the bridge - that
remains the operator's job (or Phase 2 auto-action's).

Run via:
  C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/bridge_watcher.py --node legion          # foreground
  C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/bridge_watcher.py --node legion --poll 15
  pythonw tools/bridge_watcher.py --node legion     # via scheduled task

Stop with: ctrl+C (foreground) or taskkill (scheduled-task pid).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# Allow `from bridge_watcher_classify import ...` when launched directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bridge_watcher_classify import classify  # noqa: E402
import bridge_watcher_actions as _actions  # noqa: E402
import bridge_watcher_history as _history  # noqa: E402

# Path defaults assume the canonical Legion layout (script at <root>/tools/...).
# Phase 1 nodes (Game-PC at C:\RC-Agent\, Peer at <peer-repo>/tools/) override
# via --data-dir / --log-dir on the install scheduled task.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "ops" / "runtime"
_DEFAULT_LOG_DIR  = _PROJECT_ROOT / "logs"
_DEFAULT_TOOLS_DIR = Path(__file__).resolve().parent
_DEFAULT_API_KEY_PATH = _PROJECT_ROOT / "API-Key-Claude.txt"

# These are reset in main() once --data-dir / --log-dir are parsed.
_HEALTH_PATH:  Path = _DEFAULT_DATA_DIR / "bridge_watcher_health.json"
_PENDING_PATH: Path = _DEFAULT_DATA_DIR / "bridge_inbox_pending.json"
_STATE_PATH:   Path = _DEFAULT_DATA_DIR / "bridge_watcher_state.json"
_PID_PATH:     Path = _DEFAULT_DATA_DIR / "bridge_watcher.pid"
_LOG_DIR:      Path = _DEFAULT_LOG_DIR
_ARTIFACTS_DIR: Path = _DEFAULT_DATA_DIR / "bridge_action_artifacts"
_ACTION_PROMPT: Path = _DEFAULT_TOOLS_DIR / "bridge_watcher_action_prompt.md"
_CONFIG_PATH:   Path = _DEFAULT_TOOLS_DIR / "bridge_watcher_config.json"
_HISTORY_DB:    Path = _DEFAULT_DATA_DIR / "bridge_action_history.db"
_MODE_PATH:     Path = _DEFAULT_DATA_DIR / "bridge_watcher_mode.json"

_DEFAULT_POLL_S = 15.0
_DEFAULT_LOOKBACK_S = 86400  # 24h
_PENDING_TTL_S = 86400       # 24h before a pending entry auto-expires
_SLEEP_POLL_S  = 300         # poll interval when mode=sleep or auto-idle
_AUTO_IDLE_S   = 900         # seconds without kind=task before auto drops to sleep
_ARTIFACT_RETENTION_S = 7 * 86400  # delete artifacts older than 7 days

# RC health checks (node-load restraint for auto-action lanes).
# Only relevant on nodes where RC runs (legion). On game-pc/peer the file
# won't exist and _check_rc_health returns (False, "") - no suppression.
_RC_HEALTH_PATH     = _PROJECT_ROOT / "ops" / "runtime" / "health.json"
_RC_HEALTH_STALE_S  = 60    # suppress if RC heartbeat is older than this
_RC_RESTART_GRACE_S = 120   # suppress for this many seconds after RC PID started

# Default bridge URL per node. Phase 1 nodes can override via --bridge-url.
#   legion : own loopback (RC dashboard hosts the bridge log)
#   gamepc : Legion's bridge (Game-PC has no local dashboard; bridge_pull_tasks.py
#            uses the same URL with target filter)
#   peer    : own loopback (Peer dashboard hosts its own bridge log)
_DEFAULT_BRIDGE_URL = {
    "legion": "https://127.0.0.1:8888/api/bridge",
    "gamepc": "https://legion-rc:8888/api/bridge",
    # Peer serves /api/bridge/messages (NOT bare /api/bridge - confirmed by
    # Peer 2026-05-03 install probe). Their response is a bare JSON list;
    # _fetch_since handles both shapes.
    "peer":    "https://127.0.0.1:8888/api/bridge/messages",
}
_MAX_PROMPT_LEN = 32 * 1024  # 32 KiB cap on prompt body before truncation

_log = logging.getLogger("rc.bridge_watcher")


def _watchdog_threshold(eff_poll_s: float) -> float:
    """Min seconds of main-loop silence before watchdog calls os._exit(1)."""
    return max(120.0, eff_poll_s * 3)


def _check_rc_health(health: dict, now: float) -> tuple:
    """Return (degraded: bool, reason: str) from a parsed RC health.json dict.

    degraded=True suppresses auto-action lanes for one poll cycle so the
    watcher doesn't compete for resources during RC incidents.

    Returns (False, '') when health is empty (no RC on this node - game-pc/peer)
    so those nodes are never suppressed by this check.
    """
    if not health:
        return False, ""
    if not health.get("alive"):
        return True, "RC alive=False"
    if not health.get("last_reload_ok"):
        err = (health.get("last_reload_error") or "?")
        return True, f"RC last_reload_ok=False (error={err!r})"
    if health.get("booting"):
        return True, "RC booting=True"
    # Stale heartbeat - RC may be hung.
    updated_str = health.get("updated_at") or ""
    if updated_str:
        try:
            import datetime as _dt
            ts = _dt.datetime.fromisoformat(
                updated_str.replace("Z", "+00:00")).timestamp()
            age = now - ts
            if age > _RC_HEALTH_STALE_S:
                return True, (f"RC heartbeat stale {age:.0f}s "
                              f"(threshold={_RC_HEALTH_STALE_S}s)")
        except Exception:  # noqa: BLE001
            pass
    # Recent restart - give RC time to stabilize.
    started_str = health.get("started_at") or ""
    if started_str:
        try:
            import datetime as _dt
            ts = _dt.datetime.fromisoformat(
                started_str.replace("Z", "+00:00")).timestamp()
            age = now - ts
            if age < _RC_RESTART_GRACE_S:
                return True, (f"RC restarted {age:.0f}s ago "
                              f"(grace={_RC_RESTART_GRACE_S}s)")
        except Exception:  # noqa: BLE001
            pass
    return False, ""

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# -- Atomic-write helper (mirrors core.bridge_monitor's WinError-5 retry) --


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    # os.replace can transiently raise PermissionError (WinError 5) when a
    # reader has the dst open; brief retries clear it. (Same pattern as
    # core.bridge_monitor._write_atomic - see reference_os_replace_winerror5.)
    last_exc: Exception | None = None
    for delay in (0, 0.025, 0.050, 0.200):
        if delay:
            time.sleep(delay)
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last_exc = exc
            continue
    if last_exc:
        raise last_exc


def _read_json(path: Path, default: dict) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return dict(default)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else dict(default)
    except json.JSONDecodeError:
        return dict(default)


# -- Sliding 24h event ring --------------------------------------------
# Persisted in _STATE_PATH under "event_ring_24h" so counts survive
# watcher restarts (unlike *_since_boot which reset on restart).

_MAX_RING_SIZE  = 5000   # cap to prevent unbounded growth on high-traffic nodes
_RING_WINDOW_S  = 86400  # 24h sliding window
_PUSH_THROTTLE_S  = 3600  # 1-hour window for push-notif throttle
_PUSH_MAX_PER_HR  = 3     # max push notifications per hour per node


def _ring_add(state: dict, kind: str, now: float) -> None:
    """Append a timestamped event; keep ring bounded."""
    ring = state.setdefault("event_ring_24h", [])
    ring.append({"k": kind, "t": now})
    if len(ring) > _MAX_RING_SIZE:
        state["event_ring_24h"] = ring[-_MAX_RING_SIZE:]


def _ring_age(state: dict, now: float) -> None:
    """Drop entries older than 24h (call once per poll cycle)."""
    ring = state.get("event_ring_24h")
    if ring:
        cutoff = now - _RING_WINDOW_S
        state["event_ring_24h"] = [e for e in ring if e.get("t", 0) >= cutoff]


def _ring_count(state: dict, kind: str, now: float) -> int:
    """Count events of *kind* within the last 24h."""
    cutoff = now - _RING_WINDOW_S
    return sum(1 for e in (state.get("event_ring_24h") or [])
               if e.get("k") == kind and e.get("t", 0) >= cutoff)


def _read_mode() -> str:
    """Read cadence sentinel; return mode or 'active' on missing/invalid file."""
    raw = _read_json(_MODE_PATH, {})
    mode = str(raw.get("mode", "active")).strip().lower()
    return mode if mode in ("active", "sleep", "auto") else "active"


def _push_eligible(state: dict, now: float) -> bool:
    """Return True if throttle allows another push notification."""
    times = state.get("push_notif_times") or []
    recent = [t for t in times if now - t < _PUSH_THROTTLE_S]
    return len(recent) < _PUSH_MAX_PER_HR


def _send_push_notification(summary: str, source: str, node: str,
                              state: dict, now: float,
                              api_key_path: Optional[Path] = None) -> bool:
    """Spawn headless claude --print to deliver a PushNotification.

    Throttled to 3/hr.  Returns True if dispatched.  Silently no-ops if
    no interactive Claude Code session is listening or claude not in PATH.
    """
    if not _push_eligible(state, now):
        _log.debug("push notif throttled (>=%d in last hour)", _PUSH_MAX_PER_HR)
        return False
    msg = f"[bridge-watcher/{node}] new escalation from {source}: {summary}"
    # Use _actions._resolve_claude_executable() instead of bare "claude": on
    # Windows the CLI is claude.cmd (npm shim) and subprocess.run won't
    # auto-append .cmd, so bare "claude" raised WinError 2 ("claude not in
    # PATH?") and push-notif silently failed fleet-wide. Fixed 2026-05-20.
    argv = [
        _actions._resolve_claude_executable(), "--print",
        "--dangerously-skip-permissions",
        "--allowed-tools", "PushNotification",
        "-p", msg,
    ]
    env_vars = dict(os.environ)
    env_vars.pop("ANTHROPIC_API_KEY", None)
    import subprocess
    # Suppress the cmd.exe window flash on Windows when spawning claude.cmd
    # (npm shim). pythonw parent has no console, so spawning a .cmd allocates
    # a new visible console for the duration of the call (~claude --print
    # takes several seconds). Mirrors the flag pattern at
    # tools/legion_bridge_daemon.py:212.
    _flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=20,
            check=False, env=env_vars, creationflags=_flags,
        )
        if proc.returncode != 0:
            _log.warning("push notif failed rc=%d stderr=%s",
                         proc.returncode, (proc.stderr or "")[:200])
            return False
    except (OSError, FileNotFoundError) as exc:
        _log.warning("push notif spawn failed (claude not in PATH?): %s", exc)
        return False
    except Exception as exc:  # subprocess.TimeoutExpired or other  # noqa: BLE001
        _log.warning("push notif error: %s", exc)
        return False
    times = [t for t in (state.get("push_notif_times") or []) if now - t < _PUSH_THROTTLE_S]
    times.append(now)
    state["push_notif_times"] = times
    _log.info("push notif sent node=%s src=%s: %s", node, source, msg[:120])
    return True


# -- PID lock ----------------------------------------------------------


def _pid_lock_acquire(node: str) -> None:
    """Refuse to start if another watcher is already alive on this node.

    Stale lockfiles (process gone) are reclaimed silently.
    """
    _PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _PID_PATH.exists():
        try:
            existing = int(_PID_PATH.read_text(encoding="utf-8").strip())
            # Best-effort liveness check (Windows). signal 0 raises if dead.
            os.kill(existing, 0)
            sys.stderr.write(
                f"bridge_watcher already running for node={node} (pid {existing}); aborting\n")
            raise SystemExit(2)
        except (ValueError, OSError, ProcessLookupError):
            pass  # stale; reclaim
    _PID_PATH.write_text(str(os.getpid()), encoding="utf-8")


def _pid_lock_release() -> None:
    try:
        if _PID_PATH.exists():
            current = _PID_PATH.read_text(encoding="utf-8").strip()
            if current == str(os.getpid()):
                _PID_PATH.unlink()
    except OSError:
        pass


# -- Bridge fetch ------------------------------------------------------


def _fetch_since(since_ts: float, bridge_url: str) -> list[dict]:
    url = f"{bridge_url}?since={since_ts}&limit=100"
    req = urllib.request.Request(url, method="GET",
                                 headers={"User-Agent": "rc-bridge-watcher/0"})
    with urllib.request.urlopen(req, timeout=4.0, context=_SSL_CTX) as r:
        data = json.loads(r.read())
    # Legion/RC returns wrapped {now, messages: [...]}, Peer returns bare list.
    # Per Peer 2026-05-03 install report - handle both shapes defensively.
    if isinstance(data, list):
        msgs = data
    elif isinstance(data, dict):
        msgs = data.get("messages") or []
    else:
        msgs = []
    return [m for m in msgs if isinstance(m, dict)]


# -- Pending queue (escalations) ---------------------------------------


def _envelope_dedupe_key(envelope: dict) -> str:
    eid = envelope.get("id")
    if eid:
        return str(eid)
    # Fall back to composite for envelopes without ids (notes/results).
    return f"{envelope.get('source','?')}::{envelope.get('ts',0):.0f}"


def _expire_old_pending(pending: dict, now: float) -> int:
    """Drop entries whose ttl_at < now. Returns count expired."""
    tasks = pending.get("tasks") or []
    fresh = [t for t in tasks if (t.get("ttl_at") or 0) > now]
    expired = len(tasks) - len(fresh)
    pending["tasks"] = fresh
    return expired


def _expire_stale_claims(pending: dict, now: float, claim_ttl_s: float = 60.0) -> int:
    """Reset claimed_by/claimed_at on entries claimed >claim_ttl_s ago.

    Mirrors S8 claim-lock spec: a worker that crashes shouldn't permanently
    block an entry; claims auto-expire after 60s so /process-bridge-tasks
    can re-pick it up.
    """
    cleared = 0
    for t in pending.get("tasks") or []:
        ca = t.get("claimed_at") or 0
        if t.get("claimed_by") and (now - ca) > claim_ttl_s:
            t["claimed_by"] = None
            t["claimed_at"] = None
            cleared += 1
    return cleared


def _add_to_pending(envelope: dict, reason: str) -> bool:
    """Append envelope to pending queue iff not already present.

    Returns True if newly added, False if already present.
    """
    pending = _read_json(_PENDING_PATH, {"schema_version": 1, "tasks": []})
    if pending.get("schema_version") != 1:
        pending = {"schema_version": 1, "tasks": []}
    tasks = pending.setdefault("tasks", [])
    key = _envelope_dedupe_key(envelope)
    if any(_envelope_dedupe_key(t) == key for t in tasks):
        return False

    now = time.time()
    _expire_old_pending(pending, now)
    _expire_stale_claims(pending, now)

    prompt_body = ""
    body = envelope.get("body") or {}
    if isinstance(body, dict):
        prompt_body = str(body.get("prompt") or "")
    if not prompt_body:
        prompt_body = str(envelope.get("summary") or "")
    if len(prompt_body) > _MAX_PROMPT_LEN:
        prompt_body = prompt_body[:_MAX_PROMPT_LEN] + f"\n\n[truncated; original {len(prompt_body)} chars]"

    tasks.append({
        "task_id":        envelope.get("id"),
        "received_at":    now,
        "from":           envelope.get("source"),
        "kind":           envelope.get("kind"),
        "summary":        (envelope.get("summary") or "")[:240],
        "prompt":         prompt_body,
        "classification": "escalate",
        "reason":         reason,
        "ttl_at":         now + _PENDING_TTL_S,
        "claimed_by":     None,
        "claimed_at":     None,
    })
    pending["updated_at"] = now
    _atomic_write_json(_PENDING_PATH, pending)
    return True


# -- State (last seen ts) ----------------------------------------------


def _load_state() -> dict:
    return _read_json(_STATE_PATH, {
        "last_seen_ts":  0.0,
        "processed_ids": [],
    })


def _save_state(state: dict) -> None:
    # Cap processed_ids to ~5000 entries; oldest dropped FIFO.
    pids = state.get("processed_ids") or []
    if len(pids) > 5000:
        state["processed_ids"] = pids[-5000:]
    _atomic_write_json(_STATE_PATH, state)


# -- Heartbeat ---------------------------------------------------------


def _write_heartbeat(stats: dict) -> None:
    # Counter naming clarity (per Peer 2026-05-03 ask):
    #   queue_depth          : LIVE - current size of bridge_inbox_pending.json
    #   *_since_boot         : MONOTONIC - counts since this watcher process started
    #   tokens_used_today_usd: DAILY - resets at local midnight (only "today" field)
    # Old "*_24h" keys are aliased for one release for any external readers,
    # then removed.
    auto_actions = int(stats.get("auto_actions_since_boot", 0))
    auto_ok      = int(stats.get("auto_ok_since_boot", 0))
    auto_err     = int(stats.get("auto_err_since_boot", 0))
    escalations  = int(stats.get("escalations_since_boot", 0))
    errors       = int(stats.get("errors_since_boot", 0))
    payload = {
        "app":         "bridge-watcher",
        "node":        stats["node"],
        "pid":         os.getpid(),
        "started_at":  stats["started_at"],
        "updated_at":  time.time(),
        "alive":       True,
        "last_poll_ok":   stats["last_poll_ok"],
        "last_poll_at":   stats["last_poll_at"],
        "queue_depth":    stats["queue_depth"],

        # Preferred names - accurate semantics
        "auto_actions_since_boot":    auto_actions,
        "auto_ok_since_boot":         auto_ok,
        "auto_err_since_boot":        auto_err,
        "escalations_since_boot":     escalations,
        "errors_since_boot":          errors,
        "auto_suppressed_since_boot": int(stats.get("auto_suppressed_since_boot", 0)),

        # Sliding 24h-window counts (accurate - backed by persisted timestamp
        # ring in state; no longer aliases for *_since_boot).
        "escalations_24h":     int(stats.get("escalations_24h",     escalations)),
        "auto_ok_24h":         int(stats.get("auto_ok_24h",         auto_ok)),
        "auto_err_24h":        int(stats.get("auto_err_24h",         auto_err)),
        "errors_24h":          int(stats.get("errors_24h",           errors)),
        "auto_actions_24h":    int(stats.get("auto_actions_24h",    auto_actions)),
        "auto_suppressed_24h": int(stats.get("auto_suppressed_24h", 0)),

        "tokens_used_today_usd": stats.get("tokens_used_today_usd", 0.0),

        # Cadence mode (read from sentinel file each poll cycle)
        "cadence_mode":      stats.get("cadence_mode", "active"),
        "effective_poll_s":  stats.get("effective_poll_s", _DEFAULT_POLL_S),

        "dry_run": bool(stats.get("dry_run", False)),
    }
    try:
        _atomic_write_json(_HEALTH_PATH, payload)
    except OSError as exc:
        _log.warning("heartbeat write failed: %s", exc)


# -- Artifact rotation -------------------------------------------------


def _should_remove_artifact(age_s: float, task_id: str, processed_ids: set) -> bool:
    """Pure predicate: True when an artifact file should be deleted."""
    return age_s > _ARTIFACT_RETENTION_S or task_id in processed_ids


def _rotate_artifacts(state: dict, processed_ids: set, now: float) -> int:
    """Delete stale artifacts from bridge_action_artifacts/.

    Runs once per day (gated by last_rotate_at in state).
    Returns count of files removed.
    """
    last = float(state.get("last_rotate_at") or 0)
    if now - last < 86400:
        return 0
    state["last_rotate_at"] = now
    if not _ARTIFACTS_DIR.exists():
        return 0
    removed = 0
    try:
        for p in _ARTIFACTS_DIR.iterdir():
            if not p.is_file():
                continue
            try:
                age = now - p.stat().st_mtime
                if _should_remove_artifact(age, p.stem, processed_ids):
                    p.unlink(missing_ok=True)
                    removed += 1
            except (OSError, PermissionError):
                pass
    except OSError:
        pass
    if removed:
        _log.info("artifact rotation: removed %d stale file(s) from %s", removed, _ARTIFACTS_DIR)
    return removed


# -- Result posting (Phase 2 auto-action result -> bridge_post_result.py) --


def _post_result_back(envelope: dict, *, res_status: str, body: dict, node: str,
                      tools_dir: Optional[Path]) -> None:
    """Invoke bridge_post_result.py to send auto-action result back to peer."""
    task_id = envelope.get("id")
    if not task_id:
        _log.warning("can't post result for envelope without id")
        return
    # bridge_post_result.py constrains --reply-to to {legion, gamepc, peer}.
    # Map source field to one of those, with prefix-match fallback.
    raw_src = (envelope.get("source") or "").strip().lower()
    if raw_src.startswith("legion") or raw_src in ("rc", "rc-monitor"):
        src_field = "legion"
    elif raw_src.startswith("peer") or raw_src == "peer-host":
        src_field = "peer"
    elif raw_src.startswith("gamepc"):
        src_field = "gamepc"
    else:
        _log.warning("post_result: unknown envelope source %r - defaulting to 'peer'", raw_src)
        src_field = "peer"
    exit_code = "0" if res_status == "ok" else "1"
    summary = body.pop("_summary", None) or f"auto-action {res_status} (lane {body.get('_lane','?')})"
    poster = (tools_dir or _DEFAULT_TOOLS_DIR) / "bridge_post_result.py"
    if not poster.exists():
        _log.warning("bridge_post_result.py missing at %s - cannot post result", poster)
        return
    import subprocess
    argv = [
        sys.executable, str(poster), str(task_id),
        "--source", node,
        "--reply-to", str(src_field),
        "--summary", summary[:240],
        "--body", json.dumps(body, ensure_ascii=False),
        "--exit-code", exit_code,
    ]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=15, check=False)
        if proc.returncode != 0:
            _log.warning("bridge_post_result rc=%s stderr=%s",
                         proc.returncode, (proc.stderr or "")[:200])
    except (subprocess.TimeoutExpired, OSError) as exc:
        _log.warning("bridge_post_result spawn failed: %s", exc)


# -- Main loop ---------------------------------------------------------


_STOP = False


def _handle_signal(signum, _frame) -> None:
    global _STOP
    _log.info("received signal %s - stopping", signum)
    _STOP = True


def _run(node: str, poll_s: float, lookback_s: float, bridge_url: str, *,
         once: bool = False,
         dry_run: bool = False,
         enabled_lanes: Optional[set] = None,
         node_config: Optional[dict] = None,
         tools_dir: Optional[Path] = None) -> int:
    enabled_lanes = enabled_lanes or set()
    state = _load_state()
    if not state.get("last_seen_ts"):
        # Cold-boot: anchor at now-lookback_s so we sweep recent history once.
        state["last_seen_ts"] = max(0.0, time.time() - lookback_s)
    _actions.reset_daily_spend_if_new_day(state)

    started_at = time.time()
    # last_task_ts - epoch of last kind=task envelope; determines auto-mode sleep.
    # Default to started_at so a fresh restart begins in active cadence.
    state.setdefault("last_task_ts", started_at)
    processed_ids: set = set(state.get("processed_ids") or [])
    # Counters reset on each watcher process restart (truly *_since_boot).
    stats = {
        "node":                    node,
        "started_at":              started_at,
        "last_poll_ok":            False,
        "last_poll_at":            0.0,
        "queue_depth":             0,
        "escalations_since_boot":  0,
        "errors_since_boot":       0,
        "auto_actions_since_boot":    0,
        "auto_ok_since_boot":         0,
        "auto_err_since_boot":        0,
        "auto_suppressed_since_boot": 0,
        "dry_run":                    dry_run,
    }

    # Self-healing watchdog: if the main loop stalls > threshold seconds,
    # call os._exit(1) so the scheduled-task restart-on-failure fires.
    # _activity_ts is a single-element list so the daemon thread can read it
    # without a Lock (CPython list-element read/write is atomic enough here).
    # _current_eff_poll is updated after each cadence calculation.
    _activity_ts     = [time.time()]
    _current_eff_poll = [poll_s]

    if not once:
        def _watchdog_thread() -> None:
            while not _STOP:
                time.sleep(30)
                age = time.time() - _activity_ts[0]
                threshold = _watchdog_threshold(_current_eff_poll[0])
                if age > threshold:
                    _log.error(
                        "watchdog: main loop stalled %.0fs (threshold=%.0fs eff_poll=%.0fs) "
                        "- forcing exit so scheduled-task restart fires",
                        age, threshold, _current_eff_poll[0],
                    )
                    os._exit(1)

        _wd = threading.Thread(target=_watchdog_thread, daemon=True, name="bridge-watchdog")
        _wd.start()

    if dry_run:
        _log.info("bridge_watcher starting in DRY-RUN mode - no pending writes, no auto-actions, no notifications")

    while not _STOP:
        try:
            _activity_ts[0] = time.time()  # watchdog heartbeat
            _actions.reset_daily_spend_if_new_day(state)
            _ring_age(state, time.time())

            # Node-load restraint: read RC health once per cycle and suppress
            # auto-action lanes if RC is degraded. Only checked when lanes are
            # enabled; on non-RC nodes the health file won't exist (returns False).
            _rc_degraded, _rc_reason = False, ""
            if enabled_lanes:
                _rc_degraded, _rc_reason = _check_rc_health(
                    _read_json(_RC_HEALTH_PATH, {}), time.time()
                )
                if _rc_degraded:
                    _log.warning("auto-action SUPPRESSED this cycle: %s", _rc_reason)
            since = state.get("last_seen_ts", 0.0)
            envelopes = _fetch_since(since, bridge_url)
            new_max_ts = since
            new_escalations = 0
            new_acks = 0
            new_auto = 0
            first_new_esc: Optional[dict] = None
            for env in envelopes:
                ts = float(env.get("ts") or 0)
                if ts > new_max_ts:
                    new_max_ts = ts
                key = _envelope_dedupe_key(env)
                if key in processed_ids:
                    continue
                processed_ids.add(key)
                if env.get("kind") == "task":
                    state["last_task_ts"] = time.time()
                # Pass any-lane-enabled to classifier; per-lane gate runs below
                cls, reason = classify(env, node=node,
                                       node_config=node_config,
                                       auto_action_enabled=bool(enabled_lanes))
                # Per-lane downgrade: if classifier picked a lane we haven't
                # opted into, demote to escalate.
                if cls in ("auto-read", "auto-ops"):
                    lane_short = cls.replace("auto-", "")
                    if lane_short not in enabled_lanes:
                        original_cls = cls
                        cls = "escalate"
                        reason = (f"{original_cls!r} matched but lane disabled "
                                  f"(enabled_lanes={sorted(enabled_lanes)}); downgraded to escalate")
                if cls == "escalate":
                    newly_added = True if dry_run else _add_to_pending(env, reason)
                    if newly_added:
                        new_escalations += 1
                        if not dry_run:
                            _ring_add(state, "escalation", time.time())
                        if first_new_esc is None:
                            first_new_esc = {"source": env.get("source", "?"),
                                             "summary": (env.get("summary") or "")[:120]}
                        _pfx = "DRY-RUN would-escalate" if dry_run else "escalate"
                        _log.info("%s id=%s src=%s kind=%s - %s",
                                  _pfx, env.get("id"), env.get("source"),
                                  env.get("kind"), reason)
                elif cls == "ack-only":
                    new_acks += 1
                    _log.debug("ack-only id=%s src=%s kind=%s - %s",
                               env.get("id"), env.get("source"),
                               env.get("kind"), reason)
                elif cls in ("auto-read", "auto-ops"):
                    # Node-load restraint: demote to escalate if RC is degraded.
                    if _rc_degraded:
                        stats["auto_suppressed_since_boot"] += 1
                        _ring_add(state, "auto_suppressed", time.time())
                        if not dry_run and _add_to_pending(
                                env, f"auto-action suppressed: {_rc_reason}"):
                            new_escalations += 1
                            if first_new_esc is None:
                                first_new_esc = {"source": env.get("source", "?"),
                                                 "summary": (env.get("summary") or "")[:120]}
                        _log.info("auto-action SUPPRESSED lane=%s id=%s - %s",
                                  cls, env.get("id"), _rc_reason)
                        continue
                    # Phase 2: invoke claude --print for auto-action lanes.
                    new_auto += 1
                    stats["auto_actions_since_boot"] += 1
                    prompt_text = ""
                    bd_field = env.get("body") or {}
                    if isinstance(bd_field, dict):
                        prompt_text = str(bd_field.get("prompt") or "")

                    # Past-task memory short-circuit (Phase 4).
                    # If a near-identical prompt+lane succeeded recently, return
                    # the cached body - no $ spent, no claude --print spawn.
                    # If a near-identical prompt+lane FAILED recently, escalate
                    # without re-spawning so we don't burn tokens on a known-bad path.
                    cached = _history.lookup_recent_match(
                        db_path=_HISTORY_DB, prompt=prompt_text, lane=cls)
                    if cached and cached["match_type"] == "high_sim":
                        if cached["status"] == "ok":
                            cached_body = {
                                "_cached": True,
                                "_original_task_id": cached["original_task_id"],
                                "_original_summary": cached["summary"],
                                "_similarity":       cached["similarity"],
                                "_hours_ago":        cached["hours_ago"],
                                "note": "auto-action result reused from past-task memory",
                            }
                            stats["auto_ok_since_boot"] += 1
                            _log.info(
                                "%sauto-action CACHE-HIT lane=%s id=%s sim=%.2f orig=%s ($0.00)",
                                "DRY-RUN " if dry_run else "",
                                cls, env.get("id"), cached["similarity"], cached["original_task_id"])
                            if not dry_run:
                                _ring_add(state, "auto_ok", time.time())
                                _post_result_back(env, res_status="ok",
                                                  body=cached_body, node=node, tools_dir=tools_dir)
                                _history.record_outcome(
                                    db_path=_HISTORY_DB, envelope=env, lane=cls,
                                    pattern_matched=reason, status="ok",
                                    cost_usd=0.0, latency_s=0.0,
                                    summary=f"cached from {cached['original_task_id']}",
                                    body=cached_body)
                            continue
                        if cached["status"] == "error":
                            esc_reason = (f"recent failure on near-identical prompt "
                                          f"(sim={cached['similarity']:.2f}, "
                                          f"orig={cached['original_task_id']}, "
                                          f"{cached['hours_ago']}h ago) - escalating without retry")
                            newly_sc = True if dry_run else _add_to_pending(env, esc_reason)
                            if newly_sc:
                                new_escalations += 1
                                if not dry_run:
                                    _ring_add(state, "escalation", time.time())
                                if first_new_esc is None:
                                    first_new_esc = {"source": env.get("source", "?"),
                                                     "summary": (env.get("summary") or "")[:120]}
                            _log.info(
                                "%sauto-action SHORT-CIRCUIT-ESCALATE lane=%s id=%s reason=%s",
                                "DRY-RUN " if dry_run else "",
                                cls, env.get("id"), esc_reason)
                            if not dry_run:
                                _history.record_outcome(
                                    db_path=_HISTORY_DB, envelope=env, lane=cls,
                                    pattern_matched=reason, status="escalate",
                                    cost_usd=0.0, latency_s=0.0,
                                    summary="short-circuit: cached recent failure",
                                    body={}, error_brief=esc_reason)
                            continue

                    # No high-sim cache hit.
                    if dry_run:
                        _log.info("DRY-RUN would-auto-action lane=%s id=%s prompt_len=%d",
                                  cls, env.get("id"), len(prompt_text))
                        continue

                    # Actually spawn claude --print.
                    t0 = time.time()
                    res_status, res_body, cost = _actions.run_action(
                        envelope=env, lane=cls, node_config=node_config or {},
                        state=state,
                        action_prompt_path=_ACTION_PROMPT,
                        artifacts_dir=_ARTIFACTS_DIR,
                        project_root=_PROJECT_ROOT,
                        api_key_path=_DEFAULT_API_KEY_PATH,
                    )
                    latency_s = time.time() - t0
                    state["tokens_used_today_usd"] = float(state.get("tokens_used_today_usd", 0.0)) + cost

                    # Record the outcome for future short-circuits + pattern stats.
                    err_brief = ""
                    if isinstance(res_body, dict) and res_status != "ok":
                        err_brief = str(res_body.get("error") or res_body.get("reason") or "")[:500]
                    _history.record_outcome(
                        db_path=_HISTORY_DB, envelope=env, lane=cls,
                        pattern_matched=reason, status=res_status,
                        cost_usd=cost, latency_s=latency_s,
                        summary=(res_body.get("_summary") if isinstance(res_body, dict) else "") or "",
                        body=res_body if isinstance(res_body, dict) else {},
                        error_brief=err_brief)

                    if res_status == "ok":
                        stats["auto_ok_since_boot"] += 1
                        _ring_add(state, "auto_ok", time.time())
                        _post_result_back(env, res_status="ok", body=res_body, node=node, tools_dir=tools_dir)
                        _log.info("auto-action OK lane=%s id=%s cost=$%.4f lat=%.1fs",
                                  cls, env.get("id"), cost, latency_s)
                    elif res_status == "error":
                        stats["auto_err_since_boot"] += 1
                        _ring_add(state, "auto_err", time.time())
                        _post_result_back(env, res_status="error", body=res_body, node=node, tools_dir=tools_dir)
                        _log.warning("auto-action ERROR lane=%s id=%s cost=$%.4f reason=%s",
                                     cls, env.get("id"), cost, res_body.get("error", ""))
                    else:  # escalate
                        if _add_to_pending(env, f"auto-action escalated: {res_body.get('reason','')}"):
                            new_escalations += 1
                            _ring_add(state, "escalation", time.time())
                            if first_new_esc is None:
                                first_new_esc = {"source": env.get("source", "?"),
                                                 "summary": (env.get("summary") or "")[:120]}
                        _log.info("auto-action ESCALATE lane=%s id=%s reason=%s",
                                  cls, env.get("id"), res_body.get("reason", ""))
                else:  # reject or unknown
                    _log.warning("reject id=%s src=%s kind=%s - %s",
                                 env.get("id"), env.get("source"),
                                 env.get("kind"), reason)

            # Compute real 24h sliding counts from persisted ring.
            _now = time.time()
            stats["escalations_24h"]     = _ring_count(state, "escalation",     _now)
            stats["auto_ok_24h"]         = _ring_count(state, "auto_ok",        _now)
            stats["auto_err_24h"]        = _ring_count(state, "auto_err",        _now)
            stats["errors_24h"]          = _ring_count(state, "error",           _now)
            stats["auto_actions_24h"]    = stats["auto_ok_24h"] + stats["auto_err_24h"]
            stats["auto_suppressed_24h"] = _ring_count(state, "auto_suppressed", _now)

            # Push notification for new escalations (throttled 3/hr; no-op in
            # dry-run or when escalations were caused by RC node-load suppression).
            if new_escalations and first_new_esc and not dry_run and not _rc_degraded:
                notif_n    = new_escalations
                notif_src  = first_new_esc["source"]
                notif_summ = first_new_esc["summary"]
                if notif_n > 1:
                    notif_summ = f"{notif_summ} (+{notif_n - 1} more)"
                _send_push_notification(
                    summary=notif_summ, source=notif_src, node=node,
                    state=state, now=_now,
                    api_key_path=_DEFAULT_API_KEY_PATH,
                )

            state["last_seen_ts"] = new_max_ts
            state["processed_ids"] = list(processed_ids)
            # State persists tokens_used_today_usd (daily reset) but NOT the
            # since-boot counters - those reset every restart by design.
            _save_state(state)
            _rotate_artifacts(state, processed_ids, time.time())

            # Refresh queue_depth from disk (operator may have drained).
            pending = _read_json(_PENDING_PATH, {"tasks": []})
            stats["queue_depth"]        = len(pending.get("tasks") or [])
            stats["last_poll_ok"]       = True
            stats["last_poll_at"]       = time.time()
            stats["escalations_since_boot"] += new_escalations
            stats["tokens_used_today_usd"] = float(state.get("tokens_used_today_usd", 0.0))

            if new_escalations or new_acks:
                _log.info("poll: +%d escalations, +%d acks, queue=%d",
                          new_escalations, new_acks, stats["queue_depth"])
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as exc:
            stats["last_poll_ok"] = False
            stats["errors_since_boot"]  += 1
            _ring_add(state, "error", time.time())
            _log.warning("poll failed: %s", exc)
        except Exception as exc:  # pragma: no cover - defensive  # noqa: BLE001
            stats["last_poll_ok"] = False
            stats["errors_since_boot"]  += 1
            _ring_add(state, "error", time.time())
            _log.exception("unexpected error: %s", exc)

        # Determine effective poll interval from cadence sentinel (read once
        # per poll cycle - not during sleep - to avoid excess FS reads).
        _cmode = _read_mode()
        if _cmode == "sleep":
            _eff_poll = _SLEEP_POLL_S
        elif _cmode == "auto":
            _idle_s = time.time() - state.get("last_task_ts", started_at)
            _eff_poll = _SLEEP_POLL_S if _idle_s > _AUTO_IDLE_S else poll_s
        else:
            _eff_poll = poll_s
        stats["cadence_mode"]     = _cmode
        stats["effective_poll_s"] = _eff_poll
        _current_eff_poll[0]      = _eff_poll
        _write_heartbeat(stats)

        if once:
            _log.info("--once: exiting after one poll cycle")
            return 0

        # Sleep in 0.5 s chunks so SIGTERM lands fast.
        slept = 0.0
        while slept < _eff_poll and not _STOP:
            time.sleep(min(0.5, _eff_poll - slept))
            slept += 0.5

    _log.info("bridge_watcher exiting cleanly")
    return 0


def _selftest() -> int:
    """Inline smoke-tests for sliding ring + push throttle.

    Run with: C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/bridge_watcher.py --selftest
    """
    errs = 0

    def chk(label: str, ok: bool) -> None:
        nonlocal errs
        if ok:
            print(f"ok  : {label}")
        else:
            print(f"FAIL: {label}")
            errs += 1

    now = 2_000_000.0

    # -- ring: aging --
    s: dict = {}
    _ring_add(s, "escalation", now - _RING_WINDOW_S - 1)  # just outside window
    _ring_add(s, "escalation", now - _RING_WINDOW_S + 1)  # just inside window
    _ring_add(s, "auto_ok",    now - 3_600)
    _ring_add(s, "auto_ok",    now - 100)
    _ring_age(s, now)
    chk("ring: 1 escalation in 24h (stale entry aged)",
        _ring_count(s, "escalation", now) == 1)
    chk("ring: 2 auto_ok in 24h",
        _ring_count(s, "auto_ok", now) == 2)
    chk("ring: 0 error in 24h",
        _ring_count(s, "error", now) == 0)
    chk("ring: no entry older than window remains",
        all(e.get("t", 0) >= now - _RING_WINDOW_S
            for e in s.get("event_ring_24h", [])))

    # -- ring: size cap --
    s2: dict = {}
    for i in range(_MAX_RING_SIZE + 10):
        _ring_add(s2, "escalation", now + i)
    chk(f"ring: capped at {_MAX_RING_SIZE}",
        len(s2.get("event_ring_24h", [])) == _MAX_RING_SIZE)

    # -- push throttle --
    s3: dict = {}
    chk("push: eligible with empty state",
        _push_eligible(s3, now))
    s3["push_notif_times"] = [now - 100, now - 200]
    chk("push: eligible with 2 recent sends",
        _push_eligible(s3, now))
    s3["push_notif_times"] = [now - 100, now - 200, now - 300]
    chk("push: blocked with 3 recent sends",
        not _push_eligible(s3, now))
    s3["push_notif_times"] = [now - 100, now - 200, now - _PUSH_THROTTLE_S - 1]
    chk("push: eligible when one send expired",
        _push_eligible(s3, now))

    # -- cadence mode logic --
    base = 15.0
    chk("cadence: auto idle<threshold → base poll",
        (base if 100 <= _AUTO_IDLE_S else _SLEEP_POLL_S) == base)
    chk("cadence: auto idle>threshold → sleep poll",
        (_SLEEP_POLL_S if 1000 > _AUTO_IDLE_S else base) == _SLEEP_POLL_S)
    chk("cadence: sleep mode → _SLEEP_POLL_S",
        _SLEEP_POLL_S == 300)
    chk("cadence: _AUTO_IDLE_S is 15 min",
        _AUTO_IDLE_S == 900)

    # -- RC health check --
    import datetime as _dt
    def _iso(offset_s: float) -> str:
        ts = _dt.datetime.fromtimestamp(now - offset_s, tz=_dt.timezone.utc)
        return ts.isoformat()

    _healthy = {
        "alive": True, "last_reload_ok": True, "booting": False,
        "updated_at": _iso(5), "started_at": _iso(_RC_RESTART_GRACE_S + 10),
    }
    chk("rc_health: healthy RC → not degraded",
        _check_rc_health(_healthy, now) == (False, ""))
    chk("rc_health: empty dict → not degraded (non-RC node)",
        _check_rc_health({}, now) == (False, ""))
    chk("rc_health: alive=False → degraded",
        _check_rc_health({**_healthy, "alive": False}, now)[0])
    chk("rc_health: last_reload_ok=False → degraded",
        _check_rc_health({**_healthy, "last_reload_ok": False}, now)[0])
    chk("rc_health: booting=True → degraded",
        _check_rc_health({**_healthy, "booting": True}, now)[0])
    chk("rc_health: stale heartbeat (>threshold) → degraded",
        _check_rc_health({**_healthy, "updated_at": _iso(_RC_HEALTH_STALE_S + 1)}, now)[0])
    chk("rc_health: fresh heartbeat (at threshold-1) → not degraded",
        not _check_rc_health({**_healthy, "updated_at": _iso(_RC_HEALTH_STALE_S - 1)}, now)[0])
    chk("rc_health: just restarted (grace-1 s ago) → degraded",
        _check_rc_health({**_healthy, "started_at": _iso(_RC_RESTART_GRACE_S - 1)}, now)[0])
    chk("rc_health: restarted just after grace (grace+1 s ago) → not degraded",
        not _check_rc_health({**_healthy, "started_at": _iso(_RC_RESTART_GRACE_S + 1)}, now)[0])

    # -- watchdog threshold --
    chk("watchdog: threshold = max(120, poll*3) for active mode (15s)",
        _watchdog_threshold(15.0) == 120.0)
    chk("watchdog: threshold = 900 for sleep mode (300s)",
        _watchdog_threshold(300.0) == 900.0)
    chk("watchdog: threshold = max(120, 60*3) = 180 for mid poll",
        _watchdog_threshold(60.0) == 180.0)

    # -- artifact rotation predicate --
    proc_set = {"task-abc123", "task-def456"}
    chk("rotation: remove old artifact (>7 days)",
        _should_remove_artifact(_ARTIFACT_RETENTION_S + 1, "task-xyz", set()))
    chk("rotation: keep recent artifact (<7 days)",
        not _should_remove_artifact(_ARTIFACT_RETENTION_S - 1, "task-xyz", set()))
    chk("rotation: remove artifact in processed_ids regardless of age",
        _should_remove_artifact(0, "task-abc123", proc_set))
    chk("rotation: keep artifact not in processed_ids and young",
        not _should_remove_artifact(60, "task-other", proc_set))
    chk("rotation: exact boundary (== retention) not removed",
        not _should_remove_artifact(_ARTIFACT_RETENTION_S, "task-xyz", set()))

    result = "PASS" if errs == 0 else "FAIL"
    print(f"\nselftest: {result} ({errs} failure(s))")
    return errs


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    p = argparse.ArgumentParser()
    p.add_argument("--node", required=True, choices=["legion", "gamepc", "peer"],
                   help="this machine's bridge label")
    p.add_argument("--bridge-url", default=None,
                   help="GET-able bridge log endpoint (default: per-node)")
    p.add_argument("--data-dir", default=None,
                   help="dir for health/pending/state/pid files (default: <root>/ops/runtime)")
    p.add_argument("--log-dir", default=None,
                   help="dir for daily log files (default: <root>/logs)")
    p.add_argument("--poll", type=float, default=_DEFAULT_POLL_S,
                   help="poll interval in seconds (default: 15)")
    p.add_argument("--lookback", type=float, default=_DEFAULT_LOOKBACK_S,
                   help="cold-boot lookback in seconds (default: 86400)")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    p.add_argument("--once", action="store_true",
                   help="run one poll cycle and exit (for testing)")
    p.add_argument("--enable-auto-action", action="store_true",
                   help="DEPRECATED: enables both 'read' and 'ops' lanes. Prefer --enable-auto-action-lanes.")
    p.add_argument("--enable-auto-action-lanes", default="",
                   help="Comma-separated list of auto-action lanes to enable: 'read', 'ops', or 'read,ops'. "
                        "Empty (default) = no auto-action; classifier never returns auto-* lanes.")
    p.add_argument("--dry-run", action="store_true",
                   help="classify envelopes but never write to pending queue, spawn auto-actions, "
                        "or send push notifications. Heartbeat still written with dry_run=true. "
                        "Useful for tuning classifier patterns against real traffic without spend.")
    p.add_argument("--config", default=None,
                   help="path to bridge_watcher_config.json (default: alongside watcher script)")
    p.add_argument("--tools-dir", default=None,
                   help="dir containing bridge_post_result.py (default: alongside watcher script)")
    args = p.parse_args()
    bridge_url = args.bridge_url or _DEFAULT_BRIDGE_URL.get(args.node)
    if not bridge_url:
        sys.stderr.write(f"no default --bridge-url for node={args.node}; pass --bridge-url\n")
        return 2

    # Re-bind path globals if operator passed --data-dir / --log-dir.
    global _HEALTH_PATH, _PENDING_PATH, _STATE_PATH, _PID_PATH, _LOG_DIR, _ARTIFACTS_DIR, _ACTION_PROMPT, _CONFIG_PATH, _HISTORY_DB, _MODE_PATH
    if args.data_dir:
        d = Path(args.data_dir).expanduser().resolve()
        _HEALTH_PATH    = d / "bridge_watcher_health.json"
        _PENDING_PATH   = d / "bridge_inbox_pending.json"
        _STATE_PATH     = d / "bridge_watcher_state.json"
        _PID_PATH       = d / "bridge_watcher.pid"
        _ARTIFACTS_DIR  = d / "bridge_action_artifacts"
        _HISTORY_DB     = d / "bridge_action_history.db"
        _MODE_PATH      = d / "bridge_watcher_mode.json"
    if args.log_dir:
        _LOG_DIR = Path(args.log_dir).expanduser().resolve()

    # Resolve tools dir + config path + action prompt (Phase 2).
    tools_dir = Path(args.tools_dir).expanduser().resolve() if args.tools_dir else _DEFAULT_TOOLS_DIR
    if args.config:
        _CONFIG_PATH = Path(args.config).expanduser().resolve()
    if not (_DEFAULT_TOOLS_DIR / "bridge_watcher_action_prompt.md").exists():
        # Action prompt should live alongside watcher; warn if missing
        pass
    _ACTION_PROMPT = tools_dir / "bridge_watcher_action_prompt.md"

    # Load per-node config if available (Phase 2).
    node_config = None
    try:
        if _CONFIG_PATH.exists():
            cfg_all = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(cfg_all, dict):
                node_config = cfg_all.get(args.node)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"warning: couldn't read config {_CONFIG_PATH}: {exc}\n")

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOG_DIR / f"bridge_watcher_{time.strftime('%Y-%m-%d')}.log"
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )
    # Resolve enabled lanes from either the legacy --enable-auto-action (both)
    # or the explicit --enable-auto-action-lanes (preferred).
    enabled_lanes: set = set()
    if args.enable_auto_action:
        enabled_lanes = {"read", "ops"}
    if args.enable_auto_action_lanes:
        for token in args.enable_auto_action_lanes.split(","):
            t = token.strip().lower()
            if t in ("read", "ops"):
                enabled_lanes.add(t)
            elif t:
                sys.stderr.write(f"warning: unknown lane {t!r}; expected 'read' or 'ops'\n")

    _log.info("bridge_watcher starting node=%s url=%s poll=%.0fs lookback=%.0fs lanes=%s config_loaded=%s",
              args.node, bridge_url, args.poll, args.lookback,
              sorted(enabled_lanes) or "[]", node_config is not None)

    run_kwargs = {
        "dry_run":       args.dry_run,
        "enabled_lanes": enabled_lanes,
        "node_config":   node_config,
        "tools_dir":     tools_dir,
    }

    if args.once:
        return _run(args.node, args.poll, args.lookback, bridge_url,
                    once=True, **run_kwargs) or 0

    _pid_lock_acquire(args.node)
    try:
        try:
            signal.signal(signal.SIGTERM, _handle_signal)
            signal.signal(signal.SIGINT, _handle_signal)
        except (AttributeError, ValueError):
            pass  # SIGTERM may be unavailable on some Windows configs
        return _run(args.node, args.poll, args.lookback, bridge_url, **run_kwargs)
    finally:
        _pid_lock_release()


if __name__ == "__main__":
    sys.exit(main())

"""bridge_watcher.py — silent cross-Claude bridge poller (MVP).

Phase 0 per BRIDGE_WATCHER_PLAN.md §11:
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
slash command. Watcher does NOT post results to the bridge — that
remains the operator's job (or Phase 2 auto-action's).

Run via:
  py tools/bridge_watcher.py --node legion          # foreground
  py tools/bridge_watcher.py --node legion --poll 15
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

_DEFAULT_POLL_S = 15.0
_DEFAULT_LOOKBACK_S = 86400  # 24h
_PENDING_TTL_S = 86400       # 24h before a pending entry auto-expires

# Default bridge URL per node. Phase 1 nodes can override via --bridge-url.
#   legion : own loopback (RC dashboard hosts the bridge log)
#   gamepc : Legion's bridge (Game-PC has no local dashboard; bridge_pull_tasks.py
#            uses the same URL with target filter)
#   peer    : own loopback (Peer dashboard hosts its own bridge log)
_DEFAULT_BRIDGE_URL = {
    "legion": "https://127.0.0.1:8888/api/bridge",
    "gamepc": "https://legion-rc:8888/api/bridge",
    # Peer serves /api/bridge/messages (NOT bare /api/bridge — confirmed by
    # Peer 2026-05-03 install probe). Their response is a bare JSON list;
    # _fetch_since handles both shapes.
    "peer":    "https://127.0.0.1:8888/api/bridge/messages",
}
_MAX_PROMPT_LEN = 32 * 1024  # 32 KiB cap on prompt body before truncation

_log = logging.getLogger("rc.bridge_watcher")

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# ── Atomic-write helper (mirrors core.bridge_monitor's WinError-5 retry) ──


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    # os.replace can transiently raise PermissionError (WinError 5) when a
    # reader has the dst open; brief retries clear it. (Same pattern as
    # core.bridge_monitor._write_atomic — see reference_os_replace_winerror5.)
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


# ── PID lock ──────────────────────────────────────────────────────────


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


# ── Bridge fetch ──────────────────────────────────────────────────────


def _fetch_since(since_ts: float, bridge_url: str) -> list[dict]:
    url = f"{bridge_url}?since={since_ts}&limit=100"
    req = urllib.request.Request(url, method="GET",
                                 headers={"User-Agent": "rc-bridge-watcher/0"})
    with urllib.request.urlopen(req, timeout=4.0, context=_SSL_CTX) as r:
        data = json.loads(r.read())
    # Legion/RC returns wrapped {now, messages: [...]}, Peer returns bare list.
    # Per Peer 2026-05-03 install report — handle both shapes defensively.
    if isinstance(data, list):
        msgs = data
    elif isinstance(data, dict):
        msgs = data.get("messages") or []
    else:
        msgs = []
    return [m for m in msgs if isinstance(m, dict)]


# ── Pending queue (escalations) ───────────────────────────────────────


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

    Mirrors §8 claim-lock spec: a worker that crashes shouldn't permanently
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


# ── State (last seen ts) ──────────────────────────────────────────────


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


# ── Heartbeat ─────────────────────────────────────────────────────────


def _write_heartbeat(stats: dict) -> None:
    # Counter naming clarity (per Peer 2026-05-03 ask):
    #   queue_depth          : LIVE — current size of bridge_inbox_pending.json
    #   *_since_boot         : MONOTONIC — counts since this watcher process started
    #   tokens_used_today_usd: DAILY — resets at local midnight (only "today" field)
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

        # Preferred names — accurate semantics
        "auto_actions_since_boot": auto_actions,
        "auto_ok_since_boot":      auto_ok,
        "auto_err_since_boot":     auto_err,
        "escalations_since_boot":  escalations,
        "errors_since_boot":       errors,

        # Legacy aliases — DEPRECATED; will be removed after one release window.
        # Same values as *_since_boot above. They were misleadingly named.
        "auto_actions_24h": auto_actions,
        "auto_ok_24h":      auto_ok,
        "auto_err_24h":     auto_err,
        "escalations_24h":  escalations,
        "errors_24h":       errors,

        "tokens_used_today_usd": stats.get("tokens_used_today_usd", 0.0),
    }
    try:
        _atomic_write_json(_HEALTH_PATH, payload)
    except OSError as exc:
        _log.warning("heartbeat write failed: %s", exc)


# ── Result posting (Phase 2 auto-action result → bridge_post_result.py) ──


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
        _log.warning("post_result: unknown envelope source %r — defaulting to 'peer'", raw_src)
        src_field = "peer"
    exit_code = "0" if res_status == "ok" else "1"
    summary = body.pop("_summary", None) or f"auto-action {res_status} (lane {body.get('_lane','?')})"
    poster = (tools_dir or _DEFAULT_TOOLS_DIR) / "bridge_post_result.py"
    if not poster.exists():
        _log.warning("bridge_post_result.py missing at %s — cannot post result", poster)
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


# ── Main loop ─────────────────────────────────────────────────────────


_STOP = False


def _handle_signal(signum, _frame) -> None:
    global _STOP
    _log.info("received signal %s — stopping", signum)
    _STOP = True


def _run(node: str, poll_s: float, lookback_s: float, bridge_url: str, *,
         once: bool = False,
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
        "auto_actions_since_boot": 0,
        "auto_ok_since_boot":      0,
        "auto_err_since_boot":     0,
    }

    while not _STOP:
        try:
            _actions.reset_daily_spend_if_new_day(state)
            since = state.get("last_seen_ts", 0.0)
            envelopes = _fetch_since(since, bridge_url)
            new_max_ts = since
            new_escalations = 0
            new_acks = 0
            new_auto = 0
            for env in envelopes:
                ts = float(env.get("ts") or 0)
                if ts > new_max_ts:
                    new_max_ts = ts
                key = _envelope_dedupe_key(env)
                if key in processed_ids:
                    continue
                processed_ids.add(key)
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
                    if _add_to_pending(env, reason):
                        new_escalations += 1
                        _log.info("escalate id=%s src=%s kind=%s — %s",
                                  env.get("id"), env.get("source"),
                                  env.get("kind"), reason)
                elif cls == "ack-only":
                    new_acks += 1
                    _log.debug("ack-only id=%s src=%s kind=%s — %s",
                               env.get("id"), env.get("source"),
                               env.get("kind"), reason)
                elif cls in ("auto-read", "auto-ops"):
                    # Phase 2: invoke claude --print for auto-action lanes.
                    new_auto += 1
                    stats["auto_actions_since_boot"] += 1
                    prompt_text = ""
                    bd_field = env.get("body") or {}
                    if isinstance(bd_field, dict):
                        prompt_text = str(bd_field.get("prompt") or "")

                    # Past-task memory short-circuit (Phase 4).
                    # If a near-identical prompt+lane succeeded recently, return
                    # the cached body — no $ spent, no claude --print spawn.
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
                            _post_result_back(env, res_status="ok",
                                              body=cached_body, node=node, tools_dir=tools_dir)
                            _log.info("auto-action CACHE-HIT lane=%s id=%s sim=%.2f orig=%s ($0.00)",
                                      cls, env.get("id"), cached["similarity"], cached["original_task_id"])
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
                                          f"{cached['hours_ago']}h ago) — escalating without retry")
                            if _add_to_pending(env, esc_reason):
                                new_escalations += 1
                            _log.info("auto-action SHORT-CIRCUIT-ESCALATE lane=%s id=%s reason=%s",
                                      cls, env.get("id"), esc_reason)
                            _history.record_outcome(
                                db_path=_HISTORY_DB, envelope=env, lane=cls,
                                pattern_matched=reason, status="escalate",
                                cost_usd=0.0, latency_s=0.0,
                                summary="short-circuit: cached recent failure",
                                body={}, error_brief=esc_reason)
                            continue

                    # No high-sim cache hit — actually spawn claude --print.
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
                        _post_result_back(env, res_status="ok", body=res_body, node=node, tools_dir=tools_dir)
                        _log.info("auto-action OK lane=%s id=%s cost=$%.4f lat=%.1fs",
                                  cls, env.get("id"), cost, latency_s)
                    elif res_status == "error":
                        stats["auto_err_since_boot"] += 1
                        _post_result_back(env, res_status="error", body=res_body, node=node, tools_dir=tools_dir)
                        _log.warning("auto-action ERROR lane=%s id=%s cost=$%.4f reason=%s",
                                     cls, env.get("id"), cost, res_body.get("error", ""))
                    else:  # escalate
                        if _add_to_pending(env, f"auto-action escalated: {res_body.get('reason','')}"):
                            new_escalations += 1
                        _log.info("auto-action ESCALATE lane=%s id=%s reason=%s",
                                  cls, env.get("id"), res_body.get("reason", ""))
                else:  # reject or unknown
                    _log.warning("reject id=%s src=%s kind=%s — %s",
                                 env.get("id"), env.get("source"),
                                 env.get("kind"), reason)

            state["last_seen_ts"] = new_max_ts
            state["processed_ids"] = list(processed_ids)
            # State persists tokens_used_today_usd (daily reset) but NOT the
            # since-boot counters — those reset every restart by design.
            _save_state(state)

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
            _log.warning("poll failed: %s", exc)
        except Exception as exc:  # pragma: no cover — defensive
            stats["last_poll_ok"] = False
            stats["errors_since_boot"]  += 1
            _log.exception("unexpected error: %s", exc)

        _write_heartbeat(stats)

        if once:
            _log.info("--once: exiting after one poll cycle")
            return 0

        # Sleep in 0.5 s chunks so SIGTERM lands fast.
        slept = 0.0
        while slept < poll_s and not _STOP:
            time.sleep(min(0.5, poll_s - slept))
            slept += 0.5

    _log.info("bridge_watcher exiting cleanly")
    return 0


def main() -> int:
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
    global _HEALTH_PATH, _PENDING_PATH, _STATE_PATH, _PID_PATH, _LOG_DIR, _ARTIFACTS_DIR, _ACTION_PROMPT, _CONFIG_PATH, _HISTORY_DB
    if args.data_dir:
        d = Path(args.data_dir).expanduser().resolve()
        _HEALTH_PATH    = d / "bridge_watcher_health.json"
        _PENDING_PATH   = d / "bridge_inbox_pending.json"
        _STATE_PATH     = d / "bridge_watcher_state.json"
        _PID_PATH       = d / "bridge_watcher.pid"
        _ARTIFACTS_DIR  = d / "bridge_action_artifacts"
        _HISTORY_DB     = d / "bridge_action_history.db"
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

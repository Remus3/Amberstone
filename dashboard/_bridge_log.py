"""Cross-Claude bridge message log.

Tier 2 helper-shake (2026-05-01): extracted from web_dashboard.py.

Lightweight in-memory message log so Legion Claude and Game-PC Claude
can leave notes for each other. Read via GET /api/bridge?since=<ts>;
post via POST /api/bridge {source, summary, kind?, id?, target?, body?,
in_reply_to?}. Last 100 messages retained in memory; mirrored to a
JSONL backup that survives RC restarts.

Schema (2026-04-24): the original {source, summary} form is preserved
as `kind: "note"` (default) for back-compat with existing
Stop/UserPromptSubmit hooks. Additional kinds:
  kind: "task"   - a job dispatched to the other side. Carries `id`
                   (uuid), `target` ("legion" | "gamepc"), and `body`
                   (free-form JSON the receiver knows how to execute,
                   typically {prompt, command, timeout_s, context}).
  kind: "result" - a response to a task. Same fields, plus
                   `in_reply_to: <task-id>` so the originator can pair
                   it.
Server doesn't interpret task/result content - that's the Claude on the
other side. It just stores + filters by kind/target so the polling
script can ask "give me pending tasks targeted at me".
"""
from __future__ import annotations

import collections
import json
import logging
import threading
import time
from pathlib import Path

from dashboard._context import APP_DIR

_log = logging.getLogger("rc.web_dashboard")

_bridge_lock = threading.Lock()
# 2026-05-02 (s31): bumped maxlen 100 -> 500. The in-memory deque is what
# /api/bridge GET reads; tasks/results can fall out within ~30 min when
# legion chat replies post 1 kind=note per response via the Stop hook.
# Peer's bridge_pull_tasks misses kind=task lookups when this window is
# too small. JSONL retains 1000 lines on disk; deque cache is now 500.
_BRIDGE_DEQUE_MAXLEN = 500
_bridge_log: collections.deque = collections.deque(maxlen=_BRIDGE_DEQUE_MAXLEN)

# 2026-04-25: persist bridge entries to JSONL so RC restart doesn't wipe
# the cross-Claude conversation. Hydrated at module import time below.
BRIDGE_LOG_PATH = APP_DIR / "ops" / "runtime" / "bridge_log.jsonl"
BRIDGE_LOG_DISK_MAX = 1000  # rotate JSONL when it exceeds this many entries

# AUDIT 2026-04-28 (deferred-low-value): every Nth append, check the
# JSONL size and trim if it has crept past BRIDGE_LOG_DISK_MAX. The
# original rotation only ran at startup; between RC restarts the file
# could grow unbounded.
BRIDGE_ROTATE_INTERVAL = 100
_bridge_writes_since_rotate = 0


def bridge_hydrate_from_disk() -> None:
    """Replay the most recent up-to-100 entries from the JSONL backup
    into the in-memory deque. Called once at import. Resilient to a
    truncated or partially-written tail line."""
    if not BRIDGE_LOG_PATH.exists():
        return
    try:
        lines = BRIDGE_LOG_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    # Re-rotate on disk if too long - trim to last 1000.
    if len(lines) > BRIDGE_LOG_DISK_MAX:
        try:
            tmp = BRIDGE_LOG_PATH.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(lines[-BRIDGE_LOG_DISK_MAX:]) + "\n",
                           encoding="utf-8")
            tmp.replace(BRIDGE_LOG_PATH)
            lines = lines[-BRIDGE_LOG_DISK_MAX:]
        except OSError:
            pass
    for line in lines[-_BRIDGE_DEQUE_MAXLEN:]:
        try:
            entry = json.loads(line)
            if isinstance(entry, dict) and "ts" in entry and "summary" in entry:
                _bridge_log.append(entry)
        except Exception:
            pass  # tolerate a torn final write


def bridge_maybe_rotate(force: bool = False) -> None:
    """Trim bridge_log.jsonl to the last BRIDGE_LOG_DISK_MAX lines if it
    has grown past that. Called periodically from bridge_post; safe to
    call from any thread (caller should already hold _bridge_lock or
    accept the rare two-rotates-collide case as harmless)."""
    try:
        if not BRIDGE_LOG_PATH.exists():
            return
        # Cheap line count via a single read. The file is JSONL bounded
        # at ~1 MB at the trim point - affordable.
        text = BRIDGE_LOG_PATH.read_text(encoding="utf-8")
        lines = text.splitlines()
        if len(lines) <= BRIDGE_LOG_DISK_MAX and not force:
            return
        keep = lines[-BRIDGE_LOG_DISK_MAX:]
        tmp = BRIDGE_LOG_PATH.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
        tmp.replace(BRIDGE_LOG_PATH)
        _log.info("bridge log rotated: %d -> %d lines",
                  len(lines), len(keep))
    except OSError as exc:
        _log.debug("bridge rotate failed: %s", exc)


def bridge_post(source: str, summary: str, *,
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
            BRIDGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(BRIDGE_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            _log.debug("bridge JSONL append failed: %s", exc)
        _bridge_writes_since_rotate += 1
        if _bridge_writes_since_rotate >= BRIDGE_ROTATE_INTERVAL:
            _bridge_writes_since_rotate = 0
            bridge_maybe_rotate()
    return entry


def bridge_since(since_ts: float, limit: int = 20, *,
                 kind: str | None = None,
                 target: str | None = None,
                 source: str | None = None) -> list:
    with _bridge_lock:
        items = [e for e in _bridge_log if e["ts"] > since_ts]
    if kind:
        items = [e for e in items if e.get("kind", "note") == kind]
    if target:
        items = [e for e in items if e.get("target") == target]
    if source:
        items = [e for e in items if e.get("source") == source]
    return items[-limit:]


def gamepc_result_age_s() -> float | None:
    """Seconds since the most recent {kind:"result", source:"gamepc"} entry,
    or None if there is no such entry in the in-memory deque.

    Used by /api/health/all to surface a "bridge silent for N minutes"
    indicator. The Game-PC `/loop /process-bridge-tasks` posts a result
    after each task it processes, so silence here means either no tasks
    have been dispatched OR the auto-flow loop on Game-PC died (the
    typical post-Claude-restart failure mode)."""
    with _bridge_lock:
        for e in reversed(_bridge_log):
            if e.get("kind") == "result" and e.get("source") == "gamepc":
                return max(0.0, time.time() - float(e.get("ts") or 0))
    return None


bridge_hydrate_from_disk()

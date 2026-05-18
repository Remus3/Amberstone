"""POST /api/bridge/pending/<task_id>/<action> - operator triage actions.

Companion to the read-only routes_bridge_pending.py (frozen). Provides
in-dashboard accept/defer/dismiss for entries the bridge_watcher has
escalated to ops/runtime/bridge_inbox_pending.json.

Actions:
  - accept   - stamp claimed_by="operator" + claimed_at=now. Visual
               indicator only; operator drains via /process-bridge-tasks.
               Watcher auto-clears claims older than 60s, so a dropped
               accept doesn't permanently block the entry.
  - defer    - extend ttl_at by 24h (resetting any claim). Pushes the
               task back in the queue without removing.
  - dismiss  - remove the task from the pending list. The watcher's
               processed_ids dedup set already contains the envelope
               key (added when the escalation was first seen), so the
               watcher won't re-add it. Operator should still post a
               kind=result back to the source if a reply is expected.

Race window: the watcher's only pending-file writer is _add_to_pending,
called on each new escalation (~15s polling). Last-writer-wins atomic
writes cover the typical ms-scale race. If a contended write becomes
visible (e.g. accept that vanishes), the operator can re-issue.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from dashboard._dispatch import prefix

_APP_DIR = Path(__file__).parent.parent
_PENDING_PATH = _APP_DIR / "ops" / "runtime" / "bridge_inbox_pending.json"
_DEFER_EXTENSION_S = 86400.0   # 24h push-back per defer click

_VALID_ACTIONS = {"accept", "defer", "dismiss"}


def _atomic_write_json_with_retry(path: Path, payload: dict) -> None:
    """tmp + os.replace with WinError-5 retry. Mirrors bridge_watcher's
    helper since concurrent reader-open can briefly block replace on
    Windows. See reference_os_replace_winerror5."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding="utf-8")
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


def _parse_path(path: str) -> tuple[str, str] | None:
    """Parse /api/bridge/pending/<task_id>/<action>. Returns
    (task_id, action) or None if malformed."""
    base = "/api/bridge/pending/"
    if not path.startswith(base):
        return None
    rest = path[len(base):]
    if "?" in rest:
        rest = rest.split("?", 1)[0]
    parts = rest.strip("/").split("/")
    if len(parts) != 2:
        return None
    task_id, action = parts
    if not task_id or action not in _VALID_ACTIONS:
        return None
    return task_id, action


def _serve_action(h, body) -> None:
    parsed = _parse_path(h.path)
    if not parsed:
        h._send(400,
                json.dumps({"error": "expected /api/bridge/pending/<id>/<action>",
                            "valid_actions": sorted(_VALID_ACTIONS)}).encode(),
                "application/json")
        return
    task_id, action = parsed

    try:
        if not _PENDING_PATH.exists():
            h._send(404, json.dumps({"error": "no pending file",
                                     "task_id": task_id}).encode(),
                    "application/json")
            return
        raw = _PENDING_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            data = {"schema_version": 1, "tasks": []}
        tasks = data.setdefault("tasks", [])

        idx = next((i for i, t in enumerate(tasks)
                    if t.get("task_id") == task_id), None)
        if idx is None:
            h._send(404, json.dumps({"error": "task_id not in pending",
                                     "task_id": task_id}).encode(),
                    "application/json")
            return

        now = time.time()
        if action == "dismiss":
            removed = tasks.pop(idx)
            data["tasks"] = tasks
            data["updated_at"] = now
            _atomic_write_json_with_retry(_PENDING_PATH, data)
            h._send(200, json.dumps({"ok": True, "action": action,
                                     "task_id": task_id,
                                     "removed_summary": removed.get("summary"),
                                     "remaining": len(tasks)}).encode(),
                    "application/json")
            return

        if action == "accept":
            tasks[idx]["claimed_by"] = "operator"
            tasks[idx]["claimed_at"] = now
        elif action == "defer":
            cur_ttl = float(tasks[idx].get("ttl_at") or now)
            tasks[idx]["ttl_at"] = max(cur_ttl, now) + _DEFER_EXTENSION_S
            tasks[idx]["claimed_by"] = None
            tasks[idx]["claimed_at"] = None

        data["updated_at"] = now
        _atomic_write_json_with_retry(_PENDING_PATH, data)
        h._send(200, json.dumps({"ok": True, "action": action,
                                 "task_id": task_id,
                                 "claimed_by": tasks[idx].get("claimed_by"),
                                 "ttl_at": tasks[idx].get("ttl_at")}).encode(),
                "application/json")
    except (OSError, json.JSONDecodeError) as exc:
        h._send(500, json.dumps({"error": str(exc)[:200],
                                 "task_id": task_id,
                                 "action": action}).encode(),
                "application/json")


GET_ROUTES: list = []

POST_ROUTES = [
    (prefix("/api/bridge/pending/"), _serve_action),
]

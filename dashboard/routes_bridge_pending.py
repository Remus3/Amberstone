# arch: GET /api/bridge/pending - escalation queue | section=dashboard | frozen=yes
"""GET /api/bridge/pending - escalation queue from bridge_watcher.

Reads ops/runtime/bridge_inbox_pending.json and returns it. The watcher
(tools/bridge_watcher.py) writes; this route only reads. Operator surfaces:

  - Dashboard panel "Pending Bridge Tasks" (Phase 0+).
  - /process-bridge-tasks slash command will check this file alongside
    its existing bridge poll once Phase 1 ships.

No POST handlers at MVP - operator dismisses by draining via
/process-bridge-tasks (which posts results, after which the watcher
naturally won't re-escalate the same task_id).

Per BRIDGE_WATCHER_PLAN.md S8.
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard._dispatch import equals

_APP_DIR = Path(__file__).parent.parent
_PENDING_PATH = _APP_DIR / "ops" / "runtime" / "bridge_inbox_pending.json"


def _serve_pending(h) -> None:
    try:
        if not _PENDING_PATH.exists():
            payload = {"schema_version": 1, "tasks": [], "watcher_status": "no_file"}
            h._send(200, json.dumps(payload).encode(), "application/json")
            return
        raw = _PENDING_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            data = {"schema_version": 1, "tasks": []}
        data.setdefault("schema_version", 1)
        data.setdefault("tasks", [])
        h._send(200, json.dumps(data).encode(), "application/json")
    except (OSError, json.JSONDecodeError) as exc:
        h._send(500, json.dumps({"error": str(exc)[:200]}).encode(),
                "application/json")


GET_ROUTES = [
    (equals("/api/bridge/pending"), _serve_pending),
]

POST_ROUTES: list = []

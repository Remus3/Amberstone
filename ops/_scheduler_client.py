"""Thin client for filing scheduler tasks from ops scripts.

Historical problem: ops scripts instantiated their own Scheduler. The
running supervisor's in-memory heap didn't see the new task, so it
sat in the jsonl until supervisor restart (the round-5 race guard
prevented stale-heap dispatch but didn't pull from disk).

This client resolves that by filing through ``POST /api/file-task`` on
the running supervisor (which uses the SAME scheduler instance its
dispatch loop is pulling from). If the supervisor is down, it falls
back to direct Scheduler.file_task - that path writes to jsonl so the
task still gets picked up on next supervisor startup.

Usage:

    from ops._scheduler_client import file_task

    task_id = file_task(
        op="my-op", owner_agent="6", priority=20,
        payload={"something": "here"},
        user_override=True,
    )

Always returns the task id. Callers don't need to care which path was
taken; ``used_http`` in the returned dict tells them if they care.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("ops.scheduler_client")

DEFAULT_BASE_URL = os.environ.get("RC_SUPERVISOR_URL", "http://127.0.0.1:8890")
_HTTP_TIMEOUT_SEC = 3.0


def file_task(
    op: str,
    owner_agent: str,
    priority: int = 100,
    categories: list[int] | None = None,
    payload: dict | None = None,
    user_override: bool = False,
    blocks: list[str] | None = None,
    blocked_by: list[str] | None = None,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    """Prefer HTTP. On any HTTP failure, fall back to in-process
    Scheduler and note that in the return dict."""
    body = {
        "op": op,
        "owner_agent": str(owner_agent),
        "priority": priority,
        "categories": list(categories or []),
        "payload": dict(payload or {}),
        "user_override": bool(user_override),
        "blocks": list(blocks or []),
        "blocked_by": list(blocked_by or []),
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/file-task",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            result["used_http"] = True
            return result
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        logger.info("HTTP file-task failed (%s) - falling back to direct Scheduler", e)

    # Fallback path. This works even when supervisor isn't running
    # (writes to the jsonl; task gets picked up on next supervisor boot).
    from agents.agent1_lead import Scheduler
    s = Scheduler()
    task = s.file_task(
        op=op, owner_agent=owner_agent, priority=priority,
        categories=categories, payload=payload,
        user_override=user_override,
        blocks=blocks, blocked_by=blocked_by,
    )
    return {
        "id": task.id,
        "status": task.status,
        "priority": task.priority,
        "owner_agent": task.owner_agent,
        "op": task.op,
        "categories": task.categories,
        "frozen_file_hits": task.payload.get("_frozen_file_hits"),
        "used_http": False,
    }

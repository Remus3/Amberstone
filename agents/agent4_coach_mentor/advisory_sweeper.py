"""Round 39 - auto-dismiss stale advisory tasks.

Advisory tasks (cold-streak + coaching-insight) are filed as READY and
stay READY forever unless the user dismisses them via the dashboard.
Over time this pollutes the queue with days-old signals that have
already been acted on (or superseded). This sweeper runs on the
auto-analyze cycle and completes advisories older than
``max_age_hours`` with a ``{source: "auto-stale"}`` result marker
(preserving audit trail - nothing is deleted).

Only READY advisories are touched. Completed / failed / in-progress
tasks are left alone. Non-advisory ops are never swept.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.agent1_lead.scheduler import Scheduler

logger = logging.getLogger("agent4.advisory_sweeper")

ADVISORY_OPS = frozenset({"cold-streak-advisory", "coaching-insight-advisory"})
DEFAULT_MAX_AGE_HOURS = 72


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def sweep_stale(
    scheduler: "Scheduler",
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    ops: frozenset[str] = ADVISORY_OPS,
) -> dict:
    """Complete READY advisory tasks older than ``max_age_hours``.

    Returns ``{dismissed: [...], inspected: N}`` where ``dismissed``
    is a list of ``{task_id, op, age_hours}`` entries. Safe to call
    repeatedly - already-completed tasks are untouched.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    dismissed: list[dict] = []
    inspected = 0
    try:
        ready = scheduler.list_by_status("ready")
    except Exception as e:                      # noqa: BLE001
        logger.warning("list_by_status failed: %s", e)
        return {"dismissed": [], "inspected": 0}

    for t in ready:
        if t.op not in ops:
            continue
        inspected += 1
        created = _parse_iso(t.created_at)
        if created is None or created >= cutoff:
            continue
        age_h = (datetime.now(timezone.utc) - created).total_seconds() / 3600.0
        result = {
            "source": "auto-stale",
            "age_hours": round(age_h, 2),
            "dismissed_at": _now_iso(),
            "prior_status": t.status,
        }
        try:
            scheduler.complete(t.id, result=result)
            dismissed.append({
                "task_id": t.id,
                "op": t.op,
                "age_hours": round(age_h, 2),
            })
        except Exception as e:                  # noqa: BLE001
            logger.warning("auto-dismiss %s failed: %s", t.id, e)

    if dismissed:
        logger.info(
            "advisory sweeper: dismissed %d stale task(s)",
            len(dismissed),
        )
    return {"dismissed": dismissed, "inspected": inspected}

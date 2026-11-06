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

Hardening (s144 true-audit cycle 152, RM-1893..RM-1899). The tasks come
from ``task_queue.jsonl``, which other processes append to, so every field
read here is checked rather than assumed:

- a naive ``created_at`` is read as UTC (it used to raise TypeError out of
  the sweep and leave every later task unswept);
- a far-future (beyond ``_FUTURE_SKEW``) or unparseable ``created_at``
  falls back to ``updated_at``; a task with neither usable is left alone
  and counted in ``unparseable``, so a junk stamp cannot pin an advisory
  READY forever unnoticed;
- a task whose ``op`` is not a str, and a ``list_by_status`` element that
  is not a task, is skipped; a non-iterable result is a failed listing
  (logged, empty summary); a task id whose lookup raises (unhashable) is
  logged and skipped;
- ``max_age_hours`` must be a finite, positive, non-bool number (anything
  else uses ``DEFAULT_MAX_AGE_HOURS`` with a warning; a negative value used
  to dismiss FRESH advisories) and is capped at ``_MAX_AGE_HOURS_CAP`` so
  a huge value sweeps nothing instead of raising OverflowError;
- ``ops`` is an exact-match set: a bare str is one op (it used to do
  substring matching), None or a non-iterable is ``ADVISORY_OPS``;
- each task is re-read from the scheduler just before it is completed, so
  one that left READY or vanished since the snapshot is not overwritten,
  and a ``complete`` that returns None is not reported as dismissed.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents.agent1_lead.scheduler import Scheduler

logger = logging.getLogger("agent4.advisory_sweeper")

ADVISORY_OPS = frozenset({"cold-streak-advisory", "coaching-insight-advisory"})
DEFAULT_MAX_AGE_HOURS = 72
# A cutoff this far back is still a valid datetime (now minus ~1000 years),
# so a huge max_age_hours sweeps nothing instead of raising OverflowError.
_MAX_AGE_HOURS_CAP = 24.0 * 365.0 * 1000.0
# A stamp up to this far in the future is clock skew between processes and
# reads as fresh; beyond it the stamp is not trusted as an age basis.
_FUTURE_SKEW = timedelta(minutes=5)
_READY = "ready"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: Any) -> datetime | None:
    """Parse an ISO-8601 stamp to an AWARE datetime; None if unusable.

    A naive stamp is read as UTC (the scheduler writes UTC). A non-str,
    an empty str and an unparseable str are None.
    """
    if not isinstance(ts, str) or not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_basis(task: Any, now: datetime) -> tuple[datetime, str] | None:
    """Return (stamp, field name) for the task's age, or None if neither
    ``created_at`` nor ``updated_at`` is a usable, non-future stamp."""
    for name in ("created_at", "updated_at"):
        dt = _parse_iso(getattr(task, name, None))
        if dt is not None and dt <= now + _FUTURE_SKEW:
            return dt, name
    return None


def _valid_max_age(max_age_hours: Any) -> float:
    if (
        isinstance(max_age_hours, bool)
        or not isinstance(max_age_hours, (int, float))
        or not math.isfinite(max_age_hours)
        or max_age_hours <= 0
    ):
        logger.warning(
            "advisory sweeper: invalid max_age_hours %r - using %s",
            max_age_hours, DEFAULT_MAX_AGE_HOURS,
        )
        return float(DEFAULT_MAX_AGE_HOURS)
    return min(float(max_age_hours), _MAX_AGE_HOURS_CAP)


def _valid_ops(ops: Any) -> frozenset[str]:
    if isinstance(ops, str):
        return frozenset({ops})
    if not isinstance(ops, Iterable):
        if ops is not None:
            logger.warning("advisory sweeper: invalid ops %r - using default", ops)
        return ADVISORY_OPS
    return frozenset(o for o in ops if isinstance(o, str))


def sweep_stale(
    scheduler: "Scheduler",
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    ops: frozenset[str] = ADVISORY_OPS,
) -> dict:
    """Complete READY advisory tasks older than ``max_age_hours``.

    Returns ``{dismissed: [...], inspected: N, unparseable: M}`` where
    ``dismissed`` is a list of ``{task_id, op, age_hours}`` entries,
    ``inspected`` counts READY tasks whose op is in scope and
    ``unparseable`` counts those left alone because neither stamp is
    usable. Safe to call repeatedly - already-completed tasks are
    untouched. Never raises on a junk task, argument or scheduler result.
    """
    hours = _valid_max_age(max_age_hours)
    scope = _valid_ops(ops)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    dismissed: list[dict] = []
    inspected = 0
    unparseable = 0
    try:
        # list() inside the try: a non-iterable result is a failed listing.
        ready = list(scheduler.list_by_status(_READY))
    except Exception as e:                      # noqa: BLE001
        logger.warning("list_by_status failed: %s", e)
        return {"dismissed": [], "inspected": 0, "unparseable": 0}

    for t in ready:
        op = getattr(t, "op", None)
        tid = getattr(t, "id", None)
        if not isinstance(op, str) or op not in scope:
            continue
        inspected += 1
        basis = _age_basis(t, now)
        if basis is None:
            unparseable += 1
            continue
        stamp, basis_name = basis
        if stamp >= cutoff:
            continue
        age_h = round((now - stamp).total_seconds() / 3600.0, 2)
        try:
            # Re-read just before completing: the snapshot may be stale
            # (a dispatcher picked the task up, or it was removed).
            current = scheduler.get(tid)
            if getattr(current, "status", None) != _READY:
                continue
            result = {
                "source": "auto-stale",
                "age_hours": age_h,
                "age_basis": basis_name,
                "dismissed_at": _now_iso(),
                "prior_status": _READY,
            }
            done = scheduler.complete(tid, result=result)
        except Exception as e:                  # noqa: BLE001
            logger.warning("auto-dismiss %r failed: %s", tid, e)
            continue
        if done is None:
            continue
        dismissed.append({"task_id": tid, "op": op, "age_hours": age_h})

    if dismissed:
        logger.info(
            "advisory sweeper: dismissed %d stale task(s)",
            len(dismissed),
        )
    if unparseable:
        logger.warning(
            "advisory sweeper: %d advisory task(s) carry no usable timestamp",
            unparseable,
        )
    return {"dismissed": dismissed, "inspected": inspected, "unparseable": unparseable}

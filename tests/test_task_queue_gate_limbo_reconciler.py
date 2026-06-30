"""WP-F5-H02 closure - pin the gate-limbo reconciler behavior.

The audit-8 H-02 reconciler (``reconcile_stale_in_progress``) only closes
IN_PROGRESS envelopes. It deliberately leaves the *gate-limbo* states
(NEEDS_APPROVAL, AGENT0_REVIEW, RETRY_PENDING) alone. That left a second
state-machine leak: a task that lands in NEEDS_APPROVAL (frozen-file gate)
and is never approved sits forever. The live queue accumulated 1567 such
orphans (a non-hermetic integration test POSTing a frozen-file payload to
the running supervisor on every run, plus any genuinely-abandoned approval).

``reconcile_stale_gated`` closes that leak: gate-limbo envelopes older than
a generous threshold (default 7 days, so a real pending approval the
operator is about to action is never reaped) transition to DEAD_LETTER
with a terminal ``reaped_gate_limbo`` event.

These tests pin:

  * Stale NEEDS_APPROVAL / AGENT0_REVIEW / RETRY_PENDING are reaped.
  * Fresh gate-limbo tasks are left alone.
  * IN_PROGRESS / READY / COMPLETED / FAILED / DEAD_LETTER are NOT reaped
    (that is reconcile_stale_in_progress' job, or already terminal).
  * The terminal event is written to task_queue.jsonl (event + status
    dead_letter + last_error=reason) and survives a Scheduler reload.
  * Threshold override, zero/negative no-op, malformed/empty ts skip,
    empty-scheduler no-op, idempotence, exact returned ids.
  * The default threshold is generous (a 1-day-old approval is kept).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from agents.agent1_lead.scheduler import (  # noqa: E402
    _GATE_LIMBO_STALE_SEC,
    Scheduler,
    TaskStatus,
)

_GATE_LIMBO_STATES = (
    TaskStatus.NEEDS_APPROVAL,
    TaskStatus.AGENT0_REVIEW,
    TaskStatus.RETRY_PENDING,
)


def _set_status_with_age(s: Scheduler, task_id: str, status: str, age_seconds: float) -> None:
    """Force a task into ``status`` with a synthetic backdated ``updated_at``."""
    t = s._tasks[task_id]
    t.status = status
    backdated = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    t.updated_at = backdated.isoformat()


def _read_last_event_for(log_path: Path, task_id: str) -> dict | None:
    if not log_path.exists():
        return None
    last: dict | None = None
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            tid = (rec.get("task") or {}).get("id")
            if tid == task_id:
                last = rec
    return last


# ---------------------------------------------------------------------------
# Reaping the gate-limbo states
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", _GATE_LIMBO_STATES)
def test_reaps_stale_gate_limbo(tmp_path: Path, status: str) -> None:
    """An old NEEDS_APPROVAL / AGENT0_REVIEW / RETRY_PENDING is dead-lettered."""
    s = Scheduler(queue_log=tmp_path / "queue.jsonl")
    task = s.file_task(op=f"gate-{status}", owner_agent="6", priority=50)
    _set_status_with_age(s, task.id, status, age_seconds=8 * 86400)  # 8 days

    reconciled = s.reconcile_stale_gated(stale_seconds=7 * 86400.0)

    assert reconciled == [task.id]
    assert s._tasks[task.id].status == TaskStatus.DEAD_LETTER


@pytest.mark.parametrize("status", _GATE_LIMBO_STATES)
def test_skips_fresh_gate_limbo(tmp_path: Path, status: str) -> None:
    """A gate-limbo task younger than the threshold is left alone."""
    s = Scheduler(queue_log=tmp_path / "queue.jsonl")
    task = s.file_task(op=f"fresh-{status}", owner_agent="6", priority=50)
    _set_status_with_age(s, task.id, status, age_seconds=3600)  # 1h

    reconciled = s.reconcile_stale_gated(stale_seconds=7 * 86400.0)

    assert reconciled == []
    assert s._tasks[task.id].status == status


@pytest.mark.parametrize(
    "status",
    [
        TaskStatus.IN_PROGRESS,
        TaskStatus.READY,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.DEAD_LETTER,
    ],
)
def test_does_not_touch_non_gate_states(tmp_path: Path, status: str) -> None:
    """IN_PROGRESS/READY/terminal states are off-limits to the gate reaper."""
    s = Scheduler(queue_log=tmp_path / "queue.jsonl")
    task = s.file_task(op=f"non-gate-{status}", owner_agent="6", priority=50)
    _set_status_with_age(s, task.id, status, age_seconds=30 * 86400)

    reconciled = s.reconcile_stale_gated(stale_seconds=7 * 86400.0)

    assert reconciled == []
    assert s._tasks[task.id].status == status


# ---------------------------------------------------------------------------
# Terminal event written + reload semantics
# ---------------------------------------------------------------------------


def test_writes_terminal_dead_letter_event(tmp_path: Path) -> None:
    log = tmp_path / "queue.jsonl"
    s = Scheduler(queue_log=log)
    task = s.file_task(op="event-shape", owner_agent="6", priority=50)
    _set_status_with_age(s, task.id, TaskStatus.NEEDS_APPROVAL, age_seconds=8 * 86400)

    s.reconcile_stale_gated(stale_seconds=7 * 86400.0, reason="stale-gate-limbo")

    last = _read_last_event_for(log, task.id)
    assert last is not None
    assert last.get("task", {}).get("status") == TaskStatus.DEAD_LETTER
    assert last.get("task", {}).get("last_error") == "stale-gate-limbo"
    assert last.get("task", {}).get("updated_at")


def test_reaped_gate_task_survives_reload(tmp_path: Path) -> None:
    log = tmp_path / "queue.jsonl"
    s = Scheduler(queue_log=log)
    task = s.file_task(op="reload-gate", owner_agent="6", priority=50)
    _set_status_with_age(s, task.id, TaskStatus.NEEDS_APPROVAL, age_seconds=8 * 86400)
    s.reconcile_stale_gated(stale_seconds=7 * 86400.0)
    assert s._tasks[task.id].status == TaskStatus.DEAD_LETTER

    s2 = Scheduler(queue_log=log)
    assert s2._tasks[task.id].status == TaskStatus.DEAD_LETTER


# ---------------------------------------------------------------------------
# Threshold tuning + safety valves
# ---------------------------------------------------------------------------


def test_default_threshold_is_generous(tmp_path: Path) -> None:
    """A 1-day-old pending approval is NOT reaped at the default threshold."""
    assert _GATE_LIMBO_STALE_SEC >= 7 * 86400.0
    s = Scheduler(queue_log=tmp_path / "queue.jsonl")
    task = s.file_task(op="day-old", owner_agent="6", priority=50)
    _set_status_with_age(s, task.id, TaskStatus.NEEDS_APPROVAL, age_seconds=86400)

    reconciled = s.reconcile_stale_gated()  # default threshold

    assert reconciled == []
    assert s._tasks[task.id].status == TaskStatus.NEEDS_APPROVAL


def test_threshold_overridable(tmp_path: Path) -> None:
    s = Scheduler(queue_log=tmp_path / "queue.jsonl")
    a = s.file_task(op="thr-a", owner_agent="6", priority=50)
    b = s.file_task(op="thr-b", owner_agent="6", priority=50)
    _set_status_with_age(s, a.id, TaskStatus.NEEDS_APPROVAL, age_seconds=90)
    _set_status_with_age(s, b.id, TaskStatus.NEEDS_APPROVAL, age_seconds=30)

    reconciled = s.reconcile_stale_gated(stale_seconds=60.0)

    assert reconciled == [a.id]
    assert s._tasks[a.id].status == TaskStatus.DEAD_LETTER
    assert s._tasks[b.id].status == TaskStatus.NEEDS_APPROVAL


def test_zero_or_negative_threshold_is_noop(tmp_path: Path) -> None:
    s = Scheduler(queue_log=tmp_path / "queue.jsonl")
    task = s.file_task(op="zero", owner_agent="6", priority=50)
    _set_status_with_age(s, task.id, TaskStatus.NEEDS_APPROVAL, age_seconds=30 * 86400)

    assert s.reconcile_stale_gated(stale_seconds=0.0) == []
    assert s.reconcile_stale_gated(stale_seconds=-1.0) == []
    assert s._tasks[task.id].status == TaskStatus.NEEDS_APPROVAL


def test_skips_malformed_and_empty_updated_at(tmp_path: Path) -> None:
    s = Scheduler(queue_log=tmp_path / "queue.jsonl")
    bad = s.file_task(op="bad-ts", owner_agent="6", priority=50)
    empty = s.file_task(op="empty-ts", owner_agent="6", priority=50)
    s._tasks[bad.id].status = TaskStatus.NEEDS_APPROVAL
    s._tasks[bad.id].updated_at = "not-an-iso-string"
    s._tasks[empty.id].status = TaskStatus.NEEDS_APPROVAL
    s._tasks[empty.id].updated_at = ""

    reconciled = s.reconcile_stale_gated(stale_seconds=1.0)

    assert reconciled == []


def test_noop_on_empty_scheduler(tmp_path: Path) -> None:
    s = Scheduler(queue_log=tmp_path / "queue.jsonl")
    assert s.reconcile_stale_gated(stale_seconds=1.0) == []


def test_idempotent_after_first_pass(tmp_path: Path) -> None:
    s = Scheduler(queue_log=tmp_path / "queue.jsonl")
    task = s.file_task(op="idem", owner_agent="6", priority=50)
    _set_status_with_age(s, task.id, TaskStatus.NEEDS_APPROVAL, age_seconds=8 * 86400)

    first = s.reconcile_stale_gated(stale_seconds=7 * 86400.0)
    second = s.reconcile_stale_gated(stale_seconds=7 * 86400.0)

    assert first == [task.id]
    assert second == []
    assert s._tasks[task.id].status == TaskStatus.DEAD_LETTER


def test_returns_exact_reaped_ids(tmp_path: Path) -> None:
    s = Scheduler(queue_log=tmp_path / "queue.jsonl")
    stale_a = s.file_task(op="mix-a", owner_agent="6", priority=50)
    stale_b = s.file_task(op="mix-b", owner_agent="6", priority=50)
    fresh = s.file_task(op="mix-fresh", owner_agent="6", priority=50)
    in_prog = s.file_task(op="mix-inprog", owner_agent="6", priority=50)
    _set_status_with_age(s, stale_a.id, TaskStatus.NEEDS_APPROVAL, age_seconds=8 * 86400)
    _set_status_with_age(s, stale_b.id, TaskStatus.AGENT0_REVIEW, age_seconds=8 * 86400)
    _set_status_with_age(s, fresh.id, TaskStatus.NEEDS_APPROVAL, age_seconds=60)
    _set_status_with_age(s, in_prog.id, TaskStatus.IN_PROGRESS, age_seconds=8 * 86400)

    reconciled = s.reconcile_stale_gated(stale_seconds=7 * 86400.0)

    assert set(reconciled) == {stale_a.id, stale_b.id}
    assert len(reconciled) == 2

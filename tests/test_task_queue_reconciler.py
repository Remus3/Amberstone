"""Audit-8 H-02 closure - pin the task_queue.jsonl reconciler behavior.

The Phase 3 scheduler ships a periodic reconciler that closes out
IN_PROGRESS task envelopes whose ``updated_at`` is older than the
stale threshold. The reconciler emits a terminal ``failed`` event via
``Scheduler.fail()`` so the per-task last-event tally converges and the
filed -> dispatched -> completed/failed math reconciles.

These tests pin:

  * The happy path: a stale IN_PROGRESS task is reaped.
  * The negative path: a fresh IN_PROGRESS task is left alone.
  * Terminal events for non-IN_PROGRESS statuses (READY, COMPLETED,
    FAILED, NEEDS_APPROVAL) are NOT reaped.
  * The fail event is written to task_queue.jsonl in the existing
    schema (event=failed + status=failed + last_error=reason).
  * The boot-time / supervisor-restart reason path emits the correct
    error tag.
  * The custom stale_seconds threshold is honored.
  * Malformed updated_at is skipped (defensive against historic logs).
  * Reconciler is no-op when scheduler is empty.
  * Returned list contains exactly the reconciled task IDs.
  * Idempotence: a second reconcile pass over an already-reaped task
    is a no-op.
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

from agents.agent1_lead.scheduler import Scheduler, TaskStatus  # noqa: E402


def _set_in_progress_with_age(s: Scheduler, task_id: str, age_seconds: float) -> None:
    """Force a task into IN_PROGRESS with a synthetic ``updated_at``.

    The reconciler reads ``t.updated_at`` (an ISO string) and the
    in-memory dict; this helper backdates both consistently so the test
    does not have to wait real wall-clock time.
    """
    t = s._tasks[task_id]
    t.status = TaskStatus.IN_PROGRESS
    backdated = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    t.updated_at = backdated.isoformat()


def _read_last_event_for(log_path: Path, task_id: str) -> dict | None:
    """Return the most-recent JSONL event for ``task_id`` or None."""
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
# Stale IN_PROGRESS reaping
# ---------------------------------------------------------------------------


def test_reconciler_reaps_stale_in_progress_task(tmp_path: Path) -> None:
    """A 30-minute-old in_progress task is closed with a terminal failed event."""
    log = tmp_path / "queue.jsonl"
    s = Scheduler(queue_log=log)
    task = s.file_task(op="stale-test", owner_agent="6", priority=50)
    _set_in_progress_with_age(s, task.id, age_seconds=2400)  # 40 min

    reconciled = s.reconcile_stale_in_progress(stale_seconds=1800.0)

    assert reconciled == [task.id]
    assert s._tasks[task.id].status == TaskStatus.FAILED
    assert s._tasks[task.id].last_error == "timeout-no-terminal-event"


def test_reconciler_skips_fresh_in_progress_task(tmp_path: Path) -> None:
    """A 5-minute-old in_progress task must NOT be reaped (under 30 min)."""
    log = tmp_path / "queue.jsonl"
    s = Scheduler(queue_log=log)
    task = s.file_task(op="fresh-test", owner_agent="6", priority=50)
    _set_in_progress_with_age(s, task.id, age_seconds=300)  # 5 min

    reconciled = s.reconcile_stale_in_progress(stale_seconds=1800.0)

    assert reconciled == []
    assert s._tasks[task.id].status == TaskStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# Status-gating: only IN_PROGRESS is candidate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [
        TaskStatus.READY,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.NEEDS_APPROVAL,
        TaskStatus.DEAD_LETTER,
        TaskStatus.RETRY_PENDING,
        TaskStatus.AGENT0_REVIEW,
    ],
)
def test_reconciler_only_targets_in_progress(tmp_path: Path, status: str) -> None:
    """Other statuses (READY/COMPLETED/FAILED/NEEDS_APPROVAL) are off-limits."""
    log = tmp_path / "queue.jsonl"
    s = Scheduler(queue_log=log)
    task = s.file_task(op=f"status-{status}", owner_agent="6", priority=50)
    # Backdate updated_at well past the threshold but mark non-IN_PROGRESS.
    t = s._tasks[task.id]
    t.status = status
    backdated = datetime.now(timezone.utc) - timedelta(hours=24)
    t.updated_at = backdated.isoformat()

    reconciled = s.reconcile_stale_in_progress(stale_seconds=1800.0)

    assert reconciled == []
    assert s._tasks[task.id].status == status


# ---------------------------------------------------------------------------
# JSONL terminal event written
# ---------------------------------------------------------------------------


def test_reconciler_writes_terminal_failed_event(tmp_path: Path) -> None:
    """The failed event is appended to task_queue.jsonl with the right shape."""
    log = tmp_path / "queue.jsonl"
    s = Scheduler(queue_log=log)
    task = s.file_task(op="event-shape-test", owner_agent="6", priority=50)
    _set_in_progress_with_age(s, task.id, age_seconds=2400)

    s.reconcile_stale_in_progress(stale_seconds=1800.0)

    last = _read_last_event_for(log, task.id)
    assert last is not None
    assert last.get("event") == "failed"
    assert last.get("task", {}).get("status") == "failed"
    assert last.get("task", {}).get("last_error") == "timeout-no-terminal-event"
    # The terminal event MUST update updated_at so reload sees the new state.
    assert last.get("task", {}).get("updated_at")


# ---------------------------------------------------------------------------
# Custom reason / supervisor-restart path
# ---------------------------------------------------------------------------


def test_reconciler_honors_custom_reason(tmp_path: Path) -> None:
    """A supervisor-restart caller passes reason='supervisor-restart'."""
    log = tmp_path / "queue.jsonl"
    s = Scheduler(queue_log=log)
    task = s.file_task(op="reason-test", owner_agent="6", priority=50)
    _set_in_progress_with_age(s, task.id, age_seconds=7200)  # 2h

    reconciled = s.reconcile_stale_in_progress(
        stale_seconds=1800.0, reason="supervisor-restart",
    )

    assert reconciled == [task.id]
    assert s._tasks[task.id].last_error == "supervisor-restart"
    last = _read_last_event_for(log, task.id)
    assert last is not None
    assert last.get("task", {}).get("last_error") == "supervisor-restart"


# ---------------------------------------------------------------------------
# Threshold tuning
# ---------------------------------------------------------------------------


def test_reconciler_threshold_overridable(tmp_path: Path) -> None:
    """Passing stale_seconds=60 reaps a task aged 90s but not 30s."""
    log = tmp_path / "queue.jsonl"
    s = Scheduler(queue_log=log)
    task_a = s.file_task(op="thresh-a", owner_agent="6", priority=50)
    task_b = s.file_task(op="thresh-b", owner_agent="6", priority=50)
    _set_in_progress_with_age(s, task_a.id, age_seconds=90)
    _set_in_progress_with_age(s, task_b.id, age_seconds=30)

    reconciled = s.reconcile_stale_in_progress(stale_seconds=60.0)

    assert reconciled == [task_a.id]
    assert s._tasks[task_a.id].status == TaskStatus.FAILED
    assert s._tasks[task_b.id].status == TaskStatus.IN_PROGRESS


def test_reconciler_zero_or_negative_threshold_is_noop(tmp_path: Path) -> None:
    """stale_seconds<=0 disables the reconciler (safety valve)."""
    log = tmp_path / "queue.jsonl"
    s = Scheduler(queue_log=log)
    task = s.file_task(op="zero-thresh", owner_agent="6", priority=50)
    _set_in_progress_with_age(s, task.id, age_seconds=86400)

    assert s.reconcile_stale_in_progress(stale_seconds=0.0) == []
    assert s.reconcile_stale_in_progress(stale_seconds=-1.0) == []
    assert s._tasks[task.id].status == TaskStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# Defensive: malformed timestamps
# ---------------------------------------------------------------------------


def test_reconciler_skips_malformed_updated_at(tmp_path: Path) -> None:
    """A task with garbage in updated_at is skipped, not crashed on."""
    log = tmp_path / "queue.jsonl"
    s = Scheduler(queue_log=log)
    task = s.file_task(op="malformed", owner_agent="6", priority=50)
    t = s._tasks[task.id]
    t.status = TaskStatus.IN_PROGRESS
    t.updated_at = "not-an-iso-string-at-all"

    # Must NOT raise; must NOT reap.
    reconciled = s.reconcile_stale_in_progress(stale_seconds=1.0)

    assert reconciled == []
    assert s._tasks[task.id].status == TaskStatus.IN_PROGRESS


def test_reconciler_skips_empty_updated_at(tmp_path: Path) -> None:
    """A task with empty-string updated_at is skipped."""
    log = tmp_path / "queue.jsonl"
    s = Scheduler(queue_log=log)
    task = s.file_task(op="empty-ts", owner_agent="6", priority=50)
    t = s._tasks[task.id]
    t.status = TaskStatus.IN_PROGRESS
    t.updated_at = ""

    reconciled = s.reconcile_stale_in_progress(stale_seconds=1.0)

    assert reconciled == []


# ---------------------------------------------------------------------------
# Empty scheduler / no-op safety
# ---------------------------------------------------------------------------


def test_reconciler_noop_on_empty_scheduler(tmp_path: Path) -> None:
    """A scheduler with zero tasks reconciles to []."""
    log = tmp_path / "queue.jsonl"
    s = Scheduler(queue_log=log)

    assert s.reconcile_stale_in_progress(stale_seconds=1800.0) == []


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------


def test_reconciler_idempotent_after_first_pass(tmp_path: Path) -> None:
    """A second reconcile over the same already-failed task is a no-op."""
    log = tmp_path / "queue.jsonl"
    s = Scheduler(queue_log=log)
    task = s.file_task(op="idempotent-test", owner_agent="6", priority=50)
    _set_in_progress_with_age(s, task.id, age_seconds=2400)

    first = s.reconcile_stale_in_progress(stale_seconds=1800.0)
    second = s.reconcile_stale_in_progress(stale_seconds=1800.0)

    assert first == [task.id]
    assert second == []
    assert s._tasks[task.id].status == TaskStatus.FAILED


# ---------------------------------------------------------------------------
# Returned task IDs are exact
# ---------------------------------------------------------------------------


def test_reconciler_returns_exact_reaped_ids(tmp_path: Path) -> None:
    """A mix of stale + fresh + non-in_progress returns only the stale ids."""
    log = tmp_path / "queue.jsonl"
    s = Scheduler(queue_log=log)
    stale_a = s.file_task(op="stale-mix-a", owner_agent="6", priority=50)
    stale_b = s.file_task(op="stale-mix-b", owner_agent="6", priority=50)
    fresh = s.file_task(op="fresh-mix", owner_agent="6", priority=50)
    completed = s.file_task(op="completed-mix", owner_agent="6", priority=50)
    _set_in_progress_with_age(s, stale_a.id, age_seconds=3600)
    _set_in_progress_with_age(s, stale_b.id, age_seconds=3600)
    _set_in_progress_with_age(s, fresh.id, age_seconds=30)
    s.complete(completed.id)

    reconciled = s.reconcile_stale_in_progress(stale_seconds=1800.0)

    assert set(reconciled) == {stale_a.id, stale_b.id}
    assert len(reconciled) == 2


# ---------------------------------------------------------------------------
# Reload semantics: reaped task survives a Scheduler restart
# ---------------------------------------------------------------------------


def test_reaped_task_survives_scheduler_reload(tmp_path: Path) -> None:
    """A reaped task is loaded as FAILED by a fresh Scheduler instance."""
    log = tmp_path / "queue.jsonl"
    s = Scheduler(queue_log=log)
    task = s.file_task(op="reload-test", owner_agent="6", priority=50)
    _set_in_progress_with_age(s, task.id, age_seconds=2400)

    # Write the failed event to disk.
    s.reconcile_stale_in_progress(stale_seconds=1800.0)
    assert s._tasks[task.id].status == TaskStatus.FAILED

    # A second Scheduler instance (simulates supervisor restart) loads
    # the latest event and must see the task as FAILED, not IN_PROGRESS.
    s2 = Scheduler(queue_log=log)
    assert s2._tasks[task.id].status == TaskStatus.FAILED


# ---------------------------------------------------------------------------
# Static helper: timestamp parsing
# ---------------------------------------------------------------------------


def test_parse_iso_ts_handles_z_suffix() -> None:
    """The static parser accepts Z-suffix ISO timestamps (defensive)."""
    dt = Scheduler._parse_iso_ts("2026-05-25T00:00:00Z")
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_iso_ts_handles_offset_suffix() -> None:
    """The static parser accepts +00:00 offset timestamps (canonical)."""
    dt = Scheduler._parse_iso_ts("2026-05-25T00:00:00+00:00")
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_iso_ts_returns_none_on_garbage() -> None:
    """The static parser returns None for malformed input."""
    assert Scheduler._parse_iso_ts(None) is None
    assert Scheduler._parse_iso_ts("") is None
    assert Scheduler._parse_iso_ts("not-iso") is None


def test_parse_iso_ts_naive_treated_as_utc() -> None:
    """A naive (no-tz) timestamp is defensively treated as UTC."""
    dt = Scheduler._parse_iso_ts("2026-05-25T00:00:00")
    assert dt is not None
    assert dt.tzinfo == timezone.utc

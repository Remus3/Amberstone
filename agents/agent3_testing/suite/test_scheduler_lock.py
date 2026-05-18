"""Tests for cross-process append lock on task_queue.jsonl (audit P-audit-h2)
and for the cross-process dispatch race guard (P-audit3-followup-single-scheduler).

Lock tests: spawn two subprocesses that hammer the same log file and
verify that every appended line parses as valid JSON - proving writes
are never interleaved at byte level.

Race guard tests: verify that next_ready() re-reads disk before dispatching
so a task completed by a second Scheduler instance is not re-dispatched.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# AUDIT P-audit3-m03 (2026-04-22): prefer current interpreter.
PY = Path(os.environ.get("RC_PYTHON") or sys.executable)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


WRITER_SCRIPT = r"""
import sys, pathlib
sys.path.insert(0, r'{root}')
from agents.agent1_lead import Scheduler
s = Scheduler(queue_log=pathlib.Path(r'{log}'))
for i in range({count}):
    s.file_task(op=f'{tag}-{{i:03d}}', owner_agent='6', priority=50)
"""


@pytest.mark.timeout(90)
def test_two_processes_no_interleaved_lines(tmp_path: Path) -> None:
    log = tmp_path / "concurrent.jsonl"
    # 2×50 writes is enough to catch interleaving but survives the
    # filesystem pressure of the rest of the suite (previous 2×120
    # flaked on Windows under concurrent fixture tmp_path churn).
    count = 50

    def spawn(tag: str) -> subprocess.Popen:
        code = WRITER_SCRIPT.format(root=_PROJECT_ROOT, log=log, count=count, tag=tag)
        return subprocess.Popen(
            [str(PY), "-c", code],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    p1 = spawn("alpha")
    p2 = spawn("beta")
    out1 = p1.communicate(timeout=30)
    out2 = p2.communicate(timeout=30)
    assert p1.returncode == 0, out1[1].decode()
    assert p2.returncode == 0, out2[1].decode()

    # Every line must parse as JSON with a task.id field. That proves no
    # two writes smashed each other mid-line.
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= count * 2
    ids = set()
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            pytest.fail(f"corrupt line: {e}: {line[:80]!r}")
        ids.add(rec["task"]["id"])
    # Both writers contribute - at least 2*count distinct task ids.
    assert len(ids) >= count * 2


# ---------------------------------------------------------------------------
# Cross-process dispatch race guard (P-audit3-followup-single-scheduler)
# ---------------------------------------------------------------------------

def test_latest_status_from_log_returns_last_entry(tmp_path: Path) -> None:
    """_latest_status_from_log must return the *most recent* status in the log,
    not the first one."""
    sys.path.insert(0, str(_PROJECT_ROOT))
    from agents.agent1_lead.scheduler import Scheduler

    log = tmp_path / "race.jsonl"
    s = Scheduler(queue_log=log)
    task = s.file_task(op="test-race", owner_agent="6", priority=50)
    tid = task.id

    # At this point the log has a single 'filed' entry with status=ready.
    assert s._latest_status_from_log(tid) == "ready"

    # Simulate a second Scheduler process completing the task by writing
    # directly via a fresh Scheduler instance over the same file.
    s2 = Scheduler(queue_log=log)
    s2.complete(tid)

    # The original Scheduler's method must now see 'completed' as the latest.
    assert s._latest_status_from_log(tid) == "completed"


def test_next_ready_skips_task_completed_by_second_instance(tmp_path: Path) -> None:
    """next_ready() must not dispatch a task that a concurrent Scheduler
    instance already marked completed on disk, even though the first
    Scheduler's in-memory heap still has it as READY."""
    sys.path.insert(0, str(_PROJECT_ROOT))
    from agents.agent1_lead.scheduler import Scheduler, TaskStatus

    log = tmp_path / "race2.jsonl"
    s1 = Scheduler(queue_log=log)
    task = s1.file_task(op="test-no-redispatch", owner_agent="6", priority=50)
    tid = task.id

    # Second instance (simulates ops script) completes the task.
    s2 = Scheduler(queue_log=log)
    s2.complete(tid)

    # s1's in-memory state still shows the task as READY and it's on the heap.
    assert s1._tasks[tid].status == TaskStatus.READY

    # next_ready() must detect the disk-level completion and return None.
    result = s1.next_ready()
    assert result is None, (
        f"next_ready() returned {result} - stale task was re-dispatched "
        "despite being completed by a concurrent Scheduler"
    )
    # In-memory state should have been synced to the disk status.
    assert s1._tasks[tid].status == TaskStatus.COMPLETED


def test_next_ready_still_dispatches_genuinely_ready_task(tmp_path: Path) -> None:
    """Sanity check: the race guard must not block tasks that truly are READY."""
    sys.path.insert(0, str(_PROJECT_ROOT))
    from agents.agent1_lead.scheduler import Scheduler, TaskStatus

    log = tmp_path / "race3.jsonl"
    s = Scheduler(queue_log=log)
    task = s.file_task(op="test-dispatch-ok", owner_agent="6", priority=50)

    result = s.next_ready()
    assert result is not None
    assert result.id == task.id
    assert result.status == TaskStatus.IN_PROGRESS

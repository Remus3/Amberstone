"""Unit tests for Agent 1 scheduler."""
from __future__ import annotations

from pathlib import Path

import pytest

from agents.agent0_gatekeeper.evaluator import Evaluator
from agents.agent1_lead import Scheduler, TaskStatus


@pytest.fixture()
def scheduler(tmp_path: Path) -> Scheduler:
    return Scheduler(queue_log=tmp_path / "q.jsonl",
                     agent0_evaluate=Evaluator().evaluate)


def test_ungated_goes_straight_to_ready(scheduler: Scheduler) -> None:
    t = scheduler.file_task("audit", owner_agent="6", priority=10)
    assert t.status == TaskStatus.READY


def test_hard_gate_requires_approval(scheduler: Scheduler) -> None:
    t = scheduler.file_task("archive", owner_agent="6", priority=50, categories=[8])
    assert t.status == TaskStatus.NEEDS_APPROVAL
    # approve moves to ready
    scheduler.approve(t.id)
    assert scheduler.get(t.id).status == TaskStatus.READY


def test_cross_machine_ok_payload_reaches_ready(scheduler: Scheduler) -> None:
    t = scheduler.file_task(
        "push-web-ui", owner_agent="5", priority=30, categories=[5],
        payload={"remote_path": r"\\192.168.8.237\RCClient\web\x.html", "payload_ext": ".html"},
    )
    assert t.status == TaskStatus.READY


def test_cross_machine_bad_payload_dead_letters(scheduler: Scheduler) -> None:
    t = scheduler.file_task(
        "push-web-ui", owner_agent="5", priority=30, categories=[5],
        payload={"remote_path": r"\\192.168.8.237\RCClient\etc\x.html", "payload_ext": ".html"},
    )
    assert t.status == TaskStatus.DEAD_LETTER


def test_user_override_bypasses_agent0_reject(scheduler: Scheduler) -> None:
    t = scheduler.file_task(
        "push-web-ui", owner_agent="5", priority=30, categories=[5],
        user_override=True,
        payload={"remote_path": r"\\192.168.8.237\RCClient\etc\x.html", "payload_ext": ".html"},
    )
    assert t.status == TaskStatus.READY


def test_dispatch_is_priority_ordered(scheduler: Scheduler) -> None:
    scheduler.file_task("low", owner_agent="6", priority=100)
    scheduler.file_task("high", owner_agent="6", priority=1)
    scheduler.file_task("mid", owner_agent="6", priority=50)

    assert scheduler.next_ready().op == "high"
    assert scheduler.next_ready().op == "mid"
    assert scheduler.next_ready().op == "low"


def test_persistence_replay(tmp_path: Path) -> None:
    log = tmp_path / "q.jsonl"
    s1 = Scheduler(queue_log=log, agent0_evaluate=Evaluator().evaluate)
    t = s1.file_task("audit", owner_agent="6", priority=10)
    s1.next_ready()        # moves to in_progress
    s1.complete(t.id, result={"ok": True})

    s2 = Scheduler(queue_log=log, agent0_evaluate=Evaluator().evaluate)
    assert s2.get(t.id).status == TaskStatus.COMPLETED
    assert s2.get(t.id).result == {"ok": True}


def test_unknown_blocked_by_is_dropped_not_silently_stalled(tmp_path: Path, caplog) -> None:
    """Audit M4 — dropping unknown deps is safer than silently stalling."""
    import logging
    s = Scheduler(queue_log=tmp_path / "q.jsonl", agent0_evaluate=Evaluator().evaluate)
    with caplog.at_level(logging.WARNING, logger="agent1.scheduler"):
        t = s.file_task("audit", owner_agent="6", priority=10,
                        blocked_by=["t-does-not-exist"])
    assert t.blocked_by == []               # unknown id dropped
    assert any("unknown blocked_by" in rec.getMessage() for rec in caplog.records)
    assert s.next_ready().id == t.id        # dispatches normally


def test_blocked_by_dependency_waits_for_completion(tmp_path: Path) -> None:
    s = Scheduler(queue_log=tmp_path / "q.jsonl", agent0_evaluate=Evaluator().evaluate)
    first = s.file_task("first", owner_agent="6", priority=10)
    second = s.file_task("second", owner_agent="6", priority=5, blocked_by=[first.id])
    # second has smaller (=higher) priority but is blocked. Scheduler should
    # skip it and dispatch `first` (priority 10, unblocked) first.
    got = s.next_ready()
    assert got.id == first.id
    # `second` still can't dispatch — first is in_progress, not completed.
    assert s.next_ready() is None
    s.complete(first.id)
    # Now second is unblocked.
    assert s.next_ready().id == second.id


def test_compact_keeps_latest_per_task(tmp_path: Path) -> None:
    """compact() rewrites task_queue.jsonl to the latest event per task_id.

    Verifies (a) line count drops to distinct task ids, (b) reload from
    the compacted file yields the same in-memory state as before.
    """
    log = tmp_path / "q.jsonl"
    s1 = Scheduler(queue_log=log, agent0_evaluate=Evaluator().evaluate,
                   compact_interval_s=0)  # disable daemon
    t_done = s1.file_task("done-task", owner_agent="6", priority=10)
    s1.next_ready()            # filed → dispatched
    s1.complete(t_done.id, result={"ok": True})
    t_open = s1.file_task("open-task", owner_agent="6", priority=20)
    # log now has: filed, dispatched, completed, filed = 4 lines, 2 task_ids

    raw = log.read_text(encoding="utf-8").splitlines()
    assert len(raw) == 4

    before, after = s1.compact()
    assert (before, after) == (4, 2)

    raw2 = log.read_text(encoding="utf-8").splitlines()
    assert len(raw2) == 2

    # State after reload is identical
    s2 = Scheduler(queue_log=log, agent0_evaluate=Evaluator().evaluate,
                   compact_interval_s=0)
    assert s2.get(t_done.id).status == TaskStatus.COMPLETED
    assert s2.get(t_done.id).result == {"ok": True}
    assert s2.get(t_open.id).status == TaskStatus.READY
    # Heap rebuilt: only the non-terminal task is dispatchable
    assert s2.next_ready().id == t_open.id
    assert s2.next_ready() is None


def test_compact_is_idempotent_when_already_unique(tmp_path: Path) -> None:
    """compact() on a file that's already 1-line-per-task is a no-op."""
    log = tmp_path / "q.jsonl"
    s = Scheduler(queue_log=log, agent0_evaluate=Evaluator().evaluate,
                  compact_interval_s=0)
    s.file_task("a", owner_agent="6", priority=10)
    s.file_task("b", owner_agent="6", priority=10)
    before_lines = log.read_text(encoding="utf-8").splitlines()
    assert len(before_lines) == 2  # one filed event each

    before, after = s.compact()
    assert (before, after) == (2, 2)
    assert log.read_text(encoding="utf-8").splitlines() == before_lines


def test_compact_skips_corrupt_lines(tmp_path: Path) -> None:
    """Corrupt lines are dropped on compaction."""
    log = tmp_path / "q.jsonl"
    s = Scheduler(queue_log=log, agent0_evaluate=Evaluator().evaluate,
                  compact_interval_s=0)
    t = s.file_task("a", owner_agent="6", priority=10)
    with log.open("a", encoding="utf-8") as f:
        f.write("not-json-at-all\n")
    s.complete(t.id)
    raw = log.read_text(encoding="utf-8").splitlines()
    assert len(raw) == 3  # filed + corrupt + completed

    before, after = s.compact()
    assert (before, after) == (3, 1)
    raw2 = log.read_text(encoding="utf-8").splitlines()
    assert len(raw2) == 1
    assert "not-json-at-all" not in raw2[0]

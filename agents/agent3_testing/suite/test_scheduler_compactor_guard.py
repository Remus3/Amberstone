"""RM-983: the agent3 suite's conftest stops every agent1 Scheduler
compactor a test starts at that test's teardown (tests/_scheduler_compactor_guard.py;
the tests/ twin is tests/test_scheduler_compactor_guard_s144q12.py). Runs in
file order: the first test proves a default Scheduler starts its compactor, the
second that it did not outlive the first test."""
from __future__ import annotations

from typing import TYPE_CHECKING

from agents.agent1_lead import Scheduler

if TYPE_CHECKING:
    import threading

_SEEN: list[threading.Thread] = []


def test_a_default_scheduler_starts_its_compactor(tmp_path):
    sched = Scheduler(queue_log=tmp_path / "q.jsonl")
    thread = sched._compact_thread
    assert thread is not None and thread.is_alive()
    _SEEN.append(thread)


def test_that_compactor_did_not_outlive_its_test():
    assert len(_SEEN) == 1, "the test above must run first, in this file"
    assert not _SEEN[0].is_alive(), (
        "the agent1-compact thread the previous test started is still running")

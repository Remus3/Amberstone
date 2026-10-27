"""RM-983 (RM-909 follow-up (c), first root cause): no agent1 Scheduler
compactor thread started by a test outlives that test.

`agents/agent1_lead/scheduler.py` `Scheduler.__init__` starts a daemon
"agent1-compact" thread whenever `compact_interval_s > 0`, and the default is
3600 s. A test that builds a Scheduler with the default and never calls
`stop_compactor()` leaves that thread waiting for an hour, for the rest of the
xdist worker's life. Measured on the s144 lane base, one file per process:
tests/test_rm853_task_last_error_scrub.py left 30 of them,
tests/test_task_queue_gate_limbo_reconciler.py 21 and
tests/test_task_queue_reconciler.py 20; nine agents/agent3_testing/suite files
left 4 to 11 each, some through constructors that build a Scheduler for the
caller (agents/agent7_context InputParser / UIFeedback). Every such thread is
noise for the per-test and per-module thread checks (RM-909, RM-982).

tests/_scheduler_compactor_guard.py records every compactor a test starts and
stops it at that test's teardown (autouse in tests/conftest.py and in
agents/agent3_testing/suite/conftest.py). The pair below runs in file order:
the first test builds a default Scheduler and proves its compactor is running
(so the second cannot pass on a Scheduler that never started one); the second
proves the guard stopped it after the first test ended. The pair needs file
order, so it holds under `--dist loadfile` (the gated suite) and not under
`--dist load` or a random-order plugin; the `len(_SEEN) == 1` assert says so.
"""
from __future__ import annotations

import threading

from agents.agent1_lead.scheduler import Scheduler
from tests import _scheduler_compactor_guard

_SEEN: list[threading.Thread] = []


def test_a_default_scheduler_starts_its_compactor(tmp_path):
    sched = Scheduler(queue_log=tmp_path / "task_queue.jsonl")
    thread = sched._compact_thread
    assert thread is not None, "the default interval must start a compactor"
    assert thread.is_alive()
    assert thread.name == "agent1-compact"
    _SEEN.append(thread)


def test_that_compactor_did_not_outlive_its_test():
    assert len(_SEEN) == 1, "the test above must run first, in this file"
    assert not _SEEN[0].is_alive(), (
        "the agent1-compact thread the previous test started is still "
        "running after that test ended")


def test_stop_stops_every_recorded_compactor_and_clears_the_record(
        tmp_path, monkeypatch):
    started = _scheduler_compactor_guard.track(monkeypatch)
    first = Scheduler(queue_log=tmp_path / "a.jsonl")
    second = Scheduler(queue_log=tmp_path / "b.jsonl")
    threads = [first._compact_thread, second._compact_thread]
    assert started == [first, second]
    assert all(t is not None and t.is_alive() for t in threads)
    _scheduler_compactor_guard.stop(started)
    assert not any(t.is_alive() for t in threads)
    assert started == []


def test_a_disabled_compactor_is_not_recorded(tmp_path, monkeypatch):
    started = _scheduler_compactor_guard.track(monkeypatch)
    sched = Scheduler(queue_log=tmp_path / "q.jsonl", compact_interval_s=0)
    assert sched._compact_thread is None
    assert started == []


def test_stop_tolerates_a_compactor_its_test_already_stopped(
        tmp_path, monkeypatch):
    started = _scheduler_compactor_guard.track(monkeypatch)
    sched = Scheduler(queue_log=tmp_path / "q.jsonl")
    sched.stop_compactor()
    _scheduler_compactor_guard.stop(started)
    assert sched._compact_thread is None
    assert started == []

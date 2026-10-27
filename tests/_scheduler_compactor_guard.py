"""No agent1 Scheduler compactor thread started by a test may outlive that
test (RM-983, RM-909 follow-up (c)).

`Scheduler.__init__` (agents/agent1_lead/scheduler.py) starts a daemon
"agent1-compact" thread whenever `compact_interval_s > 0`; the default is
3600 s, so a Scheduler a test builds with the default and never stops leaves a
thread waiting for an hour, for the rest of the pytest worker's life. Some
constructors build one for the caller (agents/agent7_context InputParser /
UIFeedback, agents/supervisor.py Supervisor), so passing
`compact_interval_s=0` at each call site cannot reach every path. This helper
wraps the class's own start method for the duration of one test instead:

  track(monkeypatch) -> list   records every Scheduler whose compactor starts
                               while the patch is in force;
  stop(started)                stops each recorded compactor (the class's own
                               `stop_compactor()`, which joins) and clears the
                               record.

Wired autouse from tests/conftest.py and agents/agent3_testing/suite/conftest.py.
A compactor started outside a function-scoped test (at import, or in a module
or session fixture) is not recorded; none exists in either tree today.
"""
from __future__ import annotations


def track(monkeypatch) -> list:
    from agents.agent1_lead.scheduler import Scheduler

    started: list = []
    real_start = Scheduler._start_compactor

    def _recording_start(self) -> None:
        started.append(self)
        real_start(self)

    monkeypatch.setattr(Scheduler, "_start_compactor", _recording_start)
    return started


def stop(started: list) -> None:
    while started:
        started.pop(0).stop_compactor()

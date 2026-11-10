"""True-audit (s144 lane true-audit cycle 152) of
agents/agent4_coach_mentor/advisory_sweeper.py.

The sweeper runs on the supervisor's analyze pass (agents/supervisor.py,
inside ``asyncio.to_thread``) and completes READY advisory tasks older
than ``max_age_hours``. Each defect below had a test RED against the
pre-audit module (RM-1893..RM-1899); the remaining tests characterize the
well-formed path:

- RM-1893: a naive (no-offset) ``created_at`` raised TypeError (naive vs
  aware compare) out of the sweep, so every task after it went unswept on
  every pass;
- RM-1894: a task whose ``op`` is unhashable (a list from a junk queue
  record) raised TypeError out of the sweep;
- RM-1895: ``max_age_hours`` NaN / inf / huge / str raised out of the
  sweep, a negative value dismissed FRESH advisories, and a bool was read
  as 1 hour;
- RM-1896: a bare-string ``ops`` did substring matching (an op "" or
  "cold" was swept) and ``ops=None`` raised TypeError;
- RM-1897: a task the scheduler no longer holds (``complete`` returned
  None) was reported as dismissed, and a task that left READY between the
  snapshot and the dismissal (picked up by a dispatcher) was overwritten
  to COMPLETED;
- RM-1898: a far-future or unparseable ``created_at`` pinned a READY
  advisory forever; the sweeper now falls back to ``updated_at`` and
  counts a task with neither usable in ``unparseable``;
- RM-1899: a ``list_by_status`` result that is not iterable, or holds an
  element that is not a task, raised out of the sweep.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

import agents.agent4_coach_mentor.advisory_sweeper as sw

if TYPE_CHECKING:
    from pathlib import Path


def _ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


_DEFAULT = object()


class FakeTask:
    def __init__(self, tid="t1", op="cold-streak-advisory", created_at=_DEFAULT,
                 updated_at=_DEFAULT, status="ready") -> None:
        self.id = tid
        self.op = op
        self.created_at = _ago(100) if created_at is _DEFAULT else created_at
        self.updated_at = _ago(100) if updated_at is _DEFAULT else updated_at
        self.status = status


class FakeScheduler:
    def __init__(self, tasks=None, ready=None) -> None:
        self.tasks = {t.id: t for t in (tasks or []) if hasattr(t, "id")}
        self._ready = ready
        self.completed: list = []

    def list_by_status(self, status):
        if self._ready is not None:
            return self._ready
        return [t for t in self.tasks.values() if t.status == status]

    def get(self, tid):
        return self.tasks.get(tid)

    def complete(self, tid, result=None):
        t = self.tasks.get(tid)
        if t is None:
            return None
        t.status = "completed"
        t.result = result
        self.completed.append(tid)
        return t


def _real_scheduler(tmp_path: Path):
    from agents.agent1_lead import Scheduler
    return Scheduler(queue_log=tmp_path / "q.jsonl")


def _file(s, op="cold-streak-advisory"):
    return s.file_task(op=op, owner_agent="1", priority=70,
                       payload={"mode": "aram"}, user_override=True)


# -- characterization (well-formed path) ------------------------------

def test_char_stale_dismissed_with_audit_marker(tmp_path: Path) -> None:
    s = _real_scheduler(tmp_path)
    t = _file(s)
    s.get(t.id).created_at = _ago(100)
    out = sw.sweep_stale(s, max_age_hours=72)
    assert [d["task_id"] for d in out["dismissed"]] == [t.id]
    assert out["inspected"] == 1
    res = s.get(t.id).result
    assert res["source"] == "auto-stale"
    assert res["prior_status"] == "ready"
    assert 99.0 <= res["age_hours"] <= 101.0
    assert isinstance(res["dismissed_at"], str)
    assert s.get(t.id).status == "completed"


def test_char_fresh_and_foreign_ops_untouched(tmp_path: Path) -> None:
    s = _real_scheduler(tmp_path)
    fresh = _file(s)
    other = _file(s, op="some-other-op")
    s.get(other.id).created_at = _ago(500)
    out = sw.sweep_stale(s)
    assert out["dismissed"] == []
    assert out["inspected"] == 1
    assert s.get(fresh.id).status == "ready"
    assert s.get(other.id).status == "ready"


def test_char_z_suffix_parsed() -> None:
    stamp = (datetime.now(timezone.utc) - timedelta(hours=80)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    s = FakeScheduler([FakeTask(created_at=stamp)])
    assert len(sw.sweep_stale(s)["dismissed"]) == 1


def test_char_complete_raise_is_logged_not_raised(caplog) -> None:
    class Boom(FakeScheduler):
        def complete(self, tid, result=None):
            raise OSError("disk full")
    s = Boom([FakeTask()])
    with caplog.at_level(logging.WARNING, logger="agent4.advisory_sweeper"):
        out = sw.sweep_stale(s)
    assert out["dismissed"] == []
    assert "disk full" in caplog.text


def test_char_list_by_status_raise_returns_empty() -> None:
    class Boom(FakeScheduler):
        def list_by_status(self, status):
            raise RuntimeError("down")
    out = sw.sweep_stale(Boom())
    assert out["dismissed"] == [] and out["inspected"] == 0


# -- RM-1893: naive created_at -------------------------------------

def test_naive_created_at_read_as_utc_and_does_not_abort() -> None:
    naive = (datetime.now(timezone.utc) - timedelta(hours=100)).replace(
        tzinfo=None).isoformat()
    a = FakeTask("a", created_at=naive)
    b = FakeTask("b")
    s = FakeScheduler([a, b])
    out = sw.sweep_stale(s)
    assert {d["task_id"] for d in out["dismissed"]} == {"a", "b"}


def test_naive_fresh_created_at_kept() -> None:
    naive = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    s = FakeScheduler([FakeTask(created_at=naive, updated_at=naive)])
    assert sw.sweep_stale(s)["dismissed"] == []


# -- RM-1894: unhashable / non-str op -------------------------------

@pytest.mark.parametrize("op", [["cold-streak-advisory"], {"a": 1}, None, 7])
def test_junk_op_skipped_and_sweep_continues(op) -> None:
    junk = FakeTask("junk", op=op)
    good = FakeTask("good")
    s = FakeScheduler([junk, good])
    out = sw.sweep_stale(s)
    assert [d["task_id"] for d in out["dismissed"]] == ["good"]
    assert junk.status == "ready"
    assert out["inspected"] == 1


# -- RM-1895: max_age_hours validation ------------------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"),
                                 "72", None, True, False, -5, 0, [72]])
def test_bad_max_age_falls_back_to_default(bad) -> None:
    fresh = FakeTask("fresh", created_at=_ago(10), updated_at=_ago(10))
    stale = FakeTask("stale", created_at=_ago(100))
    s = FakeScheduler([fresh, stale])
    out = sw.sweep_stale(s, max_age_hours=bad)
    assert [d["task_id"] for d in out["dismissed"]] == ["stale"]
    assert fresh.status == "ready"


def test_huge_max_age_sweeps_nothing_without_raising() -> None:
    s = FakeScheduler([FakeTask(created_at=_ago(100000))])
    out = sw.sweep_stale(s, max_age_hours=1e30)
    assert out["dismissed"] == []
    assert out["inspected"] == 1


def test_int_and_float_max_age_accepted() -> None:
    s = FakeScheduler([FakeTask(created_at=_ago(5), updated_at=_ago(5))])
    assert sw.sweep_stale(s, max_age_hours=6)["dismissed"] == []
    assert len(sw.sweep_stale(s, max_age_hours=4.5)["dismissed"]) == 1


# -- RM-1896: ops normalisation -------------------------------------

def test_bare_string_ops_is_exact_match_not_substring() -> None:
    empty = FakeTask("empty", op="")
    part = FakeTask("part", op="cold")
    exact = FakeTask("exact", op="cold-streak-advisory")
    s = FakeScheduler([empty, part, exact])
    out = sw.sweep_stale(s, ops="cold-streak-advisory")
    assert [d["task_id"] for d in out["dismissed"]] == ["exact"]
    assert empty.status == "ready" and part.status == "ready"


def test_ops_none_uses_default_set() -> None:
    s = FakeScheduler([FakeTask("c"), FakeTask("i", op="coaching-insight-advisory"),
                       FakeTask("x", op="other")])
    out = sw.sweep_stale(s, ops=None)
    assert {d["task_id"] for d in out["dismissed"]} == {"c", "i"}


def test_ops_list_with_junk_elements() -> None:
    s = FakeScheduler([FakeTask("c")])
    out = sw.sweep_stale(s, ops=["cold-streak-advisory", None, ["x"]])
    assert [d["task_id"] for d in out["dismissed"]] == ["c"]


def test_ops_non_iterable_uses_default_set() -> None:
    s = FakeScheduler([FakeTask("c")])
    assert len(sw.sweep_stale(s, ops=42)["dismissed"]) == 1


# -- RM-1897: task gone / left READY ---------------------------------

def test_complete_returning_none_is_not_reported_dismissed() -> None:
    class Gone(FakeScheduler):
        def complete(self, tid, result=None):
            return None
    s = Gone([FakeTask()])
    out = sw.sweep_stale(s)
    assert out["dismissed"] == []


def test_task_that_left_ready_after_snapshot_is_not_overwritten() -> None:
    t = FakeTask()

    class Racy(FakeScheduler):
        def list_by_status(self, status):
            snap = [t]
            t.status = "in_progress"   # a dispatcher picks it up meanwhile
            return snap
    s = Racy([t])
    out = sw.sweep_stale(s)
    assert out["dismissed"] == []
    assert t.status == "in_progress"
    assert s.completed == []


def test_task_removed_after_snapshot_is_not_completed() -> None:
    t = FakeTask()
    s = FakeScheduler([t])
    snap = [t]
    s.tasks.clear()
    s._ready = snap
    out = sw.sweep_stale(s)
    assert out["dismissed"] == []


# -- RM-1898: future / unparseable created_at -----------------------

def test_far_future_created_at_falls_back_to_updated_at() -> None:
    t = FakeTask(created_at="9999-01-01T00:00:00+00:00", updated_at=_ago(100))
    s = FakeScheduler([t])
    out = sw.sweep_stale(s)
    assert [d["task_id"] for d in out["dismissed"]] == ["t1"]
    assert t.result["age_basis"] == "updated_at"


def test_unparseable_created_at_falls_back_to_updated_at() -> None:
    t = FakeTask(created_at="not-a-date", updated_at=_ago(100))
    s = FakeScheduler([t])
    assert len(sw.sweep_stale(s)["dismissed"]) == 1


@pytest.mark.parametrize("junk", [None, 12345, ["x"], "", "9999-01-01T00:00:00Z"])
def test_no_usable_stamp_counted_and_kept(junk) -> None:
    t = FakeTask(created_at=junk, updated_at=junk)
    s = FakeScheduler([t])
    out = sw.sweep_stale(s)
    assert out["dismissed"] == []
    assert out["unparseable"] == 1
    assert t.status == "ready"


def test_small_clock_skew_future_is_fresh_not_unparseable() -> None:
    soon = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    s = FakeScheduler([FakeTask(created_at=soon, updated_at=soon)])
    out = sw.sweep_stale(s)
    assert out["dismissed"] == [] and out["unparseable"] == 0


def test_created_at_basis_recorded() -> None:
    t = FakeTask()
    sw.sweep_stale(FakeScheduler([t]))
    assert t.result["age_basis"] == "created_at"


# -- RM-1899: junk list_by_status result ----------------------------

@pytest.mark.parametrize("ready", [None, 5, object()])
def test_non_iterable_ready_list_is_empty(ready) -> None:
    class Junk(FakeScheduler):
        def list_by_status(self, status):
            return ready
    out = sw.sweep_stale(Junk([FakeTask()]))
    assert out["dismissed"] == [] and out["inspected"] == 0


def test_non_task_elements_skipped() -> None:
    good = FakeTask("good")
    s = FakeScheduler([good], ready=[None, "x", 3, {"op": "cold-streak-advisory"}, good])
    out = sw.sweep_stale(s)
    assert [d["task_id"] for d in out["dismissed"]] == ["good"]


def test_non_str_task_id_skipped() -> None:
    bad = FakeTask(tid=None)
    good = FakeTask("good")
    s = FakeScheduler([good], ready=[bad, good])
    out = sw.sweep_stale(s)
    assert [d["task_id"] for d in out["dismissed"]] == ["good"]


# -- result shape -------------------------------------------------------

def test_summary_keys_always_present() -> None:
    for out in (sw.sweep_stale(FakeScheduler()),
                sw.sweep_stale(FakeScheduler(ready=None.__class__))):
        assert {"dismissed", "inspected", "unparseable"} <= set(out)

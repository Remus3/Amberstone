"""Round 39 — advisory_sweeper: auto-dismiss stale advisory tasks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path


def _make_scheduler(tmp_path: Path):
    from agents.agent1_lead import Scheduler
    return Scheduler(queue_log=tmp_path / "q.jsonl")


def _backdate(scheduler, task_id: str, hours_ago: float) -> None:
    """Rewrite the task's created_at so we can simulate age without
    waiting. Scheduler keeps the task object in-memory; mutate it."""
    t = scheduler.get(task_id)
    assert t is not None
    backdated = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    t.created_at = backdated.isoformat()


# ── threshold ───────────────────────────────────────────────────────

def test_dismisses_tasks_older_than_threshold(tmp_path: Path) -> None:
    from agents.agent4_coach_mentor.advisory_sweeper import sweep_stale

    s = _make_scheduler(tmp_path)
    t = s.file_task(
        op="cold-streak-advisory", owner_agent="1", priority=70,
        payload={"mode": "aram", "champion": "Jinx"},
        user_override=True,
    )
    _backdate(s, t.id, hours_ago=100)

    out = sweep_stale(s, max_age_hours=72)
    assert len(out["dismissed"]) == 1
    assert out["dismissed"][0]["task_id"] == t.id
    assert s.get(t.id).status == "completed"
    result = s.get(t.id).result or {}
    assert result["source"] == "auto-stale"
    assert result["age_hours"] >= 72


def test_preserves_fresh_tasks(tmp_path: Path) -> None:
    from agents.agent4_coach_mentor.advisory_sweeper import sweep_stale

    s = _make_scheduler(tmp_path)
    t = s.file_task(
        op="cold-streak-advisory", owner_agent="1", priority=70,
        payload={"mode": "aram", "champion": "Jinx"},
        user_override=True,
    )
    # Task was just filed — well under 72 h.
    out = sweep_stale(s, max_age_hours=72)
    assert out["dismissed"] == []
    assert s.get(t.id).status == "ready"


def test_only_affects_advisory_ops(tmp_path: Path) -> None:
    """A non-advisory task older than the window must NOT be dismissed."""
    from agents.agent4_coach_mentor.advisory_sweeper import sweep_stale

    s = _make_scheduler(tmp_path)
    t = s.file_task(
        op="some-other-op", owner_agent="2", priority=50,
        payload={}, user_override=True,
    )
    _backdate(s, t.id, hours_ago=200)
    out = sweep_stale(s, max_age_hours=72)
    assert out["dismissed"] == []
    assert s.get(t.id).status == "ready"


def test_handles_both_advisory_op_types(tmp_path: Path) -> None:
    """cold-streak-advisory AND coaching-insight-advisory are both in scope."""
    from agents.agent4_coach_mentor.advisory_sweeper import sweep_stale

    s = _make_scheduler(tmp_path)
    cold = s.file_task(
        op="cold-streak-advisory", owner_agent="1", priority=70,
        payload={"mode": "aram", "champion": "Jinx"},
        user_override=True,
    )
    insight = s.file_task(
        op="coaching-insight-advisory", owner_agent="1", priority=65,
        payload={"mode": "aram", "insight_type": "worst_hour"},
        user_override=True,
    )
    _backdate(s, cold.id, hours_ago=100)
    _backdate(s, insight.id, hours_ago=100)

    out = sweep_stale(s, max_age_hours=72)
    assert len(out["dismissed"]) == 2
    dismissed_ops = {d["op"] for d in out["dismissed"]}
    assert dismissed_ops == {"cold-streak-advisory", "coaching-insight-advisory"}


def test_skips_completed_tasks(tmp_path: Path) -> None:
    """Already-completed advisory tasks (user-dismissed) shouldn't
    appear in the dismissed list."""
    from agents.agent4_coach_mentor.advisory_sweeper import sweep_stale

    s = _make_scheduler(tmp_path)
    t = s.file_task(
        op="cold-streak-advisory", owner_agent="1", priority=70,
        payload={"mode": "aram", "champion": "Jinx"},
        user_override=True,
    )
    _backdate(s, t.id, hours_ago=100)
    s.complete(t.id, result={"source": "user"})

    out = sweep_stale(s, max_age_hours=72)
    assert out["dismissed"] == []


def test_custom_max_age(tmp_path: Path) -> None:
    from agents.agent4_coach_mentor.advisory_sweeper import sweep_stale

    s = _make_scheduler(tmp_path)
    t = s.file_task(
        op="cold-streak-advisory", owner_agent="1", priority=70,
        payload={"mode": "aram", "champion": "Jinx"},
        user_override=True,
    )
    _backdate(s, t.id, hours_ago=5)
    # Default 72h — still fresh.
    assert sweep_stale(s, max_age_hours=72)["dismissed"] == []
    # Tighter 2h threshold — now stale.
    out = sweep_stale(s, max_age_hours=2)
    assert len(out["dismissed"]) == 1


def test_invalid_created_at_skipped(tmp_path: Path) -> None:
    """A task with malformed created_at (shouldn't happen, but just in
    case) doesn't crash the sweeper."""
    from agents.agent4_coach_mentor.advisory_sweeper import sweep_stale

    s = _make_scheduler(tmp_path)
    t = s.file_task(
        op="cold-streak-advisory", owner_agent="1", priority=70,
        payload={"mode": "aram", "champion": "Jinx"},
        user_override=True,
    )
    s.get(t.id).created_at = "not-a-date"
    out = sweep_stale(s, max_age_hours=72)
    assert out["dismissed"] == []
    assert s.get(t.id).status == "ready"


def test_inspected_counts_scoped_ops_only(tmp_path: Path) -> None:
    from agents.agent4_coach_mentor.advisory_sweeper import sweep_stale

    s = _make_scheduler(tmp_path)
    s.file_task(
        op="cold-streak-advisory", owner_agent="1", priority=70,
        payload={"mode": "aram", "champion": "Jinx"},
        user_override=True,
    )
    s.file_task(
        op="some-other-op", owner_agent="2", priority=50,
        payload={}, user_override=True,
    )
    out = sweep_stale(s, max_age_hours=72)
    # inspected counts only advisory ops, regardless of age.
    assert out["inspected"] == 1


# ── supervisor wiring ───────────────────────────────────────────────

def test_supervisor_wires_advisory_sweeper() -> None:
    sup = Path("agents/supervisor.py").read_text(encoding="utf-8")
    assert "from agents.agent4_coach_mentor.advisory_sweeper import sweep_stale" in sup
    assert "stale_advisories_dismissed" in sup

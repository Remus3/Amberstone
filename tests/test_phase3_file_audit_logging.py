"""The weekly Phase-3 audit shim must leave a durable, greppable record.

`RC-Phase3-PeriodicAudit` runs `pythonw.exe -m ops.phase3_file_audit` with no
output redirection, so the two `print()` calls go to a console that does not
exist. `LastTaskResult 0` is returned on the skip path, the file path, and
after most silent problems, so for months there was no way to tell which of
the three happened.

These tests pin the additive file log: one ISO-8601 UTC line per invocation
recording outcome / task id / blocking status, an `error` line carrying the
traceback plus a nonzero exit, a logger that can fail without taking the
filing down with it, and a size cap so a weekly append cannot grow forever.

The skip/file DECISION logic is deliberately not exercised here - it was
verified correct and is out of scope. Only its silence is the defect.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import ops.phase3_file_audit as pfa


class _FakeTask:
    """Minimal stand-in for agents.agent1_lead.QueueTask."""

    def __init__(self, task_id: str, op: str, status: str, priority: int = 0) -> None:
        self.id = task_id
        self.op = op
        self.status = status
        self.priority = priority


def _install_scheduler(
    monkeypatch: pytest.MonkeyPatch,
    *,
    existing: dict[str, list[_FakeTask]] | None = None,
    filed: _FakeTask | None = None,
    raises: BaseException | None = None,
) -> list[dict]:
    """Swap in a Scheduler that never touches agents/state/task_queue.jsonl."""
    by_status = existing or {}
    filed_calls: list[dict] = []

    class _FakeScheduler:
        def __init__(self) -> None:
            if raises is not None:
                raise raises

        def list_by_status(self, status: str) -> list[_FakeTask]:
            return by_status.get(status, [])

        def file_task(self, **kwargs: object) -> _FakeTask:
            filed_calls.append(dict(kwargs))
            assert filed is not None, "test filed a task without providing one"
            return filed

    monkeypatch.setattr(pfa, "Scheduler", _FakeScheduler)
    return filed_calls


def _point_log_at(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    log = tmp_path / "logs" / "phase3_file_audit.log"
    monkeypatch.setattr(pfa, "LOG_PATH", log)
    return log


def test_default_log_path_is_repo_root_relative_not_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Resolved from __file__, so a stray WorkingDirectory cannot relocate it."""
    monkeypatch.chdir(tmp_path)
    expected = Path(pfa.__file__).resolve().parent.parent / "logs" / "phase3_file_audit.log"
    assert pfa.LOG_PATH == expected
    assert pfa.LOG_PATH.name == "phase3_file_audit.log"


def test_filed_path_writes_filed_line_with_task_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = _point_log_at(monkeypatch, tmp_path)
    filed_calls = _install_scheduler(
        monkeypatch, filed=_FakeTask("t-filed-001", pfa.AUDIT_OP, "pending", priority=0)
    )

    assert pfa.main() == 0
    assert len(filed_calls) == 1

    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, "an ops log is one line per run, not a transcript"
    line = lines[0]
    assert "outcome=filed" in line
    assert "task=t-filed-001" in line
    # ISO-8601 UTC, leading field so the log sorts chronologically.
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00 ", line), line


def test_skip_path_writes_skip_line_naming_the_blocking_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = _point_log_at(monkeypatch, tmp_path)
    blocker = _FakeTask("t-blocking-042", pfa.AUDIT_OP, "in_progress")
    filed_calls = _install_scheduler(monkeypatch, existing={"in_progress": [blocker]})

    assert pfa.main() == 0
    assert filed_calls == [], "skip path must not file a task"

    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    line = lines[0]
    assert "outcome=skip" in line
    assert "task=t-blocking-042" in line
    assert "blocking_status=in_progress" in line


def test_unexpected_exception_logs_traceback_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = _point_log_at(monkeypatch, tmp_path)
    _install_scheduler(monkeypatch, raises=RuntimeError("queue file is corrupt"))

    rc = pfa.main()
    assert rc != 0, "a real failure must make LastTaskResult nonzero"

    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, "the traceback must be folded onto one greppable line"
    line = lines[0]
    assert "outcome=error" in line
    assert "RuntimeError" in line
    assert "queue file is corrupt" in line
    assert "Traceback (most recent call last)" in line


def test_logging_failure_does_not_prevent_the_filing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Disk full / permission denied on the log must not cost us the audit."""
    _point_log_at(monkeypatch, tmp_path)
    filed_calls = _install_scheduler(
        monkeypatch, filed=_FakeTask("t-filed-002", pfa.AUDIT_OP, "pending")
    )

    def _boom(_line: str) -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(pfa, "_write_log_line", _boom)

    assert pfa.main() == 0
    assert len(filed_calls) == 1, "the filing is what matters, not its log line"


def test_size_cap_bounds_the_log_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = _point_log_at(monkeypatch, tmp_path)
    monkeypatch.setattr(pfa, "LOG_MAX_BYTES", 512)

    for i in range(400):
        pfa._log(f"outcome=filed task=t-{i:04d} priority=0 status=pending")

    assert log.exists()
    # Bounded: the live file never exceeds the cap plus the line that tripped it.
    assert log.stat().st_size <= 512 + 256, log.stat().st_size
    # Exactly one rotated generation is kept, so total on-disk stays bounded too.
    rotated = log.with_suffix(log.suffix + ".1")
    assert rotated.exists()
    assert sorted(p.name for p in log.parent.iterdir()) == [
        "phase3_file_audit.log",
        "phase3_file_audit.log.1",
    ]

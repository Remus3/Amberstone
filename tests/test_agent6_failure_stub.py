"""Regression: agent-6 spawn failures must leave a visible report stub.

Audit-10 finding C-01: the agent6-full-audit-pass cron silently failed 3 of 4
runs over 21 days (claude exit 1, empty stderr, no report, no health surface).
`_write_agent6_failure_stub` closes that gap by atomically writing a
FAILED-<task_id>.md whenever an agent-6 ephemeral spawn exits non-zero. These
tests pin that behaviour and the fail-soft (OSError must never crash the spawn
path - it is itself the failure handler).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agents._supervisor_ephemeral as se
from agents._supervisor_ephemeral import _write_agent6_failure_stub


def test_failure_stub_written(tmp_path, monkeypatch):
    monkeypatch.setattr(se, "_PROJECT_ROOT", tmp_path)
    _write_agent6_failure_stub(
        "t-deadbeef",
        "agent6-full-audit-pass",
        {"filed_at": "2026-06-21T10:00:00Z"},
        1,
        tmp_path / "logs" / "task-t-deadbeef.log",
        "2026-06-21T10:00:01Z",
    )
    reports = tmp_path / "agents" / "agent6_auditor" / "reports"
    stubs = list(reports.glob("*-FAILED-t-deadbeef.md"))
    assert len(stubs) == 1
    body = stubs[0].read_text(encoding="utf-8")
    assert "t-deadbeef" in body
    assert "exit_code: 1" in body
    assert "agent6-full-audit-pass" in body
    assert "2026-06-21T10:00:00Z" in body


def test_failure_stub_swallows_oserror(tmp_path, monkeypatch):
    monkeypatch.setattr(se, "_PROJECT_ROOT", tmp_path)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "mkdir", boom)
    _write_agent6_failure_stub("t-x", "op", {}, 2, tmp_path / "l.log", "ts")

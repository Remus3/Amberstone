"""Regression tests for the A2 / A3 silent-except defects in
``agents.supervisor.Supervisor._file_post_game_summary``.

Spec: docs/specs/2026-07-19-silent-except-triage.md sections 2a + 4.

Both tests MUST fail while the error is swallowed:

* A2 - filing failure logged at DEBUG under a broad ``except Exception``.
  A permanently broken filing path is indistinguishable from the function
  never running (the RM-107 shape). Test asserts a record at level
  >= WARNING exists.
* A3 - the ``_latest_rating_file`` locator CALL sits inside an
  ImportError-shaped ``except Exception`` guard, so a bug inside the
  locator silently strips rating / label / stats from the filed summary.
  Test asserts the defect does not pass unnoticed.
"""

from __future__ import annotations

import logging

import pytest

import performance_tracker
from agents.supervisor import Supervisor


class _RecordingScheduler:
    """Minimal stand-in for the supervisor's task scheduler."""

    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc
        self.calls: list[dict] = []

    def file_task(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return "task-1"


def _make_supervisor(scheduler) -> Supervisor:
    """Build a Supervisor without running __init__ (which starts servers)."""
    sup = object.__new__(Supervisor)
    sup._scheduler = scheduler
    return sup


# ---------------------------------------------------------------- A2

def test_post_game_summary_filing_failure_logs_at_warning(caplog):
    """A2: a file_task raise must surface at >= WARNING, not DEBUG.

    RED before the fix: the only record is DEBUG, so nothing is captured
    at WARNING and the assertion fails.
    """
    sched = _RecordingScheduler(exc=RuntimeError("boom"))
    sup = _make_supervisor(sched)

    with caplog.at_level(logging.WARNING, logger="supervisor"):
        sup._file_post_game_summary("game", "post_game")

    assert sched.calls, "file_task should have been attempted"
    loud = [
        r for r in caplog.records
        if r.levelno >= logging.WARNING and "summary" in r.getMessage().lower()
    ]
    assert loud, (
        "post-game summary filing failure must log at >= WARNING; "
        f"got records: {[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )


def test_post_game_summary_success_still_logs_info(caplog):
    """Guard: the success path keeps its INFO line after the A2 lift."""
    sched = _RecordingScheduler()
    sup = _make_supervisor(sched)

    with caplog.at_level(logging.INFO, logger="supervisor"):
        sup._file_post_game_summary("game", "post_game")

    assert sched.calls, "file_task should have been called"
    assert any(
        r.levelno == logging.INFO and "summary filed" in r.getMessage().lower()
        for r in caplog.records
    ), "success path must still log INFO"


# ---------------------------------------------------------------- A3

def test_rating_locator_bug_is_not_silently_swallowed(monkeypatch):
    """A3: a bug INSIDE _latest_rating_file must not be swallowed.

    RED before the fix: the locator call sits inside the ImportError-shaped
    ``except Exception`` guard, so the RuntimeError is eaten, the summary is
    filed WITHOUT rating / label / stats, and no signal reaches the operator.

    GREEN after the fix: the call is hoisted out of the try (which now only
    covers the import, narrowed to ImportError), so the bug propagates
    instead of producing a structurally incomplete summary.
    """
    def _boom(_sd):
        raise RuntimeError("locator bug")

    monkeypatch.setattr(performance_tracker, "_latest_rating_file", _boom)

    sched = _RecordingScheduler()
    sup = _make_supervisor(sched)

    with pytest.raises(RuntimeError, match="locator bug"):
        sup._file_post_game_summary("game", "post_game")

    assert not sched.calls, (
        "a rating-locator bug must not silently file a summary stripped of "
        "rating / label / stats"
    )


def test_rating_locator_import_failure_is_still_tolerated(monkeypatch):
    """The narrowed guard must still absorb a genuine ImportError.

    That is the failure mode the handler was written for: performance_tracker
    unavailable means no rating enrichment, not a crashed transition handler.
    """
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "performance_tracker":
            raise ImportError("no performance_tracker")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    sched = _RecordingScheduler()
    sup = _make_supervisor(sched)
    sup._file_post_game_summary("game", "post_game")

    assert sched.calls, "an ImportError must not block summary filing"
    payload = sched.calls[0]["payload"]
    assert "rating" not in payload

"""RM-370: `workflow_dispatch` runs on main shared ONE concurrency group with
`cancel-in-progress: true`, so a dispatch triggered by the next queue cycle
(~26 min) cancelled the previous dispatch run (~45-67 min) - measured: run
34012397811 cancelled by 34013317217.

Fix scoped to the DISPATCH event alone (fence 1: `cancel-in-progress: false`
would re-queue push runs and re-create the RM-157 cost problem): the group
gains `github.run_id` only when `github.event_name == 'workflow_dispatch'`,
so each dispatch is its own group, while push / schedule supersede exactly
as before.
"""
from __future__ import annotations

from pathlib import Path

import yaml

CI = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def _conc():
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["concurrency"]


def _eval_group(expr: str, event: str, run_id: str) -> str:
    """Evaluate the one expression shape used, for the three events."""
    out = expr
    out = out.replace("${{ github.workflow }}", "ci").replace("${{ github.ref }}", "refs/heads/main")
    out = out.replace("${{ github.event_name }}", event)
    dyn = ("${{ github.event_name == 'workflow_dispatch' && "
           "format('-{0}', github.run_id) || '' }}")
    assert dyn in out, "dispatch-only run_id suffix missing from the group"
    return out.replace(dyn, f"-{run_id}" if event == "workflow_dispatch" else "")


def test_cancel_in_progress_stays_on_for_push_runs():
    assert _conc()["cancel-in-progress"] is True


def test_two_dispatch_runs_get_distinct_groups():
    g = _conc()["group"]
    assert _eval_group(g, "workflow_dispatch", "1") != _eval_group(g, "workflow_dispatch", "2")


def test_push_and_schedule_groups_are_unchanged():
    g = _conc()["group"]
    assert _eval_group(g, "push", "1") == _eval_group(g, "push", "2") == "ci-refs/heads/main-push"
    assert _eval_group(g, "schedule", "7") == "ci-refs/heads/main-schedule"

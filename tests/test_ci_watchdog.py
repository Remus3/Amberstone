"""CI Watchdog decision-logic characterization tests (item 204).

Covers the pure gates that make the watchdog safe: HALT kill-switch, monotonic
sentinel, failed-run selection, the decision-3 stale-head guard, the 2-strike
escalation budget, the 24h PR rate-limit, frozen-file refusal, audit-line shape,
and the decision-2 escalation envelope. The I/O wiring (gh/git/claude) in main()
is intentionally not exercised here - these gates are the tested core.
"""
from __future__ import annotations

import json

import pytest

from tools import ci_watchdog as cw


# -- HALT ----------------------------------------------------------------

def test_halt_absent_is_not_halted(tmp_path):
    assert cw.is_halted(tmp_path) is False


def test_halt_present_is_halted(tmp_path):
    (tmp_path / "HALT").write_text("", encoding="utf-8")
    assert cw.is_halted(tmp_path) is True


# -- sentinel (monotonic) ------------------------------------------------

def test_sentinel_absent_reads_zero(tmp_path):
    assert cw.read_sentinel(tmp_path / "s.txt") == 0


def test_sentinel_roundtrip_and_monotonic(tmp_path):
    p = tmp_path / "s.txt"
    cw.write_sentinel(100, p)
    assert cw.read_sentinel(p) == 100
    cw.write_sentinel(50, p)  # regression ignored
    assert cw.read_sentinel(p) == 100
    cw.write_sentinel(200, p)
    assert cw.read_sentinel(p) == 200


def test_sentinel_garbage_reads_zero(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("not-a-number", encoding="utf-8")
    assert cw.read_sentinel(p) == 0


# -- failed-run selection ------------------------------------------------

def test_select_failed_runs_filters_and_sorts():
    runs = [
        {"databaseId": 5, "status": "completed", "conclusion": "failure", "headSha": "a"},
        {"databaseId": 9, "status": "completed", "conclusion": "success", "headSha": "b"},
        {"databaseId": 7, "status": "completed", "conclusion": "failure", "headSha": "c"},
        {"databaseId": 3, "status": "completed", "conclusion": "failure", "headSha": "d"},
        {"databaseId": 11, "status": "in_progress", "conclusion": None, "headSha": "e"},
    ]
    out = cw.select_failed_runs(runs, last_seen=4)
    ids = [r["databaseId"] for r in out]
    assert ids == [5, 7]  # >4, completed+failure, oldest-first; 3 excluded, 9 success, 11 running


def test_select_failed_runs_empty_when_all_seen():
    runs = [{"databaseId": 2, "status": "completed", "conclusion": "failure", "headSha": "a"}]
    assert cw.select_failed_runs(runs, last_seen=2) == []


# -- decision 3: stale head ----------------------------------------------

def test_is_stale_when_head_moved():
    assert cw.is_stale("abc123", "def456") is True


def test_is_not_stale_when_head_matches():
    assert cw.is_stale("abc123", "abc123") is False


def test_is_stale_on_unknown_sha():
    assert cw.is_stale("", "abc123") is True
    assert cw.is_stale("abc123", "") is True


# -- 2-strike escalation budget ------------------------------------------

def test_attempts_and_escalation_budget(tmp_path):
    d = tmp_path / "attempts"
    assert cw.attempts_for(123, d) == 0
    assert cw.should_escalate(123, d) is False
    assert cw.bump_attempts(123, d) == 1
    assert cw.should_escalate(123, d) is False
    assert cw.bump_attempts(123, d) == 2
    assert cw.should_escalate(123, d) is True  # 2-strike budget hit


# -- 24h PR rate-limit ---------------------------------------------------

def test_rate_limit_counts_only_last_24h(tmp_path):
    import time
    p = tmp_path / "pr.jsonl"
    now = time.time()
    cw.record_pr_creation(now - (cw._DAY_S + 100), 1, "pr1", p)  # outside window
    cw.record_pr_creation(now - 10, 2, "pr2", p)
    cw.record_pr_creation(now - 20, 3, "pr3", p)
    assert cw.pr_creations_last_24h(now, p) == 2
    assert cw.rate_limited(now, p) is False


def test_rate_limited_at_cap(tmp_path):
    import time
    p = tmp_path / "pr.jsonl"
    now = time.time()
    for i in range(cw.MAX_PR_PER_24H):
        cw.record_pr_creation(now - i, i, f"pr{i}", p)
    assert cw.rate_limited(now, p) is True


# -- frozen-file refusal -------------------------------------------------

def test_touches_frozen_flags_frozen_paths():
    changed = ["tests/test_x.py", "main.py", "dashboard/routes_bridge_pending.py"]
    assert cw.touches_frozen(changed) == ["dashboard/routes_bridge_pending.py", "main.py"]


def test_touches_frozen_normalizes_backslashes():
    assert cw.touches_frozen([r"app\_loop.py"]) == ["app/_loop.py"]


def test_touches_frozen_empty_when_safe():
    assert cw.touches_frozen(["tests/test_x.py", "core/foo.py"]) == []


# -- audit shape + escalation envelope -----------------------------------

def test_audit_line_appends_json(tmp_path):
    p = tmp_path / "audit.jsonl"
    cw.audit_line({"run_id": 1, "action": "skip_stale"}, p)
    cw.audit_line({"run_id": 2, "action": "dispatch"}, p)
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["action"] == "dispatch"


def test_escalation_body_shape():
    b = cw.escalation_body(42, "deadbeef", "two strikes", detail="x" * 5000)
    assert b["run_id"] == 42
    assert b["head_sha"] == "deadbeef"
    assert b["reason"] == "two strikes"
    assert b["repo"] == cw.REPO
    assert len(b["detail"]) == 4000  # truncated


def test_write_escalation_renders_markdown(tmp_path):
    p = tmp_path / "ESCALATION.md"
    cw.write_escalation(7, "abc", "two strikes", "boom", p)
    txt = p.read_text(encoding="utf-8")
    assert "CI Watchdog escalation - run 7" in txt
    assert "head_sha: abc" in txt
    assert "boom" in txt


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

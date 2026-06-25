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
    changed = ["tests/test_x.py", "main.py", "app/__init__.py"]
    assert cw.touches_frozen(changed) == ["app/__init__.py", "main.py"]


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


# -- dispatch plan (pure) ------------------------------------------------

def test_plan_dispatch_step_order_and_branch():
    steps = cw.plan_dispatch(555, "headsha9", worktree=cw.Path(r"C:\WT"), repo="o/r")
    labels = [s[0] for s in steps]
    assert labels == [
        "fetch", "reset", "branch", "gather_log", "gather_diff",
        "claude_fix", "diff_names", "push", "pr_create", "wait_checks", "pr_merge",
    ]
    by = {label: argv for label, argv in steps}
    assert cw.branch_name(555) == "ci-fix/555"
    # worktree-scoped git everywhere it runs git
    for label in ("fetch", "reset", "branch", "gather_diff", "diff_names", "push"):
        assert by[label][0].endswith("git") or by[label][0] == "git"
        assert "-C" in by[label] and r"C:\WT" in by[label]
    assert by["branch"][-3:] == ["-B", "ci-fix/555", "origin/main"]
    assert "headsha9" in by["gather_diff"]
    # gh steps carry the repo
    assert "--repo" in by["gather_log"] and "o/r" in by["gather_log"]
    assert "555" in by["gather_log"]


def test_plan_dispatch_claude_step_whitelist_and_no_skip_perms():
    steps = dict((s[0], s[1]) for s in cw.plan_dispatch(1, "h"))
    claude = steps["claude_fix"]
    assert claude[0] == "claude" and "-p" in claude
    assert "--allowedTools" in claude
    for tool in ("Edit", "Read", "Bash(ruff:*)", "Bash(git:*)",
                 "Bash(python -m py_compile:*)", "Bash(pytest:*)"):
        assert tool in claude
    assert "--append-system-prompt-file" in claude
    assert any("ci_watchdog_fix.md" in a for a in claude)
    # safety: never bypass permissions; never let claude push
    assert "--dangerously-skip-permissions" not in claude
    assert "--disallowedTools" in claude
    assert "Bash(git push:*)" in claude


def test_plan_dispatch_merge_is_squash_self_gated():
    """Merge is squash + SELF-GATED: NO --auto. The watchdog blocks on the PR's
    own checks itself (wait_checks), so no branch protection / repo auto-merge is
    needed - which preserves the direct-push-to-main workflow."""
    steps = dict((s[0], s[1]) for s in cw.plan_dispatch(2, "h"))
    merge = steps["pr_merge"]
    assert merge[:3] == ["gh", "pr", "merge"]
    assert cw._MERGE_METHOD in merge and "--auto" not in merge
    assert "ci-fix/2" in merge
    # the green-gate: a watched check poll on the SAME branch, BEFORE the merge
    checks = steps["wait_checks"]
    assert checks[:4] == ["gh", "pr", "checks", "ci-fix/2"]
    assert "--watch" in checks and "--fail-fast" in checks


# -- dispatch execution (injected runner; no real I/O) -------------------

class _FakeRunner:
    def __init__(self, outputs=None, fail=None):
        self.calls = []
        self.outputs = outputs or {}
        self.fail = set(fail or ())

    def __call__(self, label, argv):
        self.calls.append((label, argv))
        if label in self.outputs:
            return self.outputs[label]
        return (1 if label in self.fail else 0, "")

    @property
    def labels(self):
        return [c[0] for c in self.calls]


def test_execute_dispatch_dry_run_runs_nothing():
    def boom(label, argv):  # must never be called in dry-run
        raise AssertionError(f"runner invoked in dry-run: {label}")

    res = cw.execute_dispatch(9, "h", arm=False, runner=boom)
    assert res["mode"] == "dry_run"
    assert res["branch"] == "ci-fix/9"
    assert [s[0] for s in res["steps"]][0] == "fetch"
    assert len(res["steps"]) == 11


def test_execute_dispatch_arm_happy_path_merges(tmp_path):
    fake = _FakeRunner(outputs={
        "diff_names": (0, "core/foo.py\ntests/test_x.py\n"),
        "pr_create": (0, "https://github.com/o/r/pull/77\n"),
    })
    res = cw.execute_dispatch(77, "h", arm=True, worktree=tmp_path, runner=fake)
    assert res["action"] == "merged"
    assert res["pr"].endswith("/77")
    # push happens only AFTER the frozen-guard (diff_names) cleared it
    assert fake.labels.index("diff_names") < fake.labels.index("push")
    assert fake.labels.index("push") < fake.labels.index("pr_create") < fake.labels.index("pr_merge")
    # the self-gate (wait_checks) runs AFTER PR creation and BEFORE the merge
    assert fake.labels.index("pr_create") < fake.labels.index("wait_checks") < fake.labels.index("pr_merge")


def test_execute_dispatch_escalates_on_red_checks(tmp_path):
    """A fix whose own ci-fix PR goes red is NEVER merged - escalate instead.
    This is the self-gate's safety contract: merge only on green."""
    fake = _FakeRunner(outputs={
        "diff_names": (0, "core/foo.py\n"),
        "pr_create": (0, "https://github.com/o/r/pull/88\n"),
        "wait_checks": (1, "X 1 check failed"),
    })
    res = cw.execute_dispatch(88, "h", arm=True, worktree=tmp_path, runner=fake)
    assert res["action"] == "escalate"
    assert "check" in res["reason"].lower()
    assert res["pr"].endswith("/88")
    # the gate held: PR created but NOT merged
    assert "wait_checks" in fake.labels and "pr_merge" not in fake.labels


def test_execute_dispatch_merges_only_after_green_checks(tmp_path):
    fake = _FakeRunner(outputs={
        "diff_names": (0, "core/foo.py\n"),
        "pr_create": (0, "https://github.com/o/r/pull/99\n"),
        "wait_checks": (0, "all checks pass"),
    })
    res = cw.execute_dispatch(99, "h", arm=True, worktree=tmp_path, runner=fake)
    assert res["action"] == "merged"
    assert fake.labels.index("wait_checks") < fake.labels.index("pr_merge")


def test_step_timeouts_cover_blocking_steps():
    """The blocking steps (headless fix + the check-watch gate) get budgets well
    above the 120s default - a real fix + a full CI run each take minutes."""
    assert cw._STEP_TIMEOUTS["wait_checks"] >= 600
    assert cw._STEP_TIMEOUTS["claude_fix"] >= 300


def test_execute_dispatch_arm_escalates_on_frozen(tmp_path):
    fake = _FakeRunner(outputs={"diff_names": (0, "main.py\ncore/foo.py\n")})
    res = cw.execute_dispatch(5, "h", arm=True, worktree=tmp_path, runner=fake)
    assert res["action"] == "escalate"
    assert "main.py" in res["reason"]
    assert "push" not in fake.labels and "pr_create" not in fake.labels


def test_execute_dispatch_arm_escalates_on_claude_escalate(tmp_path):
    fake = _FakeRunner(outputs={"claude_fix": (0, "ESCALATE: multiple tests failing")})
    res = cw.execute_dispatch(6, "h", arm=True, worktree=tmp_path, runner=fake)
    assert res["action"] == "escalate"
    assert "ESCALATE" in res["reason"] or "escalate" in res["reason"].lower()
    assert "push" not in fake.labels


def test_execute_dispatch_arm_no_change_when_empty_diff(tmp_path):
    fake = _FakeRunner(outputs={"diff_names": (0, "   \n")})
    res = cw.execute_dispatch(8, "h", arm=True, worktree=tmp_path, runner=fake)
    assert res["action"] == "no_change"
    assert "push" not in fake.labels


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

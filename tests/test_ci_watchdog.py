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
        "claude_fix", "diff_names", "push", "pr_create", "wait_checks",
        "land_fetch", "land_head", "land_branch", "land_squash", "land_commit",
        "land_verify", "land_push", "pr_close",
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


def test_plan_dispatch_lands_locally_never_merges_on_github():
    """Kit v13/v14 ORDER section 4: no PR is merged on GitHub in any mode (the
    web-merge committer is a non-operator committer). A green fix is squashed
    LOCALLY into one watchdog-worded operator commit, verified, and pushed; the
    PR is then closed. The green-gate (wait_checks) is unchanged."""
    plan = cw.plan_dispatch(2, "h", worktree=cw.Path(r"C:\WT"), repo="o/r")
    steps = dict(plan)
    for label, argv in plan:
        assert argv[:3] != ["gh", "pr", "merge"], label
        assert not (len(argv) > 1 and argv[1:3] == ["pr", "merge"]), label
    assert not hasattr(cw, "_MERGE_METHOD")
    # the green-gate: a watched check poll on the SAME branch, BEFORE landing
    checks = steps["wait_checks"]
    assert checks[:4] == ["gh", "pr", "checks", "ci-fix/2"]
    assert "--watch" in checks and "--fail-fast" in checks
    # land on a throwaway local branch off the FRESH origin/main
    assert steps["land_fetch"][-2:] == ["origin", "--prune"]
    assert steps["land_head"][-2:] == ["rev-parse", "origin/main"]
    assert steps["land_branch"][-3:] == ["-B", cw.land_branch_name(2), "origin/main"]
    assert cw.land_branch_name(2) == "ci-land/2"
    # ONE squash commit: the fixer's own commit message (and any trailer in it)
    # never reaches main - the watchdog writes the message itself
    assert steps["land_squash"][-3:] == ["merge", "--squash", "ci-fix/2"]
    commit = steps["land_commit"]
    assert commit[:4] == ["git", "-C", r"C:\WT", "commit"]
    msg = "\n".join(commit[4:])
    assert "ci(fix): auto-fix red CI run 2" in msg
    assert "co-authored-by" not in msg.lower() and "claude" not in msg.lower()
    assert "--no-verify" not in commit
    # identity verified on exactly the commit range about to be pushed
    assert steps["land_verify"][-2:] == ["check", "origin/main..HEAD"]
    assert steps["land_verify"][1].replace("\\", "/").endswith("ops/fleet_kit/fleet_identity.py")
    # a plain fast-forward push of HEAD to main: never forced
    push = steps["land_push"]
    assert push[-3:] == ["push", "origin", "HEAD:main"]
    assert not any(a.startswith(("--force", "-f")) or a.startswith("+") for a in push[3:])
    # the PR is CLOSED (not merged) once main carries the fix
    close = steps["pr_close"]
    assert close[:4] == ["gh", "pr", "close", "ci-fix/2"]
    assert "--delete-branch" in close and "o/r" in close


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
    assert len(res["steps"]) == 18


HEAD = "a" * 40
_LAND = ("land_fetch", "land_head", "land_branch", "land_squash", "land_commit",
         "land_verify", "land_push", "pr_close")


def _green(pr_n, **extra):
    out = {
        "diff_names": (0, "core/foo.py\ntests/test_x.py\n"),
        "pr_create": (0, f"https://github.com/o/r/pull/{pr_n}\n"),
        "wait_checks": (0, "all checks pass"),
        "land_head": (0, HEAD + "\n"),
    }
    out.update(extra)
    return out


def test_execute_dispatch_arm_happy_path_lands_locally(tmp_path):
    fake = _FakeRunner(outputs=_green(77))
    res = cw.execute_dispatch(77, HEAD, arm=True, worktree=tmp_path, runner=fake)
    assert res["action"] == "landed"
    assert res["pr"].endswith("/77")
    # push happens only AFTER the frozen-guard (diff_names) cleared it
    assert fake.labels.index("diff_names") < fake.labels.index("push")
    assert fake.labels.index("push") < fake.labels.index("pr_create")
    # the self-gate (wait_checks) runs AFTER PR creation and BEFORE any landing
    assert fake.labels.index("pr_create") < fake.labels.index("wait_checks") < \
        fake.labels.index("land_fetch")
    # the land phase runs in order, and nothing is ever merged on GitHub
    assert [lb for lb in fake.labels if lb in _LAND] == list(_LAND)
    assert "pr_merge" not in fake.labels
    for _label, argv in fake.calls:
        assert argv[1:3] != ["pr", "merge"]


def test_execute_dispatch_does_not_land_when_main_moved(tmp_path):
    """Decision 3 at land time: main moved during the check-watch, so the fix was
    never tested on the base it would land on. Leave the PR for the operator."""
    fake = _FakeRunner(outputs=_green(31, land_head=(0, "b" * 40 + "\n")))
    res = cw.execute_dispatch(31, HEAD, arm=True, worktree=tmp_path, runner=fake)
    assert res["action"] == "escalate"
    assert "not landed" in res["reason"] and "moved" in res["reason"]
    assert res["pr"].endswith("/31")
    for label in ("land_squash", "land_commit", "land_push", "pr_close"):
        assert label not in fake.labels


def test_execute_dispatch_does_not_push_when_identity_check_fails(tmp_path):
    fake = _FakeRunner(outputs=_green(32, land_verify=(1, "IDENTITY: 1 finding")))
    res = cw.execute_dispatch(32, HEAD, arm=True, worktree=tmp_path, runner=fake)
    assert res["action"] == "escalate"
    assert "not landed" in res["reason"] and "land_verify" in res["reason"]
    assert "land_push" not in fake.labels and "pr_close" not in fake.labels


def test_execute_dispatch_does_not_push_when_the_gitlock_refuses_the_commit(tmp_path):
    fake = _FakeRunner(outputs=_green(33, land_commit=(3, "GITLOCK: the commit author is a bot")))
    res = cw.execute_dispatch(33, HEAD, arm=True, worktree=tmp_path, runner=fake)
    assert res["action"] == "escalate"
    assert "land_commit" in res["reason"]
    assert "land_verify" not in fake.labels and "land_push" not in fake.labels


def test_execute_dispatch_rejected_push_is_not_landed(tmp_path):
    fake = _FakeRunner(outputs=_green(34, land_push=(1, "! [rejected] HEAD -> main (fetch first)")))
    res = cw.execute_dispatch(34, HEAD, arm=True, worktree=tmp_path, runner=fake)
    assert res["action"] == "escalate"
    assert "land_push" in res["reason"]
    assert "pr_close" not in fake.labels


def test_execute_dispatch_pr_close_failure_still_reports_landed(tmp_path):
    fake = _FakeRunner(outputs=_green(35, pr_close=(1, "gh: not found")))
    res = cw.execute_dispatch(35, HEAD, arm=True, worktree=tmp_path, runner=fake)
    assert res["action"] == "landed"
    assert res["close_rc"] == 1


def test_execute_dispatch_escalates_on_red_checks(tmp_path):
    """A fix whose own ci-fix PR goes red is NEVER landed - escalate instead.
    This is the self-gate's safety contract: land only on green."""
    fake = _FakeRunner(outputs={
        "diff_names": (0, "core/foo.py\n"),
        "pr_create": (0, "https://github.com/o/r/pull/88\n"),
        "wait_checks": (1, "X 1 check failed"),
    })
    res = cw.execute_dispatch(88, HEAD, arm=True, worktree=tmp_path, runner=fake)
    assert res["action"] == "escalate"
    assert "check" in res["reason"].lower()
    assert res["pr"].endswith("/88")
    # the gate held: PR created but NOTHING landed
    assert "wait_checks" in fake.labels
    assert not any(lb in fake.labels for lb in _LAND)


def test_execute_dispatch_lands_only_after_green_checks(tmp_path):
    fake = _FakeRunner(outputs=_green(99))
    res = cw.execute_dispatch(99, HEAD, arm=True, worktree=tmp_path, runner=fake)
    assert res["action"] == "landed"
    assert fake.labels.index("wait_checks") < fake.labels.index("land_commit")


def test_default_runner_commits_through_the_kit_gitlock(monkeypatch, tmp_path):
    """FLEET-COMMON 16/17: the land commit runs through fleet_gitlock.run (lock,
    index-lock, claims AND the AI/bot identity refusal) under the watchdog's
    owner id; a refusal is a failed step, never a bypass."""
    seen = {}

    class _Refused(RuntimeError):
        pass

    class _Kit:
        LockRefused = _Refused

        @staticmethod
        def run(argv, cwd=None, runner=None):
            seen["argv"], seen["cwd"] = list(argv), str(cwd)
            return runner(argv[argv.index("--") + 1:])

    monkeypatch.setattr(cw, "_kit_module", lambda stem: _Kit)
    ran = []
    monkeypatch.setattr(cw, "_run", lambda cmd, cwd=None, timeout=120, **kw:
                        (ran.append(list(cmd)) or (0, "")))
    rc, _ = cw._gitlock_commit(["git", "-C", str(tmp_path), "commit", "-m", "t"], tmp_path)
    assert rc == 0
    assert seen["argv"][:3] == ["--owner", "ci-watchdog", "--"]
    assert seen["argv"][3:] == ["git", "-C", str(tmp_path), "commit", "-m", "t"]
    assert ran == [["git", "-C", str(tmp_path), "commit", "-m", "t"]]

    def refuse(argv, cwd=None, runner=None):
        raise _Refused("GITLOCK: the commit author is a Claude or bot identity")

    monkeypatch.setattr(_Kit, "run", staticmethod(refuse))
    rc, out = cw._gitlock_commit(["git", "commit", "-m", "t"], tmp_path)
    assert rc == 3 and "GITLOCK" in out


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


# The land phase end to end (real git, the real kit) lives in
# tests/test_ci_watchdog_land_e2e.py - see its docstring for why it is separate.


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

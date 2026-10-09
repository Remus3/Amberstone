"""CI Watchdog land phase, end to end: real git, the real vendored kit.

MAIN's kit-v13 ORDER section 4 and kit-v14 ORDER section 4 (operator
authority): no PR is merged on GitHub in any mode, so a green ci-fix lands
LOCALLY as one operator commit through ops/fleet_kit/fleet_gitlock.py. These
tests drive ``tools.ci_watchdog._land`` with the LIVE default runner (only the
network ``gh`` step is stubbed) against a throwaway bare origin, so the lock,
the kit's AI/bot identity refusal and the fleet_identity range check all run
for real.

Kept out of tests/test_ci_watchdog.py on purpose: that module names a tracked
prompt file, so the docs-guards selector runs it on a fetch-depth-1 checkout,
and the history reads here (on the throwaway repo, never the checkout) would
trip tests/test_ci_checkout_history_depth.py's static detector there.
"""
from __future__ import annotations

import os
import subprocess

import pytest

from tools import ci_watchdog as cw

_OP = ("Op Erator", "op@example.invalid")


def _git(cwd, *args, env=None):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, check=True, env=env).stdout


@pytest.fixture
def land_repo(tmp_path, monkeypatch):
    """A bare origin with one base commit on main, and a worktree whose
    ci-fix/5 branch carries a fixer commit authored as Claude with a co-author
    trailer - the exact shape the old GitHub squash-merge put on main."""
    nohooks = tmp_path / "nohooks"
    nohooks.mkdir()
    for k, v in (("GIT_CONFIG_COUNT", "2"),
                 ("GIT_CONFIG_KEY_0", "core.hooksPath"), ("GIT_CONFIG_VALUE_0", str(nohooks)),
                 ("GIT_CONFIG_KEY_1", "commit.gpgsign"), ("GIT_CONFIG_VALUE_1", "false"),
                 ("GIT_AUTHOR_NAME", _OP[0]), ("GIT_AUTHOR_EMAIL", _OP[1]),
                 ("GIT_COMMITTER_NAME", _OP[0]), ("GIT_COMMITTER_EMAIL", _OP[1])):
        monkeypatch.setenv(k, v)
    origin = tmp_path / "origin.git"
    wt = tmp_path / "wt"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(wt)], check=True)
    (wt / "a.py").write_text("x=1\n", encoding="ascii")
    _git(wt, "add", "a.py")
    _git(wt, "commit", "-q", "-m", "base")
    _git(wt, "remote", "add", "origin", str(origin))
    _git(wt, "push", "-q", "origin", "main")
    _git(wt, "fetch", "-q", "origin")
    _git(wt, "config", "--local", "fleet.operatorIdent", f"{_OP[0]} <{_OP[1]}>")
    head = _git(wt, "rev-parse", "origin/main").strip()
    _git(wt, "checkout", "-q", "-B", "ci-fix/5", "origin/main")
    (wt / "a.py").write_text("x = 1\n", encoding="ascii")
    _git(wt, "add", "a.py")
    bot = dict(os.environ, GIT_AUTHOR_NAME="Claude", GIT_AUTHOR_EMAIL="noreply@anthropic.com",
               GIT_COMMITTER_NAME="Claude", GIT_COMMITTER_EMAIL="noreply@anthropic.com")
    _git(wt, "commit", "-q", "-m", "fix lint",
         "-m", "Co-Authored-By: Claude <noreply@anthropic.com>", env=bot)
    return origin, wt, head


def _land_runner(wt):
    real = cw._default_runner(wt)

    def runner(label, argv):
        if label == "pr_close":  # gh is the only network step; stub it
            return 0, ""
        return real(label, argv)
    return runner


def test_land_phase_puts_one_operator_commit_on_main(land_repo):
    origin, wt, head = land_repo
    steps = dict(cw.plan_dispatch(5, head, worktree=wt, repo="o/r"))
    reason, detail = cw._land(steps, _land_runner(wt), head)
    assert reason == "", detail
    tip = _git(origin, "log", "-1", "--format=%an <%ae>|%cn <%ce>|%B", "main")
    author, committer, msg = tip.split("|", 2)
    assert author == f"{_OP[0]} <{_OP[1]}>" and committer == author
    assert msg.startswith("ci(fix): auto-fix red CI run 5")
    assert "co-authored-by" not in msg.lower() and "claude" not in msg.lower()
    assert _git(origin, "show", "main:a.py") == "x = 1\n"
    # base + ONE land commit: the Claude-authored fixer commit never reached main
    assert _git(origin, "rev-list", "--count", "main").strip() == "2"


def test_land_phase_refuses_a_bot_identity_and_leaves_main_alone(land_repo, monkeypatch):
    origin, wt, head = land_repo
    monkeypatch.setenv("GIT_AUTHOR_NAME", "github-actions[bot]")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "41898282+github-actions[bot]@users.noreply.github.com")
    steps = dict(cw.plan_dispatch(5, head, worktree=wt, repo="o/r"))
    reason, detail = cw._land(steps, _land_runner(wt), head)
    assert "land_commit" in reason
    # refused by the kit's identity rule, not by some unrelated lock failure
    assert "GITLOCK" in detail and "identity" in detail, detail
    assert _git(origin, "rev-parse", "main").strip() == head


def test_land_phase_refuses_when_the_operator_set_is_missing(land_repo):
    """fleet_identity fails CLOSED: no fleet.operatorIdent means no push."""
    origin, wt, head = land_repo
    _git(wt, "config", "--local", "--unset-all", "fleet.operatorIdent")
    steps = dict(cw.plan_dispatch(5, head, worktree=wt, repo="o/r"))
    reason, detail = cw._land(steps, _land_runner(wt), head)
    assert "land_verify" in reason
    assert "fleet.operatorIdent" in detail
    assert _git(origin, "rev-parse", "main").strip() == head

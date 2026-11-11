"""RM-2089: the s144 lane sync must never replay main's own history.

ops/loop/lane_sync.choose_sync on throwaway repos (real git, every repo under
tmp_path, nothing read from or written to this checkout). Measured 2026-11-11: the
s159 landing merged lanes into main with --no-ff merges, so each S144_LANDED_<LANE>
marker is an ancestor of main; cycle 238 fast-forwarded the lanes to main, and from
cycle 239 on the driver's `git rebase --onto main <landed>` replayed the whole landing
(queue cycle 252: 483 commits) and CONFLICTED on every cycle for five lanes.

Each history below is built the way the landing built it. The positive controls run
the driver's old rule (`--onto main <landed>` whenever the marker is a commit and an
ancestor of HEAD) on the same history and show it conflicts; the plan must instead be
a no-op, a fast-forward, or a rebase that moves only the lane's own commits.
"""
from __future__ import annotations

import subprocess

import pytest

from ops.loop import lane_sync

_OP = ("Op Erator", "op@example.invalid")


@pytest.fixture(autouse=True)
def _isolated_git(tmp_path, monkeypatch):
    nohooks = tmp_path / "nohooks"
    nohooks.mkdir()
    for k, v in (("GIT_CONFIG_COUNT", "3"),
                 ("GIT_CONFIG_KEY_0", "core.hooksPath"), ("GIT_CONFIG_VALUE_0", str(nohooks)),
                 ("GIT_CONFIG_KEY_1", "commit.gpgsign"), ("GIT_CONFIG_VALUE_1", "false"),
                 ("GIT_CONFIG_KEY_2", "core.autocrlf"), ("GIT_CONFIG_VALUE_2", "false"),
                 ("GIT_AUTHOR_NAME", _OP[0]), ("GIT_AUTHOR_EMAIL", _OP[1]),
                 ("GIT_COMMITTER_NAME", _OP[0]), ("GIT_COMMITTER_EMAIL", _OP[1])):
        monkeypatch.setenv(k, v)


def _run(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=False, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL)


def _git(repo, *args) -> str:
    r = _run(repo, *args)
    if r.returncode:
        raise AssertionError(f"git {' '.join(args)} rc={r.returncode}: {r.stderr}")
    return r.stdout.strip()


def _write(repo, name, text):
    (repo / name).write_text(text, encoding="ascii", newline="\n")


def _commit(repo, name, text, msg) -> str:
    _write(repo, name, text)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _gitfn(repo):
    return lambda *a: _run(repo, *a)


def _count(repo, rng) -> int:
    return int(_git(repo, "rev-list", "--count", rng))


def _anc(repo, a, b) -> bool:
    return _run(repo, "merge-base", "--is-ancestor", a, b).returncode == 0


def _old_rule_args(repo, landed):
    """The live driver's pre-fix choice (s144_lane_driver.py sync_worktree): --onto
    main <landed> whenever the marker is a commit and an ancestor of HEAD."""
    if (_run(repo, "cat-file", "-e", landed + "^{commit}").returncode == 0
            and _anc(repo, landed, "HEAD")):
        return ("--onto", "main", landed)
    return ("main",)


def _apply(repo, plan):
    """Execute a plan the way the driver does (ff-only merge / nothing / rebase);
    returns the rebase CompletedProcess or None."""
    if plan.kind == lane_sync.FF:
        _git(repo, "merge", "--ff-only", "-q", "main")
        return None
    if plan.kind == lane_sync.CURRENT:
        return None
    r = _run(repo, "rebase", *plan.args)
    if r.returncode:
        _run(repo, "rebase", "--abort")
    return r


def _rebase_conflicts(repo, args) -> bool:
    """Run a rebase on a throwaway branch at HEAD; True when it stopped on a conflict.
    The lane branch and HEAD are left exactly where they were."""
    head = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "symbolic-ref", "--short", "HEAD")
    _git(repo, "checkout", "-q", "-b", "probe-old-rule")
    r = _run(repo, "rebase", *args)
    stopped = r.returncode != 0
    if stopped:
        _run(repo, "rebase", "--abort")
    _git(repo, "checkout", "-q", branch)
    _git(repo, "branch", "-q", "-D", "probe-old-rule")
    assert _git(repo, "rev-parse", "HEAD") == head
    return stopped and "CONFLICT" in (r.stdout + r.stderr)


@pytest.fixture
def landed(tmp_path):
    """main carries a --no-ff landing of lane/q; main then gets more commits that edit
    the lines the lane edited (other lanes' landings), and lane/q is checked out at the
    landed tip. Returns (repo, marker)."""
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True,
                   capture_output=True)
    _commit(repo, "shared.txt", "v0\n", "base")
    _git(repo, "checkout", "-q", "-b", "lane/q")
    _commit(repo, "lane.txt", "q1\n", "lane: q1")
    marker = _commit(repo, "shared.txt", "v1\n", "lane: shared v1")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "other.txt", "o1\n", "other lane: o1")
    _git(repo, "merge", "-q", "--no-ff", "-m", "land lane/q", "lane/q")
    # later landings rewrite the same line twice: replaying the first onto a main that
    # already holds the second conflicts
    _commit(repo, "shared.txt", "v2\n", "other lane: shared v2")
    _commit(repo, "shared.txt", "v3\n", "other lane: shared v3")
    _git(repo, "checkout", "-q", "lane/q")
    assert _anc(repo, marker, "main") and _anc(repo, marker, "HEAD")
    return repo, marker


def test_cycle_238_landed_tip_fast_forwards(landed):
    repo, marker = landed
    assert _git(repo, "rev-parse", "HEAD") == marker
    plan = lane_sync.choose_sync(_gitfn(repo), marker)
    assert plan.kind == lane_sync.FF and plan.args == ()
    _apply(repo, plan)
    assert _git(repo, "rev-parse", "HEAD") == _git(repo, "rev-parse", "main")


def _lane_contains_main(repo):
    _git(repo, "merge", "--ff-only", "-q", "main")  # cycle 238
    return [_commit(repo, "lane.txt", "q2\n", "lane: q2"),
            _commit(repo, "lane.txt", "q3\n", "lane: q3")]


def test_lane_already_contains_main_is_a_no_op(landed):
    repo, marker = landed
    own = _lane_contains_main(repo)
    tip = _git(repo, "rev-parse", "HEAD")
    assert _rebase_conflicts(repo, _old_rule_args(repo, marker)), \
        "positive control: the old --onto <landed> rule must conflict on this history"
    plan = lane_sync.choose_sync(_gitfn(repo), marker)
    assert plan.kind == lane_sync.CURRENT, plan
    assert plan.args == () and "--onto" not in plan.how
    assert _apply(repo, plan) is None
    assert _git(repo, "rev-parse", "HEAD") == tip
    assert _count(repo, "main..HEAD") == len(own)


def test_main_moved_ahead_rebases_only_the_lane_commits(landed):
    repo, marker = landed
    own = _lane_contains_main(repo)
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "shared.txt", "v4\n", "other lane: shared v4")
    _commit(repo, "late.txt", "l1\n", "other lane: late")
    _git(repo, "checkout", "-q", "lane/q")
    assert _rebase_conflicts(repo, _old_rule_args(repo, marker)), \
        "positive control: the old --onto <landed> rule must conflict on this history"
    plan = lane_sync.choose_sync(_gitfn(repo), marker)
    assert plan.kind == lane_sync.REBASE and plan.args == ("main",), plan
    assert plan.marker_state == "in_main"
    r = _apply(repo, plan)
    assert r is not None and r.returncode == 0, r.stdout + r.stderr
    assert _anc(repo, "main", "HEAD")
    assert _count(repo, "main..HEAD") == len(own)
    subjects = _git(repo, "log", "--format=%s", "main..HEAD").splitlines()
    assert subjects == ["lane: q3", "lane: q2"]
    assert (repo / "shared.txt").read_text(encoding="ascii") == "v4\n"


def test_marker_never_used_once_main_carries_it(landed):
    repo, marker = landed
    _lane_contains_main(repo)
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "late.txt", "l1\n", "other lane: late")
    _git(repo, "checkout", "-q", "lane/q")
    plan = lane_sync.choose_sync(_gitfn(repo), marker)
    assert "--onto" not in plan.args
    assert lane_sync.marker_state(_gitfn(repo), marker) == "in_main"


def test_folded_landing_still_replays_only_newer_lane_commits(tmp_path):
    """repo / true-audit shape: main carries a squashed twin of the landed lane
    commits, so the marker is NOT an ancestor of main and --onto <landed> stays."""
    repo = tmp_path / "fold"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True,
                   capture_output=True)
    _commit(repo, "shared.txt", "v0\n", "base")
    _git(repo, "checkout", "-q", "-b", "lane/r")
    _commit(repo, "shared.txt", "v1\n", "lane: v1")
    marker = _commit(repo, "shared.txt", "v2\n", "lane: v2")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--squash", "lane/r")
    _git(repo, "commit", "-q", "-m", "land lane/r (folded twin)")
    _commit(repo, "shared.txt", "v3\n", "other lane: v3")
    _git(repo, "checkout", "-q", "lane/r")
    _commit(repo, "lane.txt", "r1\n", "lane: r1")
    assert not _anc(repo, marker, "main")
    plan = lane_sync.choose_sync(_gitfn(repo), marker)
    assert plan.kind == lane_sync.REBASE and plan.args == ("--onto", "main", marker), plan
    assert plan.marker_state == "used"
    r = _apply(repo, plan)
    assert r is not None and r.returncode == 0, r.stdout + r.stderr
    assert _git(repo, "log", "--format=%s", "main..HEAD").splitlines() == ["lane: r1"]


@pytest.mark.parametrize("marker, state", [("", "none"), ("0" * 40, "invalid")])
def test_no_usable_marker_falls_back_to_plain_rebase(landed, marker, state):
    repo, _real = landed
    _lane_contains_main(repo)
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "late.txt", "l1\n", "other lane: late")
    _git(repo, "checkout", "-q", "lane/q")
    plan = lane_sync.choose_sync(_gitfn(repo), marker)
    assert plan.kind == lane_sync.REBASE and plan.args == ("main",)
    assert plan.marker_state == state


def test_marker_not_in_lane_falls_back_to_plain_rebase(landed):
    repo, _real = landed
    _git(repo, "checkout", "-q", "main")
    side = _git(repo, "rev-parse", "HEAD~1")
    _commit(repo, "late.txt", "l1\n", "other lane: late")
    _git(repo, "checkout", "-q", "-b", "lane/z", "HEAD~3")
    _commit(repo, "z.txt", "z1\n", "lane z: z1")
    assert not _anc(repo, side, "HEAD")
    plan = lane_sync.choose_sync(_gitfn(repo), side)
    assert plan.kind == lane_sync.REBASE and plan.args == ("main",)
    assert plan.marker_state == "not_in_head"

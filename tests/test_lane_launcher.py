# arch: tests for ops/loop/lane_launcher.py (Mission Control S5) | section=tests | frozen=no
"""S5 - the claim becomes a running worker.

The lock (S1) decides who MAY run; the launcher is what runs. The behaviours
that matter are the ones that go wrong quietly:

- A failed launch must RELEASE the lane. A lock with no process behind it reads
  RUNNING to every poller and wedges the lane until someone reclaims it by hand.
- The pid in the lock must be the WORKER's, not the claimer's. A dashboard fire
  claims from the long-lived RC server, and a lock carrying that pid would
  report RUNNING forever after the worker died - the exact stale-lock failure
  the three states exist to prevent.
- The command doc must be a TRACKED path. A worktree is a fresh checkout and
  carries no gitignored files, so a lane pointed at .claude/commands/ would
  start with an empty prompt.

Nothing here spawns a process: `launch_lane` takes a `spawn` seam and every
test injects it.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys

import pytest

lanes = importlib.import_module("ops.loop.lanes")
launcher = importlib.import_module("ops.loop.lane_launcher")


class FakeProc:
    def __init__(self, pid=4242):
        self.pid = pid


@pytest.fixture
def lane_root(tmp_path, monkeypatch):
    """Redirect the lane lock dir AND the worktree base at a tmp sandbox."""
    root = tmp_path / "lanes"
    monkeypatch.setattr(lanes, "DEFAULT_ROOT", root)
    monkeypatch.setattr(launcher, "WORKTREE_BASE", tmp_path / "worktrees")
    monkeypatch.setattr(launcher, "LOG_DIR", tmp_path / "reports")
    return root


def _claim(lane="upgrade", run_id="run0001", wt=r"C:\some\worktree"):
    return lanes.try_acquire_lane(lane, run_id=run_id, worktree=wt)


# --------------------------------------------------------------------------- command doc
def test_every_wired_lane_points_at_a_tracked_path():
    """Never .claude/commands - a worktree does not carry gitignored files."""
    for lane, rel in launcher.LANE_COMMANDS.items():
        assert rel.startswith("tools/"), (
            f"lane {lane} points at {rel}, which a fresh worktree may not have")


def test_every_wired_command_doc_exists_on_disk():
    for lane in launcher.LANE_COMMANDS:
        assert launcher.command_path(lane).is_file()


def test_an_unwired_lane_raises_rather_than_launching_nothing():
    with pytest.raises(launcher.LaneLaunchError) as exc:
        launcher.command_path("true-audit")
    assert "no command doc wired" in str(exc.value)


def test_unwired_lanes_are_still_valid_lock_lanes():
    """The lock knows all six; only the launcher gates which can start."""
    assert set(launcher.LANE_COMMANDS) <= set(lanes.LANES), (
        "the launcher must never wire a lane the lock does not know")


def test_the_two_highest_blast_radius_lanes_stay_unwired():
    """repo and true-audit ship LAST, behind their own stage and sign-off.

    Wiring them early would put a file-by-file rewrite and a security audit one
    confirmed click away, which is exactly the ordering the plan forbids.
    """
    for lane in ("repo", "true-audit"):
        assert lane in lanes.LANES
        assert lane not in launcher.LANE_COMMANDS


# --------------------------------------------------------------------------- worktree
def test_worktree_path_is_outside_the_repo(lane_root, tmp_path):
    wt = launcher.worktree_path("upgrade")
    assert launcher.REPO_ROOT not in wt.parents
    assert wt.name == "rc-lane-upgrade"


def test_ensure_worktree_refuses_the_main_tree(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "WORKTREE_BASE", launcher.REPO_ROOT.parent)
    monkeypatch.setattr(launcher, "worktree_path",
                        lambda lane, base=None: launcher.REPO_ROOT)
    with pytest.raises(launcher.LaneLaunchError) as exc:
        launcher.ensure_worktree("upgrade")
    assert "main tree" in str(exc.value)


def test_ensure_worktree_creates_then_reuses(tmp_path, monkeypatch):
    """Real git, real worktree - the reuse path is the one that regresses."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
    (repo / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True, env=env)

    base = tmp_path / "wts"
    first = launcher.ensure_worktree("upgrade", base=base, root=repo)
    assert (first / ".git").exists()
    second = launcher.ensure_worktree("upgrade", base=base, root=repo)
    assert second == first, "a second fire must reuse the worktree, not fork one"


# --------------------------------------------------------------------------- launch
def test_launch_repoints_the_lock_at_the_worker(lane_root, monkeypatch):
    claim = _claim()
    assert claim["ok"] is True
    monkeypatch.setattr(launcher, "ensure_worktree",
                        lambda lane, base=None, root=None: lane_root.parent / "wt")
    (lane_root.parent / "wt").mkdir(parents=True, exist_ok=True)

    # A LIVE pid, or lane_state would correctly read RECLAIMABLE and the test
    # would be measuring liveness rather than the re-point.
    worker = os.getpid()
    run = launcher.launch_lane("upgrade", run_id="run0001",
                               token=claim["token"],
                               spawn=lambda *a, **k: FakeProc(worker))
    assert run["pid"] == worker
    state = lanes.lane_state(lane_root)
    assert state["state"] == "RUNNING"
    assert state["pid"] == worker, "the lock must carry the WORKER pid"
    payload = json.loads((lane_root / "0.lock").read_text(encoding="utf-8"))
    assert "claimed_by_pid" in payload, "the original claimer must be recorded"
    lanes.release_lane(claim["token"])


def test_release_still_works_after_a_repoint(lane_root, monkeypatch):
    """The ABA guard compares against _OWNED; a repoint must update it too."""
    claim = _claim()
    monkeypatch.setattr(launcher, "ensure_worktree",
                        lambda lane, base=None, root=None: lane_root.parent / "wt2")
    (lane_root.parent / "wt2").mkdir(parents=True, exist_ok=True)
    launcher.launch_lane("upgrade", run_id="run0001", token=claim["token"],
                         spawn=lambda *a, **k: FakeProc(4243))
    assert lanes.release_lane(claim["token"]) is True
    assert lanes.lane_state(lane_root)["state"] == "FREE"


def test_a_dead_worker_makes_the_lane_reclaimable(lane_root, monkeypatch):
    """The whole point of re-pointing: liveness now tracks the WORKER."""
    dead = next(p for p in range(999000, 999200) if not lanes.slots.pid_alive(p))
    claim = _claim()
    monkeypatch.setattr(launcher, "ensure_worktree",
                        lambda lane, base=None, root=None: lane_root.parent / "wt3")
    (lane_root.parent / "wt3").mkdir(parents=True, exist_ok=True)
    launcher.launch_lane("upgrade", run_id="run0001", token=claim["token"],
                         spawn=lambda *a, **k: FakeProc(dead))
    state = lanes.lane_state(lane_root)
    assert state["state"] == "RECLAIMABLE"
    assert state["state"] != "RUNNING"
    lanes.release_lane(claim["token"])


# --------------------------------------------------------------------------- failure frees the lane
def test_a_missing_command_doc_releases_the_lane(lane_root):
    # "true-audit" is deliberately UNWIRED until its stage lands, which makes it
    # the honest fixture for this path - no stub required.
    assert "true-audit" not in launcher.LANE_COMMANDS
    claim = _claim(lane="true-audit")
    with pytest.raises(launcher.LaneLaunchError):
        launcher.launch_lane("true-audit", run_id="run0002",
                             token=claim["token"],
                             spawn=lambda *a, **k: FakeProc())
    assert lanes.lane_state(lane_root)["state"] == "FREE", (
        "a lane that never started must not stay locked")


def test_a_spawn_failure_releases_the_lane(lane_root, monkeypatch):
    claim = _claim()
    monkeypatch.setattr(launcher, "ensure_worktree",
                        lambda lane, base=None, root=None: lane_root.parent / "wt4")
    (lane_root.parent / "wt4").mkdir(parents=True, exist_ok=True)

    def boom(*a, **k):
        raise launcher.LaneLaunchError("spawn failed: nope")

    with pytest.raises(launcher.LaneLaunchError):
        launcher.launch_lane("upgrade", run_id="run0003",
                             token=claim["token"], spawn=boom)
    assert lanes.lane_state(lane_root)["state"] == "FREE"


def test_a_worktree_failure_releases_the_lane(lane_root, monkeypatch):
    claim = _claim()

    def boom(*a, **k):
        raise launcher.LaneLaunchError("git worktree add failed")

    monkeypatch.setattr(launcher, "ensure_worktree", boom)
    with pytest.raises(launcher.LaneLaunchError):
        launcher.launch_lane("upgrade", run_id="run0004",
                             token=claim["token"], spawn=lambda *a, **k: FakeProc())
    assert lanes.lane_state(lane_root)["state"] == "FREE"


def test_a_spawn_with_no_pid_releases_and_does_not_repoint(lane_root, monkeypatch):
    claim = _claim()
    monkeypatch.setattr(launcher, "ensure_worktree",
                        lambda lane, base=None, root=None: lane_root.parent / "wt5")
    (lane_root.parent / "wt5").mkdir(parents=True, exist_ok=True)
    with pytest.raises(launcher.LaneLaunchError):
        launcher.launch_lane("upgrade", run_id="run0005", token=claim["token"],
                             spawn=lambda *a, **k: FakeProc(pid=None))
    assert lanes.lane_state(lane_root)["state"] == "FREE"


def test_a_failed_repoint_kills_the_worker_and_releases(lane_root, monkeypatch):
    """An untrackable worker is worse than none - it would read RUNNING forever."""
    claim = _claim()
    monkeypatch.setattr(launcher, "ensure_worktree",
                        lambda lane, base=None, root=None: lane_root.parent / "wt6")
    (lane_root.parent / "wt6").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(lanes, "repoint_lane_pid", lambda *a, **k: False)
    killed = []
    monkeypatch.setattr(launcher, "_kill", killed.append)

    with pytest.raises(launcher.LaneLaunchError) as exc:
        launcher.launch_lane("upgrade", run_id="run0006", token=claim["token"],
                             spawn=lambda *a, **k: FakeProc(5150))
    assert "re-point" in str(exc.value)
    assert killed == [5150], "the untrackable worker must be killed"
    assert lanes.lane_state(lane_root)["state"] == "FREE"


# --------------------------------------------------------------------------- repoint guards
def test_repoint_refuses_when_the_lock_is_not_ours(lane_root):
    claim = _claim()
    lock = lane_root / "0.lock"
    rec = json.loads(lock.read_text(encoding="utf-8"))
    rec["run_id"] = "somebody-else"
    lock.write_text(json.dumps(rec), encoding="utf-8")
    assert lanes.repoint_lane_pid(claim["token"], 1234) is False
    lanes._OWNED.pop(lanes._key(lock), None)
    lock.unlink()


def test_repoint_on_a_missing_lock_is_false(lane_root):
    assert lanes.repoint_lane_pid(str(lane_root / "0.lock"), 1234) is False


def test_repoint_rejects_a_non_integer_pid(lane_root):
    claim = _claim()
    assert lanes.repoint_lane_pid(claim["token"], "not-a-pid") is False
    lanes.release_lane(claim["token"])


def _code_strings(path):
    """Every string literal in the module that is NOT a docstring.

    Scanning raw text would match this file's own prose about the rule, which
    is the same comments-cite-the-bug trap that made an earlier guard red.
    """
    import ast
    tree = ast.parse(open(path, encoding="utf-8").read())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value not in docstrings]


def test_the_kill_path_uses_taskkill_not_stop_process():
    """CLAUDE.md hard rule: Stop-Process hangs the MCP pipe."""
    strings = _code_strings(launcher.__file__)
    assert "taskkill" in strings
    assert not [s for s in strings if "Stop-Process" in s]


def test_the_spawn_never_uses_detached_process():
    """DETACHED_PROCESS makes powershell exit instantly, silently, rc=0.

    MEASURED: with it set the worker issues a pid, returns success and writes
    NOTHING. The lane then flips RUNNING -> RECLAIMABLE right on schedule and
    produces no work, which is the worst shape this failure can take - it looks
    exactly like a healthy short run.
    """
    import inspect
    src = inspect.getsource(launcher._spawn)
    assert "creationflags=_NO_WINDOW," in src or "creationflags=_NO_WINDOW)" in src
    assert "_DETACHED" not in src
    assert not hasattr(launcher, "_DETACHED"), (
        "the constant is gone on purpose so it cannot be re-added by habit")


def test_the_launcher_never_binds_a_second_copy_of_lanes():
    """One lanes module, or `_OWNED` splits and a lane can never be released.

    MEASURED: the first cut file-bound lanes.py under a private name, so the
    repoint updated one `_OWNED` and the release consulted another.
    """
    import dashboard.routes_loop_control as ctlmod
    assert launcher.lanes is ctlmod._lanes(), (
        "the launcher and the route must share ONE lanes module object")
    assert launcher.lanes is lanes

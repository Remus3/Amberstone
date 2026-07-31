#!/usr/bin/env python
r"""Lane launcher - turn a held lane lock into a running headless worker.

`ops/loop/lanes.py` (S1) decides WHO may run; this module is what actually
runs. The split is deliberate: the lock is pure state management and must stay
testable without spawning anything, so nothing in lanes.py starts a process and
nothing here decides eligibility.

WORKTREE-MANDATORY, ENFORCED TWICE. Operator decision 2026-07-30: a lane may
fire while an interactive session is live, but it may only ever run against a
git worktree - never the main tree. `try_acquire_lane` already refuses a
worktree that resolves to the repo root; this module refuses it again at spawn
time, because the two checks happen at different moments and a path can be
handed in between them. Two writers in one working directory is the
concurrent-index corruption class (memory
`reference_gist_hook_worktree_index_corruption`), and it is not recoverable by
retrying.

REUSES THE PROVEN RUNNER. `ops/loop/run_lane.ps1` has detached headless
`claude -p` workers since 2026-07-16 (`spawn_lanes.ps1`): prompt piped on stdin
so there is no command-line quoting risk, stderr folded into the log so a native
warning cannot kill the lane. This module builds the worktree and the argument
list; it does not re-implement that.

THE PID IN THE LOCK IS THE WORKER'S, NOT THE CLAIMER'S. A dashboard fire claims
the lane from the RC server process, which outlives every lane. If the lock kept
that pid, `lane_state` would probe a process that is always alive and the lane
would read RUNNING forever after its worker died. `launch_lane` re-points the
lock via `lanes.repoint_lane_pid` as soon as it has a real pid, and RELEASES the
lane if anything in the spawn path fails - a lock with no process behind it is
strictly worse than no lock at all.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load_lanes():
    """Bind the SAME lanes module everything else uses - never a second copy.

    lanes.py carries process-global state: `_OWNED`, the ABA guard that decides
    whether a release is ours, and `DEFAULT_ROOT`. A file-path bind under a
    private name creates a SECOND module object with its OWN `_OWNED`, so a
    repoint recorded in one copy is invisible to a release called on the other
    and the lane can never be released. MEASURED - the first cut of this file
    did exactly that, and two launcher tests failed on it.

    `ops.loop.lanes` is what dashboard/routes_loop_control.py imports, so that
    is the canonical name. The file-path fallback exists only for callers that
    have no package on sys.path, and it reuses the same private name lanes.py
    itself would land under.
    """
    try:
        return importlib.import_module("ops.loop.lanes")
    except ImportError:
        pass
    modname = "rc_loop_lanes"
    if modname in sys.modules:
        return sys.modules[modname]
    spec = importlib.util.spec_from_file_location(modname, _HERE / "lanes.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


lanes = _load_lanes()

REPO_ROOT = lanes.REPO_ROOT
RUNNER = _HERE / "run_lane.ps1"
LOG_DIR = _HERE / "reports"

# Worktrees live OUTSIDE the repo, matching the 2026-07-16 precedent
# (C:\rc-worktrees). Inside the repo they would land in the very tree the lane
# is forbidden to touch, and every repo-wide guard would then scan them - see
# memory `reference_repo_root_guard_worktree_blind`.
WORKTREE_BASE = Path(os.environ.get("RC_LANE_WORKTREE_BASE", r"C:\rc-worktrees"))

# Lane -> the command doc fed to the worker as its prompt. TRACKED paths only
# (tools/*.md), never the gitignored .claude/commands mirror: a worktree is a
# fresh checkout and does not carry gitignored files, so a lane pointed at the
# mirror would start with an empty prompt. Same fresh-clone-has-no-wiring trap
# as the git hooks and the Perseus vault.
LANE_COMMANDS = {
    "upgrade": "tools/headless-upgrade.md",
}

# Branch per lane, stable across fires so a lane resumes its own history rather
# than sprouting a branch per click.
BRANCH_PREFIX = "lane"

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0      # CREATE_NO_WINDOW

# DETACHED_PROCESS (0x8) is DELIBERATELY NOT USED, and this is not a style call.
# MEASURED 2026-07-31, three spawns of the same script differing only in flags:
#
#   CREATE_NO_WINDOW | DETACHED_PROCESS -> pid issued, rc=0, log NEVER written
#   CREATE_NO_WINDOW                    -> pid issued, rc=0, log written
#   DETACHED_PROCESS                    -> pid issued, rc=0, log NEVER written
#
# powershell.exe cannot initialise its host without a console, so it exits
# immediately and SILENTLY - a success exit code, a real pid, and no work done.
# The lane would have flipped RUNNING then RECLAIMABLE on schedule and produced
# nothing, which is the worst shape a failure can take here. CREATE_NO_WINDOW
# alone already suppresses the console flash, and the child outlives this
# process anyway because nothing waits on it.


class LaneLaunchError(RuntimeError):
    """Anything that stops a lane from starting. Always releases the lane."""


def worktree_path(lane: str, base: Path | None = None) -> Path:
    return (WORKTREE_BASE if base is None else Path(base)) / f"rc-lane-{lane}"


def branch_name(lane: str) -> str:
    return f"{BRANCH_PREFIX}/{lane}"


def command_path(lane: str, root: Path | None = None) -> Path:
    """The tracked command doc for `lane`, or raise if the lane is not wired."""
    rel = LANE_COMMANDS.get(lane)
    if rel is None:
        raise LaneLaunchError(
            f"lane {lane!r} has no command doc wired yet "
            f"(wired: {', '.join(sorted(LANE_COMMANDS)) or 'none'})")
    path = (REPO_ROOT if root is None else Path(root)) / rel
    if not path.is_file():
        raise LaneLaunchError(f"command doc missing on disk: {path}")
    return path


def _git(args, cwd=None, timeout=120):
    return subprocess.run(
        ["git", *args], cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, timeout=timeout,
        creationflags=_NO_WINDOW,
    )


def ensure_worktree(lane: str, base: Path | None = None,
                    root: Path | None = None) -> Path:
    """Create the lane's worktree if absent, reuse it if present.

    Reuse is deliberate. A worktree per fire would leave a directory and a
    branch behind on every click, and `git worktree add` on an existing branch
    fails anyway - so the lane keeps one long-lived checkout it can resume.
    """
    repo = REPO_ROOT if root is None else Path(root)
    wt = worktree_path(lane, base)
    if _same_path(wt, repo):
        raise LaneLaunchError(
            f"refusing to run lane {lane!r} against the main tree ({repo})")
    if (wt / ".git").exists():
        return wt
    wt.parent.mkdir(parents=True, exist_ok=True)
    branch = branch_name(lane)
    exists = _git(["rev-parse", "--verify", "--quiet", branch], cwd=repo)
    args = (["worktree", "add", str(wt), branch] if exists.returncode == 0
            else ["worktree", "add", str(wt), "-b", branch])
    out = _git(args, cwd=repo)
    if out.returncode != 0 or not (wt / ".git").exists():
        raise LaneLaunchError(
            f"git worktree add failed for {lane!r}: "
            f"{(out.stderr or out.stdout or '').strip()[:300]}")
    return wt


def _same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(str(a))) == \
        os.path.normcase(os.path.abspath(str(b)))


def _log_path(lane: str, run_id: str, log_dir: Path | None = None) -> Path:
    d = LOG_DIR if log_dir is None else Path(log_dir)
    d.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in str(run_id) if ch.isalnum() or ch in "-_")[:32]
    return d / f"lane_{lane}_{safe or 'run'}.log"


def _spawn(runner: Path, prompt: Path, cwd: Path, log: Path):
    """Detached, hidden PowerShell runner. Returns the Popen handle."""
    if not runner.is_file():
        raise LaneLaunchError(f"runner missing: {runner}")
    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(runner),
        "-PromptFile", str(prompt),
        "-Cwd", str(cwd),
        "-Log", str(log),
    ]
    try:
        return subprocess.Popen(
            cmd, cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        )
    except OSError as exc:
        raise LaneLaunchError(f"spawn failed: {exc}") from exc


def launch_lane(lane: str, *, run_id: str, token, base: Path | None = None,
                root: Path | None = None, log_dir: Path | None = None,
                spawn=None) -> dict:
    """Start `lane`'s worker and re-point its lock at the spawned process.

    `token` is what `try_acquire_lane` handed back. On ANY failure the lane is
    released before the error propagates, so a failed launch can never leave a
    lock nobody is behind.

    `spawn` is the injection seam for tests - the default really does start a
    process, and no test should.
    """
    spawn = _spawn if spawn is None else spawn
    try:
        prompt = command_path(lane, root=root)
        wt = ensure_worktree(lane, base=base, root=root)
        log = _log_path(lane, run_id, log_dir=log_dir)
        proc = spawn(RUNNER, prompt, wt, log)
        pid = getattr(proc, "pid", None)
        if not pid:
            raise LaneLaunchError("spawn returned no pid")
        if not lanes.repoint_lane_pid(token, pid):
            # The lock could not be pointed at the worker, so lane_state would
            # keep probing the claimer and report RUNNING forever. A worker we
            # cannot track is worse than no worker.
            _kill(pid)
            raise LaneLaunchError("could not re-point the lane lock at the worker")
    except LaneLaunchError:
        lanes.release_lane(token)
        raise
    except Exception as exc:  # noqa: BLE001 - any fault must still free the lane
        lanes.release_lane(token)
        raise LaneLaunchError(f"launch failed: {exc}") from exc
    return {"lane": lane, "run_id": str(run_id), "pid": pid,
            "worktree": str(wt), "log": str(log), "prompt": str(prompt),
            "started_at": time.time()}


def _kill(pid: int) -> None:
    """taskkill /F, never Stop-Process (CLAUDE.md hard rule - it hangs the MCP pipe)."""
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=20,
                       creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        pass

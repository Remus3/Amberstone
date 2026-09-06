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

# NUL-separated git output, so a path containing whitespace cannot split wrong.
NUL = "\x00"

# How many files the EOL repair deletes before restoring them. Bounded so an
# interruption mid-repair leaves at most this many paths missing, all of them
# recoverable with `git checkout -- .`.
_RENORM_BATCH = 256

# Lane -> the command doc fed to the worker as its prompt. TRACKED paths only
# (tools/*.md), never the gitignored .claude/commands mirror: a worktree is a
# fresh checkout and does not carry gitignored files, so a lane pointed at the
# mirror would start with an empty prompt. Same fresh-clone-has-no-wiring trap
# as the git hooks and the Perseus vault.
LANE_COMMANDS = {
    "upgrade": "tools/headless-upgrade.md",
    "uiux": "tools/headless-uiux.md",
    "research": "tools/headless-research.md",
    "ds": "tools/headless-ds.md",
    # S8. `repo` and `true-audit` are the two highest-blast-radius lanes and
    # were held back on purpose until the rest of the control plane was proven
    # - wiring them earlier would have put a file-by-file rewrite and a
    # security audit one confirmed click away. Both are worktree-mandatory like
    # every other lane, which matters most here: these are the two that
    # restructure and rewrite files rather than adding to them.
    "repo": "tools/headless-repo.md",
    "true-audit": "tools/headless-true-audit.md",
    # 2026-08-02. The only lane whose work is gated on something outside the
    # repo: a REAL game running on Legion. It is still worktree-mandatory and
    # still detached, but it MONITORS - it polls live state and does the drain
    # half only while a game is actually up, and the prep half otherwise. It
    # must never close a row synthetically; that was measured and closed
    # (CLAUDE.md Settled, "the live-gated set is NOT synthetically drainable").
    "gated": "tools/headless-gated.md",
    # 2026-09-05. Lane 10, the DRAIN half of the lane-5 pairing: lane 5 files
    # acceptance-bearing RM rows, this lane executes them one per cycle. It is
    # the first lane meant to be re-fired on a loop rather than clicked, so its
    # worker does exactly ONE row and exits - `ops/loop/queue_loop.py` owns the
    # repeat. A worker that looped internally would accumulate context until it
    # degraded, and a crash would lose every row after the first.
    "queue": "tools/headless-queue.md",
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


def _git(args, cwd=None, timeout=120, input=None):  # noqa: A002 - subprocess kwarg
    return subprocess.run(
        ["git", *args], cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, timeout=timeout,
        creationflags=_NO_WINDOW, input=input,
    )


def _pinned_lf_paths(wt: Path) -> list[str]:
    """Tracked paths git will ACTUALLY write with LF - asked of git, never inferred.

    Both `text: set` AND `eol: lf` are required, and a suffix filter is the wrong
    one: the LFS payloads under `data/daemon_slayer/laning_scenarios/` match
    `*.json` but carry `-text`, so git deliberately does not convert them and
    their CRLF is correct. Filtering by suffix reports all 7 as offenders against
    a clean tree (memory `feedback_data_filter_vs_evaluator_filter`), which is
    the same trap that produced a false failure on the first run of
    `tests/test_text_line_endings.py`.
    """
    listed = _git(["ls-files", "-z"], cwd=wt)
    if listed.returncode != 0:
        return []
    tracked = [p for p in (listed.stdout or "").split(NUL) if p]
    if not tracked:
        return []
    got = _git(["check-attr", "--stdin", "-z", "text", "eol"], cwd=wt,
               input=NUL.join(tracked))
    if got.returncode != 0:
        return []
    fields = (got.stdout or "").split(NUL)
    attrs: dict[str, dict[str, str]] = {}
    for i in range(0, len(fields) - 2, 3):
        if fields[i]:
            attrs.setdefault(fields[i], {})[fields[i + 1]] = fields[i + 2]
    return [p for p, a in attrs.items()
            if a.get("text") == "set" and a.get("eol") == "lf"]


def _content_dirty(wt: Path) -> set[str]:
    """Paths git sees a REAL content change in. Never `git status` - measured.

    `git status` consults cached stat info, and a CRLF rewrite changes the file
    SIZE, so it reports ` M` for a file whose filtered content is byte-identical
    to its blob (measured 2026-09-06, and it repeats on a second run). Filtering
    on status would skip exactly the files this repairs and ship an inert fix.
    `git diff` applies the clean filter, so a CRLF-only difference correctly
    reads as no change while a genuine edit still reads as one.
    """
    dirty: set[str] = set()
    for args in (["diff", "--name-only", "-z"],
                 ["diff", "--cached", "--name-only", "-z"]):
        out = _git(args, cwd=wt)
        if out.returncode == 0:
            dirty.update(p for p in (out.stdout or "").split(NUL) if p)
    return dirty


def renormalize_eol(wt: Path) -> list[str]:
    """Re-materialize reused-worktree files whose disk bytes contradict eol=lf.

    RM-343. EOL conversion is decided at MATERIALIZATION time by the
    `.gitattributes` in force at that moment, and `core.autocrlf=true` on this
    fleet (from the SYSTEM gitconfig, not `.git/config`, so a per-worktree
    override is not available) writes CRLF for every tracked text path not
    pinned `eol=lf`. When `8119b3334` widened the pin to `.json`, `.js` and 13
    more, every worktree materialized before it kept those files as CRLF - and
    git never re-materializes them, because the BLOB never changed. `git status`
    stays clean, so the condition is invisible to every git-based check.

    `ensure_worktree` reusing a checkout is correct and must stay, but it is
    also what makes the staleness permanent. This is the repair, and it runs
    where the reuse happens.

    Repairs only files git agrees are unmodified, so uncommitted work is never
    discarded. Best-effort by design: a lane must not fail to start because a
    cleanup failed, so every error path returns [].

    NOT a commit of 1884 paths - re-materializing changes no blob, so the tree
    stays clean and nothing is staged.
    """
    try:
        wt = Path(wt)
        if not (wt / ".git").exists():
            return []
        pinned = _pinned_lf_paths(wt)
        if not pinned:
            return []
        dirty = _content_dirty(wt)
        stale: list[str] = []
        for rel in pinned:
            if rel in dirty:
                continue
            try:
                fp = wt / rel
                if fp.is_file() and b"\r\n" in fp.read_bytes():
                    stale.append(rel)
            except OSError:
                continue
        if not stale:
            return []
        stale.sort()
        # THE FILE MUST BE DELETED FIRST. Measured 2026-09-06 at git 2.53.0
        # against the real lane worktrees: a stale checkout has the CRLF file's
        # stat recorded in the index against an unchanged LF blob, so git is
        # convinced the file is up to date and BOTH `checkout-index -f` and
        # `git checkout --pathspec-from-file` return 0 having done nothing. The
        # first version of this repair reported 1916 files fixed and left all
        # 1916 stale. Only a missing file forces git to write one.
        #
        # Safe because every path here is one git reports as content-clean, so
        # the bytes being deleted are exactly the bytes the blob restores. Done
        # in batches so an interruption strands as little as possible.
        repaired: list[str] = []
        for i in range(0, len(stale), _RENORM_BATCH):
            batch = stale[i:i + _RENORM_BATCH]
            removed: list[str] = []
            for rel in batch:
                try:
                    (wt / rel).unlink()
                    removed.append(rel)
                except OSError:
                    continue
            if not removed:
                continue
            out = _git(["checkout-index", "-f", "-z", "--stdin"], cwd=wt,
                       input=NUL.join(removed) + NUL)
            if out.returncode != 0:
                # Restore what we removed rather than leaving a hole in the tree.
                _git(["checkout", "--", *removed[:_RENORM_BATCH]], cwd=wt)
                continue
            repaired.extend(removed)
        return sorted(repaired)
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


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
        # RM-343: a reused checkout keeps whatever EOL it was materialized with,
        # so a `.gitattributes` pin that landed after it stays unapplied forever.
        renormalize_eol(wt)
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

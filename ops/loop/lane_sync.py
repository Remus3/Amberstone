"""Lane sync choice: the tested logic behind the s144 lane driver's per-cycle sync
(RM-2089). The driver is a gitignored one-off under ops/loop/control/lane_prompts/, so
CI never sees it; it imports this module with a fallback, the same shape as
ops/loop/lane_run_ledger.py and ops/loop/proc_tree.py.

The driver brings a clean lane worktree onto LOCAL main once per cycle. A merger that
lands a lane writes control/lanes/S144_LANDED_<LANE> holding the lane tip it landed, and
the sync used `git rebase --onto main <landed>` whenever that tip was an ancestor of the
lane HEAD. That replays every commit in landed..HEAD.

Measured 2026-11-11 (RM-2089): the s159 landing merged five lanes into main with
`--no-ff` merges, so each marker (the merge's second parent) is an ancestor of main.
Cycle 238 fast-forwarded each lane to main; from cycle 239 on, every lane held main plus
its own new commits, and landed..HEAD was the whole s159 landing (queue cycle 252:
"Rebasing (1/483)") replayed onto a main that already carried it - CONFLICTED and
aborted on every cycle for queue, ds, gated, research and uiux. The two lanes landed by
a folded twin (repo, true-audit: the pre-fold tip is NOT an ancestor of main) did not
take that path and synced cleanly.

The marker only adds information when main does NOT carry the landed history by
ancestry (a squash, cherry-pick or folded-twin landing): then landed..HEAD is exactly
the lane commits that are new since the landing. When main already contains the marker,
`git rebase main` (upstream = merge-base) replays exactly the lane commits main lacks,
and when the lane already contains main there is nothing to sync at all.

choose_sync(git, landed) returns the plan; the driver keeps its own execution (the
ff-only merge through fleet_gitlock, the rebase as plain git with abort and park):

  ff       HEAD is an ancestor of main: fast-forward (cycle 238's case).
  current  main is an ancestor of HEAD: the lane already holds main; no rebase.
  rebase   anything else, with args ("--onto", main, landed) only when the marker is a
           commit, an ancestor of HEAD and NOT an ancestor of main; ("main",) otherwise.

`git` is a callable taking git argv (without "git") and returning an object with a
returncode, e.g. lambda *a: subprocess.run(["git", *a], cwd=wt, ...). Stdlib only, ASCII
only; importable by file path or as ops.loop.lane_sync.
"""
from __future__ import annotations

from typing import Callable, NamedTuple

FF = "ff"
CURRENT = "current"
REBASE = "rebase"
KINDS = (FF, CURRENT, REBASE)


class SyncPlan(NamedTuple):
    kind: str          # one of KINDS
    args: tuple        # rebase argv after "rebase" (empty unless kind == REBASE)
    how: str           # one-line description for the cycle record / dry plan
    marker_state: str  # none / invalid / not_in_head / in_main / used


def _ok(git: Callable, *args) -> bool:
    return git(*args).returncode == 0


def is_ancestor(git: Callable, a: str, b: str) -> bool:
    return _ok(git, "merge-base", "--is-ancestor", a, b)


def marker_state(git: Callable, landed: str, main: str = "main", head: str = "HEAD") -> str:
    """What the landed marker means for this sync: none (no marker), invalid (not a
    commit in this repo), not_in_head (the lane no longer carries it, e.g. rewritten by
    an earlier rebase), in_main (main carries it by ancestry: the marker is stale and
    adds nothing over the merge-base), used (the --onto upstream)."""
    landed = (landed or "").strip()
    if not landed:
        return "none"
    if not _ok(git, "cat-file", "-e", landed + "^{commit}"):
        return "invalid"
    if not is_ancestor(git, landed, head):
        return "not_in_head"
    if is_ancestor(git, landed, main):
        return "in_main"
    return "used"


def choose_sync(git: Callable, landed: str = "", main: str = "main",
                head: str = "HEAD") -> SyncPlan:
    """The sync a clean lane worktree needs to sit on `main`. Never raises on a git
    answer it does not like (a non-zero return code is a "no"); a git callable that
    raises propagates, and the driver treats that as an error."""
    if is_ancestor(git, head, main):
        return SyncPlan(FF, (), f"fast-forward to local {main}", "")
    state = marker_state(git, landed, main, head)
    if is_ancestor(git, main, head):
        return SyncPlan(CURRENT, (), f"lane already contains local {main} - nothing to sync "
                        f"(no rebase)", state)
    if state == "used":
        return SyncPlan(REBASE, ("--onto", main, landed.strip()),
                        f"rebase --onto {main} {landed.strip()[:12]} (merger landed marker)",
                        state)
    why = {"in_main": f"landed marker {landed.strip()[:12]} already in {main}",
           "not_in_head": "landed marker not in the lane",
           "invalid": "landed marker not a commit",
           "none": "no landed marker"}[state]
    return SyncPlan(REBASE, (main,), f"rebase {main} ({why})", state)

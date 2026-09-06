#!/usr/bin/env python
"""ops/loop/lanes.py - six mutually exclusive headless lanes, one holder max.

WHY THIS FILE EXISTS. A lock file whose pid is DEAD is indistinguishable from a
live one by inspection alone. On 2026-07-30 the real
`ops/loop/control/RUNNING.lock` carried
`{"pid": 9380, "run_id": "eadf15e3", ...}` and pid 9380 was gone - yet every
reader that trusted the file's EXISTENCE reported the loop as running. So the
lane lock has THREE states, not two, and it decides between them by PROBING the
pid (slots.pid_alive), never by stat-ing the file.

Two behaviours are load-bearing and each gets a byte-level assertion here:
  - `lane_state` is READ-ONLY. It must never auto-clear a stale lock as a side
    effect of being read, because a dashboard poll is a read.
  - a fire against a genuinely-held lane is REFUSED, not queued, and mutates
    NOTHING on disk.

Every test drives a tmp_path root; nothing here touches the live control dir.
No test launches, signals or kills a process - a dead holder is synthesised
with a pid the OS can never have issued.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    """Load an ops/loop module by absolute path - ops/loop is not a package."""
    modname = f"rc_loop_{name}_lane_lock_test"
    spec = importlib.util.spec_from_file_location(
        modname, ROOT / "ops" / "loop" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


lanes = _load("lanes")
slots = lanes.slots

# A pid the OS cannot have issued: Windows hands out multiples of 4 only, and
# Linux never reaches this without a raised pid_max. Synthesising a dead holder
# this way keeps the suite from spawning or killing anything.
DEAD_PID = 999999999

# A pid that is always live and is never us: System on Windows, init on Linux.
# Stands in for "another process holds this lane" without spawning one.
FOREIGN_LIVE_PID = 4 if os.name == "nt" else 1


# ---- helpers ---------------------------------------------------------------

def _snapshot(root: Path) -> dict:
    """Byte-for-byte picture of the lock dir - contents, sizes and mtimes."""
    snap = {"__siblings__": sorted(p.name for p in root.parent.iterdir())}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        st = p.stat()
        snap[rel] = (
            p.is_dir(),
            None if p.is_dir() else p.read_bytes(),
            st.st_size,
            st.st_mtime_ns,
        )
    return snap


def _set_holder_pid(root: Path, pid: int) -> None:
    """Repoint the on-disk holder at `pid` - our stand-in for a process dying.

    Atomic (tmp + os.replace) because everything under control/ is polled
    mid-write by the loop controller.
    """
    lock = lanes.lock_path(root)
    rec = json.loads(lock.read_text(encoding="utf-8"))
    rec["pid"] = pid
    tmp = lock.with_name(lock.name + ".tmp")
    tmp.write_text(json.dumps(rec), encoding="utf-8")
    os.replace(tmp, lock)


def _write_lock(root: Path, payload: dict) -> Path:
    """Plant a lock this process did not write - another holder's, in effect."""
    lock = lanes.lock_path(root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    tmp = lock.with_name(lock.name + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, lock)
    return lock


@pytest.fixture
def root(tmp_path):
    # Deliberately NOT created - a read of a lane root that does not exist yet
    # must answer FREE without conjuring the directory.
    return tmp_path / "lanes"


@pytest.fixture
def worktree(tmp_path):
    wt = tmp_path / "wt-upgrade"
    wt.mkdir()
    return wt


@pytest.fixture
def worktree2(tmp_path):
    wt = tmp_path / "wt-research"
    wt.mkdir()
    return wt


# ---- preconditions ---------------------------------------------------------

def test_the_synthetic_dead_pid_really_is_dead():
    """If this ever fails, every RECLAIMABLE assertion below is vacuous."""
    assert slots.pid_alive(os.getpid()), "own pid must probe alive"
    assert not slots.pid_alive(DEAD_PID), (
        f"pid {DEAD_PID} was expected to be unissuable on this OS")
    assert slots.pid_alive(FOREIGN_LIVE_PID), (
        f"pid {FOREIGN_LIVE_PID} was expected to be a live system process")
    assert FOREIGN_LIVE_PID != os.getpid()


def test_lane_roster_and_single_slot():
    assert lanes.LANES == (
        "upgrade", "uiux", "research", "ds", "repo", "true-audit", "gated",
        "queue")
    assert lanes.MAX_SLOTS == 1, "every lane is mutually exclusive with the rest"


# ---- the three states ------------------------------------------------------

def test_free_when_no_lock_exists_and_the_read_creates_nothing(root):
    assert lanes.lane_state(root) == {
        "state": "FREE", "lane": None, "pid": None, "run_id": None,
        "worktree": None, "age_s": None}
    assert not root.exists(), "lane_state must not create its own root"


def test_running_when_the_holder_pid_is_alive(root, worktree):
    res = lanes.try_acquire_lane(
        "upgrade", run_id="r1", worktree=str(worktree), root=root)
    assert res["ok"] is True
    assert res["lane"] == "upgrade"
    assert res["run_id"] == "r1"
    assert Path(res["worktree"]) == worktree.resolve()
    assert Path(res["token"]).is_file()
    assert Path(res["token"]).parent == root

    st = lanes.lane_state(root)
    assert st["state"] == "RUNNING"
    assert st["lane"] == "upgrade"
    assert st["pid"] == os.getpid()
    assert st["run_id"] == "r1"
    assert Path(st["worktree"]) == worktree.resolve()
    assert st["age_s"] >= 0.0


def test_reclaimable_when_the_holder_pid_is_dead(root, worktree):
    """The whole point of the slice: a dead holder NEVER renders as RUNNING."""
    lanes.try_acquire_lane(
        "upgrade", run_id="r1", worktree=str(worktree), root=root)
    _set_holder_pid(root, DEAD_PID)

    st = lanes.lane_state(root)
    assert st["state"] == "RECLAIMABLE"
    assert st["state"] != "RUNNING"
    assert st["pid"] == DEAD_PID
    assert st["lane"] == "upgrade", "a stale lock still names the lane it held"
    assert lanes.lock_path(root).is_file(), "reading must not clear the lock"


def test_lane_state_never_mutates_a_reclaimable_lock(root, worktree):
    lanes.try_acquire_lane(
        "upgrade", run_id="r1", worktree=str(worktree), root=root)
    _set_holder_pid(root, DEAD_PID)

    before = _snapshot(root)
    for _ in range(3):
        assert lanes.lane_state(root)["state"] == "RECLAIMABLE"
    assert _snapshot(root) == before, (
        "lane_state auto-cleared or rewrote the stale lock - it is a READ")


def test_age_s_is_measured_against_the_supplied_now(root, worktree):
    lanes.try_acquire_lane(
        "upgrade", run_id="r1", worktree=str(worktree), root=root)
    ts = json.loads(lanes.lock_path(root).read_text(encoding="utf-8"))["ts"]
    st = lanes.lane_state(root, now=ts + 42.0)
    assert st["age_s"] == pytest.approx(42.0, abs=0.01)
    assert st["state"] == "RUNNING", "a lane never expires on age alone"


def test_full_state_cycle_free_running_reclaimable_running_free(root, worktree, worktree2):
    assert lanes.lane_state(root)["state"] == "FREE"

    first = lanes.try_acquire_lane(
        "upgrade", run_id="r1", worktree=str(worktree), root=root)
    assert first["ok"] is True
    assert lanes.lane_state(root)["state"] == "RUNNING"

    _set_holder_pid(root, DEAD_PID)
    assert lanes.lane_state(root)["state"] == "RECLAIMABLE"

    second = lanes.try_acquire_lane(
        "research", run_id="r2", worktree=str(worktree2), root=root)
    assert second["ok"] is True, "a dead holder must be reclaimed, not respected"
    st = lanes.lane_state(root)
    assert st["state"] == "RUNNING"
    assert st["lane"] == "research"
    assert st["run_id"] == "r2"
    assert len(list(root.glob("*.lock"))) == 1, "reclaim must not leave a second lock"

    assert lanes.release_lane(second["token"]) is True
    assert lanes.lane_state(root)["state"] == "FREE"


# ---- refuse, do not queue --------------------------------------------------

def test_second_fire_against_a_live_lane_is_refused_and_mutates_nothing(root, worktree, worktree2):
    lanes.try_acquire_lane(
        "upgrade", run_id="r1", worktree=str(worktree), root=root)

    before = _snapshot(root)
    res = lanes.try_acquire_lane(
        "research", run_id="r2", worktree=str(worktree2), root=root)
    after = _snapshot(root)

    assert res == {"ok": False, "refused": "lane_held",
                   "holder": "upgrade", "pid": os.getpid()}
    assert after == before, "a refused fire wrote to disk - it must queue nothing"


def test_refire_of_the_same_live_lane_is_also_refused(root, worktree):
    lanes.try_acquire_lane(
        "upgrade", run_id="r1", worktree=str(worktree), root=root)

    before = _snapshot(root)
    res = lanes.try_acquire_lane(
        "upgrade", run_id="r2", worktree=str(worktree), root=root)
    assert res["ok"] is False
    assert res["refused"] == "lane_held"
    assert res["holder"] == "upgrade"
    assert _snapshot(root) == before
    assert lanes.lane_state(root)["run_id"] == "r1", "the first holder still owns it"


# ---- input validation ------------------------------------------------------

def test_unknown_lane_raises_before_touching_disk(root, worktree):
    with pytest.raises(ValueError):
        lanes.try_acquire_lane(
            "nope", run_id="r1", worktree=str(worktree), root=root)
    assert not root.exists(), "validation must happen before any disk write"


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_worktree_is_mandatory(bad, root):
    with pytest.raises(ValueError, match="worktree is mandatory"):
        lanes.try_acquire_lane("upgrade", run_id="r1", worktree=bad, root=root)
    assert not root.exists()


def test_worktree_may_not_be_the_repo_root(root):
    """Operator decision 2026-07-30: a lane never runs against the main tree."""
    variants = [
        lanes.REPO_ROOT,
        str(lanes.REPO_ROOT),
        str(lanes.REPO_ROOT) + os.sep,
        str(lanes.REPO_ROOT / "sub" / ".."),
    ]
    if os.name == "nt":
        variants.append(str(lanes.REPO_ROOT).lower())
    for variant in variants:
        with pytest.raises(ValueError):
            lanes.try_acquire_lane(
                "upgrade", run_id="r1", worktree=variant, root=root)
    assert not root.exists()


# ---- release ---------------------------------------------------------------

def test_release_is_idempotent(root, worktree):
    res = lanes.try_acquire_lane(
        "upgrade", run_id="r1", worktree=str(worktree), root=root)
    assert lanes.release_lane(res["token"]) is True
    assert lanes.lane_state(root)["state"] == "FREE"

    assert lanes.release_lane(res["token"]) is False
    assert lanes.release_lane(res["token"], root=root) is False
    assert lanes.release_lane(None) is False
    assert lanes.lane_state(root)["state"] == "FREE"


def test_release_will_not_unlink_a_lock_this_process_did_not_write(root, worktree):
    """ABA guard. A token names a PATH, and every holder uses the same path, so
    release has to confirm that the lock sitting there is still the one it was
    handed. Here the lane died, another process reclaimed it, and the previous
    holder releases late - the new holder must survive that."""
    first = lanes.try_acquire_lane(
        "upgrade", run_id="r1", worktree=str(worktree), root=root)
    _write_lock(root, {"pid": FOREIGN_LIVE_PID, "lane": "research",
                       "run_id": "r2", "worktree": str(worktree),
                       "ts": time.time(), "repo": "somewhere-else"})

    assert lanes.release_lane(first["token"]) is False
    st = lanes.lane_state(root)
    assert st["state"] == "RUNNING"
    assert st["lane"] == "research"
    assert lanes.lock_path(root).is_file(), "the new holder's lock was unlinked"


def test_release_will_not_unlink_a_half_written_lock(root, worktree):
    first = lanes.try_acquire_lane(
        "upgrade", run_id="r1", worktree=str(worktree), root=root)
    lanes.lock_path(root).write_bytes(b"{partial")

    assert lanes.release_lane(first["token"]) is False
    assert lanes.lock_path(root).is_file()


# ---- half-written lock -----------------------------------------------------

def test_unreadable_lock_is_held_inside_the_write_grace_then_reclaimable(root):
    """slots creates the lock file and fills it a moment later, so an empty
    lock is presumed live briefly - but it can never be proven alive, so past
    the grace it must read RECLAIMABLE rather than wedge the lane forever."""
    root.mkdir(parents=True)
    lanes.lock_path(root).write_bytes(b"")

    fresh = lanes.lane_state(root)
    assert fresh["state"] == "RUNNING"
    assert fresh["pid"] is None

    later = lanes.lane_state(root, now=time.time() + lanes.WRITE_GRACE_S + 60)
    assert later["state"] == "RECLAIMABLE"
    assert lanes.lock_path(root).is_file(), "still a read - nothing cleared"


# ---------------------------------------------------------------------------
# Regression: REPO_ROOT must resolve to the MAIN tree even when lanes.py is
# imported from inside a git worktree.
#
# The original form was `Path(__file__).resolve().parents[2]`, which returns
# the WORKTREE when this module is imported from one. The worktree-mandatory
# guard then inverts - it rejects the worktree a lane legitimately runs in and
# ACCEPTS the main tree it must never touch. Lanes are worktree-mandatory by
# operator decision 2026-07-30, so that is the shipping configuration, not an
# edge case. Caught by an integration probe; both slices passed their own
# suites with the hole present.
# ---------------------------------------------------------------------------

def test_main_tree_root_resolves_through_a_worktree_gitfile(tmp_path):
    """A `.git` FILE (worktree marker) must resolve back to the main tree."""
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt1").mkdir(parents=True)
    wt = tmp_path / "wt1"
    wt.mkdir()
    (wt / ".git").write_text(
        "gitdir: %s\n" % (main / ".git" / "worktrees" / "wt1"), encoding="utf-8")

    assert lanes._main_tree_root(wt) == main, "worktree must resolve to main tree"


def test_main_tree_root_is_identity_for_a_real_main_tree(tmp_path):
    """A `.git` DIRECTORY is already the main tree - resolve to itself."""
    main = tmp_path / "main"
    (main / ".git").mkdir(parents=True)
    assert lanes._main_tree_root(main) == main


def test_main_tree_root_falls_back_when_git_is_absent(tmp_path):
    """No .git at all (plain export, tmpdir) must not raise - stay total."""
    bare = tmp_path / "bare"
    bare.mkdir()
    assert lanes._main_tree_root(bare) == bare


def test_guard_rejects_every_spelling_of_the_main_tree(tmp_path):
    """Equality is path-normalized, not string-compared."""
    root = tmp_path / "lanes"
    base = str(lanes.REPO_ROOT)
    for spelling in (base, base.replace("\\", "/"), base + "/", base + "/."):
        with pytest.raises(ValueError, match="never run against the main tree"):
            lanes.try_acquire_lane("repo", run_id="r", worktree=spelling, root=root)
    assert not root.exists(), "a rejected acquire must not create the lock root"


def test_repo_root_is_a_main_tree_never_a_worktree():
    """REPO_ROOT must BIND via _main_tree_root(), not Path(__file__).parents[2].

    Non-tautological where it counts: the other guard tests source their base
    from REPO_ROOT itself, so they pass whatever it points at - they cannot
    catch a revert to the naive form. This one can, because it asserts a
    property of the resolved path rather than comparing it to itself.

    A main tree has a `.git` DIRECTORY; a worktree has a `.git` FILE. Under the
    naive form, running from a worktree binds REPO_ROOT to that worktree and
    this fails. Stated plainly: when the suite runs from the main tree the two
    forms agree and this test passes either way - it earns its keep in worktree
    runs, which is how every lane and every parallel build agent executes.
    """
    dotgit = lanes.REPO_ROOT / ".git"
    if not dotgit.exists():
        pytest.skip("REPO_ROOT is not a git checkout (export or tmp tree)")
    assert dotgit.is_dir(), (
        "REPO_ROOT resolved to a WORKTREE (.git is a file, not a directory). "
        "The worktree-mandatory guard inverts in that state: it rejects the "
        "worktree a lane runs in and accepts the main tree it must never "
        "touch. Bind REPO_ROOT via _main_tree_root()."
    )

#!/usr/bin/env python
"""A recycled pid must not resurrect a dead lane lock.

MEASURED LIVE 2026-08-02, and this is the whole reason the file exists. The
`gated` lane worker died at 10:02:52. `lane_state` correctly read RECLAIMABLE
at +42s. Three minutes later Windows handed pid 8820 to `SearchFilterHost`
(start time 10:05:05), and from that moment the lane read RUNNING again - a
fire was refused `lane_held` by a Windows indexing service that had never
heard of it, and no amount of waiting would have freed it, because the lane
only frees on a DEAD pid and this pid was now permanently alive.

That is the RUNNING/RECLAIMABLE decision inverting after the fact. It is worse
than the stale-lock bug the three states were built for: that one at least
decayed the moment the pid was probed, whereas this one is stable and wedges
the lane until a human deletes the file.

THE FIX IS IDENTITY, NOT TIMING. A pid alone does not name a process; (pid,
start time) does. The lock records the holder's start time when it is written,
and `lane_state` compares that against the live process's CURRENT start time.
Same pid, different start time = the holder is gone and a stranger inherited
its number. Deliberately NOT "the process started after the lock ts" - a lane
legitimately spawns seconds after the claim (git worktree add is not
instant), so that comparison would have a tolerance to tune and would still be
wrong in both directions. An exact recorded value has neither problem.

Back-compat is asserted too: a lock written before this landed carries no
recorded start time, and must keep behaving exactly as it did.
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
    modname = f"rc_loop_{name}_pid_reuse_test"
    spec = importlib.util.spec_from_file_location(
        modname, ROOT / "ops" / "loop" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


lanes = _load("lanes")


@pytest.fixture
def root(tmp_path):
    return tmp_path / "lanes"


@pytest.fixture
def worktree(tmp_path):
    wt = tmp_path / "wt-gated"
    wt.mkdir()
    return wt


def _write_lock(root: Path, payload: dict) -> Path:
    lock = lanes.lock_path(root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    tmp = lock.with_name(lock.name + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, lock)
    return lock


def _base(**over) -> dict:
    rec = {"pid": os.getpid(), "lane": "gated", "run_id": "r1",
           "worktree": r"C:\rc-worktrees\rc-lane-gated", "ts": time.time(),
           "repo": str(lanes.REPO_ROOT)}
    rec.update(over)
    return rec


# ---- the probe itself ------------------------------------------------------

def test_the_start_time_probe_answers_for_a_live_process():
    """If this returns None for our own pid, every assertion below is vacuous."""
    started = lanes.proc_started(os.getpid())
    assert started is not None, "no start-time source available for our own pid"
    assert started < time.time() + 1.0
    assert lanes.proc_started(os.getpid()) == started, "must be stable"


def test_the_probe_is_total_for_a_pid_that_cannot_exist():
    assert lanes.proc_started(999999999) is None
    assert lanes.proc_started(-1) is None


# ---- the inversion this file exists for ------------------------------------

def test_a_recycled_pid_reads_reclaimable_not_running(root):
    """The live measurement, reproduced: our own pid, someone else's identity.

    The pid is genuinely alive (it is this test process), so the pid probe
    alone says RUNNING. The recorded start time is one no process has, which
    is exactly the shape of a pid that has been handed on.
    """
    _write_lock(root, _base(pid_started=1.0))
    st = lanes.lane_state(root)
    assert st["state"] == lanes.RECLAIMABLE, (
        "a live pid whose start time does not match the recorded holder is a "
        "RECYCLED pid, not the holder")
    assert st["lane"] == "gated", "a reclaimable lock still names what held it"


def test_the_real_holder_still_reads_running(root):
    _write_lock(root, _base(pid_started=lanes.proc_started(os.getpid())))
    assert lanes.lane_state(root)["state"] == lanes.RUNNING


def test_a_lock_with_no_recorded_start_time_behaves_exactly_as_before(root):
    """Back-compat. A lock written by the previous version carries no
    pid_started, and there is nothing to compare - it must keep deciding on the
    pid probe alone rather than reading RECLAIMABLE for want of a field."""
    _write_lock(root, _base())
    assert "pid_started" not in json.loads(
        lanes.lock_path(root).read_text(encoding="utf-8"))
    assert lanes.lane_state(root)["state"] == lanes.RUNNING


def test_an_unreadable_recorded_start_time_does_not_free_a_live_lane(root):
    """Conservative on garbage, matching pid_alive's own stance: a lock we
    cannot reason about is treated as HELD. Freeing a lane on a malformed field
    would double-book a running worker, which is the worse failure."""
    _write_lock(root, _base(pid_started="not-a-number"))
    assert lanes.lane_state(root)["state"] == lanes.RUNNING


# ---- the writers record it -------------------------------------------------

def test_try_acquire_records_the_holders_start_time(root, worktree):
    res = lanes.try_acquire_lane("gated", run_id="r1", worktree=str(worktree),
                                 root=root)
    assert res["ok"]
    rec = json.loads(lanes.lock_path(root).read_text(encoding="utf-8"))
    assert rec["pid"] == os.getpid()
    assert rec["pid_started"] == lanes.proc_started(os.getpid())
    lanes.release_lane(res["token"], root=root)


def test_repoint_records_the_WORKER_start_time_not_the_claimers(root, worktree):
    """The repoint is where this matters most.

    try_acquire records the CLAIMER (the long-lived RC server, whose start time
    is minutes or days old); repoint swings the lock onto the worker. If it
    moved the pid and left the claimer's start time behind, every repointed
    lock - which is every real lane fire - would instantly look like a pid
    reuse and free itself under a running worker.
    """
    res = lanes.try_acquire_lane("gated", run_id="r1", worktree=str(worktree),
                                 root=root)
    assert res["ok"]
    # Repoint at our own pid again, but with a deliberately wrong value on disk
    # first, so a repoint that forgets to refresh the field is caught.
    lock = lanes.lock_path(root)
    rec = json.loads(lock.read_text(encoding="utf-8"))
    rec["pid_started"] = 1.0
    lock.write_text(json.dumps(rec), encoding="utf-8")

    assert lanes.repoint_lane_pid(res["token"], os.getpid(), root=root)
    rec = json.loads(lock.read_text(encoding="utf-8"))
    assert rec["pid_started"] == lanes.proc_started(os.getpid()), (
        "repoint must re-record the start time for the pid it just installed")
    assert lanes.lane_state(root)["state"] == lanes.RUNNING
    lanes.release_lane(res["token"], root=root)


# ---- end to end: the wedge clears ------------------------------------------

def test_a_pid_reuse_wedged_lane_can_be_claimed_again(root, worktree):
    """The acceptance. Before this fix the second fire returned `lane_held`
    forever and only deleting the file by hand recovered it."""
    _write_lock(root, _base(pid_started=1.0))
    res = lanes.try_acquire_lane("gated", run_id="r2", worktree=str(worktree),
                                 root=root)
    assert res["ok"], f"a recycled-pid lock must not refuse a fire: {res}"
    rec = json.loads(lanes.lock_path(root).read_text(encoding="utf-8"))
    assert rec["run_id"] == "r2", "the new holder must own the lock"
    lanes.release_lane(res["token"], root=root)


def test_a_genuinely_held_lane_is_still_refused(root, worktree):
    """The guard rail on the fix: it must not turn every lock into a free one."""
    _write_lock(root, _base(pid_started=lanes.proc_started(os.getpid())))
    res = lanes.try_acquire_lane("gated", run_id="r3", worktree=str(worktree),
                                 root=root)
    assert not res["ok"] and res["refused"] == "lane_held"

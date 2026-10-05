#!/usr/bin/env python
"""ops/loop/lanes.py on FLEET-KIT fleet_lanes (MAIN v6 order section 4a, v7 rides it).

RC used to run ONE lane at a time: `MAX_SLOTS = 1` and a single `0.lock`. The
v6 order lifts that to the kit's per-repo cap of 3 - lane locks `0.lock`,
`1.lock`, `2.lock`, the lane NAME a payload field, each name exclusive - while
keeping RC's worktree-mandatory guard and the pid-reuse guard.

Also pinned here, the SS 2245 section 5a finding as it applies to RC: the lane
lock directory must resolve against the MAIN tree, never against the worktree
lanes.py happens to be imported from. Before this change `DEFAULT_ROOT` was
`Path(__file__).parent / "control" / "lanes"`, so a driver started inside a
lane worktree claimed into a private, gitignored control dir there and three
lanes became three private caps of one.

Every test drives a tmp tree; nothing touches the live control dir and nothing
launches or kills a process.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lanes = _load("rc_loop_lanes_fleet_v6_test", ROOT / "ops" / "loop" / "lanes.py")
kit_lanes = lanes.fleet_lanes

DEAD_PID = 999999999


@pytest.fixture
def root(tmp_path):
    # A lanes dir sits at <repo>/ops/loop/control/lanes - the kit's LANES_REL.
    return tmp_path / "repo" / "ops" / "loop" / "control" / "lanes"


def _wt(tmp_path, name):
    wt = tmp_path / f"wt-{name}"
    wt.mkdir(exist_ok=True)
    return str(wt)


# ---- the cap ---------------------------------------------------------------

def test_cap_is_three_and_the_single_slot_constants_are_gone():
    assert lanes.LANE_CAP == 3
    assert lanes.LANE_CAP <= kit_lanes.LANE_CAP_MAX
    assert lanes.LANE_CAP <= kit_lanes.GOVERNOR_WIDTH
    assert not hasattr(lanes, "MAX_SLOTS"), "MAX_SLOTS=1 must go (v6 4a)"
    assert not hasattr(lanes, "LOCK_NAME"), "the single 0.lock name must go (v6 4a)"
    assert lanes.REPO_CODE == "RC"


def test_lanes_are_bound_to_the_vendored_kit_module():
    kit_file = Path(kit_lanes.__file__).resolve()
    assert kit_file == (ROOT / "ops" / "fleet_kit" / "fleet_lanes.py").resolve()


def test_default_root_resolves_against_the_main_tree_not_the_importing_worktree():
    """SS 5a. ROOT here may well be a worktree; the default must not be."""
    want = kit_lanes.main_tree(ROOT) / kit_lanes.LANES_REL
    assert Path(lanes.DEFAULT_ROOT) == want
    assert lanes.DEFAULT_ROOT == lanes.REPO_ROOT / kit_lanes.LANES_REL


def test_three_different_lanes_run_at_once_on_three_indices(root, tmp_path):
    got = [lanes.try_acquire_lane(n, run_id=f"r{i}", worktree=_wt(tmp_path, n),
                                  root=root)
           for i, n in enumerate(("upgrade", "research", "queue"))]
    assert [g["ok"] for g in got] == [True, True, True]
    assert sorted(g["index"] for g in got) == [0, 1, 2]
    assert sorted(p.name for p in root.glob("*.lock")) == ["0.lock", "1.lock", "2.lock"]
    rows = lanes.lanes_state(root)
    assert [r["state"] for r in rows] == ["RUNNING"] * 3
    assert {r["lane"] for r in rows} == {"upgrade", "research", "queue"}
    for g in got:
        assert lanes.release_lane(g["token"]) is True
    assert [r["state"] for r in lanes.lanes_state(root)] == ["FREE"] * 3


def test_a_fourth_lane_is_refused_lanes_full_and_writes_no_lock(root, tmp_path):
    for i, n in enumerate(("upgrade", "research", "queue")):
        assert lanes.try_acquire_lane(n, run_id=f"r{i}", worktree=_wt(tmp_path, n),
                                      root=root)["ok"]
    before = sorted((p.name, p.read_bytes()) for p in root.iterdir())
    res = lanes.try_acquire_lane("ds", run_id="r9", worktree=_wt(tmp_path, "ds"),
                                 root=root)
    assert res["ok"] is False and res["refused"] == "lanes_full"
    assert set(res["holders"]) == {"upgrade", "research", "queue"}
    assert sorted((p.name, p.read_bytes()) for p in root.iterdir()) == before


def test_a_lane_name_is_exclusive_across_indices(root, tmp_path):
    a = lanes.try_acquire_lane("upgrade", run_id="r1", worktree=_wt(tmp_path, "u"),
                               root=root)
    b = lanes.try_acquire_lane("research", run_id="r2", worktree=_wt(tmp_path, "r"),
                               root=root)
    assert a["ok"] and b["ok"]
    res = lanes.try_acquire_lane("research", run_id="r3", worktree=_wt(tmp_path, "r"),
                                 root=root)
    assert res["ok"] is False and res["refused"] == "lane_held"
    assert res["holder"] == "research" and res["pid"] == os.getpid()


def test_the_lock_records_rcs_worktree_and_the_holders_identity(root, tmp_path):
    wt = _wt(tmp_path, "gated")
    res = lanes.try_acquire_lane("gated", run_id="r1", worktree=wt, root=root)
    rec = json.loads(Path(res["token"]).read_text(encoding="utf-8"))
    assert Path(rec["worktree"]) == Path(wt).resolve()
    assert rec["lane"] == "gated" and rec["run_id"] == "r1"
    assert rec["repo"] == "RC" and rec["index"] == res["index"]
    assert rec["pid"] == os.getpid()
    assert rec["pid_started"] == lanes.proc_started(os.getpid())
    assert lanes.index_of(res["token"]) == res["index"]


def test_a_dead_holder_at_index_0_is_reclaimed_in_place(root, tmp_path):
    first = lanes.try_acquire_lane("upgrade", run_id="r1", worktree=_wt(tmp_path, "u"),
                                   root=root)
    lock = Path(first["token"])
    rec = json.loads(lock.read_text(encoding="utf-8"))
    rec["pid"] = DEAD_PID
    tmp = lock.with_name("x.tmp")
    tmp.write_text(json.dumps(rec), encoding="utf-8")
    os.replace(tmp, lock)
    assert lanes.lanes_state(root)[0]["state"] == "RECLAIMABLE"
    again = lanes.try_acquire_lane("upgrade", run_id="r2", worktree=_wt(tmp_path, "u"),
                                   root=root)
    assert again["ok"] and again["index"] == 0
    assert len(list(root.glob("*.lock"))) == 1


def test_release_frees_only_its_own_index(root, tmp_path):
    a = lanes.try_acquire_lane("upgrade", run_id="r1", worktree=_wt(tmp_path, "u"),
                               root=root)
    b = lanes.try_acquire_lane("ds", run_id="r2", worktree=_wt(tmp_path, "d"),
                               root=root)
    assert lanes.release_lane(a["token"]) is True
    states = {r["index"]: r["state"] for r in lanes.lanes_state(root)}
    assert states[a["index"]] == "FREE" and states[b["index"]] == "RUNNING"
    lanes.release_lane(b["token"])


def test_lane_state_summary_reports_every_running_lane(root, tmp_path):
    lanes.try_acquire_lane("upgrade", run_id="r1", worktree=_wt(tmp_path, "u"), root=root)
    lanes.try_acquire_lane("ds", run_id="r2", worktree=_wt(tmp_path, "d"), root=root)
    st = lanes.lane_state(root)
    assert st["state"] == "RUNNING"
    assert st["running"] == 2
    assert [r["lane"] for r in st["lanes"] if r["state"] == "RUNNING"] == ["upgrade", "ds"]


def test_a_root_that_is_not_a_lanes_dir_is_refused(tmp_path):
    with pytest.raises(ValueError, match="ops/loop/control/lanes"):
        lanes.try_acquire_lane("upgrade", run_id="r1", worktree=_wt(tmp_path, "u"),
                               root=tmp_path / "elsewhere")


def test_repoint_moves_the_lock_to_the_worker_and_release_still_works(root, tmp_path):
    res = lanes.try_acquire_lane("ds", run_id="r1", worktree=_wt(tmp_path, "d"), root=root)
    assert lanes.repoint_lane_pid(res["token"], os.getpid()) is True
    rec = json.loads(Path(res["token"]).read_text(encoding="utf-8"))
    assert rec["pid"] == os.getpid() and rec["claimed_by_pid"] == os.getpid()
    assert lanes.release_lane(res["token"]) is True


# ---- callers: the interrupt targets EVERY running lane ---------------------

def test_interrupt_holders_lists_every_running_lane(root, tmp_path, monkeypatch):
    """With one lane max, `_holders` read the single lane_state answer. With
    three, an interrupt that only saw the first running lane would leave two
    workers alive behind a confirmed kill."""
    interrupt = _load("rc_loop_interrupt_fleet_v6_test",
                      ROOT / "ops" / "loop" / "interrupt.py")
    monkeypatch.setattr(interrupt, "CONTROLLER_LOCK", tmp_path / "no-RUNNING.lock")
    for i, n in enumerate(("upgrade", "ds")):
        assert interrupt.lanes.try_acquire_lane(
            n, run_id=f"r{i}", worktree=_wt(tmp_path, n), root=root)["ok"]
    got = interrupt._holders(root=root)
    assert sorted(h["lane"] for h in got if h["kind"] == "lane") == ["ds", "upgrade"]
    assert all(h["pid"] == os.getpid() for h in got)

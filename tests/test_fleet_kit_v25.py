"""FLEET-KIT v25 (MAIN 2026-10-27 2136 ORDER to all seven, cumulative, LANE-CAP:
lane cap and governor width from machine config, borrowing + should_yield,
lane admission, lanes status): the tree-side half of the adoption.

The kit bytes are pinned by tests/test_fleet_kit_conformance.py and
tests/test_fleet_kit_v15.py (manifest sha + common block). This file pins
what the ORDER's section 5 asks RC to do around them:
  * step 1: the vendored kit is v25, patch 0, 23 files + MANIFEST, manifest
    sha from the ORDER's section 1; FLEET-COMMON block unchanged and
    conformance() == [];
  * step 2: RC's lane driver (ops/loop/lanes.py) reads its cap from the live
    machine config - with FLEET_LANES_CONFIG naming {"governor_width": 5,
    "lane_cap_max": 5} the cap, the lane rows and the acquire limit read 5,
    and with the file missing they read 3; no hard-coded 3 sizes anything;
    the kit governor's slot rows follow the same config;
  * step 3: queue_loop.run_loop asks lanes.should_yield() BETWEEN cycles and,
    on True, ends the lane after its current cycle - never kill / terminate;
    an "admission" refusal is recorded like lanes_full;
  * section 4: lane_cap above the machine cap clamps instead of raising;
  * CLAUDE.md carries the RC "KIT v25" rules line naming this guard.
RC was on v24 (MAIN drift 2026-10-27 21:3x), so section 2 owes nothing.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import inspect
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"
V25_MANIFEST_SHA256 = "fa04c87ceca7c1e08f853d0447a439143f317fa21b6434c1dcefe1e5d25c1bea"
V25_COMMON_BLOCK_SHA256 = "886c5f8b1a86928f91412d2800e9dfef3dd8e5b9158d14a06e65d06c22964800"
END = "<!-- FLEET-COMMON END -->"

lanes = importlib.import_module("ops.loop.lanes")
qloop = importlib.import_module("ops.loop.queue_loop")
kit_lanes = lanes.fleet_lanes


def _load(name):
    spec = importlib.util.spec_from_file_location(f"rc_v25_probe_{name}", KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(rel):
    return (ROOT / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


@pytest.fixture
def lanes_root(tmp_path):
    return tmp_path / "repo" / "ops" / "loop" / "control" / "lanes"


@pytest.fixture
def config5(tmp_path, monkeypatch):
    cfg = tmp_path / "lanes.json"
    cfg.write_bytes(b'{"governor_width": 5, "lane_cap_max": 5}')
    monkeypatch.setenv(kit_lanes.CONFIG_ENV, str(cfg))
    return cfg


@pytest.fixture
def config_missing(tmp_path, monkeypatch):
    monkeypatch.setenv(kit_lanes.CONFIG_ENV, str(tmp_path / "absent" / "lanes.json"))


def _wt(tmp_path, name):
    wt = tmp_path / f"wt-{name}"
    wt.mkdir(exist_ok=True)
    return str(wt)


# ---------------------------------------------------------------- step 1

def test_the_vendored_kit_is_the_v25_order_bytes_and_conforms():
    raw = (KIT / "MANIFEST.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V25_MANIFEST_SHA256
    man = json.loads(raw.decode("ascii"))
    assert man["version"] == 25 and len(man["files"]) == 23
    assert man["common_block_sha256"] == V25_COMMON_BLOCK_SHA256
    fh = _load("fleet_headless")
    assert (fh.KIT_VERSION, fh.KIT_PATCH) == (25, 0)
    for name, want in man["files"].items():
        assert hashlib.sha256((KIT / name).read_bytes()).hexdigest() == want, name
    assert fh.conformance(ROOT) == []


# ---------------------------------------------------------------- step 2

def test_the_lane_cap_reads_five_from_the_machine_config(config5, lanes_root, tmp_path):
    assert kit_lanes.load_config()["lane_cap_max"] == 5
    assert lanes.lane_cap() == 5
    assert len(lanes.lanes_state(lanes_root)) == 5
    names = ("upgrade", "uiux", "research", "ds", "repo")
    got = [lanes.try_acquire_lane(n, run_id=f"r{i}", worktree=_wt(tmp_path, n),
                                  root=lanes_root) for i, n in enumerate(names)]
    try:
        assert [g["ok"] for g in got] == [True] * 5
        assert sorted(g["index"] for g in got) == [0, 1, 2, 3, 4]
        sixth = lanes.try_acquire_lane("queue", run_id="r9",
                                       worktree=_wt(tmp_path, "queue"), root=lanes_root)
        assert sixth["ok"] is False and sixth["refused"] == "lanes_full"
    finally:
        for g in got:
            if g.get("ok"):
                lanes.release_lane(g["token"])


def test_the_lane_cap_reads_three_with_the_file_missing(config_missing, lanes_root, tmp_path):
    assert kit_lanes.load_config()["source"] == "defaults"
    assert lanes.lane_cap() == 3
    assert len(lanes.lanes_state(lanes_root)) == 3
    names = ("upgrade", "uiux", "research")
    got = [lanes.try_acquire_lane(n, run_id=f"r{i}", worktree=_wt(tmp_path, n),
                                  root=lanes_root) for i, n in enumerate(names)]
    try:
        assert [g["ok"] for g in got] == [True] * 3
        fourth = lanes.try_acquire_lane("ds", run_id="r9",
                                        worktree=_wt(tmp_path, "ds"), root=lanes_root)
        assert fourth["ok"] is False and fourth["refused"] == "lanes_full"
    finally:
        for g in got:
            if g.get("ok"):
                lanes.release_lane(g["token"])


def test_the_recommended_machine_config_lets_rc_hold_all_seven_rotation_lanes(
        tmp_path, monkeypatch, lanes_root):
    # ORDER section 3's recommended config (the RC LANE-CAP request): every lane
    # of the s144 rotation ("upgrade" excluded) can hold a lane at once.
    cfg = tmp_path / "lanes7.json"
    cfg.write_bytes(b'{"governor_width": 7, "lane_cap_max": 7, "ram_floor_mb": 4096, '
                    b'"cpu_ceiling_pct": 90}')
    monkeypatch.setenv(kit_lanes.CONFIG_ENV, str(cfg))
    assert lanes.lane_cap() == 7
    assert len(lanes.lanes_state(lanes_root)) == 7
    names = ("gated", "queue", "uiux", "research", "ds", "repo", "true-audit")
    got = [lanes.try_acquire_lane(n, run_id=f"r{i}", worktree=_wt(tmp_path, n),
                                  root=lanes_root) for i, n in enumerate(names)]
    try:
        assert [g["ok"] for g in got] == [True] * 7
        assert sorted(g["index"] for g in got) == list(range(7))
        eighth = lanes.try_acquire_lane("upgrade", run_id="r9",
                                        worktree=_wt(tmp_path, "upgrade"), root=lanes_root)
        assert eighth["ok"] is False and eighth["refused"] == "lanes_full"
    finally:
        for g in got:
            if g.get("ok"):
                lanes.release_lane(g["token"])


def test_the_kit_governor_slot_count_follows_the_config(config5, tmp_path, monkeypatch):
    groot = tmp_path / "slots"
    groot.mkdir()
    assert len(kit_lanes.governor_state(groot)) == 5
    monkeypatch.setenv(kit_lanes.CONFIG_ENV, str(tmp_path / "absent.json"))
    assert len(kit_lanes.governor_state(groot)) == 3


def test_no_hard_coded_cap_sizes_the_driver():
    src = _text("ops/loop/lanes.py")
    assert "LANE_CAP = 3" not in src
    tree = ast.parse(src)
    for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef)):
        used = {x.id for x in ast.walk(fn) if isinstance(x, ast.Name)}
        assert "LANE_CAP" not in used, fn.name
    # the kit default is all LANE_CAP still names
    assert lanes.LANE_CAP == kit_lanes.LANE_CAP_MAX


def test_an_admission_refusal_passes_through_like_lanes_full(monkeypatch, lanes_root, tmp_path):
    def refuse(*a, **k):
        return {"ok": False, "refused": "admission", "reason": "free RAM 100 MB < floor",
                "holders": []}
    monkeypatch.setattr(kit_lanes, "try_acquire_lane", refuse)
    res = lanes.try_acquire_lane("ds", run_id="r1", worktree=_wt(tmp_path, "ds"),
                                 root=lanes_root)
    assert res["ok"] is False and res["refused"] == "admission"
    assert "floor" in res["reason"]
    assert not lanes_root.exists() or not list(lanes_root.glob("*.lock"))
    assert qloop._refusal_detail(res).startswith("admission refused")


# ---------------------------------------------------------------- step 3

def test_lanes_should_yield_asks_the_kit_for_rc_and_fails_open(monkeypatch):
    seen = []
    monkeypatch.setattr(kit_lanes, "should_yield", lambda code, **k: seen.append(code) or True)
    assert lanes.should_yield() is True and seen == ["RC"]

    def boom(code, **k):
        raise OSError("governor unreadable")
    monkeypatch.setattr(kit_lanes, "should_yield", boom)
    assert lanes.should_yield() is False


def _loop_fakes():
    log = {"kill": [], "launch": [], "release": [], "yield": []}
    state = {"t": 1000.0}

    def acquire(lane, *, run_id, worktree, **kw):
        return {"ok": True, "lane": lane, "run_id": run_id, "worktree": worktree,
                "token": f"T-{run_id}"}

    def launch(lane, *, run_id, token, **kw):
        log["launch"].append(run_id)
        return {"lane": lane, "run_id": run_id, "pid": 4242, "worktree": "wt",
                "log": "log", "prompt": "p", "started_at": state["t"]}

    def tick():
        state["t"] += 1.0
        return state["t"]

    def gh(args):
        raise AssertionError("no test may shell out to gh")

    return log, {"acquire": acquire, "release": lambda tok, **k: log["release"].append(tok) or True,
                 "launch": launch, "alive": lambda pid: False,
                 "proc_started": lambda pid: None, "stranger": lambda *a, **k: False,
                 "kill": lambda pid: log["kill"].append(pid), "sleep": lambda s: None,
                 "clock": tick, "monotonic": tick, "head_sha": lambda: "cafe",
                 "gh": gh, "emit": lambda line: None}


def test_should_yield_true_ends_the_lane_after_its_cycle_and_never_kills(tmp_path):
    log, seams = _loop_fakes()

    def should_yield():
        log["yield"].append(1)
        return True

    summary = qloop.run_loop(max_cycles=5, settle_s=0, control_dir=tmp_path / "ctl",
                             cycle_log=tmp_path / "q.jsonl", worktree=_wt(tmp_path, "queue"),
                             should_yield=should_yield, **seams)
    assert summary["stopped_by"] == qloop.STOPPED_BY_FAIR_YIELD
    assert summary["cycles_run"] == 1 and len(log["launch"]) == 1
    assert log["kill"] == [], "a yield must never kill a worker"
    assert log["release"] == ["T-" + summary["records"][0]["run_id"]]
    assert log["yield"] == [1], "asked once, at the first cycle boundary only"


def test_should_yield_false_runs_every_cycle(tmp_path):
    log, seams = _loop_fakes()
    summary = qloop.run_loop(max_cycles=3, settle_s=0, control_dir=tmp_path / "ctl",
                             cycle_log=tmp_path / "q.jsonl", worktree=_wt(tmp_path, "queue"),
                             should_yield=lambda: False, **seams)
    assert summary["stopped_by"] == qloop.STOPPED_BY_MAX_CYCLES
    assert summary["cycles_run"] == 3 and log["kill"] == []


def test_the_driver_never_calls_kill_or_terminate_on_the_yield_path():
    src = _text("ops/loop/queue_loop.py")
    tree = ast.parse(src)
    run_loop = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_loop")
    yields = [n for n in ast.walk(run_loop) if isinstance(n, ast.If)
              and "should_yield" in ast.get_source_segment(src, n.test)]
    assert len(yields) == 1
    body_calls = {
        (c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", ""))
        for stmt in yields[0].body for c in ast.walk(stmt) if isinstance(c, ast.Call)}
    assert not body_calls & {"kill", "terminate", "_taskkill", "send_signal"}, body_calls
    assert any(isinstance(s, ast.Break) for s in yields[0].body)
    assert inspect.signature(qloop.run_loop).parameters["should_yield"].default is lanes.should_yield


# ---------------------------------------------------------------- section 4

def test_a_cap_above_the_machine_cap_clamps_instead_of_raising(config_missing):
    assert kit_lanes.lane_cap(4) == 3
    assert kit_lanes.lane_cap(None) == 3
    with pytest.raises(ValueError):
        kit_lanes.lane_cap(0)
    with pytest.raises(ValueError):
        kit_lanes.lane_cap(True)


# ---------------------------------------------------------------- CLAUDE.md

def test_claude_md_carries_the_kit_v25_rules_line():
    text = _text("CLAUDE.md")
    rc = text[text.index(END):]
    line = next(ln for ln in rc.split("\n") if ln.startswith("**KIT v25 (MAIN 2026-10-27 2136"))
    for needle in ("LANE-CAP", "should_yield", "Guard `tests/test_fleet_kit_v25.py`"):
        assert needle in line, needle
    assert (ROOT / "CLAUDE.md").stat().st_size <= 60 * 1024

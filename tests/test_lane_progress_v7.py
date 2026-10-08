#!/usr/bin/env python
"""FLEET-COMMON item 13 d (kit v7, MAIN 2026-10-05 0215 sections 2d + 4d).

Every headless lane fire builds a `fleet_checklist.Checklist`, prints it to its
log, and writes it as the "checklist" field of its item-12 progress file
`ops/loop/control/progress/lane-<i>.json` - i = its lane-lock index - in the
MAIN checkout (fleet_lanes.main_tree), never inside its worktree, rewritten at
fire start and after every task. The loop controller holds no lane lock, so it
writes the same shape to `progress/loop.json`.

Nothing here spawns a process; the lane runners are driven through their
injection seams.
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


lp = _load("rc_loop_lane_progress_v7_test", ROOT / "ops" / "loop" / "lane_progress.py")
BOX = lp.fleet_checklist.BOX  # the kit's box glyph, never spelled in this file


def _doc(main: Path, task: str) -> dict:
    return json.loads((main / "ops/loop/control/progress" / f"{task}.json")
                      .read_text(encoding="ascii"))


def test_the_helpers_are_the_vendored_kit():
    assert Path(lp.fleet_checklist.__file__).resolve() == \
        (ROOT / "ops/fleet_kit/fleet_checklist.py").resolve()
    assert Path(lp.fleet_headless.__file__).resolve() == \
        (ROOT / "ops/fleet_kit/fleet_headless.py").resolve()
    # Kit v8 (MAIN 2026-10-05 0310) superseded v7, kit v9 (MAIN 2026-10-07
    # 2354) superseded v8, and kit v10 (MAIN 2026-10-08 0839) superseded v9,
    # each with write_progress(checklist=) unchanged (v9 only added an SPDX
    # header to fleet_checklist; v10 added emit()).
    assert lp.fleet_headless.KIT_VERSION == 10


def test_the_vendored_kit_is_v10_with_its_sixteen_file_set():
    man = json.loads((ROOT / "ops/fleet_kit/MANIFEST.json").read_text(encoding="ascii"))
    assert man["version"] == 10
    assert sorted(man["files"]) == sorted([
        "FLEET-COMMON.md", "LICENSE", "NOTICE", "cli_display.json",
        "fleet_checklist.py", "fleet_done.py", "fleet_headless.py",
        "fleet_inbox.py", "fleet_lanes.py", "fleet_secrets.py",
        "fleet_statusline.js", "fleet_subagent_first.py",
        "fleet_subagent_status.js", "fleet_watch.py",
        "tokens.css", "tokens.json"])
    on_disk = {p.name for p in (ROOT / "ops/fleet_kit").iterdir()
               if p.is_file() and p.name != "MANIFEST.json"}
    assert on_disk == set(man["files"]), "a kit file is missing or stray"


def test_default_root_is_the_main_checkout_never_a_worktree(monkeypatch):
    # conftest redirects both seams for hermeticity; the DEFAULT is under test.
    monkeypatch.setattr(lp, "ROOT_OVERRIDE", None)
    monkeypatch.delenv(lp.ROOT_ENV, raising=False)
    want = lp.fleet_lanes.main_tree(ROOT)
    assert lp.main_checkout() == want
    dotgit = want / ".git"
    if dotgit.exists():
        assert dotgit.is_dir(), "progress must land in the MAIN checkout"


def test_the_env_override_reaches_main_checkout(tmp_path, monkeypatch):
    """A child process inherits RC_LANE_PROGRESS_ROOT, never ROOT_OVERRIDE."""
    monkeypatch.setattr(lp, "ROOT_OVERRIDE", None)
    monkeypatch.setenv(lp.ROOT_ENV, str(tmp_path))
    assert lp.main_checkout() == tmp_path
    monkeypatch.delenv(lp.ROOT_ENV)
    assert lp.main_checkout() == lp.fleet_lanes.main_tree(ROOT)


def test_lane_fire_writes_lane_i_json_with_the_remaining_checklist(tmp_path):
    lines = []
    p = lp.LaneProgress.for_lane(
        2, 7, [("L1", "Prepare the lane worktree", "running", 30),
               ("L2", "Start the queue worker"),
               ("L3", "Run the queue worker")],
        root=tmp_path, emit=lines.append)
    text = p.start()
    assert text.splitlines()[0] == "Session 7 checklist"
    assert text.splitlines()[-1] == f"{BOX} /done"
    assert lines == [text], "the block is printed to the log"
    doc = _doc(tmp_path, "lane-2")
    assert doc["task"] == "lane-2" and doc["status"] == "running"
    assert [r["id"] for r in doc["checklist"]] == ["L1", "L2", "L3"]
    assert doc["checklist"][0]["state"] == "running"

    p.complete("L1")
    doc = _doc(tmp_path, "lane-2")
    assert [r["id"] for r in doc["checklist"]] == ["L2", "L3"], "remaining only"
    assert 0 < doc["pct"] < 100

    p.complete("L2")
    p.complete("L3")
    doc = _doc(tmp_path, "lane-2")
    assert doc["checklist"] == [] and doc["status"] == "done" and doc["pct"] == 100
    assert not list(tmp_path.glob("*.tmp")) and \
        not list((tmp_path / "ops/loop/control/progress").glob("*.tmp"))


def test_a_failed_fire_is_recorded_failed_with_what_was_left(tmp_path):
    p = lp.LaneProgress.for_lane(0, 1, [("L1", "Prepare"), ("L2", "Start")],
                                 root=tmp_path, emit=lambda _s: None)
    p.start()
    p.fail("worktree add failed")
    doc = _doc(tmp_path, "lane-0")
    assert doc["status"] == "failed" and "worktree add failed" in doc["step"]
    assert [r["id"] for r in doc["checklist"]] == ["L1", "L2"]


def test_a_progress_write_failure_never_fails_the_lane(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(lp.fleet_headless, "write_progress", boom)
    seen = []
    p = lp.LaneProgress.for_lane(1, 1, [("L1", "Prepare")], root=tmp_path,
                                 emit=seen.append)
    p.start()
    p.complete("L1")
    assert any("progress write failed" in s for s in seen)


def test_an_update_after_four_completions_is_printed(tmp_path):
    seen = []
    items = [(f"T{i}", f"Task {i}") for i in range(1, 7)]
    p = lp.LaneProgress("loop", 3, items, root=tmp_path, emit=seen.append)
    p.start()
    for i in range(1, 5):
        p.complete(f"T{i}")
    assert seen[-1].startswith("Session 3 checklist - remaining")
    assert "T5" in seen[-1] and "T1" not in seen[-1]


# ---- kit v10: checklist printing goes through fleet_checklist.emit() --------
# MAIN 2026-10-08 0839 ORDER step 5. The fire's sinks are queue_loop._emit and
# loop_controller.log (print() under pythonw, stdout redirected to a cp1252
# file) and lane_launcher's logger; the U+2610 box cannot encode on the first
# two, and a raise from prog.start() escapes launch_lane before its release.

def test_checklist_printing_goes_through_the_kits_emit(tmp_path, monkeypatch):
    calls = []
    real = lp.fleet_checklist.emit

    def spy(text, stream=None):
        calls.append(text)
        return real(text, stream)

    monkeypatch.setattr(lp.fleet_checklist, "emit", spy)
    seen = []
    p = lp.LaneProgress("loop", 2, [("T1", "Task 1")], root=tmp_path, emit=seen.append)
    text = p.start()
    assert calls == [text] and seen == [text]


def test_a_cp1252_sink_gets_the_ascii_box_and_never_fails_the_fire(tmp_path):
    seen = []

    def cp1252_print(line):
        line.encode("cp1252")  # U+2610 raises UnicodeEncodeError, as print() does
        seen.append(line)

    p = lp.LaneProgress("loop", 2, [("T1", "Task 1")], root=tmp_path, emit=cp1252_print)
    text = p.start()
    assert BOX in text, "the returned block keeps the glyph"
    assert seen == [text.replace(BOX, "[ ]")]
    assert _doc(tmp_path, "loop")["status"] == "running"


def test_a_dead_sink_never_fails_the_fire(tmp_path):
    def dead(_line):
        raise OSError("log handle closed")

    p = lp.LaneProgress("loop", 2, [("T1", "Task 1"), ("T2", "Task 2")],
                        root=tmp_path, emit=dead)
    p.start()
    p.complete("T1")
    p.fail("worker died")
    assert _doc(tmp_path, "loop")["status"] == "failed"


# ---- the lane runner: launch_lane writes lane-<i>.json ---------------------

launcher = _load("rc_loop_lane_launcher_v7_test",
                 ROOT / "ops" / "loop" / "lane_launcher.py")


class _Proc:
    pid = os.getpid()


def test_launch_lane_writes_its_checklist_at_fire_start_and_after_each_task(
        tmp_path, monkeypatch):
    lanes = launcher.lanes
    root = tmp_path / "repo" / "ops" / "loop" / "control" / "lanes"
    wt = tmp_path / "wt"
    wt.mkdir()
    claim = lanes.try_acquire_lane("ds", run_id="r1", worktree=str(wt), root=root)
    assert claim["ok"]
    monkeypatch.setattr(launcher, "ensure_worktree", lambda *a, **k: wt)
    writes = []
    real = lp.LaneProgress._write

    def spy(self, step, status):
        writes.append((self.task, [r["id"] for r in self.cl.rows()], status))
        return real(self, step, status)

    monkeypatch.setattr(lp.LaneProgress, "_write", spy)
    monkeypatch.setattr(launcher, "_progress_mod", lambda: lp)
    main = tmp_path / "main"
    run = launcher.launch_lane("ds", run_id="r1", token=claim["token"],
                               log_dir=tmp_path / "logs",
                               spawn=lambda *a: _Proc(), progress_root=main,
                               session=4)
    assert run["pid"] == os.getpid()
    task = f"lane-{claim['index']}"
    # Kit v8 item 14: the inbox pass (I1) is the first row of every fire.
    assert writes[0] == (task, ["I1", "L1", "L2", "L3"], "running"), "fire start"
    assert writes[2][1] == ["L1", "L2", "L3"], "the inbox pass completed first"
    assert writes[3][1] == ["L2", "L3"] and writes[4][1] == ["L3"]
    doc = _doc(main, task)
    assert doc["checklist"][0]["id"] == "L3"
    assert doc["checklist"][0]["state"] == "worker running"
    lanes.release_lane(claim["token"])


qloop = _load("rc_loop_queue_loop_v7_test", ROOT / "ops" / "loop" / "queue_loop.py")


@pytest.mark.parametrize("alive_ticks,timeout,want_status", [
    (1, 10_000, "done"),     # worker exits on its own: L3 completes
    (-1, 0, "failed"),       # worker overruns its budget: the fire is failed
])
def test_queue_cycle_passes_its_cycle_as_the_session_and_closes_the_checklist(
        tmp_path, alive_ticks, timeout, want_status):
    """The queue driver is the lane runner that WAITS for its worker, so it is
    the one that can mark L3 when the worker exits (item 13 d: after every
    task). launch_lane hands it the fire's LaneProgress."""
    prog = lp.LaneProgress.for_lane(
        1, 5, [("L1", "Prepare"), ("L2", "Start"), ("L3", "Run the queue worker")],
        root=tmp_path, emit=lambda _s: None)
    prog.start()
    prog.complete("L1")
    prog.complete("L2")
    seen = {}
    ticks = {"n": alive_ticks}

    def launch(lane, *, run_id, token, **kw):
        seen.update(kw)
        return {"pid": 4242, "log": "log", "progress": prog}

    def alive(_pid):
        if ticks["n"] == -1:
            return True
        ticks["n"] -= 1
        return ticks["n"] >= 0

    mono = {"t": 0.0}

    def monotonic():
        mono["t"] += 1.0
        return mono["t"]

    rec = qloop.run_cycle(
        5, acquire=lambda lane, **k: {"ok": True, "token": "T"},
        release=lambda token, **k: True, launch=launch, alive=alive,
        proc_started=lambda pid: None, stranger=lambda pid, rec: False,
        kill=lambda pid: None, sleep=lambda s: None, monotonic=monotonic,
        cycle_timeout_s=timeout, kill_grace_s=0, poll_s=1)
    assert seen.get("session") == 5, "the cycle number is the fire's run count"
    assert callable(seen.get("emit")), "the checklist prints to the driver log"
    doc = _doc(tmp_path, "lane-1")
    assert doc["status"] == want_status, rec


def test_loop_controller_cycle_checklist_writes_loop_json(tmp_path):
    """The loop controller holds no lane lock (it runs on RUNNING.lock), so its
    item-13 d file is progress/loop.json, session n = the cycle."""
    spec = importlib.util.spec_from_file_location(
        "loop_controller_uut_v7", ROOT / "ops" / "loop" / "loop_controller.py")
    lc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lc)
    seen = []
    prog = lc.cycle_checklist(9, root=tmp_path, emit=seen.append)
    prog.start()
    assert seen[0].splitlines()[0] == "Session 9 checklist"
    doc = _doc(tmp_path, "loop")
    assert [r["id"] for r in doc["checklist"]] == ["I1", "C1", "C2", "C3", "C4"]
    for cid in ("I1", "C1", "C2", "C3", "C4"):
        prog.complete(cid)
    doc = _doc(tmp_path, "loop")
    assert doc["status"] == "done" and doc["checklist"] == []


def test_loop_controller_wraps_the_executor_call_in_its_checklist():
    """Source pin, because main() cannot run in a unit test: the checklist is
    started at the cycle top and each task is completed around its call, and
    the executor call keeps its ONE slots.hold - no governor= beside it."""
    src = (ROOT / "ops" / "loop" / "loop_controller.py").read_text(encoding="utf-8")
    body = src[src.index("def main():"):]
    for needle in ("prog = cycle_checklist(cycle)", "prog.start()",
                   'prog.complete("C1")', 'prog.complete("C2")',
                   'prog.complete("C3")', 'prog.complete("C4")'):
        assert needle in body, needle
    assert body.index('prog.set_state("C2"') < body.index("with slots.hold(")
    assert "governor=" not in body


def test_launch_lane_records_failed_when_the_spawn_fails(tmp_path, monkeypatch):
    lanes = launcher.lanes
    root = tmp_path / "repo" / "ops" / "loop" / "control" / "lanes"
    wt = tmp_path / "wt"
    wt.mkdir()
    claim = lanes.try_acquire_lane("ds", run_id="r2", worktree=str(wt), root=root)
    monkeypatch.setattr(launcher, "ensure_worktree", lambda *a, **k: wt)
    monkeypatch.setattr(launcher, "_progress_mod", lambda: lp)

    def bad_spawn(*_a):
        raise launcher.LaneLaunchError("spawn failed: nope")

    main = tmp_path / "main"
    with pytest.raises(launcher.LaneLaunchError):
        launcher.launch_lane("ds", run_id="r2", token=claim["token"],
                             log_dir=tmp_path / "logs", spawn=bad_spawn,
                             progress_root=main, session=1)
    doc = _doc(main, f"lane-{claim['index']}")
    assert doc["status"] == "failed"
    assert [r["id"] for r in doc["checklist"]] == ["L2", "L3"]

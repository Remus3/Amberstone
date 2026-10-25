"""RM-874: the fleet test guard must not fail a suite because a LIVE lane driver
rewrote its own state mid-run, and must still fail on every other live write.

Measured s133 (LEDGER 1811 / 1832 / 1839): three test batches ERRORED once at
the guard's session teardown with
  `fleet_test_guard: the suite touched live tree state - changed 1
   (ops/loop/control/lane_prompts/s133_queue_state.json)`
  `... changed 2 (ops/loop/control/lane_prompts/s133-gated.md,
   ops/loop/control/lane_prompts/s133_gated_state.json)`
and passed on re-run. Writers, in the gitignored per-session driver
ops/loop/control/lane_prompts/s133_lane_driver.py:
  * write_state() -> s<NNN>_<lane>_state.json (`state_path` :104-105, tmp then
    replace :116-118), at every claim / launch / wait / between cycles;
  * build_prompt() -> the rendered directive s<NNN>-<lane>.md (:279-282), once
    per cycle;
  * say() / append_cycle() -> *.log / *.jsonl and the .json.tmp / .md.tmp temps,
    which the kit IGNORE already covers.
The kit's own spawn writers (fleet_headless.py BUDGET_REL / STATUS_REL /
USAGE_REL / PROGRESS_REL :258-261, fleet_lanes.py LANES_REL :77) are in the kit
IGNORE already. So RC adds exactly the two driver families through
tests/_fleet_guard_config.EXTRA_IGNORE (kit v14: install(..., extra_ignore=...),
never a restated IGNORE). These tests drive the kit's real snapshot / compare /
verdict with the same ignore tuple install() builds (IGNORE + extra_ignore).
ASCII only.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from tests import _fleet_guard_config as cfg

ROOT = Path(__file__).resolve().parents[1]
LP = "ops/loop/control/lane_prompts"
LANES = ("research", "queue", "gated")

# The exact files the s133 driver rewrites on its own schedule and the kit
# IGNORE misses (the failure messages above name them).
DRIVER_STATE = tuple(f"{LP}/s133_{lane}_state.json" for lane in LANES)
DRIVER_DIRECTIVE = tuple(f"{LP}/s133-{lane}.md" for lane in LANES)
# RM-874 residual, measured s134 M1c gated run (8 teardown ERRORs + the NOW-6
# nested run): the s134 driver adds two more families of its own -
# s134_<lane>_last.json (the per-cycle result record, s134_lane_driver.py
# `last = HERE / f"s134_{lane}_last.json"`) and the headless lane worker's
# report under s134_reports/ (`REPORTS = HERE / "s134_reports"`,
# `report = REPORTS / f"{lane}_{run_id}.md"`). Named from the failure lines.
DRIVER_LAST = (f"{LP}/s134_ds_last.json", f"{LP}/s134_queue_last.json",
               f"{LP}/s134_uiux_last.json")
DRIVER_REPORT = (f"{LP}/s134_reports/ds_s134d005-c95b9a.md",
                 f"{LP}/s134_reports/uiux_s134u005-c944ac.md")
REPORTS_GLOB_DIR = "s[0-9][0-9][0-9]_reports/"


def _guard():
    cached = sys.modules.get("fleet_test_guard")
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(
        "fleet_test_guard", ROOT / "ops" / "fleet_kit" / "fleet_test_guard.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fleet_test_guard"] = mod
    spec.loader.exec_module(mod)
    return mod


def _ignore():
    """What install() uses: tuple(ignore) + tuple(extra_ignore)."""
    return tuple(_guard().IGNORE) + tuple(cfg.EXTRA_IGNORE)


def _put(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("ascii"))
    return p


def _age(root: Path, rels) -> None:
    for rel in rels:
        os.utime(root / rel, ns=(10**18, 10**18))


def _driver_tree(root: Path) -> None:
    """A tmp tree laid out like the live control dir while the s133 lanes run."""
    for lane in LANES:
        _put(root, f"{LP}/s133_{lane}_state.json", '{"status": "waiting"}\n')
        _put(root, f"{LP}/s133-{lane}.md", "directive v1\n")
        _put(root, f"{LP}/s133_{lane}_cycles.jsonl", "{}\n")
        _put(root, f"{LP}/s133_{lane}_driver.log", "start\n")
        _put(root, f"{LP}/s133-{lane}.tmpl", "@@LANE@@\n")
    _put(root, f"{LP}/s133-common.tmpl", "@@LANE_DIRECTIVE@@\n")
    _put(root, f"{LP}/s133_lane_driver.py", "# driver\n")
    _put(root, f"{LP}/s133_lane_progress.py", "# progress\n")
    _put(root, "ops/loop/control/lane_exclusions.txt", "- a/b.py\n")
    _put(root, "ops/loop/control/inbox_tick_last.json", "{}\n")
    _put(root, "moon_sync_inbox/2026-10-25-0100-MAIN-to-RC.txt", "note\n")
    _put(root, "moon_sync_outbox/2026-10-25-0101-RC-to-MAIN.txt", "note\n")
    _age(root, [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()])


def _driver_cycle(root: Path, lane: str) -> None:
    """One driver cycle's writes, in the driver's own shape (tmp then replace)."""
    state = root / LP / f"s133_{lane}_state.json"
    tmp = state.with_suffix(".json.tmp")
    tmp.write_bytes(json.dumps({"status": "running", "cycle": 2}, indent=1)
                    .encode("ascii") + b"\n")
    tmp.replace(state)
    out = root / LP / f"s133-{lane}.md"
    tmp = out.with_suffix(".md.tmp")
    tmp.write_bytes(b"directive v2 - a longer rendered prompt\n")
    tmp.replace(out)
    with open(root / LP / f"s133_{lane}_cycles.jsonl", "a", encoding="ascii") as fh:
        fh.write('{"cycle": 2}\n')
    with open(root / LP / f"s133_{lane}_driver.log", "a", encoding="ascii") as fh:
        fh.write("cycle 2\n")


def _verdict(root: Path, before) -> str:
    g = _guard()
    return g.verdict(*g.compare(before, g.snapshot(root, g.WATCH, _ignore()), g.INFLOW))


# ---------------------------------------------------------------- ignored

@pytest.mark.parametrize("lane", LANES)
def test_a_driver_cycle_mid_session_does_not_fail_the_guard(tmp_path, lane):
    g = _guard()
    _driver_tree(tmp_path)
    raw = g.snapshot(tmp_path, g.WATCH, ())
    before = g.snapshot(tmp_path, g.WATCH, _ignore())
    _driver_cycle(tmp_path, lane)
    changed = g.compare(raw, g.snapshot(tmp_path, g.WATCH, ()), g.INFLOW)[0]
    # Positive control: the simulated cycle really changed both driver files.
    assert f"{LP}/s133_{lane}_state.json" in changed
    assert f"{LP}/s133-{lane}.md" in changed
    assert _verdict(tmp_path, before) == ""


@pytest.mark.parametrize("rel", DRIVER_STATE + DRIVER_DIRECTIVE + DRIVER_LAST + DRIVER_REPORT)
def test_each_measured_driver_file_is_ignored(rel):
    lowered = rel.lower()
    import fnmatch
    hits = [gl for gl in _ignore() if fnmatch.fnmatchcase(lowered, gl.lower())]
    assert hits, f"{rel} is not ignored by the installed guard"
    # It is RC's EXTRA_IGNORE that covers it, not the kit default.
    assert not [gl for gl in _guard().IGNORE if fnmatch.fnmatchcase(lowered, gl.lower())]


def test_the_driver_files_appearing_mid_session_do_not_fail_the_guard(tmp_path):
    # A driver started after the suite: its first state + directive are NEW files.
    g = _guard()
    _put(tmp_path, "ops/loop/control/lane_exclusions.txt", "- a\n")
    before = g.snapshot(tmp_path, g.WATCH, _ignore())
    for rel in DRIVER_STATE + DRIVER_DIRECTIVE:
        _put(tmp_path, rel, "x\n")
    assert _verdict(tmp_path, before) == ""


# ---------------------------------------------------------------- still caught

@pytest.mark.parametrize("rel", [
    "ops/loop/control/STOP",
    "ops/loop/control/lanes_STOP.txt",
    f"{LP}/s133_queue_state.json.bak",
    "ops/loop/control/s133_queue_state.json",
    f"{LP}/notes.md",
    f"{LP}/queue-rm740e-s115.md",
    f"{LP}/s133_state.json",
    f"{LP}/s134_last.json",
    f"{LP}/s134_reports.md",
    f"{LP}/notes/s134_queue_last.json",
    f"{LP}/s134_reports/queue_s134q005-90ee93.json",
    f"{LP}/reports/queue_s134q005-90ee93.md",
])
def test_a_new_non_driver_control_file_still_fails_the_guard(tmp_path, rel):
    _driver_tree(tmp_path)
    before = _guard().snapshot(tmp_path, _guard().WATCH, _ignore())
    _put(tmp_path, rel, "written by a test\n")
    msg = _verdict(tmp_path, before)
    assert msg.startswith("fleet_test_guard:"), rel
    assert rel in msg


@pytest.mark.parametrize("rel", [
    "moon_sync_inbox/2026-10-25-0100-MAIN-to-RC.txt",
    "moon_sync_outbox/2026-10-25-0101-RC-to-MAIN.txt",
    "ops/loop/control/lane_exclusions.txt",
    f"{LP}/s133-common.tmpl",
    f"{LP}/s133-queue.tmpl",
    f"{LP}/s133_lane_driver.py",
    f"{LP}/s133_lane_progress.py",
])
def test_a_change_to_a_non_driver_file_still_fails_the_guard(tmp_path, rel):
    _driver_tree(tmp_path)
    before = _guard().snapshot(tmp_path, _guard().WATCH, _ignore())
    _put(tmp_path, rel, "corrupted by a test - longer than before\n")
    msg = _verdict(tmp_path, before)
    assert msg.startswith("fleet_test_guard:"), rel
    assert f"changed 1 ({rel})" in msg


def test_a_new_outbox_note_still_fails_the_guard(tmp_path):
    _driver_tree(tmp_path)
    before = _guard().snapshot(tmp_path, _guard().WATCH, _ignore())
    rel = "moon_sync_outbox/2026-10-25-0200-RC-to-MAIN.txt"
    _put(tmp_path, rel, "a test wrote a note\n")
    assert f"created 1 ({rel})" in _verdict(tmp_path, before)


def test_the_driver_ignores_stay_inside_lane_prompts_and_off_the_templates():
    import fnmatch
    new = [gl for gl in cfg.EXTRA_IGNORE if gl.startswith(f"{LP}/")]
    assert new, "RM-874 adds its driver globs under lane_prompts/"
    for gl in new:
        tail = gl[len(LP) + 1:]
        # The one sanctioned subdirectory is the driver's own reports dir
        # (s<NNN>_reports/), and only its direct children.
        if tail.startswith(REPORTS_GLOB_DIR):
            tail = tail[len(REPORTS_GLOB_DIR):]
        assert "/" not in tail, f"{gl} reaches below lane_prompts/"
        for probe in ("s133-common.tmpl", "s133-gated.tmpl", "s133_lane_driver.py",
                      "s133_lane_progress.py", "queue-rm740e-s115.tmpl"):
            assert not fnmatch.fnmatchcase(f"{LP}/{probe}", gl), (gl, probe)

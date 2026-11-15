"""s165 C11: the fleet test guard must not fail a suite because the LIVE lane
driver's empty-cycle back-off (MAIN ORDER 2026-11-14 0930 O2, 5393cac6a8) wrote,
rewrote or removed its per-lane state file mid-run - and the ignore that covers
it must stay narrow.

Measured s165: a local test run ERRORED at the guard's session teardown on
ops/loop/control/lane_prompts/s144_ds_backoff.json and s144_gated_backoff.json.
Writer: the gitignored per-session driver s144_lane_driver.py names the path
`HERE / f"s144_{lane}_backoff.json"` (backoff_state_path) and passes it as
`state_path=` to ops/loop/lane_backoff.check(), which write_json()s it (atomic,
`.<pid>.<hex>.tmp` scratch, already in the kit IGNORE) on a skip and unlinks it
on resume. No test writes the live path (tests/test_lane_backoff.py uses
tmp_path). The module's other outputs - lanes/backoff.jsonl,
lanes/model_changes.jsonl, progress/s144-lanes.json - are in the kit IGNORE
already. RC adds the one family through tests/_fleet_guard_config.EXTRA_IGNORE
(kit v14: install(..., extra_ignore=...), never a restated IGNORE). ASCII only.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from tests import _fleet_guard_config as cfg

ROOT = Path(__file__).resolve().parents[1]
LP = "ops/loop/control/lane_prompts"
BACKOFF_GLOB = f"{LP}/s[0-9][0-9][0-9]_*_backoff.json"
LANES = ("ds", "gated", "queue", "repo", "research", "true-audit", "uiux")


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


def _hits(rel: str, globs) -> list:
    return [gl for gl in globs if fnmatch.fnmatchcase(rel.lower(), gl.lower())]


def _put(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("ascii"))


def _tree(root: Path) -> None:
    for lane in LANES:
        _put(root, f"{LP}/s144_{lane}_state.json", '{"status": "waiting"}\n')
        _put(root, f"{LP}/s144-{lane}.tmpl", "@@LANE@@\n")
    _put(root, f"{LP}/s144_ds_backoff.json", '{"fp": "a", "since": 1}\n')
    _put(root, f"{LP}/s144_lane_driver.py", "# driver\n")
    _put(root, "ops/loop/control/lane_exclusions_s144.txt", "CLAUDE.md\n")
    for p in root.rglob("*"):
        if p.is_file():
            os.utime(p, ns=(10**18, 10**18))


def _verdict(root: Path, before) -> str:
    g = _guard()
    return g.verdict(*g.compare(before, g.snapshot(root, g.WATCH, _ignore()), g.INFLOW))


def test_the_backoff_glob_rides_extra_ignore_not_the_kit():
    assert BACKOFF_GLOB in cfg.EXTRA_IGNORE
    assert BACKOFF_GLOB not in _guard().IGNORE


@pytest.mark.parametrize("lane", LANES)
def test_each_lane_backoff_state_file_is_ignored_by_rc(lane):
    rel = f"{LP}/s144_{lane}_backoff.json"
    assert _hits(rel, _ignore()), rel
    assert not _hits(rel, _guard().IGNORE), "the kit default should not be what covers it"


def test_a_backoff_skip_resume_and_new_lane_mid_session_do_not_fail_the_guard(tmp_path):
    g = _guard()
    _tree(tmp_path)
    raw = g.snapshot(tmp_path, g.WATCH, ())
    before = g.snapshot(tmp_path, g.WATCH, _ignore())
    # skip (rewrite), resume (unlink), first skip on another lane (create)
    _put(tmp_path, f"{LP}/s144_ds_backoff.json", '{"fp": "b", "since": 2, "count": 3}\n')
    (tmp_path / LP / "s144_ds_backoff.json").unlink()
    _put(tmp_path, f"{LP}/s144_gated_backoff.json", '{"fp": "c"}\n')
    _changed, deleted, created = g.compare(raw, g.snapshot(tmp_path, g.WATCH, ()), g.INFLOW)
    # Positive control: without the ignore these ARE live-state changes.
    assert f"{LP}/s144_ds_backoff.json" in deleted
    assert f"{LP}/s144_gated_backoff.json" in created
    assert _verdict(tmp_path, before) == ""


@pytest.mark.parametrize("rel", [
    f"{LP}/s144_lane_driver.py",
    f"{LP}/s144-ds.tmpl",
    "ops/loop/control/lane_exclusions_s144.txt",
])
def test_a_non_backoff_control_file_is_still_watched(tmp_path, rel):
    _tree(tmp_path)
    before = _guard().snapshot(tmp_path, _guard().WATCH, _ignore())
    _put(tmp_path, rel, "corrupted by a test - longer than before\n")
    assert f"changed 1 ({rel})" in _verdict(tmp_path, before)


@pytest.mark.parametrize("rel", [
    f"{LP}/s144_backoff.json",
    f"{LP}/s144_ds_backoff.json.bak",
    f"{LP}/backoff.json",
    f"{LP}/notes/s144_ds_backoff.json",
    "ops/loop/control/s144_ds_backoff.json",
    f"{LP}/s144_ds_backoff.md",
])
def test_a_near_miss_of_the_backoff_glob_still_fails_the_guard(tmp_path, rel):
    _tree(tmp_path)
    before = _guard().snapshot(tmp_path, _guard().WATCH, _ignore())
    _put(tmp_path, rel, "written by a test\n")
    msg = _verdict(tmp_path, before)
    assert msg.startswith("fleet_test_guard:"), rel
    assert rel in msg

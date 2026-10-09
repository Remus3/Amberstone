"""FLEET-KIT v14 (MAIN 2026-10-09 0930 ORDER; KIT-14 defects, state blocked,
identity history tiers): the tree-side half of the adoption.

The kit bytes are pinned by tests/test_fleet_kit_conformance.py (manifest +
FLEET-COMMON block + v14's marker-alone-on-its-line rule) and by
tests/test_lane_progress_v7.py (version + file set). This file pins what the
ORDER's section 3 asks RC to wire around them:
  * step 1: the vendored MANIFEST.json is the ORDER's section-1 bytes;
  * step 3: tests/conftest.py hands RC's tick files to the guard through
    install(..., extra_ignore=...) instead of restating the kit's IGNORE, and
    no RC extra glob is one the v14 IGNORE already covers;
  * step 4: RC tests acquire lanes through the kit (ops/loop/lanes.py ->
    fleet_lanes.try_acquire_lane -> worktree_path), so the suite pins
    FLEET_SIDECAR_ROOT to "" and never depends on the machine variable;
  * step 5: a kit refusal reaches RC callers with its machine code
    (ops/loop/fleet_route.RouteRefused.code), so nothing matches message text.
"""
from __future__ import annotations

import fnmatch
import hashlib
import importlib.util
import json
import os
from pathlib import Path

from tests import _fleet_guard_config as cfg

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"

# The ORDER's section-1 hash for MANIFEST.json (verified against MAIN's
# committed outbox copy at adoption, LEDGER).
V14_MANIFEST_SHA256 = "d045d4ba6f7f397fa6d14a934362ec6ddf2b2f4738c3b0dbfdf2c5ad19acbb78"


def _load(name):
    spec = importlib.util.spec_from_file_location(
        f"rc_v14_probe_{name}", KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(rel):
    return (ROOT / rel).read_bytes().decode("ascii").replace("\r\n", "\n")


# ---------------------------------------------------------------- step 1

def test_the_vendored_manifest_is_the_v14_order_bytes():
    raw = (KIT / "MANIFEST.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V14_MANIFEST_SHA256
    assert json.loads(raw.decode("ascii"))["version"] == 14


def test_conformance_checks_the_marker_lines():
    # v14 (SS 2239 c): a welded BEGIN line fails even when the block hash
    # passes, so the RC CLAUDE.md must carry each marker alone on its line.
    lines = _text("CLAUDE.md").split("\n")
    assert lines.count("<!-- FLEET-COMMON BEGIN -->") == 1
    assert lines.count("<!-- FLEET-COMMON END -->") == 1
    assert _load("fleet_headless").conformance(ROOT) == []


# ---------------------------------------------------------------- step 3

def test_conftest_passes_tick_files_as_extra_ignore():
    src = _text("tests/conftest.py")
    assert "extra_ignore=_fleet_guard_config.EXTRA_IGNORE" in src
    assert "fleet_test_guard.IGNORE +" not in src, "restates the kit IGNORE"


def test_no_extra_glob_is_already_covered_by_the_kit_ignore():
    guard = _load("fleet_test_guard")
    assert cfg.EXTRA_IGNORE, "an empty extra set would pass vacuously"
    for glob in cfg.EXTRA_IGNORE:
        probe = glob.replace("*", "x")
        covered = [g for g in guard.IGNORE
                   if fnmatch.fnmatchcase(probe.lower(), g.lower())]
        assert not covered, f"{glob} is already in the kit IGNORE via {covered}"


# ---------------------------------------------------------------- step 4

def test_the_suite_pins_the_sidecar_variable_off(tmp_path):
    pinned = os.environ.get("FLEET_SIDECAR_ROOT")
    assert pinned == ""
    lanes = _load("fleet_lanes")
    # A registry value that WOULD apply is ignored while the process env names
    # the variable (empty = off).
    machine = str(tmp_path / "sidecar")
    assert lanes.sidecar_root(registry=lambda: (True, machine)) is None
    assert lanes.sidecar_root(registry=lambda: (True, machine),
                              environ={}) == Path(machine)


def test_lane_worktree_path_ignores_the_machine_variable(tmp_path):
    lanes = _load("fleet_lanes")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    got = lanes.worktree_path(repo, "RC", 1)
    assert got == repo.resolve().parent / "rc-worktrees" / "lane-1"


# ---------------------------------------------------------------- step 5

def test_route_refusal_carries_the_kit_code():
    from ops.loop import fleet_route
    exc = fleet_route.RouteRefused("kit", "proxy unreachable: X",
                                   code="proxy-unreachable")
    assert exc.code == "proxy-unreachable"
    assert fleet_route.RouteRefused("no_url").code == "no_url"

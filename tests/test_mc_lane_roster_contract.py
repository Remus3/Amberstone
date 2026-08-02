# arch: contract - the MC panel roster cannot drift from the lock roster | section=tests | frozen=no
"""The Mission Control lane row must name exactly the lanes that exist.

Three rosters have to agree and they live in three different languages:

  ops/loop/lanes.py        LANES          - who may hold the mutex
  ops/loop/lane_launcher.py LANE_COMMANDS - who has a prompt to run
  web/mc/mc.js             _LANE_LABELS   - what the operator can see

test_lane_launcher.py already pins the first two against each other. Nothing
pinned the THIRD, and its failure mode is silent in the direction that matters:
`_mcPaintLanes` falls back to `Object.keys(_LANE_LABELS)` only when the server
sends no roster, and otherwise renders `_LANE_LABELS[lane] || lane`. So a lane
added to the lock and the launcher but not to the panel still renders - as its
bare id, unlabelled, beside six labelled siblings - and a lane REMOVED from the
lock keeps a label that can never appear. Neither breaks a test, and neither is
visible from the Python side at all.

Reads the contract off disk rather than restating it (memory
`feedback_contract_test_must_read_the_contract_from_disk`): a copy of the
expected roster inlined here would pass while both files were wrong together.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

lanes = importlib.import_module("ops.loop.lanes")
launcher = importlib.import_module("ops.loop.lane_launcher")

MC_JS = Path(__file__).resolve().parents[1] / "web" / "mc" / "mc.js"

# The declaration, then the quoted keys inside it. Deliberately anchored on the
# `const _LANE_LABELS = {` ... `}` block rather than scanning the whole file:
# every other quoted string in mc.js would otherwise read as a lane id.
_BLOCK = re.compile(r"const\s+_LANE_LABELS\s*=\s*\{(.*?)\n\};", re.S)
_KEY = re.compile(r'"([^"]+)"\s*:')


def _panel_labels() -> dict:
    src = MC_JS.read_text(encoding="utf-8")
    block = _BLOCK.search(src)
    assert block, "web/mc/mc.js no longer declares a _LANE_LABELS object literal"
    body = block.group(1)
    return {
        key: True
        for key in _KEY.findall(body)
    }


def test_the_panel_labels_exactly_the_lanes_that_exist():
    panel = set(_panel_labels())
    assert panel == set(lanes.LANES), (
        "web/mc/mc.js _LANE_LABELS and ops/loop/lanes.py LANES disagree: "
        f"panel-only={sorted(panel - set(lanes.LANES))} "
        f"lock-only={sorted(set(lanes.LANES) - panel)}")


def test_every_labelled_lane_is_startable():
    """A label with no command doc is a button that can only ever refuse."""
    assert set(_panel_labels()) == set(launcher.LANE_COMMANDS)


def test_the_gated_lane_is_present_in_all_three_rosters():
    """The live-game-gated drain lane (2026-08-02).

    Named explicitly, not left to the set-equality tests above: those stay
    green if the lane is deleted from all three at once, and this lane's whole
    reason to exist - draining docs/LIVE_GAME_GATED_SYNC.md against a REAL
    game - is the one thing no other lane can do.
    """
    assert "gated" in lanes.LANES
    assert "gated" in launcher.LANE_COMMANDS
    assert "gated" in _panel_labels()
    assert launcher.command_path("gated").is_file()

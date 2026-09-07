"""Cross-package parity for the kit damage-axis decisiveness gates.

``agents.daemon_slayer.hybrid._damage_axis`` and
``core.archetype_picks._axis_from_distribution`` both classify a champion's
damage axis from ``lolmath.damage_distribution``, and they MUST agree - a
champion the archetype resolver calls AP-axis while the bruiser scorer scores
on auto-attacks is the exact defect the kit-axis fix removed.

They cannot share code. The daemon_slayer package is self-contained by design -
no module in it imports ``core`` - so ``hybrid.py`` keeps LOCAL literals (the
same reason ``_burst_off_axis.py`` does). This file is the seam that stops the
two copies drifting, and it lives in ``tests/`` rather than
``agents/daemon_slayer/tests/`` because it holds BOTH sides at once: it imports
``core.archetype_picks`` alongside the engine module it is checked against.

Parity is asserted three ways so a single sloppy edit cannot pass:
  1. the LITERAL constants match,
  2. the two resolvers return the same verdict for every champion in the live
     snapshot whose split is decisive,
  3. the boundary cases (exactly at each gate, and just under) agree.
"""

from __future__ import annotations

import pytest

from agents.daemon_slayer import hybrid
from agents.daemon_slayer.data_loader import DataSnapshot
from core import archetype_picks as ap


def test_threshold_literals_match():
    assert hybrid._AXIS_DOMINANT_MIN == ap._AXIS_DOMINANT_MIN
    assert hybrid._AXIS_MARGIN_MIN == ap._AXIS_MARGIN_MIN


@pytest.mark.parametrize(
    "dist",
    [
        {"magical": 0.55, "physical": 0.35},      # exactly on both gates -> ap
        {"magical": 0.35, "physical": 0.55},      # exactly on both gates -> ad
        {"magical": 0.549, "physical": 0.10},     # under the dominance gate
        {"magical": 0.60, "physical": 0.41},      # under the margin gate
        {"magical": 0.94, "physical": 0.03},      # comfortably decisive
        {"magical": 0.115, "physical": 0.698},    # Belveth
        {"magical": 0.612, "physical": 0.162},    # Chogath
        {"magical": 0.5795, "physical": 0.3152},  # KogMaw - narrowest pass
        {"magical": 0.521, "physical": 0.347},    # Shaco - the canonical hybrid
        {},
        {"magical": "x", "physical": 0.9},
    ],
)
def test_resolvers_agree_on_boundary_shapes(dist):
    assert hybrid._kit_axis_from_distribution({"lolmath": {
        "damage_distribution": dist}}) == ap._axis_from_distribution(dist)


def test_resolvers_agree_across_the_live_roster():
    snap = DataSnapshot.load()
    checked = 0
    for cid, rec in snap.champions.items():
        if not isinstance(rec, dict):
            continue
        dist = (rec.get("lolmath") or {}).get("damage_distribution") or {}
        theirs = ap._axis_from_distribution(dist)
        mine = hybrid._kit_axis_from_distribution(rec)
        assert mine == theirs, cid
        checked += 1
    # Tripwire - a snapshot that failed to load would make the loop vacuous.
    assert checked >= 150, f"only {checked} champion records inspected"


def test_decisive_axis_drives_the_public_chokepoint():
    """Where the kit is decisive, ``_damage_axis`` returns exactly that."""
    snap = DataSnapshot.load()
    decisive = 0
    for cid, rec in snap.champions.items():
        if not isinstance(rec, dict):
            continue
        dist = (rec.get("lolmath") or {}).get("damage_distribution") or {}
        theirs = ap._axis_from_distribution(dist)
        if theirs is None:
            continue
        assert hybrid._damage_axis(snap, cid) == theirs, cid
        decisive += 1
    assert decisive >= 150, f"only {decisive} decisive champions found"

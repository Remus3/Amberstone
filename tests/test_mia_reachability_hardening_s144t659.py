# arch: S144-T-659 hardening tests for core/mia_reachability | section=tests
"""S144-T-659 (s144 true-audit) - core.mia_reachability never invents an
origin and never publishes the tracker's placeholder as a champion name.

Ground truth (grep-confirmed before writing):
  - core/vision_tracker.py ``_compute_enemies``: a Live Client
    ``position: "NONE"`` becomes ``x = z = 0.0``; the first-sighting branch
    treats (0, 0) as "no position", but the moved branch accepts it, so a
    previously seen, alive enemy can carry ``last_seen_pos`` {0, 0}.
  - core/vision_tracker.py ``_compute_enemies``: ``champ = championName or
    "?"`` - "?" is the tracker's unknown-champion placeholder.
  - web/js/panels/minimap_zoi.js ``_normMiaRing``: drops a ring whose cx /
    cy is off the [0, 1] box - a server-side clamp onto the edge defeats it.
"""
from __future__ import annotations

import pytest

from core import mia_reachability as mia
from core.mia_reachability import compute_mia

EXTENT = 14800.0


def _track(**kw):
    base = {
        "champion": "Ahri",
        "team": "CHAOS",
        "level": 10,
        "is_dead": False,
        "respawn_in_s": None,
        "visible": False,
        "missing_for_s": 10.0,
        "last_seen_pos": {"x": 7400.0, "z": 3700.0},
        "last_seen_t": 300.0,
        "last_seen_zone": "bot_river",
    }
    base.update(kw)
    return base


def _rings(*tracks, minimap_rect=None):
    out = compute_mia(list(tracks), "sr", 400.0, minimap_rect=minimap_rect)
    assert out is not None
    return out["rings"]


# -- F1: a far out-of-map origin is garbage, not an edge ring --------------


@pytest.mark.parametrize(
    "pos",
    [
        {"x": -90000.0, "z": 3700.0},
        {"x": 7400.0, "z": 1.0e9},
        {"x": EXTENT * 3, "z": EXTENT * 3},
        {"x": -5000.0, "z": -5000.0},
    ],
)
def test_far_out_of_map_origin_gets_no_ring(pos):
    assert _rings(_track(last_seen_pos=pos)) == []


@pytest.mark.parametrize("flip", [False, True])
def test_far_out_of_map_origin_gets_no_ring_flipped(flip):
    rings = _rings(
        _track(last_seen_pos={"x": -90000.0, "z": 3700.0}),
        minimap_rect={"flip": flip},
    )
    assert rings == []


def test_slightly_past_extent_still_clamps_inside_box():
    # Real SR coordinates run a little past the nominal 14800 extent near
    # the red fountain; those stay valid and clamp onto the box.
    rings = _rings(_track(last_seen_pos={"x": EXTENT + 100.0, "z": -100.0}))
    assert len(rings) == 1
    assert rings[0]["cx"] == 1.0
    assert rings[0]["cy"] == 1.0


def test_margin_boundary_is_inclusive_and_one_past_is_refused():
    edge = EXTENT + mia._POS_MARGIN
    assert len(_rings(_track(last_seen_pos={"x": edge, "z": 100.0}))) == 1
    assert len(_rings(_track(last_seen_pos={"x": -mia._POS_MARGIN, "z": 100.0}))) == 1
    assert _rings(_track(last_seen_pos={"x": edge + 1.0, "z": 100.0})) == []
    assert _rings(_track(last_seen_pos={"x": 100.0, "z": -mia._POS_MARGIN - 1.0})) == []


# -- F2: the tracker's (0, 0) "no position" sentinel is never an origin -----


def test_zero_zero_sentinel_gets_no_ring():
    assert _rings(_track(last_seen_pos={"x": 0.0, "z": 0.0})) == []
    assert _rings(_track(last_seen_pos={"x": 0, "z": 0})) == []


def test_one_zero_axis_is_a_real_position():
    rings = _rings(_track(last_seen_pos={"x": 0.0, "z": 3700.0}))
    assert len(rings) == 1
    assert rings[0]["cx"] == 0.0


def test_sentinel_row_does_not_suppress_good_rows():
    rings = _rings(
        _track(champion="Ahri", last_seen_pos={"x": 0.0, "z": 0.0}),
        _track(champion="Zed", last_seen_pos={"x": 7400.0, "z": 7400.0}),
    )
    assert [r["champion"] for r in rings] == ["Zed"]


# -- F3: the "?" placeholder and padded names are normalised ---------------


@pytest.mark.parametrize("raw", ["?", " ? ", "  "])
def test_placeholder_champion_becomes_none(raw):
    rings = _rings(_track(champion=raw))
    assert len(rings) == 1
    assert rings[0]["champion"] is None


def test_padded_champion_name_is_stripped():
    rings = _rings(_track(champion="  Ahri  "))
    assert rings[0]["champion"] == "Ahri"


def test_placeholder_ring_uses_fallback_speed_same_as_none():
    a = _rings(_track(champion="?"))[0]
    b = _rings(_track(champion=None))[0]
    assert a["r_frac"] == b["r_frac"]

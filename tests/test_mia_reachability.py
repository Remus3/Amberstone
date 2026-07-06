# arch: tests for core/mia_reachability (ZOI Wave 3, spec E-2) | section=tests
"""Tests for core.mia_reachability - the SOLE zoi.mia producer.

Written FIRST (TDD). Ground-truth surfaces grep-confirmed before
scaffolding:
  - enemy track row shape: core/vision_tracker.py:376-388
  - SR map extent ~14800, origin at Blue base corner: core/vision_tracker.py:55-61
  - box-fraction frame is y-down with blue base bottom-LEFT:
    config/minimap_grids/sr.json:4 (blue_base poly y in [0.82, 1.0])
    -> cx = x/extent, cy = 1 - z/extent (z axis INVERTED to minimap y)
  - est_ms / distance_frac_per_s: core/champion_movespeed.py:229-261
  - missing floor precedent: core/laning_cv_overrides.py:50 (3.0s)
  - minimap_rect payload carries "flip": core/league_settings.py:137-146
"""
from __future__ import annotations

import math

import pytest

from core import mia_reachability as mia
from core.mia_reachability import compute_mia

EXTENT = 14800.0


def _track(**kw):
    """One vision_tracker enemy row (core/vision_tracker.py:376-388)."""
    base = {
        "champion": "Ahri",
        "summoner_name": "enemy1",
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


# -- ring math -----------------------------------------------------------


def test_origin_mapping_center_bot_half():
    # x=7400 (mid), z=3700 (bot quarter) -> cx=0.5, cy=1-0.25=0.75 (y-down).
    out = compute_mia({"Ahri": _track()}, "sr", 310.0)
    assert out is not None and out["count"] == 1
    ring = out["rings"][0]
    assert ring["cx"] == pytest.approx(0.5, abs=0.01)
    assert ring["cy"] == pytest.approx(0.75, abs=0.01)


def test_axis_inversion_blue_base_maps_bottom_left():
    # Blue base = LOW x, LOW z in map units (vision_tracker.py:60-61) but
    # bottom-LEFT of the minimap crop (sr.json:4) -> small cx, LARGE cy.
    t = _track(last_seen_pos={"x": 1000.0, "z": 1000.0})
    out = compute_mia({"Ahri": t}, "sr", 310.0)
    ring = out["rings"][0]
    assert ring["cx"] < 0.2
    assert ring["cy"] > 0.8


def test_radius_growth_monotonic_with_missing_time():
    short = compute_mia({"A": _track(missing_for_s=5.0)}, "sr", 310.0)
    long = compute_mia({"A": _track(missing_for_s=20.0)}, "sr", 310.0)
    assert long["rings"][0]["r_frac"] > short["rings"][0]["r_frac"]


def test_radius_min_clamp(monkeypatch):
    monkeypatch.setattr(mia, "distance_frac_per_s", lambda ms: 0.0001)
    out = compute_mia({"A": _track(missing_for_s=4.0)}, "sr", 310.0)
    assert out["rings"][0]["r_frac"] == pytest.approx(mia.R_MIN_FRAC)


def test_radius_max_clamp():
    out = compute_mia({"A": _track(missing_for_s=600.0)}, "sr", 910.0)
    assert out["rings"][0]["r_frac"] == pytest.approx(mia.R_MAX_FRAC)


def test_confidence_decays_with_missing_time():
    fresh = compute_mia({"A": _track(missing_for_s=5.0)}, "sr", 310.0)
    stale = compute_mia({"A": _track(missing_for_s=120.0)}, "sr", 430.0)
    c_fresh = fresh["rings"][0]["confidence"]
    c_stale = stale["rings"][0]["confidence"]
    assert 0.0 < c_stale < c_fresh <= 1.0
    assert c_stale >= mia.CONF_MIN


# -- exclusions ----------------------------------------------------------


def test_dead_enemy_no_ring():
    # Respawn is API truth (respawnTimer) - dead champs get NO ring.
    t = _track(is_dead=True, respawn_in_s=25.0)
    out = compute_mia({"Ahri": t}, "sr", 310.0)
    assert out == {"rings": [], "count": 0}


def test_visible_enemy_no_ring():
    out = compute_mia({"Ahri": _track(visible=True, missing_for_s=None)}, "sr", 310.0)
    assert out == {"rings": [], "count": 0}


def test_no_last_seen_pos_no_ring_never_guess():
    out = compute_mia({"Ahri": _track(last_seen_pos=None)}, "sr", 310.0)
    assert out == {"rings": [], "count": 0}


def test_floor_threshold():
    # Ring requires missing_for_s STRICTLY above MIN_MISSING_S (3.0s).
    at = compute_mia({"A": _track(missing_for_s=3.0)}, "sr", 303.0)
    below = compute_mia({"A": _track(missing_for_s=2.0)}, "sr", 302.0)
    above = compute_mia({"A": _track(missing_for_s=3.5)}, "sr", 303.5)
    assert at["count"] == 0
    assert below["count"] == 0
    assert above["count"] == 1


# -- mode gate (fail-CLOSED, SR only) --------------------------------------


@pytest.mark.parametrize("mode", ["sr", "SR", "CLASSIC", "classic"])
def test_mode_gate_sr_forms_accepted(mode):
    out = compute_mia({"Ahri": _track()}, mode, 310.0)
    assert out is not None and out["count"] == 1


@pytest.mark.parametrize(
    "mode",
    ["aram", "ARAM", "KIWI", "arena", "ARENA", "CHERRY", "brawl", "tft",
     "client", "", None, 42, "garbage"],
)
def test_mode_gate_non_sr_none(mode):
    assert compute_mia({"Ahri": _track()}, mode, 310.0) is None


# -- count + input shapes --------------------------------------------------


def test_count_matches_qualifying_rings():
    tracks = {
        "Ahri": _track(champion="Ahri"),
        "Zed": _track(champion="Zed", last_seen_pos={"x": 3000.0, "z": 9000.0}),
        "Sion": _track(champion="Sion", is_dead=True),
        "Jinx": _track(champion="Jinx", visible=True, missing_for_s=None),
    }
    out = compute_mia(tracks, "sr", 310.0)
    assert out["count"] == 2
    assert len(out["rings"]) == 2


def test_accepts_list_of_rows():
    out = compute_mia([_track(), _track(champion="Zed")], "sr", 310.0)
    assert out["count"] == 2


def test_missing_for_s_derived_from_last_seen_t():
    # missing_for_s absent -> derived from game_time_s - last_seen_t.
    t = _track(missing_for_s=None, last_seen_t=100.0)
    out = compute_mia({"Ahri": t}, "sr", 110.0)
    assert out["count"] == 1
    assert out["rings"][0]["missing_for_s"] == pytest.approx(10.0)


def test_flip_mirrors_x_only():
    plain = compute_mia({"A": _track()}, "sr", 310.0)
    flipped = compute_mia({"A": _track()}, "sr", 310.0, minimap_rect={"flip": True})
    p, f = plain["rings"][0], flipped["rings"][0]
    assert f["cx"] == pytest.approx(1.0 - p["cx"], abs=1e-6)
    assert f["cy"] == pytest.approx(p["cy"], abs=1e-6)


# -- fail-soft -------------------------------------------------------------


def test_garbage_tracks_container_returns_none():
    assert compute_mia(None, "sr", 310.0) is None
    assert compute_mia("garbage", "sr", 310.0) is None
    assert compute_mia(42, "sr", 310.0) is None


def test_garbage_rows_skipped_never_raise():
    tracks = {
        "a": "not-a-dict",
        "b": None,
        "c": _track(last_seen_pos={"x": float("nan"), "z": 100.0}),
        "d": _track(last_seen_pos={"x": "bogus"}),
        "e": _track(missing_for_s=float("nan")),
        "f": _track(missing_for_s="soon"),
        "g": _track(champion=None),  # champion None passes through OK
    }
    out = compute_mia(tracks, "sr", 310.0)
    assert out["count"] == 1
    assert out["rings"][0]["champion"] is None


def test_never_raises_on_pathological_inputs():
    compute_mia({"A": _track()}, "sr", float("nan"))
    compute_mia({"A": _track()}, "sr", None, minimap_rect="junk")
    compute_mia({"A": _track(visible=0)}, "sr", 310.0)
    compute_mia([], "sr", 310.0)


def test_contract_key_shape_stability():
    out = compute_mia({"Ahri": _track()}, "sr", 310.0)
    assert set(out.keys()) == {"rings", "count"}
    ring = out["rings"][0]
    assert set(ring.keys()) == {
        "champion", "cx", "cy", "r_frac", "missing_for_s", "confidence",
    }
    assert isinstance(ring["champion"], str)
    for k in ("cx", "cy", "r_frac", "missing_for_s", "confidence"):
        assert isinstance(ring[k], float) and math.isfinite(ring[k])
    assert 0.0 <= ring["cx"] <= 1.0
    assert 0.0 <= ring["cy"] <= 1.0
    assert mia.R_MIN_FRAC <= ring["r_frac"] <= mia.R_MAX_FRAC
    assert 0.0 < ring["confidence"] <= 1.0
    assert isinstance(out["count"], int)

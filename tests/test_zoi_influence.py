"""Tests for core.zoi_influence - pure Zone-of-Influence shading from per-team
minimap dots (item 567 slice 3). Synthetic fixtures only (deterministic, no
live frame), mirrors tests/test_minimap_blob_detect.py so they run on a clean
checkout / CI."""
import math

import pytest

from core.zoi_influence import (
    _R_MAX_FRAC,
    _R_MIN_FRAC,
    compute_zoi,
    zoi_callout,
)

_QUADRANTS = {
    "top_left", "top_right", "bot_left", "bot_right", "mid",
    "top_river", "bot_river", "ally_base", "enemy_base",
}


def _dot(team, x, y, px=40, conf=0.8):
    return {"team": team, "x_frac": x, "y_frac": y, "px": px, "confidence": conf}


# --- entry guards ---------------------------------------------------------

def test_empty_dots_none():
    assert compute_zoi([], my_level=11, game_time_s=600) is None


def test_none_dots_none():
    assert compute_zoi(None, my_level=11, game_time_s=600) is None


# --- single-team -> no demarcation, 100% control --------------------------

def test_all_one_team_no_demarcation_full_control():
    dots = [_dot("blue", 0.2, 0.8), _dot("blue", 0.3, 0.7)]
    z = compute_zoi(dots, my_level=6, game_time_s=600)
    assert z is not None
    assert set(z.keys()) == {"bubbles", "demarcation", "map_control"}
    assert z["demarcation"] is None
    assert z["map_control"]["ally_control_pct"] == 100
    assert len(z["bubbles"]) == 2
    for b in z["bubbles"]:
        for k in ("cx", "cy", "r_frac", "weight"):
            assert math.isfinite(b[k])
        assert b["team"] == "blue"


def test_all_enemy_team_zero_ally_control():
    dots = [_dot("red", 0.7, 0.2), _dot("red", 0.8, 0.3)]
    z = compute_zoi(dots, my_level=6, game_time_s=600)
    assert z["demarcation"] is None
    assert z["map_control"]["ally_control_pct"] == 0


# --- two-team symmetric -> 50/50 + finite demarcation ---------------------

def test_two_team_symmetric_50_50_and_finite_demarcation():
    # mirror-image weights so the split is exactly 50/50
    dots = [_dot("blue", 0.2, 0.8), _dot("red", 0.8, 0.2)]
    z = compute_zoi(dots, my_level=11, game_time_s=600)
    assert z["map_control"]["ally_control_pct"] == 50
    dem = z["demarcation"]
    assert dem is not None
    for k in ("x1", "y1", "x2", "y2"):
        assert math.isfinite(dem[k])
        assert 0.0 <= dem[k] <= 1.0
    assert dem["ally_side"] in ("left", "right", "top", "bottom")


def test_demarcation_endpoints_on_box_edge():
    dots = [_dot("blue", 0.25, 0.75), _dot("red", 0.75, 0.25)]
    dem = compute_zoi(dots, my_level=11, game_time_s=600)["demarcation"]
    assert dem is not None

    def _on_edge(x, y):
        eps = 1e-6
        on_x = abs(x) < eps or abs(x - 1.0) < eps
        on_y = abs(y) < eps or abs(y - 1.0) < eps
        return on_x or on_y

    assert _on_edge(dem["x1"], dem["y1"])
    assert _on_edge(dem["x2"], dem["y2"])


# --- weighted skew -> pct>50 + split fraction along Ca->Ce ----------------

def test_weighted_skew_control_above_50_and_split_fraction():
    # ally has far more presence -> control > 50, demarcation pushed toward enemy
    ally = [_dot("blue", 0.2, 0.8, px=80, conf=1.0),
            _dot("blue", 0.25, 0.78, px=80, conf=1.0)]
    enemy = [_dot("red", 0.8, 0.2, px=20, conf=0.5)]
    z = compute_zoi(ally + enemy, my_level=11, game_time_s=600)
    pct = z["map_control"]["ally_control_pct"]
    assert pct > 50

    # the demarcation point P = Ca + (Ce-Ca)*(Wa/(Wa+We)); verify the split
    # fraction lands proportional to the weights along the Ca->Ce segment.
    wa = sum(d["px"] * d["confidence"] for d in ally)
    we = sum(d["px"] * d["confidence"] for d in enemy)
    expected_frac = wa / (wa + we)
    ca = (sum(d["px"] * d["confidence"] * d["x_frac"] for d in ally) / wa,
          sum(d["px"] * d["confidence"] * d["y_frac"] for d in ally) / wa)
    ce = (enemy[0]["x_frac"], enemy[0]["y_frac"])
    # midpoint of the clipped line should be ~ P
    dem = z["demarcation"]
    pmx = (dem["x1"] + dem["x2"]) / 2.0
    pmy = (dem["y1"] + dem["y2"]) / 2.0
    px_expected = ca[0] + (ce[0] - ca[0]) * expected_frac
    py_expected = ca[1] + (ce[1] - ca[1]) * expected_frac
    assert abs(pmx - px_expected) < 0.06
    assert abs(pmy - py_expected) < 0.06


# --- ally spike levels bump radius ----------------------------------------

def test_ally_spike_grows_radius_at_each_threshold():
    dots = [_dot("blue", 0.5, 0.5)]
    r5 = compute_zoi(dots, my_level=5, game_time_s=600)["bubbles"][0]["r_frac"]
    r6 = compute_zoi(dots, my_level=6, game_time_s=600)["bubbles"][0]["r_frac"]
    r11 = compute_zoi(dots, my_level=11, game_time_s=600)["bubbles"][0]["r_frac"]
    r16 = compute_zoi(dots, my_level=16, game_time_s=600)["bubbles"][0]["r_frac"]
    assert r6 > r5
    assert r11 > r6
    assert r16 > r11


# --- enemy radius grows with game_time ------------------------------------

def test_enemy_radius_grows_with_game_time():
    dots = [_dot("red", 0.5, 0.5)]
    r_early = compute_zoi(dots, my_level=1, game_time_s=60)["bubbles"][0]["r_frac"]
    r_late = compute_zoi(dots, my_level=1, game_time_s=1100)["bubbles"][0]["r_frac"]
    assert r_late > r_early


# --- radius clamp at extremes ---------------------------------------------

def test_radius_clamped_to_bounds():
    # huge presence + max spikes + late game -> still clamped to max
    big = compute_zoi(
        [_dot("blue", 0.5, 0.5, px=9999, conf=1.0)],
        my_level=18, game_time_s=99999,
    )["bubbles"][0]["r_frac"]
    # r_frac is rounded to 5 places, so allow a rounding epsilon over the cap
    assert big <= _R_MAX_FRAC + 1e-5
    assert big >= _R_MIN_FRAC - 1e-5
    # tiny presence -> floor
    small = compute_zoi(
        [_dot("red", 0.5, 0.5, px=1, conf=0.01)],
        my_level=1, game_time_s=0,
    )["bubbles"][0]["r_frac"]
    assert small >= _R_MIN_FRAC - 1e-5
    assert abs(small - _R_MIN_FRAC) < 1e-5


# --- action_quadrant always in the 9-set ----------------------------------

def test_action_quadrant_always_valid():
    samples = [
        (0.1, 0.1), (0.9, 0.1), (0.1, 0.9), (0.9, 0.9),
        (0.5, 0.5), (0.5, 0.1), (0.5, 0.9), (0.1, 0.5), (0.9, 0.5),
        (0.0, 0.0), (1.0, 1.0), (0.3, 0.7), (0.7, 0.3),
    ]
    for x, y in samples:
        z = compute_zoi([_dot("blue", x, y)], my_level=6, game_time_s=600)
        assert z["map_control"]["action_quadrant"] in _QUADRANTS


# --- zero-dot-team NaN safety ---------------------------------------------

def test_zero_dot_team_all_finite():
    z = compute_zoi([_dot("blue", 0.5, 0.5)], my_level=6, game_time_s=600)
    mc = z["map_control"]
    assert math.isfinite(mc["ally_control_pct"])
    assert 0 <= mc["ally_control_pct"] <= 100
    for b in z["bubbles"]:
        for k in ("cx", "cy", "r_frac", "weight"):
            assert math.isfinite(b[k])


# --- malformed dots skipped, never raises ---------------------------------

def test_malformed_dots_skipped_no_raise():
    dots = [
        _dot("blue", 0.3, 0.7),
        {"team": "blue"},                      # missing fracs
        {"team": "red", "x_frac": "nope", "y_frac": 0.5, "px": 10, "confidence": 0.5},
        {"team": "green", "x_frac": 0.5, "y_frac": 0.5, "px": 10, "confidence": 0.5},
        {"x_frac": 0.5, "y_frac": 0.5, "px": 10, "confidence": 0.5},  # no team
        None,
        "garbage",
    ]
    z = compute_zoi(dots, my_level=6, game_time_s=600)
    assert z is not None
    # only the one good blue dot survives
    assert len(z["bubbles"]) == 1
    assert z["bubbles"][0]["team"] == "blue"


def test_all_malformed_dots_none():
    dots = [{"team": "green"}, None, "x", {"x_frac": "a"}]
    assert compute_zoi(dots, my_level=6, game_time_s=600) is None


# --- control_pct bounds + my_level None safe ------------------------------

def test_control_pct_in_range_and_none_level():
    z = compute_zoi(
        [_dot("blue", 0.2, 0.8), _dot("red", 0.8, 0.2)],
        my_level=None, game_time_s=None,
    )
    assert 0 <= z["map_control"]["ally_control_pct"] <= 100
    for b in z["bubbles"]:
        assert math.isfinite(b["r_frac"])


# --- line is ASCII + bounded ----------------------------------------------

def test_line_is_ascii_and_bounded():
    z = compute_zoi([_dot("blue", 0.5, 0.5)], my_level=16, game_time_s=600)
    line = z["map_control"]["line"]
    assert isinstance(line, str)
    assert len(line) <= 120
    # ord<128 already excludes em-dash (U+2014) / en-dash (U+2013) - the repo
    # hard rule - plus smart quotes; an explicit dash literal here would itself
    # break the ASCII-only source rule, so the byte-range check stands in.
    assert all(ord(c) < 128 for c in line)
    assert max((ord(c) for c in line), default=0) < 128


# --- callout shape --------------------------------------------------------

def test_zoi_callout_shape():
    z = compute_zoi([_dot("blue", 0.5, 0.5)], my_level=6, game_time_s=600)
    co = zoi_callout(z)
    assert set(co.keys()) == {"tag", "line", "eta_s", "kind"}
    assert co["tag"] == "map_control"
    assert co["kind"] == "map_control"
    assert co["eta_s"] is None
    assert co["line"] == z["map_control"]["line"]
    assert all(ord(c) < 128 for c in co["line"])


def test_zoi_callout_none_passthrough():
    assert zoi_callout(None) is None

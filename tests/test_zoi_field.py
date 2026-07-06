"""Tests for core.zoi_field - fluid DMZ frontier from signed influence bubbles
(ZOI district orchestration, spec F, wave 3b).

field_dmz(bubbles) samples a coarse grid of summed SIGNED influence (ally +weight,
enemy -weight) and extracts the zero-crossing frontier as an ordered polyline path
plus a band width. Degenerate (one team absent, <2 crossings, all-zero) -> None.

Contract (zoi.dmz): {"path": [[x,y],...] (>=2 pts, box-fraction [0,1]),
"band_w_frac": float} or None.

Bubble dict shape grep-confirmed core/zoi_influence.py:290-296 -> the SIGNED
source for the field is {team, cx, cy, r_frac, weight}; this module signs it
(ally +weight, enemy -weight). Pure, fail-soft, never raises.
"""
import math

import pytest

from core.zoi_field import field_dmz


def _bub(team, cx, cy, w=1.0, r=0.15):
    return {"team": team, "cx": cx, "cy": cy, "r_frac": r, "weight": w}


# --- degenerate -> None ---------------------------------------------------

def test_none_bubbles_none():
    assert field_dmz(None) is None


def test_empty_bubbles_none():
    assert field_dmz([]) is None


def test_single_team_ally_only_none():
    bubbles = [_bub("blue", 0.2, 0.8), _bub("blue", 0.3, 0.7)]
    assert field_dmz(bubbles) is None


def test_single_team_enemy_only_none():
    bubbles = [_bub("red", 0.7, 0.2), _bub("red", 0.8, 0.3)]
    assert field_dmz(bubbles) is None


def test_all_zero_weight_none():
    bubbles = [_bub("blue", 0.2, 0.8, w=0.0), _bub("red", 0.8, 0.2, w=0.0)]
    assert field_dmz(bubbles) is None


def test_garbage_bubbles_no_raise_none():
    # malformed entries must be skipped, not crash; all-malformed -> None
    bubbles = [None, 42, {"team": "green", "cx": 0.5}, {"cx": "x", "cy": None}]
    assert field_dmz(bubbles) is None


# --- two-bubble (one ally one enemy) -> valid frontier --------------------

def test_two_bubble_frontier_valid():
    # ally bottom-left (+), enemy top-right (-). A zero-crossing frontier exists.
    bubbles = [_bub("blue", 0.2, 0.8, w=1.0), _bub("red", 0.8, 0.2, w=1.0)]
    dmz = field_dmz(bubbles)
    assert dmz is not None
    assert set(dmz.keys()) == {"path", "band_w_frac"}
    path = dmz["path"]
    assert isinstance(path, list)
    assert len(path) >= 2
    for pt in path:
        assert isinstance(pt, (list, tuple))
        assert len(pt) == 2
        x, y = pt
        assert math.isfinite(x) and math.isfinite(y)
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0
    assert isinstance(dmz["band_w_frac"], float)
    assert math.isfinite(dmz["band_w_frac"])
    assert dmz["band_w_frac"] >= 0.0


def test_frontier_separates_the_two_bubbles():
    # The zero-crossing should sit between the ally and enemy centroids: the
    # mean path point falls near the diagonal midline (x + y ~ 1).
    bubbles = [_bub("blue", 0.2, 0.8, w=1.0), _bub("red", 0.8, 0.2, w=1.0)]
    dmz = field_dmz(bubbles)
    assert dmz is not None
    path = dmz["path"]
    mx = sum(p[0] for p in path) / len(path)
    my = sum(p[1] for p in path) / len(path)
    # symmetric fixture -> frontier centered on the anti-diagonal
    assert abs((mx + my) - 1.0) < 0.35


def test_path_is_ordered_monotone_ish():
    # An ordered polyline: consecutive points advance along one sweep axis
    # (no random scatter). We assert the path coordinate along the dominant
    # sweep axis is monotone non-decreasing.
    bubbles = [_bub("blue", 0.2, 0.8, w=1.0), _bub("red", 0.8, 0.2, w=1.0)]
    dmz = field_dmz(bubbles)
    assert dmz is not None
    path = dmz["path"]
    xs = [p[0] for p in path]
    ys = [p[1] for p in path]
    x_mono = all(xs[i] <= xs[i + 1] + 1e-9 for i in range(len(xs) - 1))
    y_mono = all(ys[i] <= ys[i + 1] + 1e-9 for i in range(len(ys) - 1))
    assert x_mono or y_mono


def test_weight_imbalance_shifts_frontier_toward_weaker():
    # Ally far stronger: the neutral boundary ALONG the ally->enemy axis is
    # pushed toward the enemy corner (the ally owns more of the contested line).
    # We measure the zero-crossing along the diagonal ally(0.2,0.8)->enemy(0.8,0.2)
    # directly - the robust, geometry-independent claim (a 2D contour's whole-
    # path centroid is NOT a monotone proxy for boundary position, so we probe
    # the axis).
    from core.zoi_field import _field_at, _valid_source

    def _axis_crossing(bubbles):
        srcs = [_valid_source(b) for b in bubbles]
        srcs = [s for s in srcs if s is not None]
        prev_f = None
        prev_field = None
        n = 101
        for k in range(n):
            frac = k / (n - 1)
            x = 0.2 + frac * 0.6
            y = 0.8 - frac * 0.6
            val = _field_at(x, y, srcs)
            if prev_field is not None and (val > 0.0) != (prev_field > 0.0):
                # linear interp of the crossing fraction
                t = prev_field / (prev_field - val) if (prev_field - val) else 0.5
                return prev_f + (frac - prev_f) * t
            prev_f = frac
            prev_field = val
        return None

    strong_ally = [_bub("blue", 0.2, 0.8, w=5.0), _bub("red", 0.8, 0.2, w=1.0)]
    even = [_bub("blue", 0.2, 0.8, w=1.0), _bub("red", 0.8, 0.2, w=1.0)]
    f_strong = _axis_crossing(strong_ally)
    f_even = _axis_crossing(even)
    assert f_strong is not None and f_even is not None
    # frac closer to 1.0 == closer to the enemy corner
    assert f_strong > f_even


def test_fail_soft_never_raises_on_wild_input():
    # NaN / inf coords + wild weights must not raise.
    bubbles = [
        _bub("blue", float("nan"), 0.8, w=1.0),
        _bub("red", 0.8, float("inf"), w=1.0),
        _bub("blue", 0.2, 0.8, w=1e12),
        _bub("red", 0.8, 0.2, w=-3.0),
    ]
    # must return either None or a valid payload, never raise
    out = field_dmz(bubbles)
    assert out is None or set(out.keys()) == {"path", "band_w_frac"}

"""Characterization tests for the settings-driven minimap geometry model.

The model maps (MinimapScale, FlipMiniMap, target_w, target_h) to an on-screen
minimap rectangle. It is calibration-anchored at the operator's live setup
(MinimapScale=1.62, FlipMiniMap=0), measured 2026-06-21 on a 16:9 vision frame:
minimap side = 0.2889 * screen_height, right margin = 0.0039 * width, bottom
margin = 0.0069 * height. These tests pin that anchor + the flip / clamp /
fallback behaviour. Pure math, no I/O.
"""
from __future__ import annotations

import math

import pytest

from core.minimap_geometry import (
    CAL_SCALE,
    MinimapRect,
    compute_minimap_rect,
)


def test_calibration_anchor_1920x1080():
    # At the calibrated scale on the design canvas, the box matches the
    # live-measured square (bottom-right anchored, ~312px) within a few px.
    r = compute_minimap_rect(CAL_SCALE, False, 1920, 1080)
    assert isinstance(r, MinimapRect)
    assert r.w == r.h  # square
    assert 300 <= r.w <= 320
    # bottom-right anchored: a small inset from each far edge
    assert 1920 - (r.x + r.w) <= 12
    assert 1080 - (r.y + r.h) <= 12
    assert r.flip is False


def test_calibration_anchor_resolution_independent():
    # The same scale on a 1280x720 frame yields the measured ~208px side
    # (16:9 preserved, so the fraction-of-height is identical).
    r = compute_minimap_rect(CAL_SCALE, False, 1280, 720)
    assert 200 <= r.w <= 216
    assert r.w == r.h


def test_flip_mirrors_x_only():
    right = compute_minimap_rect(CAL_SCALE, False, 1920, 1080)
    left = compute_minimap_rect(CAL_SCALE, True, 1920, 1080)
    assert left.flip is True
    # same square size + same vertical placement
    assert left.w == right.w and left.h == right.h
    assert left.y == right.y
    # x is mirrored about the screen: left.x ~= W - (right.x + right.w)
    assert abs(left.x - (1920 - (right.x + right.w))) <= 1
    # left-anchored sits on the left half, right-anchored on the right half
    assert left.x < 1920 // 2
    assert right.x > 1920 // 2


def test_scale_proportional_monotonic():
    small = compute_minimap_rect(1.0, False, 1920, 1080)
    big = compute_minimap_rect(2.0, False, 1920, 1080)
    assert big.w > small.w  # larger scale -> larger minimap


def test_scale_clamped_high_and_low():
    huge = compute_minimap_rect(99.0, False, 1920, 1080)
    tiny = compute_minimap_rect(-5.0, False, 1920, 1080)
    # side stays within sane fraction-of-height bounds [0.15, 0.45]
    for r in (huge, tiny):
        assert r is not None
        assert 0.15 * 1080 - 1 <= r.h <= 0.45 * 1080 + 1


def test_non_finite_scale_falls_back_to_calibration():
    nan = compute_minimap_rect(math.nan, False, 1920, 1080)
    inf = compute_minimap_rect(math.inf, False, 1920, 1080)
    cal = compute_minimap_rect(CAL_SCALE, False, 1920, 1080)
    assert nan.w == cal.w
    assert inf.w == cal.w


def test_non_numeric_scale_falls_back():
    r = compute_minimap_rect("not-a-number", False, 1920, 1080)
    cal = compute_minimap_rect(CAL_SCALE, False, 1920, 1080)
    assert r.w == cal.w


def test_rect_always_within_screen():
    for scale in (0.5, 1.0, 1.62, 2.0, 3.0):
        for flip in (False, True):
            r = compute_minimap_rect(scale, flip, 1920, 1080)
            assert r is not None
            assert 0 <= r.x and 0 <= r.y
            assert r.x + r.w <= 1920
            assert r.y + r.h <= 1080


def test_bbox_form_agrees_with_xywh():
    r = compute_minimap_rect(CAL_SCALE, False, 1920, 1080)
    l, t, rr, b = r.as_bbox()
    assert (l, t) == (r.x, r.y)
    assert rr - l == r.w
    assert b - t == r.h


def test_bad_target_dims_return_none():
    assert compute_minimap_rect(CAL_SCALE, False, 0, 1080) is None
    assert compute_minimap_rect(CAL_SCALE, False, 1920, 0) is None
    assert compute_minimap_rect(CAL_SCALE, False, -1, -1) is None


def test_affine_intercept_minimap_has_a_floor():
    # The minimap has a real MINIMUM size, not zero: MinimapScale 0.0 renders a
    # ~238px square at 2560x1440 (live-measured 2026-07-05), neither a collapse to
    # 0 (old proportional-through-origin) nor the old <=0 -> CAL_SCALE snap to 416.
    r = compute_minimap_rect(0.0, False, 2560, 1440)
    assert r is not None
    assert 225 <= r.w <= 252


def test_affine_matches_measured_points_2560x1440():
    # Live-measured (2026-07-05, operator setup, 2560x1440) minimap side vs the
    # game.cfg MinimapScale float. The relationship is affine (slope*scale +
    # floor), not proportional through the origin.
    assert 328 <= compute_minimap_rect(0.93, False, 2560, 1440).w <= 354  # ~340
    assert 408 <= compute_minimap_rect(1.62, False, 2560, 1440).w <= 424  # 416 anchor
    assert 520 <= compute_minimap_rect(2.70, False, 2560, 1440).w <= 550  # ~535


def test_low_scale_does_not_undershoot_regression():
    # Regression for the through-origin bug: the old model gave ~239px at scale
    # 0.93 (2560x1440) by heading toward 0 at scale 0; the real minimap is ~340px.
    assert compute_minimap_rect(0.93, False, 2560, 1440).w >= 320


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

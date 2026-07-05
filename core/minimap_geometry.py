"""Settings-driven minimap geometry - the Zone-of-Influence foundation.

Maps League's HUD minimap settings (MinimapScale, FlipMiniMap) to an on-screen
minimap rectangle in a target coordinate space. The League minimap is a square
anchored to the bottom-RIGHT corner of the render (bottom-LEFT when FlipMiniMap
is set), inset by a small margin, whose side grows with MinimapScale.

This module is PURE math (no I/O) so it is trivially unit-testable. The reader +
compose lives in core/league_settings. The overlay consumes the emitted rect in
1920x1080 design pixels (the overlay body-zoom reconciles design px to the live
window, exactly like every other widget in web/js/lib/overlay_layout.js).

CALIBRATION:
  Anchor (2026-06-21): game.cfg MinimapScale=1.62, FlipMiniMap=0; measured
  minimap side = 0.2889*height, right inset = 0.0039*width, bottom inset =
  0.0069*height (a 312px square at (1600,760) on the 1920x1080 design canvas).

  Scale model (2026-07-05): a live sweep at 2560x1440 measured the minimap side
  against the MinimapScale float - 0.0 -> ~238px, 0.93 -> ~340px, 1.62 -> 416px
  (anchor), 2.70 -> ~535px. Those fall on a straight line, so side is AFFINE in
  the scale (slope*scale + a real floor), NOT proportional through the origin:
  the minimap bottoms out near 0.165*height, never collapsing to zero. The
  intercept is pinned so 1.62 still maps to the 0.2889 anchor exactly. The
  team-frame strip (ShowTeamFramesOnLeft=0) rides above the minimap and scales
  with it - which is why MinimapScale is part of config_key. The operator-nudge
  + clamps absorb any residual error.

ASCII only (repo hard rule).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# --- calibration constants (see module docstring) ---------------------------
CAL_SCALE = 1.62
SIDE_FRAC_H_AT_CAL = 0.2889   # minimap side / screen height at CAL_SCALE
# Affine model: side_frac = SLOPE*scale + INTERCEPT (fraction of screen height).
# Slope from the 2026-07-05 live sweep; intercept pinned so CAL_SCALE maps to
# SIDE_FRAC_H_AT_CAL exactly (preserves the 2026-06-21 anchor).
SIDE_FRAC_H_SLOPE = 0.0764
SIDE_FRAC_H_INTERCEPT = SIDE_FRAC_H_AT_CAL - SIDE_FRAC_H_SLOPE * CAL_SCALE  # ~0.1651
MARGIN_R_FRAC_W = 0.0039      # right inset / screen width
MARGIN_B_FRAC_H = 0.0069      # bottom inset / screen height

# sane bounds on the minimap side as a fraction of screen height
_MIN_SIDE_FRAC_H = 0.15
_MAX_SIDE_FRAC_H = 0.45
# MinimapScale upper bound (defensive clamp; the affine floor covers the low end,
# and a real scale of 0 is the smallest minimap, not a sentinel).
_MAX_SCALE = 3.0


@dataclass(frozen=True)
class MinimapRect:
    """An on-screen minimap square in a target pixel space."""

    x: int
    y: int
    w: int
    h: int
    flip: bool

    def as_bbox(self) -> tuple[int, int, int, int]:
        """(left, top, right, bottom)."""
        return (self.x, self.y, self.x + self.w, self.y + self.h)


def _coerce_scale(scale: object) -> float:
    try:
        s = float(scale)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return CAL_SCALE
    if not math.isfinite(s):
        return CAL_SCALE
    # A real MinimapScale of 0 is the smallest minimap (the affine floor), not a
    # sentinel - let it through; only coerce garbage negatives up to 0.
    return max(0.0, min(_MAX_SCALE, s))


def compute_minimap_rect(
    scale: object,
    flip: object,
    target_w: int,
    target_h: int,
) -> Optional[MinimapRect]:
    """Compute the minimap square for the given scale/flip in target px.

    Returns None when the target dimensions are non-positive or the computed
    rect fails the on-screen sanity check (caller falls back).
    """
    if target_w <= 0 or target_h <= 0:
        return None

    s = _coerce_scale(scale)
    side_frac = SIDE_FRAC_H_SLOPE * s + SIDE_FRAC_H_INTERCEPT
    side_frac = max(_MIN_SIDE_FRAC_H, min(_MAX_SIDE_FRAC_H, side_frac))

    side = side_frac * target_h
    margin_r = MARGIN_R_FRAC_W * target_w
    margin_b = MARGIN_B_FRAC_H * target_h

    if flip:
        left = margin_r
    else:
        left = target_w - margin_r - side
    top = target_h - margin_b - side

    x, y = int(round(left)), int(round(top))
    w = h = int(round(side))
    if w <= 0 or h <= 0:
        return None
    if x < 0 or y < 0 or x + w > target_w or y + h > target_h:
        return None
    return MinimapRect(x=x, y=y, w=w, h=h, flip=bool(flip))

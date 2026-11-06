"""s144 true-audit hardening of core/minimap_geometry.py.

compute_minimap_rect is documented to return None (caller falls back) on a
bad target size, and its scale / flip arguments are typed ``object``. Before
this pass:

- G1: a NaN target raised ValueError and an infinite one OverflowError out of
  int(round()) instead of returning None.
- G2: a str / None / complex target raised TypeError at the ``<= 0`` check;
  a bool target was read as 1 px.
- G3: an int target too big for a float raised OverflowError.
- G4: an absurd finite target (1e308) returned a rect with 300-digit fields;
  there was no upper bound (core.league_settings / core.hud_settings bound a
  resolution to 1..10000).
- G5: an int scale too big for a float raised OverflowError out of
  _coerce_scale, whose only job is to absorb a junk scale.
- G6: a bool scale was read as MinimapScale 1.0 instead of junk.
- G7: flip used plain truthiness, so the game.cfg strings "0" / "false"
  mirrored the minimap onto the WRONG corner.

Pure math, no I/O.
"""
from __future__ import annotations

import math
from fractions import Fraction

import pytest

from core import minimap_geometry as mg
from core.minimap_geometry import CAL_SCALE, compute_minimap_rect

# The calibrated design-canvas rect (pinned by tests/test_minimap_geometry.py
# to within a few px; pinned exactly here so a fallback is visible by VALUE).
_CAL_RECT = (1600, 761, 312, 312)


def _xywh(r):
    return (r.x, r.y, r.w, r.h)


def test_calibrated_rect_literal_anchor():
    r = compute_minimap_rect(CAL_SCALE, False, 1920, 1080)
    assert _xywh(r) == _CAL_RECT
    assert r.flip is False


# --- G1 / G2 / G3 / G4: a junk target is None, never a raise ----------------

@pytest.mark.parametrize("bad", [
    math.nan, math.inf, -math.inf,           # G1
    "1920", None, 1j, [1920], b"1920",       # G2
    True, False,                             # G2 (bool is not a size)
    10 ** 400,                               # G3
    1e308, 10001, 10 ** 6,                   # G4 (over the 10000 bound)
])
def test_junk_target_width_returns_none(bad):
    assert compute_minimap_rect(CAL_SCALE, False, bad, 1080) is None


@pytest.mark.parametrize("bad", [
    math.nan, math.inf, "1080", None, True, 10 ** 400, 1e308, 10001,
])
def test_junk_target_height_returns_none(bad):
    assert compute_minimap_rect(CAL_SCALE, False, 1920, bad) is None


@pytest.mark.parametrize("bad", [True, False, math.nan, math.inf, "5", None])
def test_coerce_target_direct(bad):
    # A bool can never yield a rect through compute_minimap_rect (1 px is too
    # small), so the bool refusal is pinned on the helper itself.
    assert mg._coerce_target(bad) is None


def test_coerce_target_accepts_the_bounds():
    assert mg._coerce_target(1) == 1.0
    assert mg._coerce_target(10000) == 10000.0
    assert mg._coerce_target(0) is None
    assert mg._coerce_target(10000.5) is None


def test_target_bound_is_inclusive_at_10000():
    r = compute_minimap_rect(CAL_SCALE, False, 10000, 10000)
    assert r is not None
    assert r.x + r.w <= 10000 and r.y + r.h <= 10000


def test_target_bound_matches_the_settings_readers():
    # The geometry bound must never be TIGHTER than the resolution bound the
    # game.cfg readers apply, or a size they accept would lose its rect.
    from core import hud_settings, league_settings
    assert mg._MAX_TARGET >= league_settings._RES_MAX
    assert mg._MAX_TARGET >= hud_settings._RES_MAX


def test_float_and_fraction_targets_still_work():
    a = compute_minimap_rect(CAL_SCALE, False, 1920.0, 1080.0)
    b = compute_minimap_rect(CAL_SCALE, False, Fraction(1920), Fraction(1080))
    assert _xywh(a) == _CAL_RECT
    assert _xywh(b) == _CAL_RECT


# --- G5 / G6: a junk scale falls back to CAL_SCALE, never a raise -----------

def test_overflowing_int_scale_falls_back_to_calibration():
    r = compute_minimap_rect(10 ** 400, False, 1920, 1080)
    assert r is not None
    assert _xywh(r) == _CAL_RECT


def test_overflowing_int_scale_coerce_direct():
    assert mg._coerce_scale(10 ** 400) == CAL_SCALE


@pytest.mark.parametrize("b", [True, False])
def test_bool_scale_is_junk_not_one_or_zero(b):
    assert mg._coerce_scale(b) == CAL_SCALE
    assert _xywh(compute_minimap_rect(b, False, 1920, 1080)) == _CAL_RECT


def test_numeric_and_string_scales_unchanged():
    assert mg._coerce_scale(1) == 1.0
    assert mg._coerce_scale(0) == 0.0
    assert mg._coerce_scale(" 2.5 ") == 2.5
    assert mg._coerce_scale(-5) == 0.0
    assert mg._coerce_scale(99) == mg._MAX_SCALE


# --- G7: flip is an explicit on value, never truthiness ---------------------

@pytest.mark.parametrize("off", [
    "0", "false", "False", "FALSE", " 0 ", "", "no", "off",
    0, 0.0, 2, -1, math.nan, [], [1], {"a": 1}, None, 10 ** 400, object(),
])
def test_flip_off_values_keep_the_default_corner(off):
    r = compute_minimap_rect(CAL_SCALE, off, 1920, 1080)
    assert _xywh(r) == _CAL_RECT
    assert r.flip is False


@pytest.mark.parametrize("on", [True, 1, 1.0, "1", "true", "True", " TRUE "])
def test_flip_on_values_anchor_left(on):
    r = compute_minimap_rect(CAL_SCALE, on, 1920, 1080)
    assert r.flip is True
    assert (r.x, r.y, r.w, r.h) == (7, 761, 312, 312)


def test_flip_matches_league_settings_parser():
    # core.league_settings turns FlipMiniMap into a bool with the set
    # ("1", "true", "True"); the geometry must agree on every one of those
    # strings when handed the raw value.
    for raw in ("1", "true", "True"):
        assert mg._coerce_flip(raw) is True
    for raw in ("0", "false", "False", "2", "yes"):
        assert mg._coerce_flip(raw) is False


# --- the never-raise contract over a mixed grid -----------------------------

_JUNK = [math.nan, math.inf, None, "x", True, 10 ** 400, 1e308, -1, 0, [], 1j]


def test_never_raises_over_a_junk_grid():
    for scale in _JUNK + [CAL_SCALE]:
        for flip in _JUNK + [True, False]:
            for w in _JUNK + [1920]:
                for h in _JUNK + [1080]:
                    r = compute_minimap_rect(scale, flip, w, h)
                    if r is not None:
                        assert r.x >= 0 and r.y >= 0
                        assert r.x + r.w <= 1920 and r.y + r.h <= 1080
                        assert isinstance(r.flip, bool)

"""Hardening of agents/daemon_slayer/geometry.py (s144 true-audit, S144-T-684).

The module turns the CDragon geometry sidecar (third-party JSON) into a shape
string, an AoE damage multiplier and three magnitude accessors. Each test
below was RED at the audited HEAD:

- F1 the three magnitude accessors returned ``nan`` / ``inf`` for a
  non-finite datum (``nan <= 0`` is False and ``nan`` is in no sentinel set),
  although each promises "the positive float ... or None";
- F2 a JSON integer too large for a float raised ``OverflowError`` out of
  the accessors, whose handler lists only TypeError / ValueError /
  AttributeError;
- F3 ``spell_cone_angle`` read a bool ``True`` as a 1.0 degree cone, unlike
  its two siblings, which reject a bool;
- F4 ``classify_spell_shape`` raised ``AttributeError`` on a truthy
  non-mapping geometry and ``TypeError`` on an unhashable ``cast_radius``,
  and classified a non-finite or non-numeric ``cast_radius`` (and the string
  form of a conflation sentinel) as a real "circle", so the AoE multiplier
  scaled damage off a radius the radius accessor rejects;
- F5 ``aoe_multiplier`` raised ValueError / OverflowError / TypeError on a
  NaN, infinite or None ``targets_hit`` instead of clamping as documented
  ("values above the cap are clamped to the cap").

Every real sidecar value is a finite float, None or a bool flag (measured
over every tracked ``data/daemon_slayer/*/cdragon_spell_stats.json``), so the
in-range output is unchanged; ``test_in_range_parity_*`` pins that.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from agents.daemon_slayer import geometry
from agents.daemon_slayer.geometry import (
    _AOE_TARGET_CAP,
    aoe_multiplier,
    classify_spell_shape,
    is_aoe_shape,
    spell_aoe_multiplier,
    spell_cast_radius,
    spell_cone_angle,
    spell_cone_distance,
)

_HUGE = 10**400  # a valid JSON integer that no float can hold


class _Stub:
    """Minimal snapshot exposing only ``spell_geometry``."""

    def __init__(self, geo):
        self._geo = geo

    def spell_geometry(self, champ_id, slot):
        return self._geo


_ACCESSORS = (
    (spell_cone_angle, "cone_angle"),
    (spell_cone_distance, "cone_distance"),
    (spell_cast_radius, "cast_radius"),
)


# ---------------- F1: non-finite magnitude ----------------


@pytest.mark.parametrize(("accessor", "key"), _ACCESSORS)
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "nan", "inf", "1e999"])
def test_f1_non_finite_magnitude_is_none(accessor, key, bad):
    geo = {key: bad}
    if key == "cast_radius":
        geo["cast_radius_conflated"] = False
    assert accessor(_Stub(geo), "X", "Q") is None


# ---------------- F2: overflow never escapes ----------------


@pytest.mark.parametrize(("accessor", "key"), _ACCESSORS)
@pytest.mark.parametrize("bad", [_HUGE, -_HUGE])
def test_f2_overflowing_integer_is_none(accessor, key, bad):
    geo = {key: bad}
    if key == "cast_radius":
        geo["cast_radius_conflated"] = False
    assert accessor(_Stub(geo), "X", "Q") is None


# ---------------- F3: bool is not an angle ----------------


@pytest.mark.parametrize("flag", [True, False])
def test_f3_cone_angle_rejects_bool(flag):
    assert spell_cone_angle(_Stub({"cone_angle": flag}), "X", "W") is None


# ---------------- F4: classifier on junk ----------------


@pytest.mark.parametrize("geo", [["line_width"], "line", (1,), 7, object()])
def test_f4_non_mapping_geometry_is_unknown(geo):
    assert classify_spell_shape(geo) == "unknown"
    assert is_aoe_shape(geo) is False
    assert aoe_multiplier(geo, 5) == 1.0


@pytest.mark.parametrize(
    "radius",
    [float("nan"), float("inf"), "wide", [250.0], {"r": 1}, True, _HUGE, "210"],
)
def test_f4_junk_cast_radius_is_not_a_circle(radius):
    geo = {"cast_radius": radius, "cast_radius_conflated": False}
    assert classify_spell_shape(geo) == "point"
    assert aoe_multiplier(geo, 5) == 1.0


def test_f4_classifier_agrees_with_radius_accessor_on_junk():
    for radius in (float("nan"), "wide", True, "100"):
        geo = {"cast_radius": radius, "cast_radius_conflated": False}
        assert spell_cast_radius(_Stub(geo), "X", "W") is None
        assert classify_spell_shape(geo) != "circle", radius


def test_f4_numeric_string_radius_still_a_circle():
    # numeric strings stay accepted, as the accessors' own tests pin
    geo = {"cast_radius": "275", "cast_radius_conflated": False}
    assert classify_spell_shape(geo) == "circle"


# ---------------- F5: targets_hit clamp ----------------


def _line():
    return {"line_width": 70.0}


@pytest.mark.parametrize(
    ("hit", "want"),
    [
        (float("nan"), 1.0),
        (None, 1.0),
        ("many", 1.0),
        (float("-inf"), 1.0),
        (float("inf"), float(_AOE_TARGET_CAP)),
        (_HUGE, float(_AOE_TARGET_CAP)),
        (-_HUGE, 1.0),
    ],
)
def test_f5_targets_hit_junk_clamps(hit, want):
    assert aoe_multiplier(_line(), hit) == want


def test_f5_wrapper_follows_the_documented_inf_clamp():
    assert spell_aoe_multiplier(_Stub(_line()), "X", "Q", float("inf")) == float(_AOE_TARGET_CAP)


# ---------------- in-range parity (characterization) ----------------


@pytest.mark.parametrize(
    ("hit", "want"), [(0, 1.0), (1, 1.0), (2, 2.0), (3, 3.0), (2.9, 2.0), (8, 5.0), ("3", 3.0), (True, 1.0)]
)
def test_in_range_parity_targets_hit(hit, want):
    assert aoe_multiplier(_line(), hit) == want


@pytest.mark.parametrize(
    ("geo", "shape"),
    [
        (None, "unknown"),
        ({}, "unknown"),
        ({"line_width": 70.0}, "line"),
        ({"cone_angle": 0.0}, "cone"),
        ({"cone_distance": 100.0}, "cone"),
        ({"cast_radius": 0.0, "cast_radius_conflated": False}, "circle"),
        ({"cast_radius": -5.0, "cast_radius_conflated": False}, "circle"),
        ({"cast_radius": 275.0}, "circle"),
        ({"cast_radius": 210.0, "cast_radius_conflated": False}, "point"),
        ({"cast_radius": 275.0, "cast_radius_conflated": True}, "point"),
        ({"cast_radius": None, "line_width": None}, "point"),
    ],
)
def test_in_range_parity_classifier(geo, shape):
    assert classify_spell_shape(geo) == shape


@pytest.mark.parametrize(("accessor", "key"), _ACCESSORS)
def test_in_range_parity_accessors(accessor, key):
    geo = {key: 345.5}
    if key == "cast_radius":
        geo["cast_radius_conflated"] = False
    got = accessor(_Stub(geo), "X", "Q")
    assert got == 345.5 and isinstance(got, float)
    geo[key] = "345"
    assert accessor(_Stub(geo), "X", "Q") == 345.0


def test_magnitudes_are_always_finite_or_none():
    for bad in (float("nan"), float("inf"), _HUGE, "nan"):
        for accessor, key in _ACCESSORS:
            got = accessor(_Stub({key: bad}), "X", "Q")
            assert got is None or math.isfinite(got)


def test_module_is_ascii_and_lf():
    raw = Path(geometry.__file__).read_bytes()
    assert all(b < 128 for b in raw)
    assert b"\r\n" not in raw

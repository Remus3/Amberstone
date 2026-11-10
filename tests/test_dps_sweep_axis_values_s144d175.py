"""S144-D-175 - ``compute_dps_sweep`` drops a non-numeric ``axis_values`` entry.

The function already drops a NaN / +-inf entry on BOTH axes (P2 W2,
``tests/test_p2w2_ds_a.py``) so one malformed caller value cannot sink the
whole curve. Measured at HEAD before this fix, a non-numeric entry still did:
``math.isfinite`` raised ``TypeError`` for a str / None / object entry and
``OverflowError`` for an int too large for a float, on the resist axes and on
the level axis alike. Contract pinned here: such an entry is dropped like a
non-finite one, so the curve equals the curve over the clean entries; a
numeric string keeps its float reading; finite numbers are unchanged.

Python callers only: the dashboard route builds its list from ``range``.
"""
from __future__ import annotations

import pytest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps_sweep import (
    AXIS_LEVEL,
    AXIS_TARGET_ARMOR,
    AXIS_TARGET_MR,
    compute_dps_sweep,
)

_CHAMP = "Caitlyn"
_BUILD = ("3094", "3031", "3036")
_JUNK = ["x", None, object(), 10 ** 400, float("nan"), float("inf")]


@pytest.fixture(scope="module")
def snap() -> DataSnapshot:
    return DataSnapshot.load()


def _sweep(snap, axis, values):
    return compute_dps_sweep(
        snap, _CHAMP, item_ids=_BUILD, axis=axis, axis_values=values,
        target_armor=50.0, target_mr=40.0,
    )


@pytest.mark.parametrize("axis", [AXIS_TARGET_ARMOR, AXIS_TARGET_MR])
@pytest.mark.parametrize("junk", _JUNK, ids=lambda v: type(v).__name__)
def test_resist_axis_drops_a_junk_entry(snap, axis, junk):
    clean = _sweep(snap, axis, [0.0, 50.0, 100.0])
    assert len(clean.points) == 3
    assert _sweep(snap, axis, [0.0, junk, 50.0, 100.0]) == clean


@pytest.mark.parametrize("junk", _JUNK, ids=lambda v: type(v).__name__)
def test_level_axis_drops_a_junk_entry(snap, junk):
    clean = _sweep(snap, AXIS_LEVEL, [1, 11])
    assert len(clean.points) == 2
    assert _sweep(snap, AXIS_LEVEL, [1, junk, 11]) == clean


def test_an_all_junk_list_is_an_empty_curve_not_a_raise(snap):
    r = _sweep(snap, AXIS_TARGET_ARMOR, ["x", None])
    assert r.points == ()


def test_numeric_strings_keep_their_float_reading(snap):
    assert _sweep(snap, AXIS_TARGET_ARMOR, ["0", "50"]) == _sweep(
        snap, AXIS_TARGET_ARMOR, [0.0, 50.0])
    assert _sweep(snap, AXIS_LEVEL, ["1", "11"]) == _sweep(
        snap, AXIS_LEVEL, [1, 11])


def test_finite_values_are_unchanged(snap):
    r = _sweep(snap, AXIS_TARGET_ARMOR, [0, 25.5, 300])
    assert [p.x for p in r.points] == [0.0, 25.5, 300.0]
    lv = _sweep(snap, AXIS_LEVEL, [1, 5.7, 18])
    assert [p.x for p in lv.points] == [1.0, 5.0, 18.0]

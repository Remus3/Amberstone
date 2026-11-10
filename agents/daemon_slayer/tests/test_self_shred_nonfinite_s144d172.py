"""S144-D-172..174 - ``compute_self_shred_uplift`` keeps its NEVER-raises,
always-finite contract for a bad target resist or a bad channel DPS.

The docstring promises a 0.0-uplift result with a note, never a raise, and the
dataclass documents ``dps_uplift_pct`` / ``dps_uplift_abs`` as ``>= 0``.
Measured at HEAD before the fix (Nasus L11, target 100 armor / 60 MR, 500
physical DPS: 33.33 pct / 166.67 abs):

* S144-D-172: a NaN or -inf ``target_armor`` / ``target_mr`` gave a NaN
  ``dps_uplift_pct`` and ``dps_uplift_abs``; +inf gave a NaN
  ``new_mit_factor`` and an infinite ``target_resist`` in the result.
* S144-D-173: a non-numeric resist (None, "x") raised TypeError / ValueError
  out of this fail-soft surface.
* S144-D-174: a NaN / +-inf channel DPS gave a NaN / inf ``dps_uplift_abs``,
  a negative one gave a NEGATIVE uplift, and a non-numeric one raised.

Contract pinned here: a resist that is not a finite number skips that shred
source (a champion left with no usable source gets the zero result with a
note); a channel DPS that is not a finite non-negative number reads as 0.0,
the parameter's own default, and the percentage is unchanged. The resist of
the channel a shred does NOT touch is never read, so a bad MR leaves an armor
shred's result byte-identical. Stub snapshots, synthetic champion ids only.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from agents.daemon_slayer import self_shred as ss

_NAN = float("nan")
_INF = float("inf")
_HUGE = pytest.param(10 ** 400, id="huge_int")


class _Snap:
    def __init__(self, result):
        self._result = result

    def get_abilities(self, champion):
        return self._result


def _form(attribute, values=(10, 20, 30, 40, 50), units=("",),
          damage_type="PHYSICAL"):
    blk = SimpleNamespace(
        attribute=attribute, attribute_kind="modifier",
        raw_modifiers=({"values": list(values), "units": list(units)},),
    )
    return (SimpleNamespace(damage_blocks=(blk,), damage_type=damage_type),)


def _armor_snap():
    return _Snap({"E": _form("Armor Reduction")})


def _mr_snap():
    return _Snap({"W": _form("Magic Resistance Reduction",
                             damage_type="MAGIC")})


def _both_snap():
    return _Snap({
        "E": _form("Armor Reduction"),
        "W": _form("Magic Resistance Reduction", damage_type="MAGIC"),
    })


def _all_finite(r):
    return all(
        math.isfinite(v) for v in r.to_dict().values() if isinstance(v, float)
    )


def _call(snap, armor=100.0, mr=60.0, phys=500.0, magic=300.0):
    return ss.compute_self_shred_uplift(
        "Synth", 11, armor, mr,
        champion_physical_dps=phys, champion_magic_dps=magic,
        snapshot=snap,
    )


def _assert_zero(r, note_fragment):
    assert r.shred_source == ""
    assert r.resist_kind == ""
    assert (r.dps_uplift_pct, r.dps_uplift_abs) == (0.0, 0.0)
    assert (r.old_mit_factor, r.new_mit_factor, r.target_resist) == (
        0.0, 0.0, 0.0,
    )
    assert note_fragment in r.notes


# ---- S144-D-172: non-finite resist ------------------------------------------

@pytest.mark.parametrize("bad", [_NAN, _INF, -_INF])
def test_non_finite_armor_is_a_zero_result_for_an_armor_shred(bad):
    r = _call(_armor_snap(), armor=bad)
    assert _all_finite(r)
    _assert_zero(r, "target_armor")


@pytest.mark.parametrize("bad", [_NAN, _INF, -_INF])
def test_non_finite_mr_is_a_zero_result_for_an_mr_shred(bad):
    r = _call(_mr_snap(), mr=bad)
    assert _all_finite(r)
    _assert_zero(r, "target_mr")


@pytest.mark.parametrize("bad", [_NAN, _INF, -_INF, None, "x"])
def test_bad_mr_never_touches_an_armor_shred(bad):
    good = _call(_armor_snap())
    assert _call(_armor_snap(), mr=bad) == good


@pytest.mark.parametrize("bad", [_NAN, _INF, -_INF, None, "x"])
def test_bad_armor_never_touches_an_mr_shred(bad):
    good = _call(_mr_snap())
    assert _call(_mr_snap(), armor=bad) == good


@pytest.mark.parametrize("bad", [_NAN, _INF, -_INF, None, "x"])
def test_bad_armor_falls_through_to_the_mr_source(bad):
    r = _call(_both_snap(), armor=bad)
    assert r.shred_source == "Synth:W"
    assert r.resist_kind == ss.RESIST_MR
    assert r == _call(_mr_snap())
    assert _all_finite(r)


# ---- S144-D-173: non-numeric resist ------------------------------------------

@pytest.mark.parametrize("bad", [None, "x", object(), _HUGE])
def test_non_numeric_armor_never_raises(bad):
    r = _call(_armor_snap(), armor=bad)
    _assert_zero(r, "target_armor")


@pytest.mark.parametrize("bad", [None, "x", object(), _HUGE])
def test_non_numeric_mr_never_raises(bad):
    r = _call(_mr_snap(), mr=bad)
    _assert_zero(r, "target_mr")


def test_numeric_string_resist_keeps_its_float_reading():
    assert _call(_armor_snap(), armor="100") == _call(_armor_snap())


def test_finite_resists_are_unchanged():
    r = _call(_armor_snap())
    assert r.shred_source == "Synth:E"
    assert r.target_resist == 100.0
    assert r.dps_uplift_abs == pytest.approx(500.0 * r.dps_uplift_pct / 100.0)
    assert r.dps_uplift_pct > 0.0


# ---- S144-D-174: bad channel DPS ---------------------------------------------

@pytest.mark.parametrize("bad", [_NAN, _INF, -_INF, -500.0, None, "x",
                                 object(), _HUGE])
def test_bad_physical_dps_reads_as_zero(bad):
    good = _call(_armor_snap())
    r = _call(_armor_snap(), phys=bad)
    assert _all_finite(r)
    assert r.dps_uplift_abs == 0.0
    assert r.dps_uplift_pct == good.dps_uplift_pct
    assert r.shred_source == good.shred_source


@pytest.mark.parametrize("bad", [_NAN, _INF, -_INF, -300.0, None, "x",
                                 object(), _HUGE])
def test_bad_magic_dps_reads_as_zero(bad):
    good = _call(_mr_snap())
    r = _call(_mr_snap(), magic=bad)
    assert _all_finite(r)
    assert r.dps_uplift_abs == 0.0
    assert r.dps_uplift_pct == good.dps_uplift_pct


@pytest.mark.parametrize("bad", [_NAN, _INF, -1.0, None, "x"])
def test_bad_dps_on_the_unused_channel_is_ignored(bad):
    assert _call(_armor_snap(), magic=bad) == _call(_armor_snap())
    assert _call(_mr_snap(), phys=bad) == _call(_mr_snap())


def test_numeric_string_dps_keeps_its_float_reading():
    assert _call(_armor_snap(), phys="500") == _call(_armor_snap())


def test_uplift_abs_is_never_negative_over_a_grid():
    for phys in (0.0, 1e-9, 1.0, 500.0, 1e6):
        for armor in (0.0, 1.0, 100.0, 1e6):
            r = _call(_armor_snap(), armor=armor, phys=phys)
            assert r.dps_uplift_abs >= 0.0
            assert r.dps_uplift_pct >= 0.0
            assert _all_finite(r)

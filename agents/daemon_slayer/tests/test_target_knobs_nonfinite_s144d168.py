"""S144-D-168..171 - the damage scorers refuse a non-finite target knob.

Measured at HEAD (lane/ds, 2026-11-08), level 11, targets armor 100 / MR 60 /
max HP 2500 / bonus HP 1200 unless named:

- S144-D-168: ``compute_dps`` (Jinx 3031 + 3153, weighted_dps 86.52 at armor
  100, 173.04 at armor 0): ``target_armor`` NaN gave NaN; +inf gave 215.73, the
  WHOLE raw attack DPS, more than a zero-armor target takes; -inf gave 346.09.
  ``target_mr`` NaN gave NaN for Brand (6653 + 3089). ``target_max_hp`` NaN /
  +inf read silently as 0.0 (Jinx 46.02, where 1e6 gives 16246.02).
  ``compute_hybrid`` reaches the same math through its first ``compute_dps``
  call (Darius 3071 + 3053: dps 38.88 at armor 100, 138.48 at armor +inf).
- S144-D-169: ``compute_burst_damage`` (Zed 3142 + 6692, total 742.40):
  ``target_armor`` NaN gave 1351.17 (read as zero armor), ``target_mr`` NaN
  gave a NaN total.
- S144-D-170: ``compute_ability_dps`` (Brand 6653 + 3089, total 59.63):
  ``target_mr`` NaN gave a NaN total, -inf gave 190.82.

Contract after the fix: each of the four target knobs, when it is a float and
not finite (NaN, +inf, -inf), raises ValueError naming the knob - the same
contract all three functions already apply to ``target_current_hp_pct``. NaN
has no default to fall back to here (0.0 armor is exactly the inflated
reading the bug produced). Every finite value and every non-float value is
unchanged. The HTTP routes reject non-finite numbers first
(``server._opt_float``), and the dashboard's own parsers drop them, so only
Python callers could reach these.
"""
from __future__ import annotations

import math

import pytest

from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.hybrid import compute_hybrid

_NAN = float("nan")
_INF = float("inf")
_KNOBS = ("target_armor", "target_mr", "target_max_hp", "target_bonus_hp")
_BAD = (_NAN, _INF, -_INF)
_TARGETS = {
    "target_armor": 100.0,
    "target_mr": 60.0,
    "target_max_hp": 2500.0,
    "target_bonus_hp": 1200.0,
}


@pytest.fixture(scope="module")
def snap():
    return DataSnapshot.load()


def _dps(snap, **kw):
    args = dict(_TARGETS, **kw)
    return compute_dps(snap, "Jinx", 11, item_ids=["3031", "3153"], **args).weighted_dps


def _hybrid(snap, **kw):
    args = dict(_TARGETS, **kw)
    return compute_hybrid(snap, "Darius", 11, item_ids=["3071", "3053"], **args).dps


def _burst(snap, **kw):
    args = dict(_TARGETS, **kw)
    return compute_burst_damage(
        snap, "Zed", 11, item_ids=["3142", "6692"], **args
    ).total_burst_damage


def _ability(snap, **kw):
    args = dict(_TARGETS, **kw)
    return compute_ability_dps(
        snap, "Brand", 11, item_ids=["6653", "3089"], **args
    ).total_ability_dps


_SCORERS = {
    "compute_dps": _dps,
    "compute_hybrid": _hybrid,
    "compute_burst_damage": _burst,
    "compute_ability_dps": _ability,
}


@pytest.mark.parametrize("scorer", sorted(_SCORERS))
@pytest.mark.parametrize("knob", _KNOBS)
@pytest.mark.parametrize("bad", _BAD, ids=("nan", "pinf", "ninf"))
def test_non_finite_target_knob_is_refused(snap, scorer, knob, bad):
    with pytest.raises(ValueError, match=knob):
        _SCORERS[scorer](snap, **{knob: bad})


@pytest.mark.parametrize("scorer", sorted(_SCORERS))
def test_defaults_are_finite_and_positive(snap, scorer):
    # Anchor: the fixture builds really produce damage, so the refusal tests
    # are not passing on a scorer that would have returned 0.0 anyway.
    value = _SCORERS[scorer](snap)
    assert math.isfinite(value)
    assert value > 0.0


@pytest.mark.parametrize("scorer", sorted(_SCORERS))
@pytest.mark.parametrize("knob", _KNOBS)
@pytest.mark.parametrize("value", (0.0, 1e6, -50.0))
def test_finite_target_knob_still_scores(snap, scorer, knob, value):
    assert math.isfinite(_SCORERS[scorer](snap, **{knob: value}))


@pytest.mark.parametrize("scorer", sorted(_SCORERS))
@pytest.mark.parametrize("knob", _KNOBS)
def test_int_knob_reads_like_its_float(snap, scorer, knob):
    # The refusal is float-only: an int (always finite) is untouched.
    as_int = int(_TARGETS[knob])
    assert _SCORERS[scorer](snap, **{knob: as_int}) == _SCORERS[scorer](snap)


def test_armor_still_lowers_dps_on_the_finite_range(snap):
    # The defect inverted this at +inf (215.73 > 173.04 at armor 0); the
    # finite curve stays monotone.
    assert _dps(snap, target_armor=0.0) > _dps(snap) > _dps(snap, target_armor=1e6)


def test_mr_still_lowers_ability_dps_on_the_finite_range(snap):
    # Brand's ability DPS is magical, so MR lowers it (NaN made it NaN).
    assert _ability(snap, target_mr=0.0) > _ability(snap) > _ability(snap, target_mr=1e6)


# ---- S144-D-171: the burst walkers inherit the refusal ----------------------
# compute_combo, compute_mana_bounded_combo and compute_fight_report call
# compute_burst_damage and already fail soft (log, empty result) when it
# raises. At HEAD a NaN target_mr instead leaked through as a NaN
# total_mitigated (combo, Lux 6655 + 3089, Q E R: 954.53 at MR 60) and a NaN
# bounded_dps (fight report: 1272.71 at MR 60).

_LUX = dict(item_ids=["6655", "3089"], sequence=["Q", "E", "R"])


def test_combo_never_reports_a_nan_total(snap):
    from agents.daemon_slayer.combo import compute_combo

    ok = compute_combo("Lux", 11, snapshot=snap, **_LUX, **_TARGETS)
    assert ok.total_mitigated > 0.0
    bad = compute_combo("Lux", 11, snapshot=snap, **_LUX, **dict(_TARGETS, target_mr=_NAN))
    assert math.isfinite(bad.total_mitigated)
    assert bad.total_mitigated == 0.0


def test_fight_report_never_reports_a_nan_bounded_dps(snap):
    from agents.daemon_slayer.fight_report import compute_fight_report

    ok = compute_fight_report("Lux", 11, snapshot=snap, **_LUX, **_TARGETS)
    assert ok.bounded_dps > 0.0
    bad = compute_fight_report(
        "Lux", 11, snapshot=snap, **_LUX, **dict(_TARGETS, target_mr=_NAN)
    )
    assert math.isfinite(bad.bounded_dps)

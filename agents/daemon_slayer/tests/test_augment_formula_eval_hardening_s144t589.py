"""The cdragon formula evaluator keeps its "never raises" contract (S144-T-589).

``augment_formula_eval`` interprets cdragon's ``mFormulaParts`` JSON, a
payload RC does not author. Its module docstring promises the evaluator
"never raises on unknown shapes - returns 0.0" and that every call
"returns a float". Measured at HEAD before this slice:

  * an int too large for a float (``mNumber`` / ``mCoefficient`` / a
    ``dataValues`` entry of 10**400) raised OverflowError - only
    TypeError / ValueError were caught;
  * an unhashable ``__type`` / ``mStat`` / ``mDataValue`` / calc name
    raised TypeError from a dict lookup;
  * ``mStat=False`` hashed as 0 and read HP;
  * NaN / inf (a float, or the strings "nan" / "1e999") flowed straight
    into the result, and a sum or product of finite parts could overflow
    to inf, so a NaN could reach ``stat_overlay_from_calculations``
    (``if v:`` is true for NaN) and the engine's stat totals;
  * a bool ``mNumber`` / ``mCoefficient`` / data value read as 1.0;
  * a ``level_index`` of None or a str raised TypeError, True read index 1
    and 1.5 read 0.0 instead of a level;
  * a non-numeric ``ctx.stats`` / ``base_stats`` value raised ValueError,
    a non-mapping ``stats`` / ``base_stats`` / ``data_values`` /
    ``calculations`` raised AttributeError, ``ctx=None`` raised, and an
    int ``mFormulaParts`` raised TypeError.

Every real cdragon payload in data/daemon_slayer/*/arena_augments.json
carries only str / int / float of the expected kinds, so none of these
reached the live engine; the corpus test pins that every real calc still
evaluates to a finite float.
"""
from __future__ import annotations

import json
import math
import pathlib

import pytest

from agents.daemon_slayer import augment_formula_eval as E
from agents.daemon_slayer.augments import Augment

_REPO = pathlib.Path(__file__).resolve().parents[3]
_CTX = E.StatContext(stats={"hp": 1000.0, "ad": 100.0, "ap": 50.0})
_BIG = 10 ** 400
_NONFINITE = [float("nan"), float("inf"), float("-inf"), "nan", "1e999", "-inf"]


def _aug(data_values=None, calc=None) -> Augment:
    return Augment(
        id=1, api_name="T", name="T", rarity=0, desc="",
        data_values={} if data_values is None else data_values,
        calculations=calc,
    )


def _num(v):
    return {"__type": "NumberCalculationPart", "mNumber": v}


def _coef(v, stat=None):
    part = {"__type": "StatByCoefficientCalculationPart", "mCoefficient": v}
    if stat is not None:
        part["mStat"] = stat
    return part


def _named(name="X"):
    return {"__type": "NamedDataValueCalculationPart", "mDataValue": name}


def _exact_zero(v) -> bool:
    return type(v) is float and v == 0.0 and math.isfinite(v)


# ---- number / coefficient coercion ----------------------------------------


@pytest.mark.parametrize("value", [_BIG, -_BIG, True, False, *_NONFINITE])
def test_number_part_bad_value_is_zero(value):
    assert _exact_zero(E.evaluate_part(_num(value), _aug(), _CTX))


@pytest.mark.parametrize("value", [_BIG, True, *_NONFINITE])
def test_bare_coefficient_bad_value_is_zero(value):
    assert _exact_zero(E.evaluate_part(_coef(value), _aug(), _CTX))


@pytest.mark.parametrize("value", [_BIG, True, *_NONFINITE])
def test_stat_coefficient_bad_value_is_zero(value):
    assert _exact_zero(E.evaluate_part(_coef(value, 2), _aug(), _CTX))


def test_numeric_string_number_still_parses():
    # Positive control: the pre-slice float() coercion of a numeric string
    # is preserved.
    assert E.evaluate_part(_num("0.5"), _aug(), _CTX) == 0.5
    assert E.evaluate_part(_coef("2", 2), _aug(), _CTX) == 200.0


# ---- unhashable / mistyped keys ------------------------------------------


@pytest.mark.parametrize("ptype", [["NumberCalculationPart"], {"a": 1}])
def test_unhashable_type_is_zero(ptype):
    assert _exact_zero(E.evaluate_part({"__type": ptype, "mNumber": 3.0}, _aug(), _CTX))


@pytest.mark.parametrize("stat", [[2], {"a": 2}, False, True, "2", 2.5, float("nan")])
def test_bad_stat_ordinal_is_zero(stat):
    assert _exact_zero(E.evaluate_part(_coef(1.0, stat), _aug(), _CTX))
    assert _exact_zero(E.read_stat(_CTX, stat))


def test_integral_float_stat_ordinal_still_maps():
    # Positive control: 2.0 hashed equal to 2 before the slice and still maps.
    assert E.read_stat(_CTX, 2.0) == 100.0


def test_numpy_int_ordinal_and_level_still_map():
    # Positive control: a numpy int hashed equal to the int before the slice.
    np = pytest.importorskip("numpy")
    assert E.read_stat(_CTX, np.int64(2)) == 100.0
    aug = _aug({"X": [1.0, 2.0]})
    assert E.evaluate_part(_named(), aug, E.StatContext(level_index=np.int32(1))) == 2.0


@pytest.mark.parametrize("name", [["X"], {"X": 1}, 7])
def test_bad_data_value_name_is_zero(name):
    assert _exact_zero(E.evaluate_part(_named(name), _aug({"X": [4.0]}), _CTX))


@pytest.mark.parametrize("name", [["X"], {"X": 1}, None, 7])
def test_bad_calculation_name_is_zero(name):
    aug = _aug(calc={"X": {"mFormulaParts": [_num(3.0)]}})
    assert _exact_zero(E.evaluate_named_calculation(aug, name, _CTX))


# ---- data values -----------------------------------------------------------


@pytest.mark.parametrize("value", [_BIG, True, *_NONFINITE])
def test_bad_data_value_element_is_zero(value):
    assert _exact_zero(E.evaluate_part(_named(), _aug({"X": [value]}), _CTX))


@pytest.mark.parametrize("value", [_BIG, True, float("nan"), float("inf")])
def test_bad_scalar_data_value_is_zero(value):
    assert _exact_zero(E.evaluate_part(_named(), _aug({"X": value}), _CTX))


def test_bad_out_of_range_fallback_element_is_zero():
    aug = _aug({"X": [1.0, _BIG]})
    ctx = E.StatContext(level_index=5)
    assert _exact_zero(E.evaluate_part(_named(), aug, ctx))


@pytest.mark.parametrize("level", [None, "1", 1.5, True, False, [1]])
def test_bad_level_index_reads_level_zero(level):
    aug = _aug({"X": [1.0, 2.0]})
    assert E.evaluate_part(_named(), aug, E.StatContext(level_index=level)) == 1.0


def test_negative_level_index_still_falls_back_to_last():
    # Positive control: an out-of-range index (negative included) keeps the
    # documented last-entry fallback.
    aug = _aug({"X": [1.0, 2.0]})
    assert E.evaluate_part(_named(), aug, E.StatContext(level_index=-3)) == 2.0
    assert E.evaluate_part(_named(), aug, E.StatContext(level_index=9)) == 2.0


@pytest.mark.parametrize("dv", [[("X", 4.0)], "X", 5])
def test_non_mapping_data_values_is_zero(dv):
    assert _exact_zero(E.evaluate_part(_named(), _aug(dv), _CTX))


# ---- stat context ----------------------------------------------------------


@pytest.mark.parametrize("value", ["abc", None, [1], *_NONFINITE, _BIG, True])
def test_bad_resolved_stat_value_reads_zero(value):
    ctx = E.StatContext(stats={"ad": value})
    assert _exact_zero(E.read_stat(ctx, 2))


@pytest.mark.parametrize("value", ["x", float("nan"), float("inf"), True])
def test_bad_base_stat_value_reads_as_zero_base(value):
    ctx = E.StatContext(stats={"ad": 100.0}, base_stats={"ad": value})
    assert E.read_stat(ctx, 2, 2) == 100.0


@pytest.mark.parametrize("formula", [True, [2], "2", None])
def test_non_number_stat_formula_is_no_refinement(formula):
    ctx = E.StatContext(stats={"ad": 100.0}, base_stats={"ad": 40.0})
    assert E.read_stat(ctx, 2, formula) == 100.0


def test_array_stat_formula_does_not_raise():
    np = pytest.importorskip("numpy")
    ctx = E.StatContext(stats={"ad": 100.0}, base_stats={"ad": 40.0})
    assert E.read_stat(ctx, 2, np.array([2, 2])) == 100.0
    # Positive controls: 2, 2.0 and a numpy int still select the bonus delta.
    for formula in (2, 2.0, np.int64(2)):
        assert E.read_stat(ctx, 2, formula) == 60.0


@pytest.mark.parametrize("stats", [None, [("ad", 1.0)], "ad", 5])
def test_non_mapping_stats_reads_zero(stats):
    assert _exact_zero(E.read_stat(E.StatContext(stats=stats), 2))


@pytest.mark.parametrize("base", [[("ad", 1.0)], "ad", 5])
def test_non_mapping_base_stats_reads_total(base):
    ctx = E.StatContext(stats={"ad": 100.0}, base_stats=base)
    assert E.read_stat(ctx, 2, 2) == 100.0


@pytest.mark.parametrize("ctx", [None, {"stats": {"ad": 1.0}}, 5])
def test_missing_or_foreign_context_uses_empty_context(ctx):
    aug = _aug({"X": [3.0]})
    calc = {"mFormulaParts": [_named(), _coef(2.0, 2)]}
    assert E.evaluate_calculation(calc, aug, ctx) == 3.0
    assert E.evaluate_part(_named(), aug, ctx) == 3.0
    assert _exact_zero(E.read_stat(ctx, 2))


# ---- composition -----------------------------------------------------------


@pytest.mark.parametrize("parts", [5, 2.5, True, "abc", {"__type": "NumberCalculationPart"}])
def test_non_list_formula_parts_is_zero(parts):
    assert _exact_zero(E.evaluate_calculation({"mFormulaParts": parts}, _aug(), _CTX))


def test_sum_overflow_is_zero():
    calc = {"mFormulaParts": [_num(1.7e308), _num(1.7e308)]}
    assert _exact_zero(E.evaluate_calculation(calc, _aug(), _CTX))


def test_part_product_overflow_is_zero():
    ctx = E.StatContext(stats={"ad": 1e200})
    assert _exact_zero(E.evaluate_part(_coef(1e200, 2), _aug(), ctx))
    part = {"__type": "StatByNamedDataValueCalculationPart", "mDataValue": "X", "mStat": 2}
    assert _exact_zero(E.evaluate_part(part, _aug({"X": [1e200]}), ctx))


def test_multiplier_overflow_is_zero():
    calc = {"mFormulaParts": [_num(1e200)], "mMultiplier": _num(1e200)}
    assert _exact_zero(E.evaluate_calculation(calc, _aug(), _CTX))


def test_tuple_formula_parts_still_summed():
    calc = {"mFormulaParts": (_num(1.0), _num(2.0))}
    assert E.evaluate_calculation(calc, _aug(), _CTX) == 3.0


# ---- augment shape / overlay -----------------------------------------------


@pytest.mark.parametrize("calcs", [[1], "X", 5])
def test_non_mapping_calculations_is_zero(calcs):
    aug = _aug(calc=calcs)
    assert _exact_zero(E.evaluate_named_calculation(aug, "X", _CTX))
    assert E.stat_overlay_from_calculations(aug) == {}


@pytest.mark.parametrize("aug", [None, 5, {"calculations": {"X": {}}}])
def test_non_augment_is_zero(aug):
    assert _exact_zero(E.evaluate_named_calculation(aug, "X", _CTX))
    assert _exact_zero(E.evaluate_part(_named(), aug, _CTX))
    assert E.stat_overlay_from_calculations(aug) == {}


def test_overlay_never_carries_a_nonfinite_grant(monkeypatch):
    monkeypatch.setitem(E.STAT_GRANT_CALC_KEYS, "Bad", "ad")
    monkeypatch.setitem(E.STAT_GRANT_CALC_KEYS, "Good", "ap")
    aug = _aug(calc={
        "Bad": {"mFormulaParts": [_num(float("nan"))]},
        "Good": {"mFormulaParts": [_num(7.0)]},
    })
    assert E.stat_overlay_from_calculations(aug) == {"ap": 7.0}


def test_overlay_drops_a_grant_total_that_overflows(monkeypatch):
    # Each grant is finite on its own; their sum into one stat key is not.
    monkeypatch.setitem(E.STAT_GRANT_CALC_KEYS, "A", "ad")
    monkeypatch.setitem(E.STAT_GRANT_CALC_KEYS, "B", "ad")
    monkeypatch.setitem(E.STAT_GRANT_CALC_KEYS, "C", "ap")
    aug = _aug(calc={
        "A": {"mFormulaParts": [_num(1.7e308)]},
        "B": {"mFormulaParts": [_num(1.7e308)]},
        "C": {"mFormulaParts": [_num(2.0)]},
    })
    assert E.stat_overlay_from_calculations(aug) == {"ap": 2.0}


# ---- real corpus characterization -----------------------------------------


def test_every_real_calculation_evaluates_finite():
    paths = sorted((_REPO / "data" / "daemon_slayer").glob("*/arena_augments.json"))
    assert paths, "no arena_augments.json found - the corpus walk would pass empty"
    stats = {"hp": 2000.0, "ad": 150.0, "ap": 220.0, "mp": 900.0, "armor": 90.0,
             "mr": 60.0, "as": 1.3, "crit": 0.4, "ms": 380.0, "ability_haste": 30.0}
    base = {k: v / 2 for k, v in stats.items()}
    evaluated = 0
    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        recs = raw if isinstance(raw, list) else (raw.get("augments") or list(raw.values()))
        for rec in recs:
            if not isinstance(rec, dict):
                continue
            aug = Augment.from_record(rec)
            for name in aug.calculations:
                for level in (0, 3, 7):
                    for b in (None, base):
                        ctx = E.StatContext(stats=stats, base_stats=b, level_index=level)
                        v = E.evaluate_named_calculation(aug, name, ctx)
                        assert type(v) is float and math.isfinite(v), (path.parent.name, name)
                        evaluated += 1
    assert evaluated > 1000

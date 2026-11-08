"""Lane 8 true-audit regressions for core/post_game_rubric.py (s144 cycle 230).

Each test names one confirmed weakness. The JSON override file is
operator-authored and read at MODULE IMPORT, and its weights are served
verbatim as `weights_used` by GET /api/post-game-rubric; the per-match stats
come from the rewind SQLite rows (dynamically typed). The module promises
"never raises" on both paths, and the route serializes every component with
json.dumps, which writes a bare NaN / Infinity token a browser's JSON.parse
rejects.

  F1  a non-finite override weight (json.loads accepts NaN / Infinity /
      -Infinity) was applied: a NaN weight silently zeroed the axis and was
      served as a bare NaN token; Infinity produced an Infinity component.
  F2  an integer override too large for a float raised OverflowError out of
      _apply_overrides - at import time, so the module (and the dashboard
      dispatcher that imports its route) failed to import.
  F3  a deeply nested override document raised RecursionError out of
      json.loads, past the loader's ValueError handler - same import crash.
  F4  compute_role_grade raised on a non-numeric stat (a junk string, a
      dict, a list) or a non-dict stats argument despite its fail-soft,
      never-raise contract.
  F5  a NaN stat (or inf / inf) leaked NaN into the components.
  F6  a caller-supplied non-finite weight leaked NaN / Infinity into the
      components.
  F7  a bool stat counted as the number 1 (the loader already rejects a
      bool weight for the same reason).
  F8  a negative-zero weight survived the "floor to 0.0" and a "-0" stat
      produced a -0.0 component (served as -0.0).
  F9  a non-ASCII spelling that upper-cases onto an alias ("\\u017fup" ->
      "SUP") was graded as that role instead of the MID fallback.
"""
from __future__ import annotations

import json
import logging
import math
from decimal import Decimal

import pytest

from core import post_game_rubric as pgr

_AXES = ("kda", "cs_per_min", "obj_participation", "vision_score", "damage_per_min")

_GOOD_STATS = {
    "kills": 6,
    "deaths": 3,
    "assists": 9,
    "cs": 210,
    "game_time_s": 1800,
    "obj_participation_pct": 0.2,
    "vision_score": 22,
    "damage_dealt_to_champions": 24000,
}


def _defaults() -> dict[str, pgr.RoleWeights]:
    return {
        "ADC": pgr.RoleWeights(
            role="ADC", kda=1.5, cs_per_min=1.1, obj_participation=0.6,
            vision_score=0.3, damage_per_min=1.5,
        ),
        "SUP": pgr.RoleWeights(
            role="SUP", kda=1.6, cs_per_min=0.0, obj_participation=1.0,
            vision_score=1.8, damage_per_min=0.6,
        ),
    }


def _strict_json(obj) -> str:
    return json.dumps(obj, allow_nan=False)


def _all_finite_nonneg(result: dict) -> None:
    for key, value in result["components"].items():
        assert math.isfinite(value), (key, value)
        assert math.copysign(1.0, value) == 1.0, (key, value)
    assert math.isfinite(result["total_score"])
    _strict_json(result)


# --------------------------------------------------------------------- F1


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_f1_non_finite_override_weight_keeps_default(bad):
    out = pgr._apply_overrides(_defaults(), {"ADC": {"kda": bad, "cs_per_min": 2.0}})
    assert out["ADC"].kda == 1.5
    # The finite sibling axis in the same role still applies.
    assert out["ADC"].cs_per_min == 2.0


def test_f1_non_finite_override_from_file_never_served(tmp_path, monkeypatch):
    path = tmp_path / "w.json"
    path.write_bytes(b'{"ADC": {"kda": NaN, "damage_per_min": Infinity}}')
    monkeypatch.setattr(pgr, "_OVERRIDES_PATH", path)
    out = pgr._apply_overrides(_defaults(), pgr._load_weights_overrides())
    for axis in _AXES:
        _strict_json(getattr(out["ADC"], axis))
    assert out["ADC"].kda == 1.5
    assert out["ADC"].damage_per_min == 1.5


def test_f1_non_finite_override_is_warned(caplog):
    with caplog.at_level(logging.WARNING, logger=pgr.__name__):
        pgr._apply_overrides(_defaults(), {"ADC": {"kda": float("nan")}})
    assert any("non-finite" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------- F2


def test_f2_oversized_int_override_does_not_raise():
    out = pgr._apply_overrides(_defaults(), {"ADC": {"kda": 10 ** 400, "vision_score": 0.9}})
    assert out["ADC"].kda == 1.5
    assert out["ADC"].vision_score == 0.9


def test_f2_oversized_int_override_from_file(tmp_path, monkeypatch):
    path = tmp_path / "w.json"
    path.write_bytes(b'{"SUP": {"kda": 1' + b"0" * 400 + b"}}")
    monkeypatch.setattr(pgr, "_OVERRIDES_PATH", path)
    out = pgr._apply_overrides(_defaults(), pgr._load_weights_overrides())
    assert out["SUP"].kda == 1.6


# --------------------------------------------------------------------- F3


def test_f3_deeply_nested_override_file_degrades(tmp_path, monkeypatch, caplog):
    path = tmp_path / "w.json"
    depth = 200000
    path.write_bytes(b'{"ADC": ' + b"[" * depth + b"]" * depth + b"}")
    monkeypatch.setattr(pgr, "_OVERRIDES_PATH", path)
    with caplog.at_level(logging.WARNING, logger=pgr.__name__):
        assert pgr._load_weights_overrides() == {}
    assert any("defaults preserved" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------- F4


@pytest.mark.parametrize("junk", ["abc", {"a": 1}, [1, 2], object(), b"\xff"])
def test_f4_non_numeric_stat_degrades_to_zero(junk):
    stats = dict(_GOOD_STATS, damage_dealt_to_champions=junk)
    result = pgr.compute_role_grade(stats, "MID")
    assert result["components"]["dpm"] == 0.0
    # The other axes are untouched by the junk field.
    clean = pgr.compute_role_grade(dict(_GOOD_STATS, damage_dealt_to_champions=0), "MID")
    assert result == clean
    _all_finite_nonneg(result)


@pytest.mark.parametrize("stats", [None, [], "kills", 7])
def test_f4_non_dict_stats_grades_as_empty(stats):
    result = pgr.compute_role_grade(stats, "TOP")
    assert result == pgr.compute_role_grade({}, "TOP")


def test_f4_numeric_string_still_counts():
    # Characterization: a numeric TEXT cell from SQLite keeps counting.
    as_text = pgr.compute_role_grade(dict(_GOOD_STATS, cs="210"), "MID")
    as_int = pgr.compute_role_grade(_GOOD_STATS, "MID")
    assert as_text == as_int


# --------------------------------------------------------------------- F5


@pytest.mark.parametrize(
    "patch",
    [
        {"kills": float("nan")},
        {"vision_score": float("nan")},
        {"obj_participation_pct": float("nan")},
        {"kills": float("inf"), "deaths": float("inf")},
        {"game_time_s": float("nan")},
        {"cs": "NaN"},
    ],
)
def test_f5_nan_stat_never_reaches_components(patch):
    result = pgr.compute_role_grade(dict(_GOOD_STATS, **patch), "ADC")
    _all_finite_nonneg(result)


def test_f5_nan_carry_efficiency_inputs_are_finite():
    stats = dict(_GOOD_STATS, gold_share_pct=float("nan"), kp_pct="nan")
    result = pgr.compute_role_grade(stats, "ADC", carry_efficiency=True)
    assert result["components"]["carry_efficiency"] == 0.0
    _all_finite_nonneg(result)


def test_f5_huge_finite_stat_still_saturates():
    # Characterization: an absurdly large but finite stat saturates at 2x.
    result = pgr.compute_role_grade(dict(_GOOD_STATS, vision_score=1e300), "SUP")
    assert result["components"]["vision"] == pytest.approx(1.8 * 2.0)


def test_f5_infinite_stat_is_corrupt_not_a_performance():
    # Decision (recorded): a non-finite count reads as missing (0.0), so
    # corrupt data cannot saturate an axis into an S-grade contribution.
    result = pgr.compute_role_grade(dict(_GOOD_STATS, vision_score=float("inf")), "SUP")
    assert result["components"]["vision"] == 0.0
    assert result == pgr.compute_role_grade(dict(_GOOD_STATS, vision_score=0), "SUP")


# --------------------------------------------------------------------- F6


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_f6_caller_non_finite_weight_is_finite(bad):
    weights = pgr.RoleWeights(role="ADC", kda=bad, cs_per_min=1.0)
    result = pgr.compute_role_grade(_GOOD_STATS, "ADC", weights=weights)
    assert result["components"]["kda"] == 0.0
    _all_finite_nonneg(result)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), -0.0])
def test_f6_component_score_non_finite_inputs(bad):
    assert pgr._component_score(bad, 1.0, 1.0) == 0.0
    assert math.copysign(1.0, pgr._component_score(bad, 1.0, 1.0)) == 1.0
    assert pgr._component_score(1.0, 1.0, bad) == 0.0
    assert math.copysign(1.0, pgr._component_score(1.0, bad, 1.0)) == 1.0


def test_f6_overflowing_product_is_finite():
    # A finite weight whose product overflows (1e308 * 2) must not serve inf.
    assert pgr._component_score(1e308, 4.0, 1.0) == 0.0
    weights = pgr.RoleWeights(role="ADC", kda=1e308)
    result = pgr.compute_role_grade(dict(_GOOD_STATS, kills=1000), "ADC", weights=weights)
    _all_finite_nonneg(result)


def test_f6_baseline_infinity_contributes_zero():
    assert pgr._component_score(1.0, float("inf"), float("inf")) == 0.0
    assert pgr._component_score(1.0, 5.0, float("inf")) == 0.0


# --------------------------------------------------------------------- F7


def test_f7_bool_stat_is_not_a_count():
    as_bool = pgr.compute_role_grade(dict(_GOOD_STATS, kills=True, assists=False), "JG")
    as_zero = pgr.compute_role_grade(dict(_GOOD_STATS, kills=0, assists=0), "JG")
    assert as_bool == as_zero


# --------------------------------------------------------------------- F8


def test_f8_negative_zero_weight_floors_to_positive_zero():
    out = pgr._apply_overrides(_defaults(), {"ADC": {"kda": -0.0}})
    assert out["ADC"].kda == 0.0
    assert math.copysign(1.0, out["ADC"].kda) == 1.0


def test_f8_negative_zero_stat_component_is_positive_zero():
    result = pgr.compute_role_grade(dict(_GOOD_STATS, cs=-0.0, vision_score="-0"), "TOP")
    assert result["components"]["cs_per_min"] == 0.0
    _all_finite_nonneg(result)
    assert "-0.0" not in _strict_json(result)


# --------------------------------------------------------------------- F9


@pytest.mark.parametrize(
    "role", ["\u017fup", "ut\u0131l\u0131ty", "\u017fupport", "\uff34\uff2f\uff30", "TO\u0420"],
)
def test_f9_non_ascii_role_falls_back_to_mid(role):
    assert pgr._normalize_role(role) == "MID"


@pytest.mark.parametrize(
    ("role", "want"),
    [("utility", "SUP"), (" Bottom ", "ADC"), ("jungle", "JG"), ("TOP", "TOP"), ("", "MID"), (None, "MID")],
)
def test_f9_ascii_spellings_still_canonicalize(role, want):
    assert pgr._normalize_role(role) == want


# ------------------------------------------------------- module invariants


def test_shipped_default_vectors_sum_to_five():
    # The shipped calibration contract: a median game lands at 50.0 (B floor).
    # Read the MODULE's weights; an operator override file would legitimately
    # change them, so the check only binds when none is present.
    if pgr._OVERRIDES_PATH.exists():
        pytest.skip("operator override file present")
    assert set(pgr._DEFAULT_WEIGHTS) == {"ADC", "SUP", "JG", "MID", "TOP"}
    for role, w in pgr._DEFAULT_WEIGHTS.items():
        assert sum(getattr(w, a) for a in _AXES) == pytest.approx(5.0), role


def test_median_game_is_the_b_floor():
    if pgr._OVERRIDES_PATH.exists():
        pytest.skip("operator override file present")
    for role, base in pgr._ROLE_BASELINES.items():
        stats = {
            "kills": base["kda"],
            "deaths": 1,
            "assists": 0,
            "cs": base["cs_per_min"] * 30,
            "game_time_s": 1800,
            "obj_participation_pct": base["obj_participation"],
            "vision_score": base["vision_score"],
            "damage_dealt_to_champions": base["damage_per_min"] * 30,
        }
        result = pgr.compute_role_grade(stats, role)
        assert result["total_score"] == pytest.approx(50.0), role
        assert result["percentile_grade"] == "B", role


def test_decimal_stat_still_counts():
    # float() always accepted a Decimal; the hardening keeps that.
    as_dec = pgr.compute_role_grade(dict(_GOOD_STATS, cs=Decimal("210")), "MID")
    assert as_dec == pgr.compute_role_grade(_GOOD_STATS, "MID")
    junk = pgr.compute_role_grade(dict(_GOOD_STATS, cs=Decimal("NaN")), "MID")
    assert junk["components"]["cs_per_min"] == 0.0
    snan = pgr.compute_role_grade(dict(_GOOD_STATS, cs=Decimal("sNaN")), "MID")
    assert snan["components"]["cs_per_min"] == 0.0

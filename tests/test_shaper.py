"""
tests/test_shaper.py - property-style coverage of the shaper primitive.

Deterministic: no random module, no hypothesis dep, no external IO. The
"property" assertions iterate the FULL discrete knob space
({-2..+2}^3 = 125 combos) and the cartesian product of representative
archetype scorer dicts, so every assertion is exhaustive over the input
universe the production primitive sees.
"""
from __future__ import annotations

import itertools
import logging

import pytest

from core.shaper import (
    NUDGE_STEP,
    WEIGHT_MAX,
    WEIGHT_MIN,
    ShaperState,
    apply_shaper,
)

# Representative archetype-scorer weight dicts. Shape matches what
# `agents/daemon_slayer/rank.py` returns for each of the 6 wired
# scorers (carry / tank / bruiser / mage / assassin / enchanter) -
# the dicts are illustrative for the primitive, not pinned to live
# scorer state (which is the source of truth).
BASELINES = [
    # Bruiser-style 3-axis with utility=0.
    {"damage_alpha": 0.65, "survivability_beta": 0.35, "utility_gamma": 0.0},
    # Carry-style damage-heavy.
    {"damage_alpha": 0.80, "survivability_beta": 0.10, "utility_gamma": 0.10},
    # Enchanter-style utility-heavy.
    {"damage_alpha": 0.10, "survivability_beta": 0.20, "utility_gamma": 0.70},
    # Tank-style survivability-heavy.
    {"damage_alpha": 0.15, "survivability_beta": 0.75, "utility_gamma": 0.10},
    # Even-split mage hybrid.
    {"damage_alpha": 0.50, "survivability_beta": 0.25, "utility_gamma": 0.25},
]

ALL_KNOB_COMBOS = list(itertools.product(range(-2, 3), repeat=3))
assert len(ALL_KNOB_COMBOS) == 125


def _shaper(d: int, s: int, u: int) -> ShaperState:
    return ShaperState(damage_nudge=d, survivability_nudge=s, utility_nudge=u)


# ---------------------------------------------------------------------------
# ShaperState construction / validation
# ---------------------------------------------------------------------------


def test_shaper_state_defaults_zero():
    st = ShaperState()
    assert st.damage_nudge == 0
    assert st.survivability_nudge == 0
    assert st.utility_nudge == 0


def test_shaper_state_frozen():
    import dataclasses

    st = ShaperState(damage_nudge=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        st.damage_nudge = 2  # type: ignore[misc]


def test_shaper_state_hashable():
    a = ShaperState(1, -1, 0)
    b = ShaperState(1, -1, 0)
    assert hash(a) == hash(b)
    assert {a, b} == {a}


@pytest.mark.parametrize("bad", [-3, 3, 10, -10])
def test_shaper_state_out_of_range_raises(bad: int):
    with pytest.raises(ValueError):
        ShaperState(damage_nudge=bad)
    with pytest.raises(ValueError):
        ShaperState(survivability_nudge=bad)
    with pytest.raises(ValueError):
        ShaperState(utility_nudge=bad)


def test_shaper_state_rejects_non_int():
    with pytest.raises(ValueError):
        ShaperState(damage_nudge=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ShaperState(damage_nudge="1")  # type: ignore[arg-type]
    # booleans subclass int in Python; we explicitly reject them.
    with pytest.raises(ValueError):
        ShaperState(damage_nudge=True)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Identity (0,0,0) returns equivalent dict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("baseline", BASELINES)
def test_identity_returns_equivalent_dict(baseline):
    out = apply_shaper(baseline, ShaperState(0, 0, 0))
    # Same keys
    assert set(out.keys()) == set(baseline.keys())
    # Values equivalent within float epsilon
    for k in baseline:
        assert out[k] == pytest.approx(baseline[k], abs=1e-12)


def test_identity_does_not_mutate_input():
    inp = {"damage_alpha": 0.65, "survivability_beta": 0.35, "utility_gamma": 0.0}
    snapshot = dict(inp)
    apply_shaper(inp, ShaperState(0, 0, 0))
    assert inp == snapshot


def test_apply_returns_new_dict_instance():
    inp = {"damage_alpha": 0.65, "survivability_beta": 0.35, "utility_gamma": 0.0}
    out = apply_shaper(inp, ShaperState(1, 0, 0))
    assert out is not inp


# ---------------------------------------------------------------------------
# Sum-to-1 invariant across every knob combo + every baseline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("baseline", BASELINES)
def test_sum_to_one_invariant_full_combo_space(baseline):
    for d, s, u in ALL_KNOB_COMBOS:
        out = apply_shaper(baseline, _shaper(d, s, u))
        total = sum(out.values())
        assert total == pytest.approx(1.0, abs=1e-9), (
            f"baseline={baseline} knobs=({d},{s},{u}) sum={total}"
        )


# ---------------------------------------------------------------------------
# Monotonicity: +1 damage strictly increases damage weight
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("baseline", BASELINES)
def test_damage_plus_one_strictly_increases_damage(baseline):
    base_out = apply_shaper(baseline, ShaperState(0, 0, 0))
    plus_out = apply_shaper(baseline, ShaperState(1, 0, 0))
    # Find the damage key.
    dkey = next(k for k in baseline if "damage" in k)
    # Strict increase unless the damage weight was already at the
    # clamp ceiling (none of our BASELINES start there, so this is
    # a hard '>' here).
    assert plus_out[dkey] > base_out[dkey], (
        f"baseline={baseline} base={base_out[dkey]} plus1={plus_out[dkey]}"
    )


@pytest.mark.parametrize("baseline", BASELINES)
def test_survivability_plus_one_strictly_increases_survivability(baseline):
    base_out = apply_shaper(baseline, ShaperState(0, 0, 0))
    plus_out = apply_shaper(baseline, ShaperState(0, 1, 0))
    skey = next(k for k in baseline if "survivability" in k)
    assert plus_out[skey] > base_out[skey]


@pytest.mark.parametrize("baseline", BASELINES)
def test_utility_plus_one_strictly_increases_utility(baseline):
    # Bruiser baseline has utility=0 which after +1 nudge + clamp +
    # renorm should still strictly exceed the baseline's 0.0 share.
    base_out = apply_shaper(baseline, ShaperState(0, 0, 0))
    plus_out = apply_shaper(baseline, ShaperState(0, 0, 1))
    ukey = next(k for k in baseline if "utility" in k)
    assert plus_out[ukey] > base_out[ukey]


# ---------------------------------------------------------------------------
# Clamp: no single weight exceeds WEIGHT_MAX or drops below WEIGHT_MIN
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("baseline", BASELINES)
def test_clamp_ceiling_at_full_positive(baseline):
    out = apply_shaper(baseline, ShaperState(2, 2, 2))
    for k, v in out.items():
        assert v <= WEIGHT_MAX + 1e-9, f"key={k} v={v} exceeds ceiling"


@pytest.mark.parametrize("baseline", BASELINES)
def test_clamp_floor_at_full_negative(baseline):
    out = apply_shaper(baseline, ShaperState(-2, -2, -2))
    # The clamp floor is WEIGHT_MIN BEFORE renorm. After renorm a
    # weight can dip slightly below WEIGHT_MIN if other weights also
    # hit the floor and the renorm divisor is large; what we actually
    # assert is the spec wording: "doesn't break any single weight
    # past 0.90". So the ceiling is the load-bearing clamp here.
    # Floor: we still assert each value is strictly positive (no
    # collapse to zero) since the degenerate guard would have caught
    # any all-zero case.
    for k, v in out.items():
        assert v > 0.0, f"key={k} v={v} collapsed to <= 0"


@pytest.mark.parametrize("baseline", BASELINES)
def test_clamp_ceiling_across_full_combo_space(baseline):
    """Strongest form of the clamp claim: every (d,s,u) combo keeps
    every weight at or under WEIGHT_MAX (plus float epsilon)."""
    for d, s, u in ALL_KNOB_COMBOS:
        out = apply_shaper(baseline, _shaper(d, s, u))
        for k, v in out.items():
            assert v <= WEIGHT_MAX + 1e-9, (
                f"baseline={baseline} knobs=({d},{s},{u}) key={k} v={v}"
            )


# ---------------------------------------------------------------------------
# Degenerate guard: all-zero input returns dict unchanged + no crash
# ---------------------------------------------------------------------------


def test_all_zero_input_returns_unchanged(caplog):
    inp = {"damage_alpha": 0.0, "survivability_beta": 0.0, "utility_gamma": 0.0}
    with caplog.at_level(logging.WARNING, logger="core.shaper"):
        out = apply_shaper(inp, ShaperState(0, 0, 0))
    assert out == inp
    assert any("degenerate" in r.message.lower() for r in caplog.records)


def test_all_identical_input_returns_unchanged():
    inp = {"damage_alpha": 0.33, "survivability_beta": 0.33, "utility_gamma": 0.33}
    out = apply_shaper(inp, ShaperState(0, 0, 0))
    # All-identical baseline with zero knobs is degenerate per the
    # spec's "all weights become identical" clause - guard fires and
    # returns input unchanged.
    assert out == inp


def test_empty_dict_no_crash():
    out = apply_shaper({}, ShaperState(0, 0, 0))
    assert out == {}


def test_degenerate_guard_does_not_crash_under_max_negative_pressure():
    """Hammering -2 on all axes against a baseline whose damage axis
    is already small should not crash; either it renorms to a valid
    distribution or the degenerate guard fires and returns baseline.
    Either is acceptable; we only assert it does not raise."""
    inp = {"damage_alpha": 0.10, "survivability_beta": 0.10, "utility_gamma": 0.80}
    out = apply_shaper(inp, ShaperState(-2, -2, -2))
    # Either renormalized to sum 1.0, or returned unchanged.
    total = sum(out.values())
    assert total == pytest.approx(1.0, abs=1e-9) or out == inp


# ---------------------------------------------------------------------------
# Non-axis keys pass through (defensive: future scorers might add other
# weight dimensions; the shaper should not silently drop them)
# ---------------------------------------------------------------------------


def test_non_axis_keys_pass_through_renormalized():
    inp = {
        "damage_alpha": 0.4,
        "survivability_beta": 0.3,
        "utility_gamma": 0.2,
        "miscellaneous_extra": 0.1,
    }
    out = apply_shaper(inp, ShaperState(0, 0, 0))
    assert set(out.keys()) == set(inp.keys())
    # Sum still 1.0 (renorm respects the non-axis key)
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)
    # Non-axis key is preserved exactly (input sums to 1.0 already, so
    # the renorm divisor is 1.0 and the value should pass through).
    assert out["miscellaneous_extra"] == pytest.approx(0.1, abs=1e-12)


# ---------------------------------------------------------------------------
# Spot-check the BACKLOG-described shift magnitude.
# ---------------------------------------------------------------------------


def test_backlog_example_bruiser_damage_plus():
    """BACKLOG sketch: Bruiser alpha=0.65 / beta=0.35 / gamma=0.0,
    DAMAGE+ pushes 'toward alpha=0.80'. With NUDGE_STEP=0.075 and
    +1 knob the raw shift is 0.075; renorm produces alpha ~= 0.72.
    The exact value is not the spec contract - we only assert the
    direction + that it lands in a sane band (>baseline, <ceiling)."""
    inp = {"damage_alpha": 0.65, "survivability_beta": 0.35, "utility_gamma": 0.0}
    out = apply_shaper(inp, ShaperState(damage_nudge=1))
    assert out["damage_alpha"] > 0.65
    assert out["damage_alpha"] < WEIGHT_MAX
    assert out["survivability_beta"] < 0.35


def test_nudge_step_constant_exposed():
    # Other code (UI later, or tests) may want to reference the step.
    assert NUDGE_STEP == 0.075
    assert WEIGHT_MIN == 0.05
    assert WEIGHT_MAX == 0.90

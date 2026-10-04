"""RM-595: once FLAT reduction takes a resist to zero or below, every later
step (percent reduction, percent pen, flat pen) is skipped.

League wiki "Magic penetration" / "Armor penetration", worked Target B:
18 MR - 20 flat reduction = -2 final, even with 30 percent reduction and
pen also present. Pre-fix DS applied the percent reduction to the negative
value (-2 * 0.7 = -1.4), shrinking the negative-resist amplification.

Reference implementation: ``core.math_core.effective_resist`` (same skip).
"""

from __future__ import annotations

import pytest

from agents.daemon_slayer import effects
from agents.daemon_slayer._effects_types import ItemEffect


def _eff(**kw) -> ItemEffect:
    return ItemEffect(item_id="rm595", name="rm595", **kw)


def test_mr_target_b_wiki_minus_two():
    e = _eff(mr_reduction_flat=20.0, mr_reduction_pct=0.30,
             magic_pen_pct=0.35, magic_pen_flat=10.0)
    assert effects.effective_target_mr(18.0, [e]) == pytest.approx(-2.0)


def test_armor_target_b_wiki_minus_twelve():
    e = _eff(armor_reduction_flat=30.0, armor_reduction_pct=0.30,
             armor_pen_pct=0.45, armor_pen_flat=10.0)
    assert effects.effective_target_armor(18.0, [e], level=10) == pytest.approx(-12.0)


def test_armor_kit_pen_does_not_touch_negative_post_flat():
    e = _eff(armor_reduction_flat=30.0, armor_reduction_pct=0.30)
    got = effects.effective_target_armor(18.0, [e], kit_pen_pct=0.40, kit_pen_flat=5.0)
    assert got == pytest.approx(-12.0)


@pytest.mark.parametrize("fn,red_kw", [
    (effects.effective_target_mr, "mr_reduction"),
    (effects.effective_target_armor, "armor_reduction"),
])
def test_flat_reduction_to_exactly_zero_stays_zero(fn, red_kw):
    e = _eff(**{f"{red_kw}_flat": 18.0, f"{red_kw}_pct": 0.30})
    assert fn(18.0, [e]) == pytest.approx(0.0)


@pytest.mark.parametrize("fn,red_kw", [
    (effects.effective_target_mr, "mr_reduction"),
    (effects.effective_target_armor, "armor_reduction"),
])
def test_positive_post_flat_still_gets_percent_reduction(fn, red_kw):
    # Control: the skip must not fire while the resist is still positive.
    e = _eff(**{f"{red_kw}_flat": 20.0, f"{red_kw}_pct": 0.30})
    assert fn(80.0, [e]) == pytest.approx(42.0)


@pytest.mark.parametrize("fn,red_kw", [
    (effects.effective_target_mr, "mr_reduction"),
    (effects.effective_target_armor, "armor_reduction"),
])
def test_matches_math_core_reference_across_grid(fn, red_kw):
    from core import math_core

    for resist in (0.0, 5.0, 18.0, 30.0, 120.0):
        for flat in (0.0, 10.0, 18.0, 25.0, 40.0):
            for pct in (0.0, 0.30, 0.45):
                e = _eff(**{f"{red_kw}_flat": flat, f"{red_kw}_pct": pct})
                want = math_core.effective_resist(
                    resist, 0.0, flat_reduction=flat, pct_reductions=[pct] if pct else [],
                )
                assert fn(resist, [e]) == pytest.approx(want), (resist, flat, pct)

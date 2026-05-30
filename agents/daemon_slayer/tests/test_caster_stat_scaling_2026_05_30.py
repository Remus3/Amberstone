"""Caster-stat ability-scaling evaluator pins (2026-05-30 unit-map exhaustion).

Item 216 wired 3 new caster-stat scaling fields end to end into the LIVE
ability-DPS evaluator: caster_armor_pct -> caster_armor, caster_bonus_mp_pct
-> caster_bonus_mp, caster_bonus_ms_pct -> caster_bonus_ms. The extractor side
is pinned by test_abilities_unit_map_2026_05_30.py; the EVALUATOR side
(AbilityContext.from_build + _evaluate_block) was verified live at ship time
(Malphite W +22.5 raw at rank5 / 150 armor; Janna caster_bonus_ms 0.0 itemless)
but had no committed regression. These parametrized property tests lock the
math: caster_armor uses FULL armor (base + bonus, unlike caster_bonus_armor
which is above-base), while caster_bonus_mp / caster_bonus_ms follow the
"above level-1 base" convention. Mathematical invariants over single pins.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.abilities import DamageBlock
from agents.daemon_slayer.ability_dps import AbilityContext, _evaluate_block


# Sweep grids - small, deterministic, cover the linear regime + boundaries.
_PCTS = (0.0, 5.0, 15.0, 50.0, 100.0)
_STAT_VALS = (0.0, 25.0, 80.0, 150.0, 300.0)
_RANKS = (0, 1, 2, 3, 4)


def _ctx(**overrides) -> AbilityContext:
    base = {
        "base_ad": 60.0,
        "total_ad": 100.0,
        "bonus_ad": 40.0,
        "ap": 0.0,
        "caster_max_hp": 2000.0,
        "caster_bonus_hp": 500.0,
        "caster_bonus_armor": 0.0,
        "caster_bonus_mr": 0.0,
        "caster_max_mp": 800.0,
        "caster_mp_regen_per_5": 15.0,
        "target_armor": 60.0,
        "target_mr": 40.0,
        "target_max_hp": 2200.0,
        "target_current_hp": 2200.0,
        "target_missing_hp": 0.0,
        "target_bonus_hp": 700.0,
        "caster_armor": 0.0,
        "caster_bonus_mp": 0.0,
        "caster_bonus_ms": 0.0,
    }
    base.update(overrides)
    return AbilityContext(**base)


class CasterStatFromBuildTests(unittest.TestCase):
    """from_build resolves the 3 caster-stat ctx attrs per item-216 convention."""

    def test_caster_armor_is_full_not_bonus(self) -> None:
        # caster_armor is FULL armor (base + bonus), distinct from
        # caster_bonus_armor which is above-base. This is the subtle
        # invariant most at risk of a silent regression.
        for total_armor in _STAT_VALS:
            for base_armor in (0.0, 18.0, 40.0):
                with self.subTest(total=total_armor, base=base_armor):
                    ctx = AbilityContext.from_build(
                        stats={"armor": total_armor},
                        base_stats={"armor": base_armor},
                        target_armor=60.0, target_mr=40.0,
                        target_max_hp=2000.0, target_bonus_hp=0.0,
                    )
                    self.assertEqual(ctx.caster_armor, total_armor)
                    # bonus armor stays above-base for contrast.
                    self.assertEqual(
                        ctx.caster_bonus_armor, max(0.0, total_armor - base_armor)
                    )

    def test_caster_bonus_mp_is_above_base(self) -> None:
        for total_mp in (0.0, 400.0, 1000.0, 2400.0):
            for base_mp in (0.0, 350.0, 480.0):
                with self.subTest(total=total_mp, base=base_mp):
                    ctx = AbilityContext.from_build(
                        stats={"mp": total_mp},
                        base_stats={"mp": base_mp},
                        target_armor=60.0, target_mr=40.0,
                        target_max_hp=2000.0, target_bonus_hp=0.0,
                    )
                    self.assertEqual(ctx.caster_bonus_mp, max(0.0, total_mp - base_mp))

    def test_caster_bonus_ms_is_above_base(self) -> None:
        # Movement speed has no per-level base growth, so caster_bonus_ms is
        # exact item/buff MS above the level-1 base.
        for total_ms in (325.0, 340.0, 400.0, 490.0):
            for base_ms in (325.0, 335.0):
                with self.subTest(total=total_ms, base=base_ms):
                    ctx = AbilityContext.from_build(
                        stats={"ms": total_ms},
                        base_stats={"ms": base_ms},
                        target_armor=60.0, target_mr=40.0,
                        target_max_hp=2000.0, target_bonus_hp=0.0,
                    )
                    self.assertEqual(ctx.caster_bonus_ms, max(0.0, total_ms - base_ms))

    def test_itemless_bonus_stats_are_zero(self) -> None:
        # Item-216 Janna check: itemless build -> caster_bonus_ms 0.0 (no
        # overcount). Same for bonus_mp when total == base.
        ctx = AbilityContext.from_build(
            stats={"armor": 28.0, "mp": 480.0, "ms": 325.0},
            base_stats={"armor": 28.0, "mp": 480.0, "ms": 325.0},
            target_armor=60.0, target_mr=40.0,
            target_max_hp=2000.0, target_bonus_hp=0.0,
        )
        self.assertEqual(ctx.caster_bonus_mp, 0.0)
        self.assertEqual(ctx.caster_bonus_ms, 0.0)
        self.assertEqual(ctx.caster_armor, 28.0)  # full armor still credited

    def test_missing_stat_keys_default_zero(self) -> None:
        ctx = AbilityContext.from_build(
            stats={}, base_stats={},
            target_armor=0.0, target_mr=0.0,
            target_max_hp=0.0, target_bonus_hp=0.0,
        )
        self.assertEqual(ctx.caster_armor, 0.0)
        self.assertEqual(ctx.caster_bonus_mp, 0.0)
        self.assertEqual(ctx.caster_bonus_ms, 0.0)


class CasterStatEvaluateBlockTests(unittest.TestCase):
    """_evaluate_block multiplies each caster-stat field by its ctx attr / 100."""

    def test_caster_armor_pct_linear(self) -> None:
        for pct in _PCTS:
            for armor in _STAT_VALS:
                with self.subTest(pct=pct, armor=armor):
                    b = DamageBlock(attribute="X", attribute_kind="damage",
                                    base=(40.0,), caster_armor_pct=(pct,))
                    ctx = _ctx(caster_armor=armor)
                    self.assertAlmostEqual(
                        _evaluate_block(b, 0, ctx), 40.0 + (pct / 100.0) * armor
                    )

    def test_caster_bonus_mp_pct_linear(self) -> None:
        for pct in _PCTS:
            for mp in (0.0, 250.0, 600.0, 1200.0):
                with self.subTest(pct=pct, mp=mp):
                    b = DamageBlock(attribute="X", attribute_kind="damage",
                                    base=(20.0,), caster_bonus_mp_pct=(pct,))
                    ctx = _ctx(caster_bonus_mp=mp)
                    self.assertAlmostEqual(
                        _evaluate_block(b, 0, ctx), 20.0 + (pct / 100.0) * mp
                    )

    def test_caster_bonus_ms_pct_linear(self) -> None:
        for pct in _PCTS:
            for ms in (0.0, 35.0, 90.0, 165.0):
                with self.subTest(pct=pct, ms=ms):
                    b = DamageBlock(attribute="X", attribute_kind="damage",
                                    base=(0.0,), caster_bonus_ms_pct=(pct,))
                    ctx = _ctx(caster_bonus_ms=ms)
                    self.assertAlmostEqual(
                        _evaluate_block(b, 0, ctx), (pct / 100.0) * ms
                    )

    def test_rank_clamp_one_element_list(self) -> None:
        # A 1-element scaling list applies at every rank (value_at clamps).
        b = DamageBlock(attribute="X", attribute_kind="damage",
                        base=(10.0,), caster_armor_pct=(20.0,))
        ctx = _ctx(caster_armor=100.0)
        for rank in _RANKS:
            with self.subTest(rank=rank):
                self.assertAlmostEqual(_evaluate_block(b, rank, ctx), 30.0)

    def test_per_rank_scaling_list(self) -> None:
        b = DamageBlock(attribute="X", attribute_kind="damage",
                        base=(0.0, 0.0, 0.0, 0.0, 0.0),
                        caster_armor_pct=(10.0, 12.0, 14.0, 16.0, 18.0))
        ctx = _ctx(caster_armor=200.0)
        expected = (20.0, 24.0, 28.0, 32.0, 36.0)
        for rank in _RANKS:
            with self.subTest(rank=rank):
                self.assertAlmostEqual(_evaluate_block(b, rank, ctx), expected[rank])

    def test_doubling_stat_doubles_contribution(self) -> None:
        # Pure linearity: 2x the stat -> 2x the scaling term (base held at 0).
        b = DamageBlock(attribute="X", attribute_kind="damage",
                        base=(0.0,), caster_armor_pct=(15.0,))
        single = _evaluate_block(b, 0, _ctx(caster_armor=75.0))
        double = _evaluate_block(b, 0, _ctx(caster_armor=150.0))
        self.assertAlmostEqual(double, 2.0 * single)


class CasterStatIntegrationPins(unittest.TestCase):
    """Item-216 live-verified values, now committed regressions."""

    def test_malphite_w_shape_recovers_22_5(self) -> None:
        # Malphite W: 15% armor scaling, rank5 (idx 4), 150 armor -> +22.5 raw.
        # This is the value item 216 confirmed the old parser silently dropped.
        b = DamageBlock(attribute="W", attribute_kind="damage",
                        base=(0.0, 0.0, 0.0, 0.0, 0.0),
                        caster_armor_pct=(15.0, 15.0, 15.0, 15.0, 15.0))
        ctx = _ctx(caster_armor=150.0)
        self.assertAlmostEqual(_evaluate_block(b, 4, ctx), 22.5)

    def test_janna_itemless_ms_no_overcount(self) -> None:
        # caster_bonus_ms 0.0 itemless -> 0 contribution (no overcount).
        b = DamageBlock(attribute="W", attribute_kind="damage",
                        base=(60.0,), caster_bonus_ms_pct=(20.0,))
        ctx = _ctx(caster_bonus_ms=0.0)
        self.assertAlmostEqual(_evaluate_block(b, 0, ctx), 60.0)


if __name__ == "__main__":
    unittest.main()

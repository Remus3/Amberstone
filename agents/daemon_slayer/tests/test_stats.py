import unittest

from agents.daemon_slayer.stats import (
    aggregate_item_stats,
    attack_speed_scaling,
    clamp_level,
    growth_multiplier,
    scaled,
)


class GrowthMultiplierTests(unittest.TestCase):
    """Riot champion stat growth multiplier.

    growth_multiplier(n) = (n - 1) * (0.7025 + 0.0175 * (n - 1))

    This is the canonical Riot/League-wiki stat-growth coefficient. It
    coincides with the naive linear multiplier (n - 1) ONLY at the two
    endpoints - level 1 (multiplier 0) and level 18 (multiplier exactly
    17.0). For every level 2..17 it is strictly lower than (n - 1); the
    pre-fix engine used the linear multiplier and over-stated every
    per-level stat between the endpoints.
    """

    def test_level_1_is_zero(self) -> None:
        # (1-1) * anything == 0
        self.assertEqual(growth_multiplier(1), 0.0)

    def test_level_6(self) -> None:
        # 5 * (0.7025 + 0.0175*5) = 5 * 0.79 = 3.95
        self.assertAlmostEqual(growth_multiplier(6), 3.95, places=9)

    def test_level_11(self) -> None:
        # 10 * (0.7025 + 0.0175*10) = 10 * 0.8775 = 8.775
        self.assertAlmostEqual(growth_multiplier(11), 8.775, places=9)

    def test_level_13(self) -> None:
        # 12 * (0.7025 + 0.0175*12) = 12 * 0.9125 = 10.95
        self.assertAlmostEqual(growth_multiplier(13), 10.95, places=9)

    def test_level_18_is_exactly_17(self) -> None:
        # 17 * (0.7025 + 0.0175*17) = 17 * 1.0 = 17.0  (endpoint identity)
        self.assertAlmostEqual(growth_multiplier(18), 17.0, places=9)

    def test_strictly_monotonic_increasing(self) -> None:
        vals = [growth_multiplier(n) for n in range(1, 19)]
        self.assertTrue(all(b > a for a, b in zip(vals, vals[1:])))

    def test_strictly_below_linear_between_endpoints(self) -> None:
        # The exact bug guard: real growth < naive (n-1) for levels 2..17.
        for n in range(2, 18):
            self.assertLess(growth_multiplier(n), float(n - 1))


class ScaledStatTests(unittest.TestCase):
    """scaled() = base + perlevel * growth_multiplier(level).

    Hand-derived against real Riot per-level base stats. The pre-fix
    ``linear`` engine produced the (higher, wrong) values noted in the
    comments; these are the corrected in-game values.
    """

    def test_level_1_returns_base(self) -> None:
        self.assertEqual(scaled(690, 98, 1), 690.0)

    def test_garen_hp_level_6(self) -> None:
        # Garen HP base 690, perlevel 98.
        # 690 + 98 * 3.95 = 1077.1   (DS-linear was 1180)
        self.assertAlmostEqual(scaled(690, 98, 6), 1077.1, places=4)

    def test_garen_hp_level_11(self) -> None:
        # 690 + 98 * 8.775 = 1549.95  (DS-linear was 1670)
        self.assertAlmostEqual(scaled(690, 98, 11), 1549.95, places=4)

    def test_garen_hp_level_13(self) -> None:
        # 690 + 98 * 10.95 = 1763.1   (DS-linear was 1866)
        self.assertAlmostEqual(scaled(690, 98, 13), 1763.1, places=4)

    def test_garen_hp_level_18_endpoint_unchanged(self) -> None:
        # 690 + 98 * 17 = 2356  (endpoint identity; old linear agreed)
        self.assertAlmostEqual(scaled(690, 98, 18), 2356.0, places=4)

    def test_lux_hp_level_11(self) -> None:
        # Lux HP base 580, perlevel 99.
        # 580 + 99 * 8.775 = 1448.725  (DS-linear was 1570)
        self.assertAlmostEqual(scaled(580, 99, 11), 1448.725, places=4)

    def test_lux_hp_level_18_endpoint_unchanged(self) -> None:
        # 580 + 99 * 17 = 2263  (endpoint identity)
        self.assertAlmostEqual(scaled(580, 99, 18), 2263.0, places=4)

    def test_zero_perlevel_is_flat(self) -> None:
        # crit has critperlevel == 0 for every champion - scaled() must
        # return base at every level (no growth).
        for n in range(1, 19):
            self.assertEqual(scaled(0.0, 0.0, n), 0.0)


class AttackSpeedScalingTests(unittest.TestCase):
    """Riot AS math is already correct - this fix must NOT touch it."""

    def test_attack_speed_lvl_1_returns_base(self) -> None:
        self.assertAlmostEqual(attack_speed_scaling(0.651, 2.5, 1), 0.651, places=4)

    def test_attack_speed_lvl_18_aatrox(self) -> None:
        # 0.651 * (1 + 0.025 * 17) = 0.651 * 1.425 = 0.927675
        self.assertAlmostEqual(attack_speed_scaling(0.651, 2.5, 18), 0.927675, places=4)


class LevelGuardTests(unittest.TestCase):
    def test_below_range(self) -> None:
        with self.assertRaises(ValueError):
            clamp_level(0)

    def test_above_range(self) -> None:
        with self.assertRaises(ValueError):
            clamp_level(19)

    def test_non_int(self) -> None:
        with self.assertRaises(TypeError):
            clamp_level(5.0)  # type: ignore[arg-type]


class ItemAggregateTests(unittest.TestCase):
    def test_empty_returns_empty(self) -> None:
        self.assertEqual(aggregate_item_stats([]), {})

    def test_bloodthirster_block(self) -> None:
        # Bloodthirster (3072): +80 AD, +18% lifesteal
        block = {"FlatPhysicalDamageMod": 80, "PercentLifeStealMod": 0.18}
        out = aggregate_item_stats([block])
        self.assertEqual(out["ad_flat"], 80.0)
        self.assertAlmostEqual(out["lifesteal_pct"], 0.18)

    def test_two_items_stack_ad(self) -> None:
        # Bloodthirster + Eclipse: 80 + 60 = 140 AD
        out = aggregate_item_stats([
            {"FlatPhysicalDamageMod": 80, "PercentLifeStealMod": 0.18},
            {"FlatPhysicalDamageMod": 60},
        ])
        self.assertEqual(out["ad_flat"], 140.0)

    def test_unknown_ddragon_keys_ignored(self) -> None:
        # Phase 4 conditional keys don't crash the aggregator.
        out = aggregate_item_stats([{"PassiveSheen": True, "FlatPhysicalDamageMod": 30}])
        self.assertEqual(out, {"ad_flat": 30.0})


if __name__ == "__main__":
    unittest.main()

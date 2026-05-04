import unittest

from agents.daemon_slayer.stats import (
    aggregate_item_stats,
    attack_speed_scaling,
    clamp_level,
    linear,
)


class ScalingFormulaTests(unittest.TestCase):
    def test_linear_scaling_lvl_1_returns_base(self) -> None:
        self.assertEqual(linear(650, 114, 1), 650)

    def test_linear_scaling_lvl_18_aatrox_hp(self) -> None:
        # Aatrox: 650 + 114 * 17 = 2588
        self.assertEqual(linear(650, 114, 18), 2588)

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

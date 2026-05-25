import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import (
    DEFAULT_CRIT_BONUS,
    DPS_CURVE_LEVELS,
    DpsCurvePoint,
    _armor_factor,
    _select_phase,
    compute_dps,
    compute_dps_curve,
)
from agents.daemon_slayer.effects import ITEM_EFFECTS


class PhaseSelectionTests(unittest.TestCase):
    def test_early(self) -> None:
        self.assertEqual(_select_phase(1), "early")
        self.assertEqual(_select_phase(6), "early")

    def test_mid(self) -> None:
        self.assertEqual(_select_phase(7), "mid")
        self.assertEqual(_select_phase(12), "mid")

    def test_late(self) -> None:
        self.assertEqual(_select_phase(13), "late")
        self.assertEqual(_select_phase(18), "late")


class ArmorFactorTests(unittest.TestCase):
    def test_zero_armor_is_one(self) -> None:
        self.assertEqual(_armor_factor(0), 1.0)

    def test_100_armor_halves(self) -> None:
        self.assertAlmostEqual(_armor_factor(100), 0.5)

    def test_negative_armor_amplifies(self) -> None:
        # -100 armor -> 2 - 100/200 = 1.5
        self.assertAlmostEqual(_armor_factor(-100), 1.5)

    def test_armor_factor_parametrized_sweep(self) -> None:
        # Item 184 Phase 7 - parametrize across the +/-120 boundary
        # range to lock both branches (positive: 100/(100+a), negative:
        # 2 - 100/(100-a)) including the +/-1 / +/-99 boundaries
        # closest to the branch flip at a=0.
        cases = [
            (-120, 2.0 - 100.0 / 220.0),
            (-99,  2.0 - 100.0 / 199.0),
            (-48,  2.0 - 100.0 / 148.0),
            (-24,  2.0 - 100.0 / 124.0),
            (-1,   2.0 - 100.0 / 101.0),
            (0,    1.0),
            (1,    100.0 / 101.0),
            (24,   100.0 / 124.0),
            (48,   100.0 / 148.0),
            (99,   100.0 / 199.0),
            (120,  100.0 / 220.0),
        ]
        for armor, expected in cases:
            with self.subTest(armor=armor):
                self.assertAlmostEqual(_armor_factor(armor), expected, places=9)


class AatroxDpsBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_naked_lvl_1_early_phase(self) -> None:
        # Hand-calc verification for Aatrox lvl 1 naked, early phase:
        #   AD=60, AS=0.651, crit=0 → avg per-hit = 60
        #   Rotations:
        #     QQQ auto:  basic=1, basicTime=0, duration=3, weight=20
        #                attacks = 1 → dps = 60/3 = 20.0
        #     Major Harass: basic=2, basicTime=1, duration=6, weight=30
        #                attacks = 2 + 0.651 = 2.651 → dps = 2.651*60/6 = 26.51
        #     All-out: basic=2, basicTime=2, duration=7, weight=50
        #                attacks = 2 + 1.302 = 3.302 → dps = 3.302*60/7 = 28.30
        #   Weighted: (20*20 + 26.51*30 + 28.30*50) / 100 = 26.10
        r = compute_dps(self.snap, "Aatrox", level=1)
        self.assertEqual(r.phase, "early")
        self.assertAlmostEqual(r.weighted_dps, 26.10, places=1)
        self.assertEqual(r.mode_multiplier, 1.0)
        self.assertEqual(r.target_armor, 0.0)

    def test_phase_auto_select_lvl_11_is_mid(self) -> None:
        r = compute_dps(self.snap, "Aatrox", level=11)
        self.assertEqual(r.phase, "mid")

    def test_phase_auto_select_lvl_18_is_late(self) -> None:
        r = compute_dps(self.snap, "Aatrox", level=18)
        self.assertEqual(r.phase, "late")

    def test_explicit_phase_override(self) -> None:
        early = compute_dps(self.snap, "Aatrox", level=18, phase="early")
        late = compute_dps(self.snap, "Aatrox", level=18, phase="late")
        self.assertEqual(early.phase, "early")
        self.assertEqual(late.phase, "late")
        self.assertNotAlmostEqual(early.weighted_dps, late.weighted_dps, places=1)

    def test_invalid_phase_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_dps(self.snap, "Aatrox", level=11, phase="endgame")

    def test_invalid_level_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_dps(self.snap, "Aatrox", level=20)


class ItemImpactTests(unittest.TestCase):
    """Sanity-check that items the engine handles bump DPS in expected directions."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_bloodthirster_raises_dps_via_ad(self) -> None:
        naked = compute_dps(self.snap, "Aatrox", level=1)
        bt = compute_dps(self.snap, "Aatrox", level=1, item_ids=["3072"])
        self.assertGreater(bt.weighted_dps, naked.weighted_dps)
        # AD goes from 60 → 140 (factor 7/3); attacks/duration unchanged.
        self.assertAlmostEqual(bt.weighted_dps, naked.weighted_dps * 140 / 60, places=1)

    def test_berserkers_raises_dps_via_as(self) -> None:
        naked = compute_dps(self.snap, "Aatrox", level=1)
        zerks = compute_dps(self.snap, "Aatrox", level=1, item_ids=["3006"])
        # AS scales basicTime portion only - DPS climbs but not by AS factor flat.
        self.assertGreater(zerks.weighted_dps, naked.weighted_dps)

    def test_infinity_edge_raises_dps_via_ad_and_crit(self) -> None:
        # IE 16.9.1: +75 AD, +25% crit, +30% bonus crit damage (Phase 4 effect).
        # Combines AD bump (60→135) with crit avg factor
        # (1 + 0.25*(0.75+0.30) = 1.2625). DPS should scale ≈ 135/60 * 1.2625.
        naked = compute_dps(self.snap, "Aatrox", level=1)
        ie = compute_dps(self.snap, "Aatrox", level=1, item_ids=["3031"])
        self.assertGreater(ie.weighted_dps, naked.weighted_dps)
        self.assertAlmostEqual(ie.stats["crit"], 0.25)
        ie_crit_bonus = DEFAULT_CRIT_BONUS + ITEM_EFFECTS["3031"].crit_damage_bonus
        expected_factor = (135 / 60) * (1 + 0.25 * ie_crit_bonus)
        self.assertAlmostEqual(
            ie.weighted_dps, naked.weighted_dps * expected_factor, places=2
        )

    def test_crit_caps_at_one(self) -> None:
        # 5x IE = 125% pre-clamp → clamped to 100% in engine. Each IE also
        # stacks +30% bonus crit damage (effects.ITEM_EFFECTS), so total
        # crit_bonus = 0.75 + 5*0.30 = 2.25.
        r = compute_dps(self.snap, "Aatrox", level=1, item_ids=["3031"] * 5)
        self.assertEqual(r.stats["crit"], 1.0)
        stacked_crit_bonus = DEFAULT_CRIT_BONUS + 5 * ITEM_EFFECTS["3031"].crit_damage_bonus
        self.assertAlmostEqual(
            r.avg_attack_dmg, r.stats["ad"] * (1 + stacked_crit_bonus), places=2
        )


class TargetResistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_target_armor_scales_dps_by_armor_factor(self) -> None:
        bare = compute_dps(self.snap, "Aatrox", level=1)
        armored = compute_dps(self.snap, "Aatrox", level=1, target_armor=100.0)
        # 100 armor → factor 0.5
        self.assertAlmostEqual(armored.weighted_dps, bare.weighted_dps * 0.5, places=2)

    def test_negative_armor_amplifies(self) -> None:
        bare = compute_dps(self.snap, "Aatrox", level=1)
        shred = compute_dps(self.snap, "Aatrox", level=1, target_armor=-100.0)
        self.assertAlmostEqual(shred.weighted_dps, bare.weighted_dps * 1.5, places=2)


class ModeMultiplierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_aatrox_aram_applies_dmg_dealt(self) -> None:
        sr = compute_dps(self.snap, "Aatrox", level=11, mode="SR")
        aram = compute_dps(self.snap, "Aatrox", level=11, mode="ARAM")
        # Aatrox aramDamageDealt = 1.05 (snapshot 16.9.1)
        self.assertAlmostEqual(aram.mode_multiplier, 1.05)
        self.assertAlmostEqual(aram.weighted_dps, sr.weighted_dps * 1.05, places=2)
        self.assertTrue(any("aramDamageDealt" in n for n in aram.notes))

    def test_yunara_aram_zero_multiplier_zeros_dps(self) -> None:
        # Yunara aramDamageDealt = 0 in 16.9.1 - hard ARAM disable
        aram = compute_dps(self.snap, "Yunara", level=11, mode="ARAM")
        self.assertEqual(aram.mode_multiplier, 0.0)
        self.assertEqual(aram.weighted_dps, 0.0)
        self.assertEqual(aram.avg_attack_dmg, 0.0)
        # raw_attack_dps is mode-independent (sanity context number)
        self.assertGreater(aram.raw_attack_dps, 0.0)

    def test_unknown_mode_does_not_break(self) -> None:
        # ARENA is not yet wired; should fall through to default 1.0 mult + a note
        r = compute_dps(self.snap, "Aatrox", level=11, mode="ARENA")
        self.assertEqual(r.mode_multiplier, 1.0)


class SerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_to_dict_contains_phase_and_components(self) -> None:
        r = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3006"])
        d = r.to_dict()
        self.assertEqual(d["champion_id"], "Aatrox")
        self.assertEqual(d["level"], 11)
        self.assertEqual(d["item_ids"], ["3006"])
        self.assertEqual(d["phase"], "mid")
        for p in ("early", "mid", "late"):
            self.assertIn(p, d["phase_dps"])
        self.assertIn("ad", d["stats"])

    def test_format_table_contains_key_fields(self) -> None:
        r = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3006"])
        table = r.format_table()
        self.assertIn("Aatrox", table)
        self.assertIn("lvl 11", table)
        self.assertIn("3006", table)
        self.assertIn("weighted_dps", table)
        self.assertIn("mid", table)


class DpsCurveTests(unittest.TestCase):
    """Phase 6 step 7 - per-level DPS curve helper."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_levels_returns_five_points(self) -> None:
        curve = compute_dps_curve(self.snap, "Aatrox")
        self.assertEqual(len(curve), 5)
        self.assertEqual(tuple(p.level for p in curve), DPS_CURVE_LEVELS)

    def test_each_point_is_dataclass(self) -> None:
        curve = compute_dps_curve(self.snap, "Aatrox")
        for p in curve:
            self.assertIsInstance(p, DpsCurvePoint)
            self.assertIn("ad", p.stats)
            self.assertIn("as", p.stats)
            self.assertIn("crit", p.stats)
            self.assertIn("ap", p.stats)

    def test_phase_progression_across_default_levels(self) -> None:
        # Phase auto-derive: 1=early, 6=early, 11=mid, 16=late, 18=late.
        curve = compute_dps_curve(self.snap, "Aatrox")
        phases = [p.phase for p in curve]
        self.assertEqual(phases, ["early", "early", "mid", "late", "late"])

    def test_naked_ad_grows_monotonically(self) -> None:
        # AD per-level is positive for Aatrox; bare build → AD strictly
        # increases at each sampled level.
        curve = compute_dps_curve(self.snap, "Aatrox")
        ads = [p.stats["ad"] for p in curve]
        for prev, cur in zip(ads, ads[1:]):
            self.assertGreater(cur, prev)

    def test_dps_at_18_with_ie_exceeds_naked_lvl_1(self) -> None:
        # Sanity: lvl 18 + Infinity Edge is strictly higher DPS than
        # lvl 1 naked. (Not testing the whole curve is monotonic - late-
        # phase rotations weight differently, so weighted DPS can dip on
        # phase transitions; this is the safe inequality.)
        curve = compute_dps_curve(self.snap, "Aatrox", item_ids=["3031"])
        self.assertGreater(curve[-1].weighted_dps, curve[0].weighted_dps)

    def test_custom_levels_subset(self) -> None:
        curve = compute_dps_curve(self.snap, "Aatrox", levels=(3, 9))
        self.assertEqual(len(curve), 2)
        self.assertEqual(curve[0].level, 3)
        self.assertEqual(curve[1].level, 9)
        self.assertEqual(curve[0].phase, "early")
        self.assertEqual(curve[1].phase, "mid")

    def test_invalid_level_raises(self) -> None:
        with self.assertRaises(ValueError):
            compute_dps_curve(self.snap, "Aatrox", levels=(0,))
        with self.assertRaises(ValueError):
            compute_dps_curve(self.snap, "Aatrox", levels=(19,))

    def test_items_thread_through(self) -> None:
        bare = compute_dps_curve(self.snap, "Aatrox")
        with_bt = compute_dps_curve(self.snap, "Aatrox", item_ids=["3072"])
        # Bloodthirster (+80 AD) lifts AD at every sample level.
        for b, w in zip(bare, with_bt):
            self.assertGreater(w.stats["ad"], b.stats["ad"])
            self.assertGreater(w.weighted_dps, b.weighted_dps)

    def test_aram_mode_threads_through(self) -> None:
        sr = compute_dps_curve(self.snap, "Aatrox", mode="SR")
        aram = compute_dps_curve(self.snap, "Aatrox", mode="ARAM")
        # Aatrox aramDamageDealt = 1.05 → each level's DPS is 1.05x of SR.
        for s, a in zip(sr, aram):
            self.assertAlmostEqual(a.weighted_dps, s.weighted_dps * 1.05, places=1)

    def test_arena_augment_threads_through(self) -> None:
        bare = compute_dps_curve(self.snap, "Aatrox", mode="ARENA")
        with_aug = compute_dps_curve(
            self.snap, "Aatrox", mode="ARENA",
            augments=["TheBrutalizer"],
        )
        # +20 AD from TheBrutalizer must lift every sample's AD by 20 flat.
        for b, w in zip(bare, with_aug):
            self.assertAlmostEqual(w.stats["ad"] - b.stats["ad"], 20.0, places=1)
            self.assertGreater(w.weighted_dps, b.weighted_dps)

    def test_to_dict_round_trip(self) -> None:
        curve = compute_dps_curve(self.snap, "Aatrox", levels=(11,))
        d = curve[0].to_dict()
        self.assertEqual(d["level"], 11)
        self.assertEqual(d["phase"], "mid")
        self.assertIn("ad", d["stats"])

    def test_duplicate_levels_honored(self) -> None:
        # No dedup - caller controls sample density.
        curve = compute_dps_curve(self.snap, "Aatrox", levels=(6, 6, 11))
        self.assertEqual(len(curve), 3)
        self.assertAlmostEqual(curve[0].weighted_dps, curve[1].weighted_dps)


if __name__ == "__main__":
    unittest.main()

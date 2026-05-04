import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import (
    DEFAULT_CRIT_BONUS,
    _armor_factor,
    _select_phase,
    compute_dps,
)


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
        # -100 armor → 2 - 100/200 = 1.5
        self.assertAlmostEqual(_armor_factor(-100), 1.5)


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
        # AS scales basicTime portion only — DPS climbs but not by AS factor flat.
        self.assertGreater(zerks.weighted_dps, naked.weighted_dps)

    def test_infinity_edge_raises_dps_via_ad_and_crit(self) -> None:
        # IE 16.9.1: +75 AD, +25% crit. Combines AD bump (60→135) with crit avg
        # factor (1 + 0.25*0.75 = 1.1875). DPS should scale ≈ 135/60 * 1.1875.
        naked = compute_dps(self.snap, "Aatrox", level=1)
        ie = compute_dps(self.snap, "Aatrox", level=1, item_ids=["3031"])
        self.assertGreater(ie.weighted_dps, naked.weighted_dps)
        self.assertAlmostEqual(ie.stats["crit"], 0.25)
        expected_factor = (135 / 60) * (1 + 0.25 * 0.75)
        self.assertAlmostEqual(
            ie.weighted_dps, naked.weighted_dps * expected_factor, places=2
        )

    def test_crit_caps_at_one(self) -> None:
        # 5x IE = 125% pre-clamp → clamped to 100% in engine
        r = compute_dps(self.snap, "Aatrox", level=1, item_ids=["3031"] * 5)
        self.assertEqual(r.stats["crit"], 1.0)
        # avg per-hit factor = 1 + 1.0 * 0.75 = 1.75
        self.assertAlmostEqual(
            r.avg_attack_dmg, r.stats["ad"] * (1 + DEFAULT_CRIT_BONUS), places=2
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
        # Yunara aramDamageDealt = 0 in 16.9.1 — hard ARAM disable
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


if __name__ == "__main__":
    unittest.main()

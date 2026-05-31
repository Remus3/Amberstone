"""Tests for self_shred.py - target_shred -> self-DPS-uplift consumer.

Grounded against patch 16.11.1 champion_abilities.json:
  * Nasus E "Armor Reduction" pct [30,35,40,45,50] (% of target's armor)
  * Corki E "Total Resistances Reduction" flat [12,14,16,18,20]
  * Evelynn W "Magic Resistance Reduction" pct [35,37.5,40,42.5,45]
  * Trundle Q "Attack Damage Reduction" - NOT a mitigation resist (skipped)

The mitigation curve (dps._armor_factor) is the single source of truth;
these tests pin the uplift mechanism + selection + fail-soft contract.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.dps import _armor_factor
from agents.daemon_slayer.self_shred import (
    RESIST_ARMOR,
    RESIST_MR,
    SelfShredUplift,
    compute_self_shred_uplift,
)


class NasusPctShredTests(unittest.TestCase):
    """Nasus E armor pct shred raises mit factor + yields positive uplift."""

    def test_nasus_uplift_is_positive_and_mit_rises(self):
        r = compute_self_shred_uplift(
            "Nasus", 18, target_armor=100.0, target_mr=50.0,
            champion_physical_dps=200.0,
        )
        self.assertEqual(r.shred_source, "Nasus:E")
        self.assertEqual(r.resist_kind, RESIST_ARMOR)
        self.assertGreater(r.new_mit_factor, r.old_mit_factor)
        self.assertGreater(r.dps_uplift_pct, 0.0)

    def test_nasus_rank5_100armor_hand_computed_pin(self):
        # Rank 5 = 50% armor pct shred. 100 armor -> shredded 50.
        # old = 100/200 = 0.5 ; new = 100/150 = 0.6666... ; uplift = +33.333%.
        r = compute_self_shred_uplift(
            "Nasus", 18, target_armor=100.0, target_mr=50.0,
            champion_physical_dps=200.0,
        )
        self.assertEqual(r.pct_shred, 0.5)
        self.assertEqual(r.flat_shred, 0.0)
        self.assertAlmostEqual(r.target_resist, 100.0, places=6)
        self.assertAlmostEqual(r.old_mit_factor, 0.5, places=6)
        self.assertAlmostEqual(r.new_mit_factor, 100.0 / 150.0, places=6)
        self.assertAlmostEqual(r.dps_uplift_pct, 33.3333333, places=4)
        # abs uplift = 200 * (new/old - 1) = 200 * 0.33333 = 66.666...
        self.assertAlmostEqual(r.dps_uplift_abs, 200.0 * (1.0 / 3.0), places=4)

    def test_nasus_uplift_pct_matches_armor_factor_directly(self):
        # Independent re-derivation of the same number from _armor_factor.
        r = compute_self_shred_uplift(
            "Nasus", 18, target_armor=120.0, target_mr=0.0,
            champion_physical_dps=100.0,
        )
        shredded = 120.0 - 120.0 * 0.5  # rank5 50%
        expected = (_armor_factor(shredded) / _armor_factor(120.0) - 1.0) * 100.0
        self.assertAlmostEqual(r.dps_uplift_pct, expected, places=6)


class NoShredFailSoftTests(unittest.TestCase):
    """Champions with no modeled shred -> 0.0 uplift, note, no raise."""

    def test_annie_no_shred(self):
        r = compute_self_shred_uplift(
            "Annie", 18, target_armor=100.0, target_mr=50.0,
            champion_physical_dps=200.0,
        )
        self.assertEqual(r.dps_uplift_pct, 0.0)
        self.assertEqual(r.dps_uplift_abs, 0.0)
        self.assertEqual(r.shred_source, "")
        self.assertEqual(r.resist_kind, "")
        self.assertTrue(r.notes)

    def test_unknown_champion_fail_soft(self):
        r = compute_self_shred_uplift(
            "NotAChampion", 18, target_armor=100.0, target_mr=50.0,
            champion_physical_dps=200.0,
        )
        self.assertEqual(r.dps_uplift_pct, 0.0)
        self.assertEqual(r.shred_source, "")
        self.assertTrue(r.notes)

    def test_blank_champion_fail_soft(self):
        r = compute_self_shred_uplift(
            "", 18, target_armor=100.0, target_mr=50.0,
            champion_physical_dps=200.0,
        )
        self.assertEqual(r.dps_uplift_pct, 0.0)
        self.assertTrue(r.notes)

    def test_ad_reduction_shred_is_skipped(self):
        # Trundle Q is an Attack Damage Reduction shred - reduces the
        # target's OUTGOING damage, not a mitigation resist. No uplift.
        r = compute_self_shred_uplift(
            "Trundle", 18, target_armor=100.0, target_mr=50.0,
            champion_physical_dps=200.0,
        )
        self.assertEqual(r.dps_uplift_pct, 0.0)
        self.assertEqual(r.shred_source, "")

    def test_no_raise_on_garbage_level(self):
        # Non-int level coerces to 1, never raises.
        r = compute_self_shred_uplift(
            "Nasus", None, target_armor=100.0, target_mr=50.0,  # type: ignore[arg-type]
            champion_physical_dps=200.0,
        )
        self.assertEqual(r.level, 1)
        self.assertIsInstance(r, SelfShredUplift)


class MonotonicityTests(unittest.TestCase):
    """More shred -> higher uplift; higher base resist -> higher uplift."""

    def test_more_shred_higher_uplift(self):
        # Nasus E (50% rank5) vs Yorick E (25% rank5) at identical 100 armor.
        # Stronger pct shred must produce a strictly larger uplift.
        nasus = compute_self_shred_uplift(
            "Nasus", 18, target_armor=100.0, target_mr=50.0,
            champion_physical_dps=200.0,
        )
        yorick = compute_self_shred_uplift(
            "Yorick", 18, target_armor=100.0, target_mr=50.0,
            champion_physical_dps=200.0,
        )
        self.assertGreater(nasus.pct_shred, yorick.pct_shred)
        self.assertGreater(nasus.dps_uplift_pct, yorick.dps_uplift_pct)

    def test_pct_shred_higher_base_armor_higher_abs_gain(self):
        # PCT shred (Nasus E 50%): a fixed-percentage shred removes more
        # resist points off a higher base armor, so the absolute
        # mitigation-factor gain (new - old) grows with base armor.
        lo = compute_self_shred_uplift(
            "Nasus", 18, target_armor=60.0, target_mr=0.0,
            champion_physical_dps=200.0,
        )
        hi = compute_self_shred_uplift(
            "Nasus", 18, target_armor=200.0, target_mr=0.0,
            champion_physical_dps=200.0,
        )
        self.assertEqual(lo.pct_shred, 0.5)
        self.assertEqual(hi.pct_shred, 0.5)
        lo_gain = lo.new_mit_factor - lo.old_mit_factor
        hi_gain = hi.new_mit_factor - hi.old_mit_factor
        self.assertGreater(hi_gain, lo_gain)

    def test_flat_shred_lower_base_armor_higher_pct_uplift(self):
        # FLAT shred (Corki E 20 resist points at rank5): a fixed flat
        # shred is a LARGER fraction of a SMALLER base resist, so the
        # percent uplift is higher off lower base armor (the honest
        # direction - a flat 20 off 40 armor matters far more than off
        # 200 armor).
        lo = compute_self_shred_uplift(
            "Corki", 18, target_armor=60.0, target_mr=0.0,
            champion_physical_dps=200.0,
        )
        hi = compute_self_shred_uplift(
            "Corki", 18, target_armor=200.0, target_mr=0.0,
            champion_physical_dps=200.0,
        )
        self.assertEqual(lo.flat_shred, 20.0)
        self.assertEqual(hi.flat_shred, 20.0)
        self.assertGreater(lo.dps_uplift_pct, hi.dps_uplift_pct)

    def test_higher_rank_not_smaller_uplift(self):
        # Nasus E at higher level (higher rank, larger pct) yields >= uplift
        # vs a lower level on the same target.
        low = compute_self_shred_uplift(
            "Nasus", 1, target_armor=100.0, target_mr=0.0,
            champion_physical_dps=200.0,
        )
        high = compute_self_shred_uplift(
            "Nasus", 18, target_armor=100.0, target_mr=0.0,
            champion_physical_dps=200.0,
        )
        self.assertGreaterEqual(high.dps_uplift_pct, low.dps_uplift_pct)
        self.assertGreater(high.pct_shred, low.pct_shred)


class FlatShredTests(unittest.TestCase):
    """Corki flat resist shred routes through flat_shred, picks Total."""

    def test_corki_flat_shred_picks_total_block(self):
        # Corki E ships a per-stack (5 rank5) + Total (20 rank5) block.
        # Selection by max-uplift must land on the larger Total magnitude.
        r = compute_self_shred_uplift(
            "Corki", 18, target_armor=100.0, target_mr=0.0,
            champion_physical_dps=200.0,
        )
        self.assertEqual(r.shred_source, "Corki:E")
        self.assertEqual(r.flat_shred, 20.0)
        self.assertEqual(r.pct_shred, 0.0)
        # 100 armor - 20 flat = 80 ; old 0.5, new 100/180.
        self.assertAlmostEqual(r.old_mit_factor, 0.5, places=6)
        self.assertAlmostEqual(r.new_mit_factor, 100.0 / 180.0, places=6)


class MrShredChannelTests(unittest.TestCase):
    """MR shred routes through the magic channel + target_mr."""

    def test_evelynn_mr_shred_uses_magic_dps(self):
        r = compute_self_shred_uplift(
            "Evelynn", 18, target_armor=100.0, target_mr=60.0,
            champion_physical_dps=0.0, champion_magic_dps=300.0,
        )
        self.assertEqual(r.shred_source, "Evelynn:W")
        self.assertEqual(r.resist_kind, RESIST_MR)
        self.assertAlmostEqual(r.target_resist, 60.0, places=6)
        # rank5 = 45% MR shred. 60 MR -> 33. old 100/160, new 100/133.
        self.assertEqual(r.pct_shred, 0.45)
        expected_old = _armor_factor(60.0)
        expected_new = _armor_factor(60.0 - 60.0 * 0.45)
        self.assertAlmostEqual(r.old_mit_factor, expected_old, places=6)
        self.assertAlmostEqual(r.new_mit_factor, expected_new, places=6)
        # abs uplift scales the MAGIC channel, not physical.
        self.assertAlmostEqual(
            r.dps_uplift_abs,
            300.0 * (expected_new / expected_old - 1.0),
            places=4,
        )

    def test_mr_shred_ignores_physical_dps(self):
        # Passing only physical DPS to an MR-shred champ -> abs uplift 0.0
        # (no magic DPS to amplify) but pct still computed.
        r = compute_self_shred_uplift(
            "Evelynn", 18, target_armor=100.0, target_mr=60.0,
            champion_physical_dps=500.0, champion_magic_dps=0.0,
        )
        self.assertEqual(r.resist_kind, RESIST_MR)
        self.assertGreater(r.dps_uplift_pct, 0.0)
        self.assertEqual(r.dps_uplift_abs, 0.0)


class OverShredFloorTests(unittest.TestCase):
    """Shred exceeding the resist floors shredded armor at 0, never neg."""

    def test_shred_exceeding_armor_floors_at_zero(self):
        # Corki flat 20 shred against a 5-armor target -> shredded would be
        # -15; must floor to 0 (mit factor 1.0), never enter the neg-armor
        # amp branch (>1.0).
        r = compute_self_shred_uplift(
            "Corki", 18, target_armor=5.0, target_mr=0.0,
            champion_physical_dps=200.0,
        )
        # new mit factor is exactly armor_factor(0) == 1.0, not >1.0.
        self.assertAlmostEqual(r.new_mit_factor, 1.0, places=6)
        self.assertLessEqual(r.new_mit_factor, 1.0)

    def test_pct_shred_never_negative_resist(self):
        # Nasus 50% off a 10-armor target -> shredded 5 (still positive),
        # mit factor stays < 1.0; sanity that pct never drives below 0.
        r = compute_self_shred_uplift(
            "Nasus", 18, target_armor=10.0, target_mr=0.0,
            champion_physical_dps=200.0,
        )
        shredded = 10.0 - 10.0 * 0.5  # 5
        self.assertAlmostEqual(r.new_mit_factor, _armor_factor(shredded), places=6)
        self.assertLess(r.new_mit_factor, 1.0)

    def test_zero_armor_target_no_negative_uplift(self):
        # Target already at 0 armor -> shredding does nothing (old==new==1.0),
        # uplift floored at 0.0 (no negative uplift from a no-op shred).
        r = compute_self_shred_uplift(
            "Nasus", 18, target_armor=0.0, target_mr=0.0,
            champion_physical_dps=200.0,
        )
        self.assertAlmostEqual(r.old_mit_factor, 1.0, places=6)
        self.assertAlmostEqual(r.new_mit_factor, 1.0, places=6)
        self.assertEqual(r.dps_uplift_pct, 0.0)
        self.assertEqual(r.dps_uplift_abs, 0.0)


class ToDictTests(unittest.TestCase):
    """to_dict round-trips every field."""

    def test_to_dict_has_all_fields(self):
        r = compute_self_shred_uplift(
            "Nasus", 18, target_armor=100.0, target_mr=50.0,
            champion_physical_dps=200.0,
        )
        d = r.to_dict()
        for k in (
            "champion", "level", "shred_source", "flat_shred", "pct_shred",
            "resist_kind", "target_resist", "old_mit_factor",
            "new_mit_factor", "dps_uplift_pct", "dps_uplift_abs", "notes",
        ):
            self.assertIn(k, d)
        self.assertEqual(d["champion"], "Nasus")
        self.assertEqual(d["shred_source"], "Nasus:E")


class AsciiHygieneTests(unittest.TestCase):
    """Module + test file carry zero non-ASCII bytes."""

    def test_module_is_ascii(self):
        from pathlib import Path
        import agents.daemon_slayer.self_shred as mod
        raw = Path(mod.__file__).read_bytes()
        non_ascii = [b for b in raw if b > 127]
        self.assertEqual(non_ascii, [], "self_shred.py has non-ASCII bytes")

    def test_test_file_is_ascii(self):
        from pathlib import Path
        raw = Path(__file__).read_bytes()
        non_ascii = [b for b in raw if b > 127]
        self.assertEqual(non_ascii, [], "test_self_shred.py has non-ASCII bytes")


if __name__ == "__main__":
    unittest.main()

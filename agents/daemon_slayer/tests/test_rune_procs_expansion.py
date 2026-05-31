"""Tests for the DS V2 rune-proc S4 expansion (8 -> 14 runes).

Six new runes are added to agents/daemon_slayer/rune_procs.py, every
coefficient verbatim from live DDragon 16.11.1 runesReforged.json:

  8214 Summon Aery     (Sorcery,     on_proc_burst)
  8437 Grasp           (Resolve,     on_proc_burst, caster max HP)
  8439 Aftershock      (Resolve,     on_proc_burst)
  8369 First Strike    (Inspiration, stacking_amp 1.07)
  8014 Coup de Grace   (Precision,   stacking_amp 1.08)
  8017 Cut Down        (Precision,   stacking_amp 1.08)

DDragon id crossing (the WAKEUP brief crossed two ids): the live
runesReforged.json maps 8299 -> Last Stand, 8014 -> Coup de Grace,
8017 -> Cut Down. These tests pin the DDragon-authoritative ids.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer import rune_procs as rp
from agents.daemon_slayer.rune_procs import (
    RUNE_PROCS,
    compute_rune_proc_damage,
    keystone_amp,
)


def _lerp(low, high, level):
    """Mirror the module's 1..18 17-step ramp for hand-recompute."""
    lvl = max(1, min(18, int(level)))
    return low + (high - low) * (lvl - 1) / 17.0


class RegistrySizeTests(unittest.TestCase):
    def test_registry_has_14_entries(self):
        self.assertEqual(len(RUNE_PROCS), 14)

    def test_original_eight_unchanged(self):
        # The 8 original runes from item 226 must still be present.
        for rid in (8112, 8128, 8229, 8143, 8126, 8237, 8005, 8010):
            self.assertIn(rid, RUNE_PROCS)
        # Spot-check Electrocute still computes its 70-240 base.
        self.assertAlmostEqual(
            compute_rune_proc_damage(8112, level=18, ad=0.0, ap=0.0),
            240.0,
            places=4,
        )

    def test_six_new_runes_present(self):
        for rid in (8214, 8437, 8439, 8369, 8014, 8017):
            self.assertIn(rid, RUNE_PROCS)

    def test_id_crossing_documented_correctly(self):
        # DDragon: 8014 = Coup de Grace, 8017 = Cut Down. 8299 (Last Stand)
        # must NOT be in the registry (it is not modeled).
        self.assertEqual(RUNE_PROCS[8014].name, "Coup de Grace")
        self.assertEqual(RUNE_PROCS[8017].name, "Cut Down")
        self.assertNotIn(8299, RUNE_PROCS)


class SummonAeryTests(unittest.TestCase):
    # DDragon 16.11.1: "10 - 50 based on level (+0.05 AP) (+0.1 bonus AD)".
    def test_level1_base_no_stats(self):
        self.assertAlmostEqual(
            compute_rune_proc_damage(8214, level=1, ad=0.0, ap=0.0),
            10.0,
            places=4,
        )

    def test_level18_base_no_stats(self):
        self.assertAlmostEqual(
            compute_rune_proc_damage(8214, level=18, ad=0.0, ap=0.0),
            50.0,
            places=4,
        )

    def test_adaptive_ad_dominant(self):
        # ad=100 ap=20 -> AD wins -> +0.10*100 = 10; base 10 -> 20.
        got = compute_rune_proc_damage(8214, level=1, ad=100.0, ap=20.0)
        self.assertAlmostEqual(got, 10.0 + 10.0, places=4)

    def test_adaptive_ap_dominant(self):
        # ad=10 ap=200 -> AP wins -> +0.05*200 = 10; base 10 -> 20.
        got = compute_rune_proc_damage(8214, level=1, ad=10.0, ap=200.0)
        self.assertAlmostEqual(got, 10.0 + 10.0, places=4)

    def test_midlevel_lerp(self):
        base = _lerp(10.0, 50.0, 9)
        got = compute_rune_proc_damage(8214, level=9, ad=0.0, ap=0.0)
        self.assertAlmostEqual(got, base, places=4)

    def test_proc_type_and_tree(self):
        self.assertEqual(RUNE_PROCS[8214].proc_type, "on_proc_burst")
        self.assertEqual(RUNE_PROCS[8214].tree, "Sorcery")


class GraspTests(unittest.TestCase):
    # DDragon 16.11.1: "3.5% of your max health" magic damage.
    def test_caster_max_hp_2000(self):
        # 0.035 * 2000 = 70.
        got = compute_rune_proc_damage(8437, level=1, caster_max_hp=2000.0)
        self.assertAlmostEqual(got, 70.0, places=4)

    def test_caster_max_hp_zero(self):
        got = compute_rune_proc_damage(8437, level=10, caster_max_hp=0.0)
        self.assertAlmostEqual(got, 0.0, places=4)

    def test_caster_max_hp_missing_is_zero(self):
        # No caster_max_hp passed -> defaults to 0.0, never raises.
        got = compute_rune_proc_damage(8437, level=10)
        self.assertAlmostEqual(got, 0.0, places=4)

    def test_proc_type_and_tree(self):
        self.assertEqual(RUNE_PROCS[8437].proc_type, "on_proc_burst")
        self.assertEqual(RUNE_PROCS[8437].tree, "Resolve")

    def test_cooldown_is_4s(self):
        self.assertAlmostEqual(RUNE_PROCS[8437].cooldown_s, 4.0, places=4)


class AftershockTests(unittest.TestCase):
    # DDragon 16.11.1: "25 - 120 (+8% of your bonus health)".
    def test_level1_no_bonus_hp(self):
        got = compute_rune_proc_damage(8439, level=1, bonus_hp=0.0)
        self.assertAlmostEqual(got, 25.0, places=4)

    def test_level18_no_bonus_hp(self):
        got = compute_rune_proc_damage(8439, level=18, bonus_hp=0.0)
        self.assertAlmostEqual(got, 120.0, places=4)

    def test_level1_with_bonus_hp(self):
        # base 25 + 0.08 * 1000 = 25 + 80 = 105.
        got = compute_rune_proc_damage(8439, level=1, bonus_hp=1000.0)
        self.assertAlmostEqual(got, 25.0 + 80.0, places=4)

    def test_proc_type_and_tree(self):
        self.assertEqual(RUNE_PROCS[8439].proc_type, "on_proc_burst")
        self.assertEqual(RUNE_PROCS[8439].tree, "Resolve")

    def test_cooldown_is_20s(self):
        self.assertAlmostEqual(RUNE_PROCS[8439].cooldown_s, 20.0, places=4)


class FirstStrikeTests(unittest.TestCase):
    # DDragon 16.11.1: "7% extra true damage against champions" (amp).
    def test_compute_returns_zero(self):
        # Pure amp; no burst piece.
        self.assertAlmostEqual(
            compute_rune_proc_damage(8369, level=18, ad=999, ap=999),
            0.0,
            places=4,
        )

    def test_amp_multiplies_1_07(self):
        # 7% amp -> 100 * 1.07 = 107.
        self.assertAlmostEqual(keystone_amp(8369, 100.0), 107.0, places=4)

    def test_proc_type_tree_cooldown(self):
        self.assertEqual(RUNE_PROCS[8369].proc_type, "stacking_amp")
        self.assertEqual(RUNE_PROCS[8369].tree, "Inspiration")
        self.assertAlmostEqual(RUNE_PROCS[8369].cooldown_s, 25.0, places=4)

    def test_amp_mult_field(self):
        self.assertAlmostEqual(RUNE_PROCS[8369].amp_mult, 1.07, places=4)


class CoupDeGraceTests(unittest.TestCase):
    # DDragon 16.11.1: "8% more damage to champions below 40% health".
    def test_compute_returns_zero(self):
        self.assertAlmostEqual(
            compute_rune_proc_damage(8014, level=18, ad=999, ap=999),
            0.0,
            places=4,
        )

    def test_amp_multiplies_1_08(self):
        self.assertAlmostEqual(keystone_amp(8014, 100.0), 108.0, places=4)

    def test_proc_type_tree(self):
        self.assertEqual(RUNE_PROCS[8014].proc_type, "stacking_amp")
        self.assertEqual(RUNE_PROCS[8014].tree, "Precision")

    def test_amp_mult_field(self):
        self.assertAlmostEqual(RUNE_PROCS[8014].amp_mult, 1.08, places=4)


class CutDownTests(unittest.TestCase):
    # DDragon 16.11.1: "8% more damage to champions above 60% health".
    def test_compute_returns_zero(self):
        self.assertAlmostEqual(
            compute_rune_proc_damage(8017, level=18, ad=999, ap=999),
            0.0,
            places=4,
        )

    def test_amp_multiplies_1_08(self):
        self.assertAlmostEqual(keystone_amp(8017, 100.0), 108.0, places=4)

    def test_proc_type_tree(self):
        self.assertEqual(RUNE_PROCS[8017].proc_type, "stacking_amp")
        self.assertEqual(RUNE_PROCS[8017].tree, "Precision")

    def test_amp_mult_field(self):
        self.assertAlmostEqual(RUNE_PROCS[8017].amp_mult, 1.08, places=4)


class NewRuneFailSoftTests(unittest.TestCase):
    def test_grasp_bad_caster_hp(self):
        got = compute_rune_proc_damage(8437, level=1, caster_max_hp=None)
        self.assertAlmostEqual(got, 0.0, places=4)

    def test_aftershock_bad_bonus_hp(self):
        got = compute_rune_proc_damage(8439, level=1, bonus_hp=None)
        self.assertAlmostEqual(got, 25.0, places=4)

    def test_amp_runs_passthrough_on_bad_base(self):
        # keystone_amp fails soft to 0.0 on non-numeric base.
        self.assertEqual(keystone_amp(8369, "nope"), 0.0)
        self.assertEqual(keystone_amp(8014, "nope"), 0.0)
        self.assertEqual(keystone_amp(8017, "nope"), 0.0)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self):
        with open(rp.__file__, "rb") as fh:
            raw = fh.read()
        non_ascii = [b for b in raw if b > 0x7F]
        self.assertEqual(
            non_ascii, [], "rune_procs.py must contain 0 non-ASCII bytes"
        )

    def test_test_module_is_ascii(self):
        with open(__file__, "rb") as fh:
            raw = fh.read()
        non_ascii = [b for b in raw if b > 0x7F]
        self.assertEqual(
            non_ascii, [], "this test module must contain 0 non-ASCII bytes"
        )


if __name__ == "__main__":
    unittest.main()

"""Tests for the DS V2 rune-proc layer (agents/daemon_slayer/rune_procs.py).

Coefficients are recomputed by hand here from the live DDragon 16.11.1
longDesc values (the module's documented source of truth). The module
intentionally diverges from the DS_V2 brief where the brief's numbers were
stale; these tests pin the DDragon-authoritative values.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer import rune_procs as rp
from agents.daemon_slayer.rune_procs import (
    RUNE_PROCS,
    RuneProc,
    compute_rune_proc_damage,
    keystone_amp,
)


def _lerp(low, high, level):
    """Mirror the module's 1..18 17-step ramp for hand-recompute."""
    lvl = max(1, min(18, int(level)))
    return low + (high - low) * (lvl - 1) / 17.0


class RegistryShapeTests(unittest.TestCase):
    def test_keys_are_valid_ints(self):
        self.assertTrue(RUNE_PROCS)
        for k in RUNE_PROCS:
            self.assertIsInstance(k, int)
            self.assertGreater(k, 0)

    def test_values_are_runeproc_with_matching_id(self):
        for k, v in RUNE_PROCS.items():
            self.assertIsInstance(v, RuneProc)
            self.assertEqual(v.rune_id, k)
            self.assertIsInstance(v.name, str)
            self.assertTrue(v.name)
            self.assertIsInstance(v.formula, str)
            self.assertTrue(v.formula)

    def test_proc_types_are_known(self):
        known = {"on_proc_burst", "per_attack", "stacking_amp", "adaptive"}
        for v in RUNE_PROCS.values():
            self.assertIn(v.proc_type, known)

    def test_trees_are_real(self):
        trees = {"Domination", "Inspiration", "Precision", "Resolve", "Sorcery"}
        for v in RUNE_PROCS.values():
            self.assertIn(v.tree, trees)

    def test_expected_runes_present(self):
        for rid in (8112, 8128, 8229, 8143, 8126, 8237, 8005, 8010):
            self.assertIn(rid, RUNE_PROCS)


class ElectrocuteTests(unittest.TestCase):
    # 70-240 by level + 0.10 bonus AD + 0.05 AP (adaptive).
    def test_level1_ad_dominant(self):
        # level 1 base = 70; ad=100 ap=20 -> AD wins -> +0.10*100 = 10.
        got = compute_rune_proc_damage(8112, level=1, ad=100.0, ap=20.0)
        self.assertAlmostEqual(got, 70.0 + 10.0, places=4)

    def test_level18_base(self):
        got = compute_rune_proc_damage(8112, level=18, ad=0.0, ap=0.0)
        self.assertAlmostEqual(got, 240.0, places=4)

    def test_midlevel_lerp(self):
        base = _lerp(70.0, 240.0, 9)
        got = compute_rune_proc_damage(8112, level=9, ad=0.0, ap=0.0)
        self.assertAlmostEqual(got, base, places=4)


class DarkHarvestTests(unittest.TestCase):
    # 30 + 11*souls + 0.10 bonus AD + 0.05 AP.
    def test_no_souls_ap_dominant(self):
        # ad=10 ap=200 -> AP wins -> +0.05*200 = 10. souls=0.
        got = compute_rune_proc_damage(8128, level=1, ad=10.0, ap=200.0)
        self.assertAlmostEqual(got, 30.0 + 10.0, places=4)

    def test_souls_stack(self):
        got = compute_rune_proc_damage(8128, level=5, ad=0.0, ap=0.0, souls=7)
        self.assertAlmostEqual(got, 30.0 + 11.0 * 7, places=4)


class ArcaneCometTests(unittest.TestCase):
    # 15-100 by level + 0.10 bonus AD + 0.05 AP.
    def test_level1_ap(self):
        # ap-only build: ad=0 ap=100 -> AP wins -> +0.05*100 = 5; base 15.
        got = compute_rune_proc_damage(8229, level=1, ad=0.0, ap=100.0)
        self.assertAlmostEqual(got, 15.0 + 5.0, places=4)

    def test_level18_base(self):
        got = compute_rune_proc_damage(8229, level=18)
        self.assertAlmostEqual(got, 100.0, places=4)


class FlatTrueRuneTests(unittest.TestCase):
    def test_sudden_impact_level_scaled_true(self):
        # 20-80 true by level; no AD/AP scaling.
        self.assertAlmostEqual(
            compute_rune_proc_damage(8143, level=1, ad=999, ap=999), 20.0, places=4
        )
        self.assertAlmostEqual(
            compute_rune_proc_damage(8143, level=18), 80.0, places=4
        )

    def test_cheap_shot_level_scaled_true(self):
        # 10-45 true by level.
        self.assertAlmostEqual(
            compute_rune_proc_damage(8126, level=1), 10.0, places=4
        )
        self.assertAlmostEqual(
            compute_rune_proc_damage(8126, level=18), 45.0, places=4
        )

    def test_scorch_level_scaled_magic(self):
        # 20-40 magic by level.
        self.assertAlmostEqual(
            compute_rune_proc_damage(8237, level=1), 20.0, places=4
        )
        self.assertAlmostEqual(
            compute_rune_proc_damage(8237, level=18), 40.0, places=4
        )


class PressTheAttackTests(unittest.TestCase):
    def test_amp_multiplies(self):
        # 8% flat amp -> 1000 * 1.08 = 1080.
        self.assertAlmostEqual(keystone_amp(8005, 1000.0), 1080.0, places=4)
        self.assertGreater(keystone_amp(8005, 1000.0), 1000.0)

    def test_burst_piece_via_compute(self):
        # 40-160 adaptive burst by level; level 1 base 40.
        self.assertAlmostEqual(
            compute_rune_proc_damage(8005, level=1), 40.0, places=4
        )
        self.assertAlmostEqual(
            compute_rune_proc_damage(8005, level=18), 160.0, places=4
        )

    def test_proc_type_is_stacking_amp(self):
        self.assertEqual(RUNE_PROCS[8005].proc_type, "stacking_amp")


class ConquerorTests(unittest.TestCase):
    def test_per_stack_adaptive_by_level(self):
        # 1.8-4.0 adaptive per stack by level.
        self.assertAlmostEqual(
            compute_rune_proc_damage(8010, level=1), 1.8, places=4
        )
        self.assertAlmostEqual(
            compute_rune_proc_damage(8010, level=18), 4.0, places=4
        )

    def test_keystone_amp_is_noop_passthrough(self):
        # Conqueror is a stat stack on 16.11, NOT a damage amp.
        self.assertEqual(keystone_amp(8010, 1000.0), 1000.0)

    def test_proc_type_is_adaptive(self):
        self.assertEqual(RUNE_PROCS[8010].proc_type, "adaptive")


class AdaptiveTiebreakTests(unittest.TestCase):
    def test_ad_wins_tie(self):
        # ad == ap: AD coefficient (0.10) wins on Electrocute.
        got = compute_rune_proc_damage(8112, level=1, ad=100.0, ap=100.0)
        # base 70 + 0.10*100 = 80 (AD path), NOT 70 + 0.05*100 = 75.
        self.assertAlmostEqual(got, 80.0, places=4)

    def test_ap_dominant_picks_ap(self):
        got = compute_rune_proc_damage(8112, level=1, ad=10.0, ap=300.0)
        self.assertAlmostEqual(got, 70.0 + 0.05 * 300.0, places=4)

    def test_ad_dominant_picks_ad(self):
        got = compute_rune_proc_damage(8112, level=1, ad=300.0, ap=10.0)
        self.assertAlmostEqual(got, 70.0 + 0.10 * 300.0, places=4)


class FailSoftTests(unittest.TestCase):
    def test_unknown_rune_returns_zero(self):
        self.assertEqual(compute_rune_proc_damage(999999, level=10, ad=100), 0.0)
        self.assertEqual(compute_rune_proc_damage(0, level=10), 0.0)

    def test_keystone_amp_unknown_passthrough(self):
        self.assertEqual(keystone_amp(999999, 1000.0), 1000.0)

    def test_keystone_amp_nonamp_passthrough(self):
        # Electrocute is on_proc_burst, not an amp -> pass through.
        self.assertEqual(keystone_amp(8112, 1000.0), 1000.0)

    def test_bad_level_clamps_not_raises(self):
        self.assertEqual(compute_rune_proc_damage(8112, level="nope"), 70.0)
        self.assertAlmostEqual(
            compute_rune_proc_damage(8112, level=-5), 70.0, places=4
        )
        self.assertAlmostEqual(
            compute_rune_proc_damage(8112, level=99), 240.0, places=4
        )

    def test_bad_stats_fail_soft(self):
        got = compute_rune_proc_damage(8112, level=1, ad=None, ap=None)
        self.assertAlmostEqual(got, 70.0, places=4)

    def test_keystone_amp_bad_base_fail_soft(self):
        self.assertEqual(keystone_amp(8005, "nope"), 0.0)


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
            non_ascii, [], "test_rune_procs.py must contain 0 non-ASCII bytes"
        )


if __name__ == "__main__":
    unittest.main()

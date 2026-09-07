"""Tests for the DS V2 rune-proc per_attack expansion (item-229-NEXT(3)).

Two per-AA damage runes are added to agents/daemon_slayer/rune_procs.py, every
coefficient verbatim from live DDragon 16.11.1 runesReforged.json:

  9923 Hail of Blades   (Domination, per_attack, ADDITIVE 4-20 + 0.08 bAD + 0.06 AP, TRUE, CD 10s)
  8008 Lethal Tempo     (Precision,  per_attack, flat 9-30 by level adaptive-typed, no CD)

Fleet Footwork 8021 is an HONEST EXCLUSION: heal + move-speed sustain keystone
with no damage component, so it is NOT in RUNE_PROCS (same data-availability
ceiling as the Aery shield side). These tests pin all three facts.

Version-agnostic: no ENGINE_VERSION string is asserted (functional contract
only).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from agents.daemon_slayer.rune_procs import (
    RUNE_PROCS,
    compute_rune_proc_damage,
    keystone_amp,
)

# Anchor source-file lookups on this file's own location, not the process CWD,
# so the hygiene tests run from any directory.
_DS_DIR = Path(__file__).resolve().parents[1]   # agents/daemon_slayer

_TOL = 1e-6


class PerAttackPresenceTests(unittest.TestCase):
    def test_hail_of_blades_present_per_attack(self):
        self.assertIn(9923, RUNE_PROCS)
        self.assertEqual(RUNE_PROCS[9923].proc_type, "per_attack")

    def test_lethal_tempo_present_per_attack(self):
        self.assertIn(8008, RUNE_PROCS)
        self.assertEqual(RUNE_PROCS[8008].proc_type, "per_attack")

    def test_fleet_footwork_NOT_in_registry(self):
        # 8021 is a heal + MS sustain keystone with no damage component.
        self.assertNotIn(8021, RUNE_PROCS)


class HailOfBladesValueTests(unittest.TestCase):
    def test_level1_itemless(self):
        v = compute_rune_proc_damage(9923, 1)
        self.assertAlmostEqual(v, 4.0, delta=_TOL)

    def test_level1_with_ad_100(self):
        # 4.0 + 0.08*100 = 4.0 + 8.0 = 12.0 (additive bonus-AD side).
        v = compute_rune_proc_damage(9923, 1, ad=100.0, ap=0.0)
        self.assertAlmostEqual(v, 12.0, delta=_TOL)

    def test_level18_itemless(self):
        v = compute_rune_proc_damage(9923, 18)
        self.assertAlmostEqual(v, 20.0, delta=_TOL)

    def test_level18_with_ad_and_ap(self):
        # 20.0 + 0.08*100 + 0.06*100 = 20.0 + 8.0 + 6.0 = 34.0 (ADDITIVE both).
        v = compute_rune_proc_damage(9923, 18, ad=100.0, ap=100.0)
        self.assertAlmostEqual(v, 34.0, delta=_TOL)


class LethalTempoValueTests(unittest.TestCase):
    def test_level1(self):
        v = compute_rune_proc_damage(8008, 1)
        self.assertAlmostEqual(v, 9.0, delta=_TOL)

    def test_level18(self):
        v = compute_rune_proc_damage(8008, 18)
        self.assertAlmostEqual(v, 30.0, delta=_TOL)

    def test_flat_by_level_ad_ap_ignored(self):
        # No stat coefficient: AD/AP do not change the value.
        base = compute_rune_proc_damage(8008, 11)
        with_ad = compute_rune_proc_damage(8008, 11, ad=300.0)
        with_ap = compute_rune_proc_damage(8008, 11, ap=300.0)
        self.assertAlmostEqual(base, with_ad, delta=_TOL)
        self.assertAlmostEqual(base, with_ap, delta=_TOL)


class KeystoneAmpPassThroughTests(unittest.TestCase):
    def test_hail_of_blades_amp_pass_through(self):
        # per_attack rune is not a stacking_amp; keystone_amp returns base.
        self.assertAlmostEqual(keystone_amp(9923, 137.5), 137.5, delta=_TOL)

    def test_lethal_tempo_amp_pass_through(self):
        self.assertAlmostEqual(keystone_amp(8008, 250.0), 250.0, delta=_TOL)


class FailSoftTests(unittest.TestCase):
    def test_unknown_rune_returns_zero(self):
        self.assertEqual(compute_rune_proc_damage(999999, 10), 0.0)


class AsciiHygieneTests(unittest.TestCase):
    def test_rune_procs_module_is_ascii(self):
        path = _DS_DIR / "rune_procs.py"
        with open(path, "rb") as fh:
            data = fh.read()
        for i, b in enumerate(data):
            self.assertLess(b, 128, f"non-ASCII byte {b} at offset {i} in {path}")

    def test_this_test_file_is_ascii(self):
        path = Path(__file__).resolve()
        with open(path, "rb") as fh:
            data = fh.read()
        for i, b in enumerate(data):
            self.assertLess(b, 128, f"non-ASCII byte {b} at offset {i} in {path}")


if __name__ == "__main__":
    unittest.main()

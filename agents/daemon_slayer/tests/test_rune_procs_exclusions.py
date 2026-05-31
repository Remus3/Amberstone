"""Honest-exclusion contract for the rune-proc registry (RUNE_PROCS).

Closes the operator NEXT "expand per_attack to other on-hit runes if DDragon
exposes them". A scoping pass verified the DDragon 16.11.1 well is a dry one:
16 damage/amp runes are modeled, Fleet Footwork 8021 is an honest exclusion,
and the remaining candidates are sustain / utility / stat-stack / tower-only OR
caster-state / game-time gated. These tests PIN the deliberate non-entries so a
future maintainer does not "discover" them and add a misleading best-case proc:

  * Last Stand 8299      - CASTER-hp-gated amp (below 60% HP). Best-case 1.11x is
                            materially misleading for a burst-MAX scorer because
                            the caster is typically NOT low-hp during a burst
                            window (the opposite of target-hp gates like Cut Down
                            / Coup de Grace which burst windows routinely meet).
  * Absolute Focus 8233  - caster-hp-gated STAT GRANT (adaptive force while above
                            70% HP), same class as Eyeball/Legend stat runes we
                            never model.
  * Gathering Storm 8236 - time-scaled adaptive STAT GRANT (game-time gated).
  * Taste of Blood 8139  - heal/sustain, no damage.
  * Demolish 8446        - tower-only damage, no champion damage.

These are NOT shippable as proc damage. Modeling any of them would invent
numbers / misrepresent the scorer.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from agents.daemon_slayer.rune_procs import (
    RUNE_PROCS,
    compute_rune_proc_damage,
    keystone_amp,
)

# Ids that MUST NOT live in RUNE_PROCS (honest exclusions).
_EXCLUDED_IDS = {
    8299,  # Last Stand    - caster-hp-gated amp; best-case misleading for burst-MAX
    8233,  # Absolute Focus- caster-hp-gated stat grant
    8236,  # Gathering Storm - game-time-gated stat grant
    8139,  # Taste of Blood- heal/sustain only
    8446,  # Demolish      - tower-only damage
}

# The 16 runes that ARE modeled (8 substrate + 6 S4 + 2 per_attack).
_MODELED_IDS = {
    8112,  # Electrocute
    8128,  # Dark Harvest
    8229,  # Arcane Comet
    8143,  # Sudden Impact
    8126,  # Cheap Shot
    8237,  # Scorch
    8005,  # Press the Attack
    8010,  # Conqueror
    8214,  # Summon Aery
    8437,  # Grasp of the Undying
    8439,  # Aftershock
    8369,  # First Strike
    8014,  # Coup de Grace (target <40% hp, best-case stacking_amp)
    8017,  # Cut Down (target >60% hp, best-case stacking_amp)
    9923,  # Hail of Blades
    8008,  # Lethal Tempo
}


class ExcludedRunesNotRegistered(unittest.TestCase):
    """The deliberate non-entries must stay out of RUNE_PROCS."""

    def test_excluded_ids_absent_from_registry(self):
        for rune_id in sorted(_EXCLUDED_IDS):
            self.assertNotIn(
                rune_id,
                RUNE_PROCS,
                f"rune {rune_id} is an honest exclusion - must NOT be in RUNE_PROCS",
            )

    def test_last_stand_8299_excluded(self):
        # The borderline candidate: caster-hp-gated amp. EXCLUDED because a
        # best-case 1.11x is materially misleading for a burst-MAX scorer.
        self.assertNotIn(8299, RUNE_PROCS)

    def test_excluded_compute_is_zero(self):
        # Fail-soft: an unknown (excluded) rune contributes 0.0 proc damage.
        for rune_id in sorted(_EXCLUDED_IDS):
            self.assertEqual(
                compute_rune_proc_damage(rune_id, level=11.0, ad=200.0, ap=0.0),
                0.0,
                f"excluded rune {rune_id} must compute 0.0 proc damage",
            )

    def test_excluded_keystone_amp_is_passthrough(self):
        # Excluded ids are unknown to keystone_amp -> base unchanged (no amp).
        base = 1000.0
        for rune_id in sorted(_EXCLUDED_IDS):
            self.assertEqual(
                keystone_amp(rune_id, base),
                base,
                f"excluded rune {rune_id} must pass base damage through unchanged",
            )


class ModeledRunesStillPresent(unittest.TestCase):
    """Guard the dry-well finding: exactly the known 16 runes are modeled."""

    def test_all_16_modeled_present(self):
        for rune_id in sorted(_MODELED_IDS):
            self.assertIn(rune_id, RUNE_PROCS, f"modeled rune {rune_id} missing")

    def test_registry_is_exactly_the_16_modeled(self):
        # No silent additions and no silent drops since the scoping pass.
        self.assertEqual(set(RUNE_PROCS.keys()), _MODELED_IDS)


class LastStandConsistencyWithSiblings(unittest.TestCase):
    """Last Stand 8299 shares Precision slot 3 with Cut Down + Coup de Grace.

    Cut Down 8017 (target >60% hp) and Coup de Grace 8014 (target <40% hp) ARE
    modeled as unconditional best-case stacking_amp (the target-hp gate is met
    by the target during a normal burst window). Last Stand gates on the CASTER
    being low-hp, which a burst-opener typically is NOT - so it is the honest
    exclusion. These asserts pin the asymmetry: the two target-hp siblings are
    stacking_amp 1.08x; Last Stand is absent.
    """

    def test_cut_down_and_coup_are_stacking_amp(self):
        for rune_id, expected_mult in ((8017, 1.08), (8014, 1.08)):
            proc = RUNE_PROCS[rune_id]
            self.assertEqual(proc.proc_type, "stacking_amp")
            self.assertAlmostEqual(proc.amp_mult, expected_mult, places=6)
            # The amp closure returns 0.0 (the amp lives in keystone_amp).
            self.assertEqual(
                compute_rune_proc_damage(rune_id, level=11.0, ad=200.0, ap=0.0),
                0.0,
            )
            self.assertAlmostEqual(
                keystone_amp(rune_id, 1000.0), 1000.0 * expected_mult, places=4
            )

    def test_last_stand_does_not_amp(self):
        # Last Stand is NOT a stacking_amp in the registry: keystone_amp returns
        # base unchanged (it is excluded, so unknown to the amp path).
        self.assertEqual(keystone_amp(8299, 1000.0), 1000.0)


class ExclusionDocumentedInSource(unittest.TestCase):
    """The exclusions must be DOCUMENTED inline (mirrors the Fleet Footwork
    comment style) so they are never re-pitched."""

    @classmethod
    def setUpClass(cls):
        src_path = (
            Path(__file__).resolve().parent.parent / "rune_procs.py"
        )
        cls.source = src_path.read_text(encoding="ascii")

    def test_fleet_footwork_exclusion_still_documented(self):
        self.assertIn("8021", self.source)
        self.assertIn("Fleet Footwork", self.source)

    def test_last_stand_exclusion_documented(self):
        self.assertIn("8299", self.source)
        self.assertIn("Last Stand", self.source)

    def test_absolute_focus_exclusion_documented(self):
        self.assertIn("8233", self.source)
        self.assertIn("Absolute Focus", self.source)

    def test_gathering_storm_exclusion_documented(self):
        self.assertIn("8236", self.source)
        self.assertIn("Gathering Storm", self.source)


class AsciiHygiene(unittest.TestCase):
    """rune_procs.py + this test file must be pure 7-bit ASCII."""

    def test_rune_procs_is_ascii(self):
        src_path = Path(__file__).resolve().parent.parent / "rune_procs.py"
        raw = src_path.read_bytes()
        for i, b in enumerate(raw):
            self.assertLess(
                b, 128, f"non-ASCII byte 0x{b:02x} at offset {i} in rune_procs.py"
            )

    def test_this_test_file_is_ascii(self):
        raw = Path(__file__).resolve().read_bytes()
        for i, b in enumerate(raw):
            self.assertLess(
                b, 128, f"non-ASCII byte 0x{b:02x} at offset {i} in this test file"
            )


if __name__ == "__main__":
    unittest.main()

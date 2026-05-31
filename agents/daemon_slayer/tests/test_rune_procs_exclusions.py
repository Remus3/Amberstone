"""Honest-exclusion + conditionally-modeled contract for RUNE_PROCS.

ITEM 232 PROC-SIGNATURE LIFT updated this file. Last Stand 8299 / Absolute
Focus 8233 / Gathering Storm 8236 WERE honest exclusions (item 231) because the
unconditional best-case proc model could not express their gates without
inflating the burst-MAX scorer. The item-232 lift makes those gates EXPRESSIBLE
(a `condition` tag + gating-context kwargs), defaulting to BYTE-IDENTICAL
behaviour (zero contribution at the full-HP / time-0 context, matching the
exclusion). They are now CONDITIONALLY MODELED, not excluded. The item-231
reasoning still holds: the DEFAULT context yields no contribution.

Still HONEST EXCLUSIONS (truly out of scope - heal / tower, not champion proc
damage):
  * Taste of Blood 8139  - heal/sustain, no damage.
  * Demolish 8446        - tower-only damage, no champion damage.
Plus Fleet Footwork 8021 (heal + move speed sustain keystone, no damage).

These tests PIN both contracts so a future maintainer neither (a) re-pitches
8139/8446 as proc damage, nor (b) regresses the 8299/8233/8236 gates back to a
misleading unconditional best-case (the gates MUST yield zero contribution at
the default context).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from agents.daemon_slayer.rune_procs import (
    RUNE_PROCS,
    compute_rune_proc_damage,
    keystone_amp,
)

# Ids that MUST NOT live in RUNE_PROCS (honest exclusions - heal / tower).
_EXCLUDED_IDS = {
    8139,  # Taste of Blood- heal/sustain only
    8446,  # Demolish      - tower-only damage
}

# Item 232: the 3 conditionally-modeled gated runes (NOW in RUNE_PROCS).
_CONDITIONAL_IDS = {
    8299,  # Last Stand    - caster_hp_below stacking_amp (amp 1.0 at full HP)
    8233,  # Absolute Focus- caster_hp_above adaptive (burst-excluded grant)
    8236,  # Gathering Storm - game_time adaptive (burst-excluded grant)
}

# The runes that ARE modeled (16 pre-lift + 3 item-232 gated = 19).
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
    8299,  # Last Stand (item 232: caster_hp_below)
    8233,  # Absolute Focus (item 232: caster_hp_above)
    8236,  # Gathering Storm (item 232: game_time)
}


class ExcludedRunesNotRegistered(unittest.TestCase):
    """The remaining honest exclusions (heal / tower) must stay out."""

    def test_excluded_ids_absent_from_registry(self):
        for rune_id in sorted(_EXCLUDED_IDS):
            self.assertNotIn(
                rune_id,
                RUNE_PROCS,
                f"rune {rune_id} is an honest exclusion - must NOT be in RUNE_PROCS",
            )

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


class ConditionallyModeledRunesPresent(unittest.TestCase):
    """Item 232: the 3 gated runes are registered with their condition tags."""

    def test_conditional_ids_present(self):
        for rune_id in sorted(_CONDITIONAL_IDS):
            self.assertIn(rune_id, RUNE_PROCS, f"conditional rune {rune_id} missing")

    def test_conditions_assigned(self):
        self.assertEqual(RUNE_PROCS[8299].condition, "caster_hp_below")
        self.assertEqual(RUNE_PROCS[8233].condition, "caster_hp_above")
        self.assertEqual(RUNE_PROCS[8236].condition, "game_time")

    def test_default_context_zero_burst_contribution(self):
        # The lift defaults MUST yield no contribution (byte-identical to the
        # item-231 exclusion):
        #   8299 stacking_amp -> amp 1.0 at default full HP.
        self.assertEqual(keystone_amp(8299, 1000.0), 1000.0)
        #   8233 + 8236 are proc_type "adaptive" -> burst consumer SKIPS them.
        self.assertEqual(RUNE_PROCS[8233].proc_type, "adaptive")
        self.assertEqual(RUNE_PROCS[8236].proc_type, "adaptive")
        #   8236 compute is 0.0 at the default game_time_s=0.0 too.
        self.assertEqual(compute_rune_proc_damage(8236, 11, 100.0, 0.0), 0.0)


class ModeledRunesStillPresent(unittest.TestCase):
    """Guard the registry: exactly the known 19 runes are modeled."""

    def test_all_19_modeled_present(self):
        for rune_id in sorted(_MODELED_IDS):
            self.assertIn(rune_id, RUNE_PROCS, f"modeled rune {rune_id} missing")

    def test_registry_is_exactly_the_19_modeled(self):
        # No silent additions and no silent drops since the item-232 lift.
        self.assertEqual(set(RUNE_PROCS.keys()), _MODELED_IDS)


class LastStandGateHonorsAntiInflation(unittest.TestCase):
    """Last Stand 8299 shares Precision slot 4 with Cut Down + Coup de Grace.

    Cut Down 8017 (target >60% hp) and Coup de Grace 8014 (target <40% hp) ARE
    modeled as unconditional best-case stacking_amp (the target-hp gate is met
    by the target during a normal burst window). Last Stand gates on the CASTER
    being low-hp, which a burst-opener typically is NOT - so item 232 models it
    as a caster_hp_below stacking_amp whose amp is 1.0 at the default full HP
    (NO inflation, honoring the item-231 anti-inflation concern) and ramps to
    1.11x only when a caller supplies a low caster HP.
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

    def test_last_stand_no_amp_at_full_hp(self):
        # Item 232: Last Stand IS a stacking_amp, but its amp is caster-hp gated.
        # At the default full HP the amp is 1.0 -> base unchanged (no inflation).
        self.assertEqual(keystone_amp(8299, 1000.0), 1000.0)
        self.assertEqual(keystone_amp(8299, 1000.0, caster_hp_pct=1.0), 1000.0)

    def test_last_stand_amps_at_low_hp(self):
        # When a caller supplies a low caster HP, the gate computes correctly.
        self.assertAlmostEqual(
            keystone_amp(8299, 1000.0, caster_hp_pct=0.30), 1110.0, places=4
        )


class ExclusionDocumentedInSource(unittest.TestCase):
    """The exclusions + conditionally-modeled runes must be DOCUMENTED inline."""

    @classmethod
    def setUpClass(cls):
        src_path = (
            Path(__file__).resolve().parent.parent / "rune_procs.py"
        )
        cls.source = src_path.read_text(encoding="ascii")

    def test_fleet_footwork_exclusion_still_documented(self):
        self.assertIn("8021", self.source)
        self.assertIn("Fleet Footwork", self.source)

    def test_last_stand_documented(self):
        self.assertIn("8299", self.source)
        self.assertIn("Last Stand", self.source)

    def test_absolute_focus_documented(self):
        self.assertIn("8233", self.source)
        self.assertIn("Absolute Focus", self.source)

    def test_gathering_storm_documented(self):
        self.assertIn("8236", self.source)
        self.assertIn("Gathering Storm", self.source)

    def test_heal_tower_exclusions_documented(self):
        self.assertIn("8139", self.source)
        self.assertIn("8446", self.source)


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

"""Item 232 rune proc-signature lift regression + byte-identical contract.

Pins:
  * BYTE-IDENTICAL: every one of the 16 pre-lift runes returns EXACTLY its
    pre-lift value from compute_rune_proc_damage + keystone_amp at the DEFAULT
    gating context (caster_hp_pct=1.0, game_time_s=0.0, role="melee",
    bonus_as=0.0). The numbers below were captured from the live engine BEFORE
    the lift; they are the contract.
  * The 3 newly-shipped gated runes (Last Stand 8299 / Absolute Focus 8233 /
    Gathering Storm 8236) contribute 0 to a burst total at the default context
    (8299 amp 1.0; 8233 + 8236 adaptive -> burst consumer skips them) and
    compute correctly when a caller supplies the gating context.
  * Lethal Tempo 8008 role + bonus_as lift (melee default byte-identical;
    ranged < melee; bonus_as amps).
  * Registry size 19; condition field present on all (default "unconditional"
    for the 16 pre-lift runes).
  * ASCII hygiene.

ASCII only. No em-dashes.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer.rune_procs import (
    RUNE_PROCS,
    compute_rune_proc_damage,
    keystone_amp,
)


# Captured from the live engine BEFORE the item-232 lift. compute at
# level=11, ad=100.0, ap=80.0 for every pre-lift rune. These ARE the contract.
_PRE_LIFT_COMPUTE = {
    8005: 110.58823529411765,
    8008: 21.352941176470587,
    8010: 3.0941176470588236,
    8014: 0.0,
    8017: 0.0,
    8112: 180.0,
    8126: 30.58823529411765,
    8128: 40.0,
    8143: 55.294117647058826,
    8214: 43.529411764705884,
    8229: 75.0,
    8237: 31.764705882352942,
    8369: 0.0,
    8437: 0.0,
    8439: 80.88235294117646,
    9923: 26.211764705882356,
}

# Captured from the live engine BEFORE the lift. keystone_amp(rid, 100.0).
_PRE_LIFT_AMP = {
    8005: 108.0,
    8008: 100.0,
    8010: 100.0,
    8014: 108.0,
    8017: 108.0,
    8112: 100.0,
    8126: 100.0,
    8128: 100.0,
    8143: 100.0,
    8214: 100.0,
    8229: 100.0,
    8237: 100.0,
    8369: 107.0,
    8437: 100.0,
    8439: 100.0,
    9923: 100.0,
}

# The 3 newly-shipped gated runes (item 232).
_NEW_RUNE_IDS = {8299, 8233, 8236}


class ByteIdenticalContractTests(unittest.TestCase):
    """The 16 pre-lift runes are EXACTLY unchanged at the default context."""

    def test_compute_byte_identical_at_default_context(self):
        for rid, expected in _PRE_LIFT_COMPUTE.items():
            got = compute_rune_proc_damage(rid, 11, 100.0, 80.0)
            self.assertEqual(
                got,
                expected,
                f"rune {rid} compute drifted from pre-lift value {expected!r} (got {got!r})",
            )

    def test_compute_byte_identical_explicit_default_kwargs(self):
        # Passing the gating kwargs AT THEIR DEFAULTS must also be byte-identical.
        for rid, expected in _PRE_LIFT_COMPUTE.items():
            got = compute_rune_proc_damage(
                rid,
                11,
                100.0,
                80.0,
                caster_hp_pct=1.0,
                game_time_s=0.0,
                role="melee",
                bonus_as=0.0,
            )
            self.assertEqual(got, expected, f"rune {rid} explicit-default drift")

    def test_keystone_amp_byte_identical_at_default_context(self):
        for rid, expected in _PRE_LIFT_AMP.items():
            got = keystone_amp(rid, 100.0)
            self.assertEqual(
                got,
                expected,
                f"rune {rid} amp drifted from pre-lift value {expected!r} (got {got!r})",
            )

    def test_electrocute_level11_pin(self):
        # The brief's named example: Electrocute 8112 at level 11.
        self.assertEqual(compute_rune_proc_damage(8112, 11, 100.0, 80.0), 180.0)

    def test_pre_lift_runes_are_unconditional(self):
        # The 13 non-new runes that existed before AND were never gated keep
        # the default "unconditional" tag (Lethal Tempo 8008 is per_attack;
        # the 3 new ones are gated; everything else is unconditional).
        for rid in _PRE_LIFT_COMPUTE:
            if rid == 8008:
                self.assertEqual(RUNE_PROCS[rid].condition, "per_attack")
            else:
                self.assertEqual(
                    RUNE_PROCS[rid].condition,
                    "unconditional",
                    f"pre-lift rune {rid} should be unconditional",
                )


class LastStandTests(unittest.TestCase):
    """Last Stand 8299: caster_hp_below stacking_amp, byte-identical default."""

    def test_registered_with_condition(self):
        self.assertIn(8299, RUNE_PROCS)
        self.assertEqual(RUNE_PROCS[8299].condition, "caster_hp_below")
        self.assertEqual(RUNE_PROCS[8299].proc_type, "stacking_amp")
        self.assertEqual(RUNE_PROCS[8299].tree, "Precision")

    def test_full_hp_no_amp(self):
        # Default full HP: amp 1.0 -> base unchanged -> byte-identical exclusion.
        self.assertEqual(keystone_amp(8299, 100.0, caster_hp_pct=1.0), 100.0)

    def test_full_hp_default_kwarg(self):
        # No caster_hp_pct passed -> default 1.0 -> no amp.
        self.assertEqual(keystone_amp(8299, 100.0), 100.0)

    def test_at_60pct_no_amp(self):
        # Gate boundary: at exactly 60% HP, still no amp.
        self.assertEqual(keystone_amp(8299, 100.0, caster_hp_pct=0.60), 100.0)

    def test_at_30pct_max_amp(self):
        # Max at 30% -> 1.11x.
        self.assertAlmostEqual(
            keystone_amp(8299, 100.0, caster_hp_pct=0.30), 111.0, places=6
        )

    def test_below_30pct_capped(self):
        # Below 30% stays capped at 1.11x.
        self.assertAlmostEqual(
            keystone_amp(8299, 100.0, caster_hp_pct=0.10), 111.0, places=6
        )

    def test_at_45pct_midpoint(self):
        # Midpoint of the 0.60 -> 0.30 ramp (0.45) -> ~1.08x (per the brief).
        self.assertAlmostEqual(
            keystone_amp(8299, 100.0, caster_hp_pct=0.45), 108.0, places=6
        )

    def test_ramp_is_monotonic_decreasing_hp(self):
        # Lower caster HP -> higher amp (within the 0.60 -> 0.30 band).
        amps = [
            keystone_amp(8299, 100.0, caster_hp_pct=hp)
            for hp in (0.60, 0.55, 0.50, 0.45, 0.40, 0.35, 0.30)
        ]
        for a, b in zip(amps, amps[1:]):
            self.assertLessEqual(a, b)


class AbsoluteFocusTests(unittest.TestCase):
    """Absolute Focus 8233: caster_hp_above adaptive; burst-excluded grant."""

    def test_registered_adaptive(self):
        self.assertIn(8233, RUNE_PROCS)
        self.assertEqual(RUNE_PROCS[8233].proc_type, "adaptive")
        self.assertEqual(RUNE_PROCS[8233].condition, "caster_hp_above")
        self.assertEqual(RUNE_PROCS[8233].tree, "Sorcery")

    def test_grant_positive_at_full_hp(self):
        # At default full HP (>0.70) the grant is > 0 (but adaptive -> burst
        # consumer skips it, so it does not enter the burst total).
        self.assertGreater(
            compute_rune_proc_damage(8233, 11, 100.0, 0.0, caster_hp_pct=1.0), 0.0
        )

    def test_grant_zero_when_gate_fails(self):
        # caster_hp_pct <= 0.70 -> gate fails -> 0.0.
        self.assertEqual(
            compute_rune_proc_damage(8233, 11, 100.0, 0.0, caster_hp_pct=0.5), 0.0
        )

    def test_grant_zero_at_70pct_boundary(self):
        # At exactly 70% the gate (strictly above) fails -> 0.0.
        self.assertEqual(
            compute_rune_proc_damage(8233, 11, 100.0, 0.0, caster_hp_pct=0.70), 0.0
        )

    def test_level1_grant_floor(self):
        # DDragon: 1.8 AD at level 1 (AD-side on the default ad>=ap tie).
        self.assertAlmostEqual(
            compute_rune_proc_damage(8233, 1, 100.0, 0.0, caster_hp_pct=1.0),
            1.8,
            places=6,
        )

    def test_level18_grant_ceiling_ad(self):
        # DDragon: up to 18 AD at level 18 (AD-side when ad >= ap).
        self.assertAlmostEqual(
            compute_rune_proc_damage(8233, 18, 100.0, 0.0, caster_hp_pct=1.0),
            18.0,
            places=6,
        )

    def test_ap_side_when_ap_dominant(self):
        # AP > AD -> AP-side grant (up to 30 AP at level 18).
        self.assertAlmostEqual(
            compute_rune_proc_damage(8233, 18, 0.0, 100.0, caster_hp_pct=1.0),
            30.0,
            places=6,
        )


class GatheringStormTests(unittest.TestCase):
    """Gathering Storm 8236: game_time adaptive; burst-excluded grant."""

    def test_registered_adaptive(self):
        self.assertIn(8236, RUNE_PROCS)
        self.assertEqual(RUNE_PROCS[8236].proc_type, "adaptive")
        self.assertEqual(RUNE_PROCS[8236].condition, "game_time")
        self.assertEqual(RUNE_PROCS[8236].tree, "Sorcery")

    def test_zero_at_game_start(self):
        # game_time_s=0 -> 0.0 (default; byte-identical to the exclusion).
        self.assertEqual(
            compute_rune_proc_damage(8236, 11, 100.0, 0.0, game_time_s=0.0), 0.0
        )

    def test_zero_default_game_time(self):
        # No game_time_s passed -> default 0.0 -> 0.0.
        self.assertEqual(compute_rune_proc_damage(8236, 11, 100.0, 0.0), 0.0)

    def test_positive_at_30min(self):
        # game_time_s=1800 (30 min) -> > 0.
        self.assertGreater(
            compute_rune_proc_damage(8236, 11, 100.0, 0.0, game_time_s=1800.0), 0.0
        )

    def test_ad_side_10min_anchor(self):
        # AD-side 5 per 10 min: at 600s -> ~5 AD (default ad>=ap tie).
        self.assertAlmostEqual(
            compute_rune_proc_damage(8236, 11, 100.0, 0.0, game_time_s=600.0),
            5.0,
            places=6,
        )

    def test_grant_increases_with_time(self):
        early = compute_rune_proc_damage(8236, 11, 100.0, 0.0, game_time_s=600.0)
        late = compute_rune_proc_damage(8236, 11, 100.0, 0.0, game_time_s=1800.0)
        self.assertGreater(late, early)


class LethalTempoRoleTests(unittest.TestCase):
    """Lethal Tempo 8008: role + bonus_as lift; melee default byte-identical."""

    def test_melee_default_byte_identical(self):
        # Default role="melee" + bonus_as=0.0 == pre-lift value.
        self.assertEqual(
            compute_rune_proc_damage(8008, 11), _PRE_LIFT_COMPUTE[8008]
        )

    def test_melee_explicit_matches_default(self):
        self.assertEqual(
            compute_rune_proc_damage(8008, 11, role="melee", bonus_as=0.0),
            _PRE_LIFT_COMPUTE[8008],
        )

    def test_ranged_less_than_melee(self):
        melee = compute_rune_proc_damage(8008, 11, role="melee")
        ranged = compute_rune_proc_damage(8008, 11, role="ranged")
        self.assertLess(ranged, melee)

    def test_bonus_as_amps_melee_by_1_5x(self):
        base = compute_rune_proc_damage(8008, 11, role="melee", bonus_as=0.0)
        amped = compute_rune_proc_damage(8008, 11, role="melee", bonus_as=0.5)
        self.assertAlmostEqual(amped, base * 1.5, places=6)

    def test_ranged_floor_and_ceiling(self):
        # DDragon: 6-24 ranged by level.
        self.assertAlmostEqual(
            compute_rune_proc_damage(8008, 1, role="ranged"), 6.0, places=6
        )
        self.assertAlmostEqual(
            compute_rune_proc_damage(8008, 18, role="ranged"), 24.0, places=6
        )

    def test_condition_is_per_attack(self):
        self.assertEqual(RUNE_PROCS[8008].condition, "per_attack")


class HailOfBladesRoleParityTests(unittest.TestCase):
    """Hail of Blades 9923: role accepted but value unchanged (no role split)."""

    def test_melee_default_byte_identical(self):
        self.assertEqual(
            compute_rune_proc_damage(9923, 11, 100.0, 80.0), _PRE_LIFT_COMPUTE[9923]
        )

    def test_role_does_not_change_value(self):
        melee = compute_rune_proc_damage(9923, 11, 100.0, 80.0, role="melee")
        ranged = compute_rune_proc_damage(9923, 11, 100.0, 80.0, role="ranged")
        self.assertEqual(melee, ranged)

    def test_condition_unconditional(self):
        self.assertEqual(RUNE_PROCS[9923].condition, "unconditional")


class RegistryShapeTests(unittest.TestCase):
    """Registry now has 19 entries; condition field present on all."""

    def test_registry_size_19(self):
        self.assertEqual(len(RUNE_PROCS), 19)

    def test_three_new_runes_present(self):
        for rid in _NEW_RUNE_IDS:
            self.assertIn(rid, RUNE_PROCS)

    def test_condition_field_on_all(self):
        valid = {
            "unconditional",
            "caster_hp_below",
            "caster_hp_above",
            "target_hp_below",
            "target_hp_above",
            "game_time",
            "per_attack",
        }
        for rid, proc in RUNE_PROCS.items():
            self.assertTrue(
                hasattr(proc, "condition"), f"rune {rid} missing condition"
            )
            self.assertIn(
                proc.condition,
                valid,
                f"rune {rid} has invalid condition {proc.condition!r}",
            )

    def test_sixteen_originals_still_present(self):
        for rid in _PRE_LIFT_COMPUTE:
            self.assertIn(rid, RUNE_PROCS)


class BurstExclusionContractTests(unittest.TestCase):
    """The 3 new runes contribute 0 to a burst total at the default context.

    A burst total folds in proc_type in {on_proc_burst, per_attack,
    stacking_amp} (Conqueror / adaptive EXCLUDED), and applies keystone_amp.
    At the default context:
      * 8299 amp == 1.0 (no inflation).
      * 8233 + 8236 are proc_type "adaptive" -> burst skips them.
    """

    _BURST_PROC_TYPES = {"on_proc_burst", "per_attack", "stacking_amp"}

    def test_new_runes_zero_burst_contribution_default(self):
        for rid in _NEW_RUNE_IDS:
            proc = RUNE_PROCS[rid]
            if proc.proc_type in self._BURST_PROC_TYPES:
                # Only 8299 (stacking_amp) qualifies; verify its amp is 1.0
                # at the default context (no inflation to a burst base).
                self.assertEqual(
                    keystone_amp(rid, 100.0), 100.0,
                    f"rune {rid} should not amplify a burst base at default context",
                )
            else:
                # adaptive -> excluded from burst total by the consumer.
                self.assertEqual(proc.proc_type, "adaptive")

    def test_adaptive_new_runes_are_excluded_type(self):
        self.assertEqual(RUNE_PROCS[8233].proc_type, "adaptive")
        self.assertEqual(RUNE_PROCS[8236].proc_type, "adaptive")


class AsciiHygieneTests(unittest.TestCase):
    """The module and this test file are ASCII-only (no em-dashes/smart quotes)."""

    def test_rune_procs_module_is_ascii(self):
        from pathlib import Path

        import agents.daemon_slayer.rune_procs as mod

        raw = Path(mod.__file__).read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as exc:
            self.fail(f"rune_procs.py contains non-ASCII byte: {exc}")

    def test_this_test_file_is_ascii(self):
        from pathlib import Path

        raw = Path(__file__).read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as exc:
            self.fail(f"test file contains non-ASCII byte: {exc}")


if __name__ == "__main__":
    unittest.main()

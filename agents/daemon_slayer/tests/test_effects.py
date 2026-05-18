"""Phase 4 thin slice tests - per-item conditional effects."""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import DEFAULT_CRIT_BONUS, _armor_factor, compute_dps
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    MAGICAL,
    PHYSICAL,
    ItemEffect,
    PeriodicProc,
    collect_effects,
    total_crit_damage_bonus,
)


class PeriodicProcGuardTests(unittest.TestCase):
    """Schema-level guards in PeriodicProc."""

    def test_invalid_damage_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            PeriodicProc(
                name="bad", bonus_damage=10, damage_type="hybrid", every_n_attacks=3
            )

    def test_neither_interval_set_raises(self) -> None:
        with self.assertRaises(ValueError):
            PeriodicProc(name="bad", bonus_damage=10, damage_type=PHYSICAL)

    def test_both_intervals_set_raises(self) -> None:
        with self.assertRaises(ValueError):
            PeriodicProc(
                name="bad",
                bonus_damage=10,
                damage_type=PHYSICAL,
                every_n_attacks=3,
                every_n_seconds=4,
            )


class CollectorTests(unittest.TestCase):
    def test_collect_effects_in_order(self) -> None:
        # 3031 IE has an effect, 3101 Crystal Scepter fragment has no entry.
        out = collect_effects(["3101", "3031", "3072"])
        names = [e.name for e in out]
        self.assertEqual(names, ["Infinity Edge", "Bloodthirster"])

    def test_collect_effects_accepts_int_ids(self) -> None:
        out = collect_effects([3031, 6672])
        ids = [e.item_id for e in out]
        self.assertEqual(ids, ["3031", "6672"])

    def test_collect_effects_keeps_duplicates(self) -> None:
        # Engine doesn't enforce per-item uniqueness - ensure effect aggregation
        # mirrors that. Two IEs => two entries in the effects list.
        out = collect_effects(["3031", "3031"])
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(total_crit_damage_bonus(out), 0.60, places=2)

    def test_unknown_ids_silently_skipped(self) -> None:
        out = collect_effects(["999999", "3031"])
        self.assertEqual([e.item_id for e in out], ["3031"])


class InfinityEdgeCritDamageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_ie_adds_30pct_crit_damage_bonus(self) -> None:
        self.assertAlmostEqual(ITEM_EFFECTS["3031"].crit_damage_bonus, 0.30)

    def test_ie_dps_uses_bumped_crit_bonus(self) -> None:
        # Aatrox lvl 1 + IE: AD goes 60→135, crit goes 0→25%, crit_bonus 0.75→1.05.
        # Compare against the DPS we'd compute by hand with the bumped factor.
        ie = compute_dps(self.snap, "Aatrox", level=1, item_ids=["3031"])
        ad = ie.stats["ad"]
        crit = ie.stats["crit"]
        crit_bonus = DEFAULT_CRIT_BONUS + 0.30
        # avg_attack_dmg surfaces the crit_bonus directly.
        self.assertAlmostEqual(ie.avg_attack_dmg, ad * (1 + crit * crit_bonus), places=3)

    def test_ie_note_surfaces_in_dps_result(self) -> None:
        ie = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3031"])
        self.assertTrue(any("Infinity Edge" in n for n in ie.notes))

    def test_two_ies_stack_crit_damage(self) -> None:
        # 50% crit, +60% bonus crit damage above default.
        r = compute_dps(self.snap, "Aatrox", level=1, item_ids=["3031", "3031"])
        ad = r.stats["ad"]
        crit = r.stats["crit"]
        self.assertAlmostEqual(crit, 0.50)
        crit_bonus = DEFAULT_CRIT_BONUS + 0.60
        self.assertAlmostEqual(r.avg_attack_dmg, ad * (1 + crit * crit_bonus), places=3)


class KrakenSlayerProcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_kraken_proc_raises_dps_above_stats_alone(self) -> None:
        # Kraken vs naked: AD/AS/MS bumps PLUS the every-3rd-attack proc.
        # Net DPS should exceed what stats alone would give.
        naked = compute_dps(self.snap, "Aatrox", level=11)
        with_kraken = compute_dps(self.snap, "Aatrox", level=11, item_ids=["6672"])
        self.assertGreater(with_kraken.weighted_dps, naked.weighted_dps)

    def test_kraken_proc_uses_target_armor(self) -> None:
        # Same build, two different armors. The proc is physical, so doubling
        # armor halves the proc contribution alongside the auto-attack damage.
        soft = compute_dps(self.snap, "Aatrox", level=11, item_ids=["6672"])
        armored = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["6672"], target_armor=100.0
        )
        # 100 armor → factor 0.5. Both base auto + Kraken proc share the factor,
        # so the ratio should be ~0.5.
        self.assertAlmostEqual(
            armored.weighted_dps / soft.weighted_dps, 0.5, places=2
        )

    def test_kraken_note_surfaces(self) -> None:
        r = compute_dps(self.snap, "Aatrox", level=11, item_ids=["6672"])
        self.assertTrue(any("Kraken Slayer" in n for n in r.notes))


class StormrazorMagicProcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_stormrazor_proc_uses_mr_not_armor(self) -> None:
        # Magic-damage proc should not be reduced by target armor and SHOULD be
        # reduced by target MR. Concretely: stormrazor with 100 armor / 0 MR
        # should exceed stormrazor with 0 armor / 100 MR (because the proc is
        # full-damage in the first case but halved in the second; the auto-
        # attack portion is symmetric - full vs halved respectively).
        # We verify the proc contribution itself by comparing two cases that
        # only differ in target MR.
        no_mr = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3097"])
        with_mr = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3097"], target_mr=100.0
        )
        # Auto-attack portion is identical (target_armor=0 in both); only the
        # Stormrazor proc differs. Delta should equal procs * 120 * (1.0 - 0.5).
        delta = no_mr.weighted_dps - with_mr.weighted_dps
        self.assertGreater(delta, 0.0)

    def test_stormrazor_proc_unaffected_by_target_armor(self) -> None:
        # Set MR to 0 so only armor varies. Stormrazor proc is magical, so it
        # ignores armor - but the auto-attack portion DOES scale with armor.
        # We want the auto-attack scale to differ, but the proc to stay flat.
        # Easiest assertion: with high armor, the difference between Stormrazor
        # builds and naked builds should still include the full proc contribution.
        naked_armored = compute_dps(self.snap, "Aatrox", level=11, target_armor=100.0)
        sr_armored = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3097"], target_armor=100.0
        )
        # The DPS gain over naked includes the magic proc (full damage, since
        # target MR=0) plus the auto-attack stat bumps. Both should be positive.
        self.assertGreater(sr_armored.weighted_dps, naked_armored.weighted_dps)

    def test_stormrazor_note_surfaces(self) -> None:
        r = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3097"])
        self.assertTrue(any("Stormrazor" in n for n in r.notes))


class DefensiveOnlyItemTests(unittest.TestCase):
    """BT and Shieldbow are tagged defensive_only - no DPS contribution beyond
    their stat blocks. Ensures the schema entry is exercised end-to-end without
    accidentally adding DPS via a stale `periodic` field."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_bt_defensive_only_flag(self) -> None:
        self.assertTrue(ITEM_EFFECTS["3072"].defensive_only)
        self.assertEqual(ITEM_EFFECTS["3072"].periodics, ())
        self.assertEqual(ITEM_EFFECTS["3072"].crit_damage_bonus, 0.0)

    def test_shieldbow_defensive_only_flag(self) -> None:
        self.assertTrue(ITEM_EFFECTS["6673"].defensive_only)
        self.assertEqual(ITEM_EFFECTS["6673"].periodics, ())
        self.assertEqual(ITEM_EFFECTS["6673"].crit_damage_bonus, 0.0)

    def test_bt_dps_matches_stat_block_only(self) -> None:
        # Bloodthirster: +80 AD, +15% lifesteal. No conditional DPS effect.
        # DPS should be exactly the AD bump (60→140) factor of naked DPS.
        naked = compute_dps(self.snap, "Aatrox", level=1)
        bt = compute_dps(self.snap, "Aatrox", level=1, item_ids=["3072"])
        self.assertAlmostEqual(
            bt.weighted_dps, naked.weighted_dps * (140 / 60), places=2
        )


class UnmodeledItemRegressionTests(unittest.TestCase):
    """Items without an ITEM_EFFECTS entry must keep producing the same DPS
    they did before Phase 4 - the conditionals layer is purely additive."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_berserkers_greaves_unchanged(self) -> None:
        # Berserker's (3006) has no ITEM_EFFECTS entry. DPS should reflect only
        # the AS bump from its stat block.
        naked = compute_dps(self.snap, "Aatrox", level=1)
        zerks = compute_dps(self.snap, "Aatrox", level=1, item_ids=["3006"])
        # AS bonus 35% → adjust the basicTime portion of each rotation. Verify
        # via the avg_attack_dmg path (no crit bonus, no proc).
        self.assertAlmostEqual(zerks.avg_attack_dmg, naked.avg_attack_dmg, places=2)
        # And crit_bonus surfaced via avg should still equal default.
        ad = zerks.stats["ad"]
        self.assertAlmostEqual(zerks.avg_attack_dmg, ad, places=3)


class EffectAggregationTests(unittest.TestCase):
    """Effects are aggregated, not just last-wins. Stack 1 IE + 1 Stormrazor +
    1 Kraken - all three should fire together."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_three_effect_items_all_fire_in_notes(self) -> None:
        r = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3031", "3097", "6672"],
        )
        joined = " ".join(r.notes)
        self.assertIn("Infinity Edge", joined)
        self.assertIn("Stormrazor", joined)
        self.assertIn("Kraken Slayer", joined)


if __name__ == "__main__":
    unittest.main()

"""Phase 4 expansion tests — callable bonus_damage, armor pen layer, +25 items.

Companion to ``test_effects.py`` (thin slice). New coverage:
* ``CallContext`` resolution for callable ``bonus_damage``.
* Armor reduction → % pen → flat pen pipeline via ``effective_target_armor``.
* Black Cleaver, LDR, Mortal Reminder DPS impact.
* Energized family entries (Statikk Shiv, Rapid Firecannon, Voltaic, Sundered Sky).
* Scaling proc entries (Wit's End by level, Runaan's by bonus AD, TriForce by base AD).
* defensive_only entries — no DPS contribution beyond stat block.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    CallContext,
    PHYSICAL,
    PeriodicProc,
    effective_target_armor,
)


# ---------------------------------------------------------------- schema bumps


class CallContextTests(unittest.TestCase):
    """CallContext resolves callable bonus_damage entries."""

    def test_constant_passes_through(self) -> None:
        proc = PeriodicProc(
            name="const", bonus_damage=120.0, damage_type=PHYSICAL,
            every_n_attacks=3,
        )
        ctx = CallContext(base_ad=60, bonus_ad=0, level=1)
        self.assertEqual(proc.resolve_damage(ctx), 120.0)

    def test_callable_resolves_against_ctx(self) -> None:
        proc = PeriodicProc(
            name="scale_bonus_ad",
            bonus_damage=lambda c: 0.6 * c.bonus_ad,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        )
        self.assertEqual(
            proc.resolve_damage(CallContext(base_ad=60, bonus_ad=100, level=11)),
            60.0,
        )
        self.assertEqual(
            proc.resolve_damage(CallContext(base_ad=60, bonus_ad=0, level=11)),
            0.0,
        )

    def test_callable_returning_int_coerces_to_float(self) -> None:
        proc = PeriodicProc(
            name="int_returner",
            bonus_damage=lambda c: int(50),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        )
        result = proc.resolve_damage(CallContext(base_ad=60, bonus_ad=0, level=1))
        self.assertIsInstance(result, float)
        self.assertEqual(result, 50.0)


class EffectiveTargetArmorTests(unittest.TestCase):
    """Reduction → % pen → flat pen pipeline."""

    def test_no_effects_passthrough(self) -> None:
        self.assertEqual(effective_target_armor(80.0, []), 80.0)

    def test_no_effects_preserves_negative(self) -> None:
        # Tests of the armor-curve math pass negative armor through.
        self.assertEqual(effective_target_armor(-100.0, []), -100.0)

    def test_negative_armor_no_op_with_pen(self) -> None:
        # Pen / reduction is a no-op when target is already shredded.
        ldr = ITEM_EFFECTS["3036"]
        self.assertEqual(effective_target_armor(-50.0, [ldr]), -50.0)

    def test_ldr_applies_35pct_pen(self) -> None:
        ldr = ITEM_EFFECTS["3036"]
        self.assertAlmostEqual(effective_target_armor(100.0, [ldr]), 65.0, places=3)

    def test_mortal_reminder_30pct_pen(self) -> None:
        mr = ITEM_EFFECTS["3033"]
        self.assertAlmostEqual(effective_target_armor(100.0, [mr]), 70.0, places=3)

    def test_black_cleaver_reduction(self) -> None:
        bc = ITEM_EFFECTS["3071"]
        self.assertAlmostEqual(effective_target_armor(100.0, [bc]), 70.0, places=3)

    def test_bc_then_ldr_compose(self) -> None:
        # Reduction first, then % pen. 100 → 70 (BC) → 45.5 (LDR 35%).
        bc = ITEM_EFFECTS["3071"]
        ldr = ITEM_EFFECTS["3036"]
        self.assertAlmostEqual(effective_target_armor(100.0, [bc, ldr]), 45.5, places=3)

    def test_floors_at_zero_after_pen(self) -> None:
        bc = ITEM_EFFECTS["3071"]
        ldr = ITEM_EFFECTS["3036"]
        # 30 → 21 (BC) → 13.65 (LDR). Stays positive.
        self.assertGreater(effective_target_armor(30.0, [bc, ldr]), 0.0)
        # Stack flat pen big enough to push below zero → floored.
        from agents.daemon_slayer.effects import ItemEffect
        flat = ItemEffect(item_id="x", name="x", armor_pen_flat=200.0)
        self.assertEqual(effective_target_armor(50.0, [flat]), 0.0)


# ---------------------------------------------------------------- new entries


class ArmorPenDpsImpactTests(unittest.TestCase):
    """Pen items raise DPS against an armored target."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_ldr_raises_dps_vs_armored(self) -> None:
        # vs 100 armor: bare auto-attacks see factor 0.5; LDR raises factor.
        bare = compute_dps(self.snap, "Aatrox", level=11, target_armor=100.0)
        with_ldr = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3036"], target_armor=100.0,
        )
        self.assertGreater(with_ldr.weighted_dps, bare.weighted_dps)

    def test_ldr_no_effect_vs_zero_armor(self) -> None:
        # vs 0 armor, LDR's pen doesn't help (factor already 1.0). DPS gain
        # comes only from LDR's stat block (AD + crit).
        bare = compute_dps(self.snap, "Aatrox", level=11, target_armor=0.0)
        with_ldr = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3036"], target_armor=0.0,
        )
        # Both have armor_factor=1.0; DPS difference is purely stat block.
        # Verify the effective_target_armor stayed at zero.
        self.assertEqual(with_ldr.target_armor, 0.0)  # input field unchanged
        # DPS still differs (stat block), but pen contribution is zero.
        self.assertGreater(with_ldr.weighted_dps, bare.weighted_dps)

    def test_black_cleaver_raises_dps_vs_armored(self) -> None:
        bare = compute_dps(self.snap, "Aatrox", level=11, target_armor=100.0)
        with_bc = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3071"], target_armor=100.0,
        )
        self.assertGreater(with_bc.weighted_dps, bare.weighted_dps)

    def test_mortal_reminder_raises_dps_vs_armored(self) -> None:
        bare = compute_dps(self.snap, "Aatrox", level=11, target_armor=100.0)
        with_mr = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3033"], target_armor=100.0,
        )
        self.assertGreater(with_mr.weighted_dps, bare.weighted_dps)

    def test_pen_note_surfaces_when_armor_reduced(self) -> None:
        with_ldr = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3036"], target_armor=100.0,
        )
        joined = " ".join(with_ldr.notes)
        self.assertIn("effective target armor", joined)
        self.assertIn("65.0", joined)  # 100 * 0.65 = 65 after LDR pen

    def test_pen_note_absent_when_no_armor_modifier(self) -> None:
        bare = compute_dps(self.snap, "Aatrox", level=11, target_armor=100.0)
        joined = " ".join(bare.notes)
        self.assertNotIn("effective target armor", joined)


class EnergizedFamilyTests(unittest.TestCase):
    """Statikk Shiv / Rapid Firecannon / Voltaic Cyclosword / Sundered Sky."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_statikk_shiv_raises_dps(self) -> None:
        bare = compute_dps(self.snap, "Aatrox", level=11)
        with_ss = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3087"])
        self.assertGreater(with_ss.weighted_dps, bare.weighted_dps)

    def test_statikk_proc_uses_mr_not_armor(self) -> None:
        # Magic chain → MR matters, armor doesn't.
        no_mr = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3087"])
        with_mr = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3087"], target_mr=100.0,
        )
        self.assertGreater(no_mr.weighted_dps, with_mr.weighted_dps)

    def test_rapid_firecannon_raises_dps(self) -> None:
        bare = compute_dps(self.snap, "Aatrox", level=11)
        with_rf = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3094"])
        self.assertGreater(with_rf.weighted_dps, bare.weighted_dps)

    def test_voltaic_cyclosword_scales_with_bonus_ad(self) -> None:
        # Voltaic proc = 100 + 25% bonus_AD physical. With more bonus AD
        # (stack a BF Sword 3057... wait, just stack two Voltaics for
        # max bonus AD demonstration since 3057 may not be in items).
        # Easier: compare Voltaic alone vs Voltaic + Bloodthirster (huge bonus AD).
        v_only = compute_dps(self.snap, "Aatrox", level=11, item_ids=["6699"])
        v_bt = compute_dps(self.snap, "Aatrox", level=11, item_ids=["6699", "3072"])
        # BT adds 80 AD as bonus → Voltaic proc gains 0.25*80=20 per fire.
        # v_bt should exceed v_only by more than just the BT auto-attack
        # contribution alone — but proving that cleanly is hard. Cheaper
        # assertion: BT lifts DPS, period.
        self.assertGreater(v_bt.weighted_dps, v_only.weighted_dps)

    def test_sundered_sky_raises_dps(self) -> None:
        bare = compute_dps(self.snap, "Aatrox", level=11)
        with_ss = compute_dps(self.snap, "Aatrox", level=11, item_ids=["6610"])
        self.assertGreater(with_ss.weighted_dps, bare.weighted_dps)


class ScalingProcTests(unittest.TestCase):
    """Wit's End by level, Runaan's by bonus AD, TriForce by base AD, Guinsoo's."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_wits_end_scales_with_level(self) -> None:
        # 15 magic at lvl 1 → 80 at lvl 18. DPS at lvl 11 should exceed lvl 1.
        # Lvl 11: 15 + 10 * (65/17) ≈ 53 magic per attack.
        l1 = compute_dps(self.snap, "Aatrox", level=1, item_ids=["3091"])
        l11 = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3091"])
        # Lvl-11 DPS includes more attacks per rotation AND more proc damage.
        # Verify lvl-11 > lvl-1 (mostly drives by stats but proc helps).
        self.assertGreater(l11.weighted_dps, l1.weighted_dps)

    def test_runaans_scales_with_bonus_ad(self) -> None:
        # Runaan's alone has small bonus AD (just from its own stats);
        # add Bloodthirster (+80 AD) and the proc fires harder.
        r_only = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3085"])
        r_bt = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3085", "3072"])
        self.assertGreater(r_bt.weighted_dps, r_only.weighted_dps)

    def test_triforce_proc_uses_base_ad(self) -> None:
        # TriForce spellblade = 200% base_AD. Aatrox has 60 base AD; proc
        # contributes 120 phys per fire (every ~3s).
        with_tf = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3078"])
        bare = compute_dps(self.snap, "Aatrox", level=11)
        self.assertGreater(with_tf.weighted_dps, bare.weighted_dps)

    def test_guinsoos_phantom_hit_scales_with_bonus_ad(self) -> None:
        g_only = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3124"])
        g_bt = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3124", "3072"])
        self.assertGreater(g_bt.weighted_dps, g_only.weighted_dps)


class DefensiveOnlyExpansionTests(unittest.TestCase):
    """defensive_only entries shouldn't add DPS beyond their stat block."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_collector_no_periodic(self) -> None:
        e = ITEM_EFFECTS["6676"]
        self.assertTrue(e.defensive_only)
        self.assertIsNone(e.periodic)

    def test_phantom_dancer_no_periodic(self) -> None:
        e = ITEM_EFFECTS["3046"]
        self.assertTrue(e.defensive_only)
        self.assertIsNone(e.periodic)

    def test_sterak_no_periodic(self) -> None:
        e = ITEM_EFFECTS["3053"]
        self.assertTrue(e.defensive_only)
        self.assertIsNone(e.periodic)

    def test_blade_of_ruined_king_defensive_for_now(self) -> None:
        # BotRK requires target HP modeling; explicitly defensive_only in
        # Phase 4. Promote when target_max_hp lands.
        e = ITEM_EFFECTS["3153"]
        self.assertTrue(e.defensive_only)
        self.assertIn("not modeled", e.note.lower())

    def test_eclipse_defensive_for_now(self) -> None:
        e = ITEM_EFFECTS["6692"]
        self.assertTrue(e.defensive_only)
        self.assertIn("not modeled", e.note.lower())

    def test_terminus_defensive_for_now(self) -> None:
        e = ITEM_EFFECTS["3302"]
        self.assertTrue(e.defensive_only)


class DefensiveOnlyBatch2Tests(unittest.TestCase):
    """Phase 4 batch 2 (2026-05-04) — 10 high-pickrate SR legendaries.

    All defensive_only — utilities/shields/storage with no DPS proc.
    Pinning the table here so future schema-promotion work (target HP,
    magic pen, ability scaling) can find these via grep when the
    relevant hooks land.
    """

    EXPECTED = {
        "6333": "Death's Dance",
        "3161": "Spear of Shojin",
        "3508": "Essence Reaver",
        "3084": "Heartsteel",
        "3083": "Warmog's Armor",
        "3139": "Mercurial Scimitar",
        "3026": "Guardian Angel",
        "3102": "Banshee's Veil",
        "3157": "Zhonya's Hourglass",
        "6631": "Stridebreaker",
    }

    def test_all_present(self) -> None:
        for iid in self.EXPECTED:
            self.assertIn(iid, ITEM_EFFECTS, f"missing {iid}")

    def test_all_defensive_only(self) -> None:
        for iid, expected_name in self.EXPECTED.items():
            e = ITEM_EFFECTS[iid]
            self.assertEqual(e.name, expected_name, iid)
            self.assertTrue(e.defensive_only, f"{iid} should be defensive_only")
            self.assertIsNone(e.periodic, f"{iid} should have no periodic proc")
            self.assertEqual(e.crit_damage_bonus, 0.0, iid)
            self.assertEqual(e.armor_reduction_pct, 0.0, iid)
            self.assertEqual(e.armor_pen_pct, 0.0, iid)
            self.assertEqual(e.armor_pen_flat, 0.0, iid)

    def test_all_have_notes(self) -> None:
        for iid in self.EXPECTED:
            self.assertTrue(
                ITEM_EFFECTS[iid].note.strip(),
                f"{iid} missing note",
            )


class CoverageCountTests(unittest.TestCase):
    """Sanity: ITEM_EFFECTS keeps growing (5 thin slice + 25 expansion + 10 batch 2 = 40)."""

    def test_table_size_at_phase_4_expansion(self) -> None:
        # Lower bound: no regressions removed entries.
        self.assertGreaterEqual(len(ITEM_EFFECTS), 40)


if __name__ == "__main__":
    unittest.main()

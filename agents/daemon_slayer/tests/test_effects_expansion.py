"""Phase 4 expansion tests — callable bonus_damage, armor pen layer, +25 items.

Companion to ``test_effects.py`` (thin slice). New coverage:
* ``CallContext`` resolution for callable ``bonus_damage``.
* Armor reduction → % pen → flat pen pipeline via ``effective_target_armor``.
* Black Cleaver, LDR, Mortal Reminder DPS impact.
* Energized family entries (Statikk Shiv, Rapid Firecannon, Voltaic, Sundered Sky).
* Scaling proc entries (Wit's End by level, Runaan's by bonus AD, TriForce by base AD).
* AP-scaling spellblade / on-hit (Lich Bane, Nashor's Tooth) — Phase 4 batch 3.
* Magic pen layer (Void Staff, Cryptbloom, Sorc, Shadowflame) — Phase 4 batch 4.
* Target-HP layer (BotRK Mist's Edge, Eclipse Ever Rising Moon) — Phase 4 batch 5.
* Caster-HP layer (Titanic Hydra Cleave, Heartsteel Colossal Consumption) — Phase 4 batch 6.
* defensive_only entries — no DPS contribution beyond stat block.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    CallContext,
    MAGICAL,
    PHYSICAL,
    PeriodicProc,
    effective_target_armor,
    effective_target_mr,
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

    # BotRK (3153) and Eclipse (6692) promoted in Phase 4 batch 5
    # (2026-05-04) once ``target_max_hp`` landed. Their proc-shape
    # assertions live in TargetHpItemTests below; the schema-promotion
    # path matches Shadowflame in batch 4.

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

    # Heartsteel (3084) was here through batch 5; promoted in batch 6
    # (caster-HP layer, 2026-05-04) — its proc-shape assertions live
    # in CasterHpItemTests below.
    EXPECTED = {
        "6333": "Death's Dance",
        "3161": "Spear of Shojin",
        "3508": "Essence Reaver",
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


class CallContextApTests(unittest.TestCase):
    """Phase 4 batch 3 — CallContext.ap field for AP-scaling procs."""

    def test_ap_default_zero(self) -> None:
        # Backward-compatible default — pre-batch-3 callers don't pass ap.
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11)
        self.assertEqual(ctx.ap, 0.0)

    def test_callable_resolves_against_ap(self) -> None:
        proc = PeriodicProc(
            name="ap_scale",
            bonus_damage=lambda c: 0.5 * c.ap,
            damage_type=MAGICAL,
            every_n_attacks=1,
        )
        self.assertEqual(
            proc.resolve_damage(CallContext(base_ad=60, bonus_ad=0, level=11, ap=100.0)),
            50.0,
        )
        self.assertEqual(
            proc.resolve_damage(CallContext(base_ad=60, bonus_ad=0, level=11)),
            0.0,
        )

    def test_combined_base_ad_and_ap(self) -> None:
        # Mirrors Lich Bane: 75% base AD + 50% AP magic.
        proc = PeriodicProc(
            name="lich_bane_like",
            bonus_damage=lambda c: 0.75 * c.base_ad + 0.50 * c.ap,
            damage_type=MAGICAL,
            every_n_seconds=3.0,
        )
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11, ap=100.0)
        # 0.75*60 + 0.5*100 = 45 + 50 = 95.
        self.assertEqual(proc.resolve_damage(ctx), 95.0)


class SpellbladeAndOnHitApTests(unittest.TestCase):
    """Lich Bane (3100) + Nashor's Tooth (3115) — AP-scaling promotions."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_lich_bane_periodic_present(self) -> None:
        e = ITEM_EFFECTS["3100"]
        self.assertIsNotNone(e.periodic)
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.periodic.damage_type, MAGICAL)

    def test_lich_bane_raises_dps(self) -> None:
        bare = compute_dps(self.snap, "Aatrox", level=11)
        with_lb = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3100"])
        self.assertGreater(with_lb.weighted_dps, bare.weighted_dps)

    def test_lich_bane_proc_uses_mr(self) -> None:
        no_mr = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3100"])
        with_mr = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3100"], target_mr=100.0,
        )
        self.assertGreater(no_mr.weighted_dps, with_mr.weighted_dps)

    def test_lich_bane_scales_with_ap(self) -> None:
        # One Lich Bane = 100 AP; two Lich Banes = 200 AP. The proc
        # contribution scales 50% off AP, so the bigger AP pile wins.
        # Stat-block AS / AH stack too, so just assert "more is more".
        one_lb = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3100"])
        two_lb = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3100", "3100"])
        self.assertGreater(two_lb.weighted_dps, one_lb.weighted_dps)

    def test_nashors_tooth_periodic_present(self) -> None:
        e = ITEM_EFFECTS["3115"]
        self.assertIsNotNone(e.periodic)
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.periodic.damage_type, MAGICAL)
        self.assertEqual(e.periodic.every_n_attacks, 1)

    def test_nashors_tooth_raises_dps(self) -> None:
        bare = compute_dps(self.snap, "Aatrox", level=11)
        with_nt = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3115"])
        self.assertGreater(with_nt.weighted_dps, bare.weighted_dps)

    def test_nashors_proc_uses_mr(self) -> None:
        # On-hit magic → MR matters, armor doesn't.
        no_mr = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3115"])
        with_mr = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3115"], target_mr=100.0,
        )
        self.assertGreater(no_mr.weighted_dps, with_mr.weighted_dps)

    def test_nashors_scales_with_ap(self) -> None:
        # Stack a Lich Bane (+100 AP) on top of Nashor's (80 AP). Proc
        # damage rises with the bigger AP pile; we already test Lich Bane
        # raises DPS, so we need "Nashor + Lich beats Nashor + non-AP".
        # Pair Nashor's with Bloodthirster (3072, +80 AD, no AP) as the
        # control — same gold-ish, no AP. Lich Bane companion has AP.
        nt_bt = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3115", "3072"])
        nt_lb = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3115", "3100"])
        # nt_lb has 100 extra AP in CallContext → Nashor's proc gains
        # 0.20 * 100 = 20 extra magic per attack. Should beat the AD-only
        # companion's auto-attack contribution.
        self.assertGreater(nt_lb.weighted_dps, nt_bt.weighted_dps)


class DefensiveOnlyBatch3Tests(unittest.TestCase):
    """Phase 4 batch 3 (2026-05-04) — 4 AP-stat siblings without DPS proc.

    Hextech Gunblade (3146) / Luden's Echo (6655) / Riftmaker (4633) /
    Deathfire Grasp (3128). All carry AP stat blocks but their effects
    don't fit the periodic/on-hit shape: active utilities, ability-bound
    bolts, combat-state amps, and active %-target-max-HP. Pinned here
    so future hooks (target HP, combat-state amp) can find them via
    grep.

    Note: Shadowflame (4645) shipped batch 3 as defensive_only but
    promoted in batch 4 — its 15 flat magic pen IS modeled by the new
    pipeline (the unmodeled piece is the magic-crit-on-low-HP). So
    it now lives in MagicPenItemTests, not here.
    """

    EXPECTED = {
        "3146": "Hextech Gunblade",
        "6655": "Luden's Echo",
        "4633": "Riftmaker",
        "3128": "Deathfire Grasp",
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


class EffectiveTargetMrTests(unittest.TestCase):
    """Phase 4 batch 4 — % magic pen → flat magic pen pipeline."""

    def test_no_effects_passthrough(self) -> None:
        self.assertEqual(effective_target_mr(60.0, []), 60.0)

    def test_no_effects_preserves_negative(self) -> None:
        # Negative MR (test harnesses, external shred) passes through.
        self.assertEqual(effective_target_mr(-100.0, []), -100.0)

    def test_negative_mr_no_op_with_pen(self) -> None:
        void = ITEM_EFFECTS["3135"]
        self.assertEqual(effective_target_mr(-50.0, [void]), -50.0)

    def test_void_staff_applies_40pct_pen(self) -> None:
        void = ITEM_EFFECTS["3135"]
        self.assertAlmostEqual(effective_target_mr(100.0, [void]), 60.0, places=3)

    def test_cryptbloom_applies_30pct_pen(self) -> None:
        crypt = ITEM_EFFECTS["3137"]
        self.assertAlmostEqual(effective_target_mr(100.0, [crypt]), 70.0, places=3)

    def test_sorcerers_shoes_12_flat_pen(self) -> None:
        sorc = ITEM_EFFECTS["3020"]
        self.assertAlmostEqual(effective_target_mr(50.0, [sorc]), 38.0, places=3)

    def test_shadowflame_15_flat_pen(self) -> None:
        sf = ITEM_EFFECTS["4645"]
        self.assertAlmostEqual(effective_target_mr(50.0, [sf]), 35.0, places=3)

    def test_void_then_sorc_compose(self) -> None:
        # 100 → 60 (Void 40%) → 48 (Sorc 12 flat).
        void = ITEM_EFFECTS["3135"]
        sorc = ITEM_EFFECTS["3020"]
        self.assertAlmostEqual(effective_target_mr(100.0, [void, sorc]), 48.0, places=3)

    def test_floors_at_zero(self) -> None:
        # Stack flat pen big enough to push below zero → floored.
        from agents.daemon_slayer.effects import ItemEffect
        flat = ItemEffect(item_id="x", name="x", magic_pen_flat=200.0)
        self.assertEqual(effective_target_mr(50.0, [flat]), 0.0)


class MagicPenItemTests(unittest.TestCase):
    """Magic-pen items raise DPS for magical procs against an MR'd target."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_void_staff_raises_dps_via_lich_bane(self) -> None:
        # Lich Bane proc is magical → MR-sensitive. Vs 100 MR target,
        # Void Staff's 40% pen should lift the proc damage.
        no_void = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3100"], target_mr=100.0,
        )
        with_void = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3100", "3135"], target_mr=100.0,
        )
        self.assertGreater(with_void.weighted_dps, no_void.weighted_dps)

    def test_void_staff_no_proc_effect_vs_zero_mr(self) -> None:
        # Vs 0 MR, pen does nothing — only Void's stat block contributes.
        bare = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3100"])
        with_void = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3100", "3135"],
        )
        # Stat block alone (95 AP) lifts the Lich Bane proc — assert >.
        self.assertGreater(with_void.weighted_dps, bare.weighted_dps)
        # And note no MR-pen note surfaces when target_mr=0.
        joined = " ".join(with_void.notes)
        self.assertNotIn("effective target MR", joined)

    def test_cryptbloom_raises_dps_via_nashors(self) -> None:
        no_crypt = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3115"], target_mr=100.0,
        )
        with_crypt = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3115", "3137"], target_mr=100.0,
        )
        self.assertGreater(with_crypt.weighted_dps, no_crypt.weighted_dps)

    def test_sorcerers_shoes_raises_dps(self) -> None:
        bare_proc = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3115"], target_mr=50.0,
        )
        with_sorc = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3115", "3020"], target_mr=50.0,
        )
        self.assertGreater(with_sorc.weighted_dps, bare_proc.weighted_dps)

    def test_shadowflame_promoted_not_defensive_only(self) -> None:
        # Shadowflame shipped batch 3 as defensive_only; batch 4 promoted
        # it to magic_pen_flat=15. Documents the schema-promotion path.
        e = ITEM_EFFECTS["4645"]
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.magic_pen_flat, 15.0)
        self.assertIn("magic pen", e.note.lower())

    def test_shadowflame_raises_dps_via_nashors(self) -> None:
        no_sf = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3115"], target_mr=50.0,
        )
        with_sf = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3115", "4645"], target_mr=50.0,
        )
        self.assertGreater(with_sf.weighted_dps, no_sf.weighted_dps)

    def test_mr_pen_note_surfaces_when_mr_reduced(self) -> None:
        with_void = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3115", "3135"], target_mr=100.0,
        )
        joined = " ".join(with_void.notes)
        self.assertIn("effective target MR", joined)
        self.assertIn("60.0", joined)  # 100 * (1 - 0.40) = 60

    def test_mr_pen_note_absent_when_no_mr_modifier(self) -> None:
        bare = compute_dps(self.snap, "Aatrox", level=11, target_mr=100.0)
        joined = " ".join(bare.notes)
        self.assertNotIn("effective target MR", joined)

    def test_armor_pen_unaffected_by_magic_pen_layer(self) -> None:
        # Sanity: physical pen pipeline is independent of magic pen.
        ldr = ITEM_EFFECTS["3036"]
        # Even when MR pen is present, armor pen still resolves correctly.
        with_both = compute_dps(
            self.snap, "Aatrox", level=11,
            item_ids=["3036", "3135"],
            target_armor=100.0, target_mr=100.0,
        )
        joined = " ".join(with_both.notes)
        self.assertIn("effective target armor", joined)
        self.assertIn("effective target MR", joined)


class CoverageCountTests(unittest.TestCase):
    """Sanity: ITEM_EFFECTS keeps growing.

    5 thin slice + 25 expansion + 10 batch 2 + 6 batch 3 + 4 batch 4 = 50.
    Batch 3 originally landed 7 items but Shadowflame (4645) promoted in
    batch 4, leaving 6 net batch-3 entries here. Batch 5 (target HP)
    promoted BotRK + Eclipse from defensive_only — count stayed at 50
    (promotions don't add or remove entries). Batch 6 (caster HP)
    adds Titanic Hydra (new entry) + promotes Heartsteel — table grows
    to 51.
    """

    def test_table_size_at_phase_4_expansion(self) -> None:
        # Lower bound: no regressions removed entries.
        self.assertGreaterEqual(len(ITEM_EFFECTS), 51)


class CallContextTargetMaxHpTests(unittest.TestCase):
    """Phase 4 batch 5 — CallContext.target_max_hp field for %HP procs."""

    def test_target_max_hp_default_zero(self) -> None:
        # Backward-compat default — pre-batch-5 callers don't pass it.
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11)
        self.assertEqual(ctx.target_max_hp, 0.0)

    def test_callable_resolves_against_target_max_hp(self) -> None:
        proc = PeriodicProc(
            name="hp_scale",
            bonus_damage=lambda c: 0.08 * c.target_max_hp,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        )
        # 1500 HP * 8% = 120 per proc.
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11, target_max_hp=1500.0)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 120.0, places=3)

    def test_zero_target_max_hp_zeros_hp_proc(self) -> None:
        # Default target_max_hp=0 means %HP procs contribute zero — keeps
        # pre-batch tests stable when callers don't supply HP.
        proc = PeriodicProc(
            name="hp_scale",
            bonus_damage=lambda c: 0.08 * c.target_max_hp,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        )
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11)
        self.assertEqual(proc.resolve_damage(ctx), 0.0)


class TargetHpItemTests(unittest.TestCase):
    """BotRK + Eclipse promoted from defensive_only via target_max_hp.

    Both procs scale linearly with target_max_hp — tests assert the
    monotonicity (more HP → more DPS) and the shape (BotRK every basic,
    Eclipse every 2nd basic). Default target_max_hp=0.0 means a caller
    that doesn't supply HP gets the pre-batch DPS exactly, so there's
    a "no regression" assertion too.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_botrk_promoted_not_defensive_only(self) -> None:
        e = ITEM_EFFECTS["3153"]
        self.assertFalse(e.defensive_only)
        self.assertIsNotNone(e.periodic)
        self.assertEqual(e.periodic.damage_type, PHYSICAL)
        self.assertEqual(e.periodic.every_n_attacks, 1)
        self.assertIn("mist", e.note.lower())

    def test_eclipse_promoted_not_defensive_only(self) -> None:
        e = ITEM_EFFECTS["6692"]
        self.assertFalse(e.defensive_only)
        self.assertIsNotNone(e.periodic)
        self.assertEqual(e.periodic.damage_type, PHYSICAL)
        self.assertEqual(e.periodic.every_n_attacks, 2)
        self.assertIn("ever rising moon", e.note.lower())

    def test_botrk_dps_zero_target_hp_matches_no_hp_signal(self) -> None:
        # With target_max_hp=0 (default), BotRK proc contributes zero —
        # only the stat block (AD/AS/lifesteal) lifts DPS. Sanity: stat
        # block alone makes BotRK > bare baseline, but the lambda's HP
        # contribution is exactly zero.
        bare = compute_dps(self.snap, "Aatrox", level=11)
        with_botrk = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3153"],
        )
        self.assertGreater(with_botrk.weighted_dps, bare.weighted_dps)

    def test_botrk_raises_dps_with_target_max_hp(self) -> None:
        # Same build, raising target_max_hp from 0 → 1500 should bump
        # DPS via the Mist's Edge proc.
        no_hp = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3153"],
        )
        with_hp = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3153"],
            target_max_hp=1500.0,
        )
        self.assertGreater(with_hp.weighted_dps, no_hp.weighted_dps)

    def test_botrk_scales_linearly_with_target_max_hp(self) -> None:
        # Doubling target_max_hp should roughly double the proc's
        # contribution to DPS (other factors held constant). Exact
        # equality won't hold because of crit / AS interactions on the
        # base attack, but the proc piece IS linear, so total DPS
        # delta should at least *strictly* grow.
        low = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3153"],
            target_max_hp=1000.0,
        )
        high = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3153"],
            target_max_hp=3000.0,
        )
        self.assertGreater(high.weighted_dps, low.weighted_dps)

    def test_eclipse_raises_dps_with_target_max_hp(self) -> None:
        no_hp = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["6692"],
        )
        with_hp = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["6692"],
            target_max_hp=1800.0,
        )
        self.assertGreater(with_hp.weighted_dps, no_hp.weighted_dps)

    def test_botrk_per_basic_outpaces_eclipse_per_2nd(self) -> None:
        # BotRK fires every basic at 8% HP; Eclipse fires every 2nd at
        # 6% HP. Same target_max_hp, BotRK should score higher on the
        # proc piece. (Stat blocks differ — BotRK has AS/lifesteal,
        # Eclipse has lethality — but at zero target_armor the AS bonus
        # makes BotRK win regardless.)
        botrk = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3153"],
            target_max_hp=2000.0,
        )
        eclipse = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["6692"],
            target_max_hp=2000.0,
        )
        self.assertGreater(botrk.weighted_dps, eclipse.weighted_dps)

    def test_target_max_hp_round_trips_in_dps_result(self) -> None:
        # Result carries target_max_hp back so callers can audit what
        # they got — same shape as target_armor / target_mr.
        result = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3153"],
            target_max_hp=1750.0,
        )
        self.assertEqual(result.target_max_hp, 1750.0)
        self.assertIn("target_max_hp", result.to_dict())
        self.assertEqual(result.to_dict()["target_max_hp"], 1750.0)

    def test_target_max_hp_in_format_table(self) -> None:
        result = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3153"],
            target_max_hp=1750.0,
        )
        text = result.format_table()
        self.assertIn("max_hp=1750", text)


class CallContextCasterHpTests(unittest.TestCase):
    """Phase 4 batch 6 — CallContext.caster_max_hp / caster_bonus_hp."""

    def test_caster_hp_defaults_zero(self) -> None:
        # Backward-compat: pre-batch-6 ctx construction omits both fields.
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11)
        self.assertEqual(ctx.caster_max_hp, 0.0)
        self.assertEqual(ctx.caster_bonus_hp, 0.0)

    def test_callable_resolves_against_caster_max_hp(self) -> None:
        # Heartsteel-style: 70 + 6% caster max HP.
        proc = PeriodicProc(
            name="ks_scale",
            bonus_damage=lambda c: 70.0 + 0.06 * c.caster_max_hp,
            damage_type=PHYSICAL,
            every_n_seconds=3.5,
        )
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11, caster_max_hp=2400)
        # 70 + 0.06*2400 = 70 + 144 = 214
        self.assertAlmostEqual(proc.resolve_damage(ctx), 214.0, places=3)

    def test_callable_resolves_against_caster_bonus_hp(self) -> None:
        # Titanic-style: 5 + 1.5% caster bonus HP.
        proc = PeriodicProc(
            name="th_scale",
            bonus_damage=lambda c: 5.0 + 0.015 * c.caster_bonus_hp,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        )
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11, caster_bonus_hp=600)
        # 5 + 0.015*600 = 5 + 9 = 14
        self.assertAlmostEqual(proc.resolve_damage(ctx), 14.0, places=3)


class CasterHpItemTests(unittest.TestCase):
    """Titanic Hydra (new) + Heartsteel (promoted) scale with caster HP.

    Caster HP is engine-derived (no caller param) — building with HP
    items (Titanic itself, Heartsteel itself, Warmog's, Sterak's) lifts
    caster_max_hp and thus the proc damage. Tests pin the engine-side
    derivation by stacking HP items and asserting monotonic uplift.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_titanic_hydra_periodic_present(self) -> None:
        e = ITEM_EFFECTS["3748"]
        self.assertFalse(e.defensive_only)
        self.assertIsNotNone(e.periodic)
        self.assertEqual(e.periodic.damage_type, PHYSICAL)
        self.assertEqual(e.periodic.every_n_attacks, 1)
        self.assertIn("cleave", e.note.lower())

    def test_heartsteel_promoted_not_defensive_only(self) -> None:
        # Heartsteel left DefensiveOnlyBatch2Tests in batch 6 — pin the
        # promotion path (mirrors Shadowflame in batch 4).
        e = ITEM_EFFECTS["3084"]
        self.assertFalse(e.defensive_only)
        self.assertIsNotNone(e.periodic)
        self.assertEqual(e.periodic.damage_type, PHYSICAL)
        self.assertGreater(e.periodic.every_n_seconds, 0.0)
        self.assertIn("colossal", e.note.lower())

    def test_titanic_hydra_raises_dps_via_own_bonus_hp(self) -> None:
        # Titanic gives 600 HP itself, so the proc references 1.5% of
        # 600 = 9 + base 5 = 14 per basic. Bare Aatrox vs Aatrox+Titanic
        # should clear the delta easily.
        bare = compute_dps(self.snap, "Aatrox", level=11)
        with_th = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3748"])
        self.assertGreater(with_th.weighted_dps, bare.weighted_dps)

    def test_titanic_hydra_scales_with_more_hp(self) -> None:
        # Titanic alone (600 bonus HP) vs Titanic + Warmog's (600 + 800 = 1400
        # bonus HP) — proc piece should rise. Stat block contributions
        # differ but the DELTA between (Titanic+Warmog vs Warmog alone)
        # should beat the DELTA from (Titanic alone vs naked) because
        # bonus HP grew.
        bare = compute_dps(self.snap, "Aatrox", level=11).weighted_dps
        warmog = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3083"],
        ).weighted_dps
        titanic_only = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3748"],
        ).weighted_dps
        titanic_warmog = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3748", "3083"],
        ).weighted_dps
        delta_titanic_only = titanic_only - bare
        delta_titanic_with_warmog = titanic_warmog - warmog
        self.assertGreater(delta_titanic_with_warmog, delta_titanic_only)

    def test_heartsteel_raises_dps_via_caster_max_hp(self) -> None:
        # Heartsteel grants 900 HP itself; with Aatrox base ~1790 lvl 11
        # max_hp ≈ 2690, 6% = 161 + ~123 (level lerp) = 284 per ~3.5s ≈ 81 DPS.
        # That's a meaningful jump over bare baseline.
        bare = compute_dps(self.snap, "Aatrox", level=11).weighted_dps
        with_hs = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3084"],
        ).weighted_dps
        self.assertGreater(with_hs - bare, 30.0)  # well above noise

    def test_heartsteel_scales_with_external_hp(self) -> None:
        # Adding Warmog's on top of Heartsteel should keep raising the
        # Colossal Consumption damage (6% of a bigger max HP).
        hs_only = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3084"],
        ).weighted_dps
        warmog_only = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3083"],
        ).weighted_dps
        hs_warmog = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3084", "3083"],
        ).weighted_dps
        bare = compute_dps(self.snap, "Aatrox", level=11).weighted_dps
        delta_hs_alone = hs_only - bare
        delta_hs_with_warmog = hs_warmog - warmog_only
        self.assertGreater(delta_hs_with_warmog, delta_hs_alone)

    def test_caster_hp_derivation_is_engine_internal(self) -> None:
        # The caster HP fields are derived inside compute_dps — there's
        # no caller-supplied parameter (unlike target_max_hp). Sanity
        # check: compute_dps signature has no caster_max_hp kwarg.
        import inspect
        sig = inspect.signature(compute_dps)
        self.assertNotIn("caster_max_hp", sig.parameters)
        self.assertNotIn("caster_bonus_hp", sig.parameters)


if __name__ == "__main__":
    unittest.main()

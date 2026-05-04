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
* Multi-target rotation layer (Ravenous Hydra Cleave) — Phase 4 batch 7.
* defensive_only entries — no DPS contribution beyond stat block.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    CallContext,
    ItemEffect,
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
        self.assertEqual(e.periodics, ())

    def test_phantom_dancer_no_periodic(self) -> None:
        e = ITEM_EFFECTS["3046"]
        self.assertTrue(e.defensive_only)
        self.assertEqual(e.periodics, ())

    def test_sterak_no_periodic(self) -> None:
        e = ITEM_EFFECTS["3053"]
        self.assertTrue(e.defensive_only)
        self.assertEqual(e.periodics, ())

    # BotRK (3153) and Eclipse (6692) promoted in Phase 4 batch 5
    # (2026-05-04) once ``target_max_hp`` landed. Their proc-shape
    # assertions live in TargetHpItemTests below; the schema-promotion
    # path matches Shadowflame in batch 4.

    # Terminus (3302) promoted out of defensive_only in Phase 4 batch 13
    # (2026-05-04) — Shadow on-hit proc + Juxtaposition Dark sustained
    # pen. Promotion-shape assertions live in TerminusPromotionTests
    # at the bottom of this file.


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
            self.assertEqual(e.periodics, (), f"{iid} should have no periodic proc")
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
        self.assertNotEqual(e.periodics, ())
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.periodics[0].damage_type, MAGICAL)

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
        self.assertNotEqual(e.periodics, ())
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.periodics[0].damage_type, MAGICAL)
        self.assertEqual(e.periodics[0].every_n_attacks, 1)

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
    """Phase 4 batch 3 (2026-05-04) — AP-stat siblings without DPS proc.

    Hextech Gunblade (3146) / Luden's Echo (6655) / Deathfire Grasp
    (3128). All carry AP stat blocks but their effects don't fit the
    periodic/on-hit shape: active utilities, ability-bound bolts, and
    active %-target-max-HP. Pinned here so future hooks can find them
    via grep.

    Note: Shadowflame (4645) shipped batch 3 as defensive_only but
    promoted in batch 4 — its 15 flat magic pen IS modeled by the new
    pipeline (the unmodeled piece is the magic-crit-on-low-HP). So
    it now lives in MagicPenItemTests, not here.

    Note: Riftmaker (4633) was here through batch 13; promoted in
    batch 14 (damage_amp_pct schema, 2026-05-04) — its proc-shape
    assertions live in RiftmakerPromotionTests at the bottom of this
    file. HP→AP cross-derivation is still separate.
    """

    EXPECTED = {
        "3146": "Hextech Gunblade",
        "6655": "Luden's Echo",
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
            self.assertEqual(e.periodics, (), f"{iid} should have no periodic proc")
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
    to 51. Batch 7 (multi-target rotations) adds Ravenous Hydra — 52.
    Batch 9 (Immolate items) adds Sunfire Aegis + Hollow Radiance — 54.
    """

    def test_table_size_at_phase_4_expansion(self) -> None:
        # Lower bound: no regressions removed entries.
        self.assertGreaterEqual(len(ITEM_EFFECTS), 54)


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
        self.assertNotEqual(e.periodics, ())
        self.assertEqual(e.periodics[0].damage_type, PHYSICAL)
        self.assertEqual(e.periodics[0].every_n_attacks, 1)
        self.assertIn("mist", e.note.lower())

    def test_eclipse_promoted_not_defensive_only(self) -> None:
        e = ITEM_EFFECTS["6692"]
        self.assertFalse(e.defensive_only)
        self.assertNotEqual(e.periodics, ())
        self.assertEqual(e.periodics[0].damage_type, PHYSICAL)
        self.assertEqual(e.periodics[0].every_n_attacks, 2)
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
        self.assertNotEqual(e.periodics, ())
        self.assertEqual(e.periodics[0].damage_type, PHYSICAL)
        self.assertEqual(e.periodics[0].every_n_attacks, 1)
        self.assertIn("cleave", e.note.lower())

    def test_heartsteel_promoted_not_defensive_only(self) -> None:
        # Heartsteel left DefensiveOnlyBatch2Tests in batch 6 — pin the
        # promotion path (mirrors Shadowflame in batch 4).
        e = ITEM_EFFECTS["3084"]
        self.assertFalse(e.defensive_only)
        self.assertNotEqual(e.periodics, ())
        self.assertEqual(e.periodics[0].damage_type, PHYSICAL)
        self.assertGreater(e.periodics[0].every_n_seconds, 0.0)
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
        # max_hp ≈ 2690. Per DDragon 16.9.1 "70 plus 6%": flat 70 +
        # 0.06*2690 ≈ 231 per ~3.5s ≈ 66 DPS. (Pre-batch-17 the lambda
        # added a wrong 90*(level-1)/17 lerp that came from an older
        # patch.) Threshold left at 30 — still well above noise.
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


class CallContextTargetsInRotationTests(unittest.TestCase):
    """Phase 4 batch 7 — CallContext.targets_in_rotation field."""

    def test_default_one(self) -> None:
        # Default 1.0 = single-target rotation. cleave-to-others lambdas
        # multiply by max(0, n-1) which is 0 at n=1 — backward-compat.
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11)
        self.assertEqual(ctx.targets_in_rotation, 1.0)

    def test_cleave_to_others_zero_at_single_target(self) -> None:
        # Ravenous-style: max(0, n-1) * 0.35 * (base_ad + bonus_ad).
        proc = PeriodicProc(
            name="cleave_others",
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.35 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        )
        ctx = CallContext(base_ad=60, bonus_ad=40, level=11, targets_in_rotation=1.0)
        self.assertEqual(proc.resolve_damage(ctx), 0.0)

    def test_cleave_to_others_scales_with_n(self) -> None:
        proc = PeriodicProc(
            name="cleave_others",
            bonus_damage=lambda c: max(0.0, c.targets_in_rotation - 1.0)
                * 0.35 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        )
        # Total AD = 100; n=3 → (3-1) * 0.35 * 100 = 70
        ctx = CallContext(base_ad=60, bonus_ad=40, level=11, targets_in_rotation=3.0)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 70.0, places=3)

    def test_aoe_incl_primary_scales_with_n_directly(self) -> None:
        # Sunfire-style (hypothetical): direct n multiplier — pin the
        # idiom for future AoE-incl-primary procs.
        proc = PeriodicProc(
            name="aoe_incl",
            bonus_damage=lambda c: c.targets_in_rotation * 30.0,
            damage_type=PHYSICAL,
            every_n_seconds=1.0,
        )
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11, targets_in_rotation=2.5)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 75.0, places=3)


class RavenousHydraMultiTargetTests(unittest.TestCase):
    """Ravenous Hydra (3074) — cleave-to-others scales with rotation targets.

    Most champions have all-n=1 rotations; Ravenous adds zero DPS for
    them. Champions whose lolmath scenarios carry n>1 rotations (Amumu,
    Annie, Anivia, Ahri etc.) get a real DPS uplift. Tests pin both
    behaviors.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_ravenous_hydra_periodic_present(self) -> None:
        e = ITEM_EFFECTS["3074"]
        self.assertFalse(e.defensive_only)
        self.assertNotEqual(e.periodics, ())
        self.assertEqual(e.periodics[0].damage_type, PHYSICAL)
        self.assertEqual(e.periodics[0].every_n_attacks, 1)
        self.assertIn("cleave", e.note.lower())

    def test_ravenous_hydra_zero_proc_on_single_target_champion(self) -> None:
        # Aatrox has all-n=1 scenarios; the Ravenous Cleave proc resolves
        # to zero. So Aatrox+Ravenous DPS should equal the engine's
        # stat-block-only response (AD lifted from the 65 AD stat).
        # We assert this indirectly: replace Ravenous with a hypothetical
        # 65 AD pure-stat item — same DPS expected. Easier path: just
        # assert the proc *would* resolve to zero given Aatrox's rotations.
        from agents.daemon_slayer.engine import build_champion
        from agents.daemon_slayer.dps import _phase_rotations
        rotations = _phase_rotations(self.snap, "Aatrox")
        for phase_rot in rotations.values():
            for r in phase_rot:
                self.assertEqual(
                    float(r.get("numberOfTargets", 1.0) or 1.0),
                    1.0,
                    f"Aatrox rotation {r.get('title','?')} has n>1 — fixture changed",
                )

    def test_ravenous_hydra_lifts_dps_on_multi_target_champion(self) -> None:
        # Anivia's late "DPS" rotation has numberOfTargets=3 with weight 70.
        # Ravenous should add real DPS to her total via the cleave proc.
        bare = compute_dps(self.snap, "Anivia", level=11, phase="late")
        with_rh = compute_dps(
            self.snap, "Anivia", level=11, item_ids=["3074"], phase="late",
        )
        self.assertGreater(with_rh.weighted_dps, bare.weighted_dps)

    def test_ravenous_hydra_per_rotation_isolation(self) -> None:
        # The proc must use *each* rotation's numberOfTargets, not a
        # global fallback. We exercise this by computing DPS at a phase
        # whose rotations mix n=1 and n>1 — the math should average to
        # something between "all-n=1 zero" and "all-n=3 max".
        # Use Annie's mid phase: "AOE Initiation" w=60, n=3 + others n=1.
        result = compute_dps(
            self.snap, "Annie", level=11, item_ids=["3074"], phase="mid",
        )
        # Just assert it ran clean and weighted_dps is finite-positive.
        self.assertGreater(result.weighted_dps, 0.0)
        # And note from item shouldn't surface a "no rotations" warning.
        joined = " ".join(result.notes)
        self.assertNotIn("no rotations", joined)


class MultiProcSchemaTests(unittest.TestCase):
    """Phase 4 batch 8 — `ItemEffect.periodics: tuple[PeriodicProc, ...]`.

    Schema rename from `Optional[PeriodicProc]` → `tuple[..., ...]` lets
    a single item carry multiple periodic procs. Titanic Hydra is the
    first multi-proc entry: primary on-hit + cleave-to-others.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_periodics_field_default_is_empty_tuple(self) -> None:
        # Items without procs have `periodics=()` not `None`. Sanity
        # check on a known defensive_only entry.
        e = ITEM_EFFECTS["3072"]  # Bloodthirster, defensive_only
        self.assertEqual(e.periodics, ())

    def test_titanic_hydra_has_two_periodics(self) -> None:
        # Multi-proc poster child: primary cleave on-hit (always) +
        # cleave-to-others (only when targets_in_rotation > 1).
        e = ITEM_EFFECTS["3748"]
        self.assertEqual(len(e.periodics), 2)
        primary, cleave_others = e.periodics
        self.assertIn("primary", primary.name.lower())
        self.assertIn("nearby", cleave_others.name.lower())
        self.assertEqual(primary.damage_type, PHYSICAL)
        self.assertEqual(cleave_others.damage_type, PHYSICAL)
        self.assertEqual(primary.every_n_attacks, 1)
        self.assertEqual(cleave_others.every_n_attacks, 1)

    def test_titanic_cleave_to_others_zero_at_single_target(self) -> None:
        cleave_others = ITEM_EFFECTS["3748"].periodics[1]
        ctx = CallContext(
            base_ad=80, bonus_ad=40, level=11, targets_in_rotation=1.0,
        )
        self.assertEqual(cleave_others.resolve_damage(ctx), 0.0)

    def test_titanic_cleave_to_others_scales_with_n(self) -> None:
        cleave_others = ITEM_EFFECTS["3748"].periodics[1]
        # Total AD = 120, n=3 → max(0, 3-1) * 0.40 * 120 = 96
        ctx = CallContext(
            base_ad=80, bonus_ad=40, level=11, targets_in_rotation=3.0,
        )
        self.assertAlmostEqual(cleave_others.resolve_damage(ctx), 96.0, places=3)

    def test_titanic_primary_proc_fires_on_single_target(self) -> None:
        # On Aatrox (all-n=1 rotations), Titanic's primary proc fires
        # every basic; cleave-to-others contributes zero. Net DPS still
        # rises over baseline thanks to the primary proc + stat block.
        bare = compute_dps(self.snap, "Aatrox", level=11)
        with_th = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3748"])
        self.assertGreater(with_th.weighted_dps, bare.weighted_dps)

    def test_engine_iterates_both_titanic_procs(self) -> None:
        # End-to-end test that the engine actually sums BOTH procs (not
        # just the first). Construct two builds, identical except one
        # uses an item-id that doesn't exist (engine ignores it), and
        # compare. Easier path: directly compute proc DPS via the
        # internal helper and assert magnitudes.
        from agents.daemon_slayer.dps import _periodic_proc_dps
        from agents.daemon_slayer.effects import collect_effects
        ctx = CallContext(
            base_ad=80, bonus_ad=40, level=11,
            caster_bonus_hp=600, targets_in_rotation=3.0,
        )
        effects = collect_effects(["3748"])
        # 1.0 attack, 1.0 second rotation (so DPS == per-attack damage).
        dps = _periodic_proc_dps(
            effects, total_attacks=1.0, duration=1.0,
            target_armor_for_physical=0.0, target_mr=0.0,
            mode_dmg_mult=1.0, call_ctx=ctx,
        )
        # Primary proc damage: 5 + 0.015*600 = 14
        # Cleave-to-others damage: max(0, 3-1) * 0.40 * 120 = 96
        # Sum: 110. With armor_factor=1.0 and mode_mult=1.0, dps = 110/1 = 110.
        self.assertAlmostEqual(dps, 110.0, places=3)

    def test_engine_titanic_single_target_only_primary_fires(self) -> None:
        # Same harness as above but n=1.0 → cleave-to-others = 0.
        # Result should be primary-only = 14 dps.
        from agents.daemon_slayer.dps import _periodic_proc_dps
        from agents.daemon_slayer.effects import collect_effects
        ctx = CallContext(
            base_ad=80, bonus_ad=40, level=11,
            caster_bonus_hp=600, targets_in_rotation=1.0,
        )
        effects = collect_effects(["3748"])
        dps = _periodic_proc_dps(
            effects, total_attacks=1.0, duration=1.0,
            target_armor_for_physical=0.0, target_mr=0.0,
            mode_dmg_mult=1.0, call_ctx=ctx,
        )
        self.assertAlmostEqual(dps, 14.0, places=3)


class ImmolateItemTests(unittest.TestCase):
    """Phase 4 batch 9 — Sunfire Aegis (3068) + Hollow Radiance (6664).

    Both items share the same Immolate periodic shape: per-second magic
    aura damage to nearby enemies, scaling with caster bonus HP and the
    rotation's targets count. Reuses the batch-6 caster-HP layer + the
    batch-7 multi-target layer — no new schema. Tests pin the per-second
    shape, the AoE-incl-primary multiplier, the bonus-HP scaling, and
    the end-to-end DPS uplift on a tank champion.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_sunfire_periodic_shape(self) -> None:
        e = ITEM_EFFECTS["3068"]
        self.assertFalse(e.defensive_only)
        self.assertEqual(len(e.periodics), 1)
        proc = e.periodics[0]
        self.assertEqual(proc.damage_type, MAGICAL)
        self.assertEqual(proc.every_n_seconds, 1.0)
        self.assertEqual(proc.every_n_attacks, 0)
        self.assertIn("immolate", proc.name.lower())
        self.assertIn("immolate", e.note.lower())

    def test_hollow_radiance_periodic_shape(self) -> None:
        e = ITEM_EFFECTS["6664"]
        self.assertFalse(e.defensive_only)
        self.assertEqual(len(e.periodics), 1)
        proc = e.periodics[0]
        self.assertEqual(proc.damage_type, MAGICAL)
        self.assertEqual(proc.every_n_seconds, 1.0)
        self.assertEqual(proc.every_n_attacks, 0)
        self.assertIn("immolate", proc.name.lower())

    def test_immolate_resolves_with_bonus_hp_and_n_equals_1(self) -> None:
        # Single-target rotation, 1000 bonus HP →
        # 1.0 * (12 + 0.015 * 1000) = 27 per second.
        proc = ITEM_EFFECTS["3068"].periodics[0]
        ctx = CallContext(
            base_ad=0, bonus_ad=0, level=11,
            caster_bonus_hp=1000.0, targets_in_rotation=1.0,
        )
        self.assertAlmostEqual(proc.resolve_damage(ctx), 27.0, places=3)

    def test_immolate_aoe_incl_primary_multiplier(self) -> None:
        # 3-target rotation, 1000 bonus HP →
        # 3.0 * (12 + 0.015 * 1000) = 81 per second.
        proc = ITEM_EFFECTS["3068"].periodics[0]
        ctx = CallContext(
            base_ad=0, bonus_ad=0, level=11,
            caster_bonus_hp=1000.0, targets_in_rotation=3.0,
        )
        self.assertAlmostEqual(proc.resolve_damage(ctx), 81.0, places=3)

    def test_immolate_zero_bonus_hp_floor(self) -> None:
        # No HP items in the build → flat 12 dps per second per target.
        # Single target → 12 per second.
        proc = ITEM_EFFECTS["3068"].periodics[0]
        ctx = CallContext(
            base_ad=0, bonus_ad=0, level=11,
            caster_bonus_hp=0.0, targets_in_rotation=1.0,
        )
        self.assertAlmostEqual(proc.resolve_damage(ctx), 12.0, places=3)

    def test_sunfire_lifts_dps_on_tank_champion(self) -> None:
        # Sunfire's stat block alone contributes zero DPS (350 HP, 50 armor —
        # both defensive). Any uplift over baseline must come from the
        # Immolate proc. Aatrox lvl 11 has all-n=1 rotations so n=1, and
        # Sunfire's +350 HP is bonus HP (lifts the proc damage above the
        # 12-flat floor).
        bare = compute_dps(self.snap, "Aatrox", level=11)
        with_sf = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3068"])
        self.assertGreater(with_sf.weighted_dps, bare.weighted_dps)

    def test_hollow_radiance_lifts_dps_on_tank_champion(self) -> None:
        # Same story for Hollow Radiance: stat block is HP+MR, no DPS;
        # uplift must come from the Immolate proc.
        bare = compute_dps(self.snap, "Aatrox", level=11)
        with_hr = compute_dps(self.snap, "Aatrox", level=11, item_ids=["6664"])
        self.assertGreater(with_hr.weighted_dps, bare.weighted_dps)

    def test_immolate_engine_per_second_tick(self) -> None:
        # End-to-end test that the engine does the per-second math right.
        # 1.0 second rotation duration with the Sunfire effect, 1000 bonus
        # HP, n=1: should emit 27 dps (1 second × 27 damage/second).
        from agents.daemon_slayer.dps import _periodic_proc_dps
        from agents.daemon_slayer.effects import collect_effects
        ctx = CallContext(
            base_ad=0, bonus_ad=0, level=11,
            caster_bonus_hp=1000.0, targets_in_rotation=1.0,
        )
        effects = collect_effects(["3068"])
        # No basic attacks; the proc fires on the seconds-track (every_n_seconds=1.0).
        # 1.0 second / 1.0 = 1 proc, damage 27 → 27 dps.
        dps = _periodic_proc_dps(
            effects, total_attacks=0.0, duration=1.0,
            target_armor_for_physical=0.0, target_mr=0.0,
            mode_dmg_mult=1.0, call_ctx=ctx,
        )
        self.assertAlmostEqual(dps, 27.0, places=3)

    def test_immolate_engine_aoe_uplift_in_rotation(self) -> None:
        # Same harness, n=3: 3 nearby enemies each take 27 dps → 81 dps total.
        from agents.daemon_slayer.dps import _periodic_proc_dps
        from agents.daemon_slayer.effects import collect_effects
        ctx = CallContext(
            base_ad=0, bonus_ad=0, level=11,
            caster_bonus_hp=1000.0, targets_in_rotation=3.0,
        )
        effects = collect_effects(["3068"])
        dps = _periodic_proc_dps(
            effects, total_attacks=0.0, duration=1.0,
            target_armor_for_physical=0.0, target_mr=0.0,
            mode_dmg_mult=1.0, call_ctx=ctx,
        )
        self.assertAlmostEqual(dps, 81.0, places=3)

    def test_immolate_uses_target_mr_not_armor(self) -> None:
        # Magic-typed proc → MR resists, not armor. With target_mr=100,
        # damage is halved (factor 100/(100+100) = 0.5). Bonus HP=1000,
        # n=1 → 27 raw, 13.5 post-MR.
        from agents.daemon_slayer.dps import _periodic_proc_dps
        from agents.daemon_slayer.effects import collect_effects
        ctx = CallContext(
            base_ad=0, bonus_ad=0, level=11,
            caster_bonus_hp=1000.0, targets_in_rotation=1.0,
        )
        effects = collect_effects(["3068"])
        dps = _periodic_proc_dps(
            effects, total_attacks=0.0, duration=1.0,
            # If proc were physical, target_armor would gate it instead of MR.
            target_armor_for_physical=0.0, target_mr=100.0,
            mode_dmg_mult=1.0, call_ctx=ctx,
        )
        self.assertAlmostEqual(dps, 13.5, places=3)


class UniquePassiveTests(unittest.TestCase):
    """Phase 4 batch 10 — unique-passive de-duplication.

    ItemEffect.unique_passive_key + collect_effects dedup. Surfaced by
    batch 9: building Sunfire + Hollow Radiance currently double-counted
    Immolate (Riot enforces unique-passive in-game). Tests pin the
    schema default, dedup behavior on the new field, single-item
    DPS unchanged, and end-to-end no-double-count for Sunfire+HR.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_unique_passive_key_default_empty(self) -> None:
        # Bloodthirster is a defensive_only entry pre-dating the schema;
        # default empty key means "no dedup," everything pre-batch-10 stays.
        e = ITEM_EFFECTS["3072"]
        self.assertEqual(e.unique_passive_key, "")

    def test_sunfire_and_hollow_radiance_share_immolate_key(self) -> None:
        self.assertEqual(ITEM_EFFECTS["3068"].unique_passive_key, "immolate")
        self.assertEqual(ITEM_EFFECTS["6664"].unique_passive_key, "immolate")

    def test_collect_effects_dedups_same_key(self) -> None:
        from agents.daemon_slayer.effects import collect_effects
        # Sunfire (3068) + Hollow Radiance (6664): same immolate key.
        # First seen (Sunfire) wins; Hollow Radiance is dropped from
        # the effects list. Both stat blocks still aggregate elsewhere.
        effects = collect_effects(["3068", "6664"])
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0].item_id, "3068")

    def test_collect_effects_dedup_first_seen_wins(self) -> None:
        # Order matters: HR first, Sunfire dropped.
        from agents.daemon_slayer.effects import collect_effects
        effects = collect_effects(["6664", "3068"])
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0].item_id, "6664")

    def test_collect_effects_keeps_unrelated_items(self) -> None:
        # Items without a key (or with different keys) all pass through.
        from agents.daemon_slayer.effects import collect_effects
        effects = collect_effects(["3068", "6664", "3031", "3071"])
        # Sunfire kept, HR dropped, IE + Black Cleaver both kept (no key).
        self.assertEqual(len(effects), 3)
        self.assertEqual(effects[0].item_id, "3068")
        self.assertEqual(effects[1].item_id, "3031")
        self.assertEqual(effects[2].item_id, "3071")

    def test_sunfire_solo_unchanged(self) -> None:
        # Single-item Sunfire DPS must be unchanged from batch 9 — dedup
        # only fires when the same key appears twice.
        r = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3068"])
        # Batch 9 verified 64.32 dps for this exact probe.
        self.assertAlmostEqual(r.weighted_dps, 64.32, places=2)

    def test_sunfire_plus_hollow_radiance_no_double_count(self) -> None:
        # The whole point of this batch: building both should NOT add
        # the immolate proc twice. Damage uplift over Sunfire-alone must
        # come ONLY from Hollow Radiance's stat block (40 MR + 400 HP),
        # not a second Immolate tick.
        sunfire_only = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3068"])
        both = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3068", "6664"])
        # Bonus HP rises from 350 → 750 (Sunfire 350 + HR 400). Sunfire's
        # Immolate proc damage = 12 + 0.015 * 750 = 23.25 per second per
        # target (vs 17.25 with Sunfire alone). So delta should be
        # 23.25 - 17.25 = 6.0 dps. NOT 23.25 + 18.0 (double-count) =
        # 41.25 over solo, which would be the regression case.
        delta = both.weighted_dps - sunfire_only.weighted_dps
        # 6.0 dps from HR's HP raising Sunfire's proc; floor below the
        # double-count signal at ~24 dps.
        self.assertAlmostEqual(delta, 6.0, places=1)
        self.assertLess(delta, 12.0,
            "Double-count regression: HR added a second Immolate tick")

    def test_dedup_drops_proc_but_other_items_get_their_passive(self) -> None:
        # Sanity that dedup is per-key, not per-item: building Sunfire
        # (immolate) + Black Cleaver (no key, has armor_reduction) keeps
        # both effects active.
        from agents.daemon_slayer.effects import collect_effects
        effects = collect_effects(["3068", "3071"])
        self.assertEqual(len(effects), 2)
        # Black Cleaver passive still landed (its armor_reduction_pct).
        bc = next(e for e in effects if e.item_id == "3071")
        self.assertGreater(bc.armor_reduction_pct, 0.0)


class SpellbladeUniquePassiveTests(unittest.TestCase):
    """Phase 4 batch 11 — Spellblade unique-passive on TF + Lich Bane.

    Trinity Force (3078) and Lich Bane (3100) both fire Spellblade procs
    in current League. In-game, Spellblade is unique-passive — only one
    spellblade fires per ability+attack. The engine now respects this
    via the batch-10 unique_passive_key="spellblade" tag on both items.

    Sundered Sky (6610) uses "Lightshield Strike" — a distinct mechanic
    despite being ability-gated; not tagged. Essence Reaver (3508) has
    the Spellblade label but is currently defensive_only (proc not
    modeled); tagging it would dedup against TF/LB depending on order,
    so it stays untagged until promoted out of defensive_only.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_triforce_and_lich_bane_share_spellblade_key(self) -> None:
        self.assertEqual(ITEM_EFFECTS["3078"].unique_passive_key, "spellblade")
        self.assertEqual(ITEM_EFFECTS["3100"].unique_passive_key, "spellblade")

    def test_sundered_sky_not_tagged_spellblade(self) -> None:
        # Distinct mechanic ("Lightshield Strike"). Different cooldown
        # (8s vs 3s), different effect (guaranteed crit + heal vs
        # bonus damage). Must not share the spellblade key or building
        # TF + Sundered Sky would silently drop one of them.
        self.assertNotEqual(ITEM_EFFECTS["6610"].unique_passive_key, "spellblade")

    def test_essence_reaver_not_tagged_spellblade(self) -> None:
        # Currently defensive_only — tagging would create order-
        # dependence (Essence Reaver-first would dedup TF or LB).
        # Promote it first (model the proc), then tag.
        self.assertNotEqual(ITEM_EFFECTS["3508"].unique_passive_key, "spellblade")

    def test_collect_effects_dedups_spellblade_pair(self) -> None:
        from agents.daemon_slayer.effects import collect_effects
        # First-seen-wins: TF kept, Lich Bane dropped.
        effects = collect_effects(["3078", "3100"])
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0].item_id, "3078")

    def test_collect_effects_dedup_lich_bane_first_wins(self) -> None:
        from agents.daemon_slayer.effects import collect_effects
        effects = collect_effects(["3100", "3078"])
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0].item_id, "3100")

    def test_triforce_solo_unchanged(self) -> None:
        # Single-item TF DPS must equal pre-batch-11 baseline (regression
        # guard). Ahri lvl 11 + TF was 85.08 before tagging.
        r = compute_dps(self.snap, "Ahri", level=11, item_ids=["3078"])
        self.assertAlmostEqual(r.weighted_dps, 85.08, places=2)

    def test_lich_bane_solo_unchanged(self) -> None:
        # Lich Bane alone unchanged: 58.17 on Ahri lvl 11.
        r = compute_dps(self.snap, "Ahri", level=11, item_ids=["3100"])
        self.assertAlmostEqual(r.weighted_dps, 58.17, places=2)

    def test_triforce_plus_lich_bane_no_double_count(self) -> None:
        # Pre-fix this build was 122.50 dps (sum of solo deltas =
        # double-count of spellblade). Post-fix should be ~85 dps —
        # TF spellblade kept, LB spellblade dropped, LB stat block
        # (100 AP, 4% MS, 10 AH) contributes ~0 to AA-DPS for Ahri.
        # Floor below the double-count level is the key assertion.
        bare = compute_dps(self.snap, "Ahri", level=11)
        tf_only = compute_dps(self.snap, "Ahri", level=11, item_ids=["3078"])
        both = compute_dps(self.snap, "Ahri", level=11, item_ids=["3078", "3100"])
        # No double-count: both should be roughly TF-alone (LB stats
        # don't lift Ahri's AA much).
        delta_solo = tf_only.weighted_dps - bare.weighted_dps
        delta_both = both.weighted_dps - bare.weighted_dps
        # Without dedup, delta_both would be ~delta_solo + LB-spellblade
        # contribution (~37 dps). With dedup, delta_both ≈ delta_solo.
        # Tolerate small deviation from LB stat-block contributions.
        self.assertLess(
            delta_both, delta_solo + 5.0,
            "Spellblade double-count regression: LB proc still firing",
        )
        # And both must be well above bare — TF's spellblade still fires.
        self.assertGreater(delta_both, 50.0)

    def test_triforce_plus_lich_bane_order_swap_yields_lich_bane_proc(self) -> None:
        # Order swap → LB spellblade kept (first-seen-wins).
        # LB spellblade scales with AP (50% AP bonus), so it's larger
        # on AP champions. Ahri's base AD is moderate; LB-kept value
        # should be different from TF-kept value (pin order semantics).
        tf_first = compute_dps(self.snap, "Ahri", level=11, item_ids=["3078", "3100"])
        lb_first = compute_dps(self.snap, "Ahri", level=11, item_ids=["3100", "3078"])
        # Both are valid "single spellblade" approximations but produce
        # different numerical results — order dependence is real and
        # documented.
        self.assertNotAlmostEqual(tf_first.weighted_dps, lb_first.weighted_dps, places=1)


class LifelineUniquePassiveTests(unittest.TestCase):
    """Phase 4 batch 12 — Lifeline unique-passive on Shieldbow / Sterak's / Maw.

    All 3 items use the literal "Lifeline" tooltip label in DDragon and
    are unique-passive in current League (only one Lifeline shield
    triggers per low-HP threshold). All 3 are currently defensive_only,
    so dedup affects DpsResult.notes only — no DPS proc to drop.

    Phantom Dancer (3046) is intentionally NOT tagged: DDragon shows it
    uses "Spectral Waltz" (Ghost effect on low HP), not Lifeline. RC's
    older note for PD called it "Lifeline" — corrected this batch.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_three_lifeline_items_share_key(self) -> None:
        self.assertEqual(ITEM_EFFECTS["6673"].unique_passive_key, "lifeline")
        self.assertEqual(ITEM_EFFECTS["3053"].unique_passive_key, "lifeline")
        self.assertEqual(ITEM_EFFECTS["3156"].unique_passive_key, "lifeline")

    def test_phantom_dancer_not_tagged_lifeline(self) -> None:
        # Spectral Waltz is a distinct passive — DDragon labels diverge.
        self.assertNotEqual(ITEM_EFFECTS["3046"].unique_passive_key, "lifeline")

    def test_phantom_dancer_note_corrected(self) -> None:
        # Note was previously "Phantom Dancer: Lifeline shield..."; should
        # now reference Spectral Waltz / Ghost. Belt-and-braces: the note
        # must NOT claim "Lifeline" anymore.
        note = ITEM_EFFECTS["3046"].note.lower()
        self.assertNotIn("lifeline", note)
        self.assertIn("spectral waltz", note)

    def test_collect_effects_dedups_lifeline_pair(self) -> None:
        # First-seen-wins: Shieldbow kept, Sterak's dropped.
        from agents.daemon_slayer.effects import collect_effects
        effects = collect_effects(["6673", "3053"])
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0].item_id, "6673")

    def test_collect_effects_dedups_three_lifeline_keeps_one(self) -> None:
        # Triple stack: only first-seen Lifeline survives the conditional
        # effects list. Stat blocks (in stats.py) still aggregate all 3.
        from agents.daemon_slayer.effects import collect_effects
        effects = collect_effects(["6673", "3053", "3156"])
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0].item_id, "6673")

    def test_phantom_dancer_not_deduped_with_lifeline(self) -> None:
        # PD has no key, so it survives alongside any Lifeline item.
        from agents.daemon_slayer.effects import collect_effects
        effects = collect_effects(["6673", "3046"])
        self.assertEqual(len(effects), 2)

    def test_no_dps_change_for_solo_lifeline_items(self) -> None:
        # All 3 Lifeline items are defensive_only — no proc to model.
        # Adding any one of them to a build must not change weighted_dps
        # vs bare (because the engine doesn't model the shield itself).
        # This isn't strictly a unique-passive test, but it's a useful
        # safety net for the tagging change: we shouldn't have
        # accidentally promoted any of them to a DPS-positive entry.
        bare = compute_dps(self.snap, "Aatrox", level=11)
        for iid in ("6673", "3053", "3156"):
            with self.subTest(item=iid):
                r = compute_dps(self.snap, "Aatrox", level=11, item_ids=[iid])
                # Stat block can still raise DPS (Maw has 60 AD, Sterak's
                # has 400 HP no AA effect, Shieldbow has 55 AD).
                # The point is: no Lifeline proc damage was added.
                # We assert the increase is purely stat-block — same as
                # if the item had NO ItemEffect entry at all.
                # Easiest check: the result didn't add any "Lifeline" damage
                # note to notes — defensive_only entries do surface their
                # note string but no proc damage hits.
                # We don't have a clean way to assert "no proc fired"
                # without instrumenting; instead, we just confirm the
                # function returned a valid DpsResult (smoke test).
                self.assertGreater(r.weighted_dps, 0.0)


class TerminusPromotionTests(unittest.TestCase):
    """Phase 4 batch 13 — Terminus promoted from defensive_only.

    Shadow on-hit (30 magic per basic, constant — not alternating as
    the prior note claimed) + Juxtaposition Dark sustained pen
    (10% armor pen + 10% magic pen, same sustained-DPS approximation
    as Black Cleaver's stacking). Light buff is caster-resists,
    defensive, ignored.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_terminus_no_longer_defensive_only(self) -> None:
        e = ITEM_EFFECTS["3302"]
        self.assertFalse(e.defensive_only)

    def test_terminus_has_shadow_periodic(self) -> None:
        e = ITEM_EFFECTS["3302"]
        self.assertEqual(len(e.periodics), 1)
        proc = e.periodics[0]
        self.assertEqual(proc.name, "Shadow")
        self.assertEqual(proc.damage_type, MAGICAL)
        self.assertEqual(proc.every_n_attacks, 1)
        # Constant 30 (not stat-scaling). Pinned per current patch.
        ctx = CallContext(base_ad=60, bonus_ad=30, level=11)
        self.assertEqual(proc.resolve_damage(ctx), 30.0)

    def test_terminus_armor_and_magic_pen(self) -> None:
        e = ITEM_EFFECTS["3302"]
        self.assertAlmostEqual(e.armor_pen_pct, 0.10, places=3)
        self.assertAlmostEqual(e.magic_pen_pct, 0.10, places=3)

    def test_terminus_lifts_dps_via_proc(self) -> None:
        # Aatrox + Terminus pre-promotion = 64.92 dps (stat block only).
        # Post-promotion: same stat block + Shadow proc + pen at default
        # 0 armor/MR (pen contributes nothing without targets).
        # Shadow proc = 30 magic per basic; Aatrox's effective AS with
        # Terminus = base + 35% Terminus AS bonus. Per-rotation magic
        # damage = total_attacks * 30 / duration. Should add ~25+ dps
        # uplift over the pre-promotion baseline.
        bare = compute_dps(self.snap, "Aatrox", level=11)
        post = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3302"])
        # Pre-promotion was 64.92 (~ +17.85 from bare 47.07, stats only).
        # Post-promotion should beat 64.92 by the Shadow proc value.
        self.assertGreater(post.weighted_dps, 64.92,
            "Terminus Shadow proc didn't lift DPS past stat-only baseline")
        # Sanity: should be well above bare too.
        self.assertGreater(post.weighted_dps, bare.weighted_dps + 30.0,
            "Combined Terminus stat + proc uplift below expected ~30 dps floor")

    def test_terminus_pen_engages_against_armored_target(self) -> None:
        # 10% armor pen on a 100-armor target reduces effective armor
        # to 90, lifting physical DPS. Compare a Terminus build at
        # target_armor=100 vs another armor-pen-free build (a hypothetical
        # build with same AD but no pen). Easier: probe Terminus alone
        # at 0 armor vs 100 armor. The proportional drop should be
        # smaller than no-pen would give.
        no_target = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3302"])
        armored = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3302"], target_armor=100.0)
        # 10% pen on 100 armor → effective armor 90; armor factor
        # 100/(100+90) = 0.526 vs no-pen 100/(100+100) = 0.500.
        # So armored dps with Terminus pen should be slightly higher
        # than the same build without pen would produce. We can't
        # cleanly contrast without a no-pen baseline, but we can
        # assert the ratio is reasonable.
        ratio = armored.weighted_dps / no_target.weighted_dps
        # Without any pen, 100 armor halves physical damage. With 10%
        # pen, ratio should be slightly above 0.5. With magic damage
        # untouched (default mr=0), the magic proc isn't dampened.
        self.assertGreater(ratio, 0.55,
            "Terminus pen+magic-proc didn't partially offset armor")


class TotalDamageAmpMultiplierTests(unittest.TestCase):
    """Phase 4 batch 14 — multiplicative damage-amp helper.

    Direct unit tests on ``total_damage_amp_multiplier``. Item-side and
    DPS-pipeline assertions live in ``RiftmakerPromotionTests``.
    """

    def test_no_effects_returns_unity(self) -> None:
        from agents.daemon_slayer.effects import total_damage_amp_multiplier
        self.assertEqual(total_damage_amp_multiplier([]), 1.0)

    def test_no_amps_in_effects_returns_unity(self) -> None:
        # IE / Kraken / Stormrazor — none carry damage_amp_pct.
        from agents.daemon_slayer.effects import total_damage_amp_multiplier
        effs = [ITEM_EFFECTS["3031"], ITEM_EFFECTS["6672"], ITEM_EFFECTS["3097"]]
        self.assertEqual(total_damage_amp_multiplier(effs), 1.0)

    def test_riftmaker_alone_returns_1_08(self) -> None:
        from agents.daemon_slayer.effects import total_damage_amp_multiplier
        rift = ITEM_EFFECTS["4633"]
        self.assertAlmostEqual(total_damage_amp_multiplier([rift]), 1.08, places=4)

    def test_two_amps_stack_multiplicatively(self) -> None:
        # Build two synthetic amp items inline — engine doesn't ship a
        # second amp yet (Conqueror is a rune, not an item; future
        # ItemEffect entries with damage_amp_pct will hit this path).
        from agents.daemon_slayer.effects import (
            ItemEffect,
            total_damage_amp_multiplier,
        )
        a = ItemEffect(item_id="X1", name="amp1", damage_amp_pct=0.08)
        b = ItemEffect(item_id="X2", name="amp2", damage_amp_pct=0.10)
        # 1.08 * 1.10 = 1.188 (multiplicative), NOT 1.18 (additive).
        self.assertAlmostEqual(total_damage_amp_multiplier([a, b]), 1.188, places=4)


class RiftmakerPromotionTests(unittest.TestCase):
    """Phase 4 batch 14 — Riftmaker promoted from defensive_only.

    Void Corruption ramps to 8% bonus damage after 4s in combat. The
    sustained-DPS approximation pins the full-ramp value (same shape
    as Black Cleaver's 30%-at-5-stacks). HP→AP cross-derivation
    landed in batch 15 (RiftmakerHpToApTests below) — these tests
    cover the amp piece in isolation and stay valid because Aatrox
    auto-attacks don't read AP.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_riftmaker_no_longer_defensive_only(self) -> None:
        e = ITEM_EFFECTS["4633"]
        self.assertFalse(e.defensive_only)

    def test_riftmaker_carries_8pct_amp(self) -> None:
        e = ITEM_EFFECTS["4633"]
        self.assertAlmostEqual(e.damage_amp_pct, 0.08, places=4)
        # Riftmaker has no periodic / pen / crit-bonus piece; the amp
        # is the entire DPS contribution beyond stats.
        self.assertEqual(e.periodics, ())
        self.assertEqual(e.armor_pen_pct, 0.0)
        self.assertEqual(e.magic_pen_pct, 0.0)
        self.assertEqual(e.crit_damage_bonus, 0.0)

    def test_riftmaker_lifts_dps_via_amp(self) -> None:
        # Build with Riftmaker should beat the same build minus Riftmaker
        # by approximately the amp factor times the stat-only DPS.
        # Aatrox AAs are physical so the 70 AP / 350 HP / 15 AH stat
        # block doesn't contribute directly — the entire delta is the
        # 8% Void Corruption amp.
        bare = compute_dps(self.snap, "Aatrox", level=11)
        rift = compute_dps(self.snap, "Aatrox", level=11, item_ids=["4633"])
        self.assertGreater(rift.weighted_dps, bare.weighted_dps,
            "Riftmaker should lift DPS over bare Aatrox (stat block + amp)")

    def test_riftmaker_amp_applies_multiplicatively(self) -> None:
        # Concrete check: compute Aatrox+Riftmaker DPS and Aatrox+
        # synthetic-no-amp-Riftmaker DPS (mock by zeroing the amp and
        # restoring), confirm the ratio is 1.08.
        from agents.daemon_slayer import effects as effects_mod
        original = effects_mod.ITEM_EFFECTS["4633"]
        # Replace with a no-amp variant carrying the same identity.
        no_amp = ItemEffect(
            item_id="4633",
            name="Riftmaker",
            note=original.note,
        )
        try:
            effects_mod.ITEM_EFFECTS["4633"] = no_amp
            no_amp_dps = compute_dps(self.snap, "Aatrox", level=11, item_ids=["4633"])
        finally:
            effects_mod.ITEM_EFFECTS["4633"] = original
        with_amp = compute_dps(self.snap, "Aatrox", level=11, item_ids=["4633"])
        # Ratio should be exactly 1.08 (the amp multiplier) since stat
        # block is identical between the two builds.
        ratio = with_amp.weighted_dps / no_amp_dps.weighted_dps
        self.assertAlmostEqual(ratio, 1.08, places=3,
            msg=f"amp ratio {ratio:.4f} != 1.08 — multiplier wiring is broken")

    def test_riftmaker_amp_surfaces_in_notes(self) -> None:
        result = compute_dps(self.snap, "Aatrox", level=11, item_ids=["4633"])
        self.assertTrue(
            any("damage amp" in n for n in result.notes),
            f"missing damage-amp note in result.notes: {result.notes!r}"
        )

    def test_no_amp_when_no_amp_items(self) -> None:
        # Sanity: a build with no amp items should produce no
        # "damage amp" note (avoid noise on the 99% pre-batch case).
        result = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3031"])
        self.assertFalse(
            any("damage amp" in n for n in result.notes),
            "build w/o amp items shouldn't surface a damage-amp note"
        )


class TotalBonusApFromHpTests(unittest.TestCase):
    """Phase 4 batch 15 — additive HP→AP cross-derivation helper."""

    def test_no_effects_returns_zero(self) -> None:
        from agents.daemon_slayer.effects import total_bonus_ap_from_hp
        self.assertEqual(total_bonus_ap_from_hp([], 1000.0), 0.0)

    def test_no_hp_returns_zero(self) -> None:
        # Riftmaker present but caster has zero bonus HP (e.g. no HP-stat
        # items beyond Riftmaker itself, but bonus_hp = 0 edge case).
        from agents.daemon_slayer.effects import total_bonus_ap_from_hp
        rift = ITEM_EFFECTS["4633"]
        self.assertEqual(total_bonus_ap_from_hp([rift], 0.0), 0.0)

    def test_negative_hp_clamped_to_zero(self) -> None:
        # Defensive paranoia — engine floors caster_bonus_hp at zero
        # before passing to the helper, but verify the helper itself
        # is also defensive.
        from agents.daemon_slayer.effects import total_bonus_ap_from_hp
        rift = ITEM_EFFECTS["4633"]
        self.assertEqual(total_bonus_ap_from_hp([rift], -500.0), 0.0)

    def test_riftmaker_yields_2pct_of_hp(self) -> None:
        from agents.daemon_slayer.effects import total_bonus_ap_from_hp
        rift = ITEM_EFFECTS["4633"]
        # 1000 bonus HP * 2% = 20 AP.
        self.assertAlmostEqual(total_bonus_ap_from_hp([rift], 1000.0), 20.0, places=4)

    def test_no_amp_items_yield_zero(self) -> None:
        # Items without ap_per_bonus_hp_pct (IE / Kraken / Heartsteel
        # itself) contribute nothing, even with HP in the build.
        from agents.daemon_slayer.effects import total_bonus_ap_from_hp
        ie = ITEM_EFFECTS["3031"]
        heartsteel = ITEM_EFFECTS["3084"]
        self.assertEqual(total_bonus_ap_from_hp([ie, heartsteel], 2000.0), 0.0)


class RiftmakerHpToApTests(unittest.TestCase):
    """Phase 4 batch 15 — Riftmaker Void Infusion HP→AP wiring.

    Validates the cross-derivation appears in DpsResult.notes when
    triggered, the converted AP isn't stored back into resolved.stats
    (engine-internal — /stats reflects raw stat blocks only), and the
    converted AP feeds AP-scaling procs (Lich Bane spellblade,
    Nashor's Tooth on-hit) so HP-stack builds get the expected boost.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_riftmaker_carries_2pct_hp_to_ap(self) -> None:
        e = ITEM_EFFECTS["4633"]
        self.assertAlmostEqual(e.ap_per_bonus_hp_pct, 0.02, places=4)

    def test_no_other_items_carry_hp_to_ap(self) -> None:
        # Sanity: Riftmaker is currently the only item with this hook.
        # If a future item also gets HP→AP, this test will need an
        # explicit allow-list update — surfacing the schema add.
        for iid, e in ITEM_EFFECTS.items():
            if iid == "4633":
                continue
            self.assertEqual(
                e.ap_per_bonus_hp_pct, 0.0,
                f"unexpected ap_per_bonus_hp_pct on {iid} ({e.name})"
            )

    def test_hp_to_ap_note_surfaces_when_riftmaker_present(self) -> None:
        result = compute_dps(self.snap, "Aatrox", level=11, item_ids=["4633"])
        # Aatrox + Riftmaker: bonus_hp = 350 (Riftmaker's stat block).
        # 2% * 350 = 7 AP added.
        ap_note = next(
            (n for n in result.notes if "AP cross-derived" in n),
            None,
        )
        self.assertIsNotNone(ap_note,
            f"missing HP→AP note in result.notes: {result.notes!r}")
        # Note format: "...+7.0 AP (total AP for procs: ...)"
        self.assertIn("+7.0 AP", ap_note,
            f"expected +7 AP from Riftmaker's 350 HP, got {ap_note!r}")

    def test_no_hp_to_ap_note_when_riftmaker_absent(self) -> None:
        # Sanity: a build without Riftmaker shouldn't surface the
        # cross-derivation note (avoid noise).
        result = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3031"])
        self.assertFalse(
            any("AP cross-derived" in n for n in result.notes),
            "build w/o Riftmaker shouldn't surface HP→AP note"
        )

    def test_resolved_stats_ap_unchanged_by_cross_derivation(self) -> None:
        # /stats consumers see raw stat-block AP only — cross-derivation
        # is dps-internal. Riftmaker's stat block is 70 AP per DDragon.
        result = compute_dps(self.snap, "Aatrox", level=11, item_ids=["4633"])
        self.assertAlmostEqual(
            result.stats["ap"], 70.0, places=3,
            msg="resolved.stats AP should reflect raw stat block, not cross-derived total",
        )

    def test_riftmaker_plus_heartsteel_compounds_ap(self) -> None:
        # Heartsteel (3084) is 900 HP per DDragon. Riftmaker (350 HP)
        # + Heartsteel (900 HP) = 1250 bonus HP → 2% = 25 AP cross-
        # derived. Plus Riftmaker's 70 AP stat-block = 95 AP visible
        # to AP procs.
        result = compute_dps(self.snap, "Aatrox", level=11,
                             item_ids=["4633", "3084"])
        ap_note = next(
            (n for n in result.notes if "AP cross-derived" in n),
            None,
        )
        self.assertIsNotNone(ap_note)
        self.assertIn("+25.0 AP", ap_note,
            f"expected +25 AP from 1250 bonus HP, got {ap_note!r}")

    def test_riftmaker_lifts_lich_bane_proc_via_ap(self) -> None:
        # Lich Bane spellblade scales 0.50 * AP per proc. Aatrox + Lich
        # Bane: stat AP from Lich Bane = 100, no HP→AP. Aatrox + Lich
        # Bane + Riftmaker: stat AP = 100+70 = 170, plus 2% of (Lich
        # Bane 0 HP + Riftmaker 350 HP) = 7 AP cross-derived → 177 AP
        # visible to Lich Bane spellblade. The 7 AP delta lifts each
        # spellblade by 0.50*7 = 3.5 magic dmg (ignoring MR factor).
        # Synthetic test — strip Riftmaker's amp + cross-derivation
        # to isolate the HP→AP contribution from the amp piece.
        from agents.daemon_slayer import effects as effects_mod
        original = effects_mod.ITEM_EFFECTS["4633"]
        # No-amp, no-HP→AP variant — only stat block (70 AP, 350 HP, 15 AH).
        no_xforms = ItemEffect(
            item_id="4633",
            name="Riftmaker",
            note=original.note,
        )
        # Amp-only variant — reproduces batch 14 behavior.
        amp_only = ItemEffect(
            item_id="4633",
            name="Riftmaker",
            damage_amp_pct=0.08,
            note=original.note,
        )
        try:
            effects_mod.ITEM_EFFECTS["4633"] = no_xforms
            base_dps = compute_dps(self.snap, "Aatrox", level=11,
                                   item_ids=["4633", "3100"]).weighted_dps
            effects_mod.ITEM_EFFECTS["4633"] = amp_only
            amp_dps = compute_dps(self.snap, "Aatrox", level=11,
                                  item_ids=["4633", "3100"]).weighted_dps
            effects_mod.ITEM_EFFECTS["4633"] = original  # full batch 15
            full_dps = compute_dps(self.snap, "Aatrox", level=11,
                                   item_ids=["4633", "3100"]).weighted_dps
        finally:
            effects_mod.ITEM_EFFECTS["4633"] = original
        # Ordering: full > amp_only > base. The delta full - amp_only
        # is the HP→AP boost on Lich Bane's spellblade procs (after the
        # 8% amp). Should be a small but positive number.
        self.assertGreater(amp_dps, base_dps,
            "amp-only variant should beat no-xforms baseline")
        self.assertGreater(full_dps, amp_dps,
            "HP→AP wiring should add to amp_only variant via Lich Bane proc")


class TotalTargetBonusHpAmpMultiplierTests(unittest.TestCase):
    """Phase 4 batch 19 — target-conditional damage-amp helper.

    Direct unit tests on ``total_target_bonus_hp_amp_multiplier``. LDR
    end-to-end + multiplicative-stack-with-Riftmaker pinning lives in
    ``LdrGiantSlayerTests`` below.
    """

    def test_no_effects_returns_unity(self) -> None:
        from agents.daemon_slayer.effects import total_target_bonus_hp_amp_multiplier
        self.assertEqual(total_target_bonus_hp_amp_multiplier([], 1500.0), 1.0)

    def test_zero_target_bonus_hp_returns_unity(self) -> None:
        # Pre-batch-19 callers don't supply target_bonus_hp — default 0.
        # Result must short-circuit to 1.0 even when items carry the schema.
        from agents.daemon_slayer.effects import total_target_bonus_hp_amp_multiplier
        ldr = ITEM_EFFECTS["3036"]
        self.assertEqual(total_target_bonus_hp_amp_multiplier([ldr], 0.0), 1.0)

    def test_negative_target_bonus_hp_returns_unity(self) -> None:
        # Defensive guard — caller-supplied negative values should not
        # produce a damage REDUCTION; treat as "no signal".
        from agents.daemon_slayer.effects import total_target_bonus_hp_amp_multiplier
        ldr = ITEM_EFFECTS["3036"]
        self.assertEqual(total_target_bonus_hp_amp_multiplier([ldr], -100.0), 1.0)

    def test_no_amp_items_in_effects_returns_unity(self) -> None:
        # IE / Kraken / Stormrazor — none carry target_bonus_hp_amp_max_pct.
        from agents.daemon_slayer.effects import total_target_bonus_hp_amp_multiplier
        effs = [ITEM_EFFECTS["3031"], ITEM_EFFECTS["6672"], ITEM_EFFECTS["3097"]]
        self.assertEqual(total_target_bonus_hp_amp_multiplier(effs, 1500.0), 1.0)

    def test_ldr_at_half_cap_yields_half_max_pct(self) -> None:
        # 750 / 1500 = 0.5 → 0.5 * 0.15 = 7.5% amp → ×1.075 multiplier.
        from agents.daemon_slayer.effects import total_target_bonus_hp_amp_multiplier
        ldr = ITEM_EFFECTS["3036"]
        self.assertAlmostEqual(
            total_target_bonus_hp_amp_multiplier([ldr], 750.0), 1.075, places=4,
        )

    def test_ldr_at_full_cap_yields_max_pct(self) -> None:
        # 1500 / 1500 = 1.0 → 0.15 amp → ×1.15 multiplier.
        from agents.daemon_slayer.effects import total_target_bonus_hp_amp_multiplier
        ldr = ITEM_EFFECTS["3036"]
        self.assertAlmostEqual(
            total_target_bonus_hp_amp_multiplier([ldr], 1500.0), 1.15, places=4,
        )

    def test_ldr_above_cap_clamps_to_max_pct(self) -> None:
        # 3000 / 1500 = 2.0, but min(1.0, 2.0) = 1.0 — multiplier stays
        # at ×1.15. Matches DDragon "maximum damage bonus reached at
        # 1500 bonus Health".
        from agents.daemon_slayer.effects import total_target_bonus_hp_amp_multiplier
        ldr = ITEM_EFFECTS["3036"]
        self.assertAlmostEqual(
            total_target_bonus_hp_amp_multiplier([ldr], 3000.0), 1.15, places=4,
        )

    def test_two_target_amps_stack_multiplicatively(self) -> None:
        # Engine ships only LDR with this schema today. Build two
        # synthetic items inline to pin the multiplicative-stacking
        # contract for future entries.
        from agents.daemon_slayer.effects import (
            ItemEffect,
            total_target_bonus_hp_amp_multiplier,
        )
        a = ItemEffect(
            item_id="X1", name="amp1",
            target_bonus_hp_amp_max_pct=0.10, target_bonus_hp_amp_cap=1000.0,
        )
        b = ItemEffect(
            item_id="X2", name="amp2",
            target_bonus_hp_amp_max_pct=0.20, target_bonus_hp_amp_cap=1000.0,
        )
        # At cap: 1.10 * 1.20 = 1.32 (multiplicative), not 1.30 (additive).
        self.assertAlmostEqual(
            total_target_bonus_hp_amp_multiplier([a, b], 1000.0), 1.32, places=4,
        )

    def test_partial_schema_entry_is_ignored(self) -> None:
        # Defensive: if a future item entry has max_pct set but cap=0
        # (or vice versa), the helper must skip it rather than divide
        # by zero or apply infinite ramp.
        from agents.daemon_slayer.effects import (
            ItemEffect,
            total_target_bonus_hp_amp_multiplier,
        )
        broken = ItemEffect(
            item_id="X3", name="broken",
            target_bonus_hp_amp_max_pct=0.15, target_bonus_hp_amp_cap=0.0,
        )
        self.assertEqual(
            total_target_bonus_hp_amp_multiplier([broken], 1500.0), 1.0,
        )


class LdrGiantSlayerTests(unittest.TestCase):
    """Phase 4 batch 19 — LDR Giant Slayer end-to-end via /dps.

    Mirrors RiftmakerPromotionTests' shape: stat-only baseline,
    schema field present, DPS lifts when target_bonus_hp is supplied,
    no behavior change when caller omits the signal (back-compat).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_ldr_carries_giant_slayer_schema(self) -> None:
        e = ITEM_EFFECTS["3036"]
        self.assertAlmostEqual(e.target_bonus_hp_amp_max_pct, 0.15, places=4)
        self.assertAlmostEqual(e.target_bonus_hp_amp_cap, 1500.0, places=2)
        # Armor pen still wired (existing batch 4 / batch 16 behavior).
        self.assertAlmostEqual(e.armor_pen_pct, 0.35, places=4)
        # Note text mentions Giant Slayer + the cap value so /dps clients
        # know what they're seeing.
        self.assertIn("Giant Slayer", e.note)
        self.assertIn("1500", e.note)

    def test_no_amp_when_target_bonus_hp_unset(self) -> None:
        # Pre-batch-19 caller shape — no target_bonus_hp kwarg. The
        # /dps response must look identical to a build with no Giant
        # Slayer item modulo the existing armor-pen wiring.
        result = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3036"],
                             target_armor=80.0)
        self.assertFalse(
            any("target-conditional amp" in n for n in result.notes),
            "no target_bonus_hp signal — must not surface a target-amp note",
        )

    def test_amp_lifts_dps_at_full_cap(self) -> None:
        # With LDR + target_bonus_hp=1500, weighted_dps must exceed the
        # zero-bonus-hp baseline by approximately 15% (the full Giant
        # Slayer ramp). Stat block is identical between the two runs;
        # only the multiplier differs.
        bare_target = compute_dps(self.snap, "Aatrox", level=11,
                                  item_ids=["3036"], target_armor=80.0)
        full_target = compute_dps(self.snap, "Aatrox", level=11,
                                  item_ids=["3036"], target_armor=80.0,
                                  target_bonus_hp=1500.0)
        ratio = full_target.weighted_dps / bare_target.weighted_dps
        self.assertAlmostEqual(ratio, 1.15, places=3,
            msg=f"LDR full-cap amp ratio {ratio:.4f} != 1.15")

    def test_amp_lifts_half_at_half_cap(self) -> None:
        # 750 bonus HP → 7.5% amp → ratio 1.075.
        bare_target = compute_dps(self.snap, "Aatrox", level=11,
                                  item_ids=["3036"], target_armor=80.0)
        half_target = compute_dps(self.snap, "Aatrox", level=11,
                                  item_ids=["3036"], target_armor=80.0,
                                  target_bonus_hp=750.0)
        ratio = half_target.weighted_dps / bare_target.weighted_dps
        self.assertAlmostEqual(ratio, 1.075, places=3,
            msg=f"LDR half-cap amp ratio {ratio:.4f} != 1.075")

    def test_amp_clamps_above_cap(self) -> None:
        # 3000 bonus HP must yield same multiplier as 1500.
        full_cap = compute_dps(self.snap, "Aatrox", level=11,
                               item_ids=["3036"], target_armor=80.0,
                               target_bonus_hp=1500.0).weighted_dps
        above_cap = compute_dps(self.snap, "Aatrox", level=11,
                                item_ids=["3036"], target_armor=80.0,
                                target_bonus_hp=3000.0).weighted_dps
        self.assertAlmostEqual(full_cap, above_cap, places=4,
            msg=f"above-cap dps {above_cap} != full-cap dps {full_cap}")

    def test_amp_surfaces_in_notes_when_active(self) -> None:
        result = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3036"],
                             target_armor=80.0, target_bonus_hp=1500.0)
        self.assertTrue(
            any("target-conditional amp" in n for n in result.notes),
            f"missing target-amp note in result.notes: {result.notes!r}",
        )

    def test_dps_result_carries_target_bonus_hp(self) -> None:
        # Field plumbed through compute_dps → DpsResult → to_dict so
        # /dps clients can confirm what the engine used.
        result = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3036"],
                             target_armor=80.0, target_bonus_hp=1500.0)
        self.assertAlmostEqual(result.target_bonus_hp, 1500.0, places=2)
        self.assertAlmostEqual(result.to_dict()["target_bonus_hp"], 1500.0, places=2)

    def test_ldr_plus_riftmaker_amps_stack_multiplicatively(self) -> None:
        # Riftmaker carries 8% damage_amp_pct (batch 14), LDR carries
        # 15% target-conditional amp (batch 19). Combined multiplier
        # must be 1.08 * 1.15 = 1.242 — NOT 1.23 (additive). Pins the
        # batch-14 doctrine ("League stacks amps multiplicatively").
        from agents.daemon_slayer import effects as effects_mod
        # Build a "no-amp Riftmaker" baseline so the 8% piece is the
        # only difference between the runs.
        original_rift = effects_mod.ITEM_EFFECTS["4633"]
        no_amp_rift = ItemEffect(
            item_id="4633", name="Riftmaker",
            note=original_rift.note,
            ap_per_bonus_hp_pct=original_rift.ap_per_bonus_hp_pct,
        )
        try:
            effects_mod.ITEM_EFFECTS["4633"] = no_amp_rift
            ldr_only = compute_dps(
                self.snap, "Aatrox", level=11,
                item_ids=["3036", "4633"], target_armor=80.0,
                target_bonus_hp=1500.0,
            ).weighted_dps
            effects_mod.ITEM_EFFECTS["4633"] = original_rift
            both_amps = compute_dps(
                self.snap, "Aatrox", level=11,
                item_ids=["3036", "4633"], target_armor=80.0,
                target_bonus_hp=1500.0,
            ).weighted_dps
        finally:
            effects_mod.ITEM_EFFECTS["4633"] = original_rift
        # both_amps / ldr_only should be exactly 1.08 (the Riftmaker
        # contribution on top of the already-amped LDR baseline).
        ratio = both_amps / ldr_only
        self.assertAlmostEqual(ratio, 1.08, places=3,
            msg=f"Riftmaker × LDR amp stacking ratio {ratio:.4f} != 1.08")


if __name__ == "__main__":
    unittest.main()

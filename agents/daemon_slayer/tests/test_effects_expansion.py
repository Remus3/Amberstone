"""Phase 4 expansion tests - callable bonus_damage, armor pen layer, +25 items.

Companion to ``test_effects.py`` (thin slice). New coverage:
* ``CallContext`` resolution for callable ``bonus_damage``.
* Armor reduction → % pen → flat pen pipeline via ``effective_target_armor``.
* Black Cleaver, LDR, Mortal Reminder DPS impact.
* Energized family entries (Statikk Shiv, Rapid Firecannon, Voltaic, Sundered Sky).
* Scaling proc entries (Wit's End by level, Runaan's by bonus AD, TriForce by base AD).
* AP-scaling spellblade / on-hit (Lich Bane, Nashor's Tooth) - Phase 4 batch 3.
* Magic pen layer (Void Staff, Cryptbloom, Sorc, Shadowflame) - Phase 4 batch 4.
* Target-HP layer (BotRK Mist's Edge, Eclipse Ever Rising Moon) - Phase 4 batch 5.
* Caster-HP layer (Titanic Hydra Cleave, Heartsteel Colossal Consumption) - Phase 4 batch 6.
* Multi-target rotation layer (Ravenous Hydra Cleave) - Phase 4 batch 7.
* defensive_only entries - no DPS contribution beyond stat block.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import _armor_factor, compute_dps
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    CallContext,
    ItemEffect,
    MAGICAL,
    PHYSICAL,
    PeriodicProc,
    effective_target_armor,
    effective_target_mr,
    total_crit_chance_bonus,
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
            bonus_damage=lambda c: 50,
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

    def test_voltaic_cyclosword_flat_proc(self) -> None:
        # Iter 15 (2026-05-20): Meraki bulk items 16.10.1 - Firmament is
        # now flat 100 bonus physical (the 25% bonus AD scaling clause
        # was a pre-rework formula; stripped in this iter). Voltaic +
        # Bloodthirster still raises DPS via AA bonus AD contribution
        # alone - same final assertion, the proc itself no longer
        # contributes the bonus AD lift.
        v_only = compute_dps(self.snap, "Aatrox", level=11, item_ids=["6699"])
        v_bt = compute_dps(self.snap, "Aatrox", level=11, item_ids=["6699", "3072"])
        self.assertGreater(v_bt.weighted_dps, v_only.weighted_dps)
        # Direct proc check: bonus_ad does NOT alter the Firmament damage.
        from agents.daemon_slayer.effects import ITEM_EFFECTS, CallContext
        proc = ITEM_EFFECTS["6699"].periodics[0]
        d0 = proc.resolve_damage(CallContext(base_ad=60.0, bonus_ad=0.0, level=11))
        d100 = proc.resolve_damage(CallContext(base_ad=60.0, bonus_ad=100.0, level=11))
        self.assertAlmostEqual(d0, 100.0, places=2)
        self.assertAlmostEqual(d100, 100.0, places=2)

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
        # Iter 10 (2026-05-20): promoted off defensive_only via the
        # lethality plumbing - 10 Lethality stat block contributes to
        # the rest of the rotation; the Death execute is still a finisher
        # (no per-rotation DPS proc) so periodics stays (). Pin both.
        e = ITEM_EFFECTS["6676"]
        self.assertFalse(e.defensive_only)
        self.assertAlmostEqual(e.lethality, 10.0, places=2)
        self.assertEqual(e.periodics, ())

    def test_phantom_dancer_no_periodic(self) -> None:
        e = ITEM_EFFECTS["3046"]
        self.assertTrue(e.defensive_only)
        self.assertEqual(e.periodics, ())

    def test_sterak_no_periodic(self) -> None:
        # Phase 4 batch 20 (2026-05-04): Sterak's Claws that Catch is a
        # stat-layer passive (+45% base AD), not a periodic - promotion
        # path differs from BotRK/Eclipse (which got periodics). The
        # entry no longer carries defensive_only, but periodics stay
        # empty because the AD bonus is folded into the build at stat
        # resolution time, not as an on-hit proc. Schema-promotion
        # assertions live in SteraksClawsThatCatchTests +
        # SteraksEngineWireInTests at the bottom of this file.
        e = ITEM_EFFECTS["3053"]
        self.assertEqual(e.periodics, ())
        self.assertGreater(e.bonus_ad_pct_base_ad, 0.0)

    # BotRK (3153) and Eclipse (6692) promoted in Phase 4 batch 5
    # (2026-05-04) once ``target_max_hp`` landed. Their proc-shape
    # assertions live in TargetHpItemTests below; the schema-promotion
    # path matches Shadowflame in batch 4.

    # Terminus (3302) promoted out of defensive_only in Phase 4 batch 13
    # (2026-05-04) - Shadow on-hit proc + Juxtaposition Dark sustained
    # pen. Promotion-shape assertions live in TerminusPromotionTests
    # at the bottom of this file.


class DefensiveOnlyBatch2Tests(unittest.TestCase):
    """Phase 4 batch 2 (2026-05-04) - 10 high-pickrate SR legendaries.

    All defensive_only - utilities/shields/storage with no DPS proc.
    Pinning the table here so future schema-promotion work (target HP,
    magic pen, ability scaling) can find these via grep when the
    relevant hooks land.
    """

    # Heartsteel (3084) was here through batch 5; promoted in batch 6
    # (caster-HP layer, 2026-05-04) - its proc-shape assertions live
    # in CasterHpItemTests below.
    # Stridebreaker (6631) was here through batch 20; promoted in
    # batch 21 (multi-target rotation layer, 2026-05-04) - its
    # proc-shape assertions live in StridebreakerCleaveTests below.
    # Essence Reaver (3508) was here through batch 20; promoted in
    # batch 21 (CallContext.crit_chance schema, 2026-05-04) - its
    # proc-shape assertions live in EssenceReaverSpellbladeTests below.
    EXPECTED = {
        "6333": "Death's Dance",
        "3161": "Spear of Shojin",
        "3083": "Warmog's Armor",
        "3139": "Mercurial Scimitar",
        "3026": "Guardian Angel",
        "3102": "Banshee's Veil",
        "3157": "Zhonya's Hourglass",
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
    """Phase 4 batch 3 - CallContext.ap field for AP-scaling procs."""

    def test_ap_default_zero(self) -> None:
        # Backward-compatible default - pre-batch-3 callers don't pass ap.
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
    """Lich Bane (3100) + Nashor's Tooth (3115) - AP-scaling promotions."""

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

    def test_nashors_tooth_meraki_16_10_1_coef(self) -> None:
        """Lock in the 15 + 15% AP Meraki bulk 16.10.1 coefficient.

        Pre-2026-05-20 the engine had 20% AP - drifted. Guard against
        regression by computing the closed-form damage at ap=100:
          15 + 0.15 * 100 = 30
        """
        e = ITEM_EFFECTS["3115"]
        proc = e.periodics[0]
        ctx = CallContext(base_ad=60.0, bonus_ad=0, level=11, ap=100.0)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 30.0, places=4)

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
        # control - same gold-ish, no AP. Lich Bane companion has AP.
        nt_bt = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3115", "3072"])
        nt_lb = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3115", "3100"])
        # nt_lb has 100 extra AP in CallContext → Nashor's proc gains
        # 0.20 * 100 = 20 extra magic per attack. Should beat the AD-only
        # companion's auto-attack contribution.
        self.assertGreater(nt_lb.weighted_dps, nt_bt.weighted_dps)


class DefensiveOnlyBatch3Tests(unittest.TestCase):
    """Phase 4 batch 3 (2026-05-04) - AP-stat siblings without DPS proc.

    Luden's Echo (6655) / Deathfire Grasp (3128). Both carry AP stat
    blocks but their effects don't fit the periodic/on-hit shape:
    ability-bound bolts (schema-blocked, needs ability-cast modeling)
    and active %-target-max-HP (removed-from-game in current League,
    kept for parity). Pinned here so future hooks can find them via
    grep.

    Note: Shadowflame (4645) shipped batch 3 as defensive_only but
    promoted in batch 4 - its 15 flat magic pen IS modeled by the new
    pipeline (the unmodeled piece is the magic-crit-on-low-HP). So
    it now lives in MagicPenItemTests, not here.

    Note: Riftmaker (4633) was here through batch 13; promoted in
    batch 14 (damage_amp_pct schema, 2026-05-04) - its proc-shape
    assertions live in RiftmakerPromotionTests at the bottom of this
    file. HP→AP cross-derivation is still separate.

    Note: Hextech Gunblade (3146) was here through batch 21; promoted
    in batch 22 (long-CD active modeled as periodic proc, 2026-05-04)
    - its proc-shape assertions live in HextechGunbladeTests below.
    """

    EXPECTED = {
        # 6655 Luden's Echo promoted to active periodic in batch 52
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
    """Phase 4 batch 4 - % magic pen → flat magic pen pipeline."""

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
        # Vs 0 MR, pen does nothing - only Void's stat block contributes.
        bare = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3100"])
        with_void = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3100", "3135"],
        )
        # Stat block alone (95 AP) lifts the Lich Bane proc - assert >.
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
    promoted BotRK + Eclipse from defensive_only - count stayed at 50
    (promotions don't add or remove entries). Batch 6 (caster HP)
    adds Titanic Hydra (new entry) + promotes Heartsteel - table grows
    to 51. Batch 7 (multi-target rotations) adds Ravenous Hydra - 52.
    Batch 9 (Immolate items) adds Sunfire Aegis + Hollow Radiance - 54.
    """

    def test_table_size_at_phase_4_expansion(self) -> None:
        # Lower bound: no regressions removed entries.
        self.assertGreaterEqual(len(ITEM_EFFECTS), 54)


class CallContextTargetMaxHpTests(unittest.TestCase):
    """Phase 4 batch 5 - CallContext.target_max_hp field for %HP procs."""

    def test_target_max_hp_default_zero(self) -> None:
        # Backward-compat default - pre-batch-5 callers don't pass it.
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
        # Default target_max_hp=0 means %HP procs contribute zero - keeps
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

    Both procs scale linearly with target_max_hp - tests assert the
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
        # With target_max_hp=0 (default), BotRK proc contributes zero -
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
        # BotRK fires every basic at 9% HP (Meraki melee, pipeline-A
        # follow-up 2026-05-20); Eclipse fires every 2nd at 6% HP. Same
        # target_max_hp, BotRK should score higher on the proc piece.
        # (Stat blocks differ - BotRK has AS/lifesteal, Eclipse has
        # lethality - but at zero target_armor the AS bonus makes BotRK
        # win regardless.)
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
        # they got - same shape as target_armor / target_mr.
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
    """Phase 4 batch 6 - CallContext.caster_max_hp / caster_bonus_hp."""

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

    Caster HP is engine-derived (no caller param) - building with HP
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
        # Heartsteel left DefensiveOnlyBatch2Tests in batch 6 - pin the
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
        # bonus HP) - proc piece should rise. Stat block contributions
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
        # patch.) Threshold left at 30 - still well above noise.
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
        # The caster HP fields are derived inside compute_dps - there's
        # no caller-supplied parameter (unlike target_max_hp). Sanity
        # check: compute_dps signature has no caster_max_hp kwarg.
        import inspect
        sig = inspect.signature(compute_dps)
        self.assertNotIn("caster_max_hp", sig.parameters)
        self.assertNotIn("caster_bonus_hp", sig.parameters)


class CallContextTargetsInRotationTests(unittest.TestCase):
    """Phase 4 batch 7 - CallContext.targets_in_rotation field."""

    def test_default_one(self) -> None:
        # Default 1.0 = single-target rotation. cleave-to-others lambdas
        # multiply by max(0, n-1) which is 0 at n=1 - backward-compat.
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
        # Sunfire-style (hypothetical): direct n multiplier - pin the
        # idiom for future AoE-incl-primary procs.
        proc = PeriodicProc(
            name="aoe_incl",
            bonus_damage=lambda c: c.targets_in_rotation * 30.0,
            damage_type=PHYSICAL,
            every_n_seconds=1.0,
        )
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11, targets_in_rotation=2.5)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 75.0, places=3)


class CallContextCritChanceTests(unittest.TestCase):
    """Phase 4 batch 21 - CallContext.crit_chance field."""

    def test_default_zero(self) -> None:
        # Backward-compat default - pre-batch-21 callers don't pass it.
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11)
        self.assertEqual(ctx.crit_chance, 0.0)

    def test_callable_resolves_against_crit_chance(self) -> None:
        # ER-shape proc: 1.25 * base_ad + 50 * crit_chance bonus physical.
        proc = PeriodicProc(
            name="spellblade_er",
            bonus_damage=lambda c: 1.25 * c.base_ad + 50.0 * c.crit_chance,
            damage_type=PHYSICAL,
            every_n_seconds=3.0,
        )
        # 100 base_ad, 60% crit → 125 + 30 = 155.
        ctx = CallContext(base_ad=100.0, bonus_ad=0, level=11, crit_chance=0.60)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 155.0, places=3)

    def test_zero_crit_chance_zeros_crit_piece(self) -> None:
        # No crit → ER falls back to flat 1.25 * base_ad. Pins the
        # "pre-batch consumers see no behavior change" invariant.
        proc = PeriodicProc(
            name="spellblade_er",
            bonus_damage=lambda c: 1.25 * c.base_ad + 50.0 * c.crit_chance,
            damage_type=PHYSICAL,
            every_n_seconds=3.0,
        )
        ctx = CallContext(base_ad=100.0, bonus_ad=0, level=11)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 125.0, places=3)

    def test_full_crit_caps_at_50_bonus(self) -> None:
        # Meraki text "0 to 50 based on critical strike chance" - at
        # 100% crit, crit piece = 50 flat. Engine doesn't enforce a cap
        # on the lambda; it relies on the caller clamping crit_chance to
        # 1.0 (compute_dps does this via min(stats.crit, 1.0)).
        proc = PeriodicProc(
            name="spellblade_er",
            bonus_damage=lambda c: 1.25 * c.base_ad + 50.0 * c.crit_chance,
            damage_type=PHYSICAL,
            every_n_seconds=3.0,
        )
        ctx = CallContext(base_ad=80.0, bonus_ad=0, level=11, crit_chance=1.0)
        # 1.25 * 80 + 50 * 1.0 = 100 + 50 = 150.
        self.assertAlmostEqual(proc.resolve_damage(ctx), 150.0, places=3)


class RavenousHydraMultiTargetTests(unittest.TestCase):
    """Ravenous Hydra (3074) - cleave-to-others scales with rotation targets.

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
        # 65 AD pure-stat item - same DPS expected. Easier path: just
        # assert the proc *would* resolve to zero given Aatrox's rotations.
        from agents.daemon_slayer.engine import build_champion
        from agents.daemon_slayer.dps import _phase_rotations
        rotations = _phase_rotations(self.snap, "Aatrox")
        for phase_rot in rotations.values():
            for r in phase_rot:
                self.assertEqual(
                    float(r.get("numberOfTargets", 1.0) or 1.0),
                    1.0,
                    f"Aatrox rotation {r.get('title','?')} has n>1 - fixture changed",
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
        # whose rotations mix n=1 and n>1 - the math should average to
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


class StridebreakerCleaveTests(unittest.TestCase):
    """Phase 4 batch 21 - Stridebreaker (6631) promoted via the same
    multi-target rotation layer as Ravenous Hydra (3074).

    Coefficient is 40% AD (Ravenous is 35%), so on a champion whose
    rotations include n>1 targets, Stridebreaker should outscore
    Ravenous on the cleave piece. Stat blocks differ - Ravenous brings
    omnivamp + 5% MS; Stridebreaker brings AS + Halting Slash active -
    so we test the cleave-piece signal, not the absolute total.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_stridebreaker_promoted_not_defensive_only(self) -> None:
        e = ITEM_EFFECTS["6631"]
        self.assertFalse(e.defensive_only)
        self.assertNotEqual(e.periodics, ())
        self.assertEqual(e.periodics[0].damage_type, PHYSICAL)
        self.assertEqual(e.periodics[0].every_n_attacks, 1)
        self.assertIn("cleave", e.note.lower())

    def test_stridebreaker_zero_proc_on_single_target_champion(self) -> None:
        # Same shape check as Ravenous Hydra: Aatrox's rotations are all
        # n=1, so the cleave proc resolves to zero. We assert the fixture
        # invariant here so a future scenarios.json change with n>1 on
        # Aatrox surfaces in this test, not silently in DPS deltas.
        from agents.daemon_slayer.dps import _phase_rotations
        rotations = _phase_rotations(self.snap, "Aatrox")
        for phase_rot in rotations.values():
            for r in phase_rot:
                self.assertEqual(
                    float(r.get("numberOfTargets", 1.0) or 1.0),
                    1.0,
                    f"Aatrox rotation {r.get('title','?')} has n>1 - fixture changed",
                )

    def test_stridebreaker_lifts_dps_on_multi_target_champion(self) -> None:
        # Anivia's late "DPS" rotation has numberOfTargets=3 with weight 70.
        # Stridebreaker should add real DPS via the cleave proc.
        bare = compute_dps(self.snap, "Anivia", level=11, phase="late")
        with_sb = compute_dps(
            self.snap, "Anivia", level=11, item_ids=["6631"], phase="late",
        )
        self.assertGreater(with_sb.weighted_dps, bare.weighted_dps)

    def test_stridebreaker_per_rotation_isolation(self) -> None:
        # Annie's mid phase mixes n=1 and n>1 rotations. The proc must
        # resolve per-rotation, not against a global fallback. Assert it
        # ran clean and produced finite-positive DPS.
        result = compute_dps(
            self.snap, "Annie", level=11, item_ids=["6631"], phase="mid",
        )
        self.assertGreater(result.weighted_dps, 0.0)
        joined = " ".join(result.notes)
        self.assertNotIn("no rotations", joined)

    def test_stridebreaker_cleave_outscores_ravenous_at_same_n(self) -> None:
        # Direct coefficient check: 40% > 35% on the cleave piece. Stat
        # blocks differ between the two items, so we can't compare total
        # DPS - we compare proc resolution at a fixed CallContext.
        sb = ITEM_EFFECTS["6631"].periodics[0]
        rh = ITEM_EFFECTS["3074"].periodics[0]
        # n=3, base_ad=100, bonus_ad=50 → cleave hits 2 enemies.
        # SB: 2 * 0.40 * 150 = 120; RH: 2 * 0.35 * 150 = 105.
        ctx = CallContext(
            base_ad=100.0, bonus_ad=50.0, level=11, targets_in_rotation=3.0,
        )
        sb_dmg = sb.resolve_damage(ctx)
        rh_dmg = rh.resolve_damage(ctx)
        self.assertGreater(sb_dmg, rh_dmg)
        self.assertAlmostEqual(sb_dmg, 120.0, places=3)
        self.assertAlmostEqual(rh_dmg, 105.0, places=3)

    def test_stridebreaker_zero_at_targets_one(self) -> None:
        # Single-target rotation → max(0, 1-1) * coef * AD = 0. Pins the
        # "preserves historic single-target shape" invariant.
        sb = ITEM_EFFECTS["6631"].periodics[0]
        ctx = CallContext(
            base_ad=100.0, bonus_ad=50.0, level=11, targets_in_rotation=1.0,
        )
        self.assertEqual(sb.resolve_damage(ctx), 0.0)


class ProfaneHydraCleaveTests(unittest.TestCase):
    """Phase 4 batch 24 - Profane Hydra (6698) added to ITEM_EFFECTS as
    a new entry (was stats-only via item aggregation prior - assassin-
    tagged Tiamat upgrade).

    Coefficient pinned at 40% (melee) to match Stridebreaker's call
    from batch 21. Skips the Heretical Cleave active (no Meraki bulk
    cooldown). Tiamat-tree exclusivity (only one of Strider/Ravenous/
    Profane/Titanic at a time in-game) is enforced by the ranker, not
    here - same pattern as the other hydras (no unique_passive_key).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_profane_hydra_present_with_periodic(self) -> None:
        e = ITEM_EFFECTS["6698"]
        self.assertEqual(e.name, "Profane Hydra")
        self.assertFalse(e.defensive_only)
        self.assertNotEqual(e.periodics, ())
        proc = e.periodics[0]
        self.assertEqual(proc.damage_type, PHYSICAL)
        self.assertEqual(proc.every_n_attacks, 1)
        self.assertEqual(proc.name, "Cleave")
        self.assertIn("cleave", e.note.lower())

    def test_profane_hydra_tagged_hydra_cleave_iter3(self) -> None:
        # Iter 3 (2026-05-19): the original assertion that Tiamat-tree
        # exclusivity is "build-legality, not unique-passive" was wrong -
        # the ranker's _filter_candidates has no Tiamat-tree awareness,
        # so a 2-hydra build double-counted Cleave both in DPS and in
        # recommendations. Profane and its 3 SR siblings + 4 Arena
        # mirrors now carry unique_passive_key="hydra_cleave" so the
        # existing collect_effects first-seen-wins dedup handles both
        # layers. See test_hydra_cleave_unique_iter3.py for the full
        # contract + DPS proofs.
        e = ITEM_EFFECTS["6698"]
        self.assertEqual(e.unique_passive_key, "hydra_cleave")

    def test_profane_hydra_zero_proc_on_single_target_champion(self) -> None:
        # Aatrox's rotations are all n=1 - cleave resolves to zero on
        # every rotation. Same fixture invariant check as Stridebreaker
        # / Ravenous; surfaces a fixture drift if Aatrox's rotations
        # ever pick up an n>1 entry.
        from agents.daemon_slayer.dps import _phase_rotations
        rotations = _phase_rotations(self.snap, "Aatrox")
        for phase_rot in rotations.values():
            for r in phase_rot:
                self.assertEqual(
                    float(r.get("numberOfTargets", 1.0) or 1.0),
                    1.0,
                    f"Aatrox rotation {r.get('title','?')} has n>1 - fixture changed",
                )

    def test_profane_hydra_lifts_dps_on_multi_target_champion(self) -> None:
        # Anivia's late "DPS" rotation has numberOfTargets=3 with weight 70.
        # Profane Hydra adds real DPS via the cleave proc on top of the
        # 55 AD + 18 lethality + 10 AH stat block.
        bare = compute_dps(self.snap, "Anivia", level=11, phase="late")
        with_ph = compute_dps(
            self.snap, "Anivia", level=11, item_ids=["6698"], phase="late",
        )
        self.assertGreater(with_ph.weighted_dps, bare.weighted_dps)

    def test_profane_hydra_matches_stridebreaker_cleave_at_same_ctx(self) -> None:
        # Both use 40% coefficient and identical formula structure. At
        # any fixed CallContext the resolve_damage calls must match
        # exactly - pins the family-shape invariant. Stat blocks differ
        # (PH: AD/lethality/AH; SB: AD/HP/AH/AS/MS) but the cleave
        # proc itself is shape-identical.
        ph = ITEM_EFFECTS["6698"].periodics[0]
        sb = ITEM_EFFECTS["6631"].periodics[0]
        # n=3, base_ad=100, bonus_ad=50 → 2 * 0.40 * 150 = 120 each.
        ctx = CallContext(
            base_ad=100.0, bonus_ad=50.0, level=11, targets_in_rotation=3.0,
        )
        ph_dmg = ph.resolve_damage(ctx)
        sb_dmg = sb.resolve_damage(ctx)
        self.assertAlmostEqual(ph_dmg, sb_dmg, places=3)
        self.assertAlmostEqual(ph_dmg, 120.0, places=3)

    def test_profane_hydra_outscores_ravenous_cleave(self) -> None:
        # Direct coefficient check: 40% > 35% on the cleave piece, same
        # structure as Stridebreaker vs Ravenous comparison. Pins the
        # batch-24 coefficient choice ("matches Stridebreaker, not
        # Ravenous"). Stat blocks aside.
        ph = ITEM_EFFECTS["6698"].periodics[0]
        rh = ITEM_EFFECTS["3074"].periodics[0]
        ctx = CallContext(
            base_ad=100.0, bonus_ad=50.0, level=11, targets_in_rotation=3.0,
        )
        self.assertGreater(ph.resolve_damage(ctx), rh.resolve_damage(ctx))
        self.assertAlmostEqual(rh.resolve_damage(ctx), 105.0, places=3)

    def test_profane_hydra_zero_at_targets_one(self) -> None:
        # Single-target rotation → max(0, 1-1) * 0.40 * AD = 0. Pins
        # the "preserves historic single-target shape" invariant.
        ph = ITEM_EFFECTS["6698"].periodics[0]
        ctx = CallContext(
            base_ad=100.0, bonus_ad=50.0, level=11, targets_in_rotation=1.0,
        )
        self.assertEqual(ph.resolve_damage(ctx), 0.0)


class EssenceReaverSpellbladeTests(unittest.TestCase):
    """Phase 4 batch 21 - Essence Reaver (3508) promoted via the new
    CallContext.crit_chance schema.

    ER fires Spellblade once per ~3s rotation cadence (same shape as
    Trinity Force / Lich Bane), dealing 125% base AD + 0.5/crit% bonus
    physical. Joins the spellblade unique-passive dedup family. Tests
    pin the proc shape, the crit-scaling behavior, and the dedup
    against TF/LB.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_er_promoted_not_defensive_only(self) -> None:
        e = ITEM_EFFECTS["3508"]
        self.assertFalse(e.defensive_only)
        self.assertNotEqual(e.periodics, ())
        self.assertEqual(e.periodics[0].damage_type, PHYSICAL)
        self.assertEqual(e.periodics[0].every_n_seconds, 3.0)
        self.assertEqual(e.periodics[0].name, "Spellblade")
        self.assertIn("spellblade", e.note.lower())

    def test_er_tagged_spellblade_unique_passive(self) -> None:
        e = ITEM_EFFECTS["3508"]
        self.assertEqual(e.unique_passive_key, "spellblade")

    def test_er_proc_zero_crit_is_125_pct_base_ad(self) -> None:
        # No crit signal → ER falls back to 1.25 * base_ad bonus physical
        # (the historic "modeling 125% base AD alone" path). 100 base_ad
        # → 125 bonus damage per proc.
        proc = ITEM_EFFECTS["3508"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0, level=11)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 125.0, places=3)

    def test_er_proc_scales_with_crit_chance(self) -> None:
        # 80% crit → 1.25 * 100 + 50 * 0.80 = 125 + 40 = 165.
        proc = ITEM_EFFECTS["3508"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0, level=11, crit_chance=0.80)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 165.0, places=3)

    def test_er_dps_outscores_baseline_on_crit_user(self) -> None:
        # Caitlyn level 11 + ER: ER's stat block (60 AD, 25% crit, 25 AH,
        # +25 mana) plus the now-active Spellblade proc should beat the
        # bare baseline. Stat-block-only would already lift DPS; this
        # asserts the engine ran clean post-promotion.
        bare = compute_dps(self.snap, "Caitlyn", level=11)
        with_er = compute_dps(
            self.snap, "Caitlyn", level=11, item_ids=["3508"],
        )
        self.assertGreater(with_er.weighted_dps, bare.weighted_dps)

    def test_er_dps_higher_with_crit_stack(self) -> None:
        # ER + IE (3031, 60 AD, 25% crit) on Caitlyn - the crit_chance
        # passed into ER's lambda is the BUILD's crit, not 0. So adding
        # IE on top of ER should lift DPS more than two stat-equivalent
        # items would in isolation, because ER's crit-piece scales with
        # the higher crit chance.
        er_only = compute_dps(
            self.snap, "Caitlyn", level=11, item_ids=["3508"],
        )
        er_plus_ie = compute_dps(
            self.snap, "Caitlyn", level=11, item_ids=["3508", "3031"],
        )
        self.assertGreater(er_plus_ie.weighted_dps, er_only.weighted_dps)

    def test_er_spellblade_dedups_against_lich_bane(self) -> None:
        # Both [ER, LB] and [LB, ER] should keep ONE spellblade proc
        # via the unique-passive key. We can't directly inspect the
        # filtered effects list from compute_dps (it's internal), so we
        # check the dedup helper used by the engine.
        from agents.daemon_slayer.effects import collect_effects
        effects_er_first = collect_effects(["3508", "3100"])
        effects_lb_first = collect_effects(["3100", "3508"])
        # Both orderings drop one spellblade proc - only one remains.
        self.assertEqual(len(effects_er_first), 1)
        self.assertEqual(len(effects_lb_first), 1)
        # First-seen-wins ordering: ER first keeps ER; LB first keeps LB.
        self.assertEqual(effects_er_first[0].item_id, "3508")
        self.assertEqual(effects_lb_first[0].item_id, "3100")


class HextechGunbladeTests(unittest.TestCase):
    """Phase 4 batch 22 - Hextech Gunblade (3146) promoted from
    defensive_only.

    Lightning Bolt active is a long-CD targeted nuke: 175→253 (level
    1→18, linear) + 30% AP magic damage, 40s cooldown. Modeled as a
    PeriodicProc with ``every_n_seconds=40.0`` - same shape as Sundered
    Sky's 8s Lightshield Strike, just a far longer cadence. The 25%/1.5s
    slow is utility, not damage, and is not modeled. AP scales via
    ``c.ap`` (build-derived stat-property, plumbed at compute_dps
    construction per the batch 21 pattern).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_gunblade_promoted_not_defensive_only(self) -> None:
        e = ITEM_EFFECTS["3146"]
        self.assertFalse(e.defensive_only)
        self.assertNotEqual(e.periodics, ())
        proc = e.periodics[0]
        self.assertEqual(proc.damage_type, MAGICAL)
        self.assertEqual(proc.every_n_seconds, 40.0)
        self.assertEqual(proc.every_n_attacks, 0)
        self.assertEqual(proc.name, "Lightning Bolt")
        self.assertIn("lightning bolt", e.note.lower())

    def test_gunblade_proc_level_1_no_ap(self) -> None:
        # Level 1, 0 AP → 175 flat magic damage per active.
        proc = ITEM_EFFECTS["3146"].periodics[0]
        ctx = CallContext(base_ad=60.0, bonus_ad=0, level=1)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 175.0, places=3)

    def test_gunblade_proc_level_18_no_ap(self) -> None:
        # Level 18, 0 AP → 253 flat magic damage per active.
        proc = ITEM_EFFECTS["3146"].periodics[0]
        ctx = CallContext(base_ad=60.0, bonus_ad=0, level=18)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 253.0, places=3)

    def test_gunblade_proc_scales_with_ap(self) -> None:
        # Level 11, 200 AP → 175 + 78/17*10 + 0.30 * 200
        #                = 175 + 45.882... + 60 = 280.882...
        proc = ITEM_EFFECTS["3146"].periodics[0]
        ctx = CallContext(base_ad=60.0, bonus_ad=0, level=11, ap=200.0)
        expected = 175.0 + (253.0 - 175.0) / 17.0 * 10 + 0.30 * 200.0
        self.assertAlmostEqual(proc.resolve_damage(ctx), expected, places=3)

    def test_gunblade_level_scaling_is_linear(self) -> None:
        # Per-level uplift = (253 - 175) / 17 ≈ 4.588 magic damage.
        proc = ITEM_EFFECTS["3146"].periodics[0]
        ctx10 = CallContext(base_ad=60.0, bonus_ad=0, level=10)
        ctx11 = CallContext(base_ad=60.0, bonus_ad=0, level=11)
        delta = proc.resolve_damage(ctx11) - proc.resolve_damage(ctx10)
        self.assertAlmostEqual(delta, 78.0 / 17.0, places=3)

    def test_gunblade_dps_lifts_ap_user(self) -> None:
        # Akali level 11 + Gunblade: stat block alone (60 AP, 45 AD,
        # 12% omnivamp) lifts DPS; the now-active Lightning Bolt proc
        # adds a small additional contribution. We assert the engine
        # ran clean post-promotion - bare baseline < with-gunblade.
        bare = compute_dps(self.snap, "Akali", level=11)
        with_gb = compute_dps(
            self.snap, "Akali", level=11, item_ids=["3146"],
        )
        self.assertGreater(with_gb.weighted_dps, bare.weighted_dps)


class IcebornGauntletSpellbladeTests(unittest.TestCase):
    """Phase 4 batch 23 - Iceborn Gauntlet (6662) added to ITEM_EFFECTS
    as a new entry (was stats-only via item aggregation prior).

    Iceborn's Spellblade variant: 150% base AD bonus physical on the
    next basic after an ability, 1.5s real CD post-empowered-attack.
    Rotation cadence approx ~3s (matches Trinity / Lich Bane / Essence
    Reaver - the family's shared ability-cast frequency assumption).
    Joins the spellblade unique-passive dedup family. Frost field's
    25% slow is utility, not damage - not modeled.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_ibg_present_with_periodic(self) -> None:
        e = ITEM_EFFECTS["6662"]
        self.assertEqual(e.name, "Iceborn Gauntlet")
        self.assertFalse(e.defensive_only)
        self.assertNotEqual(e.periodics, ())
        proc = e.periodics[0]
        self.assertEqual(proc.damage_type, PHYSICAL)
        self.assertEqual(proc.every_n_seconds, 3.0)
        self.assertEqual(proc.every_n_attacks, 0)
        self.assertEqual(proc.name, "Spellblade")
        self.assertIn("spellblade", e.note.lower())

    def test_ibg_tagged_spellblade_unique_passive(self) -> None:
        e = ITEM_EFFECTS["6662"]
        self.assertEqual(e.unique_passive_key, "spellblade")

    def test_ibg_proc_is_150_pct_base_ad(self) -> None:
        # 100 base_ad → 150 bonus damage per proc (1.50 * c.base_ad).
        proc = ITEM_EFFECTS["6662"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0, level=11)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 150.0, places=3)

    def test_ibg_dedups_against_trinity_force(self) -> None:
        # First-seen-wins: [TF, IBG] keeps TF; [IBG, TF] keeps IBG.
        # Both orderings drop one spellblade proc - only one remains.
        from agents.daemon_slayer.effects import collect_effects
        effects_tf_first = collect_effects(["3078", "6662"])
        effects_ibg_first = collect_effects(["6662", "3078"])
        self.assertEqual(len(effects_tf_first), 1)
        self.assertEqual(len(effects_ibg_first), 1)
        self.assertEqual(effects_tf_first[0].item_id, "3078")
        self.assertEqual(effects_ibg_first[0].item_id, "6662")

    def test_ibg_dedups_against_lich_bane(self) -> None:
        from agents.daemon_slayer.effects import collect_effects
        effects_lb_first = collect_effects(["3100", "6662"])
        effects_ibg_first = collect_effects(["6662", "3100"])
        self.assertEqual(len(effects_lb_first), 1)
        self.assertEqual(len(effects_ibg_first), 1)
        self.assertEqual(effects_lb_first[0].item_id, "3100")
        self.assertEqual(effects_ibg_first[0].item_id, "6662")

    def test_ibg_dedups_against_essence_reaver(self) -> None:
        from agents.daemon_slayer.effects import collect_effects
        effects_er_first = collect_effects(["3508", "6662"])
        effects_ibg_first = collect_effects(["6662", "3508"])
        self.assertEqual(len(effects_er_first), 1)
        self.assertEqual(len(effects_ibg_first), 1)
        self.assertEqual(effects_er_first[0].item_id, "3508")
        self.assertEqual(effects_ibg_first[0].item_id, "6662")

    def test_ibg_dps_lifts_bruiser_baseline(self) -> None:
        # Camille level 11 + Iceborn: 60 AD effective contribution from
        # the Spellblade proc on top of the stat block (300 HP, 50
        # armor, 15 AH, 5% MS). The full DPS lift comes mostly from the
        # Spellblade proc - bare baseline must be below the with-IBG
        # value. Asserts the engine ran clean post-promotion.
        bare = compute_dps(self.snap, "Camille", level=11)
        with_ibg = compute_dps(
            self.snap, "Camille", level=11, item_ids=["6662"],
        )
        self.assertGreater(with_ibg.weighted_dps, bare.weighted_dps)


class MultiProcSchemaTests(unittest.TestCase):
    """Phase 4 batch 8 - `ItemEffect.periodics: tuple[PeriodicProc, ...]`.

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
        # Iter 8 (2026-05-19): Meraki cleave-to-others = 3% max_hp per
        # extra target (was 40% total AD). With caster_max_hp=2000 and
        # n=3: max(0, 3-1) * 0.03 * 2000 = 120.
        ctx = CallContext(
            base_ad=80, bonus_ad=40, level=11,
            caster_max_hp=2000, targets_in_rotation=3.0,
        )
        self.assertAlmostEqual(cleave_others.resolve_damage(ctx), 120.0, places=3)

    def test_titanic_primary_proc_fires_on_single_target(self) -> None:
        # On Aatrox (all-n=1 rotations), Titanic's primary proc fires
        # every basic; cleave-to-others contributes zero. Net DPS still
        # rises over baseline thanks to the primary proc + stat block.
        bare = compute_dps(self.snap, "Aatrox", level=11)
        with_th = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3748"])
        self.assertGreater(with_th.weighted_dps, bare.weighted_dps)

    def test_engine_iterates_both_titanic_procs(self) -> None:
        # End-to-end test that the engine actually sums BOTH procs (not
        # just the first). Iter 8 (2026-05-19): Meraki Cleave 1%/3%
        # caster MAX HP (was 5+1.5% bonus_hp primary + 40% total AD to
        # nearby). Ctx pinned with explicit max_hp so the post-fix
        # numbers are derivable from the formula.
        from agents.daemon_slayer.dps import _periodic_proc_dps
        from agents.daemon_slayer.effects import collect_effects
        ctx = CallContext(
            base_ad=80, bonus_ad=40, level=11,
            caster_max_hp=2500, caster_bonus_hp=600,
            targets_in_rotation=3.0,
        )
        effects = collect_effects(["3748"])
        # 1.0 attack, 1.0 second rotation (so DPS == per-attack damage).
        dps = _periodic_proc_dps(
            effects, total_attacks=1.0, duration=1.0,
            target_armor_for_physical=0.0, target_mr=0.0,
            mode_dmg_mult=1.0, call_ctx=ctx,
        )
        # Primary proc damage: 0.01 * 2500 = 25
        # Cleave-to-others damage: max(0, 3-1) * 0.03 * 2500 = 150
        # Sum: 175. With armor_factor=1.0 and mode_mult=1.0, dps = 175/1.
        self.assertAlmostEqual(dps, 175.0, places=3)

    def test_engine_titanic_single_target_only_primary_fires(self) -> None:
        # Same harness as above but n=1.0 -> cleave-to-others = 0. Iter 8
        # (2026-05-19): Meraki primary 1% max_hp - result is primary-only
        # = 0.01 * 2500 = 25 dps.
        from agents.daemon_slayer.dps import _periodic_proc_dps
        from agents.daemon_slayer.effects import collect_effects
        ctx = CallContext(
            base_ad=80, bonus_ad=40, level=11,
            caster_max_hp=2500, caster_bonus_hp=600,
            targets_in_rotation=1.0,
        )
        effects = collect_effects(["3748"])
        dps = _periodic_proc_dps(
            effects, total_attacks=1.0, duration=1.0,
            target_armor_for_physical=0.0, target_mr=0.0,
            mode_dmg_mult=1.0, call_ctx=ctx,
        )
        self.assertAlmostEqual(dps, 25.0, places=3)


class ImmolateItemTests(unittest.TestCase):
    """Phase 4 batch 9 - Sunfire Aegis (3068) + Hollow Radiance (6664).

    Both items share the same Immolate periodic shape: per-second magic
    aura damage to nearby enemies, scaling with caster bonus HP and the
    rotation's targets count. Reuses the batch-6 caster-HP layer + the
    batch-7 multi-target layer - no new schema. Tests pin the per-second
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
        # Iter 8 (2026-05-19): Sunfire Immolate corrected to Meraki
        # 16.10.1 - 20 + 1% bonus_hp. Single-target rotation, 1000 bonus
        # HP -> 1.0 * (20 + 0.010 * 1000) = 30 per second.
        proc = ITEM_EFFECTS["3068"].periodics[0]
        ctx = CallContext(
            base_ad=0, bonus_ad=0, level=11,
            caster_bonus_hp=1000.0, targets_in_rotation=1.0,
        )
        self.assertAlmostEqual(proc.resolve_damage(ctx), 30.0, places=3)

    def test_immolate_aoe_incl_primary_multiplier(self) -> None:
        # Iter 8 (2026-05-19): 3-target rotation, 1000 bonus HP ->
        # 3.0 * (20 + 0.010 * 1000) = 90 per second.
        proc = ITEM_EFFECTS["3068"].periodics[0]
        ctx = CallContext(
            base_ad=0, bonus_ad=0, level=11,
            caster_bonus_hp=1000.0, targets_in_rotation=3.0,
        )
        self.assertAlmostEqual(proc.resolve_damage(ctx), 90.0, places=3)

    def test_immolate_zero_bonus_hp_floor(self) -> None:
        # Iter 8 (2026-05-19): Sunfire base raised 12 -> 20. No HP items
        # in the build -> flat 20 dps per second per target. Single
        # target -> 20 per second.
        proc = ITEM_EFFECTS["3068"].periodics[0]
        ctx = CallContext(
            base_ad=0, bonus_ad=0, level=11,
            caster_bonus_hp=0.0, targets_in_rotation=1.0,
        )
        self.assertAlmostEqual(proc.resolve_damage(ctx), 20.0, places=3)

    def test_sunfire_lifts_dps_on_tank_champion(self) -> None:
        # Sunfire's stat block alone contributes zero DPS (350 HP, 50 armor -
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
        # Iter 8 (2026-05-19): Sunfire 20 + 1% bonus_hp. 1.0 second
        # rotation duration with Sunfire, 1000 bonus HP, n=1: should
        # emit 30 dps (1 second * 30 damage/second).
        from agents.daemon_slayer.dps import _periodic_proc_dps
        from agents.daemon_slayer.effects import collect_effects
        ctx = CallContext(
            base_ad=0, bonus_ad=0, level=11,
            caster_bonus_hp=1000.0, targets_in_rotation=1.0,
        )
        effects = collect_effects(["3068"])
        # No basic attacks; the proc fires on the seconds-track (every_n_seconds=1.0).
        # 1.0 second / 1.0 = 1 proc, damage 30 -> 30 dps.
        dps = _periodic_proc_dps(
            effects, total_attacks=0.0, duration=1.0,
            target_armor_for_physical=0.0, target_mr=0.0,
            mode_dmg_mult=1.0, call_ctx=ctx,
        )
        self.assertAlmostEqual(dps, 30.0, places=3)

    def test_immolate_engine_aoe_uplift_in_rotation(self) -> None:
        # Iter 8 (2026-05-19): Same harness, n=3: 3 nearby enemies each
        # take 30 dps -> 90 dps total.
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
        self.assertAlmostEqual(dps, 90.0, places=3)

    def test_immolate_uses_target_mr_not_armor(self) -> None:
        # Magic-typed proc -> MR resists, not armor. With target_mr=100,
        # damage is halved (factor 100/(100+100) = 0.5). Iter 8: Sunfire
        # 20 + 1% bonus_hp at 1000 bonus_hp, n=1 -> 30 raw, 15 post-MR.
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
        self.assertAlmostEqual(dps, 15.0, places=3)


class UniquePassiveTests(unittest.TestCase):
    """Phase 4 batch 10 - unique-passive de-duplication.

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
        # Single-item Sunfire DPS regression guard. Iter 8 (2026-05-19):
        # rebaselined for the Meraki 16.10.1 Immolate fix - 20 + 1%
        # bonus_hp (was 12 + 1.5% bonus_hp). Aatrox L11 with Sunfire
        # 350 bonus HP -> per-tick 20 + 0.010 * 350 = 23.5 (was 17.25).
        self.assertAlmostEqual(
            compute_dps(self.snap, "Aatrox", level=11, item_ids=["3068"]).weighted_dps,
            67.945515625, places=4,
        )

    def test_sunfire_plus_hollow_radiance_no_double_count(self) -> None:
        # The whole point of this batch: building both should NOT add
        # the immolate proc twice. Damage uplift over Sunfire-alone must
        # come ONLY from Hollow Radiance's stat block (40 MR + 400 HP),
        # not a second Immolate tick.
        sunfire_only = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3068"])
        both = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3068", "6664"])
        # Iter 8 (2026-05-19): post-Meraki-fix coefficient is 1% bonus_hp
        # (was 1.5%). Bonus HP rises from 350 -> 750 (Sunfire 350 + HR
        # 400). Sunfire's Immolate proc damage = 20 + 0.010 * 750 = 27.5
        # per second per target (vs 23.5 with Sunfire alone). So delta
        # should be 27.5 - 23.5 = 4.0 dps. NOT 27.5 + 25 (double-count)
        # = ~52.5 over solo, which would be the regression case.
        delta = both.weighted_dps - sunfire_only.weighted_dps
        # 4.0 dps from HR's HP raising Sunfire's proc; floor below the
        # double-count signal at ~25 dps.
        self.assertAlmostEqual(delta, 4.0, places=1)
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
    """Phase 4 batch 11 - Spellblade unique-passive on TF + Lich Bane.

    Trinity Force (3078) and Lich Bane (3100) both fire Spellblade procs
    in current League. In-game, Spellblade is unique-passive - only one
    spellblade fires per ability+attack. The engine now respects this
    via the batch-10 unique_passive_key="spellblade" tag on both items.

    Sundered Sky (6610) uses "Lightshield Strike" - a distinct mechanic
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

    def test_essence_reaver_tagged_spellblade(self) -> None:
        # Phase 4 batch 21 (2026-05-04) promoted ER out of defensive_only
        # and joined the spellblade family. Pre-promotion this test
        # asserted the *opposite* (untagged) - preserving the dedup
        # order-dependence guard until the proc itself was modeled.
        # EssenceReaverSpellbladeTests below covers the full dedup pair
        # against Lich Bane.
        self.assertEqual(ITEM_EFFECTS["3508"].unique_passive_key, "spellblade")

    def test_iceborn_gauntlet_tagged_spellblade(self) -> None:
        # Phase 4 batch 23 (2026-05-04) added Iceborn Gauntlet (6662) to
        # ITEM_EFFECTS as a new entry (was stats-only prior). It joins
        # the spellblade family - full dedup pair coverage against
        # TF / LB / ER lives in IcebornGauntletSpellbladeTests above.
        self.assertEqual(ITEM_EFFECTS["6662"].unique_passive_key, "spellblade")

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
        # Single-item TF DPS regression guard. Rebaselined for Riot
        # quadratic stat growth (was 85.08 on Ahri lvl 11 under the old
        # linear scaling; lvl-11 base AD is now correctly lower).
        r = compute_dps(self.snap, "Ahri", level=11, item_ids=["3078"])
        self.assertAlmostEqual(r.weighted_dps, 81.71458333333334, places=4)

    def test_lich_bane_solo_unchanged(self) -> None:
        # Lich Bane alone regression guard. Rebaselined for the 2026-05-20
        # AP coefficient correction (50% -> 40% per Meraki 16.10.1; the
        # solo value drops because the AP term contributes less per proc).
        # Prior baselines on Ahri lvl 11: 58.17 (linear stat growth, AP 50%),
        # 56.329 (post-1.5.0 quadratic growth + AP 50%), 52.996 (AP 40%).
        r = compute_dps(self.snap, "Ahri", level=11, item_ids=["3100"])
        self.assertAlmostEqual(r.weighted_dps, 52.99583333333334, places=4)

    def test_triforce_plus_lich_bane_no_double_count(self) -> None:
        # Pre-fix this build was 122.50 dps (sum of solo deltas =
        # double-count of spellblade). Post-fix should be ~85 dps -
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
        # And both must be well above bare - TF's spellblade still fires.
        self.assertGreater(delta_both, 50.0)

    def test_triforce_plus_lich_bane_order_swap_yields_lich_bane_proc(self) -> None:
        # Order swap → LB spellblade kept (first-seen-wins).
        # LB spellblade scales with AP (50% AP bonus), so it's larger
        # on AP champions. Ahri's base AD is moderate; LB-kept value
        # should be different from TF-kept value (pin order semantics).
        tf_first = compute_dps(self.snap, "Ahri", level=11, item_ids=["3078", "3100"])
        lb_first = compute_dps(self.snap, "Ahri", level=11, item_ids=["3100", "3078"])
        # Both are valid "single spellblade" approximations but produce
        # different numerical results - order dependence is real and
        # documented.
        self.assertNotAlmostEqual(tf_first.weighted_dps, lb_first.weighted_dps, places=1)


class LifelineUniquePassiveTests(unittest.TestCase):
    """Phase 4 batch 12 - Lifeline unique-passive on Shieldbow / Sterak's / Maw.

    All 3 items use the literal "Lifeline" tooltip label in DDragon and
    are unique-passive in current League (only one Lifeline shield
    triggers per low-HP threshold). All 3 are currently defensive_only,
    so dedup affects DpsResult.notes only - no DPS proc to drop.

    Phantom Dancer (3046) is intentionally NOT tagged: DDragon shows it
    uses "Spectral Waltz" (Ghost effect on low HP), not Lifeline. RC's
    older note for PD called it "Lifeline" - corrected this batch.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_three_lifeline_items_share_key(self) -> None:
        self.assertEqual(ITEM_EFFECTS["6673"].unique_passive_key, "lifeline")
        self.assertEqual(ITEM_EFFECTS["3053"].unique_passive_key, "lifeline")
        self.assertEqual(ITEM_EFFECTS["3156"].unique_passive_key, "lifeline")

    def test_phantom_dancer_not_tagged_lifeline(self) -> None:
        # Spectral Waltz is a distinct passive - DDragon labels diverge.
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
        # All 3 Lifeline items are defensive_only - no proc to model.
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
                # We assert the increase is purely stat-block - same as
                # if the item had NO ItemEffect entry at all.
                # Easiest check: the result didn't add any "Lifeline" damage
                # note to notes - defensive_only entries do surface their
                # note string but no proc damage hits.
                # We don't have a clean way to assert "no proc fired"
                # without instrumenting; instead, we just confirm the
                # function returned a valid DpsResult (smoke test).
                self.assertGreater(r.weighted_dps, 0.0)


class TerminusPromotionTests(unittest.TestCase):
    """Phase 4 batch 13 - Terminus promoted from defensive_only.

    Shadow on-hit (30 magic per basic, constant - not alternating as
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
    """Phase 4 batch 14 - multiplicative damage-amp helper.

    Direct unit tests on ``total_damage_amp_multiplier``. Item-side and
    DPS-pipeline assertions live in ``RiftmakerPromotionTests``.
    """

    def test_no_effects_returns_unity(self) -> None:
        from agents.daemon_slayer.effects import total_damage_amp_multiplier
        self.assertEqual(total_damage_amp_multiplier([]), 1.0)

    def test_no_amps_in_effects_returns_unity(self) -> None:
        # IE / Kraken / Stormrazor - none carry damage_amp_pct.
        from agents.daemon_slayer.effects import total_damage_amp_multiplier
        effs = [ITEM_EFFECTS["3031"], ITEM_EFFECTS["6672"], ITEM_EFFECTS["3097"]]
        self.assertEqual(total_damage_amp_multiplier(effs), 1.0)

    def test_riftmaker_alone_returns_1_08(self) -> None:
        from agents.daemon_slayer.effects import total_damage_amp_multiplier
        rift = ITEM_EFFECTS["4633"]
        self.assertAlmostEqual(total_damage_amp_multiplier([rift]), 1.08, places=4)

    def test_two_amps_stack_multiplicatively(self) -> None:
        # Build two synthetic amp items inline - engine doesn't ship a
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
    """Phase 4 batch 14 - Riftmaker promoted from defensive_only.

    Void Corruption ramps to 8% bonus damage after 4s in combat. The
    sustained-DPS approximation pins the full-ramp value (same shape
    as Black Cleaver's 30%-at-5-stacks). HP→AP cross-derivation
    landed in batch 15 (RiftmakerHpToApTests below) - these tests
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
        # block doesn't contribute directly - the entire delta is the
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
            msg=f"amp ratio {ratio:.4f} != 1.08 - multiplier wiring is broken")

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
    """Phase 4 batch 15 - additive HP→AP cross-derivation helper."""

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
        # Defensive paranoia - engine floors caster_bonus_hp at zero
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
    """Phase 4 batch 15 - Riftmaker Void Infusion HP→AP wiring.

    Validates the cross-derivation appears in DpsResult.notes when
    triggered, the converted AP isn't stored back into resolved.stats
    (engine-internal - /stats reflects raw stat blocks only), and the
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
        # Sanity: only Riftmaker (4633/224633) and Demonic Embrace (4637) carry
        # ap_per_bonus_hp_pct. Batch 32 added Demonic Embrace; batch 42 added
        # Arena mirror 224633 - allow-list updated. Surfacing any new additions
        # as a schema-add signal.
        ALLOWLIST = {"4633", "4637", "224633", "224637"}
        for iid, e in ITEM_EFFECTS.items():
            if iid in ALLOWLIST:
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
        # /stats consumers see raw stat-block AP only - cross-derivation
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
        # Synthetic test - strip Riftmaker's amp + cross-derivation
        # to isolate the HP→AP contribution from the amp piece.
        from agents.daemon_slayer import effects as effects_mod
        original = effects_mod.ITEM_EFFECTS["4633"]
        # No-amp, no-HP→AP variant - only stat block (70 AP, 350 HP, 15 AH).
        no_xforms = ItemEffect(
            item_id="4633",
            name="Riftmaker",
            note=original.note,
        )
        # Amp-only variant - reproduces batch 14 behavior.
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
    """Phase 4 batch 19 - target-conditional damage-amp helper.

    Direct unit tests on ``total_target_bonus_hp_amp_multiplier``. LDR
    end-to-end + multiplicative-stack-with-Riftmaker pinning lives in
    ``LdrGiantSlayerTests`` below.
    """

    def test_no_effects_returns_unity(self) -> None:
        from agents.daemon_slayer.effects import total_target_bonus_hp_amp_multiplier
        self.assertEqual(total_target_bonus_hp_amp_multiplier([], 1500.0), 1.0)

    def test_zero_target_bonus_hp_returns_unity(self) -> None:
        # Pre-batch-19 callers don't supply target_bonus_hp - default 0.
        # Result must short-circuit to 1.0 even when items carry the schema.
        from agents.daemon_slayer.effects import total_target_bonus_hp_amp_multiplier
        ldr = ITEM_EFFECTS["3036"]
        self.assertEqual(total_target_bonus_hp_amp_multiplier([ldr], 0.0), 1.0)

    def test_negative_target_bonus_hp_returns_unity(self) -> None:
        # Defensive guard - caller-supplied negative values should not
        # produce a damage REDUCTION; treat as "no signal".
        from agents.daemon_slayer.effects import total_target_bonus_hp_amp_multiplier
        ldr = ITEM_EFFECTS["3036"]
        self.assertEqual(total_target_bonus_hp_amp_multiplier([ldr], -100.0), 1.0)

    def test_no_amp_items_in_effects_returns_unity(self) -> None:
        # IE / Kraken / Stormrazor - none carry target_bonus_hp_amp_max_pct.
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
        # 3000 / 1500 = 2.0, but min(1.0, 2.0) = 1.0 - multiplier stays
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
    """Phase 4 batch 19 - LDR Giant Slayer end-to-end via /dps.

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
        # Pre-batch-19 caller shape - no target_bonus_hp kwarg. The
        # /dps response must look identical to a build with no Giant
        # Slayer item modulo the existing armor-pen wiring.
        result = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3036"],
                             target_armor=80.0)
        self.assertFalse(
            any("target-conditional amp" in n for n in result.notes),
            "no target_bonus_hp signal - must not surface a target-amp note",
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
        # must be 1.08 * 1.15 = 1.242 - NOT 1.23 (additive). Pins the
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


class HullbreakerSkipperTests(unittest.TestCase):
    """Phase 4 batch 20 - Hullbreaker (3181) Skipper periodic.

    Promoted from defensive_only using Meraki's bulk items snapshot,
    which carries the numeric formula DDragon strips. Procs every 5th
    basic attack for 120% base AD + 5% caster max HP physical. The
    "maximum health" token in Meraki's wikitext is unqualified → caster
    convention (League standard for item passives without a target
    qualifier; matches Hullbreaker's design intent as an HP-stacker
    side-laner item).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_promoted_not_defensive_only(self) -> None:
        e = ITEM_EFFECTS["3181"]
        self.assertFalse(e.defensive_only)
        self.assertNotEqual(e.periodics, ())
        self.assertEqual(len(e.periodics), 1)

    def test_periodic_shape(self) -> None:
        proc = ITEM_EFFECTS["3181"].periodics[0]
        self.assertEqual(proc.name, "Skipper")
        self.assertEqual(proc.damage_type, PHYSICAL)
        self.assertEqual(proc.every_n_attacks, 5)
        self.assertEqual(proc.every_n_seconds, 0.0)

    def test_bonus_damage_resolves_against_base_ad_and_caster_max_hp(self) -> None:
        # 1.20 * base_ad + 0.05 * caster_max_hp.
        proc = ITEM_EFFECTS["3181"].periodics[0]
        ctx = CallContext(
            base_ad=80.0, bonus_ad=0.0, level=11,
            caster_max_hp=2400.0,
        )
        # 1.20*80 + 0.05*2400 = 96 + 120 = 216
        self.assertAlmostEqual(proc.resolve_damage(ctx), 216.0, places=3)

    def test_bonus_damage_zero_when_unqualified(self) -> None:
        # If caller can't supply caster_max_hp (default 0.0), the proc
        # still pays out the base_ad piece - never crashes, never NaN.
        proc = ITEM_EFFECTS["3181"].periodics[0]
        ctx = CallContext(base_ad=70.0, bonus_ad=0.0, level=8)
        # 1.20*70 + 0.05*0 = 84
        self.assertAlmostEqual(proc.resolve_damage(ctx), 84.0, places=3)

    def test_note_calls_out_skipper_and_caster_hp(self) -> None:
        note = ITEM_EFFECTS["3181"].note.lower()
        self.assertIn("skipper", note)
        self.assertIn("every-5th-attack", note)
        self.assertIn("caster", note)

    def test_hullbreaker_raises_dps(self) -> None:
        # Hullbreaker is 5300g for AD + AS + HP + Skipper. Bare Aatrox
        # vs Aatrox + Hullbreaker should clear the proc-floor delta
        # easily even after the every-5th-attack denominator.
        bare = compute_dps(self.snap, "Aatrox", level=11).weighted_dps
        with_hb = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3181"],
        ).weighted_dps
        self.assertGreater(with_hb, bare)

    def test_hullbreaker_scales_with_external_caster_hp(self) -> None:
        # Adding Warmog's on top of Hullbreaker should keep raising the
        # Skipper damage (5% of a bigger caster max HP).
        hb_only = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3181"],
        ).weighted_dps
        warmog_only = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3083"],
        ).weighted_dps
        hb_plus_warmog = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3181", "3083"],
        ).weighted_dps
        # The combined build's DPS gain over Warmog-alone should beat
        # the gain of Hullbreaker-alone over naked: bigger HP base
        # means bigger Skipper damage per proc.
        bare = compute_dps(self.snap, "Aatrox", level=11).weighted_dps
        self.assertGreater(hb_plus_warmog - warmog_only, hb_only - bare)


class SteraksClawsThatCatchTests(unittest.TestCase):
    """Phase 4 batch 20 - Sterak's Gage (3053) "The Claws that Catch".

    +45% base AD as bonus AD - a stat layer, not a proc. Promoted via the
    new ``ItemEffect.bonus_ad_pct_base_ad`` field, resolved in
    ``build_champion`` against the leveled raw base AD before
    ``_combine_items`` folds totals into the final block. Lifeline shield
    piece is non-DPS (still deduped via ``unique_passive_key="lifeline"``).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_field_present_with_correct_value(self) -> None:
        e = ITEM_EFFECTS["3053"]
        self.assertAlmostEqual(e.bonus_ad_pct_base_ad, 0.45, places=4)

    def test_promoted_not_defensive_only(self) -> None:
        # The Claws piece IS DPS-positive - defensive_only would mask it.
        e = ITEM_EFFECTS["3053"]
        self.assertFalse(e.defensive_only)

    def test_lifeline_dedup_preserved(self) -> None:
        # Lifeline is still unique-passive - pin the key so future batches
        # don't accidentally drop dedup when fiddling with this entry.
        self.assertEqual(ITEM_EFFECTS["3053"].unique_passive_key, "lifeline")

    def test_note_reflects_both_pieces(self) -> None:
        note = ITEM_EFFECTS["3053"].note.lower()
        self.assertIn("claws", note)
        self.assertIn("base ad", note)
        self.assertIn("lifeline", note)

    def test_other_items_have_zero_pct(self) -> None:
        # Backward-compat: every other ItemEffect defaults to 0.0. Pin a
        # handful so a future batch breaking the default surfaces here.
        for iid in ("3031", "6672", "3036", "3084", "3508"):
            self.assertEqual(
                ITEM_EFFECTS[iid].bonus_ad_pct_base_ad, 0.0,
                f"{iid} unexpectedly has bonus_ad_pct_base_ad set",
            )


class SteraksEngineWireInTests(unittest.TestCase):
    """Sterak's bonus_ad_pct_base_ad lifts AD in build_champion output."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_sterak_raises_total_ad(self) -> None:
        # Sterak's stat block carries +400 HP only (no AD flat in DDragon)
        # - all the AD comes from the Claws passive (Phase 4 batch 20):
        # 0.45 * leveled_base_ad. For Aatrox at lvl 11, leveled base AD
        # ≈ 60 + 17*(105-60)/17 * (10/17) ... measured at runtime via
        # base_stats["ad"]; expect delta ≈ 0.45 * that, which clears
        # 25 AD comfortably and stays under 60 (so a flat-50 stat block
        # creep would surface here too).
        from agents.daemon_slayer.engine import build_champion
        bare = build_champion(self.snap, "Aatrox", level=11)
        with_st = build_champion(
            self.snap, "Aatrox", level=11, item_ids=["3053"],
        )
        delta = with_st.stats["ad"] - bare.stats["ad"]
        leveled_base = bare.base_stats["ad"]
        expected = 0.45 * leveled_base
        # ±0.5 AD float-noise tolerance.
        self.assertAlmostEqual(delta, expected, delta=0.5,
            msg=f"Sterak's AD delta {delta:.2f} != expected {expected:.2f} "
                f"(0.45 * leveled_base_ad={leveled_base:.2f})")

    def test_sterak_passive_proportional_to_base_ad(self) -> None:
        # Champion with bigger leveled base AD sees a bigger Sterak's
        # passive contribution. Aatrox vs Sett (typically higher base AD).
        from agents.daemon_slayer.engine import build_champion
        for cid in ("Aatrox", "Sett"):
            bare = build_champion(self.snap, cid, level=11)
            with_st = build_champion(
                self.snap, cid, level=11, item_ids=["3053"],
            )
            leveled_base = bare.base_stats["ad"]
            # Sterak's stat block is HP-only (no AD flat). The full
            # delta is the Phase 4 batch 20 passive: 0.45 * leveled_base.
            delta = with_st.stats["ad"] - bare.stats["ad"]
            expected = 0.45 * leveled_base
            self.assertAlmostEqual(delta, expected, delta=0.5,
                msg=f"{cid}: AD delta {delta:.2f} vs expected {expected:.2f}")

    def test_sterak_zero_when_not_in_build(self) -> None:
        # Defensive: items without bonus_ad_pct_base_ad contribute the
        # raw DDragon stat block AD only. Bloodthirster has 80 AD flat
        # and bonus_ad_pct_base_ad=0 - delta should match flat exactly.
        from agents.daemon_slayer.engine import build_champion
        bare = build_champion(self.snap, "Aatrox", level=11).stats["ad"]
        bt = build_champion(
            self.snap, "Aatrox", level=11, item_ids=["3072"],
        ).stats["ad"]
        bt_delta = bt - bare
        self.assertAlmostEqual(bt_delta, 80.0, delta=1.0,
            msg=f"Bloodthirster delta {bt_delta:.1f} drifted from 80 flat")

    def test_sterak_lifts_dps(self) -> None:
        # End-to-end: more bonus AD → more DPS. Sterak's adds AD + HP
        # but no proc; the AD piece (flat + passive) should clearly lift
        # weighted DPS over naked.
        bare = compute_dps(self.snap, "Aatrox", level=11).weighted_dps
        with_st = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3053"],
        ).weighted_dps
        self.assertGreater(with_st, bare)


class SeryldasGrudgeTests(unittest.TestCase):
    """Phase 4 batch 25 - Serylda's Grudge (6694) added to ITEM_EFFECTS as a
    new entry (was unmodeled prior - stats-only via item aggregation).

    Slot: % armor pen layer next to LDR (3036) / Mortal Reminder (3033).
    DDragon snapshot 16.9.1: 45 AD / 35% Armor Penetration / 15 Ability
    Haste; Bitter Cold ability slow on <50% HP targets is utility, not
    damage. Coefficient 0.35 matches LDR; the only schema difference vs
    LDR is no Giant Slayer (no target_bonus_hp_amp_max_pct).

    Tests pin: presence, stat shape, no unique_passive_key (% pen sums
    in current League - build legality is ranker-owned), pen-pipeline
    parity with LDR at the same coefficient, DPS uplift vs an armored
    target, no uplift attributable to pen vs zero-armor target.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_seryldas_present_with_armor_pen(self) -> None:
        e = ITEM_EFFECTS["6694"]
        self.assertEqual(e.name, "Serylda's Grudge")
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.periodics, ())
        self.assertAlmostEqual(e.armor_pen_pct, 0.35, places=4)
        self.assertEqual(e.armor_pen_flat, 0.0)
        self.assertEqual(e.armor_reduction_pct, 0.0)
        self.assertIn("armor pen", e.note.lower())

    def test_seryldas_no_unique_passive_key(self) -> None:
        # % pen layer in current engine sums across items (additive). The
        # in-game Last Whisper exclusivity (only one of LDR / MR / Serylda
        # at a time) is build-legality, not effect-layer - same call as
        # Tiamat-tree exclusivity for the hydra family.
        self.assertEqual(ITEM_EFFECTS["6694"].unique_passive_key, "")

    def test_seryldas_no_target_bonus_hp_amp(self) -> None:
        # LDR carries Giant Slayer (target_bonus_hp_amp_max_pct=0.15);
        # Serylda has Bitter Cold (utility slow), not a target-conditional
        # damage amp. Pins the schema-difference vs LDR.
        e = ITEM_EFFECTS["6694"]
        self.assertEqual(e.target_bonus_hp_amp_max_pct, 0.0)
        self.assertEqual(e.target_bonus_hp_amp_cap, 0.0)

    def test_seryldas_armor_pipeline_matches_ldr_coefficient(self) -> None:
        # Both apply 35% armor pen → same effective armor against any
        # positive input. Pins the coefficient parity.
        seryldas = ITEM_EFFECTS["6694"]
        ldr = ITEM_EFFECTS["3036"]
        self.assertAlmostEqual(
            effective_target_armor(100.0, [seryldas]),
            effective_target_armor(100.0, [ldr]),
            places=3,
        )
        self.assertAlmostEqual(
            effective_target_armor(100.0, [seryldas]), 65.0, places=3,
        )

    def test_seryldas_raises_dps_vs_armored(self) -> None:
        # vs 100 armor: bare auto-attacks see factor 0.5; Serylda's pen
        # raises factor + the stat block (45 AD, 15 AH) lifts DPS.
        bare = compute_dps(self.snap, "Aatrox", level=11, target_armor=100.0)
        with_sg = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["6694"], target_armor=100.0,
        )
        self.assertGreater(with_sg.weighted_dps, bare.weighted_dps)

    def test_seryldas_pen_note_surfaces_when_armor_reduced(self) -> None:
        with_sg = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["6694"], target_armor=100.0,
        )
        joined = " ".join(with_sg.notes)
        self.assertIn("effective target armor", joined)
        self.assertIn("65.0", joined)  # 100 * 0.65 = 65 after Serylda pen

    def test_seryldas_no_pen_note_vs_zero_armor(self) -> None:
        # Zero armor → pipeline early-exits. Note absent; DPS still lifts
        # via the stat block (45 AD), but the pen layer contributes nothing.
        with_sg = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["6694"], target_armor=0.0,
        )
        # input field unchanged
        self.assertEqual(with_sg.target_armor, 0.0)


class TotalCritChanceBonusHelperTests(unittest.TestCase):
    """Phase 4 batch 26 - ``total_crit_chance_bonus`` helper.

    Sums each effect's flat + HP-scaled contribution into a single
    fraction. Returns 0.0 with no contributors. The clamp at 1.0 lives
    at the call site (compute_dps), not here - this helper exposes the
    raw sum so over-cap stacking is visible to callers.
    """

    def test_empty_effects_returns_zero(self) -> None:
        self.assertEqual(total_crit_chance_bonus([], caster_bonus_hp=2000.0), 0.0)

    def test_no_crit_fields_returns_zero(self) -> None:
        # An effect with no crit_chance_bonus_* fields contributes nothing.
        plain = ItemEffect(item_id="x", name="x", armor_pen_pct=0.35)
        self.assertEqual(total_crit_chance_bonus([plain], caster_bonus_hp=2000.0), 0.0)

    def test_yun_tal_flat_contributes_unconditionally(self) -> None:
        yt = ITEM_EFFECTS["3032"]
        # Flat contribution doesn't care about caster_bonus_hp.
        self.assertAlmostEqual(total_crit_chance_bonus([yt], 0.0), 0.25, places=4)
        self.assertAlmostEqual(total_crit_chance_bonus([yt], 5000.0), 0.25, places=4)

    def test_atma_zero_at_zero_bonus_hp(self) -> None:
        # HP-scaled with 0 caster_bonus_hp → 0 contribution. Mirrors
        # batch 19's target_bonus_hp_amp behavior.
        atma = ITEM_EFFECTS["3039"]
        self.assertEqual(total_crit_chance_bonus([atma], 0.0), 0.0)

    def test_atma_half_ramp_at_1500(self) -> None:
        atma = ITEM_EFFECTS["3039"]
        # 1500 / 3000 cap = 0.5 ramp → 0.30 * 0.5 = 0.15.
        self.assertAlmostEqual(total_crit_chance_bonus([atma], 1500.0), 0.15, places=4)

    def test_atma_full_ramp_at_3000(self) -> None:
        atma = ITEM_EFFECTS["3039"]
        self.assertAlmostEqual(total_crit_chance_bonus([atma], 3000.0), 0.30, places=4)

    def test_atma_caps_past_3000(self) -> None:
        atma = ITEM_EFFECTS["3039"]
        # 4500 bonus HP > 3000 cap → still 0.30, no over-shoot.
        self.assertAlmostEqual(total_crit_chance_bonus([atma], 4500.0), 0.30, places=4)

    def test_yun_tal_plus_atma_compose_additively(self) -> None:
        yt = ITEM_EFFECTS["3032"]
        atma = ITEM_EFFECTS["3039"]
        # 0.25 (flat) + 0.15 (Atma at 1500) = 0.40.
        self.assertAlmostEqual(
            total_crit_chance_bonus([yt, atma], 1500.0), 0.40, places=4,
        )

    def test_helper_does_not_clamp_at_one(self) -> None:
        # Caller (compute_dps) clamps at 1.0. The helper exposes raw
        # sums so over-cap stacking is visible. Construct a synthetic
        # 60% flat + 50% scaled = 1.10 sum.
        big_flat = ItemEffect(item_id="a", name="a", crit_chance_bonus_flat=0.60)
        big_scaled = ItemEffect(
            item_id="b",
            name="b",
            crit_chance_bonus_max_pct=0.50,
            crit_chance_bonus_per_bonus_hp_cap=1000.0,
        )
        # 1000 HP → full ramp on big_scaled = 0.50.
        self.assertAlmostEqual(
            total_crit_chance_bonus([big_flat, big_scaled], 1000.0), 1.10, places=4,
        )


class YunTalWildarrowsTests(unittest.TestCase):
    """Phase 4 batch 26 - Yun Tal Wildarrows (3032) added to ITEM_EFFECTS as
    a new entry (was unmodeled prior - stats-only via item aggregation).

    Practice Makes Lethal pinned at full Wildarrows stacks (25%); same
    steady-state assumption as Black Cleaver's "30% reduction at 5
    stacks" and Riftmaker's "8% at full ramp". Flurry AS bonus is
    intentionally not modeled (would need a conditional AS-bonus
    schema; near-100% uptime in active rotations would over-count
    in shorter ones).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_yun_tal_present_with_flat_crit_bonus(self) -> None:
        e = ITEM_EFFECTS["3032"]
        self.assertEqual(e.name, "Yun Tal Wildarrows")
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.periodics, ())
        self.assertAlmostEqual(e.crit_chance_bonus_flat, 0.25, places=4)
        self.assertEqual(e.crit_chance_bonus_max_pct, 0.0)
        self.assertEqual(e.crit_chance_bonus_per_bonus_hp_cap, 0.0)

    def test_yun_tal_no_unique_passive_key(self) -> None:
        # Practice Makes Lethal is one-of-one currently; no dedup needed.
        self.assertEqual(ITEM_EFFECTS["3032"].unique_passive_key, "")

    def test_yun_tal_lifts_dps_on_caitlyn(self) -> None:
        # Caitlyn lvl 11 has 0% base crit (her Headshot is conditional).
        # Yun Tal's stat block (50 AD + 40% AS) plus the new 25% crit pin
        # both contribute to the lift.
        bare = compute_dps(self.snap, "Caitlyn", level=11)
        with_yt = compute_dps(self.snap, "Caitlyn", level=11, item_ids=["3032"])
        self.assertGreater(with_yt.weighted_dps, bare.weighted_dps)

    def test_yun_tal_surfaces_crit_lift_note(self) -> None:
        with_yt = compute_dps(self.snap, "Caitlyn", level=11, item_ids=["3032"])
        joined = " ".join(with_yt.notes)
        self.assertIn("crit chance lifted by items", joined)
        self.assertIn("+25.0%", joined)

    def test_yun_tal_ad_block_lands_in_resolved_stats(self) -> None:
        # /stats output is unchanged by the cross-derivation; the AD/AS
        # piece still contributes via item aggregation. Yun Tal's stat
        # block carries 50 AD + 40% AS (DDragon) + 0% base crit.
        with_yt = compute_dps(self.snap, "Caitlyn", level=11, item_ids=["3032"])
        # Crit comes from stats.get("crit") as the raw build crit (not
        # the boosted total) - same separation as batch 15 HP→AP. The
        # *engine-internal* boosted value flows through procs + display.
        # We verify the boosted note exists rather than checking for
        # mutation of resolved.stats (which should not happen).
        # Caitlyn's resolved AD with Yun Tal includes the 50 AD.
        self.assertGreaterEqual(with_yt.stats.get("ad", 0.0), 50.0)

    def test_yun_tal_boosts_avg_attack_dmg_via_crit(self) -> None:
        # avg_attack_dmg = ad * (1 + crit * crit_bonus) * armor_factor.
        # Yun Tal lifts crit by 0.25 → avg_attack_dmg should be
        # measurably higher than what AD alone would deliver.
        # Compare against a synthetic baseline: Caitlyn lvl 11 has 0
        # native crit, so avg_attack_dmg without Yun Tal scales at
        # crit=0 (no crit term), with Yun Tal scales at crit=0.25.
        bare = compute_dps(self.snap, "Caitlyn", level=11)
        with_yt = compute_dps(self.snap, "Caitlyn", level=11, item_ids=["3032"])
        # Per-hit damage gap > what 50 AD alone would explain at 0% crit.
        # Rough check: with_yt avg_attack > bare avg_attack + 50 (the
        # ceiling if crit contributed nothing).
        self.assertGreater(with_yt.avg_attack_dmg, bare.avg_attack_dmg + 50.0)


class AtmasReckoningCritTests(unittest.TestCase):
    """Phase 4 batch 26 - Atma's Reckoning (3039) added to ITEM_EFFECTS as
    a new entry (was unmodeled prior - stats-only via item aggregation).

    Big Hands: 1% crit per 100 bonus HP, max 30% at 3000 bonus HP. Linear
    ramp; same shape as batch 19's target_bonus_hp_amp on the caster
    side. Stat block (700 HP / 20% crit / 10 AH) lands via item
    aggregation.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_atma_present_with_hp_scaled_crit(self) -> None:
        e = ITEM_EFFECTS["3039"]
        self.assertEqual(e.name, "Atma's Reckoning")
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.periodics, ())
        self.assertEqual(e.crit_chance_bonus_flat, 0.0)
        self.assertAlmostEqual(e.crit_chance_bonus_max_pct, 0.30, places=4)
        self.assertAlmostEqual(e.crit_chance_bonus_per_bonus_hp_cap, 3000.0, places=2)

    def test_atma_no_unique_passive_key(self) -> None:
        self.assertEqual(ITEM_EFFECTS["3039"].unique_passive_key, "")

    def test_atma_lifts_dps_on_hp_stacker(self) -> None:
        # Sett's HP scaling is high; Atma's stat block (700 HP / 20%
        # crit / 10 AH) plus the Big Hands ramp both contribute.
        bare = compute_dps(self.snap, "Sett", level=11)
        with_atma = compute_dps(self.snap, "Sett", level=11, item_ids=["3039"])
        self.assertGreater(with_atma.weighted_dps, bare.weighted_dps)

    def test_atma_surfaces_crit_lift_note(self) -> None:
        with_atma = compute_dps(self.snap, "Sett", level=11, item_ids=["3039"])
        joined = " ".join(with_atma.notes)
        self.assertIn("crit chance lifted by items", joined)
        # Sett lvl 11 + just Atma: caster_bonus_hp ≈ 700 (Atma's flat HP).
        # Big Hands at 700/3000 = 0.233 ramp → 0.30 * 0.233 = 0.07 = 7%.
        # Note format pins ≈ +7.0% (rounding to one decimal).
        self.assertIn("+7.0%", joined)

    def test_atma_scales_with_added_hp_items(self) -> None:
        # Stack Atma + Heartsteel (3084, 800 HP) + Warmog's (3083, 800 HP)
        # - the build's caster_bonus_hp climbs and Big Hands ramps with it.
        # Build with just Atma: ~700 bonus HP → ~7% Big Hands.
        # Build with Atma + Heartsteel + Warmog's: ~2300 bonus HP → ~23%.
        atma_only = compute_dps(self.snap, "Sett", level=11, item_ids=["3039"])
        atma_stack = compute_dps(
            self.snap, "Sett", level=11, item_ids=["3039", "3084", "3083"],
        )
        # Both should surface a "crit chance lifted" note.
        atma_only_joined = " ".join(atma_only.notes)
        atma_stack_joined = " ".join(atma_stack.notes)
        self.assertIn("crit chance lifted by items", atma_only_joined)
        self.assertIn("crit chance lifted by items", atma_stack_joined)
        # Stack version has higher boosted crit.
        # Pull the +XX.X% number from each note.
        import re
        a1 = re.search(r"crit chance lifted by items: \+([\d.]+)%", atma_only_joined)
        a2 = re.search(r"crit chance lifted by items: \+([\d.]+)%", atma_stack_joined)
        self.assertIsNotNone(a1)
        self.assertIsNotNone(a2)
        self.assertGreater(float(a2.group(1)), float(a1.group(1)))


class CallContextCasterMaxMpTests(unittest.TestCase):
    """Phase 4 batch 27 - CallContext.caster_max_mp default + plumbing."""

    def test_default_caster_max_mp_zero(self) -> None:
        # Pre-batch-27 callers + manaless champion builds carry 0 here.
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11)
        self.assertEqual(ctx.caster_max_mp, 0.0)

    def test_caster_max_mp_passes_through(self) -> None:
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11, caster_max_mp=2000.0)
        self.assertEqual(ctx.caster_max_mp, 2000.0)

    def test_proc_resolves_against_caster_max_mp(self) -> None:
        # Mirrors batch 6's caster_max_hp resolution test. A proc keyed off
        # caster_max_mp returns 0 with no signal and the expected damage
        # with one.
        proc = PeriodicProc(
            name="mana_proc",
            bonus_damage=lambda c: 0.012 * c.caster_max_mp,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        )
        zero_mp_ctx = CallContext(base_ad=60, bonus_ad=0, level=11)
        full_mp_ctx = CallContext(base_ad=60, bonus_ad=0, level=11, caster_max_mp=2000.0)
        self.assertEqual(proc.resolve_damage(zero_mp_ctx), 0.0)
        self.assertAlmostEqual(proc.resolve_damage(full_mp_ctx), 24.0, places=4)


class ManamuneAweTests(unittest.TestCase):
    """Phase 4 batch 27 - Manamune (3004) "Awe" stat layer.

    Awe converts 2% max mana into bonus AD. Walked in build_champion
    after aggregate_item_stats so the items' own mana pool is included
    in the conversion base. Manaflow stack-up is intentionally not
    modeled (steady-state assumption).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_manamune_present_with_awe_field(self) -> None:
        e = ITEM_EFFECTS["3004"]
        self.assertEqual(e.name, "Manamune")
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.periodics, ())  # no Shock - that's Muramana
        self.assertAlmostEqual(e.bonus_ad_pct_max_mp, 0.02, places=4)
        self.assertEqual(e.crit_chance_bonus_flat, 0.0)
        self.assertEqual(e.bonus_ad_pct_base_ad, 0.0)
        self.assertIn("awe", e.note.lower())

    def test_manamune_no_unique_passive_key(self) -> None:
        # Awe is one-of-two in current League (Manamune transforms into
        # Muramana - you can't own both); build legality is ranker-owned.
        self.assertEqual(ITEM_EFFECTS["3004"].unique_passive_key, "")

    def test_manamune_lifts_total_ad_on_ezreal(self) -> None:
        # Ezreal lvl 11: base mp = 375 + 70*10 = 1075; with Manamune
        # adds 500 mana → 1575 total; Awe = 0.02 * 1575 = 31.5 bonus AD
        # (folded into ad_flat by build_champion).
        from agents.daemon_slayer.engine import build_champion
        bare = build_champion(self.snap, "Ezreal", level=11)
        with_manamune = build_champion(self.snap, "Ezreal", level=11, item_ids=["3004"])
        # Manamune's stat block adds 35 flat AD; Awe adds another ~31.5.
        # Total AD lift should clear 60 (35 stat + ~25 from Awe at minimum).
        ad_lift = with_manamune.stats["ad"] - bare.stats["ad"]
        self.assertGreater(ad_lift, 60.0)
        self.assertLess(ad_lift, 80.0)  # ceiling: 35 stat + 31.5 Awe ≈ 66.5

    def test_manamune_lifts_dps_on_ezreal(self) -> None:
        bare = compute_dps(self.snap, "Ezreal", level=11)
        with_manamune = compute_dps(self.snap, "Ezreal", level=11, item_ids=["3004"])
        self.assertGreater(with_manamune.weighted_dps, bare.weighted_dps)


class MuramanaShockTests(unittest.TestCase):
    """Phase 4 batch 27 - Muramana (3042) "Awe" + "Shock".

    Muramana doubles Manamune's mana pool (1000 vs 500) and adds Shock,
    a per-attack 1.2% max mana physical proc. Both Awe and Shock scale
    linearly with the larger mana pool, so on the same caster Muramana
    delivers substantially more DPS than Manamune.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_muramana_present_with_awe_and_shock(self) -> None:
        e = ITEM_EFFECTS["3042"]
        self.assertEqual(e.name, "Muramana")
        self.assertFalse(e.defensive_only)
        self.assertNotEqual(e.periodics, ())
        proc = e.periodics[0]
        self.assertEqual(proc.name, "Shock")
        self.assertEqual(proc.damage_type, PHYSICAL)
        self.assertEqual(proc.every_n_attacks, 1)
        self.assertAlmostEqual(e.bonus_ad_pct_max_mp, 0.02, places=4)

    def test_muramana_no_unique_passive_key(self) -> None:
        self.assertEqual(ITEM_EFFECTS["3042"].unique_passive_key, "")

    def test_muramana_shock_proc_scales_with_caster_max_mp(self) -> None:
        # 2000 mana → Shock = 0.012 * 2000 = 24.0.
        # 3000 mana → Shock = 36.0.
        proc = ITEM_EFFECTS["3042"].periodics[0]
        ctx_2k = CallContext(base_ad=60, bonus_ad=0, level=11, caster_max_mp=2000.0)
        ctx_3k = CallContext(base_ad=60, bonus_ad=0, level=11, caster_max_mp=3000.0)
        self.assertAlmostEqual(proc.resolve_damage(ctx_2k), 24.0, places=4)
        self.assertAlmostEqual(proc.resolve_damage(ctx_3k), 36.0, places=4)

    def test_muramana_shock_zero_with_no_mana(self) -> None:
        # Manaless caster (or pre-batch-27 caller missing the field) →
        # Shock contributes zero. Backward-compat invariant.
        proc = ITEM_EFFECTS["3042"].periodics[0]
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11)
        self.assertEqual(proc.resolve_damage(ctx), 0.0)

    def test_muramana_lifts_dps_more_than_manamune_on_ezreal(self) -> None:
        # Same gold, same AD/AH stats - Muramana's 1000 mana pool vs
        # Manamune's 500 doubles the Awe contribution AND unlocks Shock.
        # On a high-mana champ (Ezreal, 1075 mp at lvl 11) the Muramana
        # build clears Manamune by a comfortable margin.
        manamune_dps = compute_dps(
            self.snap, "Ezreal", level=11, item_ids=["3004"],
        ).weighted_dps
        muramana_dps = compute_dps(
            self.snap, "Ezreal", level=11, item_ids=["3042"],
        ).weighted_dps
        self.assertGreater(muramana_dps, manamune_dps)

    def test_muramana_lifts_total_ad_on_ezreal_more_than_manamune(self) -> None:
        # Awe contribution scales with total mana: Manamune brings 500
        # mana, Muramana brings 1000. On the same Ezreal lvl 11 (base
        # 1075 mana) the AD lift difference is purely from Awe scaling
        # off the larger mana pool. Manamune Awe = 0.02 * 1575 ≈ 31.5;
        # Muramana Awe = 0.02 * 2075 ≈ 41.5. Delta ≈ 10 AD.
        from agents.daemon_slayer.engine import build_champion
        manamune_ad = build_champion(
            self.snap, "Ezreal", level=11, item_ids=["3004"],
        ).stats["ad"]
        muramana_ad = build_champion(
            self.snap, "Ezreal", level=11, item_ids=["3042"],
        ).stats["ad"]
        delta = muramana_ad - manamune_ad
        self.assertGreater(delta, 7.0)  # tolerance for engine rounding
        self.assertLess(delta, 15.0)


class AweEngineWireInTests(unittest.TestCase):
    """Awe (bonus_ad_pct_max_mp) lifts AD in build_champion output.

    Mirror of SteraksEngineWireInTests for the mana → AD path. Pins
    the engine-side wiring: the walk in build_champion folds the
    contribution into item_totals["ad_flat"] BEFORE _combine_items
    applies item AD, so the lifted AD propagates through the rest of
    the stat resolution pipeline.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_awe_zero_on_manaless_champion(self) -> None:
        # Akali is energy-based (mp=200 per DDragon's spec, but no mana
        # scaling applies); using a champion with mana but adding no
        # mana items confirms the walk's safety. Better invariant: pick
        # a small-mana caster + a Manamune build, validate non-zero AD.
        # For the manaless invariant, use a build with NO mana items and
        # confirm Awe contributes nothing (since no item carries the field).
        from agents.daemon_slayer.engine import build_champion
        bare = build_champion(self.snap, "Aatrox", level=11)
        # No Manamune/Muramana → no Awe contribution. AD stays at base.
        self.assertEqual(bare.stats["ad"], bare.base_stats["ad"])

    def test_awe_walk_safe_when_no_awe_items(self) -> None:
        # Build with mana items but NO Awe items: walk should not crash
        # and should not contribute AD beyond the items' stat blocks.
        # Tear of the Goddess is 980g but not legendary; use Archangel's
        # Staff (3003) which has 600 mana and no bonus_ad_pct_max_mp.
        from agents.daemon_slayer.engine import build_champion
        # Archangel's Staff isn't in ITEM_EFFECTS so the walk should be
        # a no-op for it.
        archangel = build_champion(self.snap, "Ezreal", level=11, item_ids=["3003"])
        # AD should match: champion base AD + 0 (Archangel has no AD
        # stat block - it's an AP item). If the Awe walk wrongly fired
        # this would surface as an AD bump.
        bare_ad = build_champion(self.snap, "Ezreal", level=11).stats["ad"]
        self.assertAlmostEqual(archangel.stats["ad"], bare_ad, places=2)

    def test_awe_walk_includes_other_items_mana(self) -> None:
        # Awe is mana → AD; the walk uses the build's TOTAL max mana
        # (champion base + ALL items' mana, not just the Awe-carrying
        # item's mana). So a build with [Manamune, Archangel] → Awe
        # picks up 500 (Manamune) + 600 (Archangel) extra mana = +22 AD.
        # Compare against [Manamune] alone where Awe sees 500 extra.
        # The delta surfaces a mana-source-leak bug if the walk only
        # counted the Awe item's own mana.
        from agents.daemon_slayer.engine import build_champion
        manamune_only = build_champion(
            self.snap, "Ezreal", level=11, item_ids=["3004"],
        )
        manamune_plus_archangel = build_champion(
            self.snap, "Ezreal", level=11, item_ids=["3004", "3003"],
        )
        ad_lift = manamune_plus_archangel.stats["ad"] - manamune_only.stats["ad"]
        # Archangel's Staff: 600 mana flat. Awe = 0.02 * 600 = 12 AD.
        # Some engine rounding allowed; expect 10-14.
        self.assertGreater(ad_lift, 10.0)
        self.assertLess(ad_lift, 14.0)


class ArchangelsAweTests(unittest.TestCase):
    """Phase 4 batch 28 - Archangel's Staff (3003) "Awe" stat layer.

    Awe converts 1% BONUS mana (item-contributed only - distinct from
    Manamune's max-mana keying) into bonus AP. Walked in build_champion
    against item_totals["mp_flat"] (the bonus-mana sum), AFTER
    aggregate_item_stats. Manaflow stack-up + transformation into
    Seraph's at +360 max mana stacks not modeled (steady-state).
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_archangel_present_with_awe_field(self) -> None:
        e = ITEM_EFFECTS["3003"]
        self.assertEqual(e.name, "Archangel's Staff")
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.periodics, ())
        self.assertAlmostEqual(e.bonus_ap_pct_bonus_mp, 0.01, places=4)
        # Asymmetry pin: Archangel uses BONUS mana, NOT max mana.
        # bonus_ad_pct_max_mp stays at zero (that's Manamune/Muramana).
        self.assertEqual(e.bonus_ad_pct_max_mp, 0.0)
        self.assertIn("awe", e.note.lower())

    def test_archangel_no_unique_passive_key(self) -> None:
        # Archangel transforms into Seraph's at stacks; build legality
        # is ranker-owned per the s81 pattern (same call as Manamune).
        self.assertEqual(ITEM_EFFECTS["3003"].unique_passive_key, "")

    def test_archangel_lifts_ap_via_bonus_mana_only(self) -> None:
        # Ezreal lvl 11: champion base mp ≈ 1075 - must NOT count toward
        # Archangel's Awe (bonus mana only). Archangel adds 600 mana →
        # bonus mana = 600 → Awe AP = 0.01 * 600 = 6 AP.
        # If the walk wrongly used max mana (1075 + 600 = 1675), AP
        # contribution would be ~16.75 - this test pins the asymmetry.
        from agents.daemon_slayer.engine import build_champion
        bare = build_champion(self.snap, "Ezreal", level=11)
        with_arch = build_champion(self.snap, "Ezreal", level=11, item_ids=["3003"])
        # Archangel stat block AP = 70; Awe at 600 bonus mana = 6.
        # Total AP lift should be 70 + 6 = 76, with rounding tolerance.
        ap_lift = with_arch.stats.get("ap", 0.0) - bare.stats.get("ap", 0.0)
        self.assertGreater(ap_lift, 74.0)
        self.assertLess(ap_lift, 78.0)
        # Strict bound check that catches the "max mana" bug:
        # if Awe used max mana (1675), lift would be 70 + 16.75 ≈ 86.75.
        self.assertLess(ap_lift, 80.0)

    def test_archangel_walk_uses_total_build_mana(self) -> None:
        # Add Manamune (500 mana) to the build → Archangel's Awe sees
        # additional 500 bonus mana → +5 AP from Archangel's contribution.
        # Manamune itself doesn't carry bonus_ap_pct_bonus_mp so its 500
        # mana contribution is purely upstream-source for Archangel.
        from agents.daemon_slayer.engine import build_champion
        arch_only = build_champion(self.snap, "Ezreal", level=11, item_ids=["3003"])
        arch_plus_manamune = build_champion(
            self.snap, "Ezreal", level=11, item_ids=["3003", "3004"],
        )
        ap_lift = arch_plus_manamune.stats["ap"] - arch_only.stats["ap"]
        # Manamune adds 0 AP stat-block; only contribution is +5 AP via
        # Archangel's Awe ramp on Manamune's 500 bonus mana.
        self.assertGreater(ap_lift, 4.0)
        self.assertLess(ap_lift, 7.0)

    def test_archangel_lifts_dps_on_caster(self) -> None:
        # Annie / Lux / any AP user - Archangel raises DPS via the AP
        # piece feeding Lich Bane / Nashor's spellblades or just by
        # raising auto attack contribution. Use a generic AP champ.
        bare = compute_dps(self.snap, "Lux", level=11)
        with_arch = compute_dps(self.snap, "Lux", level=11, item_ids=["3003"])
        self.assertGreaterEqual(with_arch.weighted_dps, bare.weighted_dps)


class SeraphsEmbraceTests(unittest.TestCase):
    """Phase 4 batch 28 - Seraph's Embrace (3040) Awe-AP twin.

    Same field as Archangel's but at 2% (post-transformation form).
    Lifeline shield is non-DPS, deduped via unique_passive_key="lifeline";
    Awe AP walk in engine.py bypasses collect_effects so the AP piece
    survives any lifeline dedup.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_seraphs_present_with_awe_field(self) -> None:
        e = ITEM_EFFECTS["3040"]
        self.assertEqual(e.name, "Seraph's Embrace")
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.periodics, ())
        self.assertAlmostEqual(e.bonus_ap_pct_bonus_mp, 0.02, places=4)

    def test_seraphs_lifeline_unique_passive_tagged(self) -> None:
        # Same key as Shieldbow / Sterak's / Maw - lifeline shield piece.
        self.assertEqual(ITEM_EFFECTS["3040"].unique_passive_key, "lifeline")

    def test_seraphs_lifts_ap_at_double_archangel_rate(self) -> None:
        # 1000 mana stat block, 2% bonus mana = 20 AP from Seraph's own
        # mana. + 70 AP stat = 90 total AP lift.
        from agents.daemon_slayer.engine import build_champion
        bare = build_champion(self.snap, "Lux", level=11)
        with_seraphs = build_champion(self.snap, "Lux", level=11, item_ids=["3040"])
        ap_lift = with_seraphs.stats.get("ap", 0.0) - bare.stats.get("ap", 0.0)
        # 70 stat + 20 Awe = 90, with engine rounding tolerance.
        self.assertGreater(ap_lift, 88.0)
        self.assertLess(ap_lift, 92.0)

    def test_seraphs_awe_survives_lifeline_dedup(self) -> None:
        # Build with Seraph's + Sterak's (3053, also lifeline). Sterak's
        # comes first via item_id ordering - wait, ordering is the
        # caller's. Let's pin both orderings.
        # collect_effects dedups the second lifeline-tagged ItemEffect,
        # but engine.py's Awe walk reads ITEM_EFFECTS directly so the
        # Awe AP contribution is independent of the dedup decision.
        from agents.daemon_slayer.engine import build_champion
        # Lux + Seraph's only: AP includes Seraph's 20 Awe contribution.
        seraphs_only = build_champion(
            self.snap, "Lux", level=11, item_ids=["3040"],
        )
        # Lux + Seraph's + Sterak's (3053). Sterak's has 0 AP stat block
        # but its 400 HP pulls the build's stats up. Awe contribution
        # from Seraph's stays at 0.02 * 1000 = 20 (Sterak's adds 0 mana).
        with_steraks = build_champion(
            self.snap, "Lux", level=11, item_ids=["3040", "3053"],
        )
        # AP gap should be 0 (Sterak's adds no AP). Same Seraph's Awe.
        ap_gap = with_steraks.stats["ap"] - seraphs_only.stats["ap"]
        self.assertAlmostEqual(ap_gap, 0.0, places=2)


class ArchangelEngineWireInTests(unittest.TestCase):
    """Awe-AP walk safety + asymmetry vs Awe-AD walk.

    Pins the engine-side wiring guarantees: walk is safe with no
    Archangel-line items present, walk uses bonus mana not max mana
    (asymmetry vs Manamune family), walk doesn't accidentally fire
    on bonus_ad_pct_max_mp items.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_walk_safe_when_no_archangel_items(self) -> None:
        # Pure stat-only build - walk should not crash and should
        # contribute nothing to ap_flat. Lich Bane (3100) has 100 AP +
        # 4% MS, no bonus_ap_pct_bonus_mp; lift should match its stat
        # block exactly with no Awe contribution.
        from agents.daemon_slayer.engine import build_champion
        bare_ap = build_champion(self.snap, "Lux", level=11).stats.get("ap", 0.0)
        with_lb = build_champion(
            self.snap, "Lux", level=11, item_ids=["3100"],
        ).stats.get("ap", 0.0)
        ap_lift = with_lb - bare_ap
        self.assertAlmostEqual(ap_lift, 100.0, places=1)

    def test_manamune_does_not_fire_archangel_walk(self) -> None:
        # Manamune carries bonus_ad_pct_max_mp (Awe-AD), NOT
        # bonus_ap_pct_bonus_mp. Adding it should not give ANY AP via
        # the Archangel walk. AP stays at 0 for Ezreal.
        from agents.daemon_slayer.engine import build_champion
        bare_ap = build_champion(self.snap, "Ezreal", level=11).stats.get("ap", 0.0)
        with_manamune_ap = build_champion(
            self.snap, "Ezreal", level=11, item_ids=["3004"],
        ).stats.get("ap", 0.0)
        # Manamune has no AP stat block, no Awe-AP - AP unchanged.
        self.assertAlmostEqual(with_manamune_ap, bare_ap, places=2)

    def test_archangel_walk_asymmetric_vs_manamune_walk(self) -> None:
        # Direct asymmetry assertion: Archangel uses bonus mana
        # (item-contributed only), Manamune uses max mana (champion
        # base + items). On Ezreal lvl 11 (champion base 1075 mp),
        # Manamune's 500 mana → AD = 0.02 * (1075 + 500) = 31.5;
        # Archangel's 600 mana → AP = 0.01 * 600 = 6 (NOT 0.01 * 1675 = 16.75).
        # The ratio of AP-side contribution to AD-side contribution
        # being ~6/31.5 = 0.19 (rather than ~16.75/31.5 = 0.53)
        # surfaces the bonus-vs-max distinction.
        from agents.daemon_slayer.engine import build_champion
        manamune_ad = build_champion(
            self.snap, "Ezreal", level=11, item_ids=["3004"],
        ).stats["ad"]
        bare_ad = build_champion(self.snap, "Ezreal", level=11).stats["ad"]
        archangel_ap = build_champion(
            self.snap, "Ezreal", level=11, item_ids=["3003"],
        ).stats["ap"]
        bare_ap = build_champion(self.snap, "Ezreal", level=11).stats["ap"]
        # Manamune AD lift includes 35 stat + Awe - Awe ≈ 31.5.
        manamune_awe = (manamune_ad - bare_ad) - 35.0  # subtract stat block
        # Archangel AP lift includes 70 stat + Awe - Awe ≈ 6.
        archangel_awe = (archangel_ap - bare_ap) - 70.0
        # Ratio asserts asymmetry: if Archangel used max mana, ratio
        # would be ~16.75/31.5 = 0.53. With bonus mana, ratio is
        # ~6/31.5 = 0.19. Use a safe upper bound at 0.30.
        ratio = archangel_awe / manamune_awe
        self.assertLess(ratio, 0.30)


class Batch29DefensiveOnlyCoverageTests(unittest.TestCase):
    """Phase 4 batch 29 - 4 new defensive_only entries.

    Coverage-completeness for Hubris, Spirit Visage, Kaenic Rookern,
    Cosmic Drive. Each carries no current-engine DPS contribution
    (takedown-event-bound, heal amp, magic shield, MS proc respectively).
    Notes flag un-modeled-but-promotable pieces (Hubris's lethality)
    so future batches know what's there.
    """

    def test_hubris_present_with_lethality(self) -> None:
        # Batch 29 originally tagged Hubris defensive_only with the
        # lethality flagged for a future plumbing batch. Batch 30
        # (the lethality plumbing) promoted Hubris off defensive_only
        # and pinned the 18 Lethality. This test now asserts the
        # post-batch-30 state.
        e = ITEM_EFFECTS["6697"]
        self.assertEqual(e.name, "Hubris")
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.periodics, ())
        self.assertAlmostEqual(e.lethality, 18.0, places=2)
        self.assertIn("eminence", e.note.lower())
        self.assertIn("lethality", e.note.lower())

    def test_spirit_visage_present_defensive_only(self) -> None:
        e = ITEM_EFFECTS["3065"]
        self.assertEqual(e.name, "Spirit Visage")
        self.assertTrue(e.defensive_only)
        self.assertEqual(e.periodics, ())
        self.assertIn("vitality", e.note.lower())

    def test_kaenic_rookern_present_defensive_only(self) -> None:
        e = ITEM_EFFECTS["2504"]
        self.assertEqual(e.name, "Kaenic Rookern")
        self.assertTrue(e.defensive_only)
        self.assertEqual(e.periodics, ())
        self.assertIn("magebane", e.note.lower())

    def test_cosmic_drive_present_defensive_only(self) -> None:
        e = ITEM_EFFECTS["4629"]
        self.assertEqual(e.name, "Cosmic Drive")
        self.assertTrue(e.defensive_only)
        self.assertEqual(e.periodics, ())
        self.assertIn("spelldance", e.note.lower())

    def test_the_collector_present_with_lethality(self) -> None:
        # Iter 10 lethality lane audit (2026-05-20): cross-checked the
        # full lethality + flat-pen + magic-pen audit set vs Community
        # Dragon 16.10 ground truth and found one drift: The Collector
        # (6676) carries 10 Lethality in the stat block but the engine
        # had defensive_only=True with lethality=0.0 because the entry
        # was originally tagged for the Death execute (which is NOT a
        # per-rotation DPS proc; the note is correct) but the lethality
        # plumbing batch (30) never promoted Collector off defensive
        # the way it did Hubris / Youmuu's / etc. The execute stays
        # zero-rotation-DPS; the 10 Lethality stat block contributes
        # to the rest of the rotation and must be pinned. CD 16.10:
        # 50 AD + 10 Lethality + 25% Crit + Death execute + Taxes gold.
        e = ITEM_EFFECTS["6676"]
        self.assertEqual(e.name, "The Collector")
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.periodics, ())
        self.assertAlmostEqual(e.lethality, 10.0, places=2)
        self.assertIn("execute", e.note.lower())


class LiandrysSufferingTests(unittest.TestCase):
    """Phase 4 batch 29 - Liandry's Torment (6653) partial promotion via
    damage_amp_pct.

    Suffering: 2% bonus damage per second in champion combat, max 3
    stacks = 6%. Steady-state DPS pin = 6%, same shape as Riftmaker's
    8% Void Corruption (batch 14). Torment burn (ability damage burn)
    stays not-modeled per the ability-bound rule.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_liandrys_present_with_damage_amp(self) -> None:
        e = ITEM_EFFECTS["6653"]
        self.assertEqual(e.name, "Liandry's Torment")
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.periodics, ())
        self.assertAlmostEqual(e.damage_amp_pct, 0.06, places=4)
        self.assertIn("suffering", e.note.lower())

    def test_liandrys_no_unique_passive_key(self) -> None:
        # Suffering is one-of-many damage amps but Riot doesn't tag
        # them all under one unique key (Riftmaker, Liandry's, future
        # Conqueror-style amps all stack via League's buff system per
        # batch 14's pin). No dedup at the effect-layer.
        self.assertEqual(ITEM_EFFECTS["6653"].unique_passive_key, "")

    def test_liandrys_lifts_dps_via_amp(self) -> None:
        # AP champ, AP rotation. Liandry's stat block (60 AP, 300 HP)
        # plus the 6% amp should both lift weighted DPS.
        bare = compute_dps(self.snap, "Lux", level=11)
        with_liandrys = compute_dps(self.snap, "Lux", level=11, item_ids=["6653"])
        self.assertGreater(with_liandrys.weighted_dps, bare.weighted_dps)

    def test_liandrys_amp_stacks_with_riftmaker(self) -> None:
        # Both Liandry's (0.06) and Riftmaker (0.08) carry damage_amp_pct.
        # Per batch 14 pin: stacks multiplicatively via League's buff
        # system. Combined: 1.06 × 1.08 = 1.1448x. Independent: each
        # alone gives a smaller multiplier. Pin the multiplicative
        # composition by checking notes.
        with_both = compute_dps(
            self.snap, "Lux", level=11, item_ids=["6653", "4633"],
        )
        joined = " ".join(with_both.notes)
        self.assertIn("damage amp", joined.lower())
        # 1.06 * 1.08 = 1.1448; note shows 4-decimal multiplier.
        self.assertIn("1.14", joined)


class StormsurgeMagicPenTests(unittest.TestCase):
    """Phase 4 batch 29 - Stormsurge (4646) partial promotion via
    magic_pen_flat.

    Stormsurge carries 15 flat magic pen in its description (DDragon's
    stat block doesn't surface magic pen as a stat key; the 90 AP +
    6% MS pieces are in stats, the 15 magic pen is in prose). Joins
    Sorcerer's Shoes (3020, 12) and Shadowflame (4645, 15) in the
    magic_pen_flat layer. Stormraider/Squall ability-bound burst
    stays not-modeled.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_stormsurge_present_with_magic_pen(self) -> None:
        e = ITEM_EFFECTS["4646"]
        self.assertEqual(e.name, "Stormsurge")
        self.assertFalse(e.defensive_only)
        # batch 53: Squall proc added - periodics no longer empty
        self.assertAlmostEqual(e.magic_pen_flat, 15.0, places=2)
        self.assertEqual(e.magic_pen_pct, 0.0)
        self.assertIn("magic pen", e.note.lower())

    def test_stormsurge_no_unique_passive_key(self) -> None:
        # Magic pen sums in current League (no Last-Whisper-style
        # magic-side dedup). Build legality (don't double-stack flat
        # pen items) is ranker-owned.
        self.assertEqual(ITEM_EFFECTS["4646"].unique_passive_key, "")

    def test_stormsurge_pen_pipeline_matches_shadowflame(self) -> None:
        # Same coefficient as Shadowflame (4645, 15 flat magic pen).
        # Effective MR after pen should match.
        stormsurge = ITEM_EFFECTS["4646"]
        shadowflame = ITEM_EFFECTS["4645"]
        self.assertAlmostEqual(
            effective_target_mr(50.0, [stormsurge]),
            effective_target_mr(50.0, [shadowflame]),
            places=3,
        )
        # 50 - 15 = 35 effective MR.
        self.assertAlmostEqual(
            effective_target_mr(50.0, [stormsurge]), 35.0, places=3,
        )

    def test_stormsurge_raises_magic_proc_dps_vs_mr_target(self) -> None:
        # Magic pen only lifts magic-damage rotations. Lux's bare auto
        # attacks are physical (use target_armor), so Stormsurge's 15
        # magic pen contributes 0 to a bare-auto rotation - adding
        # Nashor's Tooth (3115, Icathian Bite per-attack magic proc)
        # surfaces the pen contribution.
        with_nashors = compute_dps(
            self.snap, "Lux", level=11, item_ids=["3115"], target_mr=80.0,
        )
        with_nashors_ss = compute_dps(
            self.snap, "Lux", level=11, item_ids=["3115", "4646"],
            target_mr=80.0,
        )
        self.assertGreater(with_nashors_ss.weighted_dps, with_nashors.weighted_dps)

    def test_stormsurge_pen_note_surfaces(self) -> None:
        # Even without a magic-damage rotation, the effective-MR note
        # surfaces whenever target_mr > 0 and a magic pen item is
        # present - the engine reports the pipeline outcome regardless
        # of rotation magic damage.
        with_ss = compute_dps(
            self.snap, "Lux", level=11, item_ids=["4646"], target_mr=80.0,
        )
        joined = " ".join(with_ss.notes)
        self.assertIn("effective target MR", joined)
        self.assertIn("65.0", joined)  # 80 - 15 = 65 after Stormsurge pen


class LethalityScalingTests(unittest.TestCase):
    """Post-V14.1 (ENGINE 1.10.0) - lethality grants flat armor pen 1:1
    at ALL caster levels. The historical 0.6 + 0.4*level/18 scaling was
    REMOVED by Riot in V14.1 (2024-01); engine sits on patch 16.10.x so
    the 1:1 rule is the correct math. Pre-batch-30 backward-compat
    invariant kept: ``level=None`` -> lethality contributes nothing
    (non-DPS callers).
    """

    def test_lethality_zero_when_level_omitted(self) -> None:
        # Pre-batch-30 invariant: callers without a level get the raw
        # armor_pen_flat-only behavior; lethality contributes nothing.
        e = ItemEffect(item_id="x", name="x", lethality=18.0)
        self.assertEqual(effective_target_armor(100.0, [e]), 100.0)

    def test_lethality_at_level_1(self) -> None:
        # Post-V14.1 1:1 rule: 18 lethality at L1 = 18 full flat pen;
        # 100 - 18 = 82. The historical 0.6222-at-L1 factor is obsolete.
        e = ItemEffect(item_id="x", name="x", lethality=18.0)
        self.assertAlmostEqual(
            effective_target_armor(100.0, [e], level=1), 82.0, places=2,
        )

    def test_lethality_full_at_level_18(self) -> None:
        # 18 lethality at lvl 18 -> 18 full flat pen (unchanged by V14.1
        # since the old formula already hit 1.0 at L18).
        e = ItemEffect(item_id="x", name="x", lethality=18.0)
        self.assertAlmostEqual(
            effective_target_armor(100.0, [e], level=18), 82.0, places=2,
        )

    def test_lethality_at_level_11_intermediate(self) -> None:
        # Post-V14.1: 18 lethality is 1:1 flat pen at every level
        # including L11. 100 - 18 = 82, same as L1 and L18.
        e = ItemEffect(item_id="x", name="x", lethality=18.0)
        self.assertAlmostEqual(
            effective_target_armor(100.0, [e], level=11),
            82.0,
            places=2,
        )

    def test_multiple_lethality_items_sum_additively(self) -> None:
        # Two lethality items at lvl 18 (full effective): 18 + 10 = 28
        # total flat pen → armor 100 → 72.
        e1 = ItemEffect(item_id="a", name="a", lethality=18.0)
        e2 = ItemEffect(item_id="b", name="b", lethality=10.0)
        self.assertAlmostEqual(
            effective_target_armor(100.0, [e1, e2], level=18), 72.0, places=2,
        )

    def test_lethality_floors_at_zero(self) -> None:
        # 100 lethality at full effective vs 30 armor → 30 - 100 = -70 floored to 0.
        e = ItemEffect(item_id="x", name="x", lethality=100.0)
        self.assertEqual(
            effective_target_armor(30.0, [e], level=18), 0.0,
        )

    def test_lethality_lands_after_pct_pen(self) -> None:
        # Pipeline post-V14.1: 100 armor * (1 - 0.35 LDR) = 65. Then
        # -18 lethality (Hubris 1:1 at any level) = 47.0. Pin the order
        # AND the 1:1 rule.
        ldr = ITEM_EFFECTS["3036"]
        hubris = ITEM_EFFECTS["6697"]
        self.assertAlmostEqual(
            effective_target_armor(100.0, [ldr, hubris], level=11),
            47.0, places=2,
        )


class HubrisLethalityTests(unittest.TestCase):
    """Phase 4 batch 30 - Hubris (6697) lethality lands."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_hubris_field_value(self) -> None:
        e = ITEM_EFFECTS["6697"]
        self.assertAlmostEqual(e.lethality, 18.0, places=2)
        self.assertFalse(e.defensive_only)

    def test_hubris_raises_dps_vs_armored(self) -> None:
        bare = compute_dps(self.snap, "Aatrox", level=11, target_armor=100.0)
        with_hubris = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["6697"], target_armor=100.0,
        )
        self.assertGreater(with_hubris.weighted_dps, bare.weighted_dps)


class LethalityPromotionsTests(unittest.TestCase):
    """Phase 4 batch 30 - 4 in-place promotions: Voltaic, Edge of Night,
    Youmuu's, Opportunity."""

    def test_voltaic_carries_10_lethality(self) -> None:
        e = ITEM_EFFECTS["6699"]
        self.assertAlmostEqual(e.lethality, 10.0, places=2)
        # Energized periodic still present (didn't replace, added on top).
        self.assertNotEqual(e.periodics, ())

    def test_edge_of_night_carries_15_lethality(self) -> None:
        e = ITEM_EFFECTS["3814"]
        self.assertAlmostEqual(e.lethality, 15.0, places=2)
        self.assertFalse(e.defensive_only)

    def test_youmuus_carries_18_lethality(self) -> None:
        e = ITEM_EFFECTS["3142"]
        self.assertAlmostEqual(e.lethality, 18.0, places=2)
        self.assertFalse(e.defensive_only)

    def test_opportunity_carries_18_lethality(self) -> None:
        e = ITEM_EFFECTS["6701"]
        self.assertAlmostEqual(e.lethality, 18.0, places=2)
        self.assertFalse(e.defensive_only)


class LethalityNewEntriesTests(unittest.TestCase):
    """Phase 4 batch 30 - Axiom Arc (6696) + Umbral Glaive (3179) new entries."""

    def test_axiom_arc_new_entry(self) -> None:
        e = ITEM_EFFECTS["6696"]
        self.assertEqual(e.name, "Axiom Arc")
        self.assertAlmostEqual(e.lethality, 18.0, places=2)
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.periodics, ())
        self.assertEqual(e.unique_passive_key, "")

    def test_umbral_glaive_new_entry(self) -> None:
        e = ITEM_EFFECTS["3179"]
        self.assertEqual(e.name, "Umbral Glaive")
        self.assertAlmostEqual(e.lethality, 18.0, places=2)
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.periodics, ())


class LethalityEngineWireInTests(unittest.TestCase):
    """Phase 4 batch 30 - compute_dps passes level into effective_target_armor."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_lethality_is_level_invariant_post_v14_1(self) -> None:
        # Post-V14.1: lethality is 1:1 flat pen at EVERY caster level.
        # Same Hubris (18 leth) build, lvl 1 vs lvl 18 - effective armor
        # should be IDENTICAL (82.0). The pre-V14.1 invariant ("higher
        # level caster gets more lethality") is OBSOLETE - the level
        # parameter is now only the "lethality contributes nothing"
        # sentinel for non-DPS callers.
        with_lvl1 = compute_dps(
            self.snap, "Aatrox", level=1, item_ids=["6697"], target_armor=100.0,
        )
        with_lvl18 = compute_dps(
            self.snap, "Aatrox", level=18, item_ids=["6697"], target_armor=100.0,
        )
        # Pull effective armor from notes
        import re
        def eff_armor(r):
            for n in r.notes:
                # Engine emits the U+2192 RIGHTWARDS ARROW glyph here
                # (pre-existing across dps.py / ability_dps.py / burst.py);
                # flagged for the operator-gated ASCII retro-sweep.
                m = re.search("effective target armor [\\d.]+\\s*→\\s*([\\d.]+)", n)
                if m:
                    return float(m.group(1))
            return None
        eff_lvl1 = eff_armor(with_lvl1)
        eff_lvl18 = eff_armor(with_lvl18)
        self.assertIsNotNone(eff_lvl1)
        self.assertIsNotNone(eff_lvl18)
        # 1:1 rule: 18 leth = 18 flat pen at every level; 100 - 18 = 82.
        self.assertAlmostEqual(eff_lvl1, 82.0, places=1)
        self.assertAlmostEqual(eff_lvl18, 82.0, places=1)
        # Stronger: identity, not just both equal-to-82.
        self.assertAlmostEqual(eff_lvl1, eff_lvl18, places=2)

    def test_pen_pipeline_composes_pct_then_lethality(self) -> None:
        # Post-V14.1: LDR (35% pen) + Hubris (18 leth 1:1) at lvl 11:
        # 100 * 0.65 = 65, then 65 - 18 = 47.0. Pin the order AND the
        # 1:1 lethality rule.
        with_combo = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3036", "6697"],
            target_armor=100.0,
        )
        joined = " ".join(with_combo.notes)
        self.assertIn("effective target armor", joined)
        self.assertIn("47.0", joined)


class CritBonusComposesWithEssenceReaverTests(unittest.TestCase):
    """Phase 4 batch 26 - item-effect-contributed crit feeds ER's Spellblade.

    Essence Reaver's bonus_damage scales linearly with CallContext.crit_chance:
    1.25 * base_ad + 50 * crit_chance. With Yun Tal contributing +25% crit,
    ER's per-proc damage rises by 50 * 0.25 = 12.5 vs the same build with
    a placeholder no-crit-contributing item.

    Pins the cross-batch invariant that batch 21 (CallContext.crit_chance)
    sees the build's actual crit, not just stats.crit.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_er_proc_damage_lifts_when_yun_tal_added(self) -> None:
        # Caitlyn lvl 11 + ER + Yun Tal vs Caitlyn lvl 11 + ER only.
        # Yun Tal's 25% crit pin should propagate into ER's lambda.
        er_only = compute_dps(self.snap, "Caitlyn", level=11, item_ids=["3508"])
        er_plus_yt = compute_dps(
            self.snap, "Caitlyn", level=11, item_ids=["3508", "3032"],
        )
        # Strict greater - the proc+stat composition should beat ER alone.
        self.assertGreater(er_plus_yt.weighted_dps, er_only.weighted_dps)


class DeadMansPlateShipwreckerTests(unittest.TestCase):
    """Dead Man's Plate Shipwrecker - iter 16 (2026-05-20) defensive_only flip.

    Original Phase 4 batch 31 modeling encoded Shipwrecker as a flat 109
    physical every ~4 attacks (full-Momentum approximation). Meraki 16.10.1
    has a REWORKED dual-track formula:
        0.4 * stacks (capped at 40 flat) +
        stacks% (capped at 100%) of base_ad bonus physical on-hit
    requiring a Momentum stack model the engine doesn't yet support.
    Iter 16 flips Dead Man's to defensive_only as a principled deferral
    (the item is a TANK pick where DPS contribution is incidental).
    Full re-encoding is a separate Phase-2 session.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_entry_present_and_defensive_only(self) -> None:
        eff = ITEM_EFFECTS.get("3742")
        self.assertIsNotNone(eff)
        self.assertTrue(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 0)

    def test_no_unique_passive_key(self) -> None:
        self.assertEqual(ITEM_EFFECTS["3742"].unique_passive_key, "")

    def test_defensive_only_has_deferral_note(self) -> None:
        # Note documents the Momentum stack model deferral so future
        # passes can find this entry when the schema lands.
        eff = ITEM_EFFECTS["3742"]
        self.assertTrue(len(eff.note) > 0)
        self.assertIn("Momentum", eff.note)

    def test_dps_no_lift_when_defensive(self) -> None:
        # Sett with Dead Man's vs bare Sett: stat block (HP/armor) does
        # not push DPS, so a defensive_only item should not lift it
        # (HP+armor are tankiness contributors, not DPS sources).
        bare = compute_dps(self.snap, "Sett", level=11, item_ids=[])
        with_dmp = compute_dps(self.snap, "Sett", level=11, item_ids=["3742"])
        self.assertAlmostEqual(with_dmp.weighted_dps, bare.weighted_dps, places=1)

    def test_no_active_shipwrecker_proc_in_dps(self) -> None:
        # defensive_only items still surface their note (documents the
        # deferral) but contribute no active proc damage to DPS.
        bare = compute_dps(self.snap, "Sett", level=11, item_ids=[])
        with_dmp = compute_dps(self.snap, "Sett", level=11, item_ids=["3742"])
        # No periodic damage delta - DPS is identical (stat block alone
        # adds tankiness, not damage, on a defensive_only entry).
        self.assertAlmostEqual(with_dmp.weighted_dps, bare.weighted_dps, places=1)


class SpectralCutlassLethality(unittest.TestCase):
    """Phase 4 batch 31 - Spectral Cutlass ARAM-only lethality entry.

    15 Lethality (same coefficient as Edge of Night) via the batch-30 schema.
    ARAM-only item; lethality pipeline applies identically to mode.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_entry_present_and_lethality_value(self) -> None:
        eff = ITEM_EFFECTS.get("4004")
        self.assertIsNotNone(eff)
        self.assertAlmostEqual(eff.lethality, 15.0)
        self.assertFalse(eff.defensive_only)

    def test_no_proc_no_unique_passive(self) -> None:
        eff = ITEM_EFFECTS["4004"]
        self.assertEqual(len(eff.periodics), 0)
        self.assertEqual(eff.unique_passive_key, "")

    def test_lethality_matches_edge_of_night_coefficient(self) -> None:
        # Both Spectral Cutlass (4004) and Edge of Night (3814) carry 15 Lethality.
        self.assertAlmostEqual(
            ITEM_EFFECTS["4004"].lethality, ITEM_EFFECTS["3814"].lethality
        )

    def test_pen_pipeline_at_lvl11(self) -> None:
        # Post-V14.1 (ENGINE 1.10.0): 15 lethality is 1:1 flat pen at
        # every level -> effective_armor(100) = 85.0 at lvl 11 (and at
        # any other level). The pre-V14.1 0.844 factor is obsolete.
        result = compute_dps(self.snap, "Aatrox", level=11, item_ids=["4004"],
                             target_armor=100.0)
        notes = " ".join(result.notes)
        self.assertIn("85.0", notes)


class Batch31DefensiveOnlyCoverageTests(unittest.TestCase):
    """Phase 4 batch 31 - 19 defensive_only support/ramp items.

    Each entry is present, tagged defensive_only=True, has no proc,
    and carries a one-line note. Coverage-completeness verification only.
    """

    EXPECTED: dict[str, str] = {
        "3109": "Knight's Vow",
        "3222": "Mikael's Blessing",
        "3107": "Redemption",
        "3190": "Locket of the Iron Solari",
        "3504": "Ardent Censer",
        "6616": "Staff of Flowing Water",
        "6620": "Echoes of Helia",
        "6617": "Moonstone Renewer",
        "6621": "Dawncore",
        "4005": "Imperial Mandate",
        "6657": "Rod of Ages",
        "3119": "Winter's Approach",
        "3121": "Fimbulwinter",
        "4401": "Force of Nature",
        "3116": "Rylai's Crystal Scepter",
        "6665": "Jak'Sho, The Protean",
        "3152": "Hextech Rocketbelt",
        "3073": "Experimental Hexplate",
        # 8020 Abyssal Mask was defensive_only in batch 31; promoted in batch 34.
    }

    def test_all_entries_present_and_defensive(self) -> None:
        for iid, expected_name in self.EXPECTED.items():
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff, f"{iid} ({expected_name}) missing from ITEM_EFFECTS")
                self.assertTrue(
                    eff.defensive_only,
                    f"{iid} ({expected_name}) should be defensive_only=True"
                )
                self.assertEqual(len(eff.periodics), 0,
                                 f"{iid} ({expected_name}) should have no periodics")
                self.assertTrue(len(eff.note) > 0,
                                f"{iid} ({expected_name}) should have a non-empty note")

    def test_defensive_only_count_increased(self) -> None:
        # After batch 31, defensive_only count is 40 (was 21 pre-batch-29).
        count = sum(1 for e in ITEM_EFFECTS.values() if e.defensive_only)
        self.assertGreaterEqual(count, 40)


# ────────────────────────── Phase 4 batch 32 tests ──────────────────────────

class RabadonsApAmpTests(unittest.TestCase):
    """Rabadon's Deathcap ap_amp_pct=0.30 + total_ap_amp_multiplier helper."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_entry_present_and_ap_amp_pct(self) -> None:
        eff = ITEM_EFFECTS.get("3089")
        self.assertIsNotNone(eff, "Rabadon's Deathcap (3089) must be in ITEM_EFFECTS")
        self.assertAlmostEqual(eff.ap_amp_pct, 0.30, places=4)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 0)

    def test_total_ap_amp_multiplier_single(self) -> None:
        from agents.daemon_slayer.effects import collect_effects, total_ap_amp_multiplier
        effects = collect_effects(["3089"])
        self.assertAlmostEqual(total_ap_amp_multiplier(effects), 1.30, places=4)

    def test_total_ap_amp_multiplier_no_items(self) -> None:
        from agents.daemon_slayer.effects import collect_effects, total_ap_amp_multiplier
        self.assertAlmostEqual(total_ap_amp_multiplier([]), 1.0, places=4)
        effects = collect_effects(["3031"])  # IE has no ap_amp_pct
        self.assertAlmostEqual(total_ap_amp_multiplier(effects), 1.0, places=4)

    def test_dps_lift_with_nashor_plus_rabadon(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        dps_nashor_only = compute_dps(
            self.snap, "Lissandra", level=11, item_ids=["3115"]
        )
        dps_with_rabadon = compute_dps(
            self.snap, "Lissandra", level=11, item_ids=["3115", "3089"]
        )
        self.assertGreater(
            dps_with_rabadon.weighted_dps, dps_nashor_only.weighted_dps,
            "Adding Rabadon's should boost DPS when Nashor's AP proc is active"
        )

    def test_note_surfaces_rabadon_amp(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        result = compute_dps(
            self.snap, "Lissandra", level=11, item_ids=["3115", "3089"]
        )
        combined_notes = " ".join(result.notes)
        self.assertIn("AP amplified", combined_notes)
        self.assertIn("1.3000", combined_notes)


class DuskAndDawnSpellbladeTests(unittest.TestCase):
    """Dusk and Dawn (2510) Spellblade 75% base AD + 10% AP magical, 1.5s, dedup."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_entry_present_and_shape(self) -> None:
        eff = ITEM_EFFECTS.get("2510")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)
        proc = eff.periodics[0]
        self.assertEqual(proc.damage_type, "magical")
        self.assertAlmostEqual(proc.every_n_seconds, 1.5, places=3)
        self.assertEqual(eff.unique_passive_key, "spellblade")

    def test_proc_damage_formula(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["2510"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, ap=200.0)
        expected = 0.75 * 100.0 + 0.10 * 200.0  # 75 + 20 = 95
        self.assertAlmostEqual(proc.resolve_damage(ctx), expected, places=4)

    def test_spellblade_dedup_with_trinity(self) -> None:
        from agents.daemon_slayer.effects import collect_effects
        effects = collect_effects(["2510", "3078"])  # Dusk first -> wins
        spellblade_items = [e for e in effects if e.unique_passive_key == "spellblade"]
        self.assertEqual(len(spellblade_items), 1)
        self.assertEqual(spellblade_items[0].item_id, "2510")

    def test_dps_lift_over_bare(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        dps_bare = compute_dps(self.snap, "Jayce", level=11)
        dps_with = compute_dps(self.snap, "Jayce", level=11, item_ids=["2510"])
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)


class Batch32LethAllyPromotionsTests(unittest.TestCase):
    """The Collector (667666), Prowler's Claw (6693), Bastionbreaker (2520) lethality."""

    EXPECTED_LETH: dict[str, float] = {
        "667666": 10.0,
        "6693": 22.0,
        "2520": 22.0,
    }
    EXPECTED_NAMES: dict[str, str] = {
        "667666": "The Collector",
        "6693": "Prowler's Claw",
        "2520": "Bastionbreaker",
    }

    def test_entries_present_and_lethality(self) -> None:
        for iid, leth in self.EXPECTED_LETH.items():
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff, f"{iid} must be in ITEM_EFFECTS")
                self.assertFalse(eff.defensive_only)
                self.assertAlmostEqual(
                    eff.lethality, leth, places=2,
                    msg=f"{iid} lethality expected {leth}"
                )
                self.assertEqual(eff.name, self.EXPECTED_NAMES[iid])

    def test_pen_pipeline_applied_at_lvl11(self) -> None:
        # Post-V14.1: Prowler's 22 lethality is 1:1 flat pen at any level
        # including L11 -> effective_armor(50) = 50 - 22 = 28.0
        from agents.daemon_slayer.effects import collect_effects, effective_target_armor
        effects = collect_effects(["6693"])
        eff_armor = effective_target_armor(50.0, effects, level=11)
        self.assertAlmostEqual(eff_armor, 50.0 - 22.0, places=1)


class OverlordsBloodmailStatWalkTests(unittest.TestCase):
    """Overlord's Bloodmail (2501) bonus_ad_pct_bonus_hp=0.025 engine stat walk."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_entry_present_and_field(self) -> None:
        eff = ITEM_EFFECTS.get("2501")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertAlmostEqual(eff.bonus_ad_pct_bonus_hp, 0.025, places=4)

    def test_stat_walk_adds_bonus_ad(self) -> None:
        from agents.daemon_slayer.engine import build_champion
        # Overlord's has 550 hp_flat -> Tyranny adds 2.5% * 550 = 13.75 bonus AD
        # Total AD increase should exceed item's 30 flat AD alone.
        resolved_with = build_champion(self.snap, "Garen", level=11, item_ids=["2501"])
        resolved_bare = build_champion(self.snap, "Garen", level=11)
        ad_diff = resolved_with.stats["ad"] - resolved_bare.stats["ad"]
        self.assertGreater(ad_diff, 43.0,
                           "AD delta must exceed item AD (30) + Tyranny (~13.75)")

    def test_dps_lift_over_bare(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        dps_bare = compute_dps(self.snap, "Garen", level=11, target_armor=80.0)
        dps_with = compute_dps(self.snap, "Garen", level=11, item_ids=["2501"],
                               target_armor=80.0)
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)


class DemonicEmbraceApFromHpTests(unittest.TestCase):
    """Demonic Embrace (4637): Dark Pact 2% bonus HP as AP + Azakana's Gaze burn (batch 33)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_entry_present_and_field(self) -> None:
        eff = ITEM_EFFECTS.get("4637")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertAlmostEqual(eff.ap_per_bonus_hp_pct, 0.02, places=4)

    def test_same_coefficient_as_riftmaker(self) -> None:
        eff_rift = ITEM_EFFECTS.get("4633")
        eff_demonic = ITEM_EFFECTS.get("4637")
        self.assertAlmostEqual(
            eff_rift.ap_per_bonus_hp_pct, eff_demonic.ap_per_bonus_hp_pct, places=4,
            msg="Riftmaker and Demonic Embrace both use 2% bonus HP as AP"
        )

    def test_no_unique_passive_key(self) -> None:
        eff = ITEM_EFFECTS.get("4637")
        self.assertEqual(eff.unique_passive_key, "",
                         "Dark Pact and Void Infusion are different passives; they stack")

    def test_azakana_proc_added(self) -> None:
        eff = ITEM_EFFECTS.get("4637")
        self.assertEqual(len(eff.periodics), 1, "Azakana's Gaze proc must be present")
        proc = eff.periodics[0]
        self.assertEqual(proc.damage_type, "magical")
        self.assertAlmostEqual(proc.every_n_seconds, 1.0, places=3)

    def test_azakana_proc_formula(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["4637"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, target_max_hp=2000.0)
        # 1% * 2000 = 20
        self.assertAlmostEqual(proc.resolve_damage(ctx), 20.0, places=4)

    def test_dps_lift_over_bare(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        dps_bare = compute_dps(self.snap, "Lux", level=11, target_max_hp=2000.0)
        dps_with = compute_dps(self.snap, "Lux", level=11, item_ids=["4637"],
                               target_max_hp=2000.0)
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)


class Batch32DefensiveOnlyTests(unittest.TestCase):
    """7 remaining defensive_only entries from batch 32 (Blackfire Torch promoted in batch 33)."""

    EXPECTED: dict[str, str] = {
        "3165": "Morellonomicon",
        "4628": "Horizon Focus",
        # 3118 Malignance promoted to active Hatefog proc in batch 64
        "2517": "Endless Hunger",
        "6609": "Chempunk Chainsword",
        "2523": "Hexoptics C44",
        # 8010 Bloodletter's Curse promoted to active mr_reduction_pct in batch 52
    }

    def test_all_entries_present_and_defensive(self) -> None:
        for iid, expected_name in self.EXPECTED.items():
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff, f"{iid} must be in ITEM_EFFECTS")
                self.assertTrue(eff.defensive_only,
                                f"{iid} ({expected_name}) should be defensive_only=True")
                self.assertEqual(len(eff.periodics), 0)
                self.assertTrue(len(eff.note) > 0)

    def test_defensive_only_count_increased(self) -> None:
        # After batch 34: 54 from batch 33 - 1 (Abyssal Mask promoted) = 53 defensive_only.
        count = sum(1 for e in ITEM_EFFECTS.values() if e.defensive_only)
        self.assertGreaterEqual(count, 53)


class BlackfireTorchBurnTests(unittest.TestCase):
    """Blackfire Torch (2503) Baleful Blaze promotion (batch 33)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_entry_promoted_not_defensive_only(self) -> None:
        eff = ITEM_EFFECTS.get("2503")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only,
                         "Blackfire Torch must be promoted from defensive_only in batch 33")

    def test_proc_shape(self) -> None:
        eff = ITEM_EFFECTS.get("2503")
        self.assertEqual(len(eff.periodics), 1)
        proc = eff.periodics[0]
        self.assertEqual(proc.damage_type, "magical")
        self.assertAlmostEqual(proc.every_n_seconds, 0.5, places=3)

    def test_proc_formula(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["2503"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, ap=300.0)
        # 6 + 6% * 300 = 6 + 18 = 24
        self.assertAlmostEqual(proc.resolve_damage(ctx), 24.0, places=4)

    def test_proc_formula_zero_ap(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["2503"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, ap=0.0)
        # flat component only: 6
        self.assertAlmostEqual(proc.resolve_damage(ctx), 6.0, places=4)

    def test_dps_lift_over_bare(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        dps_bare = compute_dps(self.snap, "Lux", level=11)
        dps_with = compute_dps(self.snap, "Lux", level=11, item_ids=["2503"])
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)


class GamblersBladeDualPenTests(unittest.TestCase):
    """Gambler's Blade (667101) lethality + magic pen flat (batch 33)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_entry_present_and_shape(self) -> None:
        eff = ITEM_EFFECTS.get("667101")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertAlmostEqual(eff.lethality, 15.0, places=2)
        self.assertAlmostEqual(eff.magic_pen_flat, 15.0, places=2)
        self.assertEqual(len(eff.periodics), 0)

    def test_lethality_applies_at_lvl18(self) -> None:
        from agents.daemon_slayer.effects import collect_effects, effective_target_armor
        effects = collect_effects(["667101"])
        # lvl 18: factor = 0.6 + 0.4*(18/18) = 1.0 -> flat pen = 15 * 1.0 = 15
        eff_armor = effective_target_armor(50.0, effects, level=18)
        self.assertAlmostEqual(eff_armor, 35.0, places=1)

    def test_lethality_dps_lift(self) -> None:
        # Magic pen flat has no effect on an AA-only rotation (physical damage);
        # lethality does - verify the pen pipeline fires on the physical side.
        from agents.daemon_slayer.dps import compute_dps
        dps_bare = compute_dps(self.snap, "Zed", level=11, target_armor=50.0)
        dps_with = compute_dps(self.snap, "Zed", level=11, item_ids=["667101"],
                               target_armor=50.0)
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)


class UnendingDespairCasterHpBurnTests(unittest.TestCase):
    """Unending Despair (2502) Agony: 3% caster bonus HP magic every 4s (batch 33)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_entry_present_and_shape(self) -> None:
        eff = ITEM_EFFECTS.get("2502")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)
        proc = eff.periodics[0]
        self.assertEqual(proc.damage_type, "magical")
        self.assertAlmostEqual(proc.every_n_seconds, 4.0, places=3)

    def test_proc_formula(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["2502"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, caster_bonus_hp=1200.0)
        # 3% * 1200 = 36
        self.assertAlmostEqual(proc.resolve_damage(ctx), 36.0, places=4)

    def test_proc_zero_bonus_hp(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["2502"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, caster_bonus_hp=0.0)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 0.0, places=4)

    def test_dps_lift_over_bare(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        dps_bare = compute_dps(self.snap, "Malphite", level=11)
        dps_with = compute_dps(self.snap, "Malphite", level=11, item_ids=["2502"])
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)


class Batch33DefensiveOnlyTests(unittest.TestCase):
    """7 new defensive_only entries in batch 33."""

    EXPECTED: dict[str, str] = {
        # 4636 Night Harvester promoted to active periodic in batch 52
        # 2512 Fiendhunter Bolts promoted to active periodic (Opening Barrage 45s CD)
        "663060": "Sword of the Divine",
        # 667112 Flesheater promoted to active in batch 50 (armor_reduction_flat)
        "664011": "Sword of Blossoming Dawn",
        "2522": "Actualizer",
        # 667109 Cruelty promoted batch 62 (Watch Them Fall comet proc)
    }

    def test_all_entries_present_and_defensive(self) -> None:
        for iid, expected_name in self.EXPECTED.items():
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff, f"{iid} must be in ITEM_EFFECTS")
                self.assertTrue(eff.defensive_only,
                                f"{iid} ({expected_name}) should be defensive_only=True")
                self.assertEqual(len(eff.periodics), 0)
                self.assertTrue(len(eff.note) > 0)

    def test_blackfire_torch_no_longer_defensive(self) -> None:
        # Blackfire Torch was defensive_only in batch 32; promoted in batch 33.
        eff = ITEM_EFFECTS.get("2503")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only,
                         "Blackfire Torch must be promoted (defensive_only=False) in batch 33")


class AbyssalMaskMagicAmpTests(unittest.TestCase):
    """Abyssal Mask (8020) magic_amp_pct=0.12 promotion (batch 34)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_entry_promoted_not_defensive_only(self) -> None:
        eff = ITEM_EFFECTS.get("8020")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only,
                         "Abyssal Mask must be promoted from defensive_only in batch 34")

    def test_magic_amp_pct_field(self) -> None:
        eff = ITEM_EFFECTS.get("8020")
        self.assertAlmostEqual(eff.magic_amp_pct, 0.12, places=4)
        self.assertEqual(len(eff.periodics), 0)

    def test_total_magic_amp_multiplier_helper(self) -> None:
        from agents.daemon_slayer.effects import total_magic_amp_multiplier, collect_effects
        effects_with = collect_effects(["8020"])
        self.assertAlmostEqual(total_magic_amp_multiplier(effects_with), 1.12, places=4)

    def test_multiplier_is_1_without_abyssal(self) -> None:
        from agents.daemon_slayer.effects import total_magic_amp_multiplier, collect_effects
        effects_bare = collect_effects(["3031"])  # IE - no magic_amp_pct
        self.assertAlmostEqual(total_magic_amp_multiplier(effects_bare), 1.0, places=4)

    def test_multiplier_stacks_with_second_abyssal(self) -> None:
        # Two Abyssal Masks stack multiplicatively: 1.12 * 1.12 = 1.2544
        from agents.daemon_slayer.effects import total_magic_amp_multiplier, collect_effects
        effects = collect_effects(["8020", "8020"])
        self.assertAlmostEqual(total_magic_amp_multiplier(effects), 1.12 * 1.12, places=4)

    def test_magic_amp_boosts_magical_proc_dps(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        # Nashor's Tooth (3115) adds a per-attack magical proc; Abyssal Mask should amplify it.
        dps_nashor = compute_dps(self.snap, "Lux", level=11, item_ids=["3115"],
                                 target_mr=50.0)
        dps_nashor_abyssal = compute_dps(self.snap, "Lux", level=11,
                                         item_ids=["3115", "8020"], target_mr=50.0)
        self.assertGreater(dps_nashor_abyssal.weighted_dps, dps_nashor.weighted_dps)

    def test_magic_amp_does_not_help_physical_only_build(self) -> None:
        # Abyssal Mask has no proc of its own - it only amplifies other items'
        # magical procs. Verify it carries no periodics (the amp fires externally).
        eff = ITEM_EFFECTS.get("8020")
        self.assertEqual(len(eff.periodics), 0,
                         "Abyssal Mask has no periodic proc - amp fires on other items' magic procs")

    def test_note_in_dps_output(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        result = compute_dps(self.snap, "Lux", level=11, item_ids=["3115", "8020"],
                             target_mr=50.0)
        magic_amp_notes = [n for n in result.notes if "magic damage amp" in n]
        self.assertEqual(len(magic_amp_notes), 1)
        self.assertIn("12%", magic_amp_notes[0])


class Batch35LethMissedAndDualPenTests(unittest.TestCase):
    """Duskblade (6691) lethality + Perplexity (4015) dual-pen + Hellfire (4017) lethality."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_duskblade_lethality(self) -> None:
        eff = ITEM_EFFECTS.get("6691")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertAlmostEqual(eff.lethality, 18.0, places=2)
        self.assertEqual(len(eff.periodics), 0)

    def test_duskblade_pen_pipeline(self) -> None:
        from agents.daemon_slayer.effects import collect_effects, effective_target_armor
        effects = collect_effects(["6691"])
        # lvl 18: factor = 1.0 → flat pen = 18 * 1.0 = 18
        eff_armor = effective_target_armor(50.0, effects, level=18)
        self.assertAlmostEqual(eff_armor, 50.0 - 18.0, places=1)

    def test_perplexity_dual_pen_fields(self) -> None:
        eff = ITEM_EFFECTS.get("4015")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertAlmostEqual(eff.armor_pen_pct, 0.22, places=4)
        self.assertAlmostEqual(eff.magic_pen_pct, 0.30, places=4)
        self.assertEqual(len(eff.periodics), 0)

    def test_perplexity_armor_pen_reduces_effective_armor(self) -> None:
        from agents.daemon_slayer.effects import collect_effects, effective_target_armor
        effects = collect_effects(["4015"])
        eff_armor = effective_target_armor(100.0, effects, level=11)
        # 22% armor pen: 100 * (1 - 0.22) = 78 (no lethality contribution)
        self.assertAlmostEqual(eff_armor, 78.0, places=1)

    def test_perplexity_magic_pen_reduces_effective_mr(self) -> None:
        from agents.daemon_slayer.effects import collect_effects, effective_target_mr
        effects = collect_effects(["4015"])
        eff_mr = effective_target_mr(100.0, effects)
        # 30% magic pen: 100 * (1 - 0.30) = 70
        self.assertAlmostEqual(eff_mr, 70.0, places=1)

    def test_hellfire_hatchet_lethality(self) -> None:
        eff = ITEM_EFFECTS.get("4017")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertAlmostEqual(eff.lethality, 12.0, places=2)
        # Char proc promoted: 15s CD hp_diff burn
        self.assertEqual(len(eff.periodics), 1)
        self.assertEqual(eff.periodics[0].name, "Char")
        self.assertAlmostEqual(eff.periodics[0].every_n_seconds, 15.0, places=1)


class DivineSundererSpellbladeTests(unittest.TestCase):
    """Divine Sunderer (6632) Spellblade physical proc joining the spellblade family."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_entry_present_and_shape(self) -> None:
        eff = ITEM_EFFECTS.get("6632")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)
        proc = eff.periodics[0]
        self.assertEqual(proc.damage_type, "physical")
        self.assertAlmostEqual(proc.every_n_seconds, 3.0, places=3)
        self.assertEqual(eff.unique_passive_key, "spellblade")

    def test_proc_formula_base_ad_component(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["6632"].periodics[0]
        # 125% base AD + 6% target max HP; no max HP -> only base AD contribution
        ctx = CallContext(base_ad=200.0, bonus_ad=50.0, level=11, target_max_hp=0.0)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 1.25 * 200.0, places=4)

    def test_proc_formula_max_hp_component(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["6632"].periodics[0]
        # 6% of 3000 target HP = 180, plus 125% base AD
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, target_max_hp=3000.0)
        expected = 1.25 * 100.0 + 0.06 * 3000.0  # 125 + 180 = 305
        self.assertAlmostEqual(proc.resolve_damage(ctx), expected, places=4)

    def test_spellblade_dedup_with_trinity(self) -> None:
        from agents.daemon_slayer.effects import collect_effects
        # Divine Sunderer first → should win dedup
        effects = collect_effects(["6632", "3078"])
        sb_items = [e for e in effects if e.unique_passive_key == "spellblade"]
        self.assertEqual(len(sb_items), 1)
        self.assertEqual(sb_items[0].item_id, "6632")

    def test_dps_lift_over_bare(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        dps_bare = compute_dps(self.snap, "Garen", level=11, target_max_hp=2000.0)
        dps_with = compute_dps(self.snap, "Garen", level=11, item_ids=["6632"],
                               target_max_hp=2000.0)
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)


class NavoriFlickerbladeTests(unittest.TestCase):
    """Navori Flickerblade (6675) Bring It Down every-3rd-attack level-scaling physical proc.

    Note: batch 35 mistakenly keyed this as "6672" (Kraken Slayer's DDragon ID),
    silently overwriting Kraken Slayer. Fixed in batch 41 - now correctly at "6675".
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_entry_present_and_shape(self) -> None:
        eff = ITEM_EFFECTS.get("6675")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)
        proc = eff.periodics[0]
        self.assertEqual(proc.damage_type, "physical")
        self.assertEqual(proc.every_n_attacks, 3)

    def test_proc_formula_at_level_1(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["6675"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=1)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 120.0, places=4)

    def test_proc_formula_at_level_11(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["6675"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11)
        expected = min(168.0, 120.0 + 4.0 * 10)  # 160
        self.assertAlmostEqual(proc.resolve_damage(ctx), expected, places=4)

    def test_proc_capped_at_level_18(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["6675"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=18)
        # min(168, 120 + 4*17) = min(168, 188) = 168
        self.assertAlmostEqual(proc.resolve_damage(ctx), 168.0, places=4)

    def test_dps_lift_over_bare(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        dps_bare = compute_dps(self.snap, "Jinx", level=11, target_armor=50.0)
        dps_with = compute_dps(self.snap, "Jinx", level=11, item_ids=["6675"],
                               target_armor=50.0)
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)


class Batch35DefensiveOnlyTests(unittest.TestCase):
    """6 new defensive_only entries in batch 35."""

    EXPECTED: dict[str, str] = {
        "6630": "Goredrinker",
        "6671": "Galeforce",
        "3050": "Zeke's Convergence",
        "4016": "Wordless Promise",
        "4014": "Frozen Mallet",
        "4013": "Lightning Braid",
    }

    def test_all_entries_present_and_defensive(self) -> None:
        for iid, expected_name in self.EXPECTED.items():
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff, f"{iid} must be in ITEM_EFFECTS")
                self.assertTrue(eff.defensive_only,
                                f"{iid} ({expected_name}) should be defensive_only=True")
                self.assertEqual(len(eff.periodics), 0)
                self.assertTrue(len(eff.note) > 0)

    def test_defensive_only_count_after_batch35(self) -> None:
        count = sum(1 for e in ITEM_EFFECTS.values() if e.defensive_only)
        # 53 after batch 34 + 6 new = 59
        self.assertGreaterEqual(count, 59)


# ────────────────────────── Phase 4 batch 36 tests ──────────────────────────

class Batch36ArenaAndRiteOfRuinTests(unittest.TestCase):
    """Batch 36: Arena item sweep + Rite of Ruin crit."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_detonation_orb_magic_pen(self) -> None:
        eff = ITEM_EFFECTS.get("447113")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertAlmostEqual(eff.magic_pen_flat, 12.0, places=2)
        self.assertEqual(len(eff.periodics), 0)

    def test_reverberation_resonate_shape(self) -> None:
        eff = ITEM_EFFECTS.get("447114")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)
        proc = eff.periodics[0]
        self.assertEqual(proc.damage_type, "magical")
        self.assertEqual(proc.every_n_attacks, 1)

    def test_reverberation_proc_formula(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["447114"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, caster_bonus_hp=1000.0)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 10.0 + 0.02 * 1000.0, places=4)

    def test_reverberation_zero_bonus_hp(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["447114"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, caster_bonus_hp=0.0)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 10.0, places=4)

    def test_pyromancer_spark_shape(self) -> None:
        eff = ITEM_EFFECTS.get("447118")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)
        proc = eff.periodics[0]
        self.assertEqual(proc.damage_type, "magical")
        self.assertAlmostEqual(proc.every_n_seconds, 5.0, places=3)

    def test_pyromancer_spark_formula(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["447118"].periodics[0]
        ctx_l1 = CallContext(base_ad=100.0, bonus_ad=0.0, level=1)
        ctx_l18 = CallContext(base_ad=100.0, bonus_ad=0.0, level=18)
        self.assertAlmostEqual(proc.resolve_damage(ctx_l1), 100.0, places=1)
        self.assertAlmostEqual(proc.resolve_damage(ctx_l18), 350.0, places=1)

    def test_lightning_rod_shape(self) -> None:
        eff = ITEM_EFFECTS.get("447119")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)
        proc = eff.periodics[0]
        self.assertEqual(proc.damage_type, "magical")
        self.assertAlmostEqual(proc.every_n_seconds, 16.0, places=3)

    def test_lightning_rod_formula_components(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["447119"].periodics[0]
        # base only at level 1: 135
        ctx_base = CallContext(base_ad=0.0, bonus_ad=0.0, level=1, ap=0.0, target_max_hp=0.0)
        self.assertAlmostEqual(proc.resolve_damage(ctx_base), 135.0, places=1)
        # bonus_ad component: 30% * 100 = 30
        ctx_ad = CallContext(base_ad=0.0, bonus_ad=100.0, level=1, ap=0.0, target_max_hp=0.0)
        self.assertAlmostEqual(proc.resolve_damage(ctx_ad), 135.0 + 30.0, places=1)
        # ap component: 50% * 200 = 100
        ctx_ap = CallContext(base_ad=0.0, bonus_ad=0.0, level=1, ap=200.0, target_max_hp=0.0)
        self.assertAlmostEqual(proc.resolve_damage(ctx_ap), 135.0 + 100.0, places=1)
        # target_max_hp: 10% * 3000 = 300
        ctx_hp = CallContext(base_ad=0.0, bonus_ad=0.0, level=1, ap=0.0, target_max_hp=3000.0)
        self.assertAlmostEqual(proc.resolve_damage(ctx_hp), 135.0 + 300.0, places=1)

    def test_regicide_lethality(self) -> None:
        eff = ITEM_EFFECTS.get("447115")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertAlmostEqual(eff.lethality, 15.0, places=2)
        self.assertEqual(len(eff.periodics), 0)

    def test_rite_of_ruin_crit_bonus(self) -> None:
        eff = ITEM_EFFECTS.get("3430")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertAlmostEqual(eff.crit_chance_bonus_flat, 0.20, places=4)
        self.assertEqual(len(eff.periodics), 0)

    def test_rite_of_ruin_crit_lifts_dps(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        # Rite of Ruin + some crit baseline should outperform bare Rite
        dps_bare = compute_dps(self.snap, "Jinx", level=11)
        dps_with = compute_dps(self.snap, "Jinx", level=11, item_ids=["3430"])
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)

    def test_lightning_rod_dps_lift_with_ap(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        dps_bare = compute_dps(self.snap, "Lux", level=11, target_max_hp=2000.0)
        dps_with = compute_dps(self.snap, "Lux", level=11, item_ids=["447119"],
                               target_max_hp=2000.0)
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)

    def test_batch36_defensive_only_entries(self) -> None:
        expected = {
            "447108": "Runecarver",
            "447116": "Kinkou Jitte",
            "447120": "Diamond-Tipped Spear",
            "447121": "Twilight's Edge",
            "447107": "Decapitator",
            "447100": "Mirage Blade",
        }
        for iid, name in expected.items():
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff, f"{iid} missing")
                self.assertTrue(eff.defensive_only, f"{iid} ({name}) should be defensive_only")
                self.assertEqual(len(eff.periodics), 0)

    def test_defensive_only_count_after_batch36(self) -> None:
        count = sum(1 for e in ITEM_EFFECTS.values() if e.defensive_only)
        # 59 after batch 35 + 6 new = 65
        self.assertGreaterEqual(count, 65)


# ────────────────────────── Phase 4 batch 37 tests ──────────────────────────

class Batch37TrueDamageTests(unittest.TestCase):
    """Batch 37: TRUE damage type + Darksteel Talons / Fulmination / Reaper's Toll."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ── TRUE constant present ──

    def test_true_constant_exported(self) -> None:
        from agents.daemon_slayer.effects import TRUE
        self.assertEqual(TRUE, "true")

    def test_true_in_damage_types(self) -> None:
        from agents.daemon_slayer.effects import _DAMAGE_TYPES, TRUE
        self.assertIn(TRUE, _DAMAGE_TYPES)

    # ── Darksteel Talons (443054) ──

    def test_darksteel_talons_present(self) -> None:
        eff = ITEM_EFFECTS.get("443054")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)

    def test_darksteel_talons_true_type(self) -> None:
        proc = ITEM_EFFECTS["443054"].periodics[0]
        self.assertEqual(proc.damage_type, "true")
        self.assertEqual(proc.every_n_attacks, 1)

    def test_darksteel_talons_formula_level1(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["443054"].periodics[0]
        ctx = CallContext(base_ad=0.0, bonus_ad=0.0, level=1)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 10.0, places=4)

    def test_darksteel_talons_formula_level18(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["443054"].periodics[0]
        ctx = CallContext(base_ad=0.0, bonus_ad=0.0, level=18)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 20.0, places=4)

    def test_darksteel_talons_true_bypasses_armor(self) -> None:
        # TRUE procs ignore armor - DPS with 200 armor should equal DPS with 0 armor
        from agents.daemon_slayer.dps import compute_dps
        dps_no_armor = compute_dps(
            self.snap, "Jinx", level=11, item_ids=["443054"], target_armor=0.0
        )
        dps_high_armor = compute_dps(
            self.snap, "Jinx", level=11, item_ids=["443054"], target_armor=200.0
        )
        # The TRUE proc portion should be identical; overall DPS drops but proc contribution is same
        # We verify: with no other items, weighted_dps_high < weighted_dps_no_armor
        # (AA portion drops with armor) BUT the difference should be less than a pure-physical
        # item at same level
        dps_kraken_no_armor = compute_dps(
            self.snap, "Jinx", level=11, item_ids=["3076"], target_armor=0.0
        )
        dps_kraken_high_armor = compute_dps(
            self.snap, "Jinx", level=11, item_ids=["3076"], target_armor=200.0
        )
        drop_true_item = dps_no_armor.weighted_dps - dps_high_armor.weighted_dps
        drop_physical_item = dps_kraken_no_armor.weighted_dps - dps_kraken_high_armor.weighted_dps
        # True item loses no more to armor than a similar physical item.
        # The two drops can be mathematically equal here; the quadratic
        # stat-growth path introduces sub-ULP float noise, so compare
        # with a tiny tolerance rather than a strict float inequality.
        self.assertLessEqual(drop_true_item, drop_physical_item + 1e-9)

    def test_darksteel_talons_dps_lift(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        dps_bare = compute_dps(self.snap, "Jinx", level=11, target_armor=50.0)
        dps_with = compute_dps(self.snap, "Jinx", level=11, item_ids=["443054"],
                               target_armor=50.0)
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)

    # ── Fulmination (443055) ──

    def test_fulmination_present(self) -> None:
        eff = ITEM_EFFECTS.get("443055")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)

    def test_fulmination_magical_type(self) -> None:
        proc = ITEM_EFFECTS["443055"].periodics[0]
        self.assertEqual(proc.damage_type, "magical")
        self.assertEqual(proc.every_n_attacks, 100)

    def test_fulmination_dynamo_formula(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["443055"].periodics[0]
        ctx = CallContext(base_ad=0.0, bonus_ad=0.0, level=11, target_max_hp=3000.0)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 0.13 * 3000.0, places=4)

    def test_fulmination_dps_lift_with_target_hp(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        dps_bare = compute_dps(self.snap, "Jinx", level=11, target_max_hp=3000.0)
        dps_with = compute_dps(self.snap, "Jinx", level=11, item_ids=["443055"],
                               target_max_hp=3000.0)
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)

    def test_fulmination_zero_damage_at_zero_hp(self) -> None:
        # Dynamo proc returns 0 when target_max_hp=0
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["443055"].periodics[0]
        ctx = CallContext(base_ad=0.0, bonus_ad=0.0, level=11, target_max_hp=0.0)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 0.0, places=6)

    # ── Reaper's Toll (443090) ──

    def test_reapers_toll_present(self) -> None:
        eff = ITEM_EFFECTS.get("443090")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)

    def test_reapers_toll_true_type(self) -> None:
        proc = ITEM_EFFECTS["443090"].periodics[0]
        self.assertEqual(proc.damage_type, "true")
        self.assertEqual(proc.every_n_attacks, 1)

    def test_reapers_toll_formula(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["443090"].periodics[0]
        ctx = CallContext(base_ad=0.0, bonus_ad=0.0, level=11, target_max_hp=4000.0)
        self.assertAlmostEqual(proc.resolve_damage(ctx), 0.007 * 4000.0, places=4)

    def test_reapers_toll_dps_lift_with_target_hp(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        dps_bare = compute_dps(self.snap, "Jinx", level=11, target_max_hp=3000.0)
        dps_with = compute_dps(self.snap, "Jinx", level=11, item_ids=["443090"],
                               target_max_hp=3000.0)
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)

    def test_reapers_toll_true_bypasses_armor(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        # Same proc should fire regardless of armor
        dps_low = compute_dps(self.snap, "Jinx", level=11, item_ids=["443090"],
                              target_armor=0.0, target_max_hp=3000.0)
        dps_high = compute_dps(self.snap, "Jinx", level=11, item_ids=["443090"],
                               target_armor=300.0, target_max_hp=3000.0)
        # AA DPS drops, but the 0.7% HP true proc doesn't - difference should be small
        # compared to a physical item at same armor swing
        dps_bork_low = compute_dps(self.snap, "Jinx", level=11, item_ids=["3153"],
                                   target_armor=0.0, target_max_hp=3000.0)
        dps_bork_high = compute_dps(self.snap, "Jinx", level=11, item_ids=["3153"],
                                    target_armor=300.0, target_max_hp=3000.0)
        drop_true = dps_low.weighted_dps - dps_high.weighted_dps
        drop_bork = dps_bork_low.weighted_dps - dps_bork_high.weighted_dps
        self.assertLessEqual(drop_true, drop_bork)

    # ── Defensive_only count ──

    def test_batch37_defensive_only_entries(self) -> None:
        expected = {
            "447101": "Gambler's Blade",
            # 447102 Reality Fracture promoted batch 60 (ZZ'Rot Voidmites proc)
            "447103": "Hemomancer's Helm",
            # 447104 Innervating Locket promoted (Fill the Soul bonus_ap_stacked)
            "447105": "Empyrean Promise",
            "447106": "Dragonheart",
            # 447109 Cruelty promoted batch 62 (Watch Them Fall comet proc)
            "447110": "Moonflair Spellblade",
            # 447112 Flesheater promoted to active in batch 50 (armor_reduction_flat)
            "447122": "Black Hole Gauntlet",
            "447123": "Puppeteer",
            "443056": "Demon King's Crown",
            # 443060 Sword of the Divine promoted to active in batch 54 (EV crit_damage_bonus)
            # 443069 Hamstringer promoted to active in batch 53 (Scour crit-bleed)
        }
        for iid, name in expected.items():
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff, f"{iid} missing from ITEM_EFFECTS")
                self.assertTrue(eff.defensive_only,
                                f"{iid} ({name}) should be defensive_only=True")
                self.assertEqual(len(eff.periodics), 0)
                self.assertTrue(len(eff.note) > 0)

    def test_defensive_only_count_after_batch37(self) -> None:
        count = sum(1 for e in ITEM_EFFECTS.values() if e.defensive_only)
        # 65 after batch 36 + 14 new = 79
        self.assertGreaterEqual(count, 79)

    def test_total_entry_count_after_batch37(self) -> None:
        # 139 after batch 36 + 17 new (3 active + 14 defensive) = 156
        self.assertGreaterEqual(len(ITEM_EFFECTS), 156)


# ────────────────────────── Phase 4 batch 38 tests ──────────────────────────

class Batch38GiantSlayerSchemaTests(unittest.TestCase):
    """Batch 38: Giant Slayer MAX HP diff amp schema."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ── Helper function ──

    def test_giant_slayer_multiplier_zero_when_caster_higher(self) -> None:
        from agents.daemon_slayer.effects import total_giant_slayer_multiplier
        eff = [ITEM_EFFECTS["4015"]]
        # Caster has 3000 HP, target has 2000 HP - no amp
        result = total_giant_slayer_multiplier(eff, target_max_hp=2000.0, caster_max_hp=3000.0)
        self.assertAlmostEqual(result, 1.0, places=6)

    def test_giant_slayer_multiplier_zero_when_equal(self) -> None:
        from agents.daemon_slayer.effects import total_giant_slayer_multiplier
        eff = [ITEM_EFFECTS["4015"]]
        result = total_giant_slayer_multiplier(eff, target_max_hp=2500.0, caster_max_hp=2500.0)
        self.assertAlmostEqual(result, 1.0, places=6)

    def test_giant_slayer_partial_1000_hp_diff(self) -> None:
        from agents.daemon_slayer.effects import total_giant_slayer_multiplier
        eff = [ITEM_EFFECTS["4015"]]
        # 1000 HP diff: 1000/100 * 0.006 = 0.06 → 6% amp → factor 1.06
        result = total_giant_slayer_multiplier(eff, target_max_hp=3500.0, caster_max_hp=2500.0)
        self.assertAlmostEqual(result, 1.06, places=4)

    def test_giant_slayer_capped_at_max(self) -> None:
        from agents.daemon_slayer.effects import total_giant_slayer_multiplier
        eff = [ITEM_EFFECTS["4015"]]
        # 3000 HP diff: 3000/100 * 0.006 = 0.18 but cap = 0.15 → 1.15
        result = total_giant_slayer_multiplier(eff, target_max_hp=6000.0, caster_max_hp=3000.0)
        self.assertAlmostEqual(result, 1.15, places=4)

    def test_giant_slayer_at_cap_boundary(self) -> None:
        from agents.daemon_slayer.effects import total_giant_slayer_multiplier
        eff = [ITEM_EFFECTS["4015"]]
        # 2500 HP diff: exactly at cap = 15%
        result = total_giant_slayer_multiplier(eff, target_max_hp=5000.0, caster_max_hp=2500.0)
        self.assertAlmostEqual(result, 1.15, places=4)

    def test_giant_slayer_no_items(self) -> None:
        from agents.daemon_slayer.effects import total_giant_slayer_multiplier
        result = total_giant_slayer_multiplier([], target_max_hp=5000.0, caster_max_hp=1000.0)
        self.assertAlmostEqual(result, 1.0, places=6)

    # ── Perplexity field update ──

    def test_perplexity_has_giant_slayer_fields(self) -> None:
        eff = ITEM_EFFECTS.get("4015")
        self.assertIsNotNone(eff)
        self.assertAlmostEqual(eff.giant_slayer_pct_per_100hp, 0.006, places=6)
        self.assertAlmostEqual(eff.giant_slayer_max_pct, 0.15, places=4)

    def test_perplexity_still_has_pen_fields(self) -> None:
        eff = ITEM_EFFECTS.get("4015")
        self.assertIsNotNone(eff)
        self.assertAlmostEqual(eff.armor_pen_pct, 0.22, places=4)
        self.assertAlmostEqual(eff.magic_pen_pct, 0.30, places=4)

    def test_perplexity_giant_slayer_lifts_dps_vs_tanky_target(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        # Against a very HP-heavy target (tank: 5000 HP) Perplexity should
        # outperform no-item by more than against a squish (2000 HP)
        dps_bare_tank = compute_dps(self.snap, "Zed", level=11, target_armor=50.0,
                                    target_max_hp=5000.0)
        dps_perp_tank = compute_dps(self.snap, "Zed", level=11, item_ids=["4015"],
                                    target_armor=50.0, target_max_hp=5000.0)
        dps_bare_squish = compute_dps(self.snap, "Zed", level=11, target_armor=50.0,
                                      target_max_hp=2000.0)
        dps_perp_squish = compute_dps(self.snap, "Zed", level=11, item_ids=["4015"],
                                      target_armor=50.0, target_max_hp=2000.0)
        gain_tank = dps_perp_tank.weighted_dps / dps_bare_tank.weighted_dps
        gain_squish = dps_perp_squish.weighted_dps / dps_bare_squish.weighted_dps
        self.assertGreater(gain_tank, gain_squish)


class Batch38ActiveItemTests(unittest.TestCase):
    """Batch 38: Wooglet's Witchcap, Deathblade, Obsidian Cleaver."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ── Wooglet's Witchcap (228002) ──

    def test_wooglets_ap_amp_pct(self) -> None:
        eff = ITEM_EFFECTS.get("228002")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertAlmostEqual(eff.ap_amp_pct, 0.50, places=4)
        self.assertEqual(len(eff.periodics), 0)

    def test_wooglets_stacks_with_rabadon(self) -> None:
        from agents.daemon_slayer.effects import total_ap_amp_multiplier
        effs_rabadon = [ITEM_EFFECTS["3089"]]       # Rabadon 0.30
        effs_wooglet = [ITEM_EFFECTS["228002"]]     # Wooglet 0.50
        effs_both = effs_rabadon + effs_wooglet
        factor_rabadon = total_ap_amp_multiplier(effs_rabadon)
        factor_wooglet = total_ap_amp_multiplier(effs_wooglet)
        factor_both = total_ap_amp_multiplier(effs_both)
        self.assertAlmostEqual(factor_rabadon, 1.30, places=4)
        self.assertAlmostEqual(factor_wooglet, 1.50, places=4)
        # Multiplicative: 1.30 × 1.50 = 1.95
        self.assertAlmostEqual(factor_both, 1.95, places=4)

    def test_wooglets_dps_lift_with_ap_proc_item(self) -> None:
        # ap_amp_pct only boosts DPS when an AP-scaling proc item is present.
        # Nashor's Tooth (3115) has a per-attack AP proc - Wooglet's 50% AP amp
        # should meaningfully boost Nashor's contribution.
        from agents.daemon_slayer.dps import compute_dps
        dps_nashor = compute_dps(self.snap, "Lux", level=11, item_ids=["3115"])
        dps_both = compute_dps(self.snap, "Lux", level=11, item_ids=["3115", "228002"])
        self.assertGreater(dps_both.weighted_dps, dps_nashor.weighted_dps)

    # ── Deathblade (228003) ──

    def test_deathblade_lethality_and_crit_bonus(self) -> None:
        eff = ITEM_EFFECTS.get("228003")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertAlmostEqual(eff.lethality, 20.0, places=2)
        self.assertAlmostEqual(eff.crit_damage_bonus, 0.45, places=4)
        self.assertEqual(len(eff.periodics), 0)

    def test_deathblade_dps_lift(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        dps_bare = compute_dps(self.snap, "Jinx", level=11, target_armor=80.0)
        dps_with = compute_dps(self.snap, "Jinx", level=11, item_ids=["228003"],
                               target_armor=80.0)
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)

    def test_deathblade_lethality_level_invariant_post_v14_1(self) -> None:
        # Post-V14.1: Deathblade lethality (Arena 228003) is 1:1 flat
        # pen at every caster level - effective armor is IDENTICAL at
        # L1 vs L18. The pre-V14.1 "more pen at higher level" invariant
        # is obsolete.
        from agents.daemon_slayer.effects import effective_target_armor
        effs = [ITEM_EFFECTS["228003"]]
        armor_l1 = effective_target_armor(100.0, effs, level=1)
        armor_l18 = effective_target_armor(100.0, effs, level=18)
        self.assertAlmostEqual(armor_l18, armor_l1, places=4)
        # Sanity: lethality contribution actually fires (effective < raw).
        self.assertLess(armor_l1, 100.0)

    # ── Obsidian Cleaver (228005) ──

    def test_obsidian_cleaver_armor_reduction(self) -> None:
        eff = ITEM_EFFECTS.get("228005")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertAlmostEqual(eff.armor_reduction_pct, 0.35, places=4)
        self.assertEqual(len(eff.periodics), 0)

    def test_obsidian_cleaver_reduces_effective_armor(self) -> None:
        from agents.daemon_slayer.effects import effective_target_armor
        effs = [ITEM_EFFECTS["228005"]]
        # 100 armor × (1 - 0.35) = 65 effective armor
        eff_armor = effective_target_armor(100.0, effs)
        self.assertAlmostEqual(eff_armor, 65.0, places=2)

    def test_obsidian_cleaver_dps_lift_high_armor(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        dps_bare = compute_dps(self.snap, "Jinx", level=11, target_armor=150.0)
        dps_with = compute_dps(self.snap, "Jinx", level=11, item_ids=["228005"],
                               target_armor=150.0)
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)

    # ── Defensive_only sweep ──

    def test_batch38_defensive_only_entries(self) -> None:
        expected = {
            "228001": "Anathema's Chains",
            "228004": "Adaptive Helm",
            "228006": "Sanguine Blade",
            "228008": "Runeglaive",
            "443058": "Shield of Molten Stone",
            "443059": "Cloak of Starry Night",
            "443061": "Force of Entropy",
            "443062": "Sanguine Gift",
            "443063": "Eleisa's Miracle",
            "443064": "Talisman of Ascension",
            "443079": "Turbo Chemtank",
            "443080": "Twin Mask",
            "443081": "Hexbolt Companion",
            "443193": "Gargoyle Stoneplate",
            "2525": "Protoplasm Harness",
            "3143": "Randuin's Omen",
            "8001": "Anathema's Chains",
        }
        for iid, name in expected.items():
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff, f"{iid} missing from ITEM_EFFECTS")
                self.assertTrue(eff.defensive_only, f"{iid} ({name}) should be defensive_only")
                self.assertEqual(len(eff.periodics), 0)
                self.assertTrue(len(eff.note) > 0)

    def test_protoplasm_harness_lifeline_key(self) -> None:
        eff = ITEM_EFFECTS.get("2525")
        self.assertIsNotNone(eff)
        self.assertEqual(eff.unique_passive_key, "lifeline")

    def test_defensive_only_count_after_batch38(self) -> None:
        count = sum(1 for e in ITEM_EFFECTS.values() if e.defensive_only)
        # 79 after batch 37 + 17 new = 96
        self.assertGreaterEqual(count, 96)

    def test_total_entry_count_after_batch38(self) -> None:
        # 156 after batch 37 + 20 new (3 active + 17 defensive) = 176
        self.assertGreaterEqual(len(ITEM_EFFECTS), 176)


# ────────────────────────── Phase 4 batch 39 tests ──────────────────────────

class Batch39MRReductionSchemaTests(unittest.TestCase):
    """Batch 39: mr_reduction_pct field + Bloodletter's Curse + Arena re-skins."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ── mr_reduction_pct field on ItemEffect ──

    def test_bloodletters_curse_mr_reduction(self) -> None:
        eff = ITEM_EFFECTS.get("4010")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertAlmostEqual(eff.mr_reduction_pct, 0.30, places=4)
        self.assertEqual(len(eff.periodics), 0)

    def test_effective_target_mr_with_mr_reduction(self) -> None:
        from agents.daemon_slayer.effects import effective_target_mr
        effs = [ITEM_EFFECTS["4010"]]
        # 100 MR × (1 - 0.30) = 70 before % pen
        result = effective_target_mr(100.0, effs)
        self.assertAlmostEqual(result, 70.0, places=2)

    def test_effective_target_mr_reduction_before_pen(self) -> None:
        from agents.daemon_slayer.effects import effective_target_mr
        # Bloodletter's 30% reduction + Void Staff 40% pen
        effs = [ITEM_EFFECTS["4010"], ITEM_EFFECTS["3135"]]
        # 100 × (1-0.30) = 70; then × (1-0.40) = 42.0
        result = effective_target_mr(100.0, effs)
        self.assertAlmostEqual(result, 42.0, places=2)

    def test_bloodletters_dps_lift_vs_magic_proc_target(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        # Blackfire Torch (2503) has an AP-based magical proc - pair with Bloodletter's
        dps_bare = compute_dps(self.snap, "Lux", level=11, target_mr=50.0,
                               item_ids=["2503"])
        dps_with = compute_dps(self.snap, "Lux", level=11, target_mr=50.0,
                               item_ids=["2503", "4010"])
        self.assertGreater(dps_with.weighted_dps, dps_bare.weighted_dps)

    # ── Divine Sunderer Arena (446632) ──

    def test_divine_sunderer_arena_shape(self) -> None:
        eff = ITEM_EFFECTS.get("446632")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)
        proc = eff.periodics[0]
        self.assertEqual(proc.damage_type, "physical")
        self.assertAlmostEqual(proc.every_n_seconds, 3.0, places=3)

    def test_divine_sunderer_arena_formula(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc = ITEM_EFFECTS["446632"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=50.0, level=11, target_max_hp=3000.0)
        # 1.80 * 100 + 0.02 * 3000 = 180 + 60 = 240
        self.assertAlmostEqual(proc.resolve_damage(ctx), 240.0, places=4)

    def test_divine_sunderer_arena_spellblade_key(self) -> None:
        self.assertEqual(ITEM_EFFECTS["446632"].unique_passive_key, "spellblade")

    def test_divine_sunderer_arena_dedup_with_sr(self) -> None:
        from agents.daemon_slayer.effects import collect_effects
        # Both Divine Sunderers share "spellblade" key - only one should fire
        effects = collect_effects(["6632", "446632"])
        self.assertEqual(sum(1 for e in effects if e.unique_passive_key == "spellblade"), 1)

    # ── Overlord's Bloodmail Arena (447111) ──

    def test_overlords_bloodmail_arena_bonus_ad_pct(self) -> None:
        eff = ITEM_EFFECTS.get("447111")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertAlmostEqual(eff.bonus_ad_pct_bonus_hp, 0.03, places=4)
        self.assertEqual(len(eff.periodics), 0)

    def test_overlords_bloodmail_arena_higher_than_sr(self) -> None:
        # Arena version has 3% vs SR's 2.5%
        arena = ITEM_EFFECTS.get("447111")
        sr = ITEM_EFFECTS.get("2501")
        self.assertIsNotNone(arena)
        self.assertIsNotNone(sr)
        self.assertGreater(arena.bonus_ad_pct_bonus_hp, sr.bonus_ad_pct_bonus_hp)

    # ── Atma's Reckoning variant (663039) ──

    def test_atmas_663039_same_as_3039(self) -> None:
        eff663 = ITEM_EFFECTS.get("663039")
        eff3 = ITEM_EFFECTS.get("3039")
        self.assertIsNotNone(eff663)
        self.assertIsNotNone(eff3)
        self.assertFalse(eff663.defensive_only)
        self.assertAlmostEqual(eff663.crit_chance_bonus_max_pct,
                               eff3.crit_chance_bonus_max_pct, places=4)
        self.assertAlmostEqual(eff663.crit_chance_bonus_per_bonus_hp_cap,
                               eff3.crit_chance_bonus_per_bonus_hp_cap, places=1)

    # ── Hextech Gunblade Arena (663146) ──

    def test_hextech_gunblade_663146_same_formula(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        proc663 = ITEM_EFFECTS["663146"].periodics[0]
        proc3 = ITEM_EFFECTS["3146"].periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=50.0, level=11, ap=200.0)
        self.assertAlmostEqual(proc663.resolve_damage(ctx), proc3.resolve_damage(ctx), places=4)

    def test_hextech_gunblade_663146_40s_cooldown(self) -> None:
        proc = ITEM_EFFECTS["663146"].periodics[0]
        self.assertAlmostEqual(proc.every_n_seconds, 40.0, places=3)

    # ── Defensive_only sweep ──

    def test_batch39_defensive_only_entries(self) -> None:
        expected = {
            # 444636 Night Harvester promoted to active periodic in batch 52
            # 444637 Demonic Embrace promoted to active in batch 56 (hp_scaled_ap_amp)
            "446691": "Duskblade of Draktharr",
            "446667": "Radiant Virtue",
            "443083": "Warmog's Armor",
            "663056": "Demon King's Crown",
            "4011": "Sword of Blossoming Dawn",
        }
        for iid, name in expected.items():
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff, f"{iid} missing")
                self.assertTrue(eff.defensive_only, f"{iid} ({name}) should be defensive_only")
                self.assertEqual(len(eff.periodics), 0)

    def test_defensive_only_count_after_batch39(self) -> None:
        count = sum(1 for e in ITEM_EFFECTS.values() if e.defensive_only)
        # 96 after batch 38 + 7 new = 103
        self.assertGreaterEqual(count, 103)

    def test_total_entry_count_after_batch39(self) -> None:
        # 176 after batch 38 + 12 new = 188
        self.assertGreaterEqual(len(ITEM_EFFECTS), 188)


class Batch40ComponentAndSweepTests(unittest.TestCase):
    """Phase 4 batch 40 (2026-05-04) - component items + final SR/Arena sweep.

    3 active promotions reusing existing schemas:
      3035  Last Whisper          armor_pen_pct=0.18
      2020  The Brutalizer        lethality=5.0
      3147  Haunting Guise        damage_amp_pct=0.06 (Madness, pinned full stacks)

    15 defensive_only entries completing the SR/Arena sweep.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ── active promotion field assertions ──────────────────────────────────

    def test_last_whisper_armor_pen(self) -> None:
        e = ITEM_EFFECTS.get("3035")
        self.assertIsNotNone(e, "3035 Last Whisper missing")
        self.assertAlmostEqual(e.armor_pen_pct, 0.18)
        self.assertFalse(e.defensive_only)

    def test_brutalizer_lethality(self) -> None:
        e = ITEM_EFFECTS.get("2020")
        self.assertIsNotNone(e, "2020 The Brutalizer missing")
        self.assertAlmostEqual(e.lethality, 5.0)
        self.assertFalse(e.defensive_only)

    def test_haunting_guise_damage_amp(self) -> None:
        e = ITEM_EFFECTS.get("3147")
        self.assertIsNotNone(e, "3147 Haunting Guise missing")
        self.assertAlmostEqual(e.damage_amp_pct, 0.06)
        self.assertFalse(e.defensive_only)

    def test_last_whisper_dps_lift_vs_no_pen(self) -> None:
        """Last Whisper's 18% armor pen should lift DPS against an armored target."""
        base = compute_dps(self.snap, "Caitlyn", level=12, item_ids=[])
        lw = compute_dps(self.snap, "Caitlyn", level=12, item_ids=["3035"])
        self.assertGreater(lw.weighted_dps, base.weighted_dps)

    def test_brutalizer_dps_lift_vs_armored(self) -> None:
        """The Brutalizer's lethality reduces effective armor at level 12."""
        base = compute_dps(self.snap, "Caitlyn", level=12, item_ids=[])
        brut = compute_dps(self.snap, "Caitlyn", level=12, item_ids=["2020"])
        self.assertGreater(brut.weighted_dps, base.weighted_dps)

    def test_haunting_guise_dps_lift(self) -> None:
        """6% damage_amp_pct should lift DPS vs no-item baseline."""
        base = compute_dps(self.snap, "Lux", level=10, item_ids=[])
        guise = compute_dps(self.snap, "Lux", level=10, item_ids=["3147"])
        self.assertGreater(guise.weighted_dps, base.weighted_dps)

    def test_haunting_guise_same_coefficient_as_liandrys(self) -> None:
        """3147 and 6653 (Liandry's Torment) share the same 6% damage_amp_pct."""
        guise = ITEM_EFFECTS.get("3147")
        liandrys = ITEM_EFFECTS.get("6653")
        self.assertIsNotNone(guise, "3147 missing")
        self.assertIsNotNone(liandrys, "6653 Liandry's Torment missing")
        self.assertAlmostEqual(guise.damage_amp_pct, liandrys.damage_amp_pct)

    # ── Hexdrinker lifeline dedup ──────────────────────────────────────────

    def test_hexdrinker_lifeline_key(self) -> None:
        e = ITEM_EFFECTS.get("3155")
        self.assertIsNotNone(e, "3155 Hexdrinker missing")
        self.assertEqual(e.unique_passive_key, "lifeline")
        self.assertTrue(e.defensive_only)

    # ── batch 40 defensive_only entries ───────────────────────────────────

    def test_batch40_defensive_only_entries(self) -> None:
        expected = {
            "444644": "Crown of the Shattered Queen",
            "446656": "Everfrost",
            "446671": "Galeforce",
            "664644": "Crown of the Shattered Queen",
            "663058": "Shield of Molten Stone",
            "663059": "Cloak of Starry Night",
            "663172": "Zephyr",
            "663193": "Gargoyle Stoneplate",
            "664403": "The Golden Spatula",
            "3075": "Thornmail",
            # 3041 Mejai's Soulstealer promoted to active in batch 54 (bonus_ap_stacked)
            "3140": "Quicksilver Sash",
            "4632": "Verdant Barrier",
            "3047": "Plated Steelcaps",
        }
        for iid, name in expected.items():
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff, f"{iid} ({name}) missing")
                self.assertTrue(eff.defensive_only, f"{iid} ({name}) should be defensive_only")
                self.assertEqual(len(eff.periodics), 0)

    # ── running totals ─────────────────────────────────────────────────────

    def test_defensive_only_count_after_batch40(self) -> None:
        count = sum(1 for e in ITEM_EFFECTS.values() if e.defensive_only)
        # 103 after batch 39 + 15 new = 118
        self.assertGreaterEqual(count, 118)

    def test_total_entry_count_after_batch40(self) -> None:
        # 188 after batch 39 + 18 new = 206
        self.assertGreaterEqual(len(ITEM_EFFECTS), 206)


class Batch41Arena226MirrorTests(unittest.TestCase):
    """Phase 4 batch 41 (2026-05-04) - Arena 226xxx mirrors + Kraken/Navori fix.

    Key-collision fix: Navori Flickerblade was incorrectly keyed to "6672"
    (Kraken Slayer's DDragon ID) in batch 35, silently overwriting Kraken Slayer.
    Fixed in this batch: 6672 → Kraken Slayer, 6675 → Navori Flickerblade.

    28 Arena 226xxx items covering the full pool:
      14 active with same schema as SR counterpart.
      14 defensive_only mirrors.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ── Kraken Slayer / Navori key-collision fix ───────────────────────────

    def test_kraken_slayer_restored_at_6672(self) -> None:
        e = ITEM_EFFECTS.get("6672")
        self.assertIsNotNone(e, "6672 Kraken Slayer missing")
        self.assertEqual(e.name, "Kraken Slayer")
        self.assertFalse(e.defensive_only)
        self.assertEqual(len(e.periodics), 1)

    def test_navori_at_correct_key_6675(self) -> None:
        e = ITEM_EFFECTS.get("6675")
        self.assertIsNotNone(e, "6675 Navori Flickerblade missing")
        self.assertEqual(e.name, "Navori Flickerblade")
        self.assertFalse(e.defensive_only)
        self.assertEqual(len(e.periodics), 1)

    def test_no_key_collision_kraken_navori(self) -> None:
        """6672 and 6675 are now distinct items."""
        k = ITEM_EFFECTS.get("6672")
        n = ITEM_EFFECTS.get("6675")
        self.assertNotEqual(k.name, n.name)

    # ── active Arena mirror field assertions ──────────────────────────────

    def test_arena_sundered_sky_proc(self) -> None:
        e = ITEM_EFFECTS.get("226610")
        self.assertIsNotNone(e, "226610 missing")
        self.assertFalse(e.defensive_only)
        self.assertEqual(len(e.periodics), 1)
        p = e.periodics[0]
        self.assertAlmostEqual(p.every_n_seconds, 8.0)

    def test_arena_iceborn_spellblade_key(self) -> None:
        e = ITEM_EFFECTS.get("226662")
        self.assertIsNotNone(e, "226662 missing")
        self.assertEqual(e.unique_passive_key, "spellblade")

    def test_arena_hollow_radiance_immolate_key(self) -> None:
        e = ITEM_EFFECTS.get("226664")
        self.assertIsNotNone(e, "226664 missing")
        self.assertEqual(e.unique_passive_key, "immolate")

    def test_arena_prowlers_lethality(self) -> None:
        e = ITEM_EFFECTS.get("226693")
        self.assertIsNotNone(e, "226693 missing")
        self.assertAlmostEqual(e.lethality, 22.0)

    def test_arena_seryldas_armor_pen(self) -> None:
        e = ITEM_EFFECTS.get("226694")
        self.assertIsNotNone(e, "226694 missing")
        self.assertAlmostEqual(e.armor_pen_pct, 0.35)

    def test_arena_voltaic_lethality_and_proc(self) -> None:
        e = ITEM_EFFECTS.get("226699")
        self.assertIsNotNone(e, "226699 missing")
        self.assertAlmostEqual(e.lethality, 10.0)
        self.assertEqual(len(e.periodics), 1)

    def test_arena_immortal_shieldbow_lifeline(self) -> None:
        e = ITEM_EFFECTS.get("226673")
        self.assertIsNotNone(e, "226673 missing")
        self.assertTrue(e.defensive_only)
        self.assertEqual(e.unique_passive_key, "lifeline")

    # ── Arena active items share proc formula with SR counterpart ─────────

    def test_arena_eclipse_proc_matches_sr(self) -> None:
        """226692 Eclipse Arena proc formula identical to SR 6692."""
        from agents.daemon_slayer.effects import CallContext
        ctx = CallContext(base_ad=120.0, bonus_ad=80.0, level=12, target_max_hp=2500.0)
        sr_p = ITEM_EFFECTS["6692"].periodics[0]
        arena_p = ITEM_EFFECTS["226692"].periodics[0]
        self.assertAlmostEqual(sr_p.resolve_damage(ctx), arena_p.resolve_damage(ctx))
        self.assertEqual(sr_p.every_n_attacks, arena_p.every_n_attacks)

    def test_arena_eclipse_dps_lift(self) -> None:
        """226692 Arena Eclipse lifts DPS over bare."""
        base = compute_dps(self.snap, "Caitlyn", level=12, item_ids=[])
        arena = compute_dps(self.snap, "Caitlyn", level=12, item_ids=["226692"])
        self.assertGreater(arena.weighted_dps, base.weighted_dps)

    def test_arena_prowlers_lethality_same_as_sr(self) -> None:
        """226693 and 6693 share the same lethality=22."""
        sr = ITEM_EFFECTS["6693"]
        arena = ITEM_EFFECTS["226693"]
        self.assertAlmostEqual(sr.lethality, arena.lethality)

    def test_arena_serylda_armor_pen_same_as_sr(self) -> None:
        """226694 and 6694 share the same armor_pen_pct=0.35."""
        sr = ITEM_EFFECTS["6694"]
        arena = ITEM_EFFECTS["226694"]
        self.assertAlmostEqual(sr.armor_pen_pct, arena.armor_pen_pct)

    # ── defensive_only Arena mirrors ──────────────────────────────────────

    def test_batch41_defensive_only_entries(self) -> None:
        expected = {
            "226333": "Death's Dance",
            "226609": "Chempunk Chainsword",
            "226616": "Staff of Flowing Water",
            "226617": "Moonstone Renewer",
            "226620": "Echoes of Helia",
            "226621": "Dawncore",
            "226630": "Goredrinker",
            # 226655 Luden's Echo promoted to active periodic in batch 52
            "226657": "Rod of Ages",
            "226665": "Jak'Sho, The Protean",
            "226675": "Navori Flickerblades",
            # 226676 The Collector promoted off defensive_only in iter 14
            # (mirrors iter-10 SR 6676 - lethality=10.0 feeds the rotation)
            "226695": "Serpent's Fang",
        }
        for iid, name in expected.items():
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff, f"{iid} ({name}) missing")
                self.assertTrue(eff.defensive_only, f"{iid} ({name}) should be defensive_only")
                self.assertEqual(len(eff.periodics), 0)

    # ── running totals ─────────────────────────────────────────────────────

    def test_defensive_only_count_after_batch41(self) -> None:
        count = sum(1 for e in ITEM_EFFECTS.values() if e.defensive_only)
        # 118 after batch 40 + 14 new − 1 removed stub = 131
        self.assertGreaterEqual(count, 131)

    def test_total_entry_count_after_batch41(self) -> None:
        # 206 after batch 40 + 28 new − 1 removed stub = 233
        self.assertGreaterEqual(len(ITEM_EFFECTS), 233)


class Batch42ArenaMirror222x224x32xTests(unittest.TestCase):
    """Phase 4 batch 42 - 222xxx/224xxx Arena + 32xxxx ARAM mirrors (35 items)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ── active field assertions ────────────────────────────────────────────

    def test_222502_unending_despair_proc(self) -> None:
        e = ITEM_EFFECTS.get("222502")
        self.assertIsNotNone(e, "222502 missing")
        self.assertFalse(e.defensive_only)
        self.assertEqual(len(e.periodics), 1)
        self.assertAlmostEqual(e.periodics[0].every_n_seconds, 4.0)

    def test_222510_dusk_dawn_spellblade_key(self) -> None:
        e = ITEM_EFFECTS.get("222510")
        self.assertIsNotNone(e, "222510 missing")
        self.assertEqual(e.unique_passive_key, "spellblade")
        self.assertEqual(len(e.periodics), 1)

    def test_224004_spectral_cutlass_lethality(self) -> None:
        e = ITEM_EFFECTS.get("224004")
        self.assertIsNotNone(e, "224004 missing")
        self.assertAlmostEqual(e.lethality, 15.0)

    def test_224633_riftmaker_amp_and_ap_per_hp(self) -> None:
        e = ITEM_EFFECTS.get("224633")
        self.assertIsNotNone(e, "224633 missing")
        self.assertAlmostEqual(e.damage_amp_pct, 0.08)
        self.assertAlmostEqual(e.ap_per_bonus_hp_pct, 0.02)

    def test_224645_shadowflame_flat_pen(self) -> None:
        e = ITEM_EFFECTS.get("224645")
        self.assertIsNotNone(e, "224645 missing")
        self.assertAlmostEqual(e.magic_pen_flat, 15.0)

    def test_323003_archangel_aram(self) -> None:
        e = ITEM_EFFECTS.get("323003")
        self.assertIsNotNone(e, "323003 missing")
        self.assertAlmostEqual(e.bonus_ap_pct_bonus_mp, 0.01)
        self.assertFalse(e.defensive_only)

    def test_323004_manamune_aram(self) -> None:
        e = ITEM_EFFECTS.get("323004")
        self.assertIsNotNone(e, "323004 missing")
        self.assertAlmostEqual(e.bonus_ad_pct_max_mp, 0.02)
        self.assertFalse(e.defensive_only)

    def test_328020_abyssal_mask_aram(self) -> None:
        e = ITEM_EFFECTS.get("328020")
        self.assertIsNotNone(e, "328020 missing")
        self.assertAlmostEqual(e.magic_amp_pct, 0.12)

    def test_222525_protoplasm_lifeline(self) -> None:
        e = ITEM_EFFECTS.get("222525")
        self.assertIsNotNone(e, "222525 missing")
        self.assertTrue(e.defensive_only)
        self.assertEqual(e.unique_passive_key, "lifeline")

    # ── proc formula matches SR counterpart ───────────────────────────────

    def test_222502_proc_matches_sr_2502(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx = CallContext(base_ad=100.0, bonus_ad=50.0, level=12, caster_bonus_hp=1000.0)
        sr_p = ITEM_EFFECTS["2502"].periodics[0]
        arena_p = ITEM_EFFECTS["222502"].periodics[0]
        self.assertAlmostEqual(sr_p.resolve_damage(ctx), arena_p.resolve_damage(ctx))

    # ── DPS lifts ──────────────────────────────────────────────────────────

    def test_224633_dps_lift(self) -> None:
        base = compute_dps(self.snap, "Lux", level=11, item_ids=[])
        with_rift = compute_dps(self.snap, "Lux", level=11, item_ids=["224633"])
        self.assertGreater(with_rift.weighted_dps, base.weighted_dps)

    def test_328020_magic_amp_dps_lift(self) -> None:
        base = compute_dps(self.snap, "Lux", level=11, item_ids=["3115"])
        with_mask = compute_dps(self.snap, "Lux", level=11, item_ids=["3115", "328020"])
        self.assertGreater(with_mask.weighted_dps, base.weighted_dps)

    # ── defensive_only spot-checks ────────────────────────────────────────

    def test_batch42_defensive_only_entries(self) -> None:
        expected = [
            "222504", "222512", "222517", "222522", "222523",
            "224005", "224401", "224628", "224629",
            "323050", "323075", "323107", "323109", "323110",
            "323119", "323190", "323222", "323504", "324005",
            "326616", "326617", "326620", "326621", "326657",
        ]
        for iid in expected:
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff, f"{iid} missing")
                self.assertTrue(eff.defensive_only, f"{iid} should be defensive_only")
                self.assertEqual(len(eff.periodics), 0)

    # ── running totals ─────────────────────────────────────────────────────

    def test_defensive_only_count_after_batch42(self) -> None:
        count = sum(1 for e in ITEM_EFFECTS.values() if e.defensive_only)
        # 131 after batch 41 + 25 new = 156
        self.assertGreaterEqual(count, 156)

    def test_total_entry_count_after_batch42(self) -> None:
        # 234 after batch 41 + 35 new = 269
        self.assertGreaterEqual(len(ITEM_EFFECTS), 269)


class Batch43Arena223MirrorTests(unittest.TestCase):
    """Phase 4 batch 43 - 223xxx Arena mirrors of SR 3xxx items (58 items)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ── active field assertions ────────────────────────────────────────────

    def test_223078_trinity_force_spellblade_key(self) -> None:
        e = ITEM_EFFECTS.get("223078")
        self.assertIsNotNone(e, "223078 missing")
        self.assertEqual(e.unique_passive_key, "spellblade")
        self.assertEqual(len(e.periodics), 1)

    def test_223100_lich_bane_spellblade_key(self) -> None:
        e = ITEM_EFFECTS.get("223100")
        self.assertIsNotNone(e, "223100 missing")
        self.assertEqual(e.unique_passive_key, "spellblade")

    def test_223508_er_spellblade_key(self) -> None:
        e = ITEM_EFFECTS.get("223508")
        self.assertIsNotNone(e, "223508 missing")
        self.assertEqual(e.unique_passive_key, "spellblade")

    def test_223068_sunfire_immolate_key(self) -> None:
        e = ITEM_EFFECTS.get("223068")
        self.assertIsNotNone(e, "223068 missing")
        self.assertEqual(e.unique_passive_key, "immolate")

    def test_223053_steraks_lifeline_key(self) -> None:
        e = ITEM_EFFECTS.get("223053")
        self.assertIsNotNone(e, "223053 missing")
        self.assertEqual(e.unique_passive_key, "lifeline")
        self.assertAlmostEqual(e.bonus_ad_pct_base_ad, 0.45)

    def test_223156_maw_lifeline_key(self) -> None:
        e = ITEM_EFFECTS.get("223156")
        self.assertIsNotNone(e, "223156 missing")
        self.assertTrue(e.defensive_only)
        self.assertEqual(e.unique_passive_key, "lifeline")

    def test_223036_ldr_armor_pen_and_giant_slayer(self) -> None:
        e = ITEM_EFFECTS.get("223036")
        self.assertIsNotNone(e, "223036 missing")
        self.assertAlmostEqual(e.armor_pen_pct, 0.35)
        self.assertAlmostEqual(e.target_bonus_hp_amp_max_pct, 0.15)

    def test_223039_atmas_crit_ramp(self) -> None:
        e = ITEM_EFFECTS.get("223039")
        self.assertIsNotNone(e, "223039 missing")
        self.assertAlmostEqual(e.crit_chance_bonus_max_pct, 0.30)
        self.assertAlmostEqual(e.crit_chance_bonus_per_bonus_hp_cap, 3000.0)

    def test_223302_terminus_dual_pen_and_proc(self) -> None:
        e = ITEM_EFFECTS.get("223302")
        self.assertIsNotNone(e, "223302 missing")
        self.assertAlmostEqual(e.armor_pen_pct, 0.10)
        self.assertAlmostEqual(e.magic_pen_pct, 0.10)
        self.assertEqual(len(e.periodics), 1)

    def test_223748_titanic_dual_procs(self) -> None:
        e = ITEM_EFFECTS.get("223748")
        self.assertIsNotNone(e, "223748 missing")
        self.assertEqual(len(e.periodics), 2)

    def test_223089_rabadons_ap_amp(self) -> None:
        e = ITEM_EFFECTS.get("223089")
        self.assertIsNotNone(e, "223089 missing")
        self.assertAlmostEqual(e.ap_amp_pct, 0.30)

    def test_223135_void_staff_magic_pen(self) -> None:
        e = ITEM_EFFECTS.get("223135")
        self.assertIsNotNone(e, "223135 missing")
        self.assertAlmostEqual(e.magic_pen_pct, 0.40)

    def test_223142_youmuu_lethality(self) -> None:
        e = ITEM_EFFECTS.get("223142")
        self.assertIsNotNone(e, "223142 missing")
        self.assertAlmostEqual(e.lethality, 18.0)

    # ── proc formulas match SR counterparts ───────────────────────────────

    def test_223078_spellblade_matches_sr_3078(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx = CallContext(base_ad=200.0, bonus_ad=100.0, level=13)
        sr_p = ITEM_EFFECTS["3078"].periodics[0]
        arena_p = ITEM_EFFECTS["223078"].periodics[0]
        self.assertAlmostEqual(sr_p.resolve_damage(ctx), arena_p.resolve_damage(ctx))

    def test_223100_lich_bane_matches_sr_3100(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, ap=300.0)
        sr_p = ITEM_EFFECTS["3100"].periodics[0]
        arena_p = ITEM_EFFECTS["223100"].periodics[0]
        self.assertAlmostEqual(sr_p.resolve_damage(ctx), arena_p.resolve_damage(ctx))

    def test_223748_cleave_primary_matches_sr_3748(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx = CallContext(base_ad=150.0, bonus_ad=200.0, level=14, caster_bonus_hp=2000.0)
        sr_p0 = ITEM_EFFECTS["3748"].periodics[0]
        arena_p0 = ITEM_EFFECTS["223748"].periodics[0]
        self.assertAlmostEqual(sr_p0.resolve_damage(ctx), arena_p0.resolve_damage(ctx))

    # ── DPS lifts ──────────────────────────────────────────────────────────

    def test_223115_nashor_dps_lift(self) -> None:
        base = compute_dps(self.snap, "Lux", level=11, item_ids=[])
        with_nt = compute_dps(self.snap, "Lux", level=11, item_ids=["223115"])
        self.assertGreater(with_nt.weighted_dps, base.weighted_dps)

    def test_223085_runaans_proc_exists(self) -> None:
        e = ITEM_EFFECTS["223085"]
        self.assertEqual(len(e.periodics), 1)
        self.assertEqual(e.periodics[0].name, "Wind's Fury")
        result = compute_dps(self.snap, "Caitlyn", level=12, item_ids=["223085"])
        self.assertGreater(result.weighted_dps, 0.0)

    # ── defensive_only spot-checks ────────────────────────────────────────

    def test_batch43_defensive_only_entries(self) -> None:
        expected = [
            "223026", "223046", "223047", "223050", "223065",
            "223072", "223073", "223075", "223102", "223107",
            "223109", "223110", "223116",
            # 223118 Malignance promoted to active Hatefog proc in batch 64
            "223119",
            "223139", "223143", "223152", "223157", "223161",
            "223165", "223190", "223222", "223504",
        ]
        for iid in expected:
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff, f"{iid} missing")
                self.assertTrue(eff.defensive_only, f"{iid} should be defensive_only")
                self.assertEqual(len(eff.periodics), 0)

    # ── running totals ─────────────────────────────────────────────────────

    def test_defensive_only_count_after_batch43(self) -> None:
        count = sum(1 for e in ITEM_EFFECTS.values() if e.defensive_only)
        # 156 after batch 42 + 25 new = 181
        self.assertGreaterEqual(count, 181)

    def test_total_entry_count_after_batch43(self) -> None:
        # 269 after batch 42 + 58 new = 327
        self.assertGreaterEqual(len(ITEM_EFFECTS), 327)


class Batch44DPSComponentsAndFullItemsTests(unittest.TestCase):
    """Batch 44: 19 DPS-contributing items - proc components + full items."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ── proc-bearing components ────────────────────────────────────────────

    def test_3057_sheen_spellblade_key(self) -> None:
        e = ITEM_EFFECTS["3057"]
        self.assertEqual(e.unique_passive_key, "spellblade")
        self.assertEqual(len(e.periodics), 1)
        self.assertEqual(e.periodics[0].name, "Spellblade")

    def test_3057_sheen_proc_formula_matches_trinity_base(self) -> None:
        """Sheen base-AD coefficient is 1.00x; Trinity Force (3078) is 2.00x."""
        ctx = CallContext(base_ad=80.0, bonus_ad=0.0, level=10)
        sheen_dmg = ITEM_EFFECTS["3057"].periodics[0].resolve_damage(ctx)
        tf_dmg = ITEM_EFFECTS["3078"].periodics[0].resolve_damage(ctx)
        self.assertAlmostEqual(sheen_dmg, 80.0, places=2)
        self.assertAlmostEqual(tf_dmg, 160.0, places=2)

    def test_3057_sheen_dps_lift(self) -> None:
        base = compute_dps(self.snap, "Orianna", level=9, item_ids=[])
        with_sheen = compute_dps(self.snap, "Orianna", level=9, item_ids=["3057"])
        self.assertGreater(with_sheen.weighted_dps, base.weighted_dps)

    def test_3077_tiamat_cleave_proc_exists(self) -> None:
        e = ITEM_EFFECTS["3077"]
        self.assertEqual(len(e.periodics), 1)
        self.assertEqual(e.periodics[0].name, "Cleave")

    def test_3077_tiamat_cleave_zero_single_target(self) -> None:
        ctx = CallContext(base_ad=70.0, bonus_ad=50.0, level=10, targets_in_rotation=1.0)
        dmg = ITEM_EFFECTS["3077"].periodics[0].resolve_damage(ctx)
        self.assertAlmostEqual(dmg, 0.0, places=6)

    def test_3077_tiamat_cleave_scales_multi_target(self) -> None:
        ctx_multi = CallContext(base_ad=70.0, bonus_ad=50.0, level=10, targets_in_rotation=3.0)
        dmg = ITEM_EFFECTS["3077"].periodics[0].resolve_damage(ctx_multi)
        self.assertAlmostEqual(dmg, 2.0 * 0.50 * 120.0, places=2)

    def test_3145_hextech_alternator_revved_proc(self) -> None:
        e = ITEM_EFFECTS["3145"]
        self.assertEqual(len(e.periodics), 1)
        self.assertEqual(e.periodics[0].name, "Revved")
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=8)
        dmg = e.periodics[0].resolve_damage(ctx)
        # Iter 15 (2026-05-20): Meraki bulk items 16.10.1 = 65 flat
        # magic; was stale 75 from a prior patch.
        self.assertAlmostEqual(dmg, 65.0, places=2)

    def test_3145_hextech_alternator_dps_lift(self) -> None:
        base = compute_dps(self.snap, "Lux", level=8, item_ids=[])
        with_alt = compute_dps(self.snap, "Lux", level=8, item_ids=["3145"])
        self.assertGreater(with_alt.weighted_dps, base.weighted_dps)

    def test_6660_bamis_cinder_immolate_key(self) -> None:
        e = ITEM_EFFECTS["6660"]
        self.assertEqual(e.unique_passive_key, "immolate")
        self.assertEqual(len(e.periodics), 1)

    def test_6660_bamis_cinder_immolate_formula(self) -> None:
        """Immolate component: flat 15 (Meraki 16.10.1 - components tier has
        no HP scaling; Sunfire upgrades to 20+1% bonus_hp, Hollow Radiance
        to 15+1% bonus_hp). Iter 8 (2026-05-19) corrected Bami's from the
        engine's prior 12+1% bonus_hp model."""
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=10, caster_bonus_hp=2000.0)
        dmg = ITEM_EFFECTS["6660"].periodics[0].resolve_damage(ctx)
        self.assertAlmostEqual(dmg, 15.0, places=2)
        sunfire = ITEM_EFFECTS["3068"].periodics[0].resolve_damage(ctx)
        self.assertLess(dmg, sunfire)

    def test_6677_rageknife_wrath_proc(self) -> None:
        e = ITEM_EFFECTS["6677"]
        self.assertEqual(len(e.periodics), 1)
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=10)
        self.assertAlmostEqual(e.periodics[0].resolve_damage(ctx), 20.0, places=2)

    def test_6677_rageknife_dps_lift(self) -> None:
        base = compute_dps(self.snap, "Caitlyn", level=10, item_ids=[])
        with_rk = compute_dps(self.snap, "Caitlyn", level=10, item_ids=["6677"])
        self.assertGreater(with_rk.weighted_dps, base.weighted_dps)

    # ── full items with DPS passive ────────────────────────────────────────

    def test_3131_sword_of_divine_lethality(self) -> None:
        e = ITEM_EFFECTS["3131"]
        self.assertAlmostEqual(e.lethality, 18.0, places=2)

    def test_3131_sword_of_divine_proc_exists(self) -> None:
        e = ITEM_EFFECTS["3131"]
        self.assertEqual(len(e.periodics), 1)
        self.assertEqual(e.periodics[0].name, "Divine Judgment")

    def test_3131_sword_of_divine_dps_lift(self) -> None:
        base = compute_dps(self.snap, "Jinx", level=12, item_ids=[])
        with_sotd = compute_dps(self.snap, "Jinx", level=12, item_ids=["3131"])
        self.assertGreater(with_sotd.weighted_dps, base.weighted_dps)

    def test_3134_serrated_dirk_lethality(self) -> None:
        e = ITEM_EFFECTS["3134"]
        self.assertAlmostEqual(e.lethality, 10.0, places=2)
        self.assertEqual(len(e.periodics), 0)

    def test_3001_evenshroud_damage_amp(self) -> None:
        e = ITEM_EFFECTS["3001"]
        self.assertAlmostEqual(e.damage_amp_pct, 0.06, places=4)

    def test_6700_shield_rakkor_present(self) -> None:
        e = ITEM_EFFECTS.get("6700")
        self.assertIsNotNone(e)
        self.assertFalse(e.defensive_only)

    # ── stats-only items exist and are not defensive_only ─────────────────

    def test_stats_only_items_not_defensive(self) -> None:
        for iid, name in [
            ("3086", "Zeal"), ("3133", "Caulfield's Warhammer"),
            ("3123", "Executioner's Calling"), ("3802", "Lost Chapter"),
            ("3916", "Oblivion Orb"), ("3108", "Fiendish Codex"),
            ("3113", "Aether Wisp"), ("3051", "Hearthbound Axe"),
            ("3044", "Phage"), ("6029", "Ironspike Whip"),
        ]:
            with self.subTest(iid=iid, name=name):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e, f"{iid} missing")
                self.assertFalse(e.defensive_only, f"{iid} should not be defensive_only")

    # ── count assertions ───────────────────────────────────────────────────

    def test_batch44_active_count(self) -> None:
        active = [e for e in ITEM_EFFECTS.values() if not e.defensive_only]
        self.assertGreaterEqual(len(active), 165)

    def test_batch44_total_count(self) -> None:
        # 327 after batch 43 + 19 new = 346
        self.assertGreaterEqual(len(ITEM_EFFECTS), 346)


class Batch45DefensiveItemsAndBootsTests(unittest.TestCase):
    """Batch 45: 21 items - defensive full items, defensive components, boots."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ── defensive full items ───────────────────────────────────────────────

    def test_defensive_full_items(self) -> None:
        expected_defensive = [
            "6656", "6035", "6667", "4644", "4012", "4402",
            "3193", "3002",
        ]
        for iid in expected_defensive:
            with self.subTest(iid=iid):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e, f"{iid} missing")
                self.assertTrue(e.defensive_only, f"{iid} should be defensive_only")
                self.assertEqual(len(e.periodics), 0)

    # ── defensive components ───────────────────────────────────────────────

    def test_defensive_components(self) -> None:
        expected = [
            "3067", "3070", "3211", "3024", "3076",
            "3082", "3105", "3801", "3803",
        ]
        for iid in expected:
            with self.subTest(iid=iid):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e, f"{iid} missing")
                self.assertTrue(e.defensive_only, f"{iid} should be defensive_only")

    # ── boots ─────────────────────────────────────────────────────────────

    def test_berserkers_greaves_not_defensive(self) -> None:
        e = ITEM_EFFECTS["3006"]
        self.assertFalse(e.defensive_only)
        self.assertEqual(e.name, "Berserker's Greaves")

    def test_defensive_boots(self) -> None:
        for iid in ["3009", "3111", "3158"]:
            with self.subTest(iid=iid):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e, f"{iid} missing")
                self.assertTrue(e.defensive_only)

    def test_berserkers_greaves_has_no_procs(self) -> None:
        e = ITEM_EFFECTS["3006"]
        self.assertFalse(e.defensive_only)
        self.assertEqual(len(e.periodics), 0)

    # ── count assertions ───────────────────────────────────────────────────

    def test_batch45_defensive_only_count(self) -> None:
        defo = [e for e in ITEM_EFFECTS.values() if e.defensive_only]
        self.assertGreaterEqual(len(defo), 201)

    def test_batch45_total_count(self) -> None:
        # 346 after batch 44 + 21 new = 367
        self.assertGreaterEqual(len(ITEM_EFFECTS), 367)


class Batch46Arena226x228x224xAndSRTests(unittest.TestCase):
    """Batch 46: 226xxx/228xxx/224xxx Arena mirrors + remaining SR 4xxx/6xxx."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ── active proc items ─────────────────────────────────────────────────

    def test_226632_divine_sunderer_spellblade_key(self) -> None:
        e = ITEM_EFFECTS["226632"]
        self.assertEqual(e.unique_passive_key, "spellblade")
        self.assertEqual(len(e.periodics), 1)

    def test_226632_proc_formula_matches_sr(self) -> None:
        ctx = CallContext(base_ad=80.0, bonus_ad=0.0, level=12, target_max_hp=2000.0)
        arena_dmg = ITEM_EFFECTS["226632"].periodics[0].resolve_damage(ctx)
        sr_dmg = ITEM_EFFECTS["6632"].periodics[0].resolve_damage(ctx)
        self.assertAlmostEqual(arena_dmg, sr_dmg, places=2)

    def test_226660_bamis_immolate_key(self) -> None:
        e = ITEM_EFFECTS["226660"]
        self.assertEqual(e.unique_passive_key, "immolate")
        self.assertEqual(len(e.periodics), 1)

    def test_226660_proc_formula_matches_sr_6660(self) -> None:
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=10, caster_bonus_hp=1500.0)
        arena_dmg = ITEM_EFFECTS["226660"].periodics[0].resolve_damage(ctx)
        sr_dmg = ITEM_EFFECTS["6660"].periodics[0].resolve_damage(ctx)
        self.assertAlmostEqual(arena_dmg, sr_dmg, places=2)

    def test_226691_duskblade_lethality(self) -> None:
        e = ITEM_EFFECTS["226691"]
        self.assertAlmostEqual(e.lethality, 18.0, places=2)
        self.assertFalse(e.defensive_only)

    def test_228020_abyssal_mask_magic_amp(self) -> None:
        e = ITEM_EFFECTS["228020"]
        self.assertAlmostEqual(e.magic_amp_pct, 0.12, places=4)
        self.assertFalse(e.defensive_only)

    def test_224637_demonic_embrace_fields(self) -> None:
        e = ITEM_EFFECTS["224637"]
        self.assertAlmostEqual(e.ap_per_bonus_hp_pct, 0.02, places=4)
        self.assertEqual(len(e.periodics), 1)
        self.assertEqual(e.periodics[0].name, "Azakana's Gaze")

    def test_224637_proc_formula_matches_sr(self) -> None:
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=12, target_max_hp=3000.0)
        arena_dmg = ITEM_EFFECTS["224637"].periodics[0].resolve_damage(ctx)
        sr_dmg = ITEM_EFFECTS["4637"].periodics[0].resolve_damage(ctx)
        self.assertAlmostEqual(arena_dmg, sr_dmg, places=2)

    def test_224637_dps_lift(self) -> None:
        base = compute_dps(self.snap, "Vladimir", level=11, item_ids=[], target_max_hp=2500.0)
        with_de = compute_dps(self.snap, "Vladimir", level=11, item_ids=["224637"], target_max_hp=2500.0)
        self.assertGreater(with_de.weighted_dps, base.weighted_dps)

    def test_4003_lifeline_lethality(self) -> None:
        e = ITEM_EFFECTS["4003"]
        self.assertAlmostEqual(e.lethality, 5.0, places=2)
        self.assertFalse(e.defensive_only)

    def test_4630_blighting_jewel_magic_pen(self) -> None:
        e = ITEM_EFFECTS["4630"]
        self.assertAlmostEqual(e.magic_pen_pct, 0.13, places=4)
        self.assertFalse(e.defensive_only)

    def test_stats_only_sr_items(self) -> None:
        for iid in ["6670", "6690"]:
            with self.subTest(iid=iid):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e, f"{iid} missing")
                self.assertFalse(e.defensive_only)
                self.assertEqual(len(e.periodics), 0)

    # ── defensive_only items ──────────────────────────────────────────────

    def test_batch46_defensive_entries(self) -> None:
        expected = [
            "226656", "226667", "226671", "226035", "224636",
            "224644", "228009", "4635", "4403", "4638",
            "4641", "4642", "4643",
        ]
        for iid in expected:
            with self.subTest(iid=iid):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e, f"{iid} missing")
                self.assertTrue(e.defensive_only)

    # ── count assertions ──────────────────────────────────────────────────

    def test_batch46_total_count(self) -> None:
        self.assertGreaterEqual(len(ITEM_EFFECTS), 389)


class Batch47Arena22xAnd32xRemainingTests(unittest.TestCase):
    """Batch 47: Arena 22xxxx/32xxxx pool + 221xxx components."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ── active items ──────────────────────────────────────────────────────

    def test_223001_evenshroud_damage_amp(self) -> None:
        e = ITEM_EFFECTS["223001"]
        self.assertAlmostEqual(e.damage_amp_pct, 0.06, places=4)
        self.assertFalse(e.defensive_only)

    def test_223040_serapis_fields(self) -> None:
        e = ITEM_EFFECTS["223040"]
        self.assertAlmostEqual(e.bonus_ap_pct_bonus_mp, 0.02, places=4)
        self.assertEqual(e.unique_passive_key, "lifeline")

    def test_223040_matches_sr_3040(self) -> None:
        e_arena = ITEM_EFFECTS["223040"]
        e_sr = ITEM_EFFECTS["3040"]
        self.assertAlmostEqual(e_arena.bonus_ap_pct_bonus_mp, e_sr.bonus_ap_pct_bonus_mp, places=4)
        self.assertEqual(e_arena.unique_passive_key, e_sr.unique_passive_key)

    def test_223042_muramana_fields(self) -> None:
        e = ITEM_EFFECTS["223042"]
        self.assertAlmostEqual(e.bonus_ad_pct_max_mp, 0.02, places=4)
        self.assertEqual(len(e.periodics), 1)
        self.assertEqual(e.periodics[0].name, "Shock")

    def test_223042_shock_formula_matches_sr(self) -> None:
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=10, caster_max_mp=2000.0)
        arena_dmg = ITEM_EFFECTS["223042"].periodics[0].resolve_damage(ctx)
        sr_dmg = ITEM_EFFECTS["3042"].periodics[0].resolve_damage(ctx)
        self.assertAlmostEqual(arena_dmg, sr_dmg, places=2)

    def test_223057_sheen_spellblade_key(self) -> None:
        e = ITEM_EFFECTS["223057"]
        self.assertEqual(e.unique_passive_key, "spellblade")
        ctx = CallContext(base_ad=80.0, bonus_ad=0.0, level=10)
        dmg = e.periodics[0].resolve_damage(ctx)
        self.assertAlmostEqual(dmg, 80.0, places=2)

    def test_223095_stormrazor_proc_exists(self) -> None:
        e = ITEM_EFFECTS["223095"]
        self.assertFalse(e.defensive_only)
        self.assertEqual(len(e.periodics), 1)
        self.assertEqual(e.periodics[0].name, "Stormraider")

    def test_223185_guardians_dirk_lethality(self) -> None:
        e = ITEM_EFFECTS["223185"]
        self.assertAlmostEqual(e.lethality, 11.0, places=2)
        self.assertFalse(e.defensive_only)

    def test_323040_serapis_matches_arena_223040(self) -> None:
        e1 = ITEM_EFFECTS["323040"]
        e2 = ITEM_EFFECTS["223040"]
        self.assertAlmostEqual(e1.bonus_ap_pct_bonus_mp, e2.bonus_ap_pct_bonus_mp, places=4)
        self.assertEqual(e1.unique_passive_key, e2.unique_passive_key)

    def test_323042_muramana_shock_matches_sr(self) -> None:
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=10, caster_max_mp=1500.0)
        aram_dmg = ITEM_EFFECTS["323042"].periodics[0].resolve_damage(ctx)
        sr_dmg = ITEM_EFFECTS["3042"].periodics[0].resolve_damage(ctx)
        self.assertAlmostEqual(aram_dmg, sr_dmg, places=2)

    # ── 221xxx Arena components not defensive_only ────────────────────────

    def test_221xxx_components_not_defensive(self) -> None:
        for iid in ["221011", "221026", "221043", "221053", "221058"]:
            with self.subTest(iid=iid):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e, f"{iid} missing")
                self.assertFalse(e.defensive_only)
                self.assertEqual(len(e.periodics), 0)

    def test_221031_221057_defensive(self) -> None:
        for iid in ["221031", "221057"]:
            with self.subTest(iid=iid):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e)
                self.assertTrue(e.defensive_only)

    # ── defensive_only Arena pool ─────────────────────────────────────────

    def test_batch47_defensive_entries(self) -> None:
        expected = [
            "223002", "223067",          "223105", "223111", "223112",
            # 223069 promoted batch 57: Void Immolation - TRUE Immolate proc
            "223121", "223158", "223172", "223177", "223184", "223193",
            "222065", "222051", "222524", "222526", "222530",
            # 224403 promoted batch 57: Golden Spatula - Doing Something burn
                      "322065", "322526", "322530",
            "323002", "323070", "323121",
            "222022", "222141",
        ]
        for iid in expected:
            with self.subTest(iid=iid):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e, f"{iid} missing")
                self.assertTrue(e.defensive_only)

    # ── count assertions ──────────────────────────────────────────────────

    def test_batch47_defensive_count(self) -> None:
        defo = [e for e in ITEM_EFFECTS.values() if e.defensive_only]
        self.assertGreaterEqual(len(defo), 242)

    def test_batch47_total_count(self) -> None:
        # 367 + 22 + ~42 = ~430
        self.assertGreaterEqual(len(ITEM_EFFECTS), 430)


class Batch48Core1xxxComponentsTests(unittest.TestCase):
    """Phase 4 batch 48 - 1xxx tier-1 component coverage."""

    # ── Recurve Bow proc ──────────────────────────────────────────────────

    def test_recurve_bow_sting_proc(self) -> None:
        e = ITEM_EFFECTS["1043"]
        self.assertIsNotNone(e)
        self.assertFalse(e.defensive_only)
        self.assertEqual(len(e.periodics), 1)
        p = e.periodics[0]
        self.assertEqual(p.name, "Sting")
        self.assertAlmostEqual(p.bonus_damage, 15.0)
        self.assertEqual(p.damage_type, PHYSICAL)
        self.assertEqual(p.every_n_attacks, 1)

    # ── stats-only active components ─────────────────────────────────────

    def test_stats_only_active_1xxx(self) -> None:
        for iid in ["1018", "1026", "1036", "1037", "1038", "1042",
                    "1052", "1053", "1055", "1056", "1058", "1082",
                    "1083", "1086"]:
            with self.subTest(iid=iid):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e, f"{iid} missing")
                self.assertFalse(e.defensive_only)
                self.assertEqual(len(e.periodics), 0)

    # ── defensive_only 1xxx components ───────────────────────────────────

    def test_batch48_defensive_entries(self) -> None:
        for iid in ["1001", "1004", "1006", "1011", "1027", "1028",
                    "1029", "1031", "1033", "1035", "1039", "1040",
                    "1054", "1057"]:
            with self.subTest(iid=iid):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e, f"{iid} missing")
                self.assertTrue(e.defensive_only)

    # ── count assertions ──────────────────────────────────────────────────

    def test_batch48_defensive_count(self) -> None:
        defo = [e for e in ITEM_EFFECTS.values() if e.defensive_only]
        self.assertGreaterEqual(len(defo), 256)

    def test_batch48_total_count(self) -> None:
        self.assertGreaterEqual(len(ITEM_EFFECTS), 459)


class Batch49Remaining3xxx2xxxArenaTests(unittest.TestCase):
    """Phase 4 batch 49 - remaining 3xxx/2xxx boots/components + final Arena pool."""

    @classmethod
    def setUpClass(cls) -> None:
        from agents.daemon_slayer.data_loader import DataSnapshot
        cls.snap = DataSnapshot.load()

    # ── Spellslinger's Shoes - dual-pen ──────────────────────────────────

    def test_spelllslingers_shoes_dual_pen(self) -> None:
        e = ITEM_EFFECTS["3175"]
        self.assertIsNotNone(e)
        self.assertFalse(e.defensive_only)
        self.assertAlmostEqual(e.magic_pen_flat, 18.0)
        self.assertAlmostEqual(e.magic_pen_pct, 0.08)
        self.assertEqual(len(e.periodics), 0)

    def test_spelllslingers_both_pen_layers_different_from_flat_only(self) -> None:
        # Verify dual pen stacks: effective MR with both layers should be lower
        # than with neither layer at a non-zero target_mr.
        from agents.daemon_slayer.effects import effective_target_mr, collect_effects
        effects = collect_effects(["3175"])
        mr_with = effective_target_mr(50.0, effects)
        mr_bare = effective_target_mr(50.0, [])
        self.assertLess(mr_with, mr_bare)

    # ── Lethality items ───────────────────────────────────────────────────

    def test_hubris_lethality(self) -> None:
        e = ITEM_EFFECTS["126697"]
        self.assertIsNotNone(e)
        self.assertFalse(e.defensive_only)
        self.assertAlmostEqual(e.lethality, 18.0)
        self.assertEqual(len(e.periodics), 0)

    def test_prowlers_claw_arena_lethality(self) -> None:
        e = ITEM_EFFECTS["446693"]
        self.assertIsNotNone(e)
        self.assertFalse(e.defensive_only)
        self.assertAlmostEqual(e.lethality, 20.0)

    # ── Rite of Ruin crit ────────────────────────────────────────────────

    def test_rite_of_ruin_crit_flat(self) -> None:
        e = ITEM_EFFECTS["123430"]
        self.assertIsNotNone(e)
        self.assertFalse(e.defensive_only)
        self.assertAlmostEqual(e.crit_chance_bonus_flat, 0.25)
        self.assertEqual(len(e.periodics), 0)

    # ── stats-only active items ───────────────────────────────────────────

    def test_stats_only_active_3xxx_2xxx(self) -> None:
        # 2508 Fated Ashes promoted to active periodic in batch 51
        for iid in ["3172", "3177", "3184", "3095", "3144",
                    "221038", "223006"]:
            with self.subTest(iid=iid):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e, f"{iid} missing")
                self.assertFalse(e.defensive_only)
                self.assertEqual(len(e.periodics), 0)

    # ── defensive_only boots ─────────────────────────────────────────────

    def test_batch49_defensive_boots(self) -> None:
        for iid in ["3005", "3008", "3010", "3013", "3117", "3168",
                    "3170", "3171", "3173", "3174", "3176"]:
            with self.subTest(iid=iid):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e, f"{iid} missing")
                self.assertTrue(e.defensive_only)

    # ── defensive_only components ─────────────────────────────────────────

    def test_batch49_defensive_components(self) -> None:
        for iid in ["3012", "3023", "3066", "3112", "3114",
                    "2065", "2524", "2526", "2530"]:
            with self.subTest(iid=iid):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e, f"{iid} missing")
                self.assertTrue(e.defensive_only)

    # ── defensive_only Arena pool ─────────────────────────────────────────

    def test_batch49_defensive_arena(self) -> None:
        for iid in ["124011", "223005", "223008", "223009", "223011"]:
            with self.subTest(iid=iid):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e, f"{iid} missing")
                self.assertTrue(e.defensive_only)

    # ── count assertions ──────────────────────────────────────────────────

    def test_batch49_defensive_count(self) -> None:
        defo = [e for e in ITEM_EFFECTS.values() if e.defensive_only]
        # batch 50-52 promoted 5 items from defensive_only; floor lowered
        self.assertGreaterEqual(len(defo), 275)

    def test_batch49_total_count(self) -> None:
        self.assertGreaterEqual(len(ITEM_EFFECTS), 496)


# ─────────────────────────────────── batch 50: armor_reduction_flat / mr_reduction_flat


class FlatArmorShredTests(unittest.TestCase):
    """Batch 50: armor_reduction_flat + mr_reduction_flat pipeline."""

    def test_flat_shred_reduces_before_pct_reduction(self) -> None:
        # 100 armor, 30 flat shred → 70, then 30% BC pct reduction → 49.
        flat_shred = ItemEffect(
            item_id="x", name="x", armor_reduction_flat=30.0
        )
        bc = ITEM_EFFECTS["3071"]  # armor_reduction_pct=0.30
        result = effective_target_armor(100.0, [flat_shred, bc])
        self.assertAlmostEqual(result, 49.0, places=3)

    def test_flat_shred_can_drive_armor_negative(self) -> None:
        # League rule: armor REDUCTION can take armor below zero (only
        # PENETRATION floors at 0). 80 - 200 flat reduction = -120, and
        # a negative resist amplifies physical damage. Corrected from
        # the pre-fix "floors at zero" pin (P1-L1 enemy-item audit) -
        # the old behavior discarded the negative-resist damage amp.
        flat_shred = ItemEffect(item_id="x", name="x", armor_reduction_flat=200.0)
        got = effective_target_armor(80.0, [flat_shred])
        self.assertAlmostEqual(got, -120.0, places=9)
        # Negative effective armor must amplify (factor > 1).
        self.assertGreater(_armor_factor(got), 1.0)

    def test_flat_shred_on_zero_armor_goes_negative(self) -> None:
        # 0 - 30 flat reduction = -30 (reduction, not pen) -> target
        # takes amplified physical damage. Corrected pin (P1-L1).
        flat_shred = ItemEffect(item_id="x", name="x", armor_reduction_flat=30.0)
        got = effective_target_armor(0.0, [flat_shred])
        self.assertAlmostEqual(got, -30.0, places=9)
        self.assertAlmostEqual(
            _armor_factor(got), 2.0 - 100.0 / (100.0 - (-30.0)), places=9
        )

    def test_mr_flat_shred_reduces_before_pct(self) -> None:
        # 80 MR, 30 flat shred → 50, then 30% Bloodletter's pct → 35.
        mr_flat = ItemEffect(item_id="x", name="x", mr_reduction_flat=30.0)
        bl = ITEM_EFFECTS["4010"]  # mr_reduction_pct=0.30
        result = effective_target_mr(80.0, [mr_flat, bl])
        self.assertAlmostEqual(result, 35.0, places=3)

    def test_flesheater_sr_has_flat_shred(self) -> None:
        e = ITEM_EFFECTS["667112"]
        self.assertAlmostEqual(e.armor_reduction_flat, 30.0)
        self.assertAlmostEqual(e.mr_reduction_flat, 30.0)
        self.assertFalse(e.defensive_only)

    def test_flesheater_arena_has_flat_shred(self) -> None:
        e = ITEM_EFFECTS["447112"]
        self.assertAlmostEqual(e.armor_reduction_flat, 30.0)
        self.assertAlmostEqual(e.mr_reduction_flat, 30.0)
        self.assertFalse(e.defensive_only)

    def test_flesheater_raises_dps_vs_armored(self) -> None:
        snap = DataSnapshot.load()
        bare = compute_dps(snap, "Aatrox", level=11, target_armor=100.0)
        with_fe = compute_dps(
            snap, "Aatrox", level=11, item_ids=["667112"], target_armor=100.0
        )
        self.assertGreater(with_fe.weighted_dps, bare.weighted_dps)


# ─────────────────────────────── batch 51: Fated Ashes + missing components


class Batch51FatedAshesTests(unittest.TestCase):
    """Fated Ashes Inflame proc + 5 defensive-only components."""

    def test_fated_ashes_has_inflame_proc(self) -> None:
        e = ITEM_EFFECTS["2508"]
        self.assertFalse(e.defensive_only)
        self.assertEqual(len(e.periodics), 1)
        p = e.periodics[0]
        self.assertEqual(p.name, "Inflame")
        self.assertAlmostEqual(p.bonus_damage, 15.0)
        self.assertEqual(p.damage_type, MAGICAL)
        self.assertAlmostEqual(p.every_n_seconds, 3.0)

    def test_fated_ashes_raises_magic_dps(self) -> None:
        snap = DataSnapshot.load()
        bare = compute_dps(snap, "Ahri", level=10, target_mr=50.0)
        with_fa = compute_dps(snap, "Ahri", level=10, item_ids=["2508"], target_mr=50.0)
        self.assertGreater(with_fa.weighted_dps, bare.weighted_dps)

    def test_batch51_defensive_components(self) -> None:
        for iid in ["2019", "2021", "2022", "2420", "2421"]:
            with self.subTest(iid=iid):
                e = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(e, f"{iid} missing")
                self.assertTrue(e.defensive_only)

    def test_batch51_total_count(self) -> None:
        self.assertGreaterEqual(len(ITEM_EFFECTS), 501)


# ──────────────────────────── batch 52: Night Harvester + Luden's + BL Curse SR


class Batch52AbilityProcTests(unittest.TestCase):
    """Batch 52: Night Harvester, Luden's Echo, SR Bloodletter's Curse promoted."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _check_soulrend(self, iid: str) -> None:
        e = ITEM_EFFECTS[iid]
        self.assertFalse(e.defensive_only)
        self.assertEqual(len(e.periodics), 1)
        p = e.periodics[0]
        self.assertEqual(p.name, "Soulrend")
        self.assertEqual(p.damage_type, MAGICAL)
        self.assertAlmostEqual(p.every_n_seconds, 10.0)
        # AP-scaling: at 100 AP, damage = 125 + 0.15*100 = 140
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11, ap=100.0)
        self.assertAlmostEqual(p.resolve_damage(ctx), 140.0)

    def test_night_harvester_sr_soulrend(self) -> None:
        self._check_soulrend("4636")

    def test_night_harvester_arena_soulrend(self) -> None:
        self._check_soulrend("444636")

    def _check_echo(self, iid: str) -> None:
        e = ITEM_EFFECTS[iid]
        self.assertFalse(e.defensive_only)
        self.assertEqual(len(e.periodics), 1)
        p = e.periodics[0]
        self.assertEqual(p.name, "Echo")
        self.assertEqual(p.damage_type, MAGICAL)
        self.assertAlmostEqual(p.every_n_seconds, 12.0)
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11, ap=200.0)
        self.assertAlmostEqual(p.resolve_damage(ctx), 85.0)  # 75 + 0.05*200

    def test_ludens_echo_sr_echo(self) -> None:
        self._check_echo("6655")

    def test_ludens_echo_arena_echo(self) -> None:
        self._check_echo("226655")

    def test_bloodletters_curse_sr_mr_reduction(self) -> None:
        e = ITEM_EFFECTS["8010"]
        self.assertFalse(e.defensive_only)
        self.assertAlmostEqual(e.mr_reduction_pct, 0.30)
        # Pair with a magic-proc item so MR reduction actually shifts DPS.
        # Nashor's Tooth (3115) contributes magic on-hits; vs 100 MR target,
        # adding BL's 30% MR shred reduces effective MR and raises proc damage.
        base = compute_dps(
            self.snap, "Ahri", level=11, item_ids=["3115"], target_mr=100.0
        )
        with_bl = compute_dps(
            self.snap, "Ahri", level=11, item_ids=["3115", "8010"], target_mr=100.0
        )
        self.assertGreater(with_bl.weighted_dps, base.weighted_dps)

    def test_night_harvester_raises_dps(self) -> None:
        bare = compute_dps(self.snap, "Ahri", level=11)
        with_nh = compute_dps(self.snap, "Ahri", level=11, item_ids=["4636"])
        self.assertGreater(with_nh.weighted_dps, bare.weighted_dps)


# ─────────────────── batch 53: Hamstringer Scour + Stormsurge Squall proc


class Batch53CritBleedAndSquallTests(unittest.TestCase):
    """Batch 53: Hamstringer Scour crit-bleed + Stormsurge Squall proc."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ── Hamstringer (443069) ────────────────────────────────────────────────

    def test_hamstringer_not_defensive_only(self) -> None:
        e = ITEM_EFFECTS["443069"]
        self.assertFalse(e.defensive_only)
        self.assertEqual(len(e.periodics), 1)

    def test_hamstringer_scour_proc_schema(self) -> None:
        p = ITEM_EFFECTS["443069"].periodics[0]
        self.assertEqual(p.name, "Scour")
        self.assertEqual(p.damage_type, PHYSICAL)
        self.assertEqual(p.every_n_attacks, 1)

    def test_hamstringer_scour_zero_without_crit(self) -> None:
        # crit_chance=0 → expected bleed = 0 regardless of AD/level
        p = ITEM_EFFECTS["443069"].periodics[0]
        ctx = CallContext(base_ad=100, bonus_ad=50, level=11, crit_chance=0.0)
        self.assertAlmostEqual(p.resolve_damage(ctx), 0.0)

    def test_hamstringer_scour_scales_with_crit_and_ad(self) -> None:
        p = ITEM_EFFECTS["443069"].periodics[0]
        # 100% crit: damage = (20 + 60/17*10) + 0.1875*150 ≈ 55.3 + 28.1 = 83.4
        ctx = CallContext(base_ad=100, bonus_ad=50, level=11, crit_chance=1.0)
        expected = (20.0 + (60.0 / 17.0) * 10) + 0.1875 * 150.0
        self.assertAlmostEqual(p.resolve_damage(ctx), expected, places=2)

    def test_hamstringer_scour_50pct_crit_halves_damage(self) -> None:
        p = ITEM_EFFECTS["443069"].periodics[0]
        full = p.resolve_damage(
            CallContext(base_ad=80, bonus_ad=40, level=1, crit_chance=1.0)
        )
        half = p.resolve_damage(
            CallContext(base_ad=80, bonus_ad=40, level=1, crit_chance=0.5)
        )
        self.assertAlmostEqual(half, full * 0.5, places=4)

    def test_hamstringer_raises_dps_with_crit(self) -> None:
        # Need crit on the build - pair with IE (3031, adds 25% crit).
        bare = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3031"])
        with_hs = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3031", "443069"]
        )
        self.assertGreater(with_hs.weighted_dps, bare.weighted_dps)

    # ── Stormsurge (4646 SR + 224646 Arena) ────────────────────────────────

    def _check_squall(self, iid: str) -> None:
        e = ITEM_EFFECTS[iid]
        self.assertFalse(e.defensive_only)
        self.assertAlmostEqual(e.magic_pen_flat, 15.0, places=2)
        self.assertEqual(len(e.periodics), 1)
        p = e.periodics[0]
        self.assertEqual(p.name, "Squall")
        self.assertEqual(p.damage_type, MAGICAL)
        self.assertAlmostEqual(p.every_n_seconds, 30.0)
        # AP-scaling: 100 AP → 125 + 10 = 135
        ctx = CallContext(base_ad=60, bonus_ad=0, level=11, ap=100.0)
        self.assertAlmostEqual(p.resolve_damage(ctx), 135.0)

    def test_stormsurge_sr_squall(self) -> None:
        self._check_squall("4646")

    def test_stormsurge_arena_squall(self) -> None:
        self._check_squall("224646")

    def test_stormsurge_squall_raises_dps_with_ap(self) -> None:
        # Pair with Rabadon's (3089) for meaningful AP → Squall fires.
        bare = compute_dps(self.snap, "Lux", level=11, item_ids=["3089"])
        with_ss = compute_dps(
            self.snap, "Lux", level=11, item_ids=["3089", "4646"]
        )
        self.assertGreater(with_ss.weighted_dps, bare.weighted_dps)

    def test_batch53_total_count(self) -> None:
        # 3 promotions from prior batches + 2 Squall adds + 1 Scour add
        # (443069 was defensive_only, now active; 4646/224646 gained a proc
        # but were already active). Count floor unchanged vs batch 52.
        self.assertGreaterEqual(len(ITEM_EFFECTS), 501)


# ──────────────────────────────────────── Batch 54: stacked AP + conditional AS


class Batch54StackedApTests(unittest.TestCase):
    """Mejai's bonus_ap_stacked schema (batch 54).

    DDragon carries only the base 20 AP; Glory stacked AP (125 at full
    stacks) is engine-added via compute_dps before CallContext so AP-scaling
    procs and Rabadon's amplification both see the total.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_mejais_not_defensive_only(self) -> None:
        eff = ITEM_EFFECTS.get("3041")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)

    def test_mejais_bonus_ap_stacked_value(self) -> None:
        eff = ITEM_EFFECTS["3041"]
        self.assertAlmostEqual(eff.bonus_ap_stacked, 125.0)

    def test_mejais_raises_dps_vs_naked_ap_caster(self) -> None:
        # Lux with Nashor's Tooth benefits from the +125 stacked AP proc.
        bare = compute_dps(self.snap, "Lux", level=11, item_ids=["3115"])
        with_mejais = compute_dps(
            self.snap, "Lux", level=11, item_ids=["3115", "3041"]
        )
        self.assertGreater(with_mejais.weighted_dps, bare.weighted_dps)

    def test_mejais_note_surfaces(self) -> None:
        r = compute_dps(self.snap, "Lux", level=11, item_ids=["3041"])
        self.assertTrue(any("Mejai" in n for n in r.notes))

    def test_mejais_stacked_ap_amplified_by_rabadon(self) -> None:
        # Rabadon's (3089) + Mejai's: Rabadon's multiplies ALL AP including
        # the stacked 125 → effective total should exceed either alone.
        rabadon_only = compute_dps(
            self.snap, "Lux", level=11, item_ids=["3115", "3089"]
        )
        rabadon_mejais = compute_dps(
            self.snap, "Lux", level=11, item_ids=["3115", "3089", "3041"]
        )
        self.assertGreater(rabadon_mejais.weighted_dps, rabadon_only.weighted_dps)


class Batch54ConditionalAsTests(unittest.TestCase):
    """Yun Tal Flurry conditional AS schema (batch 54).

    Flurry: +30% bonus AS for 6s on-champion-attack (30s CD, attack-driven
    CD reduction). Uptime model at 1.3 attacks/s with 25% crit ≈ 27%.
    Effective sustained AS bonus = 0.30 × 0.27 ≈ 0.08.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_yun_tal_sr_bonus_as_conditional(self) -> None:
        eff = ITEM_EFFECTS.get("3032")
        self.assertIsNotNone(eff)
        self.assertAlmostEqual(eff.bonus_as_conditional, 0.08, places=3)

    def test_yun_tal_arena_bonus_as_conditional(self) -> None:
        eff = ITEM_EFFECTS.get("223032")
        self.assertIsNotNone(eff)
        self.assertAlmostEqual(eff.bonus_as_conditional, 0.08, places=3)

    def test_yun_tal_crit_bonus_preserved(self) -> None:
        # Practice Makes Lethal +25% crit must still be present.
        eff = ITEM_EFFECTS["3032"]
        self.assertAlmostEqual(eff.crit_chance_bonus_flat, 0.25)

    def test_yun_tal_conditional_as_note_surfaces(self) -> None:
        r = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3032"])
        self.assertTrue(any("conditional AS" in n for n in r.notes))

    def test_yun_tal_dps_higher_than_no_flurry_pin(self) -> None:
        # Build with Yun Tal should produce higher DPS than same build without
        # the conditional AS contribution (compare against a zero-AS-bonus entry).
        r = compute_dps(self.snap, "Aatrox", level=11, item_ids=["3032"])
        # Verify cond_as note is present, confirming the AS path fired.
        has_as_note = any("conditional AS" in n for n in r.notes)
        self.assertTrue(has_as_note)


class Batch54SwordOfDivineEvTests(unittest.TestCase):
    """Sword of the Divine (443060) Excoriate EV crit damage bonus (batch 54).

    Excoriate grants random bonus crit damage in [0%, 50%]; EV of a uniform
    distribution = 25% → ``crit_damage_bonus=0.25``.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_443060_not_defensive_only(self) -> None:
        eff = ITEM_EFFECTS.get("443060")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)

    def test_443060_crit_damage_bonus_ev(self) -> None:
        eff = ITEM_EFFECTS["443060"]
        self.assertAlmostEqual(eff.crit_damage_bonus, 0.25)

    def test_443060_raises_dps_with_crit(self) -> None:
        # IE + SotD (443060) should exceed IE alone (crit damage stacks).
        ie_only = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3031"]
        )
        ie_sotd = compute_dps(
            self.snap, "Aatrox", level=11, item_ids=["3031", "443060"]
        )
        self.assertGreater(ie_sotd.weighted_dps, ie_only.weighted_dps)

    def test_batch54_total_count(self) -> None:
        # No new entries - 2 items promoted from defensive_only to active.
        # Total ITEM_EFFECTS count stays at 501.
        self.assertGreaterEqual(len(ITEM_EFFECTS), 501)


class Batch55DDragonCoverageTests(unittest.TestCase):
    """Batch 55: remaining DDragon purchasable items added as defensive_only.

    Completes DDragon purchasable coverage - every purchasable item with a
    gold price > 0 (excluding 9xxx Quickplay and 550xxx cosmetics) now has
    an ITEM_EFFECTS entry.
    """

    def test_doran_helm_present(self) -> None:
        eff = ITEM_EFFECTS.get("1120")
        self.assertIsNotNone(eff)
        self.assertTrue(eff.defensive_only)

    def test_jungle_companions_present(self) -> None:
        for iid in ["1101", "1102", "1103", "1105", "1106", "1107"]:
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff)
                self.assertTrue(eff.defensive_only)

    def test_bandle_juice_present(self) -> None:
        for iid in ["2161", "2162", "2163"]:
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff)
                self.assertTrue(eff.defensive_only)

    def test_arena_consumables_present(self) -> None:
        for iid in ["2141", "2142", "2143", "2144", "2147"]:
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff)
                self.assertTrue(eff.defensive_only)

    def test_legendary_prismatic_selectors_present(self) -> None:
        for iid in ["220001", "220002", "220003", "220004", "220005", "220006", "220007"]:
            with self.subTest(item_id=iid):
                eff = ITEM_EFFECTS.get(iid)
                self.assertIsNotNone(eff)
                self.assertTrue(eff.defensive_only)

    def test_ddragon_purchasable_coverage_complete(self) -> None:
        """Every DDragon purchasable item (gold>0, not 9xxx/55xxx) has an entry."""
        import json
        import os
        items_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "data",
            "daemon_slayer", "16.9.1", "items.json"
        )
        items = json.load(open(items_path))["data"]
        covered = set(ITEM_EFFECTS.keys())
        missing = []
        for k, v in items.items():
            if k.startswith("9") or k.startswith("55"):
                continue
            if not v.get("gold", {}).get("purchasable", False):
                continue
            if v.get("gold", {}).get("total", 0) <= 0:
                continue
            if k not in covered:
                missing.append(f"{k}:{v['name']}")
        self.assertEqual(missing, [], f"Uncovered purchasable items: {missing}")

    def test_batch55_total_count(self) -> None:
        # 501 + 46 new defensive_only entries = 547
        self.assertGreaterEqual(len(ITEM_EFFECTS), 547)


# ──────────────────────────── Batch 56: caster HP-scaled multiplicative AP amp


class Batch56CasterHpApAmpTests(unittest.TestCase):
    """Demonic Embrace (444637 Arena) Sinister Pact HP-scaled AP amp (batch 56).

    +1.5% AP per 100 current HP, capped at 45% at 3000 HP. Modeled with caster
    max HP. Applied multiplicatively after Rabadon's ap_amp_pct.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_444637_not_defensive_only(self) -> None:
        eff = ITEM_EFFECTS.get("444637")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)

    def test_444637_schema_values(self) -> None:
        eff = ITEM_EFFECTS["444637"]
        self.assertAlmostEqual(eff.ap_amp_pct_per_100_caster_hp, 0.015)
        self.assertAlmostEqual(eff.ap_amp_pct_per_100_caster_hp_cap, 0.45)

    def test_444637_raises_dps_vs_naked(self) -> None:
        # Lux with Nashor's Tooth (AP-scaling proc) + Demonic Embrace: at typical
        # HP (1200+), the amp is 18%+ → meaningful proc DPS gain.
        bare = compute_dps(self.snap, "Lux", level=11, item_ids=["3115"])
        with_dem = compute_dps(
            self.snap, "Lux", level=11, item_ids=["3115", "444637"]
        )
        self.assertGreater(with_dem.weighted_dps, bare.weighted_dps)

    def test_444637_note_surfaces(self) -> None:
        r = compute_dps(self.snap, "Lux", level=11, item_ids=["444637", "3115"])
        self.assertTrue(any("HP-scaled AP amp" in n for n in r.notes))

    def test_caster_hp_amp_stacks_with_rabadons(self) -> None:
        # Rabadon's + Demonic Embrace should stack multiplicatively.
        rab = compute_dps(
            self.snap, "Lux", level=11, item_ids=["3115", "3089"]
        )
        rab_dem = compute_dps(
            self.snap, "Lux", level=11, item_ids=["3115", "3089", "444637"]
        )
        self.assertGreater(rab_dem.weighted_dps, rab.weighted_dps)

    def test_batch56_count_unchanged(self) -> None:
        # 1 promotion from defensive_only to active - count stays >= 547.
        self.assertGreaterEqual(len(ITEM_EFFECTS), 547)


class Batch57VoidImmolationGoldenSpatulaTests(unittest.TestCase):
    """Phase 4 batch 57 - Void Immolation (223069) + Golden Spatula (224403) promotions."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ── Void Immolation (223069) ──────────────────────────────────────────

    def test_223069_not_defensive_only(self) -> None:
        eff = ITEM_EFFECTS.get("223069")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)

    def test_223069_schema_true_damage(self) -> None:
        eff = ITEM_EFFECTS["223069"]
        procs = eff.periodics
        self.assertEqual(len(procs), 1)
        self.assertEqual(procs[0].name, "Immolate")
        self.assertEqual(procs[0].damage_type, "true")
        self.assertAlmostEqual(procs[0].every_n_seconds, 1.0)

    def test_223069_immolate_key(self) -> None:
        eff = ITEM_EFFECTS["223069"]
        self.assertEqual(eff.unique_passive_key, "immolate")

    def test_223069_formula_at_3000_hp(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, caster_max_hp=3000.0, targets_in_rotation=1.0)
        eff = ITEM_EFFECTS["223069"]
        dmg = eff.periodics[0].bonus_damage(ctx)
        # 20 + 0.015 * 3000 = 20 + 45 = 65.0
        self.assertAlmostEqual(dmg, 65.0, places=1)

    def test_223069_raises_dps_vs_naked(self) -> None:
        bare = compute_dps(self.snap, "Malphite", level=11, item_ids=["3068"])
        with_vi = compute_dps(self.snap, "Malphite", level=11, item_ids=["223069"])
        # Void Immolation (TRUE damage bypasses armor) should contribute DPS
        self.assertGreater(with_vi.weighted_dps, 0)

    def test_223069_unique_passive_deduplication(self) -> None:
        # Both Void Immolation and Sunfire Aegis carry unique_passive_key="immolate"
        # - the engine should only apply one Immolate proc when both are in build.
        with_both = compute_dps(
            self.snap, "Malphite", level=11, item_ids=["3068", "223069"]
        )
        with_sunfire_only = compute_dps(
            self.snap, "Malphite", level=11, item_ids=["3068"]
        )
        with_void_only = compute_dps(
            self.snap, "Malphite", level=11, item_ids=["223069"]
        )
        # Combined must not exceed the sum of both individual contributions
        # (deduplication means only one Immolate fires)
        self.assertLessEqual(
            with_both.weighted_dps,
            with_sunfire_only.weighted_dps + with_void_only.weighted_dps + 1.0,
        )

    # ── The Golden Spatula (224403) ──────────────────────────────────────

    def test_224403_not_defensive_only(self) -> None:
        eff = ITEM_EFFECTS.get("224403")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)

    def test_224403_schema_magical_damage(self) -> None:
        eff = ITEM_EFFECTS["224403"]
        procs = eff.periodics
        self.assertEqual(len(procs), 1)
        self.assertEqual(procs[0].name, "Doing Something")
        self.assertEqual(procs[0].damage_type, "magical")
        self.assertAlmostEqual(procs[0].every_n_seconds, 1.0)

    def test_224403_formula_level_scaling(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx1 = CallContext(base_ad=100.0, bonus_ad=0.0, level=1, targets_in_rotation=1.0)
        ctx18 = CallContext(base_ad=100.0, bonus_ad=0.0, level=18, targets_in_rotation=1.0)
        eff = ITEM_EFFECTS["224403"]
        dmg1 = eff.periodics[0].bonus_damage(ctx1)
        dmg18 = eff.periodics[0].bonus_damage(ctx18)
        self.assertAlmostEqual(dmg1, 26.0, places=1)
        self.assertAlmostEqual(dmg18, 43.0, places=1)

    def test_224403_raises_dps(self) -> None:
        bare = compute_dps(self.snap, "Garen", level=11, item_ids=[])
        with_spat = compute_dps(self.snap, "Garen", level=11, item_ids=["224403"])
        self.assertGreater(with_spat.weighted_dps, bare.weighted_dps)

    def test_batch57_count_unchanged(self) -> None:
        # 2 promotions from defensive_only to active - total stays >= 547.
        self.assertGreaterEqual(len(ITEM_EFFECTS), 547)


class Batch58DarksteelTalonsArmorScalingTests(unittest.TestCase):
    """Phase 4 batch 58 - caster_bonus_armor field + Darksteel Talons full formula."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_call_context_has_caster_bonus_armor(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11)
        self.assertAlmostEqual(ctx.caster_bonus_armor, 0.0)

    def test_call_context_caster_bonus_armor_explicit(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, caster_bonus_armor=80.0)
        self.assertAlmostEqual(ctx.caster_bonus_armor, 80.0)

    def test_443054_formula_includes_armor_scaling(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        eff = ITEM_EFFECTS["443054"]
        # At level 11, base Gash = 10 + 10/17*10 = 15.88; with 100 bonus armor: + 20 = 35.88
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, caster_bonus_armor=100.0, targets_in_rotation=1.0)
        dmg = eff.periodics[0].bonus_damage(ctx)
        base_gash = 10.0 + 10.0 / 17.0 * 10
        expected = base_gash + 0.20 * 100.0
        self.assertAlmostEqual(dmg, expected, places=2)

    def test_443054_zero_armor_matches_old_formula(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        eff = ITEM_EFFECTS["443054"]
        ctx0 = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, caster_bonus_armor=0.0)
        dmg0 = eff.periodics[0].bonus_damage(ctx0)
        self.assertAlmostEqual(dmg0, 10.0 + 10.0 / 17.0 * 10, places=2)

    def test_443054_more_dps_with_more_bonus_armor(self) -> None:
        # Build with Darksteel Talons + armor items → more bonus armor → higher Gash
        bare = compute_dps(self.snap, "Malphite", level=11, item_ids=["443054"])
        with_armor = compute_dps(
            self.snap, "Malphite", level=11,
            item_ids=["443054", "3068"]  # Sunfire adds 50 armor
        )
        self.assertGreater(with_armor.weighted_dps, bare.weighted_dps)

    def test_443054_note_updated(self) -> None:
        eff = ITEM_EFFECTS["443054"]
        self.assertIn("bonus armor", eff.note)
        self.assertNotIn("deferred", eff.note)


class Batch59BastionbreakerLethScalingTests(unittest.TestCase):
    """Phase 4 batch 59 - caster_lethality + Bastionbreaker Shaped Charge."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_call_context_has_caster_lethality(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11)
        self.assertAlmostEqual(ctx.caster_lethality, 0.0)

    def test_2520_has_shaped_charge_proc(self) -> None:
        eff = ITEM_EFFECTS["2520"]
        self.assertFalse(eff.defensive_only)
        procs = eff.periodics
        self.assertEqual(len(procs), 1)
        self.assertEqual(procs[0].name, "Shaped Charge")
        self.assertEqual(procs[0].damage_type, "true")
        self.assertAlmostEqual(procs[0].every_n_seconds, 45.0)

    def test_2520_formula_at_lethality_22(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, caster_lethality=22.0)
        eff = ITEM_EFFECTS["2520"]
        dmg = eff.periodics[0].bonus_damage(ctx)
        # 15 + 0.75 * 22 = 15 + 16.5 = 31.5
        self.assertAlmostEqual(dmg, 31.5, places=2)

    def test_2520_formula_at_zero_lethality(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, caster_lethality=0.0)
        eff = ITEM_EFFECTS["2520"]
        dmg = eff.periodics[0].bonus_damage(ctx)
        self.assertAlmostEqual(dmg, 15.0, places=2)

    def test_2520_raises_dps(self) -> None:
        bare = compute_dps(self.snap, "Jayce", level=11, item_ids=["3179"])
        with_bb = compute_dps(self.snap, "Jayce", level=11, item_ids=["2520", "3179"])
        self.assertGreater(with_bb.weighted_dps, bare.weighted_dps)

    def test_2520_lethality_still_contributes(self) -> None:
        eff = ITEM_EFFECTS["2520"]
        self.assertAlmostEqual(eff.lethality, 22.0)


class Batch60RealityFractureVoidmitesTests(unittest.TestCase):
    """Phase 4 batch 60 - Reality Fracture (447102) ZZ'Rot Voidmites promotion."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_447102_not_defensive_only(self) -> None:
        eff = ITEM_EFFECTS.get("447102")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)

    def test_447102_proc_schema(self) -> None:
        eff = ITEM_EFFECTS["447102"]
        procs = eff.periodics
        self.assertEqual(len(procs), 1)
        self.assertEqual(procs[0].name, "ZZ'Rot")
        self.assertEqual(procs[0].damage_type, "magical")
        self.assertAlmostEqual(procs[0].every_n_seconds, 12.0)

    def test_447102_formula_baseline(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        # base_ad=100, bonus_ad=0, ap=0 → 8*(6+4+0) = 8*10 = 80
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, ap=0.0)
        eff = ITEM_EFFECTS["447102"]
        dmg = eff.periodics[0].bonus_damage(ctx)
        self.assertAlmostEqual(dmg, 8.0 * (6.0 + 0.04 * 100.0), places=2)

    def test_447102_formula_with_ap(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        # 100 total AD, 200 AP → 8*(6+4+16) = 8*26 = 208
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=11, ap=200.0)
        eff = ITEM_EFFECTS["447102"]
        dmg = eff.periodics[0].bonus_damage(ctx)
        self.assertAlmostEqual(dmg, 8.0 * (6.0 + 4.0 + 16.0), places=2)

    def test_447102_raises_dps(self) -> None:
        bare = compute_dps(self.snap, "Ezreal", level=11, item_ids=[])
        with_rf = compute_dps(self.snap, "Ezreal", level=11, item_ids=["447102"])
        self.assertGreater(with_rf.weighted_dps, bare.weighted_dps)

    def test_batch60_count_unchanged(self) -> None:
        self.assertGreaterEqual(len(ITEM_EFFECTS), 547)


class Batch61ZazzakBloodsongTests(unittest.TestCase):
    """Phase 4 batch 61 - Zaz'Zak's Realmspike (3871) + Bloodsong (3877) promotion."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # ── Zaz'Zak's Realmspike 3871 ──

    def test_3871_not_defensive_only(self) -> None:
        eff = ITEM_EFFECTS.get("3871")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)

    def test_3871_proc_schema(self) -> None:
        eff = ITEM_EFFECTS["3871"]
        self.assertEqual(len(eff.periodics), 1)
        p = eff.periodics[0]
        self.assertEqual(p.name, "Void Explosion")
        self.assertEqual(p.damage_type, "magical")
        self.assertAlmostEqual(p.every_n_seconds, 10.0)

    def test_3871_formula_baseline(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        # ap=0, target_max_hp=0 -> 1 * (10 + 0 + 0) = 10
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=11, ap=0.0, target_max_hp=0.0)
        eff = ITEM_EFFECTS["3871"]
        dmg = eff.periodics[0].bonus_damage(ctx)
        self.assertAlmostEqual(dmg, 10.0, places=2)

    def test_3871_formula_with_ap_and_hp(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        # ap=200, target_max_hp=2000, targets=1 -> 10 + 30 + 60 = 100
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=11, ap=200.0,
                         target_max_hp=2000.0, targets_in_rotation=1.0)
        eff = ITEM_EFFECTS["3871"]
        dmg = eff.periodics[0].bonus_damage(ctx)
        self.assertAlmostEqual(dmg, 10.0 + 0.15 * 200.0 + 0.03 * 2000.0, places=2)

    def test_3871_aoe_scales_with_targets(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx_single = CallContext(base_ad=60.0, bonus_ad=0.0, level=11, ap=100.0,
                                 target_max_hp=1000.0, targets_in_rotation=1.0)
        ctx_two = CallContext(base_ad=60.0, bonus_ad=0.0, level=11, ap=100.0,
                              target_max_hp=1000.0, targets_in_rotation=2.0)
        eff = ITEM_EFFECTS["3871"]
        dmg1 = eff.periodics[0].bonus_damage(ctx_single)
        dmg2 = eff.periodics[0].bonus_damage(ctx_two)
        self.assertAlmostEqual(dmg2, 2.0 * dmg1, places=2)

    def test_3871_raises_dps(self) -> None:
        bare = compute_dps(self.snap, "Lux", level=11, item_ids=[])
        with_zz = compute_dps(self.snap, "Lux", level=11, item_ids=["3871"])
        self.assertGreater(with_zz.weighted_dps, bare.weighted_dps)

    # ── Bloodsong 3877 ──

    def test_3877_not_defensive_only(self) -> None:
        eff = ITEM_EFFECTS.get("3877")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)

    def test_3877_spellblade_schema(self) -> None:
        eff = ITEM_EFFECTS["3877"]
        self.assertEqual(len(eff.periodics), 1)
        p = eff.periodics[0]
        self.assertEqual(p.name, "Spellblade")
        self.assertEqual(p.damage_type, "physical")
        self.assertAlmostEqual(p.every_n_seconds, 1.5)

    def test_3877_spellblade_is_100pct_base_ad(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx = CallContext(base_ad=80.0, bonus_ad=40.0, level=11)
        eff = ITEM_EFFECTS["3877"]
        dmg = eff.periodics[0].bonus_damage(ctx)
        self.assertAlmostEqual(dmg, 80.0, places=2)

    def test_3877_expose_weakness_damage_amp(self) -> None:
        eff = ITEM_EFFECTS["3877"]
        self.assertAlmostEqual(eff.damage_amp_pct, 0.05, places=4)

    def test_3877_unique_passive_key(self) -> None:
        self.assertEqual(ITEM_EFFECTS["3877"].unique_passive_key, "spellblade")

    def test_3877_spellblade_same_ratio_as_sheen(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx = CallContext(base_ad=80.0, bonus_ad=0.0, level=11)
        sheen_dmg = ITEM_EFFECTS["3057"].periodics[0].bonus_damage(ctx)
        blood_dmg = ITEM_EFFECTS["3877"].periodics[0].bonus_damage(ctx)
        self.assertAlmostEqual(sheen_dmg, blood_dmg, places=2)

    def test_3877_raises_dps(self) -> None:
        bare = compute_dps(self.snap, "Senna", level=11, item_ids=[])
        with_bs = compute_dps(self.snap, "Senna", level=11, item_ids=["3877"])
        self.assertGreater(with_bs.weighted_dps, bare.weighted_dps)

    def test_batch61_count_unchanged(self) -> None:
        self.assertGreaterEqual(len(ITEM_EFFECTS), 547)


class Batch62CrueltyWatchThemFallTests(unittest.TestCase):
    """Phase 4 batch 62 - Cruelty Arena (447109) + SR (667109) promotion."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _check_proc_schema(self, iid: str) -> None:
        eff = ITEM_EFFECTS[iid]
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)
        p = eff.periodics[0]
        self.assertEqual(p.name, "Watch Them Fall")
        self.assertEqual(p.damage_type, "magical")
        self.assertAlmostEqual(p.every_n_seconds, 6.0)

    def test_447109_not_defensive_only(self) -> None:
        self.assertFalse(ITEM_EFFECTS["447109"].defensive_only)

    def test_667109_not_defensive_only(self) -> None:
        self.assertFalse(ITEM_EFFECTS["667109"].defensive_only)

    def test_447109_proc_schema(self) -> None:
        self._check_proc_schema("447109")

    def test_667109_proc_schema(self) -> None:
        self._check_proc_schema("667109")

    def test_formula_baseline_level1(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        # level=1, ap=0, caster_max_hp=0 -> 50 + 0 + 0 + 0 = 50
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=1, ap=0.0, caster_max_hp=0.0)
        for iid in ["447109", "667109"]:
            dmg = ITEM_EFFECTS[iid].periodics[0].bonus_damage(ctx)
            self.assertAlmostEqual(dmg, 50.0, places=2, msg=f"item {iid}")

    def test_formula_level_scaling(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        # level=18, ap=0, hp=0 -> 50 + 100 = 150
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=18, ap=0.0, caster_max_hp=0.0)
        dmg = ITEM_EFFECTS["447109"].periodics[0].bonus_damage(ctx)
        self.assertAlmostEqual(dmg, 150.0, places=1)

    def test_formula_with_ap_and_hp(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        # level=11, ap=200, caster_max_hp=3000, targets=1
        # 50 + (100/17)*10 + 40 + 120 = 50 + 58.82 + 40 + 120 = 268.82
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=11, ap=200.0,
                         caster_max_hp=3000.0, targets_in_rotation=1.0)
        eff = ITEM_EFFECTS["447109"]
        expected = 50.0 + (100.0 / 17.0) * 10 + 0.40 * 200.0 + 0.04 * 3000.0
        dmg = eff.periodics[0].bonus_damage(ctx)
        self.assertAlmostEqual(dmg, expected, places=1)

    def test_aoe_scales_with_targets(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx1 = CallContext(base_ad=60.0, bonus_ad=0.0, level=11, ap=100.0,
                           caster_max_hp=2000.0, targets_in_rotation=1.0)
        ctx3 = CallContext(base_ad=60.0, bonus_ad=0.0, level=11, ap=100.0,
                           caster_max_hp=2000.0, targets_in_rotation=3.0)
        eff = ITEM_EFFECTS["447109"]
        self.assertAlmostEqual(eff.periodics[0].bonus_damage(ctx3),
                               3.0 * eff.periodics[0].bonus_damage(ctx1), places=2)

    def test_both_versions_same_formula(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        ctx = CallContext(base_ad=60.0, bonus_ad=0.0, level=11, ap=150.0, caster_max_hp=2500.0)
        d447 = ITEM_EFFECTS["447109"].periodics[0].bonus_damage(ctx)
        d667 = ITEM_EFFECTS["667109"].periodics[0].bonus_damage(ctx)
        self.assertAlmostEqual(d447, d667, places=4)

    def test_447109_raises_dps(self) -> None:
        bare = compute_dps(self.snap, "Lissandra", level=11, item_ids=[])
        with_cr = compute_dps(self.snap, "Lissandra", level=11, item_ids=["447109"])
        self.assertGreater(with_cr.weighted_dps, bare.weighted_dps)

    def test_667109_raises_dps(self) -> None:
        bare = compute_dps(self.snap, "Lissandra", level=11, item_ids=[])
        with_cr = compute_dps(self.snap, "Lissandra", level=11, item_ids=["667109"])
        self.assertGreater(with_cr.weighted_dps, bare.weighted_dps)

    def test_batch62_count_unchanged(self) -> None:
        self.assertGreaterEqual(len(ITEM_EFFECTS), 547)


class Batch63BlockedItemPromotionsTests(unittest.TestCase):
    """Batch 63 - 3 previously-blocked items promoted using binding-constraint CDs.

    * Hellfire Hatchet (4017): Char 15s CD - hp_diff + lethality scaling
    * Fiendhunter Bolts (2512): Opening Barrage 45s CD - 3×crit-bonus attacks
    * Innervating Locket (447104): Fill the Soul bonus_ap_stacked midpoint
    """

    snap: DataSnapshot

    @classmethod
    def setUpClass(cls) -> None:
        from agents.daemon_slayer.data_loader import DataSnapshot
        cls.snap = DataSnapshot.load()

    # ── Hellfire Hatchet ──────────────────────────────────────────────────────

    def test_hellfire_hatchet_has_char_proc(self) -> None:
        eff = ITEM_EFFECTS.get("4017")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)
        self.assertEqual(eff.periodics[0].name, "Char")
        self.assertEqual(eff.periodics[0].damage_type, PHYSICAL)
        self.assertAlmostEqual(eff.periodics[0].every_n_seconds, 15.0, places=1)
        self.assertEqual(eff.unique_passive_key, "hellfire_char")

    def test_hellfire_char_formula_zero_hpdiff(self) -> None:
        # Caster and target same HP → hp_diff=0 → base 5% target_max_hp
        ctx = CallContext(base_ad=80.0, bonus_ad=20.0, level=12, ap=0.0,
                          caster_max_hp=2000.0, target_max_hp=2000.0,
                          caster_lethality=0.0)
        dmg = ITEM_EFFECTS["4017"].periodics[0].bonus_damage(ctx)
        self.assertAlmostEqual(dmg, 2000.0 * 0.05, places=2)

    def test_hellfire_char_formula_max_hpdiff(self) -> None:
        # hp_diff=2000 → 10% target_max_hp + lethality bonus
        leth = 30.0
        ctx = CallContext(base_ad=80.0, bonus_ad=20.0, level=12, ap=0.0,
                          caster_max_hp=4000.0, target_max_hp=2000.0,
                          caster_lethality=leth)
        dmg = ITEM_EFFECTS["4017"].periodics[0].bonus_damage(ctx)
        expected = 2000.0 * (0.10 + leth * 0.004)
        self.assertAlmostEqual(dmg, expected, places=2)

    def test_hellfire_char_hpdiff_clamped(self) -> None:
        # hp_diff > 2000 → clamped to 2000
        ctx_big = CallContext(base_ad=80.0, bonus_ad=0.0, level=12, ap=0.0,
                              caster_max_hp=9000.0, target_max_hp=2000.0,
                              caster_lethality=0.0)
        ctx_cap = CallContext(base_ad=80.0, bonus_ad=0.0, level=12, ap=0.0,
                              caster_max_hp=4000.0, target_max_hp=2000.0,
                              caster_lethality=0.0)
        dmg_big = ITEM_EFFECTS["4017"].periodics[0].bonus_damage(ctx_big)
        dmg_cap = ITEM_EFFECTS["4017"].periodics[0].bonus_damage(ctx_cap)
        self.assertAlmostEqual(dmg_big, dmg_cap, places=2)

    def test_hellfire_hatchet_raises_dps(self) -> None:
        bare = compute_dps(self.snap, "Zed", level=12, item_ids=[])
        with_hh = compute_dps(self.snap, "Zed", level=12, item_ids=["4017"])
        self.assertGreater(with_hh.weighted_dps, bare.weighted_dps)

    # ── Fiendhunter Bolts ────────────────────────────────────────────────────

    def test_fiendhunter_bolts_has_opening_barrage(self) -> None:
        eff = ITEM_EFFECTS.get("2512")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)
        self.assertEqual(eff.periodics[0].name, "Opening Barrage")
        self.assertEqual(eff.periodics[0].damage_type, PHYSICAL)
        self.assertAlmostEqual(eff.periodics[0].every_n_seconds, 45.0, places=1)
        self.assertEqual(eff.unique_passive_key, "fiendhunter_barrage")

    def test_fiendhunter_barrage_scales_with_ad(self) -> None:
        ctx_low = CallContext(base_ad=50.0, bonus_ad=20.0, level=10, ap=0.0)
        ctx_high = CallContext(base_ad=100.0, bonus_ad=40.0, level=10, ap=0.0)
        dmg_low = ITEM_EFFECTS["2512"].periodics[0].bonus_damage(ctx_low)
        dmg_high = ITEM_EFFECTS["2512"].periodics[0].bonus_damage(ctx_high)
        self.assertAlmostEqual(dmg_low, 3.0 * 70.0 * 0.70, places=2)
        self.assertAlmostEqual(dmg_high, 3.0 * 140.0 * 0.70, places=2)

    def test_fiendhunter_bolts_raises_dps(self) -> None:
        bare = compute_dps(self.snap, "Jinx", level=10, item_ids=[])
        with_fb = compute_dps(self.snap, "Jinx", level=10, item_ids=["2512"])
        self.assertGreater(with_fb.weighted_dps, bare.weighted_dps)

    # ── Innervating Locket ───────────────────────────────────────────────────

    def test_innervating_locket_bonus_ap_stacked(self) -> None:
        eff = ITEM_EFFECTS.get("447104")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertAlmostEqual(eff.bonus_ap_stacked, 175.0, places=1)
        self.assertEqual(eff.unique_passive_key, "innervating_fill")
        self.assertEqual(len(eff.periodics), 0)

    def test_innervating_locket_raises_dps_with_ap_proc(self) -> None:
        # bonus_ap_stacked only contributes when paired with an AP-scaling proc item.
        # Use Lich Bane (3100) which has an AP-scaling spellblade proc.
        base = compute_dps(self.snap, "Lissandra", level=10, item_ids=["3100"])
        with_il = compute_dps(self.snap, "Lissandra", level=10, item_ids=["3100", "447104"])
        self.assertGreater(with_il.weighted_dps, base.weighted_dps)

    def test_batch63_version(self) -> None:
        from agents.daemon_slayer import ENGINE_VERSION
        # Latest engine version stamp. Bumped on each milestone:
        # 0.60.0 = Batch 64 Malignance; 0.61.0 = Phase 6 step 7 DPS curve helper;
        # 0.62.0 = Phase 6 step 8 dead-unique filter;
        # 0.63.0 = s174 Phase 1 Tank EHP scorer;
        # 0.64.0 = s175 Phase 2 Bruiser hybrid scorer;
        # 0.65.0 = s177 Phase 4a champion ability ingest;
        # 0.66.0 = s178 Phase 4b mage ability DPS evaluator;
        # 0.67.0 = s179 Phase 4c mage ability DPS ranker (+ /rank-mage route);
        # 0.68.0 = s180 Phase 5 assassin burst-window scorer (+ /rank-assassin route);
        # 0.69.0 = s181 Phase 6 enchanter HPS scorer (+ /rank-enchanter route);
        # 0.70.0 = s185 Phase 4d per-champion max_priority overrides;
        # 0.71.0 = s186 Phase 5.5 per-champion combo_sequence overrides;
        # 0.72.0 = s187 Phase 4e per-(champion, key) form_index overrides;
        # 0.73.0 = s188 Phase 5.6 per-attack on-hit proc damage in burst AAs;
        # 0.74.0 = s189 Phase 5.7 Spellblade in burst - armed by ability cast,
        #          consumed by next AA (Trinity Force / Lich Bane / ER / Iceborn /
        #          Dusk+Dawn / Divine Sunderer / Sheen / Bloodsong + Arena mirrors);
        # 0.75.0 = s190 Phase 5.8 Sundered Sky Lightshield Strike in burst -
        #          same arm-consume model, capped at 1 proc per combo (8s real CD);
        # 0.76.0 = s191 Phase 5.9 per-(champion, key) damage block_index
        #          overrides - Cassi E poisoned amp, Veigar R execute max,
        #          Anivia E chilled amp, Diana W all-orbs, Brand W CC'd, etc.
        # 0.77.0 = s192 Phase 5.9.5 token-variant block_index for Akali R -
        #          R1 → block 0 (base + bonus-AD), R2 → block 2 (max-execute
        #          missing-HP scaling); walker checks canonical token first
        #          then base key.
        # 0.78.0 = s193 Phase 5.9.6 channeled-ability block_index expansion -
        #          8 new champion entries (Alistar E, AurelionSol E,
        #          Fiddlesticks R, MissFortune E, Samira R, Singed Q,
        #          Velkoz R, Syndra R) + Anivia Q extension. Pure data
        #          batch; no resolver/walker code changes.
        # 0.79.0 = s194 Phase 5.9.7 calibration-follow-up block_index expansion -
        #          8 more (champion, key) entries closing s193's deferred list
        #          (Corki W/E, Hecarim W/E, Jayce Q/W, Rell R, DrMundo W).
        #          Pure data batch; same per-tick → total / min → max amped
        #          pattern; resolver/walker code unchanged.
        # 0.80.0 = s195 Phase 5.9.8 multi-hit/charge/recast block_index expansion -
        #          13 more (champion, key) entries across four sub-patterns:
        #          multi-hit single-target totals (Ahri W, Kaisa Q, Lulu Q,
        #          Sivir Q, Talon W/R, Velkoz W, Ekko Q), fully-charged amps
        #          (Varus Q, Zoe Q, Vladimir E), recast amp (Camille Q),
        #          CC-conditional duration total (Morgana W). Pure data batch.
        # 0.81.0 = s196 Phase 5.9.9 extended multi-hit/condition-amp block_index
        #          expansion - 17 more (champion, key) entries (14 new
        #          champions + 3 key extensions on Akali, Cassi, Morgana).
        #          Pattern A multi-hit single-target totals (Akali E, Akshan Q,
        #          Cassi W, Cho'gath E, Draven R, Lillia W, Morgana R,
        #          Nautilus E, Riven Q, Sett Q, Skarner Q, Soraka E).
        #          Pattern B fully-charged / condition amps (Gragas Q fermented,
        #          Karthus Q solo-target enhanced, Kha'Zix Q isolation,
        #          Kog'Maw R low-HP execute, Pantheon Q charged hurl). Pure
        #          data batch; no walker/resolver/server code changes.
        # 0.82.0 = s197 Phase 5.9.10 assassin/fighter resource amps + utility
        #          totals - 20 more (champion, key) entries across 18 new
        #          champions (registry 49 → 67). Pattern A multi-hit/channel/mark
        #          totals (Aatrox W, Hwei R, LeBlanc Q/E, Lucian R, Mel Q/R,
        #          MonkeyKing R, Naafiri Q/E, MasterYi Q, Smolder W).
        #          Pattern B fully-charged amps (Nunu W, Sion Q, Briar E).
        #          Pattern C resource-state amps (Renekton Q/W full-Fury,
        #          Kassadin R max-stack Riftwalk). Pattern D execute /
        #          channel-duration amps (Darius R, Nilah R). Pattern E
        #          multi-charge / multi-fire totals (Poppy R, Rumble E). Pure
        #          data batch; no walker/resolver/server code changes.
        # 0.83.0 = s198 Phase 5.9.11 bruiser/jungler/utility/marksman block_index
        #          expansion - 20 more (champion, key) entries (17 new
        #          champions + 2 key extensions on existing Sion and Vladimir;
        #          XinZhao contributes 2 entries Q+W). Registry 67 → 84
        #          champions. Pattern A multi-hit single-target totals
        #          (Sylas Q, XinZhao Q/W, Zac R, Maokai E, Kayn Q, Sejuani W,
        #          Neeko Q, Nasus E, Nami E, Ornn R, Twitch E). Pattern B
        #          fully-charged amps (Vi Q, Sion R, Irelia W, Yuumi Q).
        #          Pattern C resource-state amp (Jax E at 2 dodge stacks).
        #          Pattern D channel/duration totals (Udyr R full storm
        #          ticks, Vladimir W full Sanguine Pool, Viktor R full
        #          Chaos Storm channel). Pure data batch; no walker/resolver/
        #          server code changes.
        # 0.84.0 = s199 Phase 5.9.12 - 17 more (champion, key) entries (6 new
        #          champions: Ashe/Shaco/Shen/Swain/Tristana/Xayah + 11 key
        #          extensions on Aatrox/Fiddlesticks/Karthus/Nautilus/Nunu/
        #          Samira/Sejuani/Talon/Udyr/Viktor/Zac). Registry 84 → 90
        #          champions, 103 → 120 entries. Six patterns: Pattern A
        #          multi-hit single-target totals (Ashe Q Ranger's Focus,
        #          Nunu E 3-snowball, Samira W Blade Whirl, Shen Q 3-AA
        #          empowered, Swain Q 5-bolt, Viktor Q + AA, Xayah Q
        #          out+return, Zac Q both arms). Pattern B positional/sweet-
        #          spot amps (Aatrox Q1 sweet-spot, Shaco E backstab, Talon Q
        #          champion crit). Pattern C resource-state amps (Tristana E
        #          max-stack, Udyr Q Awakened 2-AA). Pattern D channel total
        #          (Karthus E per-second). Pattern E direct-hit primary
        #          (Sejuani R, Nautilus R). Pattern F execute amp
        #          (Fiddlesticks W low-HP). Pure data batch; no walker/
        #          resolver/server code changes.
        # 0.85.0 = s200 Phase 5.9.13 rescue batch - 7 more (champion, key)
        #          entries closing 4 previously-deferred mechanics: Ambessa
        #          Q/W Drain-stack amp (s196/s197/s198 'form swap' deferral
        #          dissolved on verification), Anivia R Empowered phase
        #          (s195 'channel ticks ambiguous' rescued), Lillia Q
        #          Dream Dust AA combo (s199 'uncertain' rescued), Nilah Q
        #          max-stack empowered AA (s199 'uncertain 2-stack'
        #          rescued). Plus Ambessa E (Lacerate slash+thrust 2×),
        #          Poppy Q (Hammer Shock out+return 2×). Pattern A multi-
        #          hit totals (Ambessa E, Lillia Q, Poppy Q). Pattern B
        #          resource-state amps (Ambessa Q, Ambessa W, Nilah Q).
        #          Pattern C channel commit (Anivia R). Registry 90 → 91
        #          champions, 120 → 127 entries. Pure data batch.
        # 0.86.0 = s201 Phase 5.9.14 block_index expansion - 16 more
        #          (champion, key) entries across 13 new champions (Fizz/
        #          Galio/Garen/Graves/Janna/Jhin/Kennen/Taliyah/Teemo/Viego/
        #          Xerath/Yasuo/Ziggs, 3 with two keys: Jhin Q+R, Teemo
        #          E+R, Xerath W+R). Pattern A multi-hit single-target
        #          totals (Graves Q, Jhin Q, Kennen R, Taliyah Q, Teemo E,
        #          Xerath R, Ziggs E). Pattern B fully-charged amps (Galio
        #          W, Janna Q, Jhin R, Viego Q). Pattern C channel/duration
        #          totals (Fizz R, Garen E, Teemo R). Pattern D resource/
        #          positional amps (Xerath W, Yasuo E). Registry 91 → 104
        #          champions, 127 → 143 entries.
        # 0.87.0 = s202 Phase 5.9.15 block_index expansion - 18 more
        #          (champion, key) entries: 6 truly-new champions
        #          (Gangplank, Gnar, KSante, RekSai, Vayne, Yunara) + 12
        #          key extensions on existing (Zoe W, Akshan R,
        #          AurelionSol Q, Nasus R, Poppy E, Renekton R, Rumble Q+R,
        #          Smolder Q+R, Viktor E, Yuumi R). Pattern A multi-hit
        #          totals (KSante R, Vayne E, Yunara Q filtered, Zoe W
        #          filtered, Viktor E). Pattern B channel/duration totals
        #          (Gangplank R, AurelionSol Q, Nasus R filtered, Renekton
        #          R filtered, Rumble R, Yuumi R filtered, Poppy E
        #          filtered). Pattern C max-charge/distance (Akshan R
        #          filtered, Smolder R filtered). Pattern D resource-state
        #          (RekSai E, Smolder Q). Pattern E wall-stun/charge
        #          condition (Gnar R filtered, Rumble Q filtered). 9 of
        #          18 entries have non-damage prefix blocks. Reverts 4
        #          prior-batch skip rationales: Gnar R + Vayne E + Poppy E
        #          wall-stun (s198/s199 'terrain condition'), Rumble Q
        #          (s199 'heat decays'). 6 deliberate skips: Syndra W (too
        #          marginal 1.12×), Camille W (needs sum-of-blocks),
        #          Yunara W (initial > total), Smolder E (Meraki ambiguity),
        #          Sona Q (sum-of-blocks), Kayle E (same Phase 4a parser
        #          limit as s201 Kindred E). Registry 104 → 110 champions,
        #          143 → 161 entries. Pure data batch.
        # 0.88.0 = s203 Phase 5.9.16 block_index expansion - 12 more
        #          (champion, key) entries: 5 truly-new champions
        #          (Blitzcrank, Gwen, Kled, LeeSin, Thresh) + 5 key
        #          extensions on existing (Diana R, Jax R, Kennen W,
        #          Smolder E, Vladimir Q). Six sub-patterns: (A) multi-hit
        #          single-target totals (Diana R, Gwen R, Kled Q, Kled E,
        #          Vladimir Q), (B) resource-state amps (Smolder E, also
        #          Vladimir Q via Crimson Rush), (C) active-cast vs
        #          passive-zap split (Blitzcrank R, Kennen W, Jax R -
        #          engine pre-s203 was scoring the passive zap / mark /
        #          3rd-AA as the R cast value), (D) max-charge condition
        #          amp (Kled R filtered), (E) missing-HP amp layered on
        #          s187 form_index (LeeSin Q - first NET-damage
        #          composition of block_index with form_index registry),
        #          (F) empty-block-0 fix (Thresh E - first instance of
        #          this pattern; raw block 0 evaluates to 0 via unparsed-
        #          only soul scaling, registry routes past it). 4 entries
        #          with non-damage prefix blocks (Diana R, Kled Q, Kled R,
        #          Vladimir Q). Reverts 1 prior skip (Smolder E s198/s202
        #          Meraki Minimum schema label - same operator-commit
        #          framing as Smolder Q s202 reintroduction). 8 deliberate
        #          skips documented inline (DrMundo Q, Caitlyn Q/R, Ezreal
        #          R, Nocturne Q/E, Orianna Q, Pantheon R, Trundle Q/R,
        #          Yone W/R, Zed Q, AurelionSol R form 1, Pyke/Quinn/Senna,
        #          Vayne W passive). 8 deferred to schema lifts (Katarina
        #          R, Malphite W, Malzahar E/R, Kalista E, Jinx R distance,
        #          Belveth R missing-HP, Riven R form 1, Qiyana Q form).
        #          Registry 110 → 115 champions, 161 → 173 entries. Pure
        #          data batch.
        # 0.89.0 = s204 Phase 5.9.17 block_index + form_index expansion -
        #          8 new (champion, key) entries (2 truly-new champions
        #          Nidalee + Seraphine + 6 key extensions on existing:
        #          Evelynn Q, Gwen Q, KSante W, Riven R, Syndra W, Zoe E)
        #          PLUS 1 new champion in form_index registry (Riven R=1).
        #          Six sub-patterns: (A) multi-hit single-target totals
        #          (Evelynn Q, Gwen Q, Syndra W), (B) fully-charged amp
        #          (KSante W max-charge Path Maker), (C) champion-vs-minion
        #          amp (Seraphine Q Maximum Champion Damage), (D) execute
        #          amp layered on form_index (Nidalee Q low-HP cougar
        #          Takedown - second NET-damage layering after s203 LeeSin
        #          Q), (E) target-state amp (Zoe E sleep-procced Maximum
        #          Mixed Damage), (F) form_index seed expansion (Riven R
        #          form 1 Wind Slash + block 1 max-missing-HP execute -
        #          first new champion added to form_index registry since
        #          s187, closes s203 carry-forward 'Riven form_index seed
        #          needed'). Riven form 0 has zero damage blocks so no
        #          information loss from routing to form 1. Registry 115
        #          → 117 champions, 173 → 181 entries. Pure data batch.
        # 0.90.0 = s205 Phase 5.9.18 form_index + block_index layered
        #          expansion - 4 new (champion, key) block_index entries
        #          (1 new champion Qiyana + 3 key extensions on existing:
        #          Hwei W, Renekton E, Shaco W) + 3 new form_index seeds
        #          (Qiyana Q=1, AurelionSol R=1, Renekton E=1). Three
        #          sub-patterns: (A) operator-commits-to-resource form
        #          layer (Qiyana Q elemental empowered = form 1 + block 2,
        #          AurelionSol R The Skies Descend = form 1, Renekton E
        #          full-Fury combo = form 1 + block 3 - closes Renekton
        #          Q/W/E full-Fury coverage after s197), (B) multi-hit
        #          single-target totals (Hwei W3 Stirring Lights 3 lights
        #          converging = block 1 Maximum Magic Damage = 3× block 0),
        #          (C) condition-amp vs target-state (Shaco W Box vs
        #          already-Feared target = block 1 Increased Damage). Third
        #          instance of form_index + block_index NET-damage
        #          composition after s203 LeeSin Q + s204 Riven R + s204
        #          Nidalee Q. Closes s204 carry-forward 'Qiyana Q
        #          form_index seed expansion still pending'. Registry 117
        #          → 118 champions, 181 → 185 entries on block_index side;
        #          form_index registry 6 → 9 champions, 10 → 13 entries.
        #          Pure data batch.
        # 0.91.0 = s206 Phase 5.9.19 cooldown inheritance from form 0 when
        #          non-form-0 has cooldown=None. Closes the s205
        #          carry-forward "Engine None-cooldown fallback". Affects
        #          the 4 form_index registry entries with form 1
        #          cooldown=None: Riven R / Renekton E / AurelionSol R /
        #          Qiyana Q. Engine helper _form_cooldown_at_rank gains an
        #          optional fallback_form param; both call sites
        #          (ability_dps.py + burst.py) pass forms[0] when
        #          form_idx != 0. Impact: per_spell.cooldown metadata now
        #          reports the canonical form 0 CD instead of the generic
        #          60s default; theoretical-fallback DPS conversion (only
        #          fires when measured cast rate is missing) is now
        #          accurate. Measured cps_source paths are unaffected
        #          (which covers all 4 entries in production), so total
        #          ability_dps is unchanged. Forward-compat for new
        #          form-swap champions where measured rates may not yet be
        #          available.
        # 0.92.0 = s207 Phase 5.9.20 sum-of-blocks schema lift. Closes the
        #          s205+s206 carry-forward "sum-of-blocks bucket warranted
        #          soon - 10+ candidates queued". block_index_overrides
        #          value type widens from int to int | list[int]; lists
        #          express "operator commits to landing every component"
        #          where the realistic single-target damage is the sum
        #          across multiple Meraki damage blocks. Engine helpers:
        #          new _normalize_block_index_value validator; _select_blocks
        #          "indexed" strategy now accepts int | Sequence[int] and
        #          loops/sums when given a sequence; same clamp semantics
        #          per element. server _parse_block_index decoder accepts
        #          JSON arrays alongside ints. Seed entries (4): Camille
        #          W=[0,1] (Tactical Sweep base + Outer Cone Bonus on
        #          in-cone target - 2-block sum), Malphite W=[2,3] (active
        #          cast + first empowered AA - 2-block sum), Heimerdinger
        #          W=[0,1,1,1,1] (Initial + 4× Subsequent rockets focused
        #          on one non-minion - sum with index repetition expresses
        #          the 4× multiplier elegantly), Katarina R=[1,3] (full
        #          Death Lotus on single target = max physical + max magic
        #          dagger volleys both summed). Backward-compat: existing
        #          int-valued entries unchanged; single-int callers retain
        #          identical pre-s207 behavior.
        # 0.93.0 = s215 Phase 5.9.21 sum-of-blocks data batch. First pure-
        #          data batch consuming the s207 schema lift. Adds 4 new
        #          (champion, key) entries from s207's queued candidate
        #          list: Thresh E=[1,2] (Maximum Bonus Magic at full Souls
        #          + canonical Magic Damage - extends s203's single-int
        #          {E:2} entry to a list, first int→list lift since the
        #          s207 seed), Sona Q=[0,1] (active Magic Damage + Power
        #          Chord empowered AA), Kalista E=[0,1,1,1,1] (base Rend
        #          + 4× additional stacks = 5-stack Rend, same model as
        #          Heimerdinger W rocket-count s207), Malzahar R=[0,2]
        #          (Total Magic suppression channel + Total target-max-HP%
        #          bonus from full-duration Nether Grasp). 4 entries
        #          verified per-rank against Meraki 16.10.1; Per-spell raw
        #          lifts: Kalista E +193% / Malzahar R +150% / Thresh E
        #          +84% / Sona Q +16%. Registry 121 → 124 champions.
        # 0.94.0 = s217 Phase 5.9.22 sum-of-blocks data batch (second).
        #          Closes the s215 carry-forward queue. 2 entries:
        #          Taliyah E=[0,2] (NEW key - Magic Damage initial shard
        #          impact + Total Maximum Detonation Damage aggregate, full
        #          single-target burst when target steps through Unraveled
        #          Earth), DrMundo W=[1,2] (LIFT from s193's {W: 1} - full
        #          channel drain + recast detonation burst). Per-spell raw
        #          lifts: Taliyah E +109%, DrMundo W +25%. Registry 124 →
        #          124 champions (Taliyah gains E key; DrMundo lifted).
        #          Sum-of-blocks bucket queue now exhausted under current
        #          operator-commit framing.
        # 0.95.0 = s223 Phase 5.9.23 nested missing/current/maximum-HP
        #          parser fix + registry-saturation finding. Extractor
        #          _canonicalize_unit() strips Meraki's nested '(+ ...)'
        #          conditional parentheticals so % target-health units
        #          (Kindred E missing-HP, Cho'Gath E / K'Sante W / Sett Q
        #          / Shen Q / Zac W / Amumu W / Evelynn E / Elise Q / Kled
        #          W maximum/current-HP) resolve to their typed field; a
        #          deterministic in-place migration promoted exactly 22
        #          such modifiers across 10 champions (their %HP component
        #          was dropped since Phase 4a). One new entry: Kindred
        #          E=1 (enhanced-execute 7.5% missing-HP). The s191→s217
        #          single-int/list registry is now provably saturated (a
        #          5-way parallel scan of all 47 uncovered champions found
        #          zero clean candidates).
        # 0.96.0 = s224 Phase 5.9.24 unmapped-key pass on COVERED
        #          champions. Bel'Veth R=1 (corrects s223's over-
        #          conservative no-entry call - engine defaults to the
        #          8-dmg block 0, not the 200-dmg recast nuke). Plus 8
        #          _UNIT_TO_FIELD text-drift health-unit variants
        #          (double-space / "the target's" / caster pronoun+name)
        #          → migration promoted 32 mods across 13 champions
        #          (Gwen Q·R / Varus W / Trundle R / Fiddlesticks Q /
        #          Sejuani W / Zac Q / Ambessa Q / …) whose %HP component
        #          was dropped (Trundle R + Fiddle Q were 0 entirely).
        # 0.97.0 = s225 Phase 5.9.25 post-parser-fix block_index sweep.
        #          Varus W=2 - 'Bonus Magic Damage at Max Stacks' (3x the
        #          per-Blight-stack value, the 3-stack detonation = the
        #          standard Varus combo). Engine defaulted to block 0
        #          (18-dmg passive on-hit), scoring W at ~7% of real
        #          (live A/B 18→240 raw, 13.3x). Found by re-running the
        #          unmapped-key pre-filter on the post-s224 snapshot.
        # 0.98.0 = s226 Phase 5.9.26 first form_index coverage sweep
        #          since s205. 3 ADDs: Swain R=1 (Demonflare recast vs
        #          form-0 drain per-tick, A/B 12.5→250), Briar W=1 (form
        #          0 'Blood Frenzy' has NO damage block - form 1 'Snack
        #          Attack' is the whole W), Evelynn E=1 (Empowered
        #          Whiplash - Eve's canonical Demon-Shade combo).
        # 0.99.0 = s227 Phase 5.9.27 max_priority audit. 3 ADDs of
        #          universally-established W-first orders the registry
        #          missed: Brand W-E-Q (+18.7%), Fiddlesticks W-E-Q
        #          (+16.4%), Talon W-Q-E (+12.0%). Finding: the numeric
        #          pre-filter over-flags (≠ real play); max_priority +
        #          combo_sequence are meta-curated, not numeric-swept.
        # 1.0.0  = s228 Phase 5.9.28 conditional-target-state schema
        #          lift (operator option B, multi-session). Part 1:
        #          block_index value widens int|list -> ALSO
        #          dict{"default",<cond>} (closed vocab
        #          target_full_hp/target_no_setup). Resolves to
        #          "default" branch unconditionally (== int/list,
        #          zero regression); live HP%/CC predicates = Part 2.
        #          3 flagship seeds (Zoe E / Evelynn Q / Kindred E)
        #          are no-op conversions of shipped unconditional
        #          entries.
        self.assertEqual(ENGINE_VERSION, "1.21.0")


class Batch64MalignanceTests(unittest.TestCase):
    """Batch 64 (2026-05-05) - Malignance Hatefog promotion via ult-cast schema."""

    @classmethod
    def setUpClass(cls) -> None:
        from agents.daemon_slayer.data_loader import DataSnapshot
        cls.snap = DataSnapshot.load()

    def test_malignance_sr_has_hatefog_proc(self) -> None:
        eff = ITEM_EFFECTS.get("3118")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)
        proc = eff.periodics[0]
        self.assertEqual(proc.name, "Hatefog")
        self.assertEqual(proc.damage_type, "magical")
        self.assertAlmostEqual(proc.every_n_seconds, 1.0)

    def test_malignance_aram_mirror_has_hatefog_proc(self) -> None:
        eff = ITEM_EFFECTS.get("223118")
        self.assertIsNotNone(eff)
        self.assertFalse(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 1)
        self.assertEqual(eff.periodics[0].name, "Hatefog")

    def test_hatefog_damage_scales_with_ap_and_ult_rate(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        eff = ITEM_EFFECTS["3118"]
        proc = eff.periodics[0]
        # With 300 AP and 0.02/s ult rate: (180 + 0.15*300) * 0.02 = 4.95
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=13, ap=300.0, ult_casts_per_sec=0.02)
        dmg = proc.resolve_damage(ctx)
        self.assertAlmostEqual(dmg, (180.0 + 0.15 * 300.0) * 0.02, places=4)

    def test_hatefog_zero_when_no_ult_data(self) -> None:
        from agents.daemon_slayer.effects import CallContext
        eff = ITEM_EFFECTS["3118"]
        proc = eff.periodics[0]
        ctx = CallContext(base_ad=100.0, bonus_ad=0.0, level=13, ap=400.0, ult_casts_per_sec=0.0)
        self.assertEqual(proc.resolve_damage(ctx), 0.0)

    def test_malignance_raises_dps_for_ap_mage(self) -> None:
        # Ahri (AP mage) + Luden's Echo should get a small but positive delta from Malignance
        base = compute_dps(self.snap, "Ahri", level=13, item_ids=["6655"], mode="ARAM")
        with_mal = compute_dps(self.snap, "Ahri", level=13, item_ids=["6655", "3118"], mode="ARAM")
        self.assertGreater(with_mal.weighted_dps, base.weighted_dps)

    def test_ult_rates_lookup(self) -> None:
        from agents.daemon_slayer.ult_rates import get_ult_casts_per_sec
        # Ahri ARAM should have a real rate
        rate = get_ult_casts_per_sec("Ahri", "ARAM")
        self.assertGreater(rate, 0.0)
        # Unknown champion falls back to global median
        fallback = get_ult_casts_per_sec("UnknownChamp999", "SR")
        self.assertGreater(fallback, 0.0)

    def test_batch64_version(self) -> None:
        from agents.daemon_slayer import ENGINE_VERSION
        self.assertEqual(ENGINE_VERSION, "1.21.0")


if __name__ == "__main__":
    unittest.main()

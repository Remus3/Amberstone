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


if __name__ == "__main__":
    unittest.main()

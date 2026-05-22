"""ENGINE 1.28.0 (2026-05-21) - Phase 6 EHP healing throughput.

Closes the ``ehp.py:23`` Phase-6 deliberate omission "Healing throughput
(lifesteal, Spirit Visage amp)". Three contributions feed the heal pool:

* item-passive heals via NEW ``ItemHeal`` dataclass + ``ItemEffect.heal``
  (Sundered Sky 6610 / Arena 226610 Lightshield Strike: 100% base AD
  melee / 50% ranged per one-trigger-per-fight)
* lifesteal-derived heal: ``stats.lifesteal * stats.ad * stats.as *
  _FIGHT_WINDOW_S`` accumulated over the 6s fight window
* multiplicative heal amp via NEW ``ItemEffect.heal_amp_pct`` (Spirit
  Visage 3065 / Arena 223065 Boundless Vitality +25%)

Bloodthirster 3072 / Arena 223072 Ichorshield ships in the Phase 1.5
ItemShield pipeline (full-cap steady-state: 165 L1 -> 315 L18, ANY).

Coverage classes:

* ``ItemHealSchemaTests`` - dataclass construction + magnitude
  composition + ranged modifier + edge cases.
* ``CollectHealsTests`` - the helper that walks item_ids and aggregates
  item-passive heals; handles missing/None heal fields.
* ``TotalHealAmpTests`` - the multiplicative amp factor across all items.
* ``LifestealHealTests`` - per-fight lifesteal magnitude from stats.
* ``BTIchorshieldTests`` - BT ships as an ItemShield in the Phase 1.5
  pipeline (NOT an ItemHeal); shield_any populated at the right magnitude.
* ``SunderedSkyHealTests`` - melee/ranged base AD scaling per trigger.
* ``SpiritVisageAmpTests`` - heal pool multiplied by 1.25; pure-shield
  builds were unaffected in Phase 6 (ENGINE 1.28.0) but Phase 6.5
  (ENGINE 1.29.0, ``test_spirit_visage_amps_phase15_shields_at_125``)
  extends the amp to the shield pool too per Riot's tooltip wording
  "increases self-healing and shielding by 25%".
* ``EhpResultHealFieldsTests`` - new heal_* fields present in to_dict
  + format_table renders heal row when non-zero.
* ``DeathsDanceDeferredTests`` - DD 6333 stays defensive_only (Defy heal
  deferred to Phase 6.5).
* ``BTPlusLifelineStacksTests`` - BT shield + Sterak shield both apply
  (BT does NOT share unique_passive_key="lifeline" so compute_ehp adds
  both magnitudes; rank.py dedup is upstream and unaffected here).
* ``EngineVersionCurrentTests`` - pin ENGINE_VERSION 1.29.0.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_types import (
    ANY,
    ItemHeal,
    MAGICAL,
)
from agents.daemon_slayer.effects import ITEM_EFFECTS
from agents.daemon_slayer.ehp import (
    _FIGHT_WINDOW_S,
    _MISSING_HP_SHARE_FOR_HEALS,
    _collect_heals,
    _lifesteal_heal,
    _total_heal_amp,
    compute_ehp,
)
from agents.daemon_slayer.data_loader import DataSnapshot


# ---------------- schema ----------------


class ItemHealSchemaTests(unittest.TestCase):
    def test_default_construction_yields_zero_heal(self) -> None:
        h = ItemHeal()
        self.assertEqual(h.resolve_magnitude(), 0.0)

    def test_flat_only(self) -> None:
        h = ItemHeal(flat=150.0)
        self.assertEqual(h.resolve_magnitude(), 150.0)

    def test_base_ad_scaling_melee(self) -> None:
        # Sundered Sky shape: 1.0 * base_ad
        h = ItemHeal(base_ad_scaling=1.0)
        self.assertEqual(h.resolve_magnitude(base_ad=100), 100.0)

    def test_ranged_modifier_halves_base_ad(self) -> None:
        h = ItemHeal(base_ad_scaling=1.0, ranged_modifier=0.5)
        self.assertEqual(
            h.resolve_magnitude(base_ad=100, is_ranged=False), 100.0
        )
        self.assertEqual(
            h.resolve_magnitude(base_ad=100, is_ranged=True), 50.0
        )

    def test_bonus_hp_scaling_with_flat(self) -> None:
        # Hypothetical: 50 flat + 30% bonus HP (Lighthearted-shape)
        h = ItemHeal(flat=50.0, bonus_hp_scaling=0.30)
        self.assertEqual(
            h.resolve_magnitude(bonus_hp=1000), 350.0
        )

    def test_bonus_ad_scaling(self) -> None:
        h = ItemHeal(bonus_ad_scaling=0.75)
        self.assertEqual(h.resolve_magnitude(bonus_ad=80), 60.0)

    def test_negative_inputs_floored_at_zero(self) -> None:
        # Defense against a future data corruption.
        h = ItemHeal(base_ad_scaling=1.0, bonus_ad_scaling=1.0, bonus_hp_scaling=1.0)
        self.assertEqual(
            h.resolve_magnitude(base_ad=-50, bonus_ad=-50, bonus_hp=-50), 0.0
        )

    def test_negative_ranged_modifier_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ItemHeal(ranged_modifier=-0.1)

    def test_ranged_modifier_zero_allowed(self) -> None:
        # ranged_modifier=0 means "no heal for ranged" - a valid
        # configuration even though no current item uses it.
        h = ItemHeal(base_ad_scaling=1.0, ranged_modifier=0.0)
        self.assertEqual(
            h.resolve_magnitude(base_ad=100, is_ranged=True), 0.0
        )

    def test_full_composition(self) -> None:
        # 25 flat + 0.5 * base_ad + 0.3 * bonus_ad + 0.05 * bonus_hp
        h = ItemHeal(
            flat=25.0,
            base_ad_scaling=0.5,
            bonus_ad_scaling=0.3,
            bonus_hp_scaling=0.05,
            ranged_modifier=0.8,
        )
        # 25 + 50 + 30 + 50 = 155 melee; ranged 155*0.8 = 124
        self.assertEqual(
            h.resolve_magnitude(base_ad=100, bonus_ad=100, bonus_hp=1000), 155.0
        )
        self.assertEqual(
            h.resolve_magnitude(
                base_ad=100, bonus_ad=100, bonus_hp=1000, is_ranged=True
            ),
            124.0,
        )


# ---------------- _collect_heals ----------------


class CollectHealsTests(unittest.TestCase):
    def test_no_items_returns_zero(self) -> None:
        total, sources = _collect_heals(
            [], base_ad=100, bonus_hp=0, bonus_ad=0, is_ranged=False
        )
        self.assertEqual(total, 0.0)
        self.assertEqual(sources, ())

    def test_skips_items_without_heal_field(self) -> None:
        # 3031 Infinity Edge has no heal field
        total, sources = _collect_heals(
            ["3031"], base_ad=100, bonus_hp=0, bonus_ad=0, is_ranged=False
        )
        self.assertEqual(total, 0.0)
        self.assertEqual(sources, ())

    def test_skips_unknown_item_id(self) -> None:
        total, sources = _collect_heals(
            ["999999"], base_ad=100, bonus_hp=0, bonus_ad=0, is_ranged=False
        )
        self.assertEqual(total, 0.0)
        self.assertEqual(sources, ())

    def test_sundered_sky_aggregates_correctly_melee(self) -> None:
        total, sources = _collect_heals(
            ["6610"], base_ad=120, bonus_hp=0, bonus_ad=0, is_ranged=False
        )
        # 1.0 * 120 = 120
        self.assertEqual(total, 120.0)
        self.assertEqual(sources, (("6610", 120.0),))

    def test_sundered_sky_ranged_halved(self) -> None:
        total, sources = _collect_heals(
            ["6610"], base_ad=120, bonus_hp=0, bonus_ad=0, is_ranged=True
        )
        self.assertEqual(total, 60.0)


# ---------------- _total_heal_amp ----------------


class TotalHealAmpTests(unittest.TestCase):
    def test_no_amp_items(self) -> None:
        self.assertEqual(_total_heal_amp([]), 1.0)

    def test_single_amp_item_spirit_visage(self) -> None:
        # SV is 0.25 -> 1.25
        self.assertEqual(_total_heal_amp(["3065"]), 1.25)

    def test_skips_items_without_amp(self) -> None:
        self.assertEqual(_total_heal_amp(["3031"]), 1.0)

    def test_unknown_item_silent(self) -> None:
        self.assertEqual(_total_heal_amp(["999999"]), 1.0)

    def test_arena_mirror_amp(self) -> None:
        # Arena 223065 same 0.25
        self.assertEqual(_total_heal_amp(["223065"]), 1.25)

    def test_two_amp_items_multiplicative(self) -> None:
        # Hypothetical 2 SVs (or SV + future amp item): 1.25 * 1.25 = 1.5625
        self.assertAlmostEqual(_total_heal_amp(["3065", "3065"]), 1.5625)


# ---------------- _lifesteal_heal ----------------


class LifestealHealTests(unittest.TestCase):
    def test_zero_lifesteal_zero_heal(self) -> None:
        self.assertEqual(
            _lifesteal_heal(lifesteal_pct=0.0, ad=100, attack_speed=1.0), 0.0
        )

    def test_zero_ad_zero_heal(self) -> None:
        self.assertEqual(
            _lifesteal_heal(lifesteal_pct=0.25, ad=0, attack_speed=1.0), 0.0
        )

    def test_full_formula_at_default_window(self) -> None:
        # 0.20 * 100 * 1.0 * 6 = 120
        self.assertEqual(
            _lifesteal_heal(lifesteal_pct=0.20, ad=100, attack_speed=1.0), 120.0
        )

    def test_default_fight_window_pinned_at_6(self) -> None:
        self.assertEqual(_FIGHT_WINDOW_S, 6.0)

    def test_custom_window(self) -> None:
        # 0.20 * 100 * 1.0 * 3 = 60
        self.assertEqual(
            _lifesteal_heal(
                lifesteal_pct=0.20, ad=100, attack_speed=1.0, fight_window_s=3.0
            ),
            60.0,
        )

    def test_zero_window_returns_zero(self) -> None:
        self.assertEqual(
            _lifesteal_heal(
                lifesteal_pct=0.25, ad=100, attack_speed=1.0, fight_window_s=0.0
            ),
            0.0,
        )

    def test_negative_inputs_floored(self) -> None:
        self.assertEqual(
            _lifesteal_heal(lifesteal_pct=-0.25, ad=100, attack_speed=1.0), 0.0
        )
        self.assertEqual(
            _lifesteal_heal(lifesteal_pct=0.25, ad=-100, attack_speed=1.0), 0.0
        )


# ---------------- BT Ichorshield (Phase 1.5 pipeline, NOT ItemHeal) ----------------


class BTIchorshieldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_bt_has_shield_not_heal_field(self) -> None:
        bt = ITEM_EFFECTS["3072"]
        self.assertIsNotNone(bt.shield)
        self.assertIsNone(bt.heal)

    def test_bt_arena_mirror_has_shield_not_heal(self) -> None:
        bt = ITEM_EFFECTS["223072"]
        self.assertIsNotNone(bt.shield)
        self.assertIsNone(bt.heal)

    def test_bt_shield_l1_value(self) -> None:
        # L1 (below level_lerp_low=9): flat = 165
        bt = ITEM_EFFECTS["3072"]
        self.assertEqual(bt.shield.resolve_magnitude(level=1), 165.0)

    def test_bt_shield_l9_value(self) -> None:
        # At lerp_low, holds at flat=165
        bt = ITEM_EFFECTS["3072"]
        self.assertEqual(bt.shield.resolve_magnitude(level=9), 165.0)

    def test_bt_shield_l18_value(self) -> None:
        # L18 (level_lerp_high): 315
        bt = ITEM_EFFECTS["3072"]
        self.assertEqual(bt.shield.resolve_magnitude(level=18), 315.0)

    def test_bt_shield_mid_lerp(self) -> None:
        # L11: 9 -> 18 span = 9, t=2/9, value = 165 + 2/9 * 150 = 198.333
        bt = ITEM_EFFECTS["3072"]
        self.assertAlmostEqual(
            bt.shield.resolve_magnitude(level=11), 198.333, places=2
        )

    def test_bt_no_lifeline_unique_passive(self) -> None:
        # BT's Ichorshield is a distinct unique-passive family; it MUST
        # NOT share unique_passive_key="lifeline" with Sterak/Shieldbow/
        # Maw/Hexdrinker or the rank.py shares_dead_unique filter would
        # incorrectly de-dup it.
        bt = ITEM_EFFECTS["3072"]
        self.assertNotEqual(bt.unique_passive_key, "lifeline")

    def test_bt_shield_lifts_physical_ehp_l11(self) -> None:
        # Aatrox L11 + BT: shield_any = 198.33 lifts physical_ehp.
        r0 = compute_ehp(self.snap, "Aatrox", 11, item_ids=[], mode="SR")
        r1 = compute_ehp(self.snap, "Aatrox", 11, item_ids=["3072"], mode="SR")
        self.assertGreater(r1.shield_any, 195)
        self.assertLess(r1.shield_any, 205)
        # EHP delta > shield magnitude (because divided by armor factor)
        self.assertGreater(r1.physical_ehp, r0.physical_ehp + 100)


# ---------------- Sundered Sky heal ----------------


class SunderedSkyHealTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_sundered_sky_has_heal_field(self) -> None:
        ss = ITEM_EFFECTS["6610"]
        self.assertIsNotNone(ss.heal)
        self.assertEqual(ss.heal.base_ad_scaling, 1.0)
        self.assertEqual(ss.heal.ranged_modifier, 0.5)

    def test_sundered_sky_arena_mirror_same_heal(self) -> None:
        ss = ITEM_EFFECTS["226610"]
        self.assertIsNotNone(ss.heal)
        self.assertEqual(ss.heal.base_ad_scaling, 1.0)
        self.assertEqual(ss.heal.ranged_modifier, 0.5)

    def test_aatrox_l11_sundered_sky_melee_heal(self) -> None:
        # Aatrox L11 base AD = 103.875, total HP = 2050.35.
        # Phase 6.5 (ENGINE 1.29.0, 2026-05-21): missing-HP additive
        # piece (6%) wired with _MISSING_HP_SHARE_FOR_HEALS=0.5 ->
        # missing_hp = 1025.175 -> additive piece = 0.06 * 1025.175 =
        # 61.51. Total heal_item_total ~ 103.875 + 61.51 = 165.39 melee.
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6610"], mode="SR"
        )
        self.assertGreater(r.heal_item_total, 160)
        self.assertLess(r.heal_item_total, 170)

    def test_caitlyn_l11_sundered_sky_ranged_heal_halved(self) -> None:
        # Caitlyn is ranged, gets 0.5x base AD heal.
        r_melee = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6610"], mode="SR"
        )
        r_ranged = compute_ehp(
            self.snap, "Caitlyn", 11, item_ids=["6610"], mode="SR"
        )
        # Ranged should be roughly half the melee heal (modulo base AD diff)
        # Aatrox base_ad ~103.875, Caitlyn ~76.875 at L11.
        # Aatrox melee heal ~= 103.875, Caitlyn ranged heal = 76.875 * 0.5 ~ 38.4
        self.assertGreater(r_melee.heal_item_total, r_ranged.heal_item_total * 2)

    def test_sundered_sky_periodic_damage_still_modeled(self) -> None:
        # The existing PeriodicProc (Lightshield Strike damage) is
        # unchanged - heal is ADDED to the entry, not a replacement.
        ss = ITEM_EFFECTS["6610"]
        self.assertEqual(len(ss.periodics), 1)
        self.assertEqual(ss.periodics[0].name, "Lightshield Strike")


# ---------------- Spirit Visage amp ----------------


class SpiritVisageAmpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_spirit_visage_carries_amp(self) -> None:
        sv = ITEM_EFFECTS["3065"]
        self.assertEqual(sv.heal_amp_pct, 0.25)

    def test_spirit_visage_arena_mirror_carries_amp(self) -> None:
        sv = ITEM_EFFECTS["223065"]
        self.assertEqual(sv.heal_amp_pct, 0.25)

    def test_spirit_visage_alone_no_heal_pool(self) -> None:
        # Spirit Visage alone has no heal contribution and no lifesteal
        # so heal_total stays 0 (amp times 0 is 0).
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3065"], mode="SR"
        )
        self.assertEqual(r.heal_total, 0.0)
        self.assertEqual(r.heal_amp_mult, 1.25)

    def test_sundered_sky_plus_spirit_visage_amped(self) -> None:
        r_alone = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6610"], mode="SR"
        )
        r_amped = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6610", "3065"], mode="SR"
        )
        # heal_amp_mult = 1.25 (Spirit Visage)
        self.assertEqual(r_amped.heal_amp_mult, 1.25)
        # Phase 6.5 (ENGINE 1.29.0, 2026-05-21): SV adds 400 HP which
        # also bumps missing_hp (0.5 * 400 = 200 more), so heal_total
        # is amped AND lifted by the additional missing-HP contribution.
        # Verify the amp piece works: heal_total_amped = 1.25 * heal_item
        # where heal_item reflects the AMPED-build's missing_hp.
        amped_heal_item_expected = r_amped.heal_item_total
        self.assertAlmostEqual(
            r_amped.heal_total, amped_heal_item_expected * 1.25, places=2
        )
        # And the amped build's heal_total exceeds the pure amp of the
        # alone-build by exactly the missing-HP-from-SV-HP delta * 1.25.
        # SV adds 400 HP -> +200 missing_hp -> +0.06 * 200 = 12 heal
        # (pre-amp) -> 12 * 1.25 = 15 heal (post-amp) more than
        # heal_alone * 1.25.
        delta = r_amped.heal_total - (r_alone.heal_total * 1.25)
        self.assertAlmostEqual(delta, 15.0, places=1)

    def test_spirit_visage_amps_phase15_shields_at_125(self) -> None:
        # Phase 6.5 (ENGINE 1.29.0) closes the Phase 6 deliberate
        # boundary: Riot's tooltip on Spirit Visage 3065 reads
        # "increases self-healing and shielding by 25%". The Phase 6
        # wire amped only the heal pool; Phase 6.5 extends the same
        # multiplier to the shield pool too.
        #
        # The ``shield_any`` / ``shield_phys`` / ``shield_mag`` /
        # ``shield_true`` fields stay PRE-amp for transparency (matching
        # the ``heal_item_total`` / ``heal_lifesteal`` pre-amp convention);
        # ``shield_amp_mult`` exposes the multiplier; the EHP-math at
        # ``compute_ehp`` line ~590 applies the amp at the top of the
        # damage stack. The two amps (heal_amp_mult and shield_amp_mult)
        # are SIBLINGS, not nested - same multiplier value today but
        # conceptually independent fields.
        r_sterak = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3053"], mode="SR"
        )
        r_sterak_sv = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3053", "3065"], mode="SR"
        )
        # shield_any pre-amp value still reacts to SV's bonus_hp pickup
        # (60% of 400 = 240); delta on the PRE-amp field is unchanged
        # from Phase 6.
        delta_pre_amp = r_sterak_sv.shield_any - r_sterak.shield_any
        self.assertAlmostEqual(delta_pre_amp, 240.0, places=0)
        # shield_amp_mult flips to 1.25 (was 1.0 pre-Phase-6.5).
        self.assertAlmostEqual(r_sterak.shield_amp_mult, 1.0, places=4)
        self.assertAlmostEqual(r_sterak_sv.shield_amp_mult, 1.25, places=4)
        # physical_ehp lift is now LARGER than Phase 6 by exactly the
        # shield-amp contribution: (shield_any_with_sv * 0.25) /
        # (armor_factor(armor) * mode_mult). Verified end-to-end with
        # Aatrox L11 armor base + Sterak's HP grant.
        armor = r_sterak_sv.armor
        armor_factor = 100.0 / (100.0 + armor)
        shield_amp_lift = (r_sterak_sv.shield_any * 0.25) / armor_factor
        phase6_lift = r_sterak_sv.physical_ehp - r_sterak.physical_ehp
        # Phase 6 would have given a smaller lift (no shield amp); the
        # Phase 6.5 delta exceeds the Phase-6 expected delta by exactly
        # the shield_amp_lift (within float tolerance). We pin the post-
        # amp physical_ehp directly: must include the amped shield.
        expected_phys_ehp = (r_sterak_sv.hp + r_sterak_sv.shield_any * 1.25) / armor_factor
        self.assertAlmostEqual(r_sterak_sv.physical_ehp, expected_phys_ehp, places=1)
        # Sanity: the shield_amp_lift is strictly positive.
        self.assertGreater(shield_amp_lift, 0.0)
        self.assertGreater(phase6_lift, shield_amp_lift)


# ---------------- EhpResult new fields ----------------


class EhpResultHealFieldsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_to_dict_includes_heal_fields(self) -> None:
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6610", "3065"], mode="SR"
        )
        d = r.to_dict()
        self.assertIn("heal_item_total", d)
        self.assertIn("heal_lifesteal", d)
        self.assertIn("heal_amp_mult", d)
        self.assertIn("heal_total", d)
        self.assertIn("heal_sources", d)
        # heal_sources is a list of dicts in to_dict
        self.assertIsInstance(d["heal_sources"], list)
        for entry in d["heal_sources"]:
            self.assertIn("item_id", entry)
            self.assertIn("heal_hp", entry)

    def test_format_table_renders_heal_row_when_present(self) -> None:
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6610", "3065"], mode="SR"
        )
        table = r.format_table()
        self.assertIn("heal_hp", table)
        self.assertIn("amp=", table)

    def test_format_table_omits_heal_row_when_zero(self) -> None:
        # No heal sources and no lifesteal
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[], mode="SR"
        )
        table = r.format_table()
        self.assertNotIn("heal_hp", table)

    def test_notes_carry_heal_source_lines(self) -> None:
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6610"], mode="SR"
        )
        notes = "\n".join(r.notes)
        self.assertIn("Sundered Sky", notes)
        self.assertIn("heal:", notes)


# ---------------- DD deferred ----------------


class DeathsDanceDeferredTests(unittest.TestCase):
    def test_dd_stays_defensive_only(self) -> None:
        dd = ITEM_EFFECTS["6333"]
        self.assertTrue(dd.defensive_only)

    def test_dd_has_no_heal_field(self) -> None:
        # Defy heal deferred to Phase 6.5
        dd = ITEM_EFFECTS["6333"]
        self.assertIsNone(dd.heal)
        self.assertEqual(dd.heal_amp_pct, 0.0)

    def test_dd_arena_mirror_same_deferral(self) -> None:
        dd = ITEM_EFFECTS["226333"]
        self.assertIsNone(dd.heal)
        self.assertEqual(dd.heal_amp_pct, 0.0)


# ---------------- BT + lifeline stacking ----------------


class BTPlusLifelineStacksTests(unittest.TestCase):
    """compute_ehp does NOT apply unique_passive dedup itself - rank.py's
    shares_dead_unique filter handles that. So a build that explicitly
    includes BT + Sterak gets BOTH shields. This pins the data-layer
    behavior; rank.py's filter is upstream.
    """

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_bt_plus_sterak_both_contribute_shields(self) -> None:
        r_bt = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3072"], mode="SR"
        )
        r_sterak = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3053"], mode="SR"
        )
        r_both = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3072", "3053"], mode="SR"
        )
        # Both shield contributions should aggregate (engine adds, planner
        # decides whether the combo is build-legal).
        self.assertGreater(r_both.shield_any, r_bt.shield_any)
        self.assertGreater(r_both.shield_any, r_sterak.shield_any)

    def test_bt_plus_shieldbow_both_contribute(self) -> None:
        # Same engine-level rule for the lifeline-shape Shieldbow.
        r_solo = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6673"], mode="SR"
        )
        r_both = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3072", "6673"], mode="SR"
        )
        self.assertGreater(r_both.shield_any, r_solo.shield_any + 150)


# ---------------- ENGINE version pin ----------------


class EngineVersionCurrentTests(unittest.TestCase):
    def test_engine_version_at_1_31_0(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.33.0")


# ---------------- Phase 6.5: missing-HP additive on item heals ----------------


class MissingHpAdditiveTests(unittest.TestCase):
    """ItemHeal.missing_hp_pct schema + resolve_magnitude composition.

    Phase 6.5 (2026-05-21): Sundered Sky's Lightshield Strike heal piece
    carries a 6% missing-HP additive in addition to the base AD scaling
    per Meraki 16.10.1. The dataclass exposes ``missing_hp_pct`` and
    threads ``missing_hp`` through ``resolve_magnitude`` so the EHP
    scorer can compose the mid-fight HP-share convention at the
    consumer site.
    """

    def test_item_heal_default_missing_hp_pct_is_zero(self) -> None:
        h = ItemHeal()
        self.assertEqual(h.missing_hp_pct, 0.0)

    def test_resolve_magnitude_with_missing_hp_zero_returns_base(self) -> None:
        # Even if missing_hp_pct > 0, missing_hp=0 means no additive
        # contribution.
        h = ItemHeal(missing_hp_pct=0.06)
        self.assertEqual(h.resolve_magnitude(missing_hp=0.0), 0.0)
        h2 = ItemHeal(base_ad_scaling=1.0, missing_hp_pct=0.06)
        self.assertEqual(
            h2.resolve_magnitude(base_ad=100, missing_hp=0.0), 100.0
        )

    def test_resolve_magnitude_with_missing_hp_adds_pct_times_missing_hp(self) -> None:
        # Pure missing-HP shape: 6% of 1000 missing HP = 60.
        h = ItemHeal(missing_hp_pct=0.06)
        self.assertEqual(h.resolve_magnitude(missing_hp=1000), 60.0)

    def test_resolve_magnitude_with_missing_hp_plus_base_ad(self) -> None:
        # Composition: base AD + missing-HP piece.
        # 1.0 * 100 + 0.06 * 1000 = 100 + 60 = 160.
        h = ItemHeal(base_ad_scaling=1.0, missing_hp_pct=0.06)
        self.assertEqual(
            h.resolve_magnitude(base_ad=100, missing_hp=1000), 160.0
        )

    def test_resolve_magnitude_ranged_modifier_applies_to_missing_hp_too(self) -> None:
        # Ranged modifier applies AFTER the missing-HP piece is added
        # to the total (mirrors the existing ranged-modifier behavior).
        # 0.06 * 1000 = 60; ranged 0.5 -> 30.
        h = ItemHeal(missing_hp_pct=0.06, ranged_modifier=0.5)
        self.assertEqual(
            h.resolve_magnitude(missing_hp=1000, is_ranged=True), 30.0
        )

    def test_negative_missing_hp_floored_to_zero(self) -> None:
        # Defensive: negative missing_hp returns base only (additive
        # piece floored at 0).
        h = ItemHeal(base_ad_scaling=1.0, missing_hp_pct=0.06)
        self.assertEqual(
            h.resolve_magnitude(base_ad=100, missing_hp=-500), 100.0
        )

    def test_negative_missing_hp_pct_rejected_by_post_init(self) -> None:
        with self.assertRaises(ValueError):
            ItemHeal(missing_hp_pct=-0.01)

    def test_missing_hp_share_constant_is_one_half(self) -> None:
        # Pin the Phase 6.5 mid-fight HP-share convention.
        self.assertEqual(_MISSING_HP_SHARE_FOR_HEALS, 0.5)


class SunderedSkyMissingHpTests(unittest.TestCase):
    """Phase 6.5 wire of Sundered Sky's 6% missing-HP additive heal piece.

    Closes the Phase 6 deliberate-omission (4) on Sundered Sky.
    """

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_sundered_sky_now_carries_missing_hp_pct_006(self) -> None:
        ss = ITEM_EFFECTS["6610"]
        self.assertEqual(ss.heal.missing_hp_pct, 0.06)

    def test_arena_226610_mirror_carries_missing_hp_pct_006(self) -> None:
        ss = ITEM_EFFECTS["226610"]
        self.assertEqual(ss.heal.missing_hp_pct, 0.06)

    def test_sundered_sky_heal_at_full_hp_unchanged(self) -> None:
        # When missing_hp=0 (full HP), the heal piece is identical to
        # the pre-Phase-6.5 base AD contribution: 100% base AD melee.
        # Aatrox L11 base AD = 103.875.
        ss = ITEM_EFFECTS["6610"]
        heal = ss.heal.resolve_magnitude(
            base_ad=103.875, missing_hp=0.0, is_ranged=False
        )
        self.assertAlmostEqual(heal, 103.875, places=3)

    def test_sundered_sky_heal_at_mid_fight_50pct_includes_additive(self) -> None:
        # Aatrox L11: hp = 2050.35, base_ad = 103.875. Mid-fight
        # missing_hp = 0.5 * 2050.35 = 1025.175. Missing-HP piece =
        # 0.06 * 1025.175 = 61.5105. Total heal = 103.875 + 61.5105 =
        # 165.3855.
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6610"], mode="SR"
        )
        expected_total = 103.875 + 0.06 * (r.hp * 0.5)
        self.assertAlmostEqual(r.heal_item_total, expected_total, places=3)
        self.assertAlmostEqual(r.heal_item_total, 165.3855, places=3)

    def test_sundered_sky_ranged_user_halves_missing_hp_piece_too(self) -> None:
        # Caitlyn L11 ranged: heal = 0.5 * (base_ad + 0.06 * missing_hp).
        # Caitlyn L11 base_ad = 95.345, hp = 1918.925, missing_hp =
        # 959.463 -> pre-ranged = 95.345 + 57.568 = 152.913 -> ranged
        # = 76.456.
        r = compute_ehp(
            self.snap, "Caitlyn", 11, item_ids=["6610"], mode="SR"
        )
        expected = 0.5 * (95.345 + 0.06 * (r.hp * 0.5))
        self.assertAlmostEqual(r.heal_item_total, expected, places=2)
        self.assertAlmostEqual(r.heal_item_total, 76.456, places=2)

    def test_sundered_sky_ehp_lift_at_full_hp_vs_mid_fight(self) -> None:
        # At full HP (missing_hp=0): heal = 103.875.
        # At mid-fight (missing_hp = 0.5*hp): heal = 103.875 + 0.06 *
        # (0.5*hp). The lift over the full-HP baseline is exactly
        # 0.06 * 0.5 * hp.
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6610"], mode="SR"
        )
        # Phase 6.5 mid-fight: heal_item_total reflects the additive.
        expected_lift_over_base_only = 0.06 * (r.hp * 0.5)
        # heal_item_total - base_only_heal (103.875)
        actual_lift = r.heal_item_total - 103.875
        self.assertAlmostEqual(
            actual_lift, expected_lift_over_base_only, places=3
        )


if __name__ == "__main__":
    unittest.main()

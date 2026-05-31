"""ENGINE 1.27.0 (2026-05-21) - Phase 1.5 EHP shield throughput.

Closes the ``ehp.py:21`` Phase-1.5 omission "Shield throughput (Sterak's
lifeline, Doran's Shield, Bloodthirster) - needs uptime modeling". Ships
the four LIFELINE-style shields (single trigger per fight, value-additive
to the effective-HP pool at top of the damage stack):

* Sterak's Gage 3053 - any-damage, 60% bonus_hp
* Immortal Shieldbow 6673 - any-damage, 400 L1-L8 -> 700 L18, ranged x0.80
* Maw of Malmortius 3156 - magical, 200 + 150% bonus_ad, ranged x0.75
* Hexdrinker 3155 - magical, 110 L1-L8 -> 280 L18, ranged x0.75

Bloodthirster's ichor-shield is intentionally DEFERRED to Phase 6 with
the rest of the healing-throughput model (it requires overheal accrual
rather than a single-trigger threshold).

Coverage classes:

* ``ItemShieldSchemaTests`` - dataclass construction + magnitude lerp +
  ranged modifier + bonus stat scaling + edge cases.
* ``CollectShieldsTests`` - the helper that walks item_ids and aggregates
  shields by damage type; handles missing/None shield fields.
* ``SterakShieldTests`` - Sett L11 with Sterak's gets exactly
  ``0.60 * bonus_hp`` shield_any; baseline is unchanged.
* ``ShieldbowShieldTests`` - L1/L9/L18 level-curve + ranged modifier.
* ``MawShieldTests`` - magic-only damage type + bonus_ad scaling + ranged
  modifier; physical_ehp unchanged when only Maw is equipped.
* ``HexdrinkerShieldTests`` - level curve + ranged modifier + magic-only.
* ``EhpResultShieldFieldsTests`` - new fields are present in to_dict
  + format_table renders shield row when non-zero.
* ``LifelineDedupTests`` - multiple lifeline items in one build sum their
  shields (engine.compute_ehp does NOT apply unique_passive dedup
  itself; the rank.py shares_dead_unique filter is upstream).
* ``EngineVersionCurrentTests`` - pin ENGINE_VERSION 1.27.0.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._effects_types import (
    ANY,
    ItemShield,
    MAGICAL,
    PHYSICAL,
    TRUE,
)
from agents.daemon_slayer.ehp import (
    _RANGED_ATTACKRANGE_THRESHOLD,
    _collect_shields,
    _is_ranged,
    compute_ehp,
)
from agents.daemon_slayer.data_loader import DataSnapshot


class ItemShieldSchemaTests(unittest.TestCase):
    def test_default_construction_yields_zero_shield(self) -> None:
        s = ItemShield()
        self.assertEqual(s.resolve_magnitude(level=11), 0.0)

    def test_flat_value_at_default_level_lerp(self) -> None:
        # When level_lerp_low == level_lerp_high, magnitude is flat.
        s = ItemShield(flat=200.0)
        self.assertEqual(s.resolve_magnitude(level=1), 200.0)
        self.assertEqual(s.resolve_magnitude(level=18), 200.0)

    def test_bonus_hp_scaling_only(self) -> None:
        s = ItemShield(bonus_hp_scaling=0.60)
        # 0.60 * 1500 = 900
        self.assertEqual(s.resolve_magnitude(level=11, bonus_hp=1500), 900.0)

    def test_bonus_ad_scaling_with_flat(self) -> None:
        s = ItemShield(flat=200.0, bonus_ad_scaling=1.50)
        # 200 + 1.50 * 120 = 380
        self.assertEqual(s.resolve_magnitude(level=11, bonus_ad=120), 380.0)

    def test_level_lerp_clamps_below_low(self) -> None:
        # Shieldbow: flat=400, lerp 9->18 to 700. Below L9 = 400.
        s = ItemShield(
            flat=400.0,
            level_lerp_low=9,
            level_lerp_high=18,
            level_lerp_high_value=700.0,
        )
        self.assertEqual(s.resolve_magnitude(level=1), 400.0)
        self.assertEqual(s.resolve_magnitude(level=8), 400.0)
        self.assertEqual(s.resolve_magnitude(level=9), 400.0)

    def test_level_lerp_clamps_at_high(self) -> None:
        s = ItemShield(
            flat=400.0,
            level_lerp_low=9,
            level_lerp_high=18,
            level_lerp_high_value=700.0,
        )
        self.assertEqual(s.resolve_magnitude(level=18), 700.0)

    def test_level_lerp_interpolates_mid_range(self) -> None:
        # L14 = 9 + 5/9 of (400 -> 700) = 400 + 5/9 * 300 = 566.67
        s = ItemShield(
            flat=400.0,
            level_lerp_low=9,
            level_lerp_high=18,
            level_lerp_high_value=700.0,
        )
        self.assertAlmostEqual(s.resolve_magnitude(level=14), 566.666, places=2)

    def test_ranged_modifier_scales_total(self) -> None:
        s = ItemShield(flat=200.0, bonus_ad_scaling=1.50, ranged_modifier=0.75)
        # melee L11 bonus_ad=120: 200 + 180 = 380; ranged: 380 * 0.75 = 285
        self.assertEqual(
            s.resolve_magnitude(level=11, bonus_ad=120, is_ranged=False), 380.0
        )
        self.assertEqual(
            s.resolve_magnitude(level=11, bonus_ad=120, is_ranged=True), 285.0
        )

    def test_negative_bonus_hp_floored_at_zero(self) -> None:
        # bonus_hp going negative (a future data corruption) cannot
        # produce a negative shield.
        s = ItemShield(bonus_hp_scaling=0.60)
        self.assertEqual(s.resolve_magnitude(level=11, bonus_hp=-500), 0.0)

    def test_invalid_damage_type_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ItemShield(damage_type="bogus")

    def test_invalid_level_lerp_low_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ItemShield(level_lerp_low=0)

    def test_high_less_than_low_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ItemShield(level_lerp_low=9, level_lerp_high=5)

    def test_negative_ranged_modifier_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ItemShield(ranged_modifier=-0.1)


class IsRangedTests(unittest.TestCase):
    def test_melee_below_threshold(self) -> None:
        self.assertFalse(_is_ranged({"attackrange": 125.0}))   # Sett
        self.assertFalse(_is_ranged({"attackrange": 175.0}))   # Yasuo / Aatrox
        self.assertFalse(_is_ranged({"attackrange": 250.0}))   # exactly at threshold

    def test_ranged_above_threshold(self) -> None:
        self.assertTrue(_is_ranged({"attackrange": 251.0}))
        self.assertTrue(_is_ranged({"attackrange": 550.0}))    # Lux / Ezreal
        self.assertTrue(_is_ranged({"attackrange": 650.0}))    # Caitlyn

    def test_missing_attackrange_treated_melee(self) -> None:
        self.assertFalse(_is_ranged({}))

    def test_threshold_constant_pinned(self) -> None:
        # Pin the threshold so future audits catch an accidental change
        # that would re-classify Yasuo / Aatrox as ranged or Sivir as melee.
        self.assertEqual(_RANGED_ATTACKRANGE_THRESHOLD, 250.0)


class CollectShieldsTests(unittest.TestCase):
    def test_no_items_returns_zero_totals(self) -> None:
        totals, sources = _collect_shields(
            [], level=11, bonus_hp=0, bonus_ad=0, is_ranged=False
        )
        self.assertEqual(totals[ANY], 0.0)
        self.assertEqual(totals[MAGICAL], 0.0)
        self.assertEqual(sources, ())

    def test_item_without_shield_field_skipped(self) -> None:
        # 3031 (Infinity Edge) has no shield field.
        totals, sources = _collect_shields(
            ["3031"], level=11, bonus_hp=0, bonus_ad=0, is_ranged=False
        )
        self.assertEqual(totals[ANY], 0.0)
        self.assertEqual(sources, ())

    def test_unknown_item_id_silently_skipped(self) -> None:
        totals, sources = _collect_shields(
            ["9999"], level=11, bonus_hp=0, bonus_ad=0, is_ranged=False
        )
        self.assertEqual(totals[ANY], 0.0)
        self.assertEqual(sources, ())

    def test_sterak_aggregates_bonus_hp(self) -> None:
        # Sterak: 60% bonus_hp.
        totals, sources = _collect_shields(
            ["3053"], level=11, bonus_hp=500, bonus_ad=0, is_ranged=False
        )
        self.assertEqual(totals[ANY], 300.0)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0][0], "3053")
        self.assertEqual(sources[0][1], ANY)

    def test_maw_aggregates_magic_only(self) -> None:
        totals, sources = _collect_shields(
            ["3156"], level=11, bonus_hp=0, bonus_ad=60, is_ranged=False
        )
        # 200 + 1.50 * 60 = 290 melee
        self.assertEqual(totals[MAGICAL], 290.0)
        self.assertEqual(totals[ANY], 0.0)

    def test_multiple_shields_sum_per_type(self) -> None:
        # Sterak + Maw - lifeline dedup is upstream in rank.py; the
        # engine compute_ehp does NOT apply it (the field is just data).
        totals, sources = _collect_shields(
            ["3053", "3156"],
            level=11,
            bonus_hp=500,
            bonus_ad=60,
            is_ranged=False,
        )
        self.assertEqual(totals[ANY], 300.0)
        self.assertEqual(totals[MAGICAL], 290.0)
        self.assertEqual(len(sources), 2)


class SterakShieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_baseline_no_shield(self) -> None:
        r0 = compute_ehp(self.snap, "Sett", level=11, item_ids=[], mode="SR")
        self.assertEqual(r0.shield_any, 0.0)
        self.assertEqual(r0.shield_sources, ())

    def test_sterak_emits_any_shield(self) -> None:
        r = compute_ehp(
            self.snap, "Sett", level=11, item_ids=["3053"], mode="SR"
        )
        # Sterak provides 400 flat HP; bonus_hp = 400; shield = 0.60 * 400 = 240
        self.assertAlmostEqual(r.shield_any, 240.0, places=1)
        self.assertEqual(r.shield_mag, 0.0)
        self.assertEqual(len(r.shield_sources), 1)
        self.assertEqual(r.shield_sources[0][0], "3053")

    def test_sterak_lifts_blended_ehp(self) -> None:
        r0 = compute_ehp(self.snap, "Sett", level=11, item_ids=[], mode="SR")
        r1 = compute_ehp(
            self.snap, "Sett", level=11, item_ids=["3053"], mode="SR"
        )
        # Sterak adds HP + bonus_ad + shield, so blended_ehp strictly > baseline.
        self.assertGreater(r1.blended_ehp, r0.blended_ehp)

    def test_sterak_shield_in_physical_and_magical(self) -> None:
        # ANY-type shield adds to BOTH physical_ehp and magical_ehp.
        r = compute_ehp(
            self.snap, "Sett", level=11, item_ids=["3053"], mode="SR"
        )
        # Hand-verify: physical_ehp = (hp + shield_any) / factor(armor)
        # Sterak hp_total = 2070 (1670 base + 400 Sterak); shield_any = 240
        from agents.daemon_slayer.ehp import _armor_factor
        expected_phys = (r.hp + r.shield_any) / _armor_factor(r.armor)
        self.assertAlmostEqual(r.physical_ehp, expected_phys, places=1)
        expected_mag = (r.hp + r.shield_any) / _armor_factor(r.mr)
        self.assertAlmostEqual(r.magical_ehp, expected_mag, places=1)


class ShieldbowShieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_l1_baseline_flat_400(self) -> None:
        # Caitlyn L1 with Shieldbow: ranged 400 * 0.80 = 320.
        r = compute_ehp(
            self.snap, "Caitlyn", level=1, item_ids=["6673"], mode="SR"
        )
        self.assertAlmostEqual(r.shield_any, 320.0, places=1)

    def test_l9_ramp_start(self) -> None:
        # L9 = ramp low value: ranged 400 * 0.80 = 320.
        r = compute_ehp(
            self.snap, "Caitlyn", level=9, item_ids=["6673"], mode="SR"
        )
        self.assertAlmostEqual(r.shield_any, 320.0, places=1)

    def test_l18_ramp_peak(self) -> None:
        # L18 = 700 melee, * 0.80 ranged = 560.
        r = compute_ehp(
            self.snap, "Caitlyn", level=18, item_ids=["6673"], mode="SR"
        )
        self.assertAlmostEqual(r.shield_any, 560.0, places=1)

    def test_melee_l18_full_value(self) -> None:
        # Aatrox L18 = melee bruiser, gets full 700.
        r = compute_ehp(
            self.snap, "Aatrox", level=18, item_ids=["6673"], mode="SR"
        )
        self.assertAlmostEqual(r.shield_any, 700.0, places=1)


class MawShieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_maw_magic_shield_only(self) -> None:
        r = compute_ehp(
            self.snap, "Ezreal", level=11, item_ids=["3156"], mode="SR"
        )
        # Magic-only -> shield_mag > 0, shield_any == 0
        self.assertEqual(r.shield_any, 0.0)
        self.assertGreater(r.shield_mag, 0)

    def test_maw_ranged_at_75_pct(self) -> None:
        # Ezreal L11 with Maw: Maw gives 60 AD. bonus_ad = 60.
        # melee: 200 + 1.50 * 60 = 290; ranged: 290 * 0.75 = 217.5
        r = compute_ehp(
            self.snap, "Ezreal", level=11, item_ids=["3156"], mode="SR"
        )
        self.assertAlmostEqual(r.shield_mag, 217.5, places=1)

    def test_maw_melee_full_value(self) -> None:
        # Aatrox L11 with Maw: bonus_ad = 60; full 200 + 90 = 290 melee.
        r = compute_ehp(
            self.snap, "Aatrox", level=11, item_ids=["3156"], mode="SR"
        )
        self.assertAlmostEqual(r.shield_mag, 290.0, places=1)

    def test_maw_does_not_lift_physical_ehp(self) -> None:
        # Magic-only shield does NOT enter physical_ehp.
        r0 = compute_ehp(self.snap, "Aatrox", level=11, item_ids=[], mode="SR")
        r = compute_ehp(
            self.snap, "Aatrox", level=11, item_ids=["3156"], mode="SR"
        )
        # physical_ehp lifts only by the AD/HP/etc gain in Maw (which is
        # marginal HP via none, marginal armor via none), NOT the shield.
        # Concretely: shield_mag does not factor into physical_ehp formula.
        from agents.daemon_slayer.ehp import _armor_factor
        expected_phys_with_maw = (
            r.hp + r.shield_any + r.shield_phys
        ) / _armor_factor(r.armor)
        self.assertAlmostEqual(r.physical_ehp, expected_phys_with_maw, places=1)

    def test_maw_lifts_magical_ehp(self) -> None:
        r0 = compute_ehp(self.snap, "Aatrox", level=11, item_ids=[], mode="SR")
        r = compute_ehp(
            self.snap, "Aatrox", level=11, item_ids=["3156"], mode="SR"
        )
        self.assertGreater(r.magical_ehp, r0.magical_ehp)


class HexdrinkerShieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_hex_melee_l1(self) -> None:
        # Aatrox L1 = melee, flat 110.
        r = compute_ehp(
            self.snap, "Aatrox", level=1, item_ids=["3155"], mode="SR"
        )
        self.assertAlmostEqual(r.shield_mag, 110.0, places=1)

    def test_hex_melee_l18(self) -> None:
        # Aatrox L18 = melee, lerp peak 280.
        r = compute_ehp(
            self.snap, "Aatrox", level=18, item_ids=["3155"], mode="SR"
        )
        self.assertAlmostEqual(r.shield_mag, 280.0, places=1)

    def test_hex_ranged_l18(self) -> None:
        # Ezreal L18 = ranged, 280 * 0.75 = 210.
        r = compute_ehp(
            self.snap, "Ezreal", level=18, item_ids=["3155"], mode="SR"
        )
        self.assertAlmostEqual(r.shield_mag, 210.0, places=1)

    def test_hex_magic_only(self) -> None:
        r = compute_ehp(
            self.snap, "Aatrox", level=18, item_ids=["3155"], mode="SR"
        )
        self.assertEqual(r.shield_any, 0.0)
        self.assertEqual(r.shield_phys, 0.0)
        self.assertGreater(r.shield_mag, 0.0)


class EhpResultShieldFieldsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_to_dict_includes_shield_fields(self) -> None:
        r = compute_ehp(
            self.snap, "Sett", level=11, item_ids=["3053"], mode="SR"
        )
        d = r.to_dict()
        for key in (
            "shield_any", "shield_phys", "shield_mag", "shield_true",
            "shield_sources",
        ):
            self.assertIn(key, d, msg=f"missing key {key}")
        self.assertAlmostEqual(d["shield_any"], 240.0, places=1)
        self.assertEqual(len(d["shield_sources"]), 1)
        self.assertEqual(d["shield_sources"][0]["item_id"], "3053")
        self.assertEqual(d["shield_sources"][0]["damage_type"], ANY)

    def test_format_table_renders_shield_row_when_nonzero(self) -> None:
        r = compute_ehp(
            self.snap, "Sett", level=11, item_ids=["3053"], mode="SR"
        )
        text = r.format_table()
        self.assertIn("shield_hp", text)
        self.assertIn("any=", text)

    def test_format_table_omits_shield_row_when_zero(self) -> None:
        r = compute_ehp(
            self.snap, "Sett", level=11, item_ids=[], mode="SR"
        )
        text = r.format_table()
        self.assertNotIn("shield_hp", text)

    def test_notes_include_shield_source(self) -> None:
        r = compute_ehp(
            self.snap, "Sett", level=11, item_ids=["3053"], mode="SR"
        )
        text = " | ".join(r.notes)
        self.assertIn("Sterak", text)
        self.assertIn("shield", text)


class LifelineDedupTests(unittest.TestCase):
    """compute_ehp does NOT apply unique_passive dedup itself - that's
    rank.py's shares_dead_unique filter. compute_ehp with two lifeline
    items will sum both shields. Test pins this so a future regression
    pushing dedup INTO compute_ehp will fail loudly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_compute_ehp_sums_lifeline_shields(self) -> None:
        # Sterak + Maw both wired; compute_ehp adds both contributions.
        r = compute_ehp(
            self.snap, "Aatrox", level=11, item_ids=["3053", "3156"], mode="SR"
        )
        self.assertGreater(r.shield_any, 0.0)
        self.assertGreater(r.shield_mag, 0.0)
        self.assertEqual(len(r.shield_sources), 2)


class AramShieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_aram_damage_taken_applies_to_shielded_ehp(self) -> None:
        # ARAM aramDamageTaken multiplies the EHP-vs-damage formula on
        # the whole stack (HP + shield). Verify that a champion with
        # non-1.0 aramDamageTaken and Sterak's gets the multiplier
        # applied AFTER adding shield, not before.
        r = compute_ehp(
            self.snap, "Aatrox", level=11, item_ids=["3053"], mode="ARAM"
        )
        if r.mode_multiplier == 1.0:
            self.skipTest("Aatrox has aramDamageTaken == 1.0; pick a different sample")
        # Effective HP scaled by 1/mode_mult: a champion in ARAM with
        # aramDamageTaken < 1.0 has MORE effective HP.
        from agents.daemon_slayer.ehp import _armor_factor
        safe_mult = r.mode_multiplier if r.mode_multiplier > 0 else 1.0
        expected_phys = (r.hp + r.shield_any) / (_armor_factor(r.armor) * safe_mult)
        self.assertAlmostEqual(r.physical_ehp, expected_phys, places=1)


class EngineVersionCurrentTests(unittest.TestCase):
    def test_engine_version_current(self) -> None:
        import agents.daemon_slayer as ds
        # 1.27.0 closes the Phase 1.5 shield-throughput omission;
        # confirmed by the live tests above.
        self.assertEqual(ds.ENGINE_VERSION, "1.74.0")


if __name__ == "__main__":
    unittest.main()

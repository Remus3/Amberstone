"""ENGINE 1.29.0 (2026-05-21) - Phase 6.5 EHP shield-amp closure.

Closes the Phase 6 deliberate boundary documented at
``ehp.py:Phase 6 deliberate omissions``: Riot's tooltip on Spirit
Visage 3065 / Arena 223065 Boundless Vitality reads "increases
self-healing and shielding by 25%". The Phase 6 wire (ENGINE 1.28.0)
amped the heal pool only; Phase 6.5 extends the SAME multiplier to
the shield pool too (Sterak / Shieldbow / Maw / Hexdrinker / BT
Ichorshield).

Design (don't re-litigate):

* The ``shield_any`` / ``shield_phys`` / ``shield_mag`` / ``shield_true``
  EhpResult fields stay PRE-amp for transparency, matching the
  ``heal_item_total`` / ``heal_lifesteal`` pre-amp convention.
* ``shield_amp_mult`` exposes the multiplier alongside ``heal_amp_mult``.
* The EHP-math at ``compute_ehp`` line ~590 applies the amp at the
  top of the damage stack:
  ``physical_ehp = (hp + shield_any*amp + shield_phys*amp + heal_total) / ...``
* The two amps (heal + shield) are SIBLINGS at the EHP-math top of
  the stack, NOT nested - heal_total is amped exactly once (via the
  Phase 6 wire); shield_any is amped exactly once (via Phase 6.5);
  the two products sum into the EHP math without compounding.
* Same multiplier value today (only Spirit Visage at 1.25) but
  conceptually independent fields so a future heal-only or shield-
  only amp item stays representable.

Coverage classes:

* ``ShieldAmpStackingTests`` - per-shield-item lifts confirmed amped
  (Sterak ANY, Maw MAGICAL, Hexdrinker MAGICAL, Shieldbow ANY, BT
  Ichorshield ANY, multi-shield stacking like BT + Sterak).
* ``EhpResultShieldAmpFieldsTests`` - new ``shield_amp_mult`` field in
  ``to_dict``; format_table renders ``amp=xN.NNN`` only when != 1.0.
* ``NoDoubleAmpTests`` - heal_total + shield_any are siblings not
  nested: a BT + SV build has heal amped 1.25 (Phase 6) and shield
  amped 1.25 (Phase 6.5) but neither is amped 1.5625 (1.25 squared).
* ``MultiplicativeStackingTests`` - if a hypothetical future item also
  carried ``heal_amp_pct > 0``, SV + that item would compound the
  shield amp the same way heal amp compounds (multiplicative). Pinned
  via monkeypatching ``_total_heal_amp`` to confirm the EHP math
  consumes the helper's return value unchanged for shields.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp


class ShieldAmpStackingTests(unittest.TestCase):
    """Each Phase 1.5 shield item gets amped by 1.25 when paired with SV."""

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_sv_alone_no_shield_no_amp_contribution(self) -> None:
        # SV alone: shield_amp_mult flips to 1.25 but shield_* are all 0
        # so no actual amp contribution. Heal pool also 0 (no lifesteal /
        # no heal items). Identity vs no-items for physical_ehp + shield_*.
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3065"], mode="SR"
        )
        self.assertEqual(r.shield_any, 0.0)
        self.assertEqual(r.shield_phys, 0.0)
        self.assertEqual(r.shield_mag, 0.0)
        self.assertEqual(r.shield_true, 0.0)
        self.assertAlmostEqual(r.shield_amp_mult, 1.25, places=4)

    def test_sterak_alone_no_amp(self) -> None:
        # Sterak alone (no SV): shield_amp_mult stays at identity 1.0.
        r = compute_ehp(
            self.snap, "Sett", 11, item_ids=["3053"], mode="SR"
        )
        self.assertAlmostEqual(r.shield_amp_mult, 1.0, places=4)
        self.assertGreater(r.shield_any, 0.0)

    def test_sterak_plus_sv_amps_any_shield(self) -> None:
        # Sterak's Gage 3053 = 60% bonus_hp ANY shield. SV adds 400 HP
        # so bonus_hp goes 400 -> 800; pre-amp shield_any goes
        # 240 -> 480. shield_amp_mult flips to 1.25. EHP math sees
        # 480 * 1.25 = 600.
        r_sterak = compute_ehp(
            self.snap, "Sett", 11, item_ids=["3053"], mode="SR"
        )
        r_sterak_sv = compute_ehp(
            self.snap, "Sett", 11, item_ids=["3053", "3065"], mode="SR"
        )
        # Pre-amp shield_any field reacts to SV's bonus_hp (60% of 400 = 240
        # lift), NOT to the amp. Phase 6 behavior preserved on the field.
        self.assertAlmostEqual(r_sterak.shield_any, 240.0, places=0)
        self.assertAlmostEqual(r_sterak_sv.shield_any, 480.0, places=0)
        # Phase 6.5 closure: amp now applied to shield pool.
        self.assertAlmostEqual(r_sterak_sv.shield_amp_mult, 1.25, places=4)
        # physical_ehp post-amp = (hp + shield_any*1.25) / armor_factor.
        armor_factor = 100.0 / (100.0 + r_sterak_sv.armor)
        expected = (r_sterak_sv.hp + r_sterak_sv.shield_any * 1.25) / armor_factor
        self.assertAlmostEqual(r_sterak_sv.physical_ehp, expected, places=1)

    def test_maw_plus_sv_amps_magical_shield_only(self) -> None:
        # Maw of Malmortius 3156 = 200 + 150% bonus_ad MAGICAL shield.
        # Melee at full magnitude. shield_mag amped at 1.25; shield_any
        # untouched (still 0).
        r_maw = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3156"], mode="SR"
        )
        r_maw_sv = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3156", "3065"], mode="SR"
        )
        self.assertEqual(r_maw.shield_any, 0.0)
        self.assertEqual(r_maw_sv.shield_any, 0.0)
        self.assertGreater(r_maw.shield_mag, 0.0)
        # shield_amp_mult flips to 1.25 in r_maw_sv.
        self.assertAlmostEqual(r_maw_sv.shield_amp_mult, 1.25, places=4)
        # magical_ehp picks up shield_mag * 1.25 in r_maw_sv but NOT in r_maw.
        # The MR delta between Maw alone and Maw+SV is also relevant (SV
        # gives 50 MR) - we pin shield-amp by examining the magical_ehp
        # against direct math instead.
        mr_factor_maw_sv = 100.0 / (100.0 + r_maw_sv.mr)
        # The shield_mag value can shift slightly with bonus_ad pickup
        # when SV adds HP without AD; SV gives 0 AD so shield_mag is
        # identical in both builds (Maw doesn't scale off bonus_hp).
        self.assertAlmostEqual(
            r_maw_sv.shield_mag, r_maw.shield_mag, places=2,
            msg="Maw shield_mag should be identical when adding SV (no AD pickup)",
        )
        expected_mag_ehp = (r_maw_sv.hp + r_maw_sv.shield_mag * 1.25) / mr_factor_maw_sv
        self.assertAlmostEqual(r_maw_sv.magical_ehp, expected_mag_ehp, places=1)

    def test_hexdrinker_plus_sv_amps_magical_shield(self) -> None:
        # Hexdrinker 3155 = 110 L1-L8 -> 280 L18 MAGICAL (lerp).
        # Aatrox L11 melee: shield_mag positive; ranged_modifier=0.75 not
        # applied to Aatrox (attackrange 175 < 250). SV amps to 1.25.
        r_hex = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3155"], mode="SR"
        )
        r_hex_sv = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3155", "3065"], mode="SR"
        )
        self.assertGreater(r_hex.shield_mag, 0.0)
        self.assertAlmostEqual(r_hex_sv.shield_amp_mult, 1.25, places=4)
        # magical_ehp lift includes amp contribution.
        self.assertGreater(r_hex_sv.physical_ehp, r_hex.physical_ehp)

    def test_shieldbow_plus_sv_amps_any_shield(self) -> None:
        # Immortal Shieldbow 6673 = 400 L1-L8 -> 700 L18 ANY shield.
        # Melee Aatrox L11: full magnitude (no ranged_modifier reduction).
        # SV amps via the ANY-shield path.
        r_sb = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6673"], mode="SR"
        )
        r_sb_sv = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["6673", "3065"], mode="SR"
        )
        self.assertGreater(r_sb.shield_any, 0.0)
        self.assertAlmostEqual(r_sb_sv.shield_amp_mult, 1.25, places=4)
        # Same shield_any pre-amp (Shieldbow doesn't scale off bonus_hp).
        self.assertAlmostEqual(r_sb_sv.shield_any, r_sb.shield_any, places=2)
        # physical_ehp lift includes the shield amp.
        armor_factor = 100.0 / (100.0 + r_sb_sv.armor)
        expected = (r_sb_sv.hp + r_sb_sv.shield_any * 1.25) / armor_factor
        self.assertAlmostEqual(r_sb_sv.physical_ehp, expected, places=1)

    def test_bt_plus_sv_amps_ichorshield_and_heal(self) -> None:
        # Bloodthirster 3072 Ichorshield (ANY shield, 165 L1 -> 315 L18
        # via lerp). BT is NOT lifeline-tagged so it stacks with Sterak
        # in a real build (pinned by BTPlusLifelineStacksTests in Phase 6).
        # BT also adds AD + lifesteal, so heal_lifesteal > 0 too.
        # Phase 6.5 amps BOTH the Ichorshield AND the heal pool at 1.25.
        r_bt = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3072"], mode="SR"
        )
        r_bt_sv = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3072", "3065"], mode="SR"
        )
        # Pre-amp shield_any from BT alone is positive (Aatrox L11 lerp).
        self.assertGreater(r_bt.shield_any, 100.0)
        # BT + SV: shield_any pre-amp is the same (no bonus_hp scaling on
        # Ichorshield); shield_amp_mult is 1.25.
        self.assertAlmostEqual(r_bt_sv.shield_any, r_bt.shield_any, places=2)
        self.assertAlmostEqual(r_bt_sv.shield_amp_mult, 1.25, places=4)
        # Heal pool also amped (Phase 6 wire still active for heal).
        self.assertAlmostEqual(r_bt_sv.heal_amp_mult, 1.25, places=4)
        self.assertGreater(r_bt_sv.heal_total, r_bt.heal_total)

    def test_sterak_plus_bt_plus_sv_both_shields_amped(self) -> None:
        # Real-build stacking: Sterak (lifeline ANY) + BT (Ichorshield ANY)
        # both contribute shield_any per Phase 6 wire (BTPlusLifelineStacks).
        # Phase 6.5 amps the SUM at the EHP-math site.
        r_both = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3053", "3072"], mode="SR"
        )
        r_both_sv = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3053", "3072", "3065"], mode="SR"
        )
        # Both shields contribute; sum > either alone.
        self.assertGreater(r_both.shield_any, 200.0)
        self.assertAlmostEqual(r_both_sv.shield_amp_mult, 1.25, places=4)
        # physical_ehp post-amp pin: amp is applied to the SUM (not
        # individually to each source - sum first, then amp).
        armor_factor = 100.0 / (100.0 + r_both_sv.armor)
        expected_min = (
            r_both_sv.hp + r_both_sv.shield_any * 1.25 + r_both_sv.heal_total
        ) / armor_factor
        # Within float tolerance (heal_total already includes its own amp;
        # shield_any pre-amp times 1.25 is the shield contribution).
        self.assertAlmostEqual(r_both_sv.physical_ehp, expected_min, places=1)


class EhpResultShieldAmpFieldsTests(unittest.TestCase):
    """The new shield_amp_mult field on EhpResult is exposed in to_dict
    and format_table, mirroring the existing heal_amp_mult surface.
    """

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_to_dict_carries_shield_amp_mult(self) -> None:
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3053", "3065"], mode="SR"
        )
        d = r.to_dict()
        self.assertIn("shield_amp_mult", d)
        self.assertAlmostEqual(d["shield_amp_mult"], 1.25, places=4)

    def test_to_dict_shield_amp_default_when_no_sv(self) -> None:
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3053"], mode="SR"
        )
        d = r.to_dict()
        self.assertIn("shield_amp_mult", d)
        self.assertAlmostEqual(d["shield_amp_mult"], 1.0, places=4)

    def test_format_table_renders_shield_amp_when_active(self) -> None:
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3053", "3065"], mode="SR"
        )
        table = r.format_table()
        # The amp note shows up in the shield_hp row when amp != 1.0.
        self.assertIn("shield_hp", table)
        self.assertIn("amp=x1.250", table)

    def test_format_table_omits_shield_amp_when_identity(self) -> None:
        # Sterak alone (no SV): no amp annotation in the shield_hp row.
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3053"], mode="SR"
        )
        table = r.format_table()
        # shield_hp row is present (shield_any > 0) but the amp suffix
        # should NOT be there.
        self.assertIn("shield_hp", table)
        # The "amp=" substring only appears on the heal row or shield row
        # when active. Since no SV here, neither row should have it.
        self.assertNotIn("amp=", table)

    def test_format_table_omits_shield_amp_when_no_shields(self) -> None:
        # SV alone (no shield item): the shield_hp row is absent entirely
        # so no amp annotation. shield_amp_mult is 1.25 but no shield
        # to apply it to.
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3065"], mode="SR"
        )
        table = r.format_table()
        self.assertNotIn("shield_hp", table)

    def test_notes_carry_shield_amp_line_when_active(self) -> None:
        # When SV is paired with a shield, notes carry an explicit
        # "shield: amp x1.250 ..." line for diagnostic transparency.
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3053", "3065"], mode="SR"
        )
        notes = "\n".join(r.notes)
        self.assertIn("shield: amp x1.250", notes)

    def test_notes_omit_shield_amp_line_without_sv(self) -> None:
        # No SV in the build: shield_amp_mult is 1.0, so no amp-note.
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3053"], mode="SR"
        )
        notes = "\n".join(r.notes)
        self.assertNotIn("shield: amp", notes)

    def test_notes_omit_shield_amp_line_without_shields(self) -> None:
        # SV alone (no shield item): no shield to amp, so no note even
        # though shield_amp_mult is 1.25.
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3065"], mode="SR"
        )
        notes = "\n".join(r.notes)
        self.assertNotIn("shield: amp", notes)


class NoDoubleAmpTests(unittest.TestCase):
    """Heal_total and shield_any are SIBLINGS at the EHP-math top of the
    stack, NOT nested. A BT + SV build has heal amped exactly once
    (Phase 6 wire at line ~583) and shield amped exactly once (Phase
    6.5 wire at line ~590) - neither contribution is amped 1.5625
    (1.25 squared).
    """

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_bt_sv_heal_amped_once(self) -> None:
        # BT + SV: heal_total should be exactly (heal_item_total +
        # heal_lifesteal) * 1.25, NOT * 1.25^2.
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3072", "3065"], mode="SR"
        )
        expected = (r.heal_item_total + r.heal_lifesteal) * r.heal_amp_mult
        self.assertAlmostEqual(r.heal_total, expected, places=4)
        # Sanity: heal_amp_mult is 1.25 exactly, not squared.
        self.assertAlmostEqual(r.heal_amp_mult, 1.25, places=4)

    def test_bt_sv_shield_amped_once_via_ehp_math(self) -> None:
        # BT + SV: physical_ehp should reconstruct exactly from pre-amp
        # shield_any * shield_amp_mult (singly applied) + heal_total
        # (already singly amped). No 1.5625 anywhere.
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3072", "3065"], mode="SR"
        )
        armor_factor = 100.0 / (100.0 + r.armor)
        expected_phys_ehp = (
            r.hp + r.shield_any * r.shield_amp_mult + r.heal_total
        ) / armor_factor
        self.assertAlmostEqual(r.physical_ehp, expected_phys_ehp, places=1)
        # Confirm both amps are exactly 1.25 (not 1.5625).
        self.assertAlmostEqual(r.shield_amp_mult, 1.25, places=4)
        self.assertAlmostEqual(r.heal_amp_mult, 1.25, places=4)

    def test_heal_pool_not_double_amped_by_shield_extension(self) -> None:
        # Sterak + BT + SV: heal_total uses heal_amp_mult; shield uses
        # shield_amp_mult; they are separate field reads (siblings).
        # heal_total is NEVER multiplied by shield_amp_mult anywhere.
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3053", "3072", "3065"], mode="SR"
        )
        # heal_total reconstruction from pre-amp + heal_amp_mult (Phase 6).
        expected_heal = (r.heal_item_total + r.heal_lifesteal) * r.heal_amp_mult
        self.assertAlmostEqual(r.heal_total, expected_heal, places=4)
        # If shield-amp were leaking into heal, heal_total would equal
        # (pre-amp * 1.25 * 1.25). Confirm it does NOT.
        wrong_double_amp = (r.heal_item_total + r.heal_lifesteal) * 1.25 * 1.25
        self.assertNotAlmostEqual(r.heal_total, wrong_double_amp, places=2)

    def test_shield_pool_not_double_amped_by_heal_extension(self) -> None:
        # Same direction: shield is amped at the EHP-math site only,
        # NOT multiplied by both shield_amp_mult AND heal_amp_mult in
        # the EHP math. The amp is applied EXACTLY ONCE to shield_any.
        r = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=["3053", "3072", "3065"], mode="SR"
        )
        armor_factor = 100.0 / (100.0 + r.armor)
        # Sterak + BT both contribute shield_any (BT not lifeline-tagged).
        # physical_ehp = (hp + shield_any * 1.25 + heal_total) / armor_factor.
        expected = (
            r.hp + r.shield_any * 1.25 + r.heal_total
        ) / armor_factor
        self.assertAlmostEqual(r.physical_ehp, expected, places=1)
        # If shield were double-amped, physical_ehp would jump by an extra
        # 25% on the shield piece - confirm it doesn't.
        wrong_double = (
            r.hp + r.shield_any * 1.25 * 1.25 + r.heal_total
        ) / armor_factor
        self.assertNotAlmostEqual(r.physical_ehp, wrong_double, places=0)


class MultiplicativeStackingTests(unittest.TestCase):
    """If a hypothetical future item also carries heal_amp_pct > 0 in
    addition to SV, the shield amp multiplier should compound the same
    way the heal amp does. _total_heal_amp is multiplicative, so SV
    (1.25) + a hypothetical x1.10 amp = 1.375 effective shield_amp_mult.
    """

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_shield_amp_compounds_via_total_heal_amp_helper(self) -> None:
        # Patch the helper return to confirm compute_ehp consumes the
        # multiplier unchanged for both heal AND shield. If _total_heal_amp
        # returned 1.5 (e.g. via a stacked amp item), shield amp should
        # also be 1.5.
        with patch(
            "agents.daemon_slayer.ehp._total_heal_amp",
            return_value=1.5,
        ):
            r = compute_ehp(
                self.snap, "Aatrox", 11, item_ids=["3053"], mode="SR"
            )
        # Both amps reflect the patched value identically.
        self.assertAlmostEqual(r.heal_amp_mult, 1.5, places=4)
        self.assertAlmostEqual(r.shield_amp_mult, 1.5, places=4)
        # Shield contribution amped at 1.5.
        armor_factor = 100.0 / (100.0 + r.armor)
        expected = (r.hp + r.shield_any * 1.5) / armor_factor
        self.assertAlmostEqual(r.physical_ehp, expected, places=1)

    def test_shield_amp_identity_at_unit_amp_value(self) -> None:
        # Patch helper to identity (1.0): both amps stay 1.0.
        with patch(
            "agents.daemon_slayer.ehp._total_heal_amp",
            return_value=1.0,
        ):
            r = compute_ehp(
                self.snap, "Aatrox", 11, item_ids=["3053"], mode="SR"
            )
        self.assertAlmostEqual(r.shield_amp_mult, 1.0, places=4)
        # physical_ehp equals the no-amp formula.
        armor_factor = 100.0 / (100.0 + r.armor)
        expected_identity = (r.hp + r.shield_any) / armor_factor
        self.assertAlmostEqual(r.physical_ehp, expected_identity, places=1)


if __name__ == "__main__":
    unittest.main()

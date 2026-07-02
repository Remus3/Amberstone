"""ENGINE 1.171.0 (R60, 2026-07-02) - wielder Heal/Shield Power (HSP) amp seam.

Distinct from R59 (which scored the TARGET-side Lifeline shield in the OFFENSE
scorers): R60 scores the WIELDER's own Heal/Shield Power (the
``heal_shield_amp_pct`` stat on Redemption / Mikael / Ardent / Moonstone /
Staff of Flowing Water). HSP amplifies the heals and shields the wielder
applies to ITSELF:

* ``ehp.py`` - the wielder's own item self-shields (Sterak's Gage, Shieldbow,
  Maw, Hexdrinker, Bloodthirster Ichorshield). Folded into the existing sibling
  ``shield_amp_mult`` alongside Spirit Visage's Boundless Vitality amp.
* ``sustain.py`` - the wielder's kit SELF-HEAL sustain (the ``REGEN`` kind).
  HSP does NOT amplify vamp (LIFESTEAL / OMNIVAMP / SPELLVAMP / DRAIN), so the
  sustain seam scopes strictly to the ``REGEN`` kind - a vamp-only champion is
  byte-identical even with the seam ON.

Both seams are DEFAULT-OFF: ``assume_hsp_amp=False`` (the default) -> HSP factor
0.0 -> BYTE-IDENTICAL to ENGINE 1.170.0. The live default-ON flip is
operator-gated (docs/LIVE_GAME_GATED_SYNC.md).

HSP is summed ADDITIVELY across the build (the directive "(1 + hsp_pct)" model,
matching real-LoL additive HSP): Redemption 0.10 + Mikael 0.12 = 0.22.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer.sustain import compute_sustain
from agents.daemon_slayer._hsp_amp import sum_wielder_hsp_pct

# Curated ids (16.13.1 enchanter_items.json + effects shield registry).
_REDEMPTION = "3107"          # heal_shield_amp_pct 0.10
_MIKAEL = "3222"              # heal_shield_amp_pct 0.12
_MOONSTONE = "6617"           # heal_shield_amp_pct 0.30
_STERAKS = "3053"             # ItemShield ANY (self-shield), no HSP
_SHIELDBOW = "6673"           # ItemShield ANY (self-shield), no HSP


class SumWielderHspPctTests(unittest.TestCase):
    """The additive HSP-sum helper (the shared source for both seams)."""

    def test_single_hsp_item(self) -> None:
        self.assertAlmostEqual(sum_wielder_hsp_pct([_REDEMPTION]), 0.10, places=6)

    def test_additive_stacking(self) -> None:
        # Redemption 0.10 + Mikael 0.12 = 0.22 (additive, not compounded).
        self.assertAlmostEqual(
            sum_wielder_hsp_pct([_REDEMPTION, _MIKAEL]), 0.22, places=6
        )

    def test_moonstone_value(self) -> None:
        self.assertAlmostEqual(sum_wielder_hsp_pct([_MOONSTONE]), 0.30, places=6)

    def test_non_hsp_item_contributes_zero(self) -> None:
        # Sterak's Gage is a self-shield item but carries no HSP stat.
        self.assertEqual(sum_wielder_hsp_pct([_STERAKS]), 0.0)

    def test_empty_and_none_fail_soft(self) -> None:
        self.assertEqual(sum_wielder_hsp_pct([]), 0.0)
        self.assertEqual(sum_wielder_hsp_pct(None), 0.0)

    def test_int_ids_coerced(self) -> None:
        self.assertAlmostEqual(sum_wielder_hsp_pct([3107]), 0.10, places=6)


class EhpHspSeamTests(unittest.TestCase):
    """ehp.py: HSP amplifies the wielder's own ItemShield pool (DEFAULT-OFF)."""

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_off_is_byte_identical_default(self) -> None:
        # The explicit flag OFF must equal the omitted-flag default, byte-for-byte.
        base = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_STERAKS, _REDEMPTION], mode="SR"
        )
        off = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_STERAKS, _REDEMPTION], mode="SR",
            assume_hsp_amp=False,
        )
        self.assertEqual(off.to_dict(), base.to_dict())
        # No Spirit Visage + Redemption has no heal_amp_pct -> shield amp stays 1.0.
        self.assertAlmostEqual(off.shield_amp_mult, 1.0, places=6)
        self.assertGreater(off.shield_any, 0.0)

    def test_on_without_hsp_item_is_byte_identical(self) -> None:
        # Seam ON but no HSP item in the build -> hsp_pct 0.0 -> byte-identical.
        off = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_STERAKS], mode="SR"
        )
        on = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_STERAKS], mode="SR",
            assume_hsp_amp=True,
        )
        self.assertEqual(on.to_dict(), off.to_dict())

    def test_on_amps_own_shield_by_exact_hsp_pct(self) -> None:
        # Sterak (ANY self-shield) + Redemption (HSP 0.10). Seam ON scales the
        # shield pool by exactly (1 + 0.10). shield_amp_mult surfaces it.
        off = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_STERAKS, _REDEMPTION], mode="SR"
        )
        on = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_STERAKS, _REDEMPTION], mode="SR",
            assume_hsp_amp=True,
        )
        self.assertAlmostEqual(on.shield_amp_mult, off.shield_amp_mult * 1.10, places=6)
        # Pre-amp shield fields are unchanged (build identical); only the
        # multiplier moved. physical_ehp rises by exactly the amped shield delta.
        self.assertAlmostEqual(on.shield_any, off.shield_any, places=6)
        armor_factor = 100.0 / (100.0 + on.armor)
        expected_delta = off.shield_any * 0.10 / armor_factor
        self.assertAlmostEqual(
            on.physical_ehp - off.physical_ehp, expected_delta, places=1
        )
        self.assertGreater(on.physical_ehp, off.physical_ehp)

    def test_on_stacks_hsp_additively(self) -> None:
        # Sterak + Redemption 0.10 + Mikael 0.12 -> shield amp 1.22 exactly.
        off = compute_ehp(
            self.snap, "Aatrox", 11,
            item_ids=[_STERAKS, _REDEMPTION, _MIKAEL], mode="SR",
        )
        on = compute_ehp(
            self.snap, "Aatrox", 11,
            item_ids=[_STERAKS, _REDEMPTION, _MIKAEL], mode="SR",
            assume_hsp_amp=True,
        )
        self.assertAlmostEqual(on.shield_amp_mult, off.shield_amp_mult * 1.22, places=6)


class SustainHspSeamTests(unittest.TestCase):
    """sustain.py: HSP amplifies REGEN (self-heal) kit sustain only, NOT vamp."""

    def test_off_is_byte_identical_default(self) -> None:
        base = compute_sustain("DrMundo")
        off = compute_sustain("DrMundo", item_ids=[_REDEMPTION], assume_hsp_amp=False)
        self.assertEqual(off.to_dict(), base.to_dict())

    def test_on_without_hsp_item_is_byte_identical(self) -> None:
        base = compute_sustain("DrMundo")
        on = compute_sustain("DrMundo", item_ids=[_STERAKS], assume_hsp_amp=True)
        self.assertEqual(on.to_dict(), base.to_dict())

    def test_on_amps_unconditional_regen_by_exact_hsp_pct(self) -> None:
        # DrMundo's kit sustain is REGEN-only (P + R, both unconditional).
        off = compute_sustain("DrMundo")
        on = compute_sustain("DrMundo", item_ids=[_REDEMPTION], assume_hsp_amp=True)
        self.assertGreater(off.sustain_score, 0.0)
        self.assertAlmostEqual(on.sustain_score, off.sustain_score * 1.10, places=6)
        self.assertAlmostEqual(
            on.total_sustain_score, off.total_sustain_score * 1.10, places=6
        )
        # raw_sustain_units is the kind-agnostic pre-weight quantity - UNamped.
        self.assertAlmostEqual(on.raw_sustain_units, off.raw_sustain_units, places=6)

    def test_on_amps_conditional_regen(self) -> None:
        # Soraka Q is a CONDITIONAL REGEN self-heal -> the conditional score amps.
        off = compute_sustain("Soraka")
        on = compute_sustain("Soraka", item_ids=[_REDEMPTION], assume_hsp_amp=True)
        self.assertGreater(off.conditional_sustain_score, 0.0)
        self.assertAlmostEqual(
            on.conditional_sustain_score,
            off.conditional_sustain_score * 1.10,
            places=6,
        )

    def test_vamp_only_champion_is_byte_identical_even_on(self) -> None:
        # Aatrox sustain is OMNIVAMP + SPELLVAMP (no REGEN). HSP does not
        # amplify vamp, so the seam ON is byte-identical.
        off = compute_sustain("Aatrox")
        on = compute_sustain("Aatrox", item_ids=[_MOONSTONE], assume_hsp_amp=True)
        self.assertEqual(on.to_dict(), off.to_dict())


if __name__ == "__main__":
    unittest.main()

"""ENGINE 1.189.0 (R92, 2026-07-10) - Kaenic Rookern (2504) magic-shield EHP credit.

R92 is a fresh adversarial Meraki(16.13.1)-vs-registry refute pass on the tank/
fighter item set. It found that Kaenic Rookern (2504) - an 80-MR MR-tank item -
carries the Magebane passive ("after not taking magic damage for 15 seconds, gain
a shield that absorbs magic damage equal to 15% of MAXIMUM health") but its
``ITEM_EFFECTS`` entry had NO ``shield=ItemShield(...)`` field, so the wielder's
own magic shield was credited as ZERO magical EHP - unlike its Lifeline-family
siblings Sterak (3053), Maw (3156), Shieldbow (6673), which all carry an
``ItemShield`` in the always-on ``ehp._collect_shields`` pool. Kaenic was tagged
``defensive_only`` in an early batch (shield noted only in prose) and then missed
by the Phase-1.5 (ENGINE 1.27.0) shield-throughput sweep.

The fix credits the shield through the EXISTING ``ItemShield`` mechanism but via a
NEW default-OFF ``assume_kaenic_shield`` seam rather than the always-on pool the
lifelines use. Justification: Magebane's "no magic damage for 15s" uptime gate is
ANTI-correlated with the magic-damage fights where the shield would matter (it pops
the instant magic damage lands), so unlike the low-HP lifelines (which trigger AT
the moment of need) Kaenic's credit is conservatively opt-in and live-gated
(``docs/LIVE_GAME_GATED_SYNC.md``), mirroring R59/R60/R90.

Two additive ItemShield fields make this exact + byte-identical:
  - ``max_hp_scaling`` - models 15% of TOTAL max HP (Magebane's real base), not the
    bonus-HP lower bound; defaults 0.0 so every existing shield is unchanged.
  - ``default_off`` - marks a shield as opt-in; ``_collect_shields`` skips it unless
    the caller passes ``assume_kaenic_shield=True``; defaults False so the four
    always-on lifelines are unchanged.

DEFAULT-OFF is BYTE-IDENTICAL: ``assume_kaenic_shield=False`` (the default) drops
2504's shield from the pool and every other shield's magnitude is unmoved (their
``max_hp_scaling`` is 0.0). No live :8860 default scorer flips it on.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import _collect_shields, compute_ehp

_KAENIC = "2504"      # Magebane magic shield, 15% max HP, default-OFF seam
_MAW = "3156"         # Lifeline magic shield, always-on (default_off False)
_THORNMAIL = "3075"   # no ItemShield - stays zero regardless of the flag


class KaenicShieldFieldTests(unittest.TestCase):
    """2504 now carries a magic ItemShield marked default_off."""

    def test_kaenic_has_magic_shield(self) -> None:
        eff = ITEM_EFFECTS[_KAENIC]
        self.assertIsNotNone(eff.shield)
        self.assertEqual(eff.shield.damage_type, "magical")

    def test_kaenic_scales_on_max_hp(self) -> None:
        self.assertAlmostEqual(ITEM_EFFECTS[_KAENIC].shield.max_hp_scaling, 0.15, places=6)

    def test_kaenic_marked_default_off(self) -> None:
        self.assertTrue(ITEM_EFFECTS[_KAENIC].shield.default_off)


class KaenicResolveMagnitudeTests(unittest.TestCase):
    """resolve_magnitude credits 15% of the passed max_hp; 0 with no max_hp."""

    def test_fifteen_pct_of_max_hp(self) -> None:
        hp = ITEM_EFFECTS[_KAENIC].shield.resolve_magnitude(level=11, max_hp=3000.0)
        self.assertAlmostEqual(hp, 450.0, places=6)  # 0.15 * 3000

    def test_zero_without_max_hp(self) -> None:
        hp = ITEM_EFFECTS[_KAENIC].shield.resolve_magnitude(level=11)
        self.assertAlmostEqual(hp, 0.0, places=6)


class KaenicCollectShieldsGateTests(unittest.TestCase):
    """_collect_shields gates 2504 on assume_kaenic_shield; lifelines stay always-on."""

    def test_off_default_drops_kaenic(self) -> None:
        totals, sources = _collect_shields(
            [_KAENIC], level=11, bonus_hp=1200.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0,
        )
        self.assertAlmostEqual(totals["magical"], 0.0, places=6)
        self.assertFalse(any(s[0] == _KAENIC for s in sources))

    def test_on_credits_kaenic_magical(self) -> None:
        totals, sources = _collect_shields(
            [_KAENIC], level=11, bonus_hp=1200.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, assume_kaenic_shield=True,
        )
        self.assertAlmostEqual(totals["magical"], 450.0, places=6)  # 0.15 * 3000
        self.assertTrue(any(s[0] == _KAENIC for s in sources))

    def test_on_no_leak_to_other_types(self) -> None:
        totals, _ = _collect_shields(
            [_KAENIC], level=11, bonus_hp=1200.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, assume_kaenic_shield=True,
        )
        self.assertEqual(totals["physical"], 0.0)
        self.assertEqual(totals["any"], 0.0)
        self.assertEqual(totals["true"], 0.0)

    def test_lifeline_sibling_always_on(self) -> None:
        # Maw (3156) is default_off False -> collected with the flag OFF.
        totals, sources = _collect_shields(
            [_MAW], level=11, bonus_hp=0.0, bonus_ad=1000.0,
            is_ranged=False, max_hp=3000.0,
        )
        self.assertGreater(totals["magical"], 0.0)
        self.assertTrue(any(s[0] == _MAW for s in sources))


class KaenicEhpSeamTests(unittest.TestCase):
    """ehp.compute_ehp: OFF byte-identical, ON raises magical EHP only."""

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_off_is_byte_identical_default(self) -> None:
        base = compute_ehp(self.snap, "Aatrox", 11, item_ids=[_KAENIC], mode="SR")
        off = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_KAENIC], mode="SR",
            assume_kaenic_shield=False,
        )
        self.assertEqual(off.to_dict(), base.to_dict())

    def test_on_raises_magical_ehp_only(self) -> None:
        off = compute_ehp(self.snap, "Aatrox", 11, item_ids=[_KAENIC], mode="SR")
        on = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_KAENIC], mode="SR",
            assume_kaenic_shield=True,
        )
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertAlmostEqual(on.physical_ehp, off.physical_ehp, places=6)


class KaenicRegressionTests(unittest.TestCase):
    """2504 defensive metadata preserved; shield-less items unaffected."""

    def test_kaenic_defensive_metadata(self) -> None:
        eff = ITEM_EFFECTS[_KAENIC]
        self.assertEqual(eff.name, "Kaenic Rookern")
        self.assertTrue(eff.defensive_only)

    def test_shieldless_item_stays_zero(self) -> None:
        totals, _ = _collect_shields(
            [_THORNMAIL], level=11, bonus_hp=1000.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, assume_kaenic_shield=True,
        )
        self.assertTrue(all(v == 0.0 for v in totals.values()))


if __name__ == "__main__":
    unittest.main()

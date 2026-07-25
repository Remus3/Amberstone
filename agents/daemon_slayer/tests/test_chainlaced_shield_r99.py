"""ENGINE 1.192.0 (R99, 2026-07-10) - Chainlaced Crushers (3173) magic-shield EHP credit.

R99 credits the UNMODELED shield of Chainlaced Crushers' "Noxian Persistence"
passive. The 3173 boot was a bare ``defensive_only`` ItemEffect (MR + tenacity
boots, no DPS proc, no shield), so its magic shield earned ZERO EHP. Meraki
16.13.1 (items["3173"] passive "Noxian Persistence"): "Taking magic damage from
champions grants you a shield that absorbs 100 to 200 (+ 8% bonus health) magic
damage for 5 seconds" (15s cooldown). ``{{pp|100 to 200}}`` = per-champion-level
scaling 100 (L1) -> 200 (L18); + 8% BONUS health; MAGICAL absorb.

The credit rides the EXISTING ``ItemShield`` mechanism via a NEW default-OFF
``assume_chainlaced_shield`` seam (parallel to R92 ``assume_kaenic_shield`` and
R97 ``assume_eclipse_shield``). Justification: the shield only triggers on TAKING
magic damage and sits on a 15s cooldown, so - like Kaenic's anti-correlated
"no magic damage for 15s" uptime - it is conservatively opt-in and live-gated
rather than folded into the always-on lifeline pool.

DEFAULT-OFF is BYTE-IDENTICAL: ``assume_chainlaced_shield=False`` (the default)
drops 3173's shield from the pool. The per-shield arming gate keeps arming one
opt-in shield from leaking credit into another (Chainlaced ON must not credit
Kaenic or Eclipse and vice versa).

Chainlaced Crushers is SR-only (no Arena 22xxxx mirror), so arming keys on "3173".
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import MAGICAL
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import _collect_shields, compute_ehp

_CHAINLACED = "3173"     # Noxian Persistence magic shield, default-OFF seam
_KAENIC = "2504"         # R92 magic shield, default-OFF on its OWN seam
_ECLIPSE = "6692"        # R97 generic shield, default-OFF on its OWN seam
_THORNMAIL = "3075"      # no ItemShield - stays zero regardless of the flag


def _lerp_l11(bonus_hp: float) -> float:
    """Noxian Persistence at champion level 11: lerp(100 at L1 -> 200 at L18) + 8% bonus HP."""
    level_value = 100.0 + (200.0 - 100.0) * (11 - 1) / (18 - 1)
    return level_value + 0.08 * bonus_hp


class ChainlacedShieldFieldTests(unittest.TestCase):
    """3173 carries a MAGICAL ItemShield marked default_off (Meraki 16.13.1)."""

    def test_field_pins(self) -> None:
        eff = ITEM_EFFECTS[_CHAINLACED]
        self.assertIsNotNone(eff.shield)
        self.assertEqual(eff.shield.damage_type, MAGICAL)
        self.assertAlmostEqual(eff.shield.flat, 100.0, places=6)
        self.assertEqual(eff.shield.level_lerp_low, 1)
        self.assertEqual(eff.shield.level_lerp_high, 18)
        self.assertAlmostEqual(eff.shield.level_lerp_high_value, 200.0, places=6)
        self.assertAlmostEqual(eff.shield.bonus_hp_scaling, 0.08, places=6)
        self.assertTrue(eff.shield.default_off)

    def test_boot_stays_defensive_only(self) -> None:
        """The shield add does not disturb the existing defensive-only boot marker."""
        eff = ITEM_EFFECTS[_CHAINLACED]
        self.assertTrue(eff.defensive_only)


class ChainlacedResolveMagnitudeTests(unittest.TestCase):
    """resolve_magnitude: 100 (L1) -> 200 (L18) level-lerp + 8% bonus HP, magic-only."""

    def test_level1_floor(self) -> None:
        shield = ITEM_EFFECTS[_CHAINLACED].shield
        hp = shield.resolve_magnitude(level=1, bonus_hp=1000.0)
        self.assertAlmostEqual(hp, 100.0 + 0.08 * 1000.0, places=6)  # 180

    def test_level18_cap(self) -> None:
        shield = ITEM_EFFECTS[_CHAINLACED].shield
        hp = shield.resolve_magnitude(level=18, bonus_hp=1000.0)
        self.assertAlmostEqual(hp, 200.0 + 0.08 * 1000.0, places=6)  # 280

    def test_level11_lerp(self) -> None:
        shield = ITEM_EFFECTS[_CHAINLACED].shield
        hp = shield.resolve_magnitude(level=11, bonus_hp=1000.0)
        self.assertAlmostEqual(hp, _lerp_l11(1000.0), places=6)

    def test_ranged_not_modified(self) -> None:
        """No ranged_modifier: Chainlaced's shield is the same for melee and ranged."""
        shield = ITEM_EFFECTS[_CHAINLACED].shield
        melee = shield.resolve_magnitude(level=11, bonus_hp=800.0, is_ranged=False)
        ranged = shield.resolve_magnitude(level=11, bonus_hp=800.0, is_ranged=True)
        self.assertAlmostEqual(melee, ranged, places=6)


class ChainlacedCollectShieldsGateTests(unittest.TestCase):
    """_collect_shields gates 3173 on assume_chainlaced_shield as a MAGICAL shield."""

    def test_off_default_drops_chainlaced(self) -> None:
        totals, sources = _collect_shields(
            [_CHAINLACED], level=11, bonus_hp=1000.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0,
        )
        self.assertAlmostEqual(totals["magical"], 0.0, places=6)
        self.assertFalse(any(s[0] == _CHAINLACED for s in sources))

    def test_on_credits_chainlaced_magical(self) -> None:
        totals, sources = _collect_shields(
            [_CHAINLACED], level=11, bonus_hp=1000.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, assume_chainlaced_shield=True,
        )
        self.assertAlmostEqual(totals["magical"], _lerp_l11(1000.0), places=6)
        self.assertTrue(any(s[0] == _CHAINLACED for s in sources))

    def test_on_no_leak_to_other_types(self) -> None:
        totals, _ = _collect_shields(
            [_CHAINLACED], level=11, bonus_hp=1000.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, assume_chainlaced_shield=True,
        )
        self.assertEqual(totals["any"], 0.0)
        self.assertEqual(totals["physical"], 0.0)
        self.assertEqual(totals["true"], 0.0)


class ChainlacedCrossContaminationTests(unittest.TestCase):
    """Arming one opt-in shield never leaks credit into another."""

    def test_chainlaced_flag_does_not_credit_kaenic(self) -> None:
        totals, sources = _collect_shields(
            [_KAENIC], level=11, bonus_hp=1200.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0,
            assume_chainlaced_shield=True, assume_kaenic_shield=False,
        )
        self.assertAlmostEqual(totals["magical"], 0.0, places=6)
        self.assertFalse(any(s[0] == _KAENIC for s in sources))

    def test_chainlaced_flag_does_not_credit_eclipse(self) -> None:
        totals, sources = _collect_shields(
            [_ECLIPSE], level=11, bonus_hp=0.0, bonus_ad=1000.0,
            is_ranged=False, max_hp=3000.0,
            assume_chainlaced_shield=True, assume_eclipse_shield=False,
        )
        self.assertAlmostEqual(totals["any"], 0.0, places=6)
        self.assertFalse(any(s[0] == _ECLIPSE for s in sources))

    def test_kaenic_flag_does_not_credit_chainlaced(self) -> None:
        totals, sources = _collect_shields(
            [_CHAINLACED], level=11, bonus_hp=1000.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0,
            assume_kaenic_shield=True, assume_chainlaced_shield=False,
        )
        self.assertAlmostEqual(totals["magical"], 0.0, places=6)
        self.assertFalse(any(s[0] == _CHAINLACED for s in sources))


class ChainlacedEhpSeamTests(unittest.TestCase):
    """compute_ehp: OFF byte-identical; ON raises magical EHP only."""

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_off_is_byte_identical_default(self) -> None:
        base = compute_ehp(self.snap, "Aatrox", 11, item_ids=[_CHAINLACED], mode="SR")
        off = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_CHAINLACED], mode="SR",
            assume_chainlaced_shield=False,
        )
        self.assertEqual(off.to_dict(), base.to_dict())

    def test_on_raises_magical_ehp_only(self) -> None:
        off = compute_ehp(self.snap, "Aatrox", 11, item_ids=[_CHAINLACED], mode="SR")
        on = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_CHAINLACED], mode="SR",
            assume_chainlaced_shield=True,
        )
        # MAGICAL shield lifts only the magical axis; physical + true stay put.
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertAlmostEqual(on.physical_ehp, off.physical_ehp, places=6)
        self.assertAlmostEqual(on.true_ehp, off.true_ehp, places=6)


class ChainlacedRegressionTests(unittest.TestCase):
    """Shieldless items stay zero even when the flag is armed."""

    def test_shieldless_item_stays_zero(self) -> None:
        totals, _ = _collect_shields(
            [_THORNMAIL], level=11, bonus_hp=1000.0, bonus_ad=1000.0,
            is_ranged=False, max_hp=3000.0, assume_chainlaced_shield=True,
        )
        self.assertTrue(all(v == 0.0 for v in totals.values()))


class ChainlacedVersionPinTests(unittest.TestCase):
    """R99 bumps ENGINE_VERSION to 1.192.0."""

    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.248.0")


if __name__ == "__main__":
    unittest.main()

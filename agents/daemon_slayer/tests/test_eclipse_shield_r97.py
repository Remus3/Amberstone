"""ENGINE 1.191.0 (R97, 2026-07-10) - Eclipse (6692 / Arena 226692) shield EHP credit.

R97 credits the UNMODELED shield half of Eclipse's "Ever Rising Moon" passive.
The proc has TWO halves; the DAMAGE half (6% target max HP physical every 2
attacks) was already modeled as a ``PeriodicProc`` in ITEM_EFFECTS, but the
SHIELD half was credited as ZERO EHP. Meraki 16.13.1 (items["6692"] passive
"Ever Rising Moon"): "...grants you a shield for {{rd|160|80}} (+ {{rd|40%|20%}}
bonus AD) for 2 seconds." So melee = 160 flat + 40% bonus AD, ranged = 80 flat +
20% bonus AD (ranged_modifier 0.5), generic (ANY) shield, 2s.

The credit rides the EXISTING ``ItemShield`` mechanism via a NEW default-OFF
``assume_eclipse_shield`` seam (parallel to R92's ``assume_kaenic_shield``).
Justification: the shield is a burst-window pop on a 6s/target cooldown, so like
Kaenic it is conservatively opt-in and live-gated rather than folded into the
always-on lifeline pool.

DEFAULT-OFF is BYTE-IDENTICAL: ``assume_eclipse_shield=False`` (the default) drops
6692/226692's shield from the pool. The per-shield arming gate keeps arming one
opt-in shield from leaking credit into another (Eclipse ON must not credit Kaenic
and vice versa).

Arena mirror 226692 mirrors SR 6692 (Meraki-absent for the Arena id; grounded by
DDragon items.json + the SR-6692 mirror convention its periodic already follows).
446692 / 326692 do not exist in the item pool.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import ANY
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import _collect_shields, compute_ehp

_ECLIPSE = "6692"        # Ever Rising Moon shield half, default-OFF seam
_ECLIPSE_ARENA = "226692"  # Arena mirror of 6692
_KAENIC = "2504"         # R92 magic shield, default-OFF on its OWN seam
_THORNMAIL = "3075"      # no ItemShield - stays zero regardless of the flag


class EclipseShieldFieldTests(unittest.TestCase):
    """6692 + 226692 carry a generic ItemShield marked default_off (Meraki 16.13.1)."""

    def _assert_meraki_pins(self, item_id: str) -> None:
        eff = ITEM_EFFECTS[item_id]
        self.assertIsNotNone(eff.shield)
        self.assertEqual(eff.shield.damage_type, ANY)
        self.assertAlmostEqual(eff.shield.flat, 160.0, places=6)
        self.assertAlmostEqual(eff.shield.bonus_ad_scaling, 0.40, places=6)
        self.assertAlmostEqual(eff.shield.ranged_modifier, 0.5, places=6)
        self.assertTrue(eff.shield.default_off)

    def test_sr_eclipse_field_pins(self) -> None:
        self._assert_meraki_pins(_ECLIPSE)

    def test_arena_eclipse_field_pins(self) -> None:
        self._assert_meraki_pins(_ECLIPSE_ARENA)


class EclipseResolveMagnitudeTests(unittest.TestCase):
    """resolve_magnitude: melee 160 + 40% bonus AD; ranged halves to 80 + 20%."""

    def test_melee_magnitude(self) -> None:
        shield = ITEM_EFFECTS[_ECLIPSE].shield
        bonus_ad = 1000.0
        hp = shield.resolve_magnitude(level=11, bonus_ad=bonus_ad, is_ranged=False)
        self.assertAlmostEqual(hp, 160.0 + 0.40 * bonus_ad, places=6)  # 560

    def test_ranged_magnitude_halves(self) -> None:
        shield = ITEM_EFFECTS[_ECLIPSE].shield
        bonus_ad = 1000.0
        hp = shield.resolve_magnitude(level=11, bonus_ad=bonus_ad, is_ranged=True)
        self.assertAlmostEqual(hp, 80.0 + 0.20 * bonus_ad, places=6)   # 280

    def test_ranged_is_exactly_half_of_melee(self) -> None:
        shield = ITEM_EFFECTS[_ECLIPSE].shield
        melee = shield.resolve_magnitude(level=11, bonus_ad=750.0, is_ranged=False)
        ranged = shield.resolve_magnitude(level=11, bonus_ad=750.0, is_ranged=True)
        self.assertAlmostEqual(ranged, 0.5 * melee, places=6)


class EclipseCollectShieldsGateTests(unittest.TestCase):
    """_collect_shields gates 6692/226692 on assume_eclipse_shield as an ANY shield."""

    def test_off_default_drops_eclipse(self) -> None:
        totals, sources = _collect_shields(
            [_ECLIPSE], level=11, bonus_hp=0.0, bonus_ad=1000.0,
            is_ranged=False, max_hp=3000.0,
        )
        self.assertAlmostEqual(totals[ANY], 0.0, places=6)
        self.assertFalse(any(s[0] == _ECLIPSE for s in sources))

    def test_on_credits_eclipse_melee_any(self) -> None:
        totals, sources = _collect_shields(
            [_ECLIPSE], level=11, bonus_hp=0.0, bonus_ad=1000.0,
            is_ranged=False, max_hp=3000.0, assume_eclipse_shield=True,
        )
        self.assertAlmostEqual(totals[ANY], 160.0 + 0.40 * 1000.0, places=6)  # 560
        self.assertTrue(any(s[0] == _ECLIPSE for s in sources))

    def test_on_credits_eclipse_ranged_half(self) -> None:
        totals, _ = _collect_shields(
            [_ECLIPSE], level=11, bonus_hp=0.0, bonus_ad=1000.0,
            is_ranged=True, max_hp=3000.0, assume_eclipse_shield=True,
        )
        self.assertAlmostEqual(totals[ANY], 80.0 + 0.20 * 1000.0, places=6)   # 280

    def test_arena_mirror_behaves_identically(self) -> None:
        sr, _ = _collect_shields(
            [_ECLIPSE], level=11, bonus_hp=0.0, bonus_ad=800.0,
            is_ranged=False, max_hp=3000.0, assume_eclipse_shield=True,
        )
        arena, _ = _collect_shields(
            [_ECLIPSE_ARENA], level=11, bonus_hp=0.0, bonus_ad=800.0,
            is_ranged=False, max_hp=3000.0, assume_eclipse_shield=True,
        )
        self.assertAlmostEqual(sr[ANY], arena[ANY], places=6)
        self.assertGreater(arena[ANY], 0.0)

    def test_on_no_leak_to_other_types(self) -> None:
        totals, _ = _collect_shields(
            [_ECLIPSE], level=11, bonus_hp=0.0, bonus_ad=1000.0,
            is_ranged=False, max_hp=3000.0, assume_eclipse_shield=True,
        )
        self.assertEqual(totals["physical"], 0.0)
        self.assertEqual(totals["magical"], 0.0)
        self.assertEqual(totals["true"], 0.0)


class EclipseCrossContaminationTests(unittest.TestCase):
    """Arming one opt-in shield never leaks credit into the other."""

    def test_eclipse_flag_does_not_credit_kaenic(self) -> None:
        totals, sources = _collect_shields(
            [_KAENIC], level=11, bonus_hp=1200.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0,
            assume_eclipse_shield=True, assume_kaenic_shield=False,
        )
        self.assertAlmostEqual(totals["magical"], 0.0, places=6)
        self.assertFalse(any(s[0] == _KAENIC for s in sources))

    def test_kaenic_flag_does_not_credit_eclipse(self) -> None:
        totals, sources = _collect_shields(
            [_ECLIPSE], level=11, bonus_hp=0.0, bonus_ad=1000.0,
            is_ranged=False, max_hp=3000.0,
            assume_kaenic_shield=True, assume_eclipse_shield=False,
        )
        self.assertAlmostEqual(totals[ANY], 0.0, places=6)
        self.assertFalse(any(s[0] == _ECLIPSE for s in sources))


class EclipseEhpSeamTests(unittest.TestCase):
    """compute_ehp: OFF byte-identical; ON raises EHP (ANY shield lifts all axes)."""

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_off_is_byte_identical_default(self) -> None:
        base = compute_ehp(self.snap, "Aatrox", 11, item_ids=[_ECLIPSE], mode="SR")
        off = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_ECLIPSE], mode="SR",
            assume_eclipse_shield=False,
        )
        self.assertEqual(off.to_dict(), base.to_dict())

    def test_on_raises_ehp(self) -> None:
        off = compute_ehp(self.snap, "Aatrox", 11, item_ids=[_ECLIPSE], mode="SR")
        on = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_ECLIPSE], mode="SR",
            assume_eclipse_shield=True,
        )
        # ANY shield lifts physical + magical EHP together.
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertGreater(on.magical_ehp, off.magical_ehp)

    def test_arena_mirror_off_byte_identical(self) -> None:
        base = compute_ehp(self.snap, "Aatrox", 11, item_ids=[_ECLIPSE_ARENA], mode="ARENA")
        off = compute_ehp(
            self.snap, "Aatrox", 11, item_ids=[_ECLIPSE_ARENA], mode="ARENA",
            assume_eclipse_shield=False,
        )
        self.assertEqual(off.to_dict(), base.to_dict())


class EclipseRegressionTests(unittest.TestCase):
    """Damage-half untouched; absent ids carry no shield; shield-less items unaffected."""

    def test_damage_half_periodic_preserved(self) -> None:
        eff = ITEM_EFFECTS[_ECLIPSE]
        self.assertEqual(len(eff.periodics), 1)
        self.assertEqual(eff.periodics[0].name, "Ever Rising Moon")

    def test_arena_damage_half_periodic_preserved(self) -> None:
        eff = ITEM_EFFECTS[_ECLIPSE_ARENA]
        self.assertEqual(len(eff.periodics), 1)
        self.assertEqual(eff.periodics[0].name, "Ever Rising Moon")

    def test_nonexistent_eclipse_ids_absent_or_shieldless(self) -> None:
        for absent in ("446692", "326692"):
            eff = ITEM_EFFECTS.get(absent)
            self.assertTrue(eff is None or eff.shield is None)

    def test_shieldless_item_stays_zero(self) -> None:
        totals, _ = _collect_shields(
            [_THORNMAIL], level=11, bonus_hp=1000.0, bonus_ad=1000.0,
            is_ranged=False, max_hp=3000.0, assume_eclipse_shield=True,
        )
        self.assertTrue(all(v == 0.0 for v in totals.values()))


class EclipseVersionPinTests(unittest.TestCase):
    """R97 bumps ENGINE_VERSION to 1.191.0."""

    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.200.0")


if __name__ == "__main__":
    unittest.main()

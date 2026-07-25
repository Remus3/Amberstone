"""Seraph's Embrace (3040) Lifeline max-mana shield EHP credit (Meraki-refute).

Credits the UNMODELED shield of Seraph's Embrace's "Lifeline" passive. The
3040 item modeled only its Awe stat (2% bonus mana as AP); the Lifeline
shield earned ZERO EHP. Meraki 16.13.1 (items["3040"] passive "Lifeline"):
"gain a shield ... that absorbs damage equal to 18% MAXIMUM mana for 3
seconds" at <30% max HP. The absorb is GENERIC (any damage type), so - unlike
the R99 Chainlaced Crushers magic-only shield - it lifts all three EHP axes.

The credit rides the EXISTING ``ItemShield`` mechanism via a NEW
``max_mana_scaling`` term plus a default-OFF ``assume_seraphs_shield`` seam
(parallel to R92 ``assume_kaenic_shield``, R97 ``assume_eclipse_shield`` and
R99 ``assume_chainlaced_shield``). Justification: Lifeline is a low-HP
threshold trigger on a per-fight cooldown, so - like the other opt-in
lifelines - it is conservatively opt-in and live-gated rather than folded
into the always-on lifeline pool.

DEFAULT-OFF is BYTE-IDENTICAL: ``assume_seraphs_shield=False`` (the default)
drops 3040/223040/323040's shield from the pool. The per-shield arming gate
keeps arming one opt-in shield from leaking credit into another (Seraph's ON
must not credit Kaenic / Eclipse / Chainlaced and vice versa).

Seraph's Embrace has three mode mirrors: SR 3040, Arena 223040, ARAM 323040 -
so arming keys on all three ids.

This credit bumps ENGINE_VERSION to 1.193.0 (the seam changes EHP output when
armed); the pin at the bottom tracks it.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import ANY, ItemShield
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import _collect_shields, compute_ehp

_SERAPHS = "3040"           # SR Lifeline 18% max-mana generic shield, default-OFF
_SERAPHS_ARENA = "223040"   # Arena mirror
_SERAPHS_ARAM = "323040"    # ARAM mirror
_KAENIC = "2504"            # R92 magic shield on its OWN seam
_ECLIPSE = "6692"           # R97 generic shield on its OWN seam
_ECLIPSE_ARENA = "226692"   # R97 Arena mirror
_CHAINLACED = "3173"        # R99 magic shield on its OWN seam
_THORNMAIL = "3075"         # no ItemShield - stays zero regardless of the flag


class SeraphsShieldFieldTests(unittest.TestCase):
    """3040 / 223040 / 323040 each carry an ANY ItemShield marked default_off."""

    def test_sr_field_pins(self) -> None:
        eff = ITEM_EFFECTS[_SERAPHS]
        self.assertIsNotNone(eff.shield)
        self.assertEqual(eff.shield.damage_type, ANY)
        self.assertAlmostEqual(eff.shield.max_mana_scaling, 0.18, places=6)
        self.assertTrue(eff.shield.default_off)

    def test_arena_field_pins(self) -> None:
        eff = ITEM_EFFECTS[_SERAPHS_ARENA]
        self.assertIsNotNone(eff.shield)
        self.assertEqual(eff.shield.damage_type, ANY)
        self.assertAlmostEqual(eff.shield.max_mana_scaling, 0.18, places=6)
        self.assertTrue(eff.shield.default_off)

    def test_aram_field_pins(self) -> None:
        eff = ITEM_EFFECTS[_SERAPHS_ARAM]
        self.assertIsNotNone(eff.shield)
        self.assertEqual(eff.shield.damage_type, ANY)
        self.assertAlmostEqual(eff.shield.max_mana_scaling, 0.18, places=6)
        self.assertTrue(eff.shield.default_off)

    def test_existing_fields_preserved(self) -> None:
        """The shield add does not disturb the Awe AP or lifeline dedup key."""
        for iid in (_SERAPHS, _SERAPHS_ARENA, _SERAPHS_ARAM):
            eff = ITEM_EFFECTS[iid]
            self.assertAlmostEqual(eff.bonus_ap_pct_bonus_mp, 0.02, places=6)
            self.assertEqual(eff.unique_passive_key, "lifeline")


class SeraphsResolveMagnitudeTests(unittest.TestCase):
    """resolve_magnitude: 18% of max mana, generic (level-independent)."""

    def test_bare_shield_max_mana_term(self) -> None:
        shield = ItemShield(max_mana_scaling=0.18)
        hp = shield.resolve_magnitude(level=11, max_mana=2000.0)
        self.assertAlmostEqual(hp, 360.0, places=6)  # 0.18 * 2000

    def test_registry_shield_max_mana_term(self) -> None:
        shield = ITEM_EFFECTS[_SERAPHS].shield
        hp = shield.resolve_magnitude(level=11, max_mana=1914.25)
        self.assertAlmostEqual(hp, 0.18 * 1914.25, places=6)

    def test_zero_max_mana_zero_shield(self) -> None:
        shield = ITEM_EFFECTS[_SERAPHS].shield
        self.assertAlmostEqual(shield.resolve_magnitude(level=11, max_mana=0.0), 0.0, places=6)


class SeraphsCollectShieldsGateTests(unittest.TestCase):
    """_collect_shields gates 3040 on assume_seraphs_shield as an ANY shield."""

    def test_off_default_drops_seraphs(self) -> None:
        totals, sources = _collect_shields(
            [_SERAPHS], level=11, bonus_hp=0.0, bonus_ad=0.0,
            is_ranged=False, max_hp=2000.0, max_mana=2000.0,
        )
        self.assertAlmostEqual(totals[ANY], 0.0, places=6)
        self.assertFalse(any(s[0] == _SERAPHS for s in sources))

    def test_on_credits_seraphs_any(self) -> None:
        totals, sources = _collect_shields(
            [_SERAPHS], level=11, bonus_hp=0.0, bonus_ad=0.0,
            is_ranged=False, max_hp=2000.0, max_mana=2000.0,
            assume_seraphs_shield=True,
        )
        self.assertAlmostEqual(totals[ANY], 0.18 * 2000.0, places=6)  # 360
        self.assertTrue(any(s[0] == _SERAPHS for s in sources))

    def test_on_no_leak_to_other_types(self) -> None:
        totals, _ = _collect_shields(
            [_SERAPHS], level=11, bonus_hp=0.0, bonus_ad=0.0,
            is_ranged=False, max_hp=2000.0, max_mana=2000.0,
            assume_seraphs_shield=True,
        )
        self.assertEqual(totals["physical"], 0.0)
        self.assertEqual(totals["magical"], 0.0)
        self.assertEqual(totals["true"], 0.0)

    def test_on_credits_arena_and_aram_mirrors(self) -> None:
        for iid in (_SERAPHS_ARENA, _SERAPHS_ARAM):
            totals, sources = _collect_shields(
                [iid], level=11, bonus_hp=0.0, bonus_ad=0.0,
                is_ranged=False, max_hp=2000.0, max_mana=1500.0,
                assume_seraphs_shield=True,
            )
            self.assertAlmostEqual(totals[ANY], 0.18 * 1500.0, places=6)
            self.assertTrue(any(s[0] == iid for s in sources))


class SeraphsCrossContaminationTests(unittest.TestCase):
    """Arming one opt-in shield never leaks credit into another (both ways)."""

    def test_seraphs_flag_does_not_credit_kaenic(self) -> None:
        totals, sources = _collect_shields(
            [_KAENIC], level=11, bonus_hp=1200.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, max_mana=2000.0,
            assume_seraphs_shield=True, assume_kaenic_shield=False,
        )
        self.assertAlmostEqual(totals["magical"], 0.0, places=6)
        self.assertFalse(any(s[0] == _KAENIC for s in sources))

    def test_seraphs_flag_does_not_credit_eclipse(self) -> None:
        for iid in (_ECLIPSE, _ECLIPSE_ARENA):
            totals, sources = _collect_shields(
                [iid], level=11, bonus_hp=0.0, bonus_ad=1000.0,
                is_ranged=False, max_hp=3000.0, max_mana=2000.0,
                assume_seraphs_shield=True, assume_eclipse_shield=False,
            )
            self.assertAlmostEqual(totals[ANY], 0.0, places=6)
            self.assertFalse(any(s[0] == iid for s in sources))

    def test_seraphs_flag_does_not_credit_chainlaced(self) -> None:
        totals, sources = _collect_shields(
            [_CHAINLACED], level=11, bonus_hp=1000.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, max_mana=2000.0,
            assume_seraphs_shield=True, assume_chainlaced_shield=False,
        )
        self.assertAlmostEqual(totals["magical"], 0.0, places=6)
        self.assertFalse(any(s[0] == _CHAINLACED for s in sources))

    def test_kaenic_flag_does_not_credit_seraphs(self) -> None:
        totals, sources = _collect_shields(
            [_SERAPHS], level=11, bonus_hp=0.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, max_mana=2000.0,
            assume_kaenic_shield=True, assume_seraphs_shield=False,
        )
        self.assertAlmostEqual(totals[ANY], 0.0, places=6)
        self.assertFalse(any(s[0] == _SERAPHS for s in sources))

    def test_eclipse_flag_does_not_credit_seraphs(self) -> None:
        totals, sources = _collect_shields(
            [_SERAPHS], level=11, bonus_hp=0.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, max_mana=2000.0,
            assume_eclipse_shield=True, assume_seraphs_shield=False,
        )
        self.assertAlmostEqual(totals[ANY], 0.0, places=6)
        self.assertFalse(any(s[0] == _SERAPHS for s in sources))

    def test_chainlaced_flag_does_not_credit_seraphs(self) -> None:
        totals, sources = _collect_shields(
            [_SERAPHS], level=11, bonus_hp=0.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, max_mana=2000.0,
            assume_chainlaced_shield=True, assume_seraphs_shield=False,
        )
        self.assertAlmostEqual(totals[ANY], 0.0, places=6)
        self.assertFalse(any(s[0] == _SERAPHS for s in sources))


class SeraphsEhpSeamTests(unittest.TestCase):
    """compute_ehp on a mana champ: OFF byte-identical; ON raises all 3 axes."""

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_off_is_byte_identical_default(self) -> None:
        base = compute_ehp(self.snap, "Ryze", 11, item_ids=[_SERAPHS], mode="SR")
        off = compute_ehp(
            self.snap, "Ryze", 11, item_ids=[_SERAPHS], mode="SR",
            assume_seraphs_shield=False,
        )
        self.assertEqual(off.to_dict(), base.to_dict())

    def test_on_raises_all_three_axes(self) -> None:
        off = compute_ehp(self.snap, "Ryze", 11, item_ids=[_SERAPHS], mode="SR")
        on = compute_ehp(
            self.snap, "Ryze", 11, item_ids=[_SERAPHS], mode="SR",
            assume_seraphs_shield=True,
        )
        # ANY (generic) shield lifts every axis; contrast R99 magic-only.
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertGreater(on.true_ehp, off.true_ehp)


class SeraphsRegressionTests(unittest.TestCase):
    """Shieldless items stay zero even when the flag is armed."""

    def test_shieldless_item_stays_zero(self) -> None:
        totals, _ = _collect_shields(
            [_THORNMAIL], level=11, bonus_hp=1000.0, bonus_ad=1000.0,
            is_ranged=False, max_hp=3000.0, max_mana=2000.0,
            assume_seraphs_shield=True,
        )
        self.assertTrue(all(v == 0.0 for v in totals.values()))


class SeraphsEngineVersionPin(unittest.TestCase):
    """The Seraph's shield credit bumps the engine revision."""

    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.246.0")


if __name__ == "__main__":
    unittest.main()

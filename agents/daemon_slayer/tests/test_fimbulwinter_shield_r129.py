"""Fimbulwinter (3121) "Everlasting" shield EHP credit (Meraki-refute, R129).

Credits the UNMODELED shield of Fimbulwinter's "Everlasting" passive. The
3121 item modeled only its Awe stat (8% max mana as bonus HP, via the
``_item_mana_health`` seam); the Everlasting shield earned ZERO EHP - the
ItemEffect carried ``shield=None`` and a stale note that mislabelled the
mechanic as "Everfrost CC on first ability hit" (a mechanic that no longer
exists in the 16.13.1 kit). Meraki 16.13.1 (items["3121"] passive
"Everlasting"): immobilizing (or slowing, if melee) an enemy champion grants a
"100 (+ 4.5% current mana) shield for 3 seconds (8 second cooldown)". The
absorb is GENERIC (any damage type), so - like the Seraph's Embrace lifeline
and unlike the R99 Chainlaced Crushers magic-only shield - it lifts all three
EHP axes.

The credit rides the EXISTING ``ItemShield`` mechanism via ``flat`` (100) plus
the ``max_mana_scaling`` term (0.045) behind a NEW default-OFF
``assume_fimbulwinter_shield`` seam (parallel to R92 ``assume_kaenic_shield``,
R97 ``assume_eclipse_shield``, R99 ``assume_chainlaced_shield`` and the
Seraph's ``assume_seraphs_shield``).

"Current mana" is modelled as MAX mana under the engine's steady-state
convention (no per-fight mana-expenditure track; the Everlasting trigger -
immobilize-an-enemy - fires throughout a fight, typically while mana is high).
This mirrors how Seraph's max_mana_scaling is resolved. Because the trigger is
a per-fight cooldown utility - not an always-on lifeline - the credit is
conservatively opt-in and live-gated rather than folded into the always-on
pool. The +80% multi-enemy arm (to 180 + 8.1% mana) is intentionally NOT
modelled; the base single-target magnitude is the clean, conservative number.

DEFAULT-OFF is BYTE-IDENTICAL: ``assume_fimbulwinter_shield=False`` (the
default) drops 3121/223121/323121's shield from the pool. The per-shield
arming gate keeps arming one opt-in shield from leaking credit into another.

Fimbulwinter has three mode mirrors: SR 3121, Arena 223121, ARAM 323121 - so
arming keys on all three ids.

This credit bumps ENGINE_VERSION to 1.215.0 (the seam changes EHP output when
armed); the pin at the bottom tracks it.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import ANY, ItemShield
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import _collect_shields, compute_ehp

_FIMB = "3121"            # SR Everlasting 100 + 4.5% mana generic shield, default-OFF
_FIMB_ARENA = "223121"    # Arena mirror
_FIMB_ARAM = "323121"     # ARAM mirror
_SERAPHS = "3040"         # Seraph's generic shield on its OWN seam
_KAENIC = "2504"          # R92 magic shield on its OWN seam
_ECLIPSE = "6692"         # R97 generic shield on its OWN seam
_CHAINLACED = "3173"      # R99 magic shield on its OWN seam
_THORNMAIL = "3075"       # no ItemShield - stays zero regardless of the flag

_FLAT = 100.0
_MANA_PCT = 0.045


class FimbulwinterShieldFieldTests(unittest.TestCase):
    """3121 / 223121 / 323121 each carry an ANY ItemShield marked default_off."""

    def _assert_pins(self, iid: str) -> None:
        eff = ITEM_EFFECTS[iid]
        self.assertIsNotNone(eff.shield)
        self.assertEqual(eff.shield.damage_type, ANY)
        self.assertAlmostEqual(eff.shield.flat, _FLAT, places=6)
        self.assertAlmostEqual(eff.shield.max_mana_scaling, _MANA_PCT, places=6)
        self.assertTrue(eff.shield.default_off)

    def test_sr_field_pins(self) -> None:
        self._assert_pins(_FIMB)

    def test_arena_field_pins(self) -> None:
        self._assert_pins(_FIMB_ARENA)

    def test_aram_field_pins(self) -> None:
        self._assert_pins(_FIMB_ARAM)

    def test_not_lifeline_keyed(self) -> None:
        """Everlasting is a CC-on-enemy trigger, NOT a low-HP lifeline - it must
        not carry the lifeline dedup key (else it would dedup against
        Sterak/Shieldbow/Maw/Seraph's)."""
        for iid in (_FIMB, _FIMB_ARENA, _FIMB_ARAM):
            self.assertNotEqual(ITEM_EFFECTS[iid].unique_passive_key, "lifeline")

    def test_still_defensive_only(self) -> None:
        """The shield add does not turn the item into a DPS proc."""
        for iid in (_FIMB, _FIMB_ARENA, _FIMB_ARAM):
            self.assertTrue(ITEM_EFFECTS[iid].defensive_only)


class FimbulwinterResolveMagnitudeTests(unittest.TestCase):
    """resolve_magnitude: 100 flat + 4.5% of max mana, generic, level-flat."""

    def test_bare_shield_flat_plus_mana(self) -> None:
        shield = ItemShield(flat=_FLAT, max_mana_scaling=_MANA_PCT)
        hp = shield.resolve_magnitude(level=11, max_mana=2000.0)
        self.assertAlmostEqual(hp, 100.0 + 0.045 * 2000.0, places=6)  # 190

    def test_registry_shield_magnitude(self) -> None:
        shield = ITEM_EFFECTS[_FIMB].shield
        hp = shield.resolve_magnitude(level=11, max_mana=1600.0)
        self.assertAlmostEqual(hp, 100.0 + 0.045 * 1600.0, places=6)  # 172

    def test_zero_mana_keeps_flat(self) -> None:
        shield = ITEM_EFFECTS[_FIMB].shield
        self.assertAlmostEqual(
            shield.resolve_magnitude(level=11, max_mana=0.0), _FLAT, places=6
        )

    def test_level_independent(self) -> None:
        shield = ITEM_EFFECTS[_FIMB].shield
        lo = shield.resolve_magnitude(level=1, max_mana=1600.0)
        hi = shield.resolve_magnitude(level=18, max_mana=1600.0)
        self.assertAlmostEqual(lo, hi, places=6)


class FimbulwinterCollectShieldsGateTests(unittest.TestCase):
    """_collect_shields gates 3121 on assume_fimbulwinter_shield as ANY."""

    def test_off_default_drops_fimbulwinter(self) -> None:
        totals, sources = _collect_shields(
            [_FIMB], level=11, bonus_hp=0.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, max_mana=2000.0,
        )
        self.assertAlmostEqual(totals[ANY], 0.0, places=6)
        self.assertFalse(any(s[0] == _FIMB for s in sources))

    def test_on_credits_fimbulwinter_any(self) -> None:
        totals, sources = _collect_shields(
            [_FIMB], level=11, bonus_hp=0.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, max_mana=2000.0,
            assume_fimbulwinter_shield=True,
        )
        self.assertAlmostEqual(totals[ANY], 100.0 + 0.045 * 2000.0, places=6)  # 190
        self.assertTrue(any(s[0] == _FIMB for s in sources))

    def test_on_no_leak_to_other_types(self) -> None:
        totals, _ = _collect_shields(
            [_FIMB], level=11, bonus_hp=0.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, max_mana=2000.0,
            assume_fimbulwinter_shield=True,
        )
        self.assertEqual(totals["physical"], 0.0)
        self.assertEqual(totals["magical"], 0.0)
        self.assertEqual(totals["true"], 0.0)

    def test_on_credits_arena_and_aram_mirrors(self) -> None:
        for iid in (_FIMB_ARENA, _FIMB_ARAM):
            totals, sources = _collect_shields(
                [iid], level=11, bonus_hp=0.0, bonus_ad=0.0,
                is_ranged=False, max_hp=3000.0, max_mana=1500.0,
                assume_fimbulwinter_shield=True,
            )
            self.assertAlmostEqual(totals[ANY], 100.0 + 0.045 * 1500.0, places=6)
            self.assertTrue(any(s[0] == iid for s in sources))


class FimbulwinterCrossContaminationTests(unittest.TestCase):
    """Arming one opt-in shield never leaks credit into another (both ways)."""

    def test_fimbulwinter_flag_does_not_credit_seraphs(self) -> None:
        totals, sources = _collect_shields(
            [_SERAPHS], level=11, bonus_hp=0.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, max_mana=2000.0,
            assume_fimbulwinter_shield=True, assume_seraphs_shield=False,
        )
        self.assertAlmostEqual(totals[ANY], 0.0, places=6)
        self.assertFalse(any(s[0] == _SERAPHS for s in sources))

    def test_fimbulwinter_flag_does_not_credit_kaenic(self) -> None:
        totals, sources = _collect_shields(
            [_KAENIC], level=11, bonus_hp=1200.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, max_mana=2000.0,
            assume_fimbulwinter_shield=True, assume_kaenic_shield=False,
        )
        self.assertAlmostEqual(totals["magical"], 0.0, places=6)
        self.assertFalse(any(s[0] == _KAENIC for s in sources))

    def test_fimbulwinter_flag_does_not_credit_chainlaced(self) -> None:
        totals, sources = _collect_shields(
            [_CHAINLACED], level=11, bonus_hp=1000.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, max_mana=2000.0,
            assume_fimbulwinter_shield=True, assume_chainlaced_shield=False,
        )
        self.assertAlmostEqual(totals["magical"], 0.0, places=6)
        self.assertFalse(any(s[0] == _CHAINLACED for s in sources))

    def test_seraphs_flag_does_not_credit_fimbulwinter(self) -> None:
        totals, sources = _collect_shields(
            [_FIMB], level=11, bonus_hp=0.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, max_mana=2000.0,
            assume_seraphs_shield=True, assume_fimbulwinter_shield=False,
        )
        self.assertAlmostEqual(totals[ANY], 0.0, places=6)
        self.assertFalse(any(s[0] == _FIMB for s in sources))

    def test_eclipse_flag_does_not_credit_fimbulwinter(self) -> None:
        totals, sources = _collect_shields(
            [_FIMB], level=11, bonus_hp=0.0, bonus_ad=0.0,
            is_ranged=False, max_hp=3000.0, max_mana=2000.0,
            assume_eclipse_shield=True, assume_fimbulwinter_shield=False,
        )
        self.assertAlmostEqual(totals[ANY], 0.0, places=6)
        self.assertFalse(any(s[0] == _FIMB for s in sources))


class FimbulwinterEhpSeamTests(unittest.TestCase):
    """compute_ehp on a mana champ: OFF byte-identical; ON raises all 3 axes."""

    def setUp(self) -> None:
        self.snap = DataSnapshot.load()

    def test_off_is_byte_identical_default(self) -> None:
        base = compute_ehp(self.snap, "Sion", 11, item_ids=[_FIMB], mode="SR")
        off = compute_ehp(
            self.snap, "Sion", 11, item_ids=[_FIMB], mode="SR",
            assume_fimbulwinter_shield=False,
        )
        self.assertEqual(off.to_dict(), base.to_dict())

    def test_on_raises_all_three_axes(self) -> None:
        off = compute_ehp(self.snap, "Sion", 11, item_ids=[_FIMB], mode="SR")
        on = compute_ehp(
            self.snap, "Sion", 11, item_ids=[_FIMB], mode="SR",
            assume_fimbulwinter_shield=True,
        )
        # ANY (generic) shield lifts every axis (the flat 100 alone guarantees it).
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertGreater(on.true_ehp, off.true_ehp)


class FimbulwinterRegressionTests(unittest.TestCase):
    """Shieldless items stay zero even when the flag is armed."""

    def test_shieldless_item_stays_zero(self) -> None:
        totals, _ = _collect_shields(
            [_THORNMAIL], level=11, bonus_hp=1000.0, bonus_ad=1000.0,
            is_ranged=False, max_hp=3000.0, max_mana=2000.0,
            assume_fimbulwinter_shield=True,
        )
        self.assertTrue(all(v == 0.0 for v in totals.values()))


class FimbulwinterEngineVersionPin(unittest.TestCase):
    """The Fimbulwinter shield credit bumps the engine revision."""

    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.247.0")


if __name__ == "__main__":
    unittest.main()

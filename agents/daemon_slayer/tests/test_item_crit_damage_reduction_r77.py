"""R77 - item-keyed incoming CRIT-DAMAGE REDUCTION into the EHP scorer.

Randuin's Omen (SR 3143 / Arena 223143) Resilience "30% reduced critical
strike damage taken" was registered ``defensive_only=True`` with a NOTE only:
the DS ranker gave its signature crit-DR ZERO effective-HP credit. R77 wires
an item-keyed physical-denominator multiplier behind the default-OFF
``assume_item_crit_dr`` seam, mirroring the champion percent-DR family
(``mitigation_multipliers``) which is champion_id-keyed and cannot see items.

WIN-anchor (data/rewind_history.db): Randuin's built = 344 games, 54.7% WR vs
the 50.0% baseline (+4.7pp) - a proven defensive buy whose crit-DR the ranker
ignored. Crit damage is PHYSICAL, so only ``physical_ehp`` moves; magical /
true are untouched. The crit-affected SHARE of incoming physical is a
conservative operator-tunable midpoint (``_ASSUMED_INCOMING_CRIT_SHARE``) -
the live feed we lack, same class as the flat-mitigation instance count. The
live default-ON flip is live-gated (docs/LIVE_GAME_GATED_SYNC.md).

DEFAULT-OFF is byte-identical: ``assume_item_crit_dr=False`` short-circuits to
the identity multiplier before any item is inspected, and the new
``ItemEffect.crit_damage_reduction`` field defaults 0.0 so every other item
passes through unchanged.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import (
    _ASSUMED_INCOMING_CRIT_SHARE,
    compute_ehp,
    item_crit_dr_multiplier,
)
from agents.daemon_slayer.effects import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import ItemEffect

SNAP = DataSnapshot.load()
RANDUINS = "3143"
RANDUINS_ARENA = "223143"
CRIT_DR = 0.30


class ItemCritDrFieldTests(unittest.TestCase):
    def test_itemeffect_default_field_zero(self):
        # New field appended at the END with a 0.0 default -> every existing
        # entry is byte-identical.
        self.assertEqual(
            ItemEffect(item_id="x", name="x").crit_damage_reduction, 0.0
        )

    def test_randuins_sr_field_pinned(self):
        self.assertAlmostEqual(
            ITEM_EFFECTS[RANDUINS].crit_damage_reduction, CRIT_DR
        )

    def test_randuins_arena_mirror_field_pinned(self):
        self.assertAlmostEqual(
            ITEM_EFFECTS[RANDUINS_ARENA].crit_damage_reduction, CRIT_DR
        )

    def test_randuins_still_defensive_only(self):
        # The DPS side stays a no-op; the field only adds the EHP-side credit.
        self.assertTrue(ITEM_EFFECTS[RANDUINS].defensive_only)

    def test_no_aram_323143_in_pool(self):
        # The ARAM mirror is absent from the 16.13.1 pool - guard the
        # assumption so a future pool add is a loud failure, not silent
        # under-credit.
        self.assertNotIn("323143", ITEM_EFFECTS)

    def test_sibling_defensive_items_carry_no_crit_dr(self):
        # Plated Steelcaps (AA-DR) + Frozen Heart (AS-aura) are a DIFFERENT
        # incoming-DR lane, intentionally NOT modeled here (one item this
        # cycle) - they must stay at 0.0.
        self.assertEqual(ITEM_EFFECTS["3047"].crit_damage_reduction, 0.0)
        self.assertEqual(ITEM_EFFECTS["3110"].crit_damage_reduction, 0.0)


class ItemCritDrMultiplierTests(unittest.TestCase):
    def _expected(self) -> float:
        return 1.0 - CRIT_DR * _ASSUMED_INCOMING_CRIT_SHARE

    def test_midpoint_bounds(self):
        # Conservative + bounded: a share in (0, 1) never over- or
        # under-reaches (a 30% crit-DR cannot reduce >30% of physical).
        self.assertGreater(_ASSUMED_INCOMING_CRIT_SHARE, 0.0)
        self.assertLessEqual(_ASSUMED_INCOMING_CRIT_SHARE, 1.0)

    def test_off_is_identity(self):
        self.assertEqual(item_crit_dr_multiplier((RANDUINS,), False), 1.0)

    def test_on_randuins_exact(self):
        self.assertAlmostEqual(
            item_crit_dr_multiplier((RANDUINS,), True), self._expected()
        )
        self.assertLess(item_crit_dr_multiplier((RANDUINS,), True), 1.0)

    def test_arena_mirror_same_multiplier(self):
        self.assertAlmostEqual(
            item_crit_dr_multiplier((RANDUINS_ARENA,), True), self._expected()
        )

    def test_on_without_randuins_is_identity(self):
        self.assertEqual(item_crit_dr_multiplier(("3047", "1001"), True), 1.0)

    def test_empty_build_identity(self):
        self.assertEqual(item_crit_dr_multiplier((), True), 1.0)


class ComputeEhpCritDrTests(unittest.TestCase):
    CHAMP = "Ashe"
    LEVEL = 11

    def _off(self, items):
        return compute_ehp(
            SNAP, self.CHAMP, self.LEVEL, item_ids=items,
            assume_item_crit_dr=False,
        )

    def _on(self, items):
        return compute_ehp(
            SNAP, self.CHAMP, self.LEVEL, item_ids=items,
            assume_item_crit_dr=True,
        )

    def test_default_now_on_matches_explicit_on(self):
        # B45 flip 2026-07-06: assume_item_crit_dr defaults ON now, so a call
        # with no flag matches the explicitly-armed result (was default-OFF; the
        # explicit-False opt-out is still covered by the _off-vs-_on tests below).
        base = compute_ehp(SNAP, self.CHAMP, self.LEVEL, item_ids=(RANDUINS,))
        on = self._on((RANDUINS,))
        self.assertEqual(base.physical_ehp, on.physical_ehp)
        self.assertEqual(base.magical_ehp, on.magical_ehp)
        self.assertEqual(base.true_ehp, on.true_ehp)

    def test_on_raises_physical_ehp_only(self):
        off = self._off((RANDUINS,))
        on = self._on((RANDUINS,))
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertAlmostEqual(on.magical_ehp, off.magical_ehp)
        self.assertAlmostEqual(on.true_ehp, off.true_ehp)

    def test_on_physical_ehp_exact_ratio(self):
        off = self._off((RANDUINS,))
        on = self._on((RANDUINS,))
        mult = 1.0 - CRIT_DR * _ASSUMED_INCOMING_CRIT_SHARE
        # denominator gains a x``mult`` factor -> physical_ehp scales by 1/mult.
        self.assertAlmostEqual(on.physical_ehp / off.physical_ehp, 1.0 / mult, places=4)

    def test_build_without_randuins_on_is_byte_identical(self):
        off = self._off(("3047",))
        on = self._on(("3047",))
        self.assertEqual(on.physical_ehp, off.physical_ehp)

    def test_no_item_build_on_byte_identical(self):
        off = compute_ehp(
            SNAP, self.CHAMP, self.LEVEL, assume_item_crit_dr=False
        )
        on = compute_ehp(
            SNAP, self.CHAMP, self.LEVEL, assume_item_crit_dr=True
        )
        self.assertEqual(on.physical_ehp, off.physical_ehp)
        self.assertEqual(on.magical_ehp, off.magical_ehp)
        self.assertEqual(on.true_ehp, off.true_ehp)


class EngineVersionTests(unittest.TestCase):
    def test_engine_version_bumped(self):
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.234.0")


if __name__ == "__main__":
    unittest.main()

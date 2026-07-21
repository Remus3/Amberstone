"""R86 - item-keyed enemy ATTACK-SPEED-SLOW aura into the EHP scorer.

Frozen Heart (SR 3110 / ARAM 323110 / Arena 223110) "Winter's Caress"
reduces the Attack Speed of nearby enemy champions by 20% (DDragon 16.13.1:
"Reduce the Attack Speed of nearby champions by 20%"). It was registered
``defensive_only=True`` with a NOTE only - the DS ranker gave its signature
anti-AA aura ZERO effective-HP credit, though the item's +armor already
counted. A 20% enemy AS slow means nearby enemies auto-attack at 0.80x rate,
so the RATE of incoming basic-attack damage drops 20% - the SAME physical-EHP
effect as a 20% per-hit basic-attack damage reduction (R80's Steelcaps lane),
just sourced from attack RATE rather than per-hit magnitude.

R86 wires an item-keyed physical-denominator multiplier behind the default-OFF
``assume_item_enemy_as_slow`` seam, a distinct lane from R77's crit-DR and
R80's per-hit AA-DR: each item carries only its own reduction, so the seams
never cross-credit and STACK multiplicatively when a build carries more than
one (Frozen Heart AS-slow x Steelcaps per-hit AA-DR). Basic-attack damage is
PHYSICAL, so only ``physical_ehp`` moves; magical / true are untouched. The
basic-attack SHARE of incoming physical reuses the conservative operator-tunable
midpoint ``_ASSUMED_INCOMING_AA_SHARE`` (the AA portion of incoming physical -
the same live feed R80 lacks). The live default-ON flip is live-gated
(docs/LIVE_GAME_GATED_SYNC.md).

DEFAULT-OFF is byte-identical: ``assume_item_enemy_as_slow=False`` short-circuits
to the identity multiplier before any item is inspected, and the new
``ItemEffect.enemy_attack_speed_slow`` field defaults 0.0 so every other item
passes through unchanged.
"""
from __future__ import annotations

import unittest

import agents.daemon_slayer as daemon_slayer
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import (
    _ASSUMED_INCOMING_AA_SHARE,
    compute_ehp,
    item_enemy_as_slow_multiplier,
)
from agents.daemon_slayer.effects import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import ItemEffect

SNAP = DataSnapshot.load()
FROZEN_HEART = "3110"
FROZEN_HEART_ARAM = "323110"
FROZEN_HEART_ARENA = "223110"
STEELCAPS = "3047"
RANDUINS = "3143"
AS_SLOW = 0.20


class ItemEnemyAsSlowFieldTests(unittest.TestCase):
    def test_itemeffect_default_field_zero(self):
        # New field appended at the END with a 0.0 default -> every existing
        # entry is byte-identical.
        self.assertEqual(
            ItemEffect(item_id="x", name="x").enemy_attack_speed_slow, 0.0
        )

    def test_frozen_heart_sr_field_pinned(self):
        self.assertAlmostEqual(
            ITEM_EFFECTS[FROZEN_HEART].enemy_attack_speed_slow, AS_SLOW
        )

    def test_frozen_heart_aram_mirror_field_pinned(self):
        self.assertAlmostEqual(
            ITEM_EFFECTS[FROZEN_HEART_ARAM].enemy_attack_speed_slow, AS_SLOW
        )

    def test_frozen_heart_arena_mirror_field_pinned(self):
        self.assertAlmostEqual(
            ITEM_EFFECTS[FROZEN_HEART_ARENA].enemy_attack_speed_slow, AS_SLOW
        )

    def test_frozen_heart_still_defensive_only(self):
        # The DPS side stays a no-op; the field only adds the EHP-side credit.
        self.assertTrue(ITEM_EFFECTS[FROZEN_HEART].defensive_only)

    def test_lanes_do_not_cross_credit(self):
        # R77 crit-DR, R80 per-hit AA-DR, R86 AS-slow are DISTINCT item-keyed
        # lanes - each item carries only its own reduction.
        self.assertEqual(ITEM_EFFECTS[FROZEN_HEART].basic_attack_damage_reduction, 0.0)
        self.assertEqual(ITEM_EFFECTS[FROZEN_HEART].crit_damage_reduction, 0.0)
        self.assertEqual(ITEM_EFFECTS[STEELCAPS].enemy_attack_speed_slow, 0.0)
        self.assertEqual(ITEM_EFFECTS[RANDUINS].enemy_attack_speed_slow, 0.0)


class ItemEnemyAsSlowMultiplierTests(unittest.TestCase):
    def _expected(self) -> float:
        return 1.0 - AS_SLOW * _ASSUMED_INCOMING_AA_SHARE

    def test_off_is_identity(self):
        self.assertEqual(item_enemy_as_slow_multiplier((FROZEN_HEART,), False), 1.0)

    def test_on_frozen_heart_exact(self):
        self.assertAlmostEqual(
            item_enemy_as_slow_multiplier((FROZEN_HEART,), True), self._expected()
        )
        self.assertLess(item_enemy_as_slow_multiplier((FROZEN_HEART,), True), 1.0)

    def test_aram_mirror_same_multiplier(self):
        self.assertAlmostEqual(
            item_enemy_as_slow_multiplier((FROZEN_HEART_ARAM,), True), self._expected()
        )

    def test_arena_mirror_same_multiplier(self):
        self.assertAlmostEqual(
            item_enemy_as_slow_multiplier((FROZEN_HEART_ARENA,), True), self._expected()
        )

    def test_on_without_frozen_heart_is_identity(self):
        self.assertEqual(
            item_enemy_as_slow_multiplier((STEELCAPS, "1001"), True), 1.0
        )

    def test_empty_build_identity(self):
        self.assertEqual(item_enemy_as_slow_multiplier((), True), 1.0)


class ComputeEhpEnemyAsSlowTests(unittest.TestCase):
    CHAMP = "Ashe"
    LEVEL = 11

    def _off(self, items):
        return compute_ehp(
            SNAP, self.CHAMP, self.LEVEL, item_ids=items,
            assume_item_enemy_as_slow=False,
        )

    def _on(self, items):
        return compute_ehp(
            SNAP, self.CHAMP, self.LEVEL, item_ids=items,
            assume_item_enemy_as_slow=True,
        )

    def test_default_is_on_armed(self):
        # R86 flipped default-ON (Live-Gated B47): a bare call must equal
        # the explicit-ON call.
        base = compute_ehp(SNAP, self.CHAMP, self.LEVEL, item_ids=(FROZEN_HEART,))
        on = self._on((FROZEN_HEART,))
        self.assertEqual(base.physical_ehp, on.physical_ehp)
        self.assertEqual(base.magical_ehp, on.magical_ehp)
        self.assertEqual(base.true_ehp, on.true_ehp)

    def test_on_raises_physical_ehp_only(self):
        off = self._off((FROZEN_HEART,))
        on = self._on((FROZEN_HEART,))
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertAlmostEqual(on.magical_ehp, off.magical_ehp)
        self.assertAlmostEqual(on.true_ehp, off.true_ehp)

    def test_on_physical_ehp_exact_ratio(self):
        off = self._off((FROZEN_HEART,))
        on = self._on((FROZEN_HEART,))
        mult = 1.0 - AS_SLOW * _ASSUMED_INCOMING_AA_SHARE
        # denominator gains a x``mult`` factor -> physical_ehp scales by 1/mult.
        self.assertAlmostEqual(
            on.physical_ehp / off.physical_ehp, 1.0 / mult, places=4
        )

    def test_build_without_frozen_heart_on_is_byte_identical(self):
        off = self._off((RANDUINS,))
        on = self._on((RANDUINS,))
        self.assertEqual(on.physical_ehp, off.physical_ehp)

    def test_no_item_build_on_byte_identical(self):
        off = compute_ehp(
            SNAP, self.CHAMP, self.LEVEL, assume_item_enemy_as_slow=False
        )
        on = compute_ehp(
            SNAP, self.CHAMP, self.LEVEL, assume_item_enemy_as_slow=True
        )
        self.assertEqual(on.physical_ehp, off.physical_ehp)
        self.assertEqual(on.magical_ehp, off.magical_ehp)
        self.assertEqual(on.true_ehp, off.true_ehp)


class EngineVersionTests(unittest.TestCase):
    def test_engine_version_bumped(self):
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.237.0")


if __name__ == "__main__":
    unittest.main()

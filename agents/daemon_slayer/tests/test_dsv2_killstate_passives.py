"""DSV2 (P6-G5 residual 2): takedown / kill-state item-passive valuation.

Root cause (P6-G5, ledger 424): the burst / auto scorers had NO seam for the
"kill-state" item passives, so three lethality-adjacent items were under-valued:

  * Hubris 6697 Eminence - "Scoring a takedown ... generates a permanent stack
    and grants you 15 (+ 2 per stack) bonus attack damage for 90 seconds"
    (Meraki 16.12.1). The bonus AD was flagged "not modeled" in _effects_data.
  * The Collector 6676 Death - "If you deal post-mitigation damage that would
    leave a champion below 5% of their maximum health, execute them" (Meraki
    16.12.1). The execute was "a finisher, not a per-rotation DPS proc".
  * Death's Dance 6333 Defy - "heals you for 75% bonus AD over 2s" on takedown.
    Its takedown payoff is DEFENSIVE and is already valued on the survivability
    axis (ehp.py ItemHeal.takedown_gated, ENGINE 1.57.0). On the OFFENSE axis the
    kill-state seam credits it nothing - crediting phantom damage would be wrong.

DSV2 adds the seam: ``compute_dps`` / ``compute_burst_damage`` gain an
``assume_takedown`` kwarg (default False = byte-identical). When True the wielder
is assumed to hold ``_ASSUMED_TAKEDOWN_STACKS`` (= 1) Eminence stack worth of
bonus AD, and Collector's execute is credited as a kill-state finisher of
``execute_max_hp_pct * target_max_hp`` true damage. Default OFF leaves every
existing ranking byte-identical; live rank flips stay validation-gated.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_types import ItemEffect
from agents.daemon_slayer.burst import compute_burst_damage, rank_items_by_burst
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import _ASSUMED_TAKEDOWN_STACKS, compute_dps
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    collect_effects,
    total_execute_max_hp_pct,
    total_takedown_bonus_ad,
)

# Item ids carrying the kill-state passives across SR / Arena / ARAM stores.
_HUBRIS_IDS = ("6697", "226697", "126697")
_COLLECTOR_IDS = ("6676", "667666", "226676")
_DD_IDS = ("6333", "226333")


class KillStateSchemaDefaults(unittest.TestCase):
    """The three new ItemEffect fields default 0.0 (byte-identical seam OFF)."""

    def test_defaults_zero(self) -> None:
        eff = ItemEffect(item_id="x", name="x")
        self.assertEqual(eff.takedown_bonus_ad_base, 0.0)
        self.assertEqual(eff.takedown_bonus_ad_per_stack, 0.0)
        self.assertEqual(eff.execute_max_hp_pct, 0.0)


class HubrisEminenceData(unittest.TestCase):
    """Hubris ids pin Eminence to Meraki 15 (+2 per stack) bonus AD."""

    def test_hubris_eminence_pins(self) -> None:
        for iid in _HUBRIS_IDS:
            eff = ITEM_EFFECTS[iid]
            self.assertAlmostEqual(eff.takedown_bonus_ad_base, 15.0, msg=iid)
            self.assertAlmostEqual(eff.takedown_bonus_ad_per_stack, 2.0, msg=iid)
            # Lethality stat is untouched by the Eminence add.
            self.assertAlmostEqual(eff.lethality, 18.0, msg=iid)


class CollectorExecuteData(unittest.TestCase):
    """Collector ids pin Death execute threshold to Meraki 5% max HP."""

    def test_collector_execute_pins(self) -> None:
        for iid in _COLLECTOR_IDS:
            eff = ITEM_EFFECTS[iid]
            self.assertAlmostEqual(eff.execute_max_hp_pct, 0.05, msg=iid)
            # Lethality stat untouched; execute is not a takedown-AD item.
            self.assertEqual(eff.takedown_bonus_ad_base, 0.0, msg=iid)


class DeathsDanceNoOffense(unittest.TestCase):
    """DD carries NO offense kill-state field; its takedown value is EHP-side."""

    def test_dd_offense_seam_noop(self) -> None:
        for iid in _DD_IDS:
            eff = ITEM_EFFECTS[iid]
            self.assertEqual(eff.takedown_bonus_ad_base, 0.0, msg=iid)
            self.assertEqual(eff.takedown_bonus_ad_per_stack, 0.0, msg=iid)
            self.assertEqual(eff.execute_max_hp_pct, 0.0, msg=iid)
            # The takedown payoff still lives on the survivability axis.
            self.assertIsNotNone(eff.heal, msg=iid)
            self.assertTrue(eff.heal.takedown_gated, msg=iid)


class EffectsHelpers(unittest.TestCase):
    """Aggregation helpers resolve the seam math."""

    def test_takedown_bonus_ad_single_stack(self) -> None:
        effs = collect_effects(["6697"])
        # 15 base + 2 per stack * 1 assumed stack = 17 bonus AD.
        self.assertEqual(_ASSUMED_TAKEDOWN_STACKS, 1)
        self.assertAlmostEqual(
            total_takedown_bonus_ad(effs, _ASSUMED_TAKEDOWN_STACKS), 17.0
        )
        self.assertAlmostEqual(total_takedown_bonus_ad(effs, 5), 25.0)

    def test_execute_pct_helper(self) -> None:
        self.assertAlmostEqual(
            total_execute_max_hp_pct(collect_effects(["6676"])), 0.05
        )
        self.assertEqual(total_execute_max_hp_pct(collect_effects([])), 0.0)
        # A non-kill-state build contributes nothing.
        self.assertEqual(total_execute_max_hp_pct(collect_effects(["3031"])), 0.0)


class ComputeDpsSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        base = compute_dps(self.snap, "Talon", level=11, item_ids=["6697"],
                           target_armor=80)
        off = compute_dps(self.snap, "Talon", level=11, item_ids=["6697"],
                          target_armor=80, assume_takedown=False)
        self.assertEqual(base.weighted_dps, off.weighted_dps)

    def test_hubris_takedown_raises_dps(self) -> None:
        off = compute_dps(self.snap, "Talon", level=11, item_ids=["6697"],
                          target_armor=80)
        on = compute_dps(self.snap, "Talon", level=11, item_ids=["6697"],
                         target_armor=80, assume_takedown=True)
        self.assertGreater(on.weighted_dps, off.weighted_dps)

    def test_collector_no_sustained_dps_change(self) -> None:
        # The execute is a one-shot finisher, NOT sustained DPS - compute_dps
        # must stay byte-identical even with the seam ON for a Collector build.
        off = compute_dps(self.snap, "Talon", level=11, item_ids=["6676"],
                          target_armor=80, target_max_hp=2000)
        on = compute_dps(self.snap, "Talon", level=11, item_ids=["6676"],
                         target_armor=80, target_max_hp=2000, assume_takedown=True)
        self.assertEqual(off.weighted_dps, on.weighted_dps)


class ComputeBurstSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        base = compute_burst_damage(self.snap, "Talon", level=11,
                                    item_ids=["6697"], target_armor=80,
                                    target_max_hp=2000)
        off = compute_burst_damage(self.snap, "Talon", level=11,
                                   item_ids=["6697"], target_armor=80,
                                   target_max_hp=2000, assume_takedown=False)
        self.assertEqual(base.total_burst_damage, off.total_burst_damage)
        self.assertEqual(off.takedown_bonus_ad, 0.0)
        self.assertEqual(off.execute_finisher_damage, 0.0)

    def test_hubris_takedown_raises_burst(self) -> None:
        off = compute_burst_damage(self.snap, "Talon", level=11,
                                   item_ids=["6697"], target_armor=80,
                                   target_max_hp=2000)
        on = compute_burst_damage(self.snap, "Talon", level=11,
                                  item_ids=["6697"], target_armor=80,
                                  target_max_hp=2000, assume_takedown=True)
        self.assertGreater(on.total_burst_damage, off.total_burst_damage)
        self.assertAlmostEqual(on.takedown_bonus_ad, 17.0)
        # The AD raises ability AND auto-attack damage (Talon scales off AD).
        self.assertGreater(on.ability_damage, off.ability_damage)

    def test_collector_execute_finisher(self) -> None:
        on = compute_burst_damage(self.snap, "Talon", level=11,
                                  item_ids=["6676"], target_armor=80,
                                  target_max_hp=2000, assume_takedown=True)
        # 5% of 2000 max HP = 100 true-damage finisher, folded into the total.
        self.assertAlmostEqual(on.execute_finisher_damage, 100.0)
        off = compute_burst_damage(self.snap, "Talon", level=11,
                                   item_ids=["6676"], target_armor=80,
                                   target_max_hp=2000, assume_takedown=False)
        self.assertAlmostEqual(
            on.total_burst_damage - off.total_burst_damage, 100.0, places=3
        )

    def test_collector_execute_needs_target_hp(self) -> None:
        # No target_max_hp signal -> no execute credit (can't size 5%).
        on = compute_burst_damage(self.snap, "Talon", level=11,
                                  item_ids=["6676"], assume_takedown=True)
        self.assertEqual(on.execute_finisher_damage, 0.0)

    def test_deaths_dance_offense_byte_identical(self) -> None:
        # DD has no offense kill-state field -> seam ON == seam OFF (no phantom).
        off = compute_burst_damage(self.snap, "Talon", level=11,
                                   item_ids=["6333"], target_armor=80,
                                   target_max_hp=2000)
        on = compute_burst_damage(self.snap, "Talon", level=11,
                                  item_ids=["6333"], target_armor=80,
                                  target_max_hp=2000, assume_takedown=True)
        self.assertEqual(off.total_burst_damage, on.total_burst_damage)
        self.assertEqual(on.execute_finisher_damage, 0.0)
        self.assertEqual(on.takedown_bonus_ad, 0.0)


class RankThreadingByteIdentical(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_rank_default_off_identical(self) -> None:
        base = rank_items_by_burst(self.snap, "Talon", level=11,
                                   target_armor=80, target_max_hp=2000, top_n=5)
        off = rank_items_by_burst(self.snap, "Talon", level=11,
                                  target_armor=80, target_max_hp=2000, top_n=5,
                                  assume_takedown=False)
        self.assertEqual(
            [r.item_id for r in base.ranked],
            [r.item_id for r in off.ranked],
        )


class EngineVersionPin(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.205.0")


if __name__ == "__main__":
    unittest.main()

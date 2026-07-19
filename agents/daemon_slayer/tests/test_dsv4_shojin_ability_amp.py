"""DSV4 (P6-G5 / G2-residual bucket-B): Spear of Shojin ability-amp valuation.

Root cause (P6-G2 work-map bucket B + the _effects_data note at item 3161): the
ability scorers had NO seam for Spear of Shojin's Focused Will, a stacking
ability/passive damage amp (Meraki 16.12.1: "3% per stack ... max 4 stacks" =
12%). The item carried ``defensive_only=True`` with the note "ability damage not
DPS-modeled", so an ability-reliant build that buys Shojin saw zero damage value
from it - only its raw AD/AH stats. Focused Will amps ABILITIES and PASSIVES
only, never basic attacks (the generic ``damage_amp_pct`` was deliberately left
off Shojin since it would amp AAs too).

DSV4 adds the seam: ``compute_ability_dps`` / ``compute_burst_damage`` /
``rank_items_by_burst`` gain an ``assume_ability_amp`` kwarg (default False =
byte-identical). When True the wielder is assumed to hold
``_ASSUMED_ABILITY_AMP_STACKS`` (= 4, a developed fight at max stacks) worth of
Focused Will, multiplying ONLY the ability damage (spell sum / burst
``ability_total``) by ``1 + 0.12``; auto-attack damage is untouched. Default OFF
leaves every existing ranking byte-identical; the live rank flip stays
validation-gated (DS Phase-D class).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_types import ItemEffect
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.burst import compute_burst_damage, rank_items_by_burst
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import _ASSUMED_ABILITY_AMP_STACKS
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    collect_effects,
    total_ability_damage_amp,
)

# Spear of Shojin across the SR + Arena stores.
_SHOJIN_IDS = ("3161", "223161")


class AbilityAmpSchemaDefaults(unittest.TestCase):
    """The two new ItemEffect fields default to the inert (seam-OFF) values."""

    def test_defaults_zero(self) -> None:
        eff = ItemEffect(item_id="x", name="x")
        self.assertEqual(eff.ability_damage_amp_per_stack, 0.0)
        self.assertEqual(eff.ability_damage_amp_max_stacks, 0)


class ShojinFocusedWillData(unittest.TestCase):
    """Shojin ids pin Focused Will to Meraki 3% per stack, 4 stacks max."""

    def test_shojin_focused_will_pins(self) -> None:
        for iid in _SHOJIN_IDS:
            eff = ITEM_EFFECTS[iid]
            self.assertAlmostEqual(eff.ability_damage_amp_per_stack, 0.03, msg=iid)
            self.assertEqual(eff.ability_damage_amp_max_stacks, 4, msg=iid)


class AbilityAmpHelper(unittest.TestCase):
    """``total_ability_damage_amp`` resolves the stacked amp fraction."""

    def test_assumed_stacks_constant(self) -> None:
        self.assertEqual(_ASSUMED_ABILITY_AMP_STACKS, 4)

    def test_shojin_full_stacks(self) -> None:
        effs = collect_effects(["3161"])
        # 0.03 per stack * min(4 assumed, 4 max) = 0.12.
        self.assertAlmostEqual(
            total_ability_damage_amp(effs, _ASSUMED_ABILITY_AMP_STACKS), 0.12
        )

    def test_stacks_capped_at_item_max(self) -> None:
        effs = collect_effects(["3161"])
        # Assuming MORE than the item's 4-stack cap still tops out at 12%.
        self.assertAlmostEqual(total_ability_damage_amp(effs, 9), 0.12)
        # Fewer stacks scale linearly: 2 stacks = 6%.
        self.assertAlmostEqual(total_ability_damage_amp(effs, 2), 0.06)

    def test_non_shojin_zero(self) -> None:
        self.assertEqual(total_ability_damage_amp(collect_effects([]), 4), 0.0)
        # Infinity Edge (3031) carries no Focused Will field.
        self.assertEqual(total_ability_damage_amp(collect_effects(["3031"]), 4), 0.0)


class ComputeAbilityDpsSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        base = compute_ability_dps(self.snap, "Veigar", 11, item_ids=["3161"],
                                   target_mr=60)
        off = compute_ability_dps(self.snap, "Veigar", 11, item_ids=["3161"],
                                  target_mr=60, assume_ability_amp=False)
        self.assertEqual(base.total_ability_dps, off.total_ability_dps)

    def test_shojin_amp_raises_ability_dps_12pct(self) -> None:
        off = compute_ability_dps(self.snap, "Veigar", 11, item_ids=["3161"],
                                  target_mr=60)
        on = compute_ability_dps(self.snap, "Veigar", 11, item_ids=["3161"],
                                 target_mr=60, assume_ability_amp=True)
        self.assertGreater(on.total_ability_dps, off.total_ability_dps)
        # Shojin alone carries no DoT proc, so the spell sum is amped exactly 12%.
        self.assertAlmostEqual(
            on.total_ability_dps, off.total_ability_dps * 1.12, places=2
        )

    def test_non_shojin_build_byte_identical_on(self) -> None:
        # A build without Shojin is unchanged even with the seam ON.
        off = compute_ability_dps(self.snap, "Veigar", 11, item_ids=["3089"],
                                  target_mr=60)
        on = compute_ability_dps(self.snap, "Veigar", 11, item_ids=["3089"],
                                 target_mr=60, assume_ability_amp=True)
        self.assertAlmostEqual(on.total_ability_dps, off.total_ability_dps, places=4)


class ComputeBurstSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        base = compute_burst_damage(self.snap, "Veigar", 11, item_ids=["3161"],
                                    target_mr=60, target_max_hp=2000)
        off = compute_burst_damage(self.snap, "Veigar", 11, item_ids=["3161"],
                                   target_mr=60, target_max_hp=2000,
                                   assume_ability_amp=False)
        self.assertEqual(base.total_burst_damage, off.total_burst_damage)

    def test_shojin_amp_raises_ability_only(self) -> None:
        off = compute_burst_damage(self.snap, "Veigar", 11, item_ids=["3161"],
                                   target_mr=60, target_max_hp=2000)
        on = compute_burst_damage(self.snap, "Veigar", 11, item_ids=["3161"],
                                  target_mr=60, target_max_hp=2000,
                                  assume_ability_amp=True)
        self.assertGreater(on.ability_damage, off.ability_damage)
        # Ability damage amped exactly 12%; AA damage is NOT touched.
        self.assertAlmostEqual(
            on.ability_damage, off.ability_damage * 1.12, places=2
        )
        self.assertAlmostEqual(
            on.auto_attack_damage, off.auto_attack_damage, places=4
        )

    def test_non_shojin_burst_byte_identical_on(self) -> None:
        off = compute_burst_damage(self.snap, "Veigar", 11, item_ids=["3089"],
                                   target_mr=60, target_max_hp=2000)
        on = compute_burst_damage(self.snap, "Veigar", 11, item_ids=["3089"],
                                  target_mr=60, target_max_hp=2000,
                                  assume_ability_amp=True)
        self.assertAlmostEqual(
            on.total_burst_damage, off.total_burst_damage, places=4
        )


class RankThreadingByteIdentical(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_rank_default_off_identical(self) -> None:
        base = rank_items_by_burst(self.snap, "Veigar", level=11,
                                   target_mr=60, target_max_hp=2000, top_n=5)
        off = rank_items_by_burst(self.snap, "Veigar", level=11,
                                  target_mr=60, target_max_hp=2000, top_n=5,
                                  assume_ability_amp=False)
        self.assertEqual(
            [r.item_id for r in base.ranked],
            [r.item_id for r in off.ranked],
        )


class EngineVersionPin(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.222.0")


if __name__ == "__main__":
    unittest.main()

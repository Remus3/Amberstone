"""ENGINE 1.24.0 (2026-05-21) - per-item flat AH wired into compute_ability_dps.

Sibling of ``test_aram_ability_haste_consumption.py``; that file proves
the ARAM-mode aram_ability_haste exposure + consumption end-to-end,
this file proves the item-id-driven ``base_ah`` lane lands the same
haste-formula compression for SR (and stacks additively with the ARAM
delta in ARAM mode).

Coverage:

* ``RegistryShapeTests`` - registry sanity (size, value bounds, no
  duplicates, every entry parseable as float).
* ``TotalItemAhTests`` - summer correctness (empty / single / multi-item /
  unknown ids contribute 0 / duplicate ids stack).
* ``EndToEndSrTests`` - SR builds with known AH items compress per-spell
  cooldowns via Riot's canonical haste formula
  ``eff_cd = base / (1 + h/100)``.
* ``ArAndItemStackTests`` - ARAM mode folds the aram_ability_haste delta
  ON TOP of base_ah; the sum drives the haste compression.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._item_ability_haste import (
    _ITEM_ABILITY_HASTE,
    item_ability_haste,
    total_item_ability_haste,
)
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.data_loader import DataSnapshot


class RegistryShapeTests(unittest.TestCase):

    def test_registry_size_pinned_for_patch_16_10_1(self) -> None:
        # 220 items in 16.10.1; if a patch refresh changes the count,
        # rebaseline this in the same commit.
        self.assertEqual(len(_ITEM_ABILITY_HASTE), 220)

    def test_every_entry_is_positive_float(self) -> None:
        for iid, ah in _ITEM_ABILITY_HASTE.items():
            self.assertIsInstance(ah, float, f"{iid} is not float: {ah!r}")
            self.assertGreater(ah, 0.0, f"{iid} has non-positive AH: {ah}")
            # Reasonable upper bound (no single item grants >50 AH today).
            self.assertLessEqual(ah, 50.0, f"{iid} has suspicious AH: {ah}")

    def test_known_high_value_items_pinned(self) -> None:
        # Spot-check the canonical SR AH items.
        self.assertEqual(_ITEM_ABILITY_HASTE["3158"], 10.0)  # Ionian Boots
        self.assertEqual(_ITEM_ABILITY_HASTE["3110"], 20.0)  # Frozen Heart
        self.assertEqual(_ITEM_ABILITY_HASTE["4629"], 25.0)  # Cosmic Drive
        self.assertEqual(_ITEM_ABILITY_HASTE["3071"], 20.0)  # Black Cleaver
        self.assertEqual(_ITEM_ABILITY_HASTE["3115"], 15.0)  # Nashor's Tooth
        self.assertEqual(_ITEM_ABILITY_HASTE["3100"], 10.0)  # Lich Bane

    def test_arena_mirror_ids_present(self) -> None:
        # Arena 22-prefix duplicates should be in the registry; their
        # values may diverge from the SR original (Arena often boosts
        # the values on the duplicate id).
        self.assertIn("223110", _ITEM_ABILITY_HASTE)
        self.assertIn("224629", _ITEM_ABILITY_HASTE)
        # Cosmic Drive Arena (35) > SR (25).
        self.assertGreater(
            _ITEM_ABILITY_HASTE["224629"], _ITEM_ABILITY_HASTE["4629"],
        )


class TotalItemAhTests(unittest.TestCase):

    def test_empty_returns_zero(self) -> None:
        self.assertEqual(total_item_ability_haste([]), 0.0)

    def test_single_known_item(self) -> None:
        # Frozen Heart alone = 20 AH.
        self.assertEqual(total_item_ability_haste(["3110"]), 20.0)

    def test_multi_item_build(self) -> None:
        # Cosmic Drive (25) + Frozen Heart (20) + Sorc Shoes (0) = 45.
        self.assertEqual(
            total_item_ability_haste(["4629", "3110", "3020"]), 45.0,
        )

    def test_unknown_item_contributes_zero(self) -> None:
        # An item not in the registry (e.g. a ward or potion) silently
        # contributes 0. Frozen Heart + ward = 20.
        self.assertEqual(total_item_ability_haste(["3110", "2055"]), 20.0)

    def test_int_ids_accepted(self) -> None:
        # Engine sometimes passes int ids; the lookup string-coerces.
        self.assertEqual(total_item_ability_haste([3110, 4629]), 45.0)

    def test_duplicate_ids_stack(self) -> None:
        # 2 Cosmic Drives = 50 AH (build planner may reject this but the
        # summer is honest about its input).
        self.assertEqual(total_item_ability_haste(["4629", "4629"]), 50.0)

    def test_full_typical_sr_caster_build(self) -> None:
        # Sorc Shoes (0) + Cosmic Drive (25) + Frozen Heart (20) +
        # Nashor's Tooth (15) + Lich Bane (10) + Zhonya's (0) = 70 AH.
        build = ["3020", "4629", "3110", "3115", "3100", "3157"]
        self.assertEqual(total_item_ability_haste(build), 70.0)

    def test_single_item_lookup_helper(self) -> None:
        # The convenience wrapper for callers with a single id.
        self.assertEqual(item_ability_haste("3110"), 20.0)
        self.assertEqual(item_ability_haste(3110), 20.0)
        self.assertEqual(item_ability_haste("99999"), 0.0)  # unknown


class EndToEndSrTests(unittest.TestCase):
    """SR mode: per-spell cooldown reflects build's total item AH."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _spell(self, champion, key, level, items, mode="SR"):
        out = compute_ability_dps(
            self.snap, champion, level=level, item_ids=items, mode=mode,
        )
        return next((s for s in out.per_spell if s.key == key), None)

    def test_veigar_q_zero_ah_baseline(self) -> None:
        # Empty build: base_ah=0, total_ah=0, cd=base_cd identity.
        s = self._spell("Veigar", "Q", level=11, items=[])
        self.assertIsNotNone(s)
        self.assertAlmostEqual(s.total_ability_haste, 0.0)
        self.assertAlmostEqual(s.cooldown, s.base_cooldown, places=4)

    def test_veigar_q_with_frozen_heart_alone(self) -> None:
        # Frozen Heart = 20 AH. Veigar Q base cd @ lvl 11 rank 4 = 4.0.
        # Eff cd = 4.0 / 1.20 = 3.3333...
        s = self._spell("Veigar", "Q", level=11, items=["3110"])
        self.assertIsNotNone(s)
        self.assertAlmostEqual(s.total_ability_haste, 20.0)
        self.assertAlmostEqual(s.cooldown, s.base_cooldown / 1.20, places=4)

    def test_veigar_q_with_cosmic_plus_frozen(self) -> None:
        # Cosmic Drive (25) + Frozen Heart (20) = 45 AH.
        s = self._spell("Veigar", "Q", level=11, items=["4629", "3110"])
        self.assertIsNotNone(s)
        self.assertAlmostEqual(s.total_ability_haste, 45.0)
        self.assertAlmostEqual(s.cooldown, s.base_cooldown / 1.45, places=4)

    def test_unknown_items_contribute_zero(self) -> None:
        # Sight Ward (2055) + Health Potion (2003) = 0 AH.
        s = self._spell("Veigar", "Q", level=11, items=["2055", "2003"])
        self.assertIsNotNone(s)
        self.assertAlmostEqual(s.total_ability_haste, 0.0)
        self.assertAlmostEqual(s.cooldown, s.base_cooldown, places=4)


class ArAndItemStackTests(unittest.TestCase):
    """ARAM mode: aram_ability_haste delta + item AH stack additively."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _spell(self, champion, key, level, items, mode):
        out = compute_ability_dps(
            self.snap, champion, level=level, item_ids=items, mode=mode,
        )
        return next((s for s in out.per_spell if s.key == key), None)

    def test_soraka_aram_q_with_item_haste_stacks(self) -> None:
        # Soraka aramAbilityHaste = +10. Add Frozen Heart (20) -> total 30.
        # Q rank 2 @ lvl 5 base = 6.0; eff = 6.0 / 1.30.
        s = self._spell("Soraka", "Q", level=5, items=["3110"], mode="ARAM")
        self.assertIsNotNone(s)
        self.assertAlmostEqual(s.total_ability_haste, 30.0, places=4)
        self.assertAlmostEqual(s.cooldown, 6.0 / 1.30, places=4)

    def test_seraphine_aram_q_negative_aram_minus_item(self) -> None:
        # Seraphine aramAbilityHaste = -20. Add Cosmic Drive (25) -> total +5.
        # Compression resumes despite the harsh ARAM penalty.
        s = self._spell("Seraphine", "Q", level=1, items=["4629"], mode="ARAM")
        self.assertIsNotNone(s)
        self.assertAlmostEqual(s.total_ability_haste, 5.0, places=4)
        self.assertAlmostEqual(s.cooldown, s.base_cooldown / 1.05, places=4)

    def test_sr_mode_strips_aram_delta_even_with_items(self) -> None:
        # Soraka in SR sees ONLY item AH (no aram delta). 20 from FH.
        s = self._spell("Soraka", "Q", level=5, items=["3110"], mode="SR")
        self.assertIsNotNone(s)
        self.assertAlmostEqual(s.total_ability_haste, 20.0, places=4)
        self.assertAlmostEqual(s.cooldown, 6.0 / 1.20, places=4)


if __name__ == "__main__":
    unittest.main()

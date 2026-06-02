"""Item 269 L1 - build-order/item-cost loaders for the recall callout.

Hermetic (reads the committed DS data files; no network). Verifies the next-
item resolver the recall callout depends on, against the live build-order
tables + item catalog.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import dashboard._deterministic_coaching as dc  # noqa: E402


class ItemCostLoaderTests(unittest.TestCase):
    def test_known_items_have_costs(self):
        costs = dc._load_item_costs()
        self.assertIn("3078", costs)  # Trinity Force
        name, total = costs["3078"]
        self.assertEqual(name, "Trinity Force")
        self.assertGreater(total, 0)


class BuildOrderLoaderTests(unittest.TestCase):
    def test_sr_orders_load_and_have_buckets(self):
        orders = dc._load_build_orders("sr")
        self.assertTrue(orders, "sr build orders empty")
        # Aatrox is a stable roster member with a full build order.
        self.assertIn("Aatrox", orders)
        self.assertIsInstance(orders["Aatrox"].get("balanced"), list)

    def test_unknown_mode_is_fail_soft(self):
        self.assertEqual(dc._load_build_orders("nonsense_mode_zzz"), {})


class NextBuildItemTests(unittest.TestCase):
    def test_first_item_resolves_name_and_cost(self):
        res = dc._next_build_item("Aatrox", "sr", 0)
        self.assertIsNotNone(res)
        name, cost = res
        self.assertTrue(name)
        self.assertGreater(cost, 0)

    def test_owned_count_past_build_returns_none(self):
        self.assertIsNone(dc._next_build_item("Aatrox", "sr", 99))

    def test_unknown_champ_returns_none(self):
        self.assertIsNone(dc._next_build_item("NotAChampion", "sr", 0))

    def test_non_str_champ_returns_none(self):
        self.assertIsNone(dc._next_build_item(None, "sr", 0))


if __name__ == "__main__":
    unittest.main()

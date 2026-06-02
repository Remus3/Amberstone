"""Item 269 L1 - recall-affordability callout (correct-by-construction).

The event_callouts docstring promised ``kind: recall`` but never produced it.
This covers the pure recall_callout fn + its threading through next_callouts,
and pins that omitting the new kwargs is byte-identical to the prior behavior.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.event_callouts import next_callouts, recall_callout  # noqa: E402


class RecallCalloutTests(unittest.TestCase):
    def test_affordable_emits_active_recall(self):
        c = recall_callout(3500, "Blade of The Ruined King", 3200)
        self.assertIsNotNone(c)
        self.assertEqual(c["kind"], "recall")
        self.assertEqual(c["eta_s"], 0.0)
        self.assertIn("Blade of The Ruined King", c["line"])
        self.assertTrue(c["line"].startswith("Back now"))

    def test_exact_threshold_is_affordable(self):
        self.assertIsNotNone(recall_callout(3200, "Trinity Force", 3200))

    def test_under_cost_returns_none(self):
        self.assertIsNone(recall_callout(3199, "Trinity Force", 3200))

    def test_fail_soft_inputs(self):
        self.assertIsNone(recall_callout(None, "X", 1000))
        self.assertIsNone(recall_callout(5000, None, 1000))
        self.assertIsNone(recall_callout(5000, "", 1000))
        self.assertIsNone(recall_callout(5000, "X", 0))
        self.assertIsNone(recall_callout(5000, "X", -10))
        self.assertIsNone(recall_callout("lots", "X", 1000))
        self.assertIsNone(recall_callout(5000, "X", "free"))

    def test_bool_is_rejected_not_treated_as_int(self):
        # bool is an int subclass - True must not pass as gold/cost.
        self.assertIsNone(recall_callout(True, "X", 1))
        self.assertIsNone(recall_callout(5000, "X", True))


class NextCalloutsThreadingTests(unittest.TestCase):
    def test_recall_surfaces_active_first_when_affordable(self):
        out = next_callouts(
            "sr", 200.0, 3, 0, max_n=5,
            gold=4000, next_item_name="Kraken Slayer", next_item_cost=3000,
        )
        recalls = [c for c in out if c.get("kind") == "recall"]
        self.assertEqual(len(recalls), 1)
        # eta_s 0.0 sorts into the active bucket, so it leads.
        self.assertEqual(out[0]["kind"], "recall")

    def test_no_recall_when_unaffordable(self):
        out = next_callouts(
            "sr", 200.0, 3, 0, max_n=5,
            gold=100, next_item_name="Kraken Slayer", next_item_cost=3000,
        )
        self.assertFalse([c for c in out if c.get("kind") == "recall"])

    def test_omitting_recall_kwargs_is_byte_identical(self):
        # Back-compat: the prior call shape must be unchanged.
        base = next_callouts("sr", 200.0, 3, 0, max_n=5)
        with_none = next_callouts(
            "sr", 200.0, 3, 0, max_n=5,
            gold=None, next_item_name=None, next_item_cost=None,
        )
        self.assertEqual(base, with_none)
        self.assertFalse([c for c in base if c.get("kind") == "recall"])


if __name__ == "__main__":
    unittest.main()

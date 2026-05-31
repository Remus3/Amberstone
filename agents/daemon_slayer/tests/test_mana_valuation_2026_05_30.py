"""2026-05-30 (DS scraper-review slice) - bounded mana-valuation knob tests.

Pins ``rank_items(mana_value_per_point=...)``. The auto-attack DPS scorer
values flat mana at ~0, so a mana-dependent caster sees early mana items
(Tear, Lost Chapter, Blackfire/Rod-of-Ages line) rank below burn/AP items.
The knob adds ``mana_value_per_point * mana_gained`` to each candidate's
score. Default (None) MUST stay byte-identical to pre-1.64.0.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import rank_items

_SNAP = DataSnapshot.load()


class ManaKnobByteIdenticalWhenUnsetTests(unittest.TestCase):
    """None / non-positive must not perturb the existing ranking."""

    def test_default_fields_zero(self):
        r = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=20)
        self.assertTrue(all(x.mana_adjusted_score == 0.0 for x in r.ranked))
        self.assertTrue(all(x.mana_gained == 0.0 for x in r.ranked))

    def test_none_matches_explicit_default_order(self):
        a = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=20)
        b = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=20,
                       mana_value_per_point=None)
        self.assertEqual(
            [x.item_id for x in a.ranked], [x.item_id for x in b.ranked],
        )

    def test_zero_value_is_default_path(self):
        a = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=20)
        b = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=20,
                       mana_value_per_point=0.0)
        self.assertEqual(
            [x.item_id for x in a.ranked], [x.item_id for x in b.ranked],
        )
        self.assertTrue(all(x.mana_adjusted_score == 0.0 for x in b.ranked))

    def test_negative_value_is_default_path(self):
        a = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=20)
        b = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=20,
                       mana_value_per_point=-1.0)
        self.assertEqual(
            [x.item_id for x in a.ranked], [x.item_id for x in b.ranked],
        )


class ManaKnobEngagedTests(unittest.TestCase):
    def test_mana_gained_populated_for_mana_items(self):
        r = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=40,
                       mana_value_per_point=0.05)
        # At least one ranked item must report positive mana gained.
        self.assertTrue(any(x.mana_gained > 0.0 for x in r.ranked))

    def test_mana_adjusted_is_delta_plus_value_times_mana(self):
        v = 0.05
        r = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=40,
                       mana_value_per_point=v)
        for x in r.ranked:
            self.assertAlmostEqual(
                x.mana_adjusted_score,
                x.delta_dps + v * x.mana_gained,
                places=4,
            )

    def test_sorted_by_mana_adjusted_desc(self):
        r = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=20,
                       mana_value_per_point=0.05)
        scores = [x.mana_adjusted_score for x in r.ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_high_value_promotes_a_mana_item(self):
        # A large mana value must lift a high-mana item above where it sits
        # on the pure-DPS board.
        base = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=60)
        big = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=60,
                         mana_value_per_point=0.5)
        # Find the item with the most mana gained in the knob run.
        mana_item = max(big.ranked, key=lambda x: x.mana_gained)
        self.assertGreater(mana_item.mana_gained, 0.0)
        base_rank = next(
            (i for i, x in enumerate(base.ranked) if x.item_id == mana_item.item_id),
            len(base.ranked),
        )
        big_rank = next(
            i for i, x in enumerate(big.ranked) if x.item_id == mana_item.item_id
        )
        self.assertLess(big_rank, base_rank)

    def test_notes_mention_knob(self):
        r = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=5,
                       mana_value_per_point=0.05)
        self.assertTrue(any("mana_value_per_point" in n for n in r.notes))


class ManaKnobInteractionTests(unittest.TestCase):
    def test_efficiency_sort_unaffected(self):
        # Efficiency owns the sort key; the mana knob must not reorder it.
        a = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=20, sort_by="efficiency")
        b = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=20, sort_by="efficiency",
                       mana_value_per_point=0.5)
        self.assertEqual(
            [x.item_id for x in a.ranked], [x.item_id for x in b.ranked],
        )

    def test_to_dict_carries_new_fields(self):
        r = rank_items(_SNAP, "Ziggs", 11, mode="SR", top_n=3,
                       mana_value_per_point=0.05)
        d = r.ranked[0].to_dict()
        self.assertIn("mana_adjusted_score", d)
        self.assertIn("mana_gained", d)


class AsciiHygieneTests(unittest.TestCase):
    def test_test_file_is_ascii(self):
        p = Path(__file__)
        data = p.read_bytes()
        non_ascii = [(i, b) for i, b in enumerate(data) if b > 0x7F]
        self.assertEqual(non_ascii, [], f"non-ASCII: {non_ascii[:5]}")


if __name__ == "__main__":
    unittest.main()

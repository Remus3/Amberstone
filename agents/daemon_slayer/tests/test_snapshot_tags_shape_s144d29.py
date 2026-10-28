"""RM-1049: every snapshot item and champion record carries ``tags`` as a list of str.

The scorers read the DDragon ``tags`` field straight off the snapshot record
with ``tuple(rec.get("tags") or ())`` (burst, ehp, hps, hybrid, onhit_dps,
rank, _rank_mage row builders), ``set(...)`` (kit_conversion) or a bare ``in``
test (beam boots / consumable, rank's Marksman gate). Those reads are only
right while the field is a JSON list of strings:

- a str ``"SpellDamage"`` would split into characters under ``tuple()`` or
  ``set()``, so onhit_dps ``_coherence_key``'s ``"SpellDamage" in tags`` test
  silently goes False and the AP coherence penalty lands on a real AP item,
  and kit_conversion's ``"OnHit" in tags`` goes False the same way;
- the same str under a bare ``in`` is a SUBSTRING test, so ``"Boots"`` or
  ``"Marksman"`` would match any tag text containing it;
- a non-str element in the list never matches a tag literal.

Measured 2026-10-28 on snapshot 16.21.1: 699/699 items and 173/173 champions
carry a list of str, so the reads are correct today and the input is data the
extractor controls. This guard pins that shape so a re-extract or a schema
change that breaks it fails here, not as a quiet ranking shift. It also pins
that each tag literal a consumer tests for is present on at least one record,
so a snapshot with emptied tags cannot pass vacuously.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot

# Item tag literals the scorers test for: onhit_dps _coherence_key,
# beam _BOOTS_TAG / _CONSUMABLE_TAG, kit_conversion's OnHit requirement.
_ITEM_CONSUMER_TAGS = ("SpellDamage", "Boots", "Consumable", "OnHit")
# Champion tag literal rank's ranged-marksman gate tests for.
_CHAMPION_CONSUMER_TAGS = ("Marksman",)


def _tag_shape_problems(records: dict) -> list[tuple[str, str]]:
    """(record id, repr of its tags) for every record whose tags is not a list of str."""
    problems: list[tuple[str, str]] = []
    for rec_id, rec in records.items():
        if not isinstance(rec, dict) or "tags" not in rec:
            problems.append((str(rec_id), "<absent>"))
            continue
        tags = rec["tags"]
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            problems.append((str(rec_id), repr(tags)))
    return problems


class TagShapePredicateTests(unittest.TestCase):
    """Negative controls: the predicate flags every bad shape and passes the good one."""

    def test_list_of_str_passes(self) -> None:
        self.assertEqual(_tag_shape_problems({"1": {"tags": ["Boots", "SpellDamage"]}}), [])

    def test_empty_list_passes(self) -> None:
        self.assertEqual(_tag_shape_problems({"1": {"tags": []}}), [])

    def test_bad_shapes_are_flagged(self) -> None:
        bad = {
            "str": {"tags": "SpellDamage"},
            "none": {"tags": None},
            "int": {"tags": 3},
            "tuple": {"tags": ("Boots",)},
            "dict": {"tags": {"Boots": True}},
            "mixed": {"tags": ["Boots", 7]},
            "absent": {"name": "x"},
            "not_a_dict": ["Boots"],
        }
        flagged = {rec_id for rec_id, _ in _tag_shape_problems(bad)}
        self.assertEqual(flagged, set(bad))


class SnapshotTagShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_snapshot_is_populated(self) -> None:
        self.assertGreater(len(self.snap.items), 0)
        self.assertGreater(len(self.snap.champions), 0)

    def test_every_item_tags_is_list_of_str(self) -> None:
        self.assertEqual(_tag_shape_problems(self.snap.items), [])

    def test_every_champion_tags_is_list_of_str(self) -> None:
        self.assertEqual(_tag_shape_problems(self.snap.champions), [])

    def test_item_consumer_tags_present(self) -> None:
        for tag in _ITEM_CONSUMER_TAGS:
            with self.subTest(tag=tag):
                hits = [i for i, r in self.snap.items.items() if tag in (r.get("tags") or [])]
                self.assertTrue(hits, f"no item carries the {tag!r} tag a scorer tests for")

    def test_champion_consumer_tags_present(self) -> None:
        for tag in _CHAMPION_CONSUMER_TAGS:
            with self.subTest(tag=tag):
                hits = [c for c, r in self.snap.champions.items() if tag in (r.get("tags") or [])]
                self.assertTrue(hits, f"no champion carries the {tag!r} tag a scorer tests for")


if __name__ == "__main__":
    unittest.main()

"""Phase 1 (item 1 rune-follows-build): the rune-page model + exact-match dedup.

coaches/rune_pages.py resolves a build's (keystone, primary, secondary[, minors])
to the 9-element perk_ids via lcu_rune_writer.build_perk_ids and mints a stable
pageId = the dedup key: two builds that resolve identically collapse to one page;
a keystone/tree difference mints a distinct page. enumerate_pages(champ, mode)
walks list_variants + build_paths + each variant's auto (recommended) page,
dedups, and maps each buildId -> its recommendedPageId. NON-frozen: it only
IMPORTS build_perk_ids (frozen). See docs/specs/2026-07-11-overlay-item1-...IMPL.md.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from coaches import rune_pages

# Valid keystone/tree names build_perk_ids accepts (lcu/lcu_rune_writer.py:29-51).
_LT = ("Lethal Tempo", "Precision", "Domination")
_PTA = ("Press the Attack", "Precision", "Domination")
_ELEC = ("Electrocute", "Domination", "Precision")


class PageId(unittest.TestCase):
    def test_stable(self):
        ids = [1, 2, 3, 4, 5, 6, 7, 8, 9]
        self.assertEqual(rune_pages.page_id(ids), rune_pages.page_id(list(ids)))

    def test_distinct(self):
        a = rune_pages.page_id([1, 2, 3, 4, 5, 6, 7, 8, 9])
        b = rune_pages.page_id([1, 2, 3, 4, 5, 6, 7, 8, 10])
        self.assertNotEqual(a, b)


class ResolvePage(unittest.TestCase):
    def test_valid_returns_page(self):
        pg = rune_pages.resolve_page(*_LT)
        self.assertIsNotNone(pg)
        self.assertEqual(pg["keystone"], "Lethal Tempo")
        self.assertEqual(len(pg["perk_ids"]), 9)
        self.assertTrue(pg["pageId"])

    def test_same_inputs_dedup_to_same_page(self):
        self.assertEqual(rune_pages.resolve_page(*_LT)["pageId"],
                         rune_pages.resolve_page(*_LT)["pageId"])

    def test_distinct_keystone_distinct_page(self):
        self.assertNotEqual(rune_pages.resolve_page(*_LT)["pageId"],
                            rune_pages.resolve_page(*_PTA)["pageId"])

    def test_unknown_keystone_is_none(self):
        self.assertIsNone(
            rune_pages.resolve_page("Not A Keystone", "Precision", "Domination"))


class EnumeratePages(unittest.TestCase):
    def _variants(self):
        # Realistic list_variants rows (loadout_resolver.py:219-235 shape).
        return [
            {"key": "crit", "keystone": "Lethal Tempo", "primary": "Precision",
             "secondary": "Domination", "auto_keystone": "Lethal Tempo",
             "auto_primary": "Precision", "auto_secondary": "Domination",
             "build_paths": []},
            {"key": "onhit", "keystone": "Press the Attack", "primary": "Precision",
             "secondary": "Domination", "auto_keystone": "Press the Attack",
             "auto_primary": "Precision", "auto_secondary": "Domination",
             "build_paths": [
                 {"key": "burst", "keystone": "Electrocute",
                  "primary": "Domination", "secondary": "Precision"}]},
        ]

    def test_dedups_pages_and_maps_builds(self):
        with mock.patch.object(rune_pages, "list_variants",
                               return_value=self._variants()):
            out = rune_pages.enumerate_pages("Jinx", "SR")
        ids = {p["pageId"] for p in out["pages"]}
        self.assertEqual(len(ids), 3)  # Lethal Tempo / Press the Attack / Electrocute
        builds = {b["buildId"]: b["recommendedPageId"] for b in out["builds"]}
        self.assertIn("crit", builds)
        self.assertIn("onhit", builds)
        self.assertIn("onhit:burst", builds)
        for pid in builds.values():
            self.assertIn(pid, ids)

    def test_identical_variants_collapse_to_one_page(self):
        row = {"keystone": "Lethal Tempo", "primary": "Precision",
               "secondary": "Domination", "auto_keystone": "Lethal Tempo",
               "auto_primary": "Precision", "auto_secondary": "Domination",
               "build_paths": []}
        dup = [{**row, "key": "a"}, {**row, "key": "b"}]
        with mock.patch.object(rune_pages, "list_variants", return_value=dup):
            out = rune_pages.enumerate_pages("Jinx", "SR")
        self.assertEqual(len(out["pages"]), 1)  # both variants -> one deduped page
        self.assertEqual(out["builds"][0]["recommendedPageId"],
                         out["builds"][1]["recommendedPageId"])


class Ascii(unittest.TestCase):
    def test_ascii(self):
        for p in (Path(rune_pages.__file__), Path(__file__)):
            raw = p.read_bytes()
            self.assertFalse([b for b in raw if b > 0x7F], f"non-ASCII in {p.name}")


if __name__ == "__main__":
    unittest.main()

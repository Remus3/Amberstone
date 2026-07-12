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
                               return_value=self._variants()), \
             mock.patch.object(rune_pages, "_user_builds_for", return_value=[]):
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
        with mock.patch.object(rune_pages, "list_variants", return_value=dup), \
             mock.patch.object(rune_pages, "_user_builds_for", return_value=[]):
            out = rune_pages.enumerate_pages("Jinx", "SR")
        self.assertEqual(len(out["pages"]), 1)  # both variants -> one deduped page
        self.assertEqual(out["builds"][0]["recommendedPageId"],
                         out["builds"][1]["recommendedPageId"])


class UserBuildFold(unittest.TestCase):
    """Phase 4: operator user-curated builds (coaches/sr_user_builds) fold into
    the same rune-page model, keyed "userbuild_<id>" and exact-match deduped by
    resolved perk_ids. Mirrors routes_loadout._serve_loadout_list_post's
    userbuild_ namespacing. list_for is patched in every test so the model stays
    hermetic (the real store is gitignored data/daemon_slayer/user_builds.json)."""

    _CRIT = {"key": "crit", "keystone": "Lethal Tempo", "primary": "Precision",
             "secondary": "Domination", "auto_keystone": "Lethal Tempo",
             "auto_primary": "Precision", "auto_secondary": "Domination",
             "build_paths": []}

    def _ub(self, uid, keystone, primary, secondary,
            minor_primary=None, minor_secondary=None):
        return {"id": uid, "runes": {
            "keystone": keystone, "primary": primary, "secondary": secondary,
            "minor_primary": minor_primary or [],
            "minor_secondary": minor_secondary or []}}

    def test_user_build_appears_as_selectable_page(self):
        ubs = [self._ub("abc123", "Electrocute", "Domination", "Precision")]
        with mock.patch.object(rune_pages, "list_variants",
                               return_value=[self._CRIT]), \
             mock.patch.object(rune_pages, "_user_builds_for", return_value=ubs):
            out = rune_pages.enumerate_pages("Jinx", "SR")
        builds = {b["buildId"]: b["recommendedPageId"] for b in out["builds"]}
        self.assertIn("userbuild_abc123", builds)
        ids = {p["pageId"] for p in out["pages"]}
        self.assertIn(builds["userbuild_abc123"], ids)
        # Lethal Tempo variant page + distinct Electrocute user page.
        self.assertEqual(len(ids), 2)

    def test_user_build_dedups_against_identical_variant(self):
        # A user build resolving identically to a generic variant collapses onto
        # that variant's page (exact-match dedup by perk_ids), minting no new page.
        ubs = [self._ub("dup1", "Lethal Tempo", "Precision", "Domination")]
        with mock.patch.object(rune_pages, "list_variants",
                               return_value=[self._CRIT]), \
             mock.patch.object(rune_pages, "_user_builds_for", return_value=ubs):
            out = rune_pages.enumerate_pages("Jinx", "SR")
        ids = {p["pageId"] for p in out["pages"]}
        self.assertEqual(len(ids), 1)
        builds = {b["buildId"]: b["recommendedPageId"] for b in out["builds"]}
        self.assertEqual(builds["userbuild_dup1"], builds["crit"])

    def test_user_build_unknown_keystone_maps_to_none(self):
        ubs = [self._ub("bad1", "Not A Keystone", "Precision", "Domination")]
        with mock.patch.object(rune_pages, "list_variants", return_value=[]), \
             mock.patch.object(rune_pages, "_user_builds_for", return_value=ubs):
            out = rune_pages.enumerate_pages("Jinx", "SR")
        builds = {b["buildId"]: b["recommendedPageId"] for b in out["builds"]}
        self.assertIsNone(builds["userbuild_bad1"])

    def test_user_build_subrune_delta_mints_distinct_page(self):
        # Two user builds identical except for minor primary runes resolve to
        # different perk_ids -> two distinct pages (1-subrune delta = new page).
        # Patch _perk_by_name so the override resolves without depending on the
        # ddragon_runes.json data file.
        fake = {"A": 101, "B": 102, "C": 103, "D": 104, "E": 105, "F": 106}
        ubs = [
            self._ub("u1", "Lethal Tempo", "Precision", "Domination",
                     minor_primary=["A", "B", "C"]),
            self._ub("u2", "Lethal Tempo", "Precision", "Domination",
                     minor_primary=["D", "E", "F"]),
        ]
        with mock.patch.object(rune_pages, "list_variants", return_value=[]), \
             mock.patch.object(rune_pages, "_user_builds_for", return_value=ubs), \
             mock.patch("lcu.lcu_rune_writer._perk_by_name", return_value=fake):
            out = rune_pages.enumerate_pages("Jinx", "SR")
        builds = {b["buildId"]: b["recommendedPageId"] for b in out["builds"]}
        self.assertNotEqual(builds["userbuild_u1"], builds["userbuild_u2"])
        self.assertEqual(len({p["pageId"] for p in out["pages"]}), 2)

    def test_user_build_fold_failure_isolated(self):
        # Operator-additive invariant: a broken user-build store never blocks the
        # generic build model - the base variants still enumerate.
        def _boom(champ):
            raise RuntimeError("store broken")
        with mock.patch.object(rune_pages, "list_variants",
                               return_value=[self._CRIT]), \
             mock.patch.object(rune_pages, "_user_builds_for", side_effect=_boom):
            out = rune_pages.enumerate_pages("Jinx", "SR")
        buildids = {b["buildId"] for b in out["builds"]}
        self.assertIn("crit", buildids)
        self.assertFalse(any(b.startswith("userbuild_") for b in buildids))


class Ascii(unittest.TestCase):
    def test_ascii(self):
        for p in (Path(rune_pages.__file__), Path(__file__)):
            raw = p.read_bytes()
            self.assertFalse([b for b in raw if b > 0x7F], f"non-ASCII in {p.name}")


if __name__ == "__main__":
    unittest.main()

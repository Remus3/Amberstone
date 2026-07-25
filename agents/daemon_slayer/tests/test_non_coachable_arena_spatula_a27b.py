"""RM-04 A-27b: the item-213 non-coachable deny leaked its cross-map twins.

Item 213 / item 243 denied Golden Spatula by the ONE id it saw in a live ARAM
game (994403, maps['12']). DDragon 16.14.1 actually ships FOUR Spatula rows and
TWO Talisman of Ascension rows in separate map-mirror id namespaces, and the
deny-by-id set caught exactly one of each. The Arena mirrors 224403 (The Golden
Spatula, maps['30']) and 443064 (Talisman Of Ascension, maps['30']) are
purchasable AND reach the ARENA candidate pool, so the identical pollution
recurred one map over: 224403 sits at slot index 2 of ad_heavy / ap_heavy /
balanced for 82 of 173 champions in build_orders_arena.json.

This module pins the SIBLING-COMPLETE deny (the whole lesson of item 213 - a
narrow single-id fix recurred), by stable item id, for every purchasable twin.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import (
    MODE_MAP_ID,
    _NON_COACHABLE_ITEM_IDS,
    _filter_candidates,
    _is_purchasable,
    rank_items,
)

# ---- Golden Spatula family (DDragon 16.14.1, verified by id + maps + gold) ----
_SPATULA_ARAM = "994403"      # maps['12'], 2500g, purchasable - denied since item 243
_SPATULA_ARENA = "224403"     # maps['30'], 2500g, purchasable - THE RECURRENCE
_SPATULA_NEXUS_BLITZ = "4403"  # maps['21'], 7187g, purchasable - no wired mode today
_SPATULA_SR = "664403"        # maps['11'], purchasable=False - self-excluded

# ---- Talisman of Ascension family ----
_TALISMAN_SR = "663064"       # maps['11'], 900g, purchasable - denied since item 243
_TALISMAN_ARENA = "443064"    # maps['30'], 2750g, purchasable - THE RECURRENCE

# Every purchasable Spatula id must be denied. 664403 is excluded by
# purchasable=False and is deliberately NOT in this tuple (asserted separately).
_PURCHASABLE_SPATULAS = (_SPATULA_ARAM, _SPATULA_ARENA, _SPATULA_NEXUS_BLITZ)
_ALL_MUST_DENY = _PURCHASABLE_SPATULAS + (_TALISMAN_SR, _TALISMAN_ARENA)

# A real Arena prismatic that MUST survive the deny (guards over-denying).
_ARENA_CONTROL_ITEM = "223084"  # Heartsteel Arena mirror, in every affected order


class ArenaSpatulaDenySetTests(unittest.TestCase):
    """The deny SET itself - pure membership, no snapshot needed."""

    def test_every_purchasable_spatula_is_denied(self) -> None:
        for iid in _PURCHASABLE_SPATULAS:
            with self.subTest(item_id=iid):
                self.assertIn(
                    iid, _NON_COACHABLE_ITEM_IDS,
                    f"purchasable Golden Spatula {iid} is not denied - "
                    "the item-213 pollution class can recur on its map",
                )

    def test_both_talismans_of_ascension_are_denied(self) -> None:
        for iid in (_TALISMAN_SR, _TALISMAN_ARENA):
            with self.subTest(item_id=iid):
                self.assertIn(iid, _NON_COACHABLE_ITEM_IDS)


class ArenaSpatulaDataShapeTests(unittest.TestCase):
    """Pin the DDragon facts the deny is built on, so a patch re-extract that
    changes them fails loudly instead of silently un-protecting a map."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_denied_twins_are_purchasable_so_the_deny_is_load_bearing(self) -> None:
        # If any of these went purchasable=False upstream the deny would be
        # redundant. They are all True today, so ONLY the deny keeps them out.
        for iid in _ALL_MUST_DENY:
            with self.subTest(item_id=iid):
                rec = self.snap.items.get(iid)
                self.assertIsNotNone(rec, f"{iid} missing from snapshot")
                self.assertTrue(
                    _is_purchasable(rec),
                    f"{iid} is no longer purchasable - re-check the deny rationale",
                )

    def test_sr_spatula_is_self_excluded_by_purchasable_false(self) -> None:
        # 664403 needs no deny entry: DDragon marks it unbuyable. Documented as a
        # test so a future patch flipping it to purchasable=True fails here.
        rec = self.snap.items.get(_SPATULA_SR)
        self.assertIsNotNone(rec, "SR Golden Spatula 664403 missing from snapshot")
        self.assertFalse(
            _is_purchasable(rec),
            "664403 became purchasable - it now needs a _NON_COACHABLE_ITEM_IDS entry",
        )

    def test_nexus_blitz_spatula_has_no_wired_mode(self) -> None:
        # 4403 is maps['21'] (Nexus Blitz). No MODE_MAP_ID entry maps to '21', so
        # it is unreachable today; it is denied pre-emptively because the deny is
        # by stable id and a future mode wiring must not resurrect the pollution.
        self.assertNotIn("21", set(MODE_MAP_ID.values()))


class ArenaSpatulaPoolTests(unittest.TestCase):
    """The candidate pool - the surface item 213 actually missed."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _pool(self, mode: str) -> set[str]:
        return {iid for iid, _ in _filter_candidates(
            self.snap, mode, set(), None, False, None)}

    def test_no_twin_survives_into_the_arena_pool(self) -> None:
        pool = self._pool("ARENA")
        for iid in _ALL_MUST_DENY:
            with self.subTest(item_id=iid):
                self.assertNotIn(iid, pool, f"{iid} leaked into the ARENA pool")

    def test_no_twin_survives_into_any_wired_mode_pool(self) -> None:
        for mode in sorted(MODE_MAP_ID):
            pool = self._pool(mode)
            for iid in _ALL_MUST_DENY:
                with self.subTest(mode=mode, item_id=iid):
                    self.assertNotIn(iid, pool, f"{iid} leaked into the {mode} pool")

    def test_arena_pool_is_not_gutted(self) -> None:
        pool = self._pool("ARENA")
        self.assertGreater(len(pool), 150, "ARENA pool unexpectedly tiny")
        self.assertIn(_ARENA_CONTROL_ITEM, pool,
                      "real Arena prismatic dropped - the deny is over-broad")


class ArenaSpatulaRankTests(unittest.TestCase):
    """End-to-end: the live ranking route, on champions the pollution hit."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_rank_items_arena_excludes_every_twin(self) -> None:
        # Aatrox / Caitlyn / Ashe all carry 224403 at slot index 2 of all three
        # branches in build_orders_arena.json (82 of 173 champions do).
        for champ in ("Aatrox", "Caitlyn", "Ashe"):
            res = rank_items(self.snap, champ, 18, mode="ARENA", top_n=40)
            ids = {r.item_id for r in res.ranked}
            for iid in _ALL_MUST_DENY:
                with self.subTest(champion=champ, item_id=iid):
                    self.assertNotIn(
                        iid, ids, f"{iid} ranked into live ARENA {champ} picks")


class ModuleHygieneTests(unittest.TestCase):
    def test_module_file_is_ascii(self) -> None:
        from pathlib import Path
        raw = Path(__file__).read_bytes()
        bad = [(i, b) for i, b in enumerate(raw) if b > 127]
        self.assertFalse(bad, f"non-ASCII at {bad[:3]}")


if __name__ == "__main__":
    unittest.main()

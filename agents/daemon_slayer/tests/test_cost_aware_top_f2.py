"""F2 cost-aware top gate (DS Tier-2 cross-eval nomination F2, default-OFF).

``rank.py`` ranks by ``sort_by="delta"`` (absolute DPS/EHP gained, which scales
with item cost), so the 6000g Arena-only mega-item Void Immolation (223069)
sat at RANK 1 in every comp cell for the hybrid/bruiser + ehp/tank scorers -
a ranking-surface artifact, not a build-correctness claim.
Evidence: ops/audit/ds_cross_eval/TIER2_REPORT.md (F2).

The ``cost_ceiling`` seam (default None = byte-identical) drops any candidate
whose ``gold.total`` STRICTLY exceeds the ceiling from the shared
``_filter_candidates`` pool, so over-cost items are excluded from the
recommendation surface. Difference-of-differences assertions (membership +
displacement + inclusive boundary), not fragile absolute magnitudes.

2026-07-07: Void Immolation (223069) is now HARD-EXCLUDED from ARAM via
``_ARAM_EXCLUDED_ITEM_IDS`` (DDragon wrongly marks maps.12=true for an
Arena-only prismatic). The cost_ceiling seam still exists as a general
gate; test it with a legitimately-ARAM-legal over-cost control item.

The live default-ON flip is EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import rank_items_by_ehp
from agents.daemon_slayer.hybrid import rank_items_by_hybrid
from agents.daemon_slayer.rank import _filter_candidates, rank_items

VOID_IMMOLATION = "223069"  # 6000g, Arena-only (maps.30=true, maps.12=mislabeled)
INFINITY_EDGE = "3031"     # 3500g, genuine ARAM-legal - control for ceiling tests
TRINITY = "3078"           # 3333g, sub-ceiling control


class TestCostCeilingFilter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _ids(self, **kw):
        cands = _filter_candidates(
            self.snap,
            mode="aram",
            current_ids=set(),
            budget=None,
            include_components=False,
            only_ids=None,
            **kw,
        )
        return {iid for iid, _ in cands}

    def test_void_immolation_is_hard_excluded_from_aram(self):
        # DDragon maps.12=true is an upstream mislabel - this is an Arena-only
        # prismatic mega-item, now hard-excluded via _ARAM_EXCLUDED_ITEM_IDS.
        rec = self.snap.items[VOID_IMMOLATION]
        self.assertEqual(int(rec["gold"]["total"]), 6000)
        self.assertTrue(rec["maps"]["12"])           # DDragon says ARAM (wrong)
        self.assertNotIn(VOID_IMMOLATION, self._ids())  # but we hard-exclude it

    def test_default_off_byte_identical(self):
        # absent param == explicit None
        self.assertEqual(self._ids(), self._ids(cost_ceiling=None))

    def test_void_always_excluded_regardless_of_ceiling(self):
        # Hard-exclude fires before cost_ceiling - VI is absent even with a high
        # ceiling that would theoretically admit it.
        self.assertNotIn(VOID_IMMOLATION, self._ids())
        self.assertNotIn(VOID_IMMOLATION, self._ids(cost_ceiling=6000))
        self.assertNotIn(VOID_IMMOLATION, self._ids(cost_ceiling=9999))

    def test_subceiling_item_retained_both_ways(self):
        self.assertIn(TRINITY, self._ids())
        self.assertIn(TRINITY, self._ids(cost_ceiling=4000))

    def test_ceiling_boundary_is_inclusive(self):
        # strict-greater drop: use Infinity Edge (3500g, genuine ARAM-legal) as the
        # boundary item since Void Immolation is now hard-excluded.
        self.assertIn(INFINITY_EDGE, self._ids(cost_ceiling=3500))
        self.assertNotIn(INFINITY_EDGE, self._ids(cost_ceiling=3499))

    def test_ceiling_only_removes_overcost_items(self):
        off = self._ids()
        on = self._ids(cost_ceiling=4000)
        # ON pool is a strict subset of OFF, and every removed id is over-cost
        self.assertTrue(on <= off)
        for removed in off - on:
            total = int((self.snap.items[removed].get("gold") or {}).get("total", 0) or 0)
            self.assertGreater(total, 4000, removed)


class TestCostCeilingRankers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _hybrid_ids(self, **kw):
        res = rank_items_by_hybrid(self.snap, "Garen", level=13, mode="aram", **kw)
        return [r.item_id for r in res.ranked]

    def _ehp_ids(self, **kw):
        res = rank_items_by_ehp(self.snap, "Malphite", level=13, mode="aram", **kw)
        return [r.item_id for r in res.ranked]

    def _dps_ids(self, **kw):
        res = rank_items(self.snap, "Garen", level=13, mode="aram", **kw)
        return [r.item_id for r in res.ranked]

    def test_void_hard_excluded_from_hybrid_aram(self):
        ids = self._hybrid_ids()
        self.assertNotIn(VOID_IMMOLATION, ids,
                         "Void Immolation is Arena-only, must not appear in ARAM hybrid")

    def test_void_hard_excluded_from_ehp_aram(self):
        ids = self._ehp_ids()
        self.assertNotIn(VOID_IMMOLATION, ids,
                         "Void Immolation is Arena-only, must not appear in ARAM EHP")

    def test_hybrid_cost_ceiling_drops_overcost_items(self):
        # Ceiling 2000: only cheap items survive; pool shrinks vs default.
        off_ids = self._hybrid_ids()
        on_ids = self._hybrid_ids(cost_ceiling=2000)
        self.assertLess(len(on_ids), len(off_ids),
                        "cost_ceiling=2000 should shrink the hybrid pool")
        # Every surviving item costs <= ceiling
        for iid in on_ids:
            total = int((self.snap.items[iid].get("gold") or {}).get("total", 0) or 0)
            self.assertLessEqual(total, 2000,
                                 f"{iid} ({total}g) survived 2000 ceiling")

    def test_hybrid_default_off_byte_identical(self):
        self.assertEqual(self._hybrid_ids(), self._hybrid_ids(cost_ceiling=None))

    def test_ehp_cost_ceiling_drops_overcost_items(self):
        # Ceiling 2000: only cheap items survive; pool shrinks vs default.
        off_ids = self._ehp_ids()
        on_ids = self._ehp_ids(cost_ceiling=2000)
        self.assertLess(len(on_ids), len(off_ids),
                        "cost_ceiling=2000 should shrink the EHP pool")
        # Every surviving item costs <= ceiling
        for iid in on_ids:
            total = int((self.snap.items[iid].get("gold") or {}).get("total", 0) or 0)
            self.assertLessEqual(total, 2000,
                                 f"{iid} ({total}g) survived 2000 ceiling")

    def test_ehp_default_off_byte_identical(self):
        self.assertEqual(self._ehp_ids(), self._ehp_ids(cost_ceiling=None))

    def test_dps_default_off_byte_identical(self):
        self.assertEqual(self._dps_ids(), self._dps_ids(cost_ceiling=None))

    def test_arena_mode_still_admits_void_immolation(self):
        # Arena mode (maps.30=true) should still admit it - the hard-exclude
        # only fires on ARAM (mode.upper() == "ARAM").
        from agents.daemon_slayer.rank import _filter_candidates as fc
        cands = fc(
            self.snap, mode="arena", current_ids=set(), budget=None,
            include_components=False, only_ids=None,
        )
        ids = {iid for iid, _ in cands}
        self.assertIn(VOID_IMMOLATION, ids,
                      "Void Immolation must remain legal in Arena mode")


if __name__ == "__main__":
    unittest.main()

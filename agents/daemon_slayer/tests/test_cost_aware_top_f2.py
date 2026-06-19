"""F2 cost-aware top gate (DS Tier-2 cross-eval nomination F2, default-OFF).

`rank.py` ranks by ``sort_by="delta"`` (absolute DPS/EHP gained, which scales
with item cost), so the 6000g ARAM/Arena mega-item Void Immolation (223069)
sits at RANK 1 in every comp cell for the hybrid/bruiser + ehp/tank scorers -
a ranking-surface artifact, not a build-correctness claim.
Evidence: ops/audit/ds_cross_eval/TIER2_REPORT.md (F2).

The ``cost_ceiling`` seam (default None = byte-identical) drops any candidate
whose ``gold.total`` STRICTLY exceeds the ceiling from the shared
``_filter_candidates`` pool, so the over-cost mega-item is excluded from the
recommendation surface. Difference-of-differences assertions (membership +
displacement + inclusive boundary), not fragile absolute magnitudes.

The live default-ON flip is EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import rank_items_by_ehp
from agents.daemon_slayer.hybrid import rank_items_by_hybrid
from agents.daemon_slayer.rank import _filter_candidates, rank_items

VOID_IMMOLATION = "223069"  # 6000g, ARAM (map 12) + Arena (map 30) legal
TRINITY = "3078"  # 3333g, sub-ceiling control


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

    def test_void_immolation_is_6000g_aram_legal(self):
        rec = self.snap.items[VOID_IMMOLATION]
        self.assertEqual(int(rec["gold"]["total"]), 6000)
        self.assertTrue(rec["maps"]["12"])  # ARAM legal -> in the pool

    def test_default_off_byte_identical(self):
        # absent param == explicit None
        self.assertEqual(self._ids(), self._ids(cost_ceiling=None))

    def test_void_in_pool_when_off(self):
        self.assertIn(VOID_IMMOLATION, self._ids())

    def test_void_dropped_when_ceiling_below_cost(self):
        self.assertNotIn(VOID_IMMOLATION, self._ids(cost_ceiling=4000))

    def test_subceiling_item_retained_both_ways(self):
        self.assertIn(TRINITY, self._ids())
        self.assertIn(TRINITY, self._ids(cost_ceiling=4000))

    def test_ceiling_boundary_is_inclusive(self):
        # strict-greater drop: ceiling == cost keeps the item, ceiling-1 drops it
        self.assertIn(VOID_IMMOLATION, self._ids(cost_ceiling=6000))
        self.assertNotIn(VOID_IMMOLATION, self._ids(cost_ceiling=5999))

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

    def test_hybrid_displaces_void_when_ceiling_on(self):
        off_ids = self._hybrid_ids()
        on_ids = self._hybrid_ids(cost_ceiling=4000)
        self.assertIn(VOID_IMMOLATION, off_ids)
        self.assertNotIn(VOID_IMMOLATION, on_ids)

    def test_hybrid_default_off_byte_identical(self):
        self.assertEqual(self._hybrid_ids(), self._hybrid_ids(cost_ceiling=None))

    def test_ehp_displaces_void_when_ceiling_on(self):
        self.assertIn(VOID_IMMOLATION, self._ehp_ids())
        self.assertNotIn(VOID_IMMOLATION, self._ehp_ids(cost_ceiling=4000))

    def test_ehp_default_off_byte_identical(self):
        self.assertEqual(self._ehp_ids(), self._ehp_ids(cost_ceiling=None))

    def test_dps_default_off_byte_identical(self):
        self.assertEqual(self._dps_ids(), self._dps_ids(cost_ceiling=None))


if __name__ == "__main__":
    unittest.main()

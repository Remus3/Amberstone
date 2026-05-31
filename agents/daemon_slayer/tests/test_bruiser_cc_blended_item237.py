"""Item 237 - bruiser cc_blended ranking + build-tenacity (symmetric to item 236).

The TANK scorer (rank_items_by_ehp) got tenacity-aware score_by="cc_blended" in
item 236; the BRUISER scorer (compute_hybrid + rank_items_by_hybrid) was still
tenacity-blind - it sorted on PRE-cc blended_ehp even when enemy_champions was
set, so a tenacity item could not rise vs a CC comp. This wires apply_build_tenacity
+ score_by through the hybrid path so the bruiser ranker re-ranks on the
CC-lockdown-adjusted EHP just like the tank ranker.

DEFAULT (score_by="blended", no enemies) byte-identical; flag-on re-ranks vs a
NON-saturating CC comp. ASCII only.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hybrid import compute_hybrid, rank_items_by_hybrid

_SUNFIRE = ["3068"]
_STERAKS = "3053"     # 20% tenacity terminal
_WITSEND = "3091"     # 20% tenacity terminal
_LIGHT_CC = ["Ashe"]  # ~1.5s CC - below the 6s saturation cap


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        server._CACHE.set(cls.snap)


class ComputeHybridTenacityTests(_Base):
    def test_tenacity_default_off_byte_identical(self) -> None:
        a = compute_hybrid(self.snap, "Sett", 11, item_ids=_SUNFIRE + [_STERAKS],
                           mode="SR", enemy_champions=_LIGHT_CC, include_conditional=True)
        b = compute_hybrid(self.snap, "Sett", 11, item_ids=_SUNFIRE + [_STERAKS],
                           mode="SR", enemy_champions=_LIGHT_CC, include_conditional=True,
                           apply_build_tenacity=False)
        self.assertEqual(a.hybrid_score, b.hybrid_score)

    def test_tenacity_raises_hybrid_score(self) -> None:
        off = compute_hybrid(self.snap, "Sett", 11, item_ids=_SUNFIRE + [_STERAKS],
                             mode="SR", enemy_champions=_LIGHT_CC, include_conditional=True,
                             apply_build_tenacity=False)
        on = compute_hybrid(self.snap, "Sett", 11, item_ids=_SUNFIRE + [_STERAKS],
                            mode="SR", enemy_champions=_LIGHT_CC, include_conditional=True,
                            apply_build_tenacity=True)
        self.assertGreater(on.hybrid_score, off.hybrid_score)

    def test_tenacity_noop_without_enemies(self) -> None:
        a = compute_hybrid(self.snap, "Sett", 11, item_ids=_SUNFIRE + [_STERAKS], mode="SR")
        b = compute_hybrid(self.snap, "Sett", 11, item_ids=_SUNFIRE + [_STERAKS], mode="SR",
                           apply_build_tenacity=True)
        self.assertEqual(a.hybrid_score, b.hybrid_score)


class RankHybridScoreByTests(_Base):
    def test_default_equals_blended(self) -> None:
        a = rank_items_by_hybrid(self.snap, "Sett", 11, current_item_ids=_SUNFIRE,
                                 mode="SR", top_n=8)
        b = rank_items_by_hybrid(self.snap, "Sett", 11, current_item_ids=_SUNFIRE,
                                 mode="SR", top_n=8, score_by="blended")
        self.assertEqual([r.item_id for r in a.ranked], [r.item_id for r in b.ranked])
        self.assertEqual([r.hybrid_delta_pct for r in a.ranked],
                         [r.hybrid_delta_pct for r in b.ranked])
        self.assertEqual(a.score_by, "blended")

    def test_no_enemy_cc_fields_equal_blended(self) -> None:
        a = rank_items_by_hybrid(self.snap, "Sett", 11, current_item_ids=_SUNFIRE,
                                 mode="SR", top_n=8)
        for r in a.ranked:
            self.assertEqual(r.cc_blended_ehp, r.new_ehp)
            self.assertEqual(r.delta_cc_blended_ehp, r.delta_ehp)

    def test_invalid_score_by_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_hybrid(self.snap, "Sett", 11, mode="SR", score_by="bogus")

    def test_cc_blended_reranks_tenacity_item_up(self) -> None:
        bl = rank_items_by_hybrid(self.snap, "Sett", 11, current_item_ids=_SUNFIRE,
                                  mode="SR", top_n=80, enemy_champions=_LIGHT_CC,
                                  include_conditional=True, score_by="blended")
        cc = rank_items_by_hybrid(self.snap, "Sett", 11, current_item_ids=_SUNFIRE,
                                  mode="SR", top_n=80, enemy_champions=_LIGHT_CC,
                                  include_conditional=True, score_by="cc_blended")
        blo = [r.item_id for r in bl.ranked]
        cco = [r.item_id for r in cc.ranked]
        self.assertNotEqual(blo, cco)
        self.assertIn(_WITSEND, blo)
        self.assertIn(_WITSEND, cco)
        # Wit's End (20% tenacity) rises (lower index) under cc_blended scoring.
        self.assertLess(cco.index(_WITSEND), blo.index(_WITSEND))
        self.assertEqual(cc.score_by, "cc_blended")

    def test_explicit_tenacity_off_inert(self) -> None:
        bl = rank_items_by_hybrid(self.snap, "Sett", 11, current_item_ids=_SUNFIRE,
                                  mode="SR", top_n=40, enemy_champions=_LIGHT_CC,
                                  include_conditional=True, score_by="blended",
                                  apply_build_tenacity=False)
        cc = rank_items_by_hybrid(self.snap, "Sett", 11, current_item_ids=_SUNFIRE,
                                  mode="SR", top_n=40, enemy_champions=_LIGHT_CC,
                                  include_conditional=True, score_by="cc_blended",
                                  apply_build_tenacity=False)
        # tenacity OFF -> cc_blended discount is a uniform per-comp scale ->
        # order-equivalent to blended (the honest no-tenacity behavior).
        self.assertEqual([r.item_id for r in bl.ranked],
                         [r.item_id for r in cc.ranked])


class RouteTests(_Base):
    def test_route_default_blended(self) -> None:
        out = server._route_rank_bruiser({"champion": "Sett", "level": 11,
                                          "items": "3068", "top": 5})
        self.assertEqual(out["score_by"], "blended")
        self.assertIn("cc_blended_ehp", out["ranked"][0])

    def test_route_cc_blended_reranks(self) -> None:
        bl = server._route_rank_bruiser({"champion": "Sett", "level": 11, "items": "3068",
                                         "top": 80, "enemies": "Ashe",
                                         "include_conditional": "1", "score_by": "blended"})
        cc = server._route_rank_bruiser({"champion": "Sett", "level": 11, "items": "3068",
                                         "top": 80, "enemies": "Ashe",
                                         "include_conditional": "1", "score_by": "cc_blended"})
        self.assertNotEqual([r["item_id"] for r in bl["ranked"]],
                            [r["item_id"] for r in cc["ranked"]])

    def test_route_bad_score_by_400(self) -> None:
        with self.assertRaises(server._ApiError) as ctx:
            server._route_rank_bruiser({"champion": "Sett", "score_by": "bogus"})
        self.assertEqual(ctx.exception.status, 400)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

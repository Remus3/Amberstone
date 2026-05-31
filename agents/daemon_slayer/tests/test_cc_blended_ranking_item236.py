"""Item 236 - opt-in CC-adjusted (cc_blended) EHP ranking + build-tenacity layer.

rank_items_by_ehp(score_by="cc_blended") ranks tank items by enemy-CC-lockdown-
adjusted EHP. The discount is made build-DEPENDENT by a NEW item-tenacity layer
(_item_tenacity.py + compute_ehp(apply_build_tenacity=...)) - tenacity shortens
the CC the caster eats, so a tenacity item (Sterak's / Mercury's) shrinks its
own lockdown and rises under cc_blended (vs a NON-saturating CC comp; against an
ultra-heavy comp the 6s fraction saturates and no tenacity helps - correct).

Two invariants: DEFAULT (score_by="blended", no enemies) byte-identical to the
pre-item-236 ranker; flag-on re-ranks. ASCII only.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer import server
from agents.daemon_slayer._item_tenacity import (
    item_tenacity,
    total_item_tenacity,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp

_SUNFIRE = ["3068"]
_STERAKS = "3053"          # 20% tenacity terminal item
_LIGHT_CC = ["Ashe"]       # ~1.5s CC - well under the 6s saturation cap


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        server._CACHE.set(cls.snap)


class ItemTenacityRegistryTests(unittest.TestCase):
    def test_single_accessor(self) -> None:
        self.assertEqual(item_tenacity("3111"), 30.0)   # Mercury's Treads
        self.assertEqual(item_tenacity("3053"), 20.0)   # Sterak's Gage
        self.assertEqual(item_tenacity("9999"), 0.0)    # unknown
        self.assertEqual(item_tenacity("3031"), 0.0)    # IE - no tenacity

    def test_total_multiplicative(self) -> None:
        # 30% + 20% multiplicative = 1 - 0.7*0.8 = 0.44 (NOT 0.50)
        self.assertAlmostEqual(total_item_tenacity(["3111", "3053"]), 0.44)
        self.assertEqual(total_item_tenacity([]), 0.0)
        self.assertEqual(total_item_tenacity(["3031", "3036"]), 0.0)
        self.assertAlmostEqual(total_item_tenacity(["3111"]), 0.30)
        # duplicate stacks per occurrence: 1 - 0.7*0.7 = 0.51
        self.assertAlmostEqual(total_item_tenacity(["3111", "3111"]), 0.51)
        # fraction always in [0, 1)
        self.assertLess(total_item_tenacity(["3111", "3053", "3091"]), 1.0)


class ComputeEhpTenacityTests(_Base):
    def test_apply_build_tenacity_default_off_byte_identical(self) -> None:
        a = compute_ehp(self.snap, "Malphite", 11, item_ids=_SUNFIRE + [_STERAKS],
                        mode="SR", enemy_champions=_LIGHT_CC, include_conditional=True)
        b = compute_ehp(self.snap, "Malphite", 11, item_ids=_SUNFIRE + [_STERAKS],
                        mode="SR", enemy_champions=_LIGHT_CC, include_conditional=True,
                        apply_build_tenacity=False)
        self.assertEqual(a.cc_blended_ehp, b.cc_blended_ehp)

    def test_tenacity_raises_cc_blended(self) -> None:
        off = compute_ehp(self.snap, "Malphite", 11, item_ids=_SUNFIRE + [_STERAKS],
                          mode="SR", enemy_champions=_LIGHT_CC, include_conditional=True,
                          apply_build_tenacity=False)
        on = compute_ehp(self.snap, "Malphite", 11, item_ids=_SUNFIRE + [_STERAKS],
                         mode="SR", enemy_champions=_LIGHT_CC, include_conditional=True,
                         apply_build_tenacity=True)
        # less CC eaten -> larger CC-adjusted EHP; blended_ehp itself unchanged
        self.assertGreater(on.cc_blended_ehp, off.cc_blended_ehp)
        self.assertEqual(on.blended_ehp, off.blended_ehp)

    def test_tenacity_noop_without_enemies(self) -> None:
        on = compute_ehp(self.snap, "Malphite", 11, item_ids=_SUNFIRE + [_STERAKS],
                         mode="SR", apply_build_tenacity=True)
        self.assertEqual(on.cc_blended_ehp, on.blended_ehp)

    def test_tenacity_noop_for_zero_tenacity_build(self) -> None:
        a = compute_ehp(self.snap, "Malphite", 11, item_ids=_SUNFIRE, mode="SR",
                        enemy_champions=_LIGHT_CC, include_conditional=True,
                        apply_build_tenacity=False)
        b = compute_ehp(self.snap, "Malphite", 11, item_ids=_SUNFIRE, mode="SR",
                        enemy_champions=_LIGHT_CC, include_conditional=True,
                        apply_build_tenacity=True)
        self.assertEqual(a.cc_blended_ehp, b.cc_blended_ehp)


class RankItemsByEhpScoreByTests(_Base):
    def test_default_equals_blended_byte_identical(self) -> None:
        a = rank_items_by_ehp(self.snap, "Malphite", 11, current_item_ids=_SUNFIRE,
                              mode="SR", top_n=8)
        b = rank_items_by_ehp(self.snap, "Malphite", 11, current_item_ids=_SUNFIRE,
                              mode="SR", top_n=8, score_by="blended")
        self.assertEqual([r.item_id for r in a.ranked], [r.item_id for r in b.ranked])
        self.assertEqual([r.delta_ehp for r in a.ranked], [r.delta_ehp for r in b.ranked])
        self.assertEqual(a.score_by, "blended")

    def test_no_enemy_cc_fields_equal_blended(self) -> None:
        a = rank_items_by_ehp(self.snap, "Malphite", 11, current_item_ids=_SUNFIRE,
                              mode="SR", top_n=8)
        for r in a.ranked:
            self.assertEqual(r.cc_blended_ehp, r.new_ehp)
            self.assertEqual(r.delta_cc_blended_ehp, r.delta_ehp)

    def test_invalid_score_by_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_ehp(self.snap, "Malphite", 11, mode="SR", score_by="bogus")

    def test_cc_blended_reranks_tenacity_item_up(self) -> None:
        bl = rank_items_by_ehp(self.snap, "Malphite", 11, current_item_ids=_SUNFIRE,
                               mode="SR", top_n=80, enemy_champions=_LIGHT_CC,
                               include_conditional=True, score_by="blended")
        cc = rank_items_by_ehp(self.snap, "Malphite", 11, current_item_ids=_SUNFIRE,
                               mode="SR", top_n=80, enemy_champions=_LIGHT_CC,
                               include_conditional=True, score_by="cc_blended")
        blo = [r.item_id for r in bl.ranked]
        cco = [r.item_id for r in cc.ranked]
        self.assertNotEqual(blo, cco)            # the mode genuinely re-ranks
        self.assertIn(_STERAKS, blo)
        self.assertIn(_STERAKS, cco)
        # Sterak's (tenacity item) rises (lower index) under cc_blended scoring
        self.assertLess(cco.index(_STERAKS), blo.index(_STERAKS))
        self.assertEqual(cc.score_by, "cc_blended")

    def test_explicit_tenacity_off_makes_cc_blended_inert(self) -> None:
        # With tenacity forced OFF the cc_blended discount is a uniform per-comp
        # scale -> order-equivalent to blended (the honest no-tenacity behavior).
        bl = rank_items_by_ehp(self.snap, "Malphite", 11, current_item_ids=_SUNFIRE,
                               mode="SR", top_n=40, enemy_champions=_LIGHT_CC,
                               include_conditional=True, score_by="blended",
                               apply_build_tenacity=False)
        cc = rank_items_by_ehp(self.snap, "Malphite", 11, current_item_ids=_SUNFIRE,
                               mode="SR", top_n=40, enemy_champions=_LIGHT_CC,
                               include_conditional=True, score_by="cc_blended",
                               apply_build_tenacity=False)
        self.assertEqual([r.item_id for r in bl.ranked],
                         [r.item_id for r in cc.ranked])


class RouteTests(_Base):
    def test_route_default_blended(self) -> None:
        out = server._route_rank_tank({"champion": "Malphite", "level": 11,
                                       "items": "3068", "top": 5})
        self.assertEqual(out["score_by"], "blended")
        self.assertIn("cc_blended_ehp", out["ranked"][0])

    def test_route_cc_blended_reranks(self) -> None:
        bl = server._route_rank_tank({"champion": "Malphite", "level": 11,
                                      "items": "3068", "top": 80, "enemies": "Ashe",
                                      "include_conditional": "1", "score_by": "blended"})
        cc = server._route_rank_tank({"champion": "Malphite", "level": 11,
                                      "items": "3068", "top": 80, "enemies": "Ashe",
                                      "include_conditional": "1", "score_by": "cc_blended"})
        self.assertNotEqual([r["item_id"] for r in bl["ranked"]],
                            [r["item_id"] for r in cc["ranked"]])

    def test_route_bad_score_by_400(self) -> None:
        with self.assertRaises(server._ApiError) as ctx:
            server._route_rank_tank({"champion": "Malphite", "score_by": "bogus"})
        self.assertEqual(ctx.exception.status, 400)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

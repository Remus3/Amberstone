"""Phase 1 (s174, 2026-05-12) - Tank item ranker tests.

Mirrors ``test_rank`` shape but exercises the EHP scorer side. The
filter-pipeline tests already live in ``test_rank`` (same helpers); these
focus on the EHP-specific scoring + the ``EhpRankedItem`` shape.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import (
    EhpRankResult,
    EhpRankedItem,
    compute_ehp,
    rank_items_by_ehp,
)


class RankByEhpBasicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_malphite_lvl_11_top_pick_includes_armor_item(self) -> None:
        # Malphite + AD-heavy enemy → top picks should include a known
        # armor item. Hardcoded ID set is the 16.9.1 floor; future patches
        # may shuffle order but at least ONE of these should land top-5.
        r = rank_items_by_ehp(
            self.snap, "Malphite", level=11,
            enemy_ad_share=0.9, enemy_ap_share=0.1, top_n=10,
        )
        self.assertGreater(len(r.ranked), 0)
        top_ids = {ri.item_id for ri in r.ranked[:5]}
        # Thornmail / Frozen Heart / Plated Steelcaps / Randuin's / Dead Man's Plate.
        self.assertTrue(
            top_ids & {"3075", "3110", "3047", "3143", "3742"},
            f"expected armor item in top-5, got: {top_ids}",
        )

    def test_baseline_ehp_matches_compute_ehp_no_items(self) -> None:
        baseline = compute_ehp(self.snap, "Malphite", level=11,
                               enemy_ad_share=0.5, enemy_ap_share=0.5)
        r = rank_items_by_ehp(self.snap, "Malphite", level=11,
                              enemy_ad_share=0.5, enemy_ap_share=0.5,
                              top_n=1)
        self.assertAlmostEqual(r.baseline_ehp, baseline.blended_ehp, places=4)

    def test_top_1_delta_equals_new_minus_baseline(self) -> None:
        r = rank_items_by_ehp(self.snap, "Malphite", level=11,
                              enemy_ad_share=0.9, enemy_ap_share=0.1,
                              top_n=1)
        top = r.ranked[0]
        self.assertAlmostEqual(top.delta_ehp, top.new_ehp - r.baseline_ehp, places=4)

    def test_results_sorted_descending_by_delta(self) -> None:
        r = rank_items_by_ehp(self.snap, "Malphite", level=11, top_n=20)
        deltas = [ri.delta_ehp for ri in r.ranked]
        self.assertEqual(deltas, sorted(deltas, reverse=True))

    def test_efficiency_sort_can_reorder_top_pick(self) -> None:
        # Cheap component items have better EHP-per-gold than full items;
        # the delta and efficiency orderings should not be identical when
        # include_components=True surfaces the components.
        by_delta = rank_items_by_ehp(
            self.snap, "Malphite", level=11,
            enemy_ad_share=0.9, enemy_ap_share=0.1,
            include_components=True, top_n=10, sort_by="delta",
        )
        by_eff = rank_items_by_ehp(
            self.snap, "Malphite", level=11,
            enemy_ad_share=0.9, enemy_ap_share=0.1,
            include_components=True, top_n=10, sort_by="efficiency",
        )
        self.assertNotEqual(
            [r.item_id for r in by_delta.ranked],
            [r.item_id for r in by_eff.ranked],
        )
        # Efficiency list sorted descending by ehp_per_1k_gold.
        effs = [r.ehp_per_1k_gold for r in by_eff.ranked]
        self.assertEqual(effs, sorted(effs, reverse=True))

    def test_sort_by_invalid_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_ehp(self.snap, "Malphite", level=1, sort_by="random")

    def test_full_inventory_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_ehp(
                self.snap, "Malphite", level=11,
                current_item_ids=["3075", "3110", "3047", "3143", "3068", "6665"],
            )

    def test_invalid_level_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_ehp(self.snap, "Malphite", level=99)

    def test_share_validation_propagates(self) -> None:
        # rank_items_by_ehp calls compute_ehp internally; share validation
        # should surface at the rank level too.
        with self.assertRaises(ValueError):
            rank_items_by_ehp(self.snap, "Malphite", level=11,
                              enemy_ad_share=0.7, enemy_ap_share=0.7)


class CandidateFilteringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_current_items_not_ranked(self) -> None:
        r = rank_items_by_ehp(
            self.snap, "Malphite", level=11,
            current_item_ids=["3075"], top_n=50,
        )
        self.assertNotIn("3075", {ri.item_id for ri in r.ranked})

    def test_budget_filters_expensive(self) -> None:
        r = rank_items_by_ehp(
            self.snap, "Malphite", level=11, budget=1000, top_n=50,
        )
        self.assertTrue(all(ri.gold <= 1000 for ri in r.ranked))

    def test_only_item_ids_whitelist_works(self) -> None:
        # Pass a curated whitelist; result should be a subset of the whitelist.
        whitelist = {"3075", "3110", "3047", "3143"}
        r = rank_items_by_ehp(
            self.snap, "Malphite", level=11,
            only_item_ids=whitelist, top_n=20,
        )
        ranked_ids = {ri.item_id for ri in r.ranked}
        self.assertTrue(ranked_ids.issubset(whitelist))
        # And at least one should make the list.
        self.assertGreater(len(ranked_ids), 0)

    def test_zero_or_negative_delta_has_zero_efficiency(self) -> None:
        # Pure-offensive items (Doran's Blade, Long Sword) shouldn't add EHP;
        # if any negative-delta entries appear their efficiency must be 0.
        r = rank_items_by_ehp(
            self.snap, "Malphite", level=11,
            include_components=True, top_n=200,
        )
        for ri in r.ranked:
            if ri.delta_ehp <= 0:
                self.assertEqual(ri.ehp_per_1k_gold, 0.0)


class SharedUniqueFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_sterak_then_maw_filtered_by_default(self) -> None:
        # Both Sterak's (3053) and Maw of Malmortius (3156) share the
        # "lifeline" unique_passive_key. With Sterak's already built,
        # Maw's lifeline shield is dead - default filter drops the
        # candidate from the rank.
        r = rank_items_by_ehp(
            self.snap, "Aatrox", level=11,
            current_item_ids=["3053"], top_n=50,
            filter_shared_uniques=True,
        )
        ids = {ri.item_id for ri in r.ranked}
        self.assertNotIn("3156", ids)

    def test_opt_out_surfaces_dead_unique_flag(self) -> None:
        r = rank_items_by_ehp(
            self.snap, "Aatrox", level=11,
            current_item_ids=["3053"], top_n=50,
            filter_shared_uniques=False,
        )
        maws = [ri for ri in r.ranked if ri.item_id == "3156"]
        if maws:
            self.assertTrue(maws[0].shares_dead_unique)
            self.assertEqual(maws[0].dead_unique_key, "lifeline")


class EnemyShareSensitivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_pure_ap_enemy_prefers_mr_items(self) -> None:
        # Force of Nature (4401) should outrank Thornmail (3075) when
        # enemy_ap_share=1.0 - magical EHP dominates blended_ehp.
        r = rank_items_by_ehp(
            self.snap, "Malphite", level=11,
            enemy_ad_share=0.0, enemy_ap_share=1.0,
            only_item_ids=["4401", "3075"], top_n=2,
        )
        ids_by_rank = [ri.item_id for ri in r.ranked]
        # FoN should land before Thornmail.
        self.assertIn("4401", ids_by_rank)
        if "3075" in ids_by_rank and "4401" in ids_by_rank:
            self.assertLess(ids_by_rank.index("4401"), ids_by_rank.index("3075"))

    def test_pure_ad_enemy_prefers_armor_items(self) -> None:
        r = rank_items_by_ehp(
            self.snap, "Malphite", level=11,
            enemy_ad_share=1.0, enemy_ap_share=0.0,
            only_item_ids=["4401", "3075"], top_n=2,
        )
        ids_by_rank = [ri.item_id for ri in r.ranked]
        self.assertIn("3075", ids_by_rank)
        if "3075" in ids_by_rank and "4401" in ids_by_rank:
            self.assertLess(ids_by_rank.index("3075"), ids_by_rank.index("4401"))


class SerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_to_dict_round_trips_core_fields(self) -> None:
        r = rank_items_by_ehp(self.snap, "Malphite", level=11, top_n=3)
        d = r.to_dict()
        for key in (
            "champion_id", "champion_name", "level", "mode",
            "current_item_ids", "baseline_ehp",
            "enemy_ad_share", "enemy_ap_share", "enemy_true_share",
            "budget", "slot_count", "sort_by",
            "candidates_considered", "candidates_evaluated", "ranked", "notes",
        ):
            self.assertIn(key, d)
        # ranked must be a list of dicts, not dataclass instances.
        self.assertIsInstance(d["ranked"], list)
        if d["ranked"]:
            self.assertIsInstance(d["ranked"][0], dict)
            self.assertIn("delta_ehp", d["ranked"][0])

    def test_format_table_renders(self) -> None:
        r = rank_items_by_ehp(self.snap, "Malphite", level=11, top_n=3)
        tbl = r.format_table()
        self.assertIn("Malphite", tbl)
        self.assertIn("TANK", tbl)
        self.assertIn("+ehp", tbl)


if __name__ == "__main__":
    unittest.main()

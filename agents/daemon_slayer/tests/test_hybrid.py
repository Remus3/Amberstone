"""Phase 2 (s175, 2026-05-12) - Bruiser hybrid scorer tests.

Mirrors ``test_ehp`` + ``test_rank_tank`` shape. Exercises ``compute_hybrid``
+ ``rank_items_by_hybrid`` + the ``archetype_weights.json`` lookup against
the live 16.9.1 snapshot. Linearity tests pin the math; archetype tests
verify that the per-champion weights actually shift ranker output.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer.hybrid import (
    HybridRankResult,
    HybridRankedItem,
    HybridResult,
    _hybrid_delta_pct,
    _load_archetype_weights,
    compute_hybrid,
    get_weights_for,
    rank_items_by_hybrid,
)


class WeightsTableTests(unittest.TestCase):
    """The per-champion (α, β) registry."""

    def test_default_pair_balanced(self) -> None:
        # Fallback when no override exists.
        self.assertEqual(get_weights_for("Aatrox"), (0.5, 0.5))
        self.assertEqual(get_weights_for("UnknownChampion"), (0.5, 0.5))

    def test_jarvaniv_override(self) -> None:
        # JarvanIV is in the table at (0.55, 0.45).
        a, b = get_weights_for("JarvanIV")
        self.assertAlmostEqual(a, 0.55)
        self.assertAlmostEqual(b, 0.45)

    def test_riven_skews_offensive(self) -> None:
        # Riven is the most offensive bruiser in the table: 0.70 / 0.30.
        a, b = get_weights_for("Riven")
        self.assertGreater(a, 0.6)
        self.assertLess(b, 0.4)

    def test_monkeyking_uses_ddragon_id_not_display_name(self) -> None:
        # The table keys MUST be DDragon IDs (display→id resolution is
        # server-side). Wukong → MonkeyKing.
        a, b = get_weights_for("MonkeyKing")
        self.assertAlmostEqual(a, 0.60)
        # "Wukong" should NOT be in the table - falls back to default.
        a_wukong, b_wukong = get_weights_for("Wukong")
        self.assertEqual((a_wukong, b_wukong), (0.5, 0.5))

    def test_all_listed_pairs_sum_close_to_one(self) -> None:
        # By convention α+β=1.0; the table is operator-facing and the
        # operator should be able to think of (0.65, 0.35) as a 65/35
        # split. Pin the convention.
        table = _load_archetype_weights()
        for cid, pair in (table.get("champions") or {}).items():
            self.assertAlmostEqual(
                pair[0] + pair[1], 1.0, places=4,
                msg=f"{cid}: α+β = {pair[0]+pair[1]} (expected 1.0)",
            )

    def test_table_has_at_least_15_bruisers(self) -> None:
        # Phase 2 ships ~20 bruisers; pin a floor.
        table = _load_archetype_weights()
        self.assertGreaterEqual(len(table.get("champions") or {}), 15)


class ComputeHybridBasicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_returns_hybrid_result(self) -> None:
        r = compute_hybrid(self.snap, "Aatrox", level=11)
        self.assertIsInstance(r, HybridResult)
        self.assertEqual(r.champion_id, "Aatrox")
        self.assertEqual(r.level, 11)

    def test_dps_field_matches_compute_dps(self) -> None:
        r_hybrid = compute_hybrid(self.snap, "Aatrox", level=11)
        r_dps = compute_dps(self.snap, "Aatrox", level=11)
        self.assertAlmostEqual(r_hybrid.dps, r_dps.weighted_dps, places=4)

    def test_ehp_field_matches_compute_ehp(self) -> None:
        r_hybrid = compute_hybrid(self.snap, "Aatrox", level=11)
        r_ehp = compute_ehp(self.snap, "Aatrox", level=11)
        self.assertAlmostEqual(r_hybrid.ehp, r_ehp.blended_ehp, places=4)

    def test_hybrid_score_is_linear_combination(self) -> None:
        # hybrid_score = α·dps + β·ehp - pin the raw scalar.
        r = compute_hybrid(self.snap, "JarvanIV", level=11)
        expected = r.alpha * r.dps + r.beta * r.ehp
        self.assertAlmostEqual(r.hybrid_score, expected, places=4)

    def test_default_alpha_for_listed_champion(self) -> None:
        # JarvanIV table entry kicks in when alpha/beta omitted.
        r = compute_hybrid(self.snap, "JarvanIV", level=11)
        self.assertAlmostEqual(r.alpha, 0.55)
        self.assertAlmostEqual(r.beta, 0.45)
        self.assertEqual(r.alpha_source, "champion")

    def test_default_alpha_for_unlisted_champion(self) -> None:
        r = compute_hybrid(self.snap, "Aatrox", level=11)
        self.assertAlmostEqual(r.alpha, 0.5)
        self.assertAlmostEqual(r.beta, 0.5)
        self.assertEqual(r.alpha_source, "default")

    def test_explicit_override_alpha_beta(self) -> None:
        r = compute_hybrid(self.snap, "JarvanIV", level=11,
                           alpha=0.8, beta=0.2)
        self.assertAlmostEqual(r.alpha, 0.8)
        self.assertAlmostEqual(r.beta, 0.2)
        self.assertEqual(r.alpha_source, "override")


class HybridDeltaPctTests(unittest.TestCase):
    """Pure-math tests for the normalized-delta scoring helper."""

    def test_linearity_in_weights(self) -> None:
        # 0.5*dps + 0.5*ehp == 0.5*(dps + ehp) - pin the linearity invariant.
        score_half_each = _hybrid_delta_pct(
            delta_dps=50.0, delta_ehp=500.0,
            baseline_dps=200.0, baseline_ehp=2500.0,
            alpha=0.5, beta=0.5,
        )
        score_sum = _hybrid_delta_pct(
            delta_dps=50.0, delta_ehp=500.0,
            baseline_dps=200.0, baseline_ehp=2500.0,
            alpha=1.0, beta=1.0,
        )
        self.assertAlmostEqual(score_half_each, 0.5 * score_sum, places=6)

    def test_normalized_balance_at_half_each(self) -> None:
        # When both percentages are equal, score = (α+β)/2 * common_pct.
        # 25% DPS gain + 25% EHP gain at α=β=0.5 → 0.25.
        s = _hybrid_delta_pct(
            delta_dps=50.0, delta_ehp=625.0,
            baseline_dps=200.0, baseline_ehp=2500.0,
            alpha=0.5, beta=0.5,
        )
        self.assertAlmostEqual(s, 0.25, places=4)

    def test_pure_dps_weight_ignores_ehp(self) -> None:
        s = _hybrid_delta_pct(
            delta_dps=50.0, delta_ehp=999999.0,
            baseline_dps=200.0, baseline_ehp=2500.0,
            alpha=1.0, beta=0.0,
        )
        # 50/200 = 0.25 × 1.0 + 0 × β = 0.25 regardless of ehp delta
        self.assertAlmostEqual(s, 0.25, places=4)

    def test_zero_baseline_dps_falls_back_to_zero_pct(self) -> None:
        # Div-by-zero guard.
        s = _hybrid_delta_pct(
            delta_dps=50.0, delta_ehp=500.0,
            baseline_dps=0.0, baseline_ehp=2500.0,
            alpha=0.5, beta=0.5,
        )
        # DPS contribution is 0; EHP delta is 500/2500 × 0.5 = 0.1
        self.assertAlmostEqual(s, 0.1, places=4)


class RankByHybridBasicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_returns_hybrid_rank_result(self) -> None:
        r = rank_items_by_hybrid(self.snap, "Darius", level=11, top_n=5)
        self.assertIsInstance(r, HybridRankResult)
        self.assertGreater(len(r.ranked), 0)
        for ri in r.ranked:
            self.assertIsInstance(ri, HybridRankedItem)

    def test_baseline_dps_matches_compute_dps(self) -> None:
        r_rank = rank_items_by_hybrid(self.snap, "Darius", level=11, top_n=1)
        r_dps = compute_dps(self.snap, "Darius", level=11)
        self.assertAlmostEqual(r_rank.baseline_dps, r_dps.weighted_dps, places=4)

    def test_baseline_ehp_matches_compute_ehp(self) -> None:
        r_rank = rank_items_by_hybrid(self.snap, "Darius", level=11, top_n=1)
        r_ehp = compute_ehp(self.snap, "Darius", level=11)
        self.assertAlmostEqual(r_rank.baseline_ehp, r_ehp.blended_ehp, places=4)

    def test_alpha_beta_loaded_from_table(self) -> None:
        r = rank_items_by_hybrid(self.snap, "JarvanIV", level=11, top_n=1)
        self.assertAlmostEqual(r.alpha, 0.55)
        self.assertAlmostEqual(r.beta, 0.45)
        self.assertEqual(r.alpha_source, "champion")

    def test_explicit_alpha_beta_override(self) -> None:
        r = rank_items_by_hybrid(
            self.snap, "JarvanIV", level=11,
            alpha=0.9, beta=0.1, top_n=1,
        )
        self.assertAlmostEqual(r.alpha, 0.9)
        self.assertEqual(r.alpha_source, "override")

    def test_results_sorted_descending_by_hybrid_delta_pct(self) -> None:
        r = rank_items_by_hybrid(self.snap, "Darius", level=11, top_n=20)
        scores = [ri.hybrid_delta_pct for ri in r.ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_high_alpha_prefers_pure_dps_items(self) -> None:
        # Riven at α=0.9 vs α=0.1 - with α=0.9, pure-AD/AS items
        # should rank higher than with α=0.1.
        # Use a constrained whitelist: pure DPS (Infinity Edge 3031)
        # vs pure tank (Thornmail 3075). At α=0.9 IE should top;
        # at α=0.1 Thornmail should top (when enemy is AD-heavy so
        # Thornmail's armor adds meaningful EHP).
        offensive = rank_items_by_hybrid(
            self.snap, "Riven", level=11,
            enemy_ad_share=0.5, enemy_ap_share=0.5,
            only_item_ids=["3031", "3075"],
            alpha=0.9, beta=0.1, top_n=2,
        )
        defensive = rank_items_by_hybrid(
            self.snap, "Riven", level=11,
            enemy_ad_share=0.5, enemy_ap_share=0.5,
            only_item_ids=["3031", "3075"],
            alpha=0.1, beta=0.9, top_n=2,
        )
        if len(offensive.ranked) >= 2 and len(defensive.ranked) >= 2:
            offensive_top = offensive.ranked[0].item_id
            defensive_top = defensive.ranked[0].item_id
            # The top picks should DIFFER between extreme α values.
            self.assertNotEqual(offensive_top, defensive_top)

    def test_extreme_alpha_matches_pure_dps_ranker_top(self) -> None:
        # α=1.0 / β=0 should pick the same top item as the pure-DPS
        # ranker would (within the same whitelist). Use a curated set
        # so the test is stable across patches.
        whitelist = ["3031", "3033", "3036", "3072", "3075", "3110"]
        from agents.daemon_slayer.rank import rank_items
        dps_rank = rank_items(
            self.snap, "Darius", level=11,
            only_item_ids=whitelist, top_n=5,
        )
        hybrid_rank = rank_items_by_hybrid(
            self.snap, "Darius", level=11,
            only_item_ids=whitelist,
            alpha=1.0, beta=0.0, top_n=5,
        )
        if dps_rank.ranked and hybrid_rank.ranked:
            self.assertEqual(
                dps_rank.ranked[0].item_id,
                hybrid_rank.ranked[0].item_id,
            )

    def test_extreme_beta_matches_pure_ehp_ranker_top(self) -> None:
        # α=0 / β=1.0 should pick the same top item as the pure-EHP ranker.
        whitelist = ["3031", "3033", "3036", "3072", "3075", "3110", "4401"]
        from agents.daemon_slayer.ehp import rank_items_by_ehp
        ehp_rank = rank_items_by_ehp(
            self.snap, "Darius", level=11,
            enemy_ad_share=0.5, enemy_ap_share=0.5,
            only_item_ids=whitelist, top_n=5,
        )
        hybrid_rank = rank_items_by_hybrid(
            self.snap, "Darius", level=11,
            enemy_ad_share=0.5, enemy_ap_share=0.5,
            only_item_ids=whitelist,
            alpha=0.0, beta=1.0, top_n=5,
        )
        if ehp_rank.ranked and hybrid_rank.ranked:
            self.assertEqual(
                ehp_rank.ranked[0].item_id,
                hybrid_rank.ranked[0].item_id,
            )

    def test_invalid_sort_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_hybrid(self.snap, "Darius", level=11, sort_by="bogus")

    def test_full_inventory_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_hybrid(
                self.snap, "Darius", level=11,
                current_item_ids=["3031", "3033", "3036", "3072", "3075", "3110"],
            )

    def test_invalid_level_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_hybrid(self.snap, "Darius", level=99)


class CandidateFilteringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_current_items_not_ranked(self) -> None:
        r = rank_items_by_hybrid(
            self.snap, "Darius", level=11,
            current_item_ids=["3075"], top_n=50,
        )
        self.assertNotIn("3075", {ri.item_id for ri in r.ranked})

    def test_budget_filters_expensive(self) -> None:
        r = rank_items_by_hybrid(
            self.snap, "Darius", level=11, budget=1500, top_n=50,
        )
        self.assertTrue(all(ri.gold <= 1500 for ri in r.ranked))

    def test_only_item_ids_whitelist_restricts(self) -> None:
        whitelist = {"3075", "3031", "3072"}
        r = rank_items_by_hybrid(
            self.snap, "Darius", level=11,
            only_item_ids=whitelist, top_n=20,
        )
        self.assertTrue({ri.item_id for ri in r.ranked}.issubset(whitelist))

    def test_efficiency_sort_orders_by_per_gold(self) -> None:
        r = rank_items_by_hybrid(
            self.snap, "Darius", level=11,
            include_components=True, top_n=10, sort_by="efficiency",
        )
        effs = [ri.hybrid_per_1k_gold for ri in r.ranked]
        self.assertEqual(effs, sorted(effs, reverse=True))


class SharedUniqueFilterTests(unittest.TestCase):
    """Dead-unique candidate filter still applies to the hybrid ranker."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_sterak_then_maw_filtered_by_default(self) -> None:
        # 3053 Sterak's + 3156 Maw both share unique_passive_key='lifeline'.
        # With Sterak's locked in, Maw's lifeline is dead.
        r = rank_items_by_hybrid(
            self.snap, "Aatrox", level=11,
            current_item_ids=["3053"], top_n=50,
            filter_shared_uniques=True,
        )
        self.assertNotIn("3156", {ri.item_id for ri in r.ranked})

    def test_opt_out_surfaces_dead_unique_flag(self) -> None:
        r = rank_items_by_hybrid(
            self.snap, "Aatrox", level=11,
            current_item_ids=["3053"], top_n=200,
            filter_shared_uniques=False,
        )
        maws = [ri for ri in r.ranked if ri.item_id == "3156"]
        if maws:
            self.assertTrue(maws[0].shares_dead_unique)
            self.assertEqual(maws[0].dead_unique_key, "lifeline")


class ARAMModeTests(unittest.TestCase):
    """ARAM modifiers flow into both component scores."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_aram_mode_multiplier_dps_flows_through(self) -> None:
        r = compute_hybrid(self.snap, "Darius", level=11, mode="ARAM")
        # mode_multiplier_dps is aramDamageDealt; mode_multiplier_ehp is aramDamageTaken.
        # Both fields populated.
        self.assertIsInstance(r.mode_multiplier_dps, float)
        self.assertIsInstance(r.mode_multiplier_ehp, float)

    def test_aram_mode_does_not_raise(self) -> None:
        # Smoke test - ranker works in ARAM mode.
        r = rank_items_by_hybrid(self.snap, "Darius", level=11, mode="ARAM",
                                 top_n=3)
        self.assertGreater(len(r.ranked), 0)


class SerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_compute_hybrid_to_dict_has_all_fields(self) -> None:
        r = compute_hybrid(self.snap, "JarvanIV", level=11)
        d = r.to_dict()
        for key in (
            "champion_id", "champion_name", "level", "item_ids", "mode",
            "alpha", "beta", "alpha_source",
            "dps", "ehp", "hybrid_score",
            "target_armor", "target_mr", "target_max_hp", "target_bonus_hp",
            "enemy_ad_share", "enemy_ap_share", "enemy_true_share",
            "phase", "mode_multiplier_dps", "mode_multiplier_ehp",
            "notes",
        ):
            self.assertIn(key, d, f"to_dict() missing key: {key}")

    def test_rank_to_dict_has_all_fields(self) -> None:
        r = rank_items_by_hybrid(self.snap, "Darius", level=11, top_n=3)
        d = r.to_dict()
        for key in (
            "champion_id", "champion_name", "level", "mode",
            "current_item_ids",
            "alpha", "beta", "alpha_source",
            "baseline_dps", "baseline_ehp", "baseline_hybrid",
            "enemy_ad_share", "enemy_ap_share", "enemy_true_share",
            "target_armor", "target_mr", "target_max_hp", "target_bonus_hp",
            "phase", "budget", "slot_count", "sort_by",
            "candidates_considered", "candidates_evaluated", "ranked", "notes",
        ):
            self.assertIn(key, d)
        if d["ranked"]:
            self.assertIsInstance(d["ranked"][0], dict)
            for key in ("delta_dps", "delta_ehp", "hybrid_delta_pct"):
                self.assertIn(key, d["ranked"][0])

    def test_format_table_renders(self) -> None:
        r = rank_items_by_hybrid(self.snap, "JarvanIV", level=11, top_n=3)
        tbl = r.format_table()
        self.assertIn("JarvanIV", tbl)
        self.assertIn("BRUISER", tbl)
        self.assertIn("+dps", tbl)
        self.assertIn("+ehp", tbl)


if __name__ == "__main__":
    unittest.main()

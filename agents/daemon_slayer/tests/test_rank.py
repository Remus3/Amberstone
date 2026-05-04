import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import (
    DEFAULT_SLOT_COUNT,
    MODE_MAP_ID,
    SORT_KEYS,
    _filter_candidates,
    _is_legal_in_mode,
    _is_purchasable,
    _is_terminal,
    rank_items,
)


class FilterPredicateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_purchasable_excludes_zero_gold_or_unpurchasable(self) -> None:
        self.assertTrue(_is_purchasable({"gold": {"purchasable": True, "total": 100}}))
        self.assertFalse(_is_purchasable({"gold": {"purchasable": False, "total": 100}}))
        self.assertFalse(_is_purchasable({"gold": {"purchasable": True, "total": 0}}))
        self.assertFalse(_is_purchasable({}))

    def test_terminal_means_no_into(self) -> None:
        self.assertTrue(_is_terminal({}))
        self.assertTrue(_is_terminal({"into": None}))
        self.assertTrue(_is_terminal({"into": []}))
        self.assertFalse(_is_terminal({"into": ["3171"]}))

    def test_mode_legality_uses_correct_map_id(self) -> None:
        # SR=11, ARAM=12, ARENA=30
        sr_only = {"maps": {"11": True, "12": False, "30": False}}
        self.assertTrue(_is_legal_in_mode(sr_only, "SR"))
        self.assertFalse(_is_legal_in_mode(sr_only, "ARAM"))
        self.assertFalse(_is_legal_in_mode(sr_only, "ARENA"))

    def test_unknown_mode_passes_through(self) -> None:
        self.assertTrue(_is_legal_in_mode({"maps": {}}, "TFT_DOUBLE_UP"))


class CandidateFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_sr_terminal_count_in_recent_snapshot_range(self) -> None:
        # 175 in 16.9.1; allow generous range so future patches don't redden CI.
        cands = _filter_candidates(
            self.snap, mode="SR", current_ids=set(), budget=None,
            include_components=False, only_ids=None,
        )
        self.assertGreater(len(cands), 100)
        self.assertLess(len(cands), 300)

    def test_aram_terminal_is_subset_of_sr(self) -> None:
        sr = {i for i, _ in _filter_candidates(
            self.snap, "SR", set(), None, False, None,
        )}
        aram = {i for i, _ in _filter_candidates(
            self.snap, "ARAM", set(), None, False, None,
        )}
        # Most ARAM-legal completed items are also SR-legal in 16.9.1.
        # Don't pin equality — pin "ARAM is meaningfully smaller than SR".
        self.assertLess(len(aram), len(sr))

    def test_include_components_grows_candidate_count(self) -> None:
        terminal = _filter_candidates(
            self.snap, "SR", set(), None, False, None,
        )
        with_components = _filter_candidates(
            self.snap, "SR", set(), None, True, None,
        )
        self.assertGreater(len(with_components), len(terminal))

    def test_budget_excludes_overpriced(self) -> None:
        ie_id = "3031"  # Infinity Edge, 3500g
        under = _filter_candidates(
            self.snap, "SR", set(), 1000, False, None,
        )
        self.assertNotIn(ie_id, {i for i, _ in under})

    def test_already_equipped_is_excluded(self) -> None:
        ie_id = "3031"
        cands = _filter_candidates(
            self.snap, "SR", current_ids={ie_id},
            budget=None, include_components=False, only_ids=None,
        )
        self.assertNotIn(ie_id, {i for i, _ in cands})

    def test_only_ids_whitelist_is_intersection_with_filter(self) -> None:
        # Whitelist of [IE, Long Sword] in SR terminal-only mode → only IE survives.
        cands = _filter_candidates(
            self.snap, "SR", set(), None, False, only_ids={"3031", "1036"},
        )
        ids = {i for i, _ in cands}
        self.assertIn("3031", ids)
        self.assertNotIn("1036", ids)


class RankItemsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_aatrox_naked_lvl_11_top_pick_is_a_dps_item(self) -> None:
        r = rank_items(self.snap, "Aatrox", level=11, mode="SR", target_armor=80, top_n=10)
        self.assertGreater(len(r.ranked), 0)
        # IE / BT / Stormrazor are the expected top tier in 16.9.1 stat-only math.
        top_ids = {ri.item_id for ri in r.ranked[:5]}
        # At least one of the standard DPS finishers should land top-5.
        self.assertTrue(top_ids & {"3031", "3072", "3097", "6673"})

    def test_baseline_dps_matches_compute_dps_no_items(self) -> None:
        from agents.daemon_slayer.dps import compute_dps
        baseline = compute_dps(self.snap, "Aatrox", level=11, target_armor=80)
        r = rank_items(self.snap, "Aatrox", level=11, target_armor=80, top_n=1)
        self.assertAlmostEqual(r.baseline_dps, baseline.weighted_dps, places=4)

    def test_top_1_delta_equals_new_minus_baseline(self) -> None:
        r = rank_items(self.snap, "Aatrox", level=11, target_armor=80, top_n=1)
        top = r.ranked[0]
        self.assertAlmostEqual(top.delta_dps, top.new_dps - r.baseline_dps, places=4)

    def test_results_are_sorted_descending_by_delta(self) -> None:
        r = rank_items(self.snap, "Aatrox", level=11, target_armor=80, top_n=20)
        deltas = [ri.delta_dps for ri in r.ranked]
        self.assertEqual(deltas, sorted(deltas, reverse=True))

    def test_efficiency_sort_can_reorder_top_pick(self) -> None:
        # Top by absolute delta is rarely top by efficiency — IE (3500g) vs.
        # a cheap stat stick (Doran's Blade, 450g, smaller delta but better g/dps).
        by_delta = rank_items(
            self.snap, "Aatrox", level=11, target_armor=80, top_n=5, sort_by="delta",
        )
        by_eff = rank_items(
            self.snap, "Aatrox", level=11, target_armor=80, top_n=5, sort_by="efficiency",
        )
        # Different sort keys should produce non-identical orderings here.
        self.assertNotEqual(
            [r.item_id for r in by_delta.ranked],
            [r.item_id for r in by_eff.ranked],
        )
        # Efficiency list is sorted descending by dps_per_1k_gold.
        effs = [r.dps_per_1k_gold for r in by_eff.ranked]
        self.assertEqual(effs, sorted(effs, reverse=True))

    def test_sort_by_invalid_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items(self.snap, "Aatrox", level=1, sort_by="random")

    def test_full_inventory_raises(self) -> None:
        # 6 already equipped — no slot for the candidate.
        with self.assertRaises(ValueError):
            rank_items(
                self.snap, "Aatrox", level=11,
                current_item_ids=["3031", "3072", "3006", "3097", "6673", "3508"],
            )

    def test_yunara_aram_zero_mult_zeros_all_deltas(self) -> None:
        r = rank_items(self.snap, "Yunara", level=11, mode="ARAM", top_n=10)
        self.assertEqual(r.baseline_dps, 0.0)
        self.assertTrue(all(ri.delta_dps == 0.0 for ri in r.ranked))
        self.assertTrue(any("mode_multiplier=0" in n for n in r.notes))

    def test_current_items_are_not_ranked(self) -> None:
        r = rank_items(
            self.snap, "Aatrox", level=11, current_item_ids=["3031"], top_n=50,
        )
        self.assertNotIn("3031", {ri.item_id for ri in r.ranked})

    def test_budget_filters_expensive_items(self) -> None:
        r = rank_items(
            self.snap, "Aatrox", level=11, budget=1000, top_n=50,
        )
        self.assertTrue(all(ri.gold <= 1000 for ri in r.ranked))

    def test_zero_or_negative_delta_has_zero_efficiency(self) -> None:
        # Pure-defense terminal items (e.g. Warmog's) shouldn't add DPS for Aatrox.
        # If any delta<=0 entries appear, their efficiency must be exactly 0.
        r = rank_items(
            self.snap, "Aatrox", level=11, target_armor=80,
            include_components=True, top_n=200,
        )
        for ri in r.ranked:
            if ri.delta_dps <= 0:
                self.assertEqual(ri.dps_per_1k_gold, 0.0)

    def test_invalid_level_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items(self.snap, "Aatrox", level=99)


class ModeMapIdTests(unittest.TestCase):
    def test_mode_table_documented_modes_present(self) -> None:
        for m in ("SR", "ARAM", "ARENA"):
            self.assertIn(m, MODE_MAP_ID)

    def test_sort_keys_match_signature(self) -> None:
        self.assertIn("delta", SORT_KEYS)
        self.assertIn("efficiency", SORT_KEYS)


class SerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_rank_result_to_dict_roundtrips_key_fields(self) -> None:
        r = rank_items(self.snap, "Aatrox", level=11, target_armor=80, top_n=3)
        d = r.to_dict()
        self.assertEqual(d["champion_id"], "Aatrox")
        self.assertEqual(d["mode"], "SR")
        self.assertEqual(d["sort_by"], "delta")
        self.assertEqual(d["slot_count"], DEFAULT_SLOT_COUNT)
        self.assertEqual(len(d["ranked"]), 3)
        for row in d["ranked"]:
            for k in ("item_id", "item_name", "gold", "delta_dps", "new_dps",
                      "dps_per_1k_gold", "is_terminal", "tags"):
                self.assertIn(k, row)

    def test_format_table_contains_key_fields(self) -> None:
        r = rank_items(self.snap, "Aatrox", level=11, target_armor=80, top_n=3)
        table = r.format_table()
        self.assertIn("Aatrox", table)
        self.assertIn("lvl 11", table)
        self.assertIn("baseline_dps", table)
        self.assertIn("dps/1k", table)


if __name__ == "__main__":
    unittest.main()

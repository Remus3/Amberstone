import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import (
    ARENA_TRINKET_IDS,
    DEFAULT_SLOT_COUNT,
    MODE_MAP_ID,
    SORT_KEYS,
    _filter_candidates,
    _is_legal_in_mode,
    _is_purchasable,
    _is_terminal,
    rank_items,
    strip_arena_trinkets,
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


class SharedUniqueFilterTests(unittest.TestCase):
    """Phase 6 step 8 (2026-05-12) — filter candidates whose unique passive
    collides with an item already in current_item_ids.

    The engine's ``collect_effects`` correctly zeroes the duplicate proc/pen
    contribution, but the candidate's stat block still lifts DPS — enough
    that items like Essence Reaver after Trinity Force would still rank
    well on stats alone. Operator-facing this is a bug: the wasted unique
    means worse value-per-gold than a non-redundant item.

    Default filter is ON; ``filter_shared_uniques=False`` opts in to
    surfacing the candidates with ``shares_dead_unique=True`` set.
    """
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_trinity_then_er_filtered_by_default(self) -> None:
        # Aatrox is a Trinity Force user; ER would normally rank well on
        # its stats alone (75 AD + 25% crit + 25% AS + mana). With Trinity
        # already in the build, ER's Spellblade proc is zeroed by
        # collect_effects, so the candidate is dropped from the ranking.
        r = rank_items(
            self.snap, "Aatrox", level=11, target_armor=80,
            current_item_ids=["3078"],  # Trinity Force
            top_n=200,
        )
        ranked_ids = {ri.item_id for ri in r.ranked}
        self.assertNotIn("3508", ranked_ids,  # Essence Reaver
                         "ER shares 'spellblade' key with Trinity — should be filtered")
        # Lich Bane (3100) also shares spellblade — filtered too.
        self.assertNotIn("3100", ranked_ids,
                         "Lich Bane shares 'spellblade' key with Trinity — should be filtered")

    def test_trinity_then_er_surfaces_when_filter_off(self) -> None:
        # filter_shared_uniques=False — ER appears with the flag set so the
        # caller can decide what to do (warn? annotate? suppress?).
        r = rank_items(
            self.snap, "Aatrox", level=11, target_armor=80,
            current_item_ids=["3078"],  # Trinity Force
            top_n=200,
            filter_shared_uniques=False,
        )
        er_rows = [ri for ri in r.ranked if ri.item_id == "3508"]
        self.assertEqual(len(er_rows), 1, "ER should appear when filter is off")
        er = er_rows[0]
        self.assertTrue(er.shares_dead_unique,
                        "ER's shares_dead_unique flag must be True after Trinity")
        self.assertEqual(er.dead_unique_key, "spellblade")

    def test_clean_build_has_no_dead_unique_flags(self) -> None:
        # Naked Aatrox — no current items, no shared uniques possible.
        r = rank_items(
            self.snap, "Aatrox", level=11, target_armor=80, top_n=20,
        )
        for ri in r.ranked:
            self.assertFalse(ri.shares_dead_unique,
                             f"{ri.item_name} flagged dead-unique on naked build")
            self.assertEqual(ri.dead_unique_key, "")

    def test_sterak_then_maw_lifeline_family_filtered(self) -> None:
        # Sterak's Gage (3053) and Maw of Malmortius (3156) both carry
        # unique_passive_key="lifeline" — second one's shield is dead.
        r = rank_items(
            self.snap, "Aatrox", level=11, target_armor=80,
            current_item_ids=["3053"],  # Sterak's Gage
            top_n=200,
        )
        ranked_ids = {ri.item_id for ri in r.ranked}
        self.assertNotIn("3156", ranked_ids,
                         "Maw of Malmortius shares 'lifeline' key with Sterak's — filtered")

    def test_sunfire_then_hollow_radiance_immolate_family_filtered(self) -> None:
        # Both carry unique_passive_key="immolate". Common ARAM tank trap.
        # Use Cho'Gath as a champion that builds these regularly.
        r = rank_items(
            self.snap, "Chogath", level=11, target_armor=80, target_mr=50,
            current_item_ids=["3068"],  # Sunfire Aegis
            top_n=200,
        )
        ranked_ids = {ri.item_id for ri in r.ranked}
        self.assertNotIn("6664", ranked_ids,
                         "Hollow Radiance shares 'immolate' key with Sunfire — filtered")

    def test_to_dict_surfaces_new_fields(self) -> None:
        # Schema regression guard — the HTTP server returns to_dict() so
        # consumers depend on these keys being present.
        r = rank_items(
            self.snap, "Aatrox", level=11, target_armor=80,
            current_item_ids=["3078"],
            filter_shared_uniques=False,
            top_n=5,
        )
        for ri in r.ranked:
            d = ri.to_dict()
            self.assertIn("shares_dead_unique", d)
            self.assertIn("dead_unique_key", d)
            self.assertIsInstance(d["shares_dead_unique"], bool)
            self.assertIsInstance(d["dead_unique_key"], str)


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


class ArenaTrinketFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_arcane_sweeper_id_in_constant(self) -> None:
        self.assertIn("3348", ARENA_TRINKET_IDS)

    def test_strip_noop_outside_arena(self) -> None:
        kept, stripped = strip_arena_trinkets(("3348", "3071"), "SR")
        self.assertEqual(kept, ("3348", "3071"))
        self.assertEqual(stripped, ())

    def test_strip_noop_on_empty(self) -> None:
        self.assertEqual(strip_arena_trinkets((), "ARENA"), ((), ()))

    def test_strip_removes_trinket_in_arena(self) -> None:
        kept, stripped = strip_arena_trinkets(("3348", "3071", "3072"), "ARENA")
        self.assertEqual(kept, ("3071", "3072"))
        self.assertEqual(stripped, ("3348",))

    def test_rank_with_full_arena_inventory_succeeds(self) -> None:
        # 5 real items + Arcane Sweeper = 6 entries; without the strip,
        # rank_items would raise "no room for a new item".
        result = rank_items(
            self.snap, "Aatrox", level=18,
            current_item_ids=["3348", "3071", "3072", "3074", "3031", "3742"],
            mode="ARENA", top_n=3,
        )
        self.assertGreater(len(result.ranked), 0)
        self.assertNotIn("3348", result.current_item_ids)
        self.assertTrue(any("trinket" in n.lower() for n in result.notes))

    def test_rank_baseline_unaffected_by_trinket_inclusion(self) -> None:
        with_trinket = rank_items(
            self.snap, "Aatrox", level=11,
            current_item_ids=["3348", "3071"], mode="ARENA", top_n=1,
        )
        without_trinket = rank_items(
            self.snap, "Aatrox", level=11,
            current_item_ids=["3071"], mode="ARENA", top_n=1,
        )
        self.assertAlmostEqual(
            with_trinket.baseline_dps, without_trinket.baseline_dps, places=3,
        )


if __name__ == "__main__":
    unittest.main()

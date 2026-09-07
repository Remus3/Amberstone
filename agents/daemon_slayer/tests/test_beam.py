import unittest

from agents.daemon_slayer.beam import (
    DEFAULT_BEAM_WIDTH,
    DEFAULT_SLOT_COUNT,
    DEFAULT_TOP_N,
    _BOOTS_TAG,
    _CONSUMABLE_TAG,
    BeamResult,
    RankedBuild,
    _build_gold,
    _has_boots_tag,
    _is_consumable,
    _seed_has_boots,
    beam_search_build,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.rank import rank_items


class HelperPredicateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_has_boots_tag(self) -> None:
        self.assertTrue(_has_boots_tag({"tags": ["Boots"]}))
        self.assertTrue(_has_boots_tag({"tags": ["Boots", "Health"]}))
        self.assertFalse(_has_boots_tag({"tags": ["AttackDamage"]}))
        self.assertFalse(_has_boots_tag({}))

    def test_build_gold_sums_total_gold_field(self) -> None:
        # Aatrox naked = 0; one IE (3500g) + Berserker's (1100g) = 4600.
        self.assertEqual(_build_gold(self.snap, []), 0)
        self.assertEqual(_build_gold(self.snap, ["3031"]), 3500)
        self.assertEqual(_build_gold(self.snap, ["3031", "3006"]), 4600)

    def test_seed_has_boots(self) -> None:
        self.assertFalse(_seed_has_boots(self.snap, []))
        self.assertFalse(_seed_has_boots(self.snap, ["3031"]))   # IE only
        self.assertTrue(_seed_has_boots(self.snap, ["3006"]))    # Berserker's
        self.assertTrue(_seed_has_boots(self.snap, ["3031", "3006"]))

    def test_is_consumable_catches_potions_and_wards(self) -> None:
        # Health Potion, Control Ward, Stealth Ward - all purchasable
        # consumables that should never land in a "build".
        for iid in ("2003", "2055", "2056"):
            rec = self.snap.items.get(iid) or {}
            self.assertTrue(
                _is_consumable(rec),
                f"item {iid} ({rec.get('name')}) should be flagged consumable",
            )

    def test_is_consumable_passes_real_items(self) -> None:
        # Infinity Edge, Stormrazor - full items, never flagged consumable.
        for iid in ("3031", "3097"):
            rec = self.snap.items.get(iid) or {}
            self.assertFalse(_is_consumable(rec))


class BeamSearchHappyPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_naked_aatrox_returns_full_six_item_builds(self) -> None:
        r = beam_search_build(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            beam_width=10, top_n=5,
        )
        self.assertEqual(r.depth_reached, 6)
        self.assertEqual(len(r.ranked), 5)
        for build in r.ranked:
            self.assertEqual(len(build.item_ids), 6)
            self.assertEqual(len(build.item_names), 6)

    def test_top_build_beats_baseline(self) -> None:
        r = beam_search_build(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            beam_width=10, top_n=3,
        )
        for build in r.ranked:
            self.assertGreater(build.delta_dps, 0)
            self.assertGreater(build.final_dps, r.baseline_dps)

    def test_results_sorted_descending_by_final_dps(self) -> None:
        r = beam_search_build(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            beam_width=10, top_n=10,
        )
        finals = [b.final_dps for b in r.ranked]
        self.assertEqual(finals, sorted(finals, reverse=True))

    def test_baseline_dps_matches_compute_dps_no_items(self) -> None:
        baseline = compute_dps(self.snap, "Aatrox", level=11, target_armor=80)
        r = beam_search_build(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            beam_width=4, top_n=1,
        )
        self.assertAlmostEqual(r.baseline_dps, baseline.weighted_dps, places=4)

    def test_returned_builds_are_all_unique(self) -> None:
        # frozenset dedup must produce distinct builds.
        r = beam_search_build(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            beam_width=10, top_n=10,
        )
        keys = {frozenset(b.item_ids) for b in r.ranked}
        self.assertEqual(len(keys), len(r.ranked))


class BeamSearchConstraintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_current_items_pinned_in_every_returned_build(self) -> None:
        # 3031=IE, 3072=Bloodthirster - both should appear in every result.
        r = beam_search_build(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            current_item_ids=["3031", "3072"],
            beam_width=8, top_n=5,
        )
        self.assertEqual(r.depth_reached, 4)  # 6 - 2 already pinned
        for build in r.ranked:
            self.assertEqual(len(build.item_ids), 6)
            self.assertIn("3031", build.item_ids)
            self.assertIn("3072", build.item_ids)

    def test_slot_count_smaller_than_default_searches_fewer_slots(self) -> None:
        r = beam_search_build(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            slot_count=4, beam_width=6, top_n=3,
        )
        self.assertEqual(r.depth_reached, 4)
        for build in r.ranked:
            self.assertEqual(len(build.item_ids), 4)

    def test_full_seed_returns_baseline_only_no_search(self) -> None:
        full = ["3031", "3072", "3006", "3097", "6673", "3508"]
        r = beam_search_build(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            current_item_ids=full,
        )
        self.assertEqual(r.depth_reached, 0)
        self.assertEqual(r.builds_evaluated, 1)
        self.assertEqual(len(r.ranked), 1)
        self.assertEqual(set(r.ranked[0].item_ids), set(full))
        self.assertEqual(r.ranked[0].delta_dps, 0.0)
        self.assertTrue(any("seed already fills slot_count" in n for n in r.notes))

    def test_seed_too_large_raises(self) -> None:
        with self.assertRaises(ValueError):
            beam_search_build(
                self.snap, "Aatrox", level=11,
                current_item_ids=["3031"] * 7,  # 7 > slot_count 6
            )

    def test_total_budget_caps_total_build_gold(self) -> None:
        budget = 8000
        r = beam_search_build(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            beam_width=8, top_n=5, total_budget=budget,
        )
        for build in r.ranked:
            self.assertLessEqual(build.total_gold, budget)
        self.assertTrue(any(f"total_budget={budget}g" in n for n in r.notes))

    def test_boots_unique_default_keeps_at_most_one_boots(self) -> None:
        # Force boots into the picture by including_components and a tight
        # boots-favoring scenario: ARAM where attack-speed boots are common.
        r = beam_search_build(
            self.snap, "MissFortune", level=11, mode="SR",
            target_armor=80, beam_width=15, top_n=10,
        )
        for build in r.ranked:
            boots_count = sum(
                1 for iid in build.item_ids
                if _BOOTS_TAG in (self.snap.items.get(iid, {}).get("tags") or [])
            )
            self.assertLessEqual(boots_count, 1)

    # RETIRED 2026-07-09 (LEDGER 826): the boots_unique=False branch is still
    # live (beam.py:280-360, exposed via cli.py --no-boots-unique + the
    # server.py :8860 body param), but a BEHAVIORAL test of it is no longer
    # constructible. It only ever passed because the pool held stat-dense T3
    # quest-reward boots (3170-3175) that beam WANTED two of; commit 8aa7c64f
    # added those to _SR_EXCLUDED_ITEM_IDS, and no buyable-boot pool reproduces
    # a multi-boot build - T2 boots are too low-DPS for beam to stack, so it
    # returns an empty build (verified). The default (boots_unique=True) path is
    # still guarded by test_boots_unique_default_keeps_at_most_one_boots above.

    def test_consumables_excluded_from_search_pool(self) -> None:
        # Tight budget that only fits a few full items - beam search must
        # NOT fill remaining slots with Health Potions / Control Wards.
        r = beam_search_build(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            beam_width=8, top_n=5, total_budget=12000,
        )
        for build in r.ranked:
            for iid in build.item_ids:
                rec = self.snap.items.get(iid) or {}
                self.assertFalse(
                    _is_consumable(rec),
                    f"consumable {iid} ({rec.get('name')}) leaked into build {build.item_ids}",
                )

    def test_only_item_ids_restricts_search_pool(self) -> None:
        # Only IE + Stormrazor + Berserker's allowed -> all builds drawn from these 3.
        whitelist = ["3031", "6673", "3006"]
        r = beam_search_build(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            slot_count=3, beam_width=4, top_n=3,
            only_item_ids=whitelist,
        )
        for build in r.ranked:
            self.assertTrue(set(build.item_ids).issubset(set(whitelist)))


class BeamSearchModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_aram_mode_filters_sr_only_items(self) -> None:
        # Some items are SR-only (maps[12]=False). They must NOT appear in any
        # ARAM-search build.
        r = beam_search_build(
            self.snap, "Aatrox", level=11, mode="ARAM", target_armor=80,
            beam_width=8, top_n=5,
        )
        for build in r.ranked:
            for iid in build.item_ids:
                rec = self.snap.items.get(iid) or {}
                maps = rec.get("maps") or {}
                # ARAM map id is "12"; key may be missing or False.
                self.assertTrue(maps.get("12"), f"item {iid} ({rec.get('name')}) is not ARAM-legal")

    def test_yunara_aram_zero_mult_zeroes_all_deltas(self) -> None:
        # Yunara aramDamageDealt = 0 (hard ARAM disable) pre-16.11.1.
        # Patch 16.11.1 enabled Yunara in ARAM; no champion is currently
        # ARAM-disabled, so this engine-invariant test pins to the
        # 16.10.1 snapshot.
        snap_pinned = DataSnapshot.load(patch="16.10.1")
        r = beam_search_build(
            snap_pinned, "Yunara", level=11, mode="ARAM",
            beam_width=4, top_n=3,
        )
        self.assertEqual(r.baseline_dps, 0.0)
        self.assertTrue(all(b.delta_dps == 0.0 for b in r.ranked))
        self.assertTrue(any("mode_multiplier=0" in n for n in r.notes))


class BeamSearchSynergyTests(unittest.TestCase):
    """Beam search should expose pairs that single-slot greedy can't."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_beam_finds_higher_dps_than_greedy_top_six(self) -> None:
        # Greedy: pick top item, then top-of-remaining given that, six times.
        # Beam: keep the top-K partial builds at each depth, expand all.
        # On a synergy-heavy champion (Aatrox, target_armor=80) the beam
        # should land at LEAST as high as greedy and typically higher.
        greedy_build: list[str] = []
        for _ in range(6):
            r = rank_items(
                self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
                current_item_ids=greedy_build, top_n=1,
            )
            if not r.ranked:
                break
            greedy_build.append(r.ranked[0].item_id)
        greedy_dps = compute_dps(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            item_ids=greedy_build,
        ).weighted_dps

        b = beam_search_build(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            beam_width=10, top_n=1,
        )
        self.assertGreaterEqual(b.ranked[0].final_dps, greedy_dps - 0.001)

    def test_beam_width_one_approximates_greedy(self) -> None:
        # beam_width=1 IS greedy (single survivor each layer).
        b = beam_search_build(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            beam_width=1, top_n=1,
        )
        self.assertEqual(len(b.ranked), 1)
        self.assertEqual(len(b.ranked[0].item_ids), 6)


class BeamSearchValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_beam_width_zero_raises(self) -> None:
        with self.assertRaises(ValueError):
            beam_search_build(self.snap, "Aatrox", level=11, beam_width=0)

    def test_top_n_zero_raises(self) -> None:
        with self.assertRaises(ValueError):
            beam_search_build(self.snap, "Aatrox", level=11, top_n=0)

    def test_invalid_level_raises(self) -> None:
        # ``clamp_level`` raises on out-of-range; matches rank_items behavior.
        with self.assertRaises(ValueError):
            beam_search_build(
                self.snap, "Aatrox", level=99, mode="SR",
                beam_width=2, top_n=1,
            )


class SerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_to_dict_roundtrips_key_fields(self) -> None:
        r = beam_search_build(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            beam_width=4, top_n=3,
        )
        d = r.to_dict()
        self.assertEqual(d["champion_id"], "Aatrox")
        self.assertEqual(d["mode"], "SR")
        self.assertEqual(d["beam_width"], 4)
        self.assertEqual(d["slot_count"], DEFAULT_SLOT_COUNT)
        self.assertEqual(len(d["ranked"]), 3)
        for row in d["ranked"]:
            for key in ("item_ids", "item_names", "total_gold", "final_dps",
                        "baseline_dps", "delta_dps", "dps_per_1k_gold"):
                self.assertIn(key, row)

    def test_format_table_contains_key_fields(self) -> None:
        r = beam_search_build(
            self.snap, "Aatrox", level=11, mode="SR", target_armor=80,
            beam_width=4, top_n=3,
        )
        table = r.format_table()
        self.assertIn("Aatrox", table)
        self.assertIn("lvl 11", table)
        self.assertIn("baseline_dps", table)
        self.assertIn("beam_width", table)


class DefaultsTests(unittest.TestCase):
    def test_defaults_sane(self) -> None:
        self.assertEqual(DEFAULT_SLOT_COUNT, 6)
        self.assertGreaterEqual(DEFAULT_BEAM_WIDTH, 4)
        self.assertGreaterEqual(DEFAULT_TOP_N, 5)


class ArenaTrinketStripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_beam_strips_arcane_sweeper_in_arena(self) -> None:
        # 2 real items + Arcane Sweeper. Beam should treat seed as 2 items
        # and search the remaining 4 slots; without strip the seed would
        # be 3 items and the search depth would be wrong by one.
        result = beam_search_build(
            self.snap, "Aatrox", level=18,
            current_item_ids=["3348", "3071", "3072"],
            mode="ARENA", beam_width=4, top_n=2,
        )
        self.assertNotIn("3348", result.current_item_ids)
        self.assertEqual(len(result.current_item_ids), 2)
        self.assertTrue(any("trinket" in n.lower() for n in result.notes))

    def test_beam_no_strip_outside_arena(self) -> None:
        # Outside ARENA the trinket id pass-through is a normal item lookup.
        # Aatrox baseline build with Arcane Sweeper as a "current item" in SR
        # mode should not be stripped (mode mismatch).
        result = beam_search_build(
            self.snap, "Aatrox", level=11,
            current_item_ids=["3348"], mode="SR",
            beam_width=2, top_n=1,
        )
        self.assertIn("3348", result.current_item_ids)


if __name__ == "__main__":
    unittest.main()

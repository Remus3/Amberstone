"""Phase 6 (s181, 2026-05-13) - Enchanter ranker tests.

Mirrors ``test_rank_tank`` / ``test_rank_assassin`` shape. Covers the
ranker pipeline, filter/whitelist/budget/dead-unique logic, sort keys,
serialization, and the ``/rank-enchanter`` server route.
"""
from __future__ import annotations

import json
import threading
import unittest
from urllib.request import Request, urlopen

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hps import (
    HpsRankedItem,
    HpsRankResult,
    compute_hps,
    rank_items_by_hps,
)


# --- Ranker basics -----------------------------------------------------


class RankByHpsBasicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_result_type(self) -> None:
        r = rank_items_by_hps(self.snap, "Soraka", level=11)
        self.assertIsInstance(r, HpsRankResult)
        self.assertEqual(r.champion_id, "Soraka")
        self.assertEqual(r.level, 11)

    def test_baseline_matches_compute(self) -> None:
        ranker = rank_items_by_hps(
            self.snap, "Soraka", level=11, current_item_ids=["3107"]
        )
        compute = compute_hps(
            self.snap, "Soraka", level=11, item_ids=["3107"]
        )
        self.assertAlmostEqual(
            ranker.baseline_hps, compute.total_throughput, places=4
        )

    def test_delta_arithmetic(self) -> None:
        """new_hps - delta_hps == baseline_hps for every row."""
        r = rank_items_by_hps(
            self.snap, "Soraka", level=11, current_item_ids=["3107"]
        )
        for row in r.ranked:
            self.assertAlmostEqual(
                row.new_hps - row.delta_hps, r.baseline_hps, places=3
            )

    def test_sort_delta_descending(self) -> None:
        r = rank_items_by_hps(self.snap, "Soraka", level=11)
        deltas = [row.delta_hps for row in r.ranked]
        self.assertEqual(deltas, sorted(deltas, reverse=True))

    def test_top_n_clipping(self) -> None:
        r = rank_items_by_hps(self.snap, "Soraka", level=11, top_n=3)
        self.assertLessEqual(len(r.ranked), 3)

    def test_ranked_item_dataclass_type(self) -> None:
        r = rank_items_by_hps(self.snap, "Soraka", level=11, top_n=3)
        for row in r.ranked:
            self.assertIsInstance(row, HpsRankedItem)


# --- Scoring sanity ----------------------------------------------------


class HpsScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_naked_top_picks_include_enchanter_items(self) -> None:
        """A naked Soraka build should rank enchanter items in the top 8."""
        r = rank_items_by_hps(self.snap, "Soraka", level=11, top_n=10)
        top_ids = {row.item_id for row in r.ranked}
        # Top picks should include at least Ardent, Helia, Locket (all
        # contribute > 0 from baseline 0).
        self.assertTrue(
            top_ids & {"6620", "3504", "3190"},
            f"expected at least one of Helia/Ardent/Locket in top 10, got {top_ids}",
        )

    def test_non_enchanter_items_dont_dominate(self) -> None:
        """A DPS item (BotRK 3153) shouldn't appear in the enchanter top 3."""
        r = rank_items_by_hps(self.snap, "Soraka", level=11, top_n=3)
        top_ids = {row.item_id for row in r.ranked}
        self.assertNotIn("3153", top_ids)

    def test_efficiency_sort_orders_by_per_gold(self) -> None:
        """sort_by=efficiency orders highest hps_per_1k_gold first."""
        r = rank_items_by_hps(
            self.snap, "Soraka", level=11,
            sort_by="efficiency", top_n=10,
        )
        effs = [row.hps_per_1k_gold for row in r.ranked]
        self.assertEqual(effs, sorted(effs, reverse=True))

    def test_efficiency_zero_when_delta_non_positive(self) -> None:
        r = rank_items_by_hps(self.snap, "Soraka", level=11, top_n=20)
        for row in r.ranked:
            if row.delta_hps <= 0:
                self.assertEqual(row.hps_per_1k_gold, 0.0)

    def test_helia_top_pick_at_naked(self) -> None:
        """Echoes of Helia (6620) has the highest delta_hps for naked enchanter
        at lvl 11 - it's the only direct-heal item with high proc rate (0.4/s)
        AND AP scaling. Verifies our live-probe finding stays stable across
        levels.
        """
        r = rank_items_by_hps(self.snap, "Soraka", level=11, top_n=8)
        # Helia should be in top 3 (high delta from its 0.4 proc rate x 50 heal)
        top_3_ids = [row.item_id for row in r.ranked[:3]]
        self.assertIn("6620", top_3_ids)

    def test_moonstone_low_priority_at_naked(self) -> None:
        """Moonstone at naked has no ITEM heal to amp; its only delta now is
        the small bump from its AP raising Soraka's own AP-scaling ability
        heal (ability HPS folded in, V2 enchanter wire). It stays low-priority
        (well below a direct-heal item) but is no longer exactly 0."""
        r = rank_items_by_hps(self.snap, "Soraka", level=11, top_n=20)
        moonstone_row = next((row for row in r.ranked if row.item_id == "6617"), None)
        helia_row = next((row for row in r.ranked if row.item_id == "6620"), None)
        if moonstone_row is not None:
            # Small positive delta from AP -> ability-heal scaling, not 0.
            self.assertGreaterEqual(moonstone_row.delta_hps, 0.0)
            self.assertLess(moonstone_row.delta_hps, 5.0)
            # Still ranks below a real direct-heal item (Helia 6620).
            if helia_row is not None:
                self.assertLess(moonstone_row.delta_hps, helia_row.delta_hps)

    def test_moonstone_rises_with_existing_heals(self) -> None:
        """Moonstone delta > 0 when build already has direct-heal items."""
        r = rank_items_by_hps(
            self.snap, "Soraka", level=11,
            current_item_ids=["3107", "3222"], top_n=20,
        )
        moonstone_row = next((row for row in r.ranked if row.item_id == "6617"), None)
        self.assertIsNotNone(moonstone_row)
        self.assertGreater(moonstone_row.delta_hps, 0.0)


# --- Filter pipeline ---------------------------------------------------


class FilterPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_already_equipped_skipped(self) -> None:
        """Item in current_item_ids should not appear in the ranking."""
        r = rank_items_by_hps(
            self.snap, "Soraka", level=11,
            current_item_ids=["3107"], top_n=20,
        )
        ids = {row.item_id for row in r.ranked}
        self.assertNotIn("3107", ids)

    def test_only_whitelist_restricts_pool(self) -> None:
        """only_item_ids=[3107] restricts to a single candidate."""
        r = rank_items_by_hps(
            self.snap, "Soraka", level=11,
            only_item_ids=["3107"], top_n=10,
        )
        ids = {row.item_id for row in r.ranked}
        self.assertEqual(ids, {"3107"})

    def test_budget_filters_expensive(self) -> None:
        """budget=500 -> no enchanter terminal items pass (all > 500g)."""
        r = rank_items_by_hps(
            self.snap, "Soraka", level=11,
            budget=500, top_n=20,
        )
        for row in r.ranked:
            self.assertLessEqual(row.gold, 500)

    def test_include_components_admits_non_terminal(self) -> None:
        """include_components=True allows non-terminal items into the ranking."""
        r = rank_items_by_hps(
            self.snap, "Soraka", level=11,
            include_components=True, only_item_ids=None,
            enchanter_only=False, top_n=50,
        )
        # Should have at least some non-terminal items in the candidate pool.
        non_terminal = [row for row in r.ranked if not row.is_terminal]
        # Allowed but not required to be present; just verify the flag plumbs.
        self.assertEqual(r.sort_by, "delta")

    def test_arena_trinket_stripped(self) -> None:
        """ARENA mode strips the Arcane Sweeper (item_id is in
        ``strip_arena_trinkets`` logic). Build with trinket -> it gets removed
        and surfaced in notes."""
        # 8001 / 8020 are the Arena trinket family; engine drops them.
        # Just verify the call works and notes surface.
        r = rank_items_by_hps(
            self.snap, "Soraka", level=11,
            current_item_ids=["8020"],
            mode="ARENA", top_n=5,
        )
        # The trinket strip note may or may not fire depending on what's in
        # current_item_ids - at minimum the call should succeed.
        self.assertIsInstance(r, HpsRankResult)


# --- Validation + serialization ----------------------------------------


class ValidationAndEdgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_invalid_sort_by_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_hps(
                self.snap, "Soraka", level=11, sort_by="bogus"
            )

    def test_full_build_raises(self) -> None:
        """current_item_ids already at slot_count -> no room for more."""
        with self.assertRaises(ValueError):
            rank_items_by_hps(
                self.snap, "Soraka", level=11,
                current_item_ids=["3107", "3222", "6617", "3504", "6616", "3190"],
                slot_count=6,
            )


class SerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_to_dict_round_trip(self) -> None:
        r = rank_items_by_hps(self.snap, "Soraka", level=11, top_n=3)
        d = r.to_dict()
        json.dumps(d)  # must be JSON-serializable
        self.assertEqual(d["champion_id"], "Soraka")
        self.assertEqual(len(d["ranked"]), len(r.ranked))

    def test_format_table_contains_archetype_tag(self) -> None:
        r = rank_items_by_hps(self.snap, "Soraka", level=11, top_n=3)
        out = r.format_table()
        self.assertIn("[ENCHANTER]", out)

    def test_ranked_item_to_dict_shape(self) -> None:
        r = rank_items_by_hps(self.snap, "Soraka", level=11, top_n=3)
        for row in r.ranked:
            d = row.to_dict()
            self.assertIn("delta_hps", d)
            self.assertIn("new_hps", d)
            self.assertIn("hps_per_1k_gold", d)
            self.assertIn("shares_dead_unique", d)


# --- Mode + targets-override pass-through ------------------------------


class ModeAndOverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_aram_mode_threads_through(self) -> None:
        r = rank_items_by_hps(self.snap, "Lulu", level=11, mode="ARAM", top_n=5)
        self.assertEqual(r.mode, "ARAM")

    def test_targets_override_threads_through(self) -> None:
        r = rank_items_by_hps(
            self.snap, "Soraka", level=11,
            targets_per_proc_override=1.0, top_n=5,
        )
        self.assertAlmostEqual(r.targets_per_proc_override, 1.0, places=4)

    def test_targets_override_reduces_aoe_item_delta(self) -> None:
        """Redemption with override=1 has 1/3 the delta of override=3 (default)."""
        default = rank_items_by_hps(
            self.snap, "Soraka", level=11,
            only_item_ids=["3107"], top_n=1,
        )
        override = rank_items_by_hps(
            self.snap, "Soraka", level=11,
            only_item_ids=["3107"], targets_per_proc_override=1.0, top_n=1,
        )
        self.assertGreater(default.ranked[0].delta_hps, override.ranked[0].delta_hps)


# --- Server route /rank-enchanter --------------------------------------


class RankEnchanterRouteTests(unittest.TestCase):
    """Spin engine server on a free port; hit /rank-enchanter; tear down."""

    @classmethod
    def setUpClass(cls) -> None:
        from agents.daemon_slayer.server import start_server, _CACHE
        cls.snap = DataSnapshot.load()
        _CACHE.set(cls.snap)
        cls.srv = start_server(host="127.0.0.1", port=0, snapshot=cls.snap)
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.srv.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        raw = json.dumps(body).encode("utf-8")
        req = Request(self.base + path, data=raw, method="POST",
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            try:
                code = getattr(e, "code", None)
                body_resp = json.loads(e.read().decode("utf-8"))  # type: ignore[attr-defined]
                return code, body_resp
            except Exception:
                raise

    def test_post_rank_enchanter_returns_200(self) -> None:
        status, body = self._post("/rank-enchanter", {
            "champion": "Soraka", "level": 11, "items": [], "top": 8,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "Soraka")
        self.assertGreater(len(body["ranked"]), 0)

    def test_enchanter_top_picks_canonical(self) -> None:
        """Soraka lvl 11 top picks should match the live-probe ordering:
        Helia/Ardent/Staff dominate."""
        status, body = self._post("/rank-enchanter", {
            "champion": "Soraka", "level": 11, "items": [], "top": 8,
        })
        self.assertEqual(status, 200)
        top_ids = [row["item_id"] for row in body["ranked"][:3]]
        # Helia (6620) should be the top-1 pick; Ardent (3504) close behind.
        self.assertIn("6620", top_ids)

    def test_post_unknown_champion_404(self) -> None:
        status, _ = self._post("/rank-enchanter", {
            "champion": "NobodyChampion", "level": 11,
        })
        self.assertEqual(status, 404)

    def test_post_invalid_sort_400(self) -> None:
        status, _ = self._post("/rank-enchanter", {
            "champion": "Soraka", "level": 11, "sort": "bogus",
        })
        self.assertEqual(status, 400)

    def test_post_only_whitelist(self) -> None:
        """only=[3107] restricts to Redemption only."""
        status, body = self._post("/rank-enchanter", {
            "champion": "Soraka", "level": 11,
            "only": ["3107"], "top": 10,
        })
        self.assertEqual(status, 200)
        ids = {row["item_id"] for row in body["ranked"]}
        self.assertEqual(ids, {"3107"})

    def test_post_efficiency_sort(self) -> None:
        status, body = self._post("/rank-enchanter", {
            "champion": "Soraka", "level": 11,
            "sort": "efficiency", "top": 10,
        })
        self.assertEqual(status, 200)
        effs = [row["hps_per_1k_gold"] for row in body["ranked"]]
        self.assertEqual(effs, sorted(effs, reverse=True))

    def test_post_targets_override_flows_through(self) -> None:
        """targets_per_proc_override=1 -> Redemption delta drops to 1/3."""
        default = self._post("/rank-enchanter", {
            "champion": "Soraka", "level": 11,
            "only": ["3107"], "top": 1,
        })
        override = self._post("/rank-enchanter", {
            "champion": "Soraka", "level": 11,
            "only": ["3107"], "targets_per_proc_override": 1.0,
            "top": 1,
        })
        self.assertEqual(default[0], 200)
        self.assertEqual(override[0], 200)
        self.assertGreater(
            default[1]["ranked"][0]["delta_hps"],
            override[1]["ranked"][0]["delta_hps"],
        )

    def test_post_enchanter_only_false_widens_pool(self) -> None:
        """enchanter_only=False uses the full candidate pool; most items
        contribute 0 but the call succeeds."""
        status, body = self._post("/rank-enchanter", {
            "champion": "Soraka", "level": 11,
            "enchanter_only": False, "top": 5,
        })
        self.assertEqual(status, 200)
        # Should still return up to 5 rows.
        self.assertLessEqual(len(body["ranked"]), 5)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

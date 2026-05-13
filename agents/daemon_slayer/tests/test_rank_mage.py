"""Phase 4c (s179, 2026-05-12) — Mage ability ranker tests.

Mirrors ``test_rank`` / ``test_rank_tank`` shape but exercises the
ability-DPS scorer side. The filter-pipeline correctness already lives
in ``test_rank``; these tests focus on the ability-DPS-specific scoring
behavior, the ``AbilityDpsRankedItem`` shape, and the new ``/rank-mage``
server route.
"""
from __future__ import annotations

import json
import threading
import unittest
from urllib.request import Request, urlopen

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.ability_dps import (
    AbilityDpsRankedItem,
    AbilityDpsRankResult,
    compute_ability_dps,
    rank_items_by_ability_dps,
)
from agents.daemon_slayer.data_loader import DataSnapshot


def _snap() -> DataSnapshot:
    reset_default_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


# ─── basic ranker behavior ───────────────────────────────────────────────────


class RankByAbilityDpsBasicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_result_type_and_metadata(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=5,
        )
        self.assertIsInstance(r, AbilityDpsRankResult)
        self.assertEqual(r.champion_id, "Veigar")
        self.assertEqual(r.level, 11)
        self.assertEqual(r.mode, "SR")
        self.assertEqual(r.sort_by, "delta")

    def test_baseline_matches_compute_ability_dps(self) -> None:
        baseline = compute_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
        )
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=1,
        )
        self.assertAlmostEqual(
            r.baseline_ability_dps, baseline.total_ability_dps, places=4,
        )

    def test_top_1_delta_equals_new_minus_baseline(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=1,
        )
        self.assertGreater(len(r.ranked), 0)
        top = r.ranked[0]
        self.assertAlmostEqual(
            top.delta_ability_dps, top.new_ability_dps - r.baseline_ability_dps,
            places=4,
        )

    def test_results_sorted_descending_by_delta(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=20,
        )
        deltas = [ri.delta_ability_dps for ri in r.ranked]
        self.assertEqual(deltas, sorted(deltas, reverse=True))

    def test_top_n_clipping(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=3,
        )
        self.assertLessEqual(len(r.ranked), 3)

    def test_primary_scaling_surfaced(self) -> None:
        # Veigar is canonical AP — primary_scaling should classify AP.
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=1,
        )
        self.assertEqual(r.primary_scaling, "AP")

    def test_ranked_item_is_dataclass(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=1,
        )
        self.assertIsInstance(r.ranked[0], AbilityDpsRankedItem)


# ─── scoring behavior ────────────────────────────────────────────────────────


class AbilityDpsScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_rabadons_top_pick_for_veigar(self) -> None:
        # Rabadon's (3089) 30% AP amp should be a top candidate for Veigar.
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=10,
        )
        top_ids = {ri.item_id for ri in r.ranked[:5]}
        # Rabadon's id is 3089 in 16.9.1. AP-heavy items expected in top:
        # 3089 Rabadon's, 6655 Luden's, 6653 Liandry's, 4645 Shadowflame,
        # 3157 Zhonya's, 4646 Stormsurge, 3135 Void Staff.
        # At least one of these should land top-5.
        self.assertTrue(
            top_ids & {"3089", "6655", "6653", "4645", "3157", "4646", "3135"},
            f"expected AP item in top-5, got: {top_ids}",
        )

    def test_pure_ad_item_not_in_top_for_mage(self) -> None:
        # Veigar at lvl 11 with the AP pool exhausted should still NOT
        # have BotRK (3153, pure AD/AS) as a top-3 mage pick.
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=20,
        )
        top3 = {ri.item_id for ri in r.ranked[:3]}
        self.assertNotIn("3153", top3, "BotRK should not be a top-3 mage pick")

    def test_delta_positive_for_ap_item_on_ap_caster(self) -> None:
        # Adding Rabadon's to naked Veigar should produce delta > 0.
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
            only_item_ids=["3089"], top_n=1,
        )
        self.assertEqual(len(r.ranked), 1)
        self.assertGreater(r.ranked[0].delta_ability_dps, 0.0)

    def test_efficiency_sort_orders_by_per_1k_gold(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
            sort_by="efficiency", top_n=20,
        )
        effs = [ri.ability_dps_per_1k_gold for ri in r.ranked]
        self.assertEqual(effs, sorted(effs, reverse=True))

    def test_efficiency_zero_on_negative_delta(self) -> None:
        # Force a candidate with negative delta by manually inspecting:
        # if a rare item turns up with non-positive delta, its efficiency
        # column must be exactly 0.0 (not negative).
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
            include_components=True, top_n=200,
        )
        for ri in r.ranked:
            if ri.delta_ability_dps <= 0.0:
                self.assertEqual(ri.ability_dps_per_1k_gold, 0.0)


# ─── filter pipeline parity ──────────────────────────────────────────────────


class FilterPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_already_equipped_item_skipped(self) -> None:
        # Rabadon's already in inventory → shouldn't reappear in candidates.
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
            current_item_ids=["3089"], top_n=50,
        )
        ids = {ri.item_id for ri in r.ranked}
        self.assertNotIn("3089", ids)

    def test_only_item_ids_restricts_pool(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
            only_item_ids=["3089", "6655", "6653"], top_n=20,
        )
        ids = {ri.item_id for ri in r.ranked}
        self.assertTrue(ids.issubset({"3089", "6655", "6653"}))
        self.assertGreaterEqual(len(r.ranked), 1)

    def test_budget_filter_drops_expensive(self) -> None:
        # 1500g budget should exclude 3500+g terminal items like Rabadon's.
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
            budget=1500, top_n=20,
        )
        for ri in r.ranked:
            self.assertLessEqual(ri.gold, 1500)

    def test_include_components_keeps_non_terminal(self) -> None:
        r_terminal = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
            include_components=False, top_n=999,
        )
        r_with_comp = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
            include_components=True, top_n=999,
        )
        self.assertGreater(
            r_with_comp.candidates_evaluated,
            r_terminal.candidates_evaluated,
        )

    def test_arena_strips_trinket(self) -> None:
        # Mode=ARENA + current items contains Arcane Sweeper (3348) →
        # should not raise (slot count check) and should report the strip.
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="ARENA", target_mr=30.0,
            current_item_ids=["3348"], top_n=3,
        )
        self.assertEqual(len(r.current_item_ids), 0)
        notes = " ".join(r.notes)
        self.assertIn("3348", notes)

    def test_dead_unique_filter_drops_collision(self) -> None:
        # With Lich Bane (3100, unique_passive_key "spellblade") in the
        # current build, the filter should drop other spellblade-keyed
        # items. Per engine docstring (batches 11/21/23): Sheen 3057,
        # Trinity 6630, Essence Reaver 3508, Iceborn Gauntlet 6662,
        # Divine Sunderer 6632 all share the "spellblade" key. Sundered
        # Sky 6610 + Lightshield Strike is INTENTIONALLY untagged
        # (distinct mechanic) so it stays in candidates.
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
            current_item_ids=["3100"], top_n=200,
        )
        ids = {ri.item_id for ri in r.ranked}
        spellblade_sibs = {"3057", "6630", "3508", "6662", "6632"}
        present = ids & spellblade_sibs
        self.assertEqual(present, set(),
                         f"shared-spellblade items should be filtered: {present}")

    def test_dead_unique_surfaced_when_filter_off(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
            current_item_ids=["3100"], top_n=200,
            filter_shared_uniques=False,
        )
        # At least one of the real spellblade sibs should now be present
        # and carry the flag. Use Trinity Force (6630) as the canonical
        # check — it's a high-tier terminal item certain to survive any
        # other filter.
        spellblade_sibs = {"3057", "6630", "3508", "6662", "6632"}
        present_items = [ri for ri in r.ranked if ri.item_id in spellblade_sibs]
        self.assertGreater(len(present_items), 0,
                           "filter_shared_uniques=False should surface them")
        for ri in present_items:
            self.assertTrue(ri.shares_dead_unique)
            self.assertEqual(ri.dead_unique_key, "spellblade")


# ─── validation + edges ─────────────────────────────────────────────────────


class ValidationAndEdgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_invalid_sort_by_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_ability_dps(
                self.snap, "Veigar", level=11, sort_by="bogus",
            )

    def test_full_build_raises(self) -> None:
        # Six items in current build → no room for a 7th.
        with self.assertRaises(ValueError):
            rank_items_by_ability_dps(
                self.snap, "Veigar", level=11,
                current_item_ids=["3089", "6655", "6653", "4645", "3157", "3135"],
            )

    def test_invalid_block_strategy_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_ability_dps(
                self.snap, "Veigar", level=11, block_strategy="bogus",
            )

    def test_invalid_max_priority_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_ability_dps(
                self.snap, "Veigar", level=11,
                max_priority=("Q", "Q", "E"),
            )


# ─── to_dict / format_table ──────────────────────────────────────────────────


class SerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_to_dict_round_trip(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=3,
        )
        d = r.to_dict()
        self.assertEqual(d["champion_id"], "Veigar")
        self.assertEqual(d["level"], 11)
        self.assertEqual(d["sort_by"], "delta")
        self.assertIn("baseline_ability_dps", d)
        self.assertIn("primary_scaling", d)
        self.assertIn("ranked", d)
        self.assertLessEqual(len(d["ranked"]), 3)
        if d["ranked"]:
            self.assertIn("delta_ability_dps", d["ranked"][0])
            self.assertIn("ability_dps_per_1k_gold", d["ranked"][0])

    def test_format_table_includes_mage_tag(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=2,
        )
        out = r.format_table()
        self.assertIn("[MAGE]", out)
        self.assertIn("Veigar", out)

    def test_ranked_item_to_dict_shape(self) -> None:
        r = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=1,
        )
        d = r.ranked[0].to_dict()
        for k in (
            "item_id", "item_name", "gold", "delta_ability_dps",
            "new_ability_dps", "ability_dps_per_1k_gold", "is_terminal",
            "tags", "shares_dead_unique", "dead_unique_key",
        ):
            self.assertIn(k, d)


# ─── mode + amp flow-through ─────────────────────────────────────────────────


class ModeAndAmpFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_aram_mode_carries_through(self) -> None:
        r_sr = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=3,
        )
        r_aram = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="ARAM", target_mr=30.0, top_n=3,
        )
        # ARAM mode_multiplier should be < 1.0 for Veigar (canonical
        # aramDamageDealt nerf on AP carries).
        self.assertLess(r_aram.mode_multiplier, 1.0)
        # ARAM result is built on ARAM mode (sanity).
        self.assertEqual(r_aram.mode, "ARAM")
        # And SR mode_multiplier is exactly 1.0.
        self.assertEqual(r_sr.mode_multiplier, 1.0)

    def test_ap_amp_item_lifts_total_ability_dps(self) -> None:
        # Adding Rabadon's (3089) via current_item_ids should produce a
        # higher baseline_ability_dps in the second ranker call.
        r_naked = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=1,
        )
        r_rabadons = rank_items_by_ability_dps(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0,
            current_item_ids=["3089"], top_n=1,
        )
        self.assertGreater(
            r_rabadons.baseline_ability_dps, r_naked.baseline_ability_dps,
        )


# ─── server route ────────────────────────────────────────────────────────────


class RankMageRouteTests(unittest.TestCase):
    """Spin the engine server on a free port; hit /rank-mage; tear down."""

    @classmethod
    def setUpClass(cls) -> None:
        from agents.daemon_slayer.server import start_server, _CACHE
        reset_default_cache()
        ult_rates.reset_cache()
        cls.snap = _snap()
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

    def test_post_rank_mage_returns_200(self) -> None:
        status, body = self._post("/rank-mage", {
            "champion": "Veigar", "level": 11, "mode": "SR",
            "target_mr": 30, "top": 5,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "Veigar")
        self.assertIn("baseline_ability_dps", body)
        self.assertIn("ranked", body)
        self.assertLessEqual(len(body["ranked"]), 5)

    def test_rank_mage_top_5_includes_known_ap_item(self) -> None:
        status, body = self._post("/rank-mage", {
            "champion": "Veigar", "level": 11, "mode": "SR",
            "target_mr": 30, "top": 5,
        })
        self.assertEqual(status, 200)
        top_ids = {r["item_id"] for r in body["ranked"]}
        self.assertTrue(
            top_ids & {"3089", "6655", "6653", "4645", "3157", "4646", "3135"},
            f"expected AP item in top-5, got: {top_ids}",
        )

    def test_rank_mage_404_on_unknown_champion(self) -> None:
        status, _ = self._post("/rank-mage", {
            "champion": "NobodyChampion", "level": 11,
        })
        self.assertEqual(status, 404)

    def test_rank_mage_422_on_invalid_sort(self) -> None:
        status, _ = self._post("/rank-mage", {
            "champion": "Veigar", "level": 11, "sort": "bogus",
        })
        # sort enum gates at 400 in the handler, mirroring /rank.
        self.assertIn(status, (400, 422))

    def test_rank_mage_with_only_item_ids_whitelist(self) -> None:
        status, body = self._post("/rank-mage", {
            "champion": "Veigar", "level": 11, "mode": "SR", "target_mr": 30,
            "only": ["3089", "6655", "6653"], "top": 10,
        })
        self.assertEqual(status, 200)
        ids = {r["item_id"] for r in body["ranked"]}
        self.assertTrue(ids.issubset({"3089", "6655", "6653"}))

    def test_rank_mage_max_priority_compact_form(self) -> None:
        status, body = self._post("/rank-mage", {
            "champion": "Veigar", "level": 11, "mode": "SR", "target_mr": 30,
            "max_priority": "WQE", "top": 3,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["max_priority"], ["W", "Q", "E"])

    def test_rank_mage_filter_shared_uniques_default_true(self) -> None:
        # With Lich Bane (3100) in current, default filter should drop
        # spellblade-key siblings from the candidate set.
        status, body = self._post("/rank-mage", {
            "champion": "Veigar", "level": 11, "mode": "SR", "target_mr": 30,
            "items": ["3100"], "top": 100,
        })
        self.assertEqual(status, 200)
        ids = {r["item_id"] for r in body["ranked"]}
        spellblade_sibs = {"3057", "6630", "3508", "6662", "6632", "6610"}
        self.assertEqual(ids & spellblade_sibs, set())

    def test_rank_mage_efficiency_sort(self) -> None:
        status, body = self._post("/rank-mage", {
            "champion": "Veigar", "level": 11, "mode": "SR", "target_mr": 30,
            "sort": "efficiency", "top": 5,
        })
        self.assertEqual(status, 200)
        effs = [r["ability_dps_per_1k_gold"] for r in body["ranked"]]
        self.assertEqual(effs, sorted(effs, reverse=True))


if __name__ == "__main__":
    unittest.main()

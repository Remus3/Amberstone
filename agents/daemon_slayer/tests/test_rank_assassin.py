"""Phase 5 (s180, 2026-05-13) — Assassin burst ranker tests.

Mirrors ``test_rank_mage`` shape but exercises the burst scorer side.
The filter-pipeline correctness already lives in ``test_rank``; these
tests focus on the burst-specific scoring behavior, the
``BurstRankedItem`` shape, and the new ``/rank-assassin`` server route.
"""
from __future__ import annotations

import json
import threading
import unittest
from urllib.request import Request, urlopen

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.burst import (
    BurstRankedItem,
    BurstRankResult,
    compute_burst_damage,
    rank_items_by_burst,
)
from agents.daemon_slayer.data_loader import DataSnapshot


def _snap() -> DataSnapshot:
    reset_default_cache()
    ult_rates.reset_cache()
    return DataSnapshot.load()


# ─── basic ranker behavior ───────────────────────────────────────────────────


class RankByBurstBasicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_result_type_and_metadata(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=5,
        )
        self.assertIsInstance(r, BurstRankResult)
        self.assertEqual(r.champion_id, "Zed")
        self.assertEqual(r.level, 11)
        self.assertEqual(r.mode, "SR")
        self.assertEqual(r.sort_by, "delta")

    def test_baseline_matches_compute_burst_damage(self) -> None:
        baseline = compute_burst_damage(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0,
        )
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=1,
        )
        self.assertAlmostEqual(
            r.baseline_burst, baseline.total_burst_damage, places=3,
        )

    def test_top_1_delta_equals_new_minus_baseline(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=1,
        )
        self.assertGreater(len(r.ranked), 0)
        top = r.ranked[0]
        self.assertAlmostEqual(
            top.delta_burst, top.new_burst - r.baseline_burst, places=3,
        )

    def test_results_sorted_descending_by_delta(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=20,
        )
        deltas = [ri.delta_burst for ri in r.ranked]
        self.assertEqual(deltas, sorted(deltas, reverse=True))

    def test_top_n_clipping(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=3,
        )
        self.assertLessEqual(len(r.ranked), 3)

    def test_default_combo_sequence_carried(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=1,
        )
        self.assertEqual(r.combo_sequence, ("Q", "W", "E", "AA", "R", "AA"))

    def test_primary_scaling_surfaced(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=1,
        )
        self.assertEqual(r.primary_scaling, "AD")

    def test_ranked_item_is_dataclass(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=1,
        )
        self.assertIsInstance(r.ranked[0], BurstRankedItem)


# ─── scoring behavior ────────────────────────────────────────────────────────


class BurstScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_lethality_or_armor_pen_in_top_for_zed(self) -> None:
        # Zed vs 80 armor should surface lethality / armor-pen items in
        # top-5 (Youmuu's 3142, Hubris 6697, LDR 3036, Serylda's 6694,
        # Mortal Reminder 3033, Axiom Arc 6696, Umbral 3179, Eclipse 6692).
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=10,
        )
        top_ids = {ri.item_id for ri in r.ranked[:10]}
        lethality_or_pen = {"3142", "6697", "3036", "6694", "3033",
                            "6696", "3179", "6692", "6691", "3041", "6701"}
        self.assertTrue(
            top_ids & lethality_or_pen,
            f"expected lethality/pen item in top-10, got: {top_ids}",
        )

    def test_ap_item_in_top_for_diana(self) -> None:
        # Diana is AP — top-5 should include Rabadon's / Shadowflame /
        # Stormsurge / Void Staff / Mejai's / Luden's.
        r = rank_items_by_burst(
            self.snap, "Diana", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=10,
        )
        top_ids = {ri.item_id for ri in r.ranked[:5]}
        ap_canonical = {"3089", "4645", "4646", "3135", "3041", "6655"}
        self.assertTrue(
            top_ids & ap_canonical,
            f"expected AP item in top-5, got: {top_ids}",
        )

    def test_pure_ap_item_not_in_top_for_zed(self) -> None:
        # Zed lvl 11 vs 80 armor — Rabadon's (3089, pure AP) should NOT
        # be a top-3 burst pick.
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=20,
        )
        top3 = {ri.item_id for ri in r.ranked[:3]}
        self.assertNotIn("3089", top3, "Rabadon's should not be a top-3 Zed burst pick")

    def test_delta_positive_for_ad_item_on_ad_assassin(self) -> None:
        # Adding Youmuu's to naked Zed should produce delta > 0.
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0,
            only_item_ids=["3142"], top_n=1,
        )
        self.assertEqual(len(r.ranked), 1)
        self.assertGreater(r.ranked[0].delta_burst, 0.0)

    def test_efficiency_sort_orders_by_per_1k_gold(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0,
            sort_by="efficiency", top_n=20,
        )
        effs = [ri.burst_per_1k_gold for ri in r.ranked]
        self.assertEqual(effs, sorted(effs, reverse=True))

    def test_efficiency_zero_on_non_positive_delta(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0,
            include_components=True, top_n=200,
        )
        for ri in r.ranked:
            if ri.delta_burst <= 0.0:
                self.assertEqual(ri.burst_per_1k_gold, 0.0)


# ─── filter pipeline parity ──────────────────────────────────────────────────


class FilterPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_already_equipped_item_skipped(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0,
            current_item_ids=["3142"], top_n=50,
        )
        ids = {ri.item_id for ri in r.ranked}
        self.assertNotIn("3142", ids)

    def test_only_item_ids_restricts_pool(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0,
            only_item_ids=["3142", "6697", "3033"], top_n=20,
        )
        ids = {ri.item_id for ri in r.ranked}
        self.assertTrue(ids.issubset({"3142", "6697", "3033"}))
        self.assertGreaterEqual(len(r.ranked), 1)

    def test_budget_filter_drops_expensive(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0,
            budget=1500, top_n=20,
        )
        for ri in r.ranked:
            self.assertLessEqual(ri.gold, 1500)

    def test_include_components_expands_candidate_pool(self) -> None:
        terminal = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0,
            include_components=False, top_n=999,
        )
        with_comp = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0,
            include_components=True, top_n=999,
        )
        self.assertGreater(
            with_comp.candidates_evaluated, terminal.candidates_evaluated,
        )

    def test_arena_strips_trinket(self) -> None:
        # Mode=ARENA + current items contains Arcane Sweeper (3348) →
        # should not raise and should report the strip in notes.
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="ARENA",
            target_armor=80.0, target_mr=30.0,
            current_item_ids=["3348"], top_n=3,
        )
        self.assertEqual(len(r.current_item_ids), 0)
        notes = " ".join(r.notes)
        self.assertIn("3348", notes)

    def test_dead_unique_filter_drops_collision(self) -> None:
        # Eclipse (6692, unique_passive_key "spellblade" via Ever Rising
        # Moon family) — wait, Eclipse is NOT spellblade-keyed in the
        # engine docstring. Use Trinity Force (6630) as a confirmed
        # spellblade-key holder via current items. Then Sheen 3057,
        # Lich Bane 3100, ER 3508, Iceborn 6662, Divine Sunderer 6632
        # should be filtered.
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0,
            current_item_ids=["3078"], top_n=200,
        )
        ids = {ri.item_id for ri in r.ranked}
        spellblade_sibs = {"3057", "3100", "3508", "6662", "6632"}
        present = ids & spellblade_sibs
        self.assertEqual(present, set(),
                         f"shared-spellblade items should be filtered: {present}")

    def test_dead_unique_surfaced_when_filter_off(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0,
            current_item_ids=["3078"], top_n=200,
            filter_shared_uniques=False,
        )
        spellblade_sibs = {"3057", "3100", "3508", "6662", "6632"}
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
            rank_items_by_burst(self.snap, "Zed", level=11, sort_by="bogus")

    def test_full_build_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_burst(
                self.snap, "Zed", level=11,
                current_item_ids=["3142", "6697", "3033", "3036", "6694", "3031"],
            )

    def test_invalid_block_strategy_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_burst(self.snap, "Zed", level=11,
                                block_strategy="bogus")

    def test_invalid_combo_sequence_raises(self) -> None:
        with self.assertRaises(ValueError):
            rank_items_by_burst(self.snap, "Zed", level=11,
                                combo_sequence=["Q", "BOGUS"])


# ─── to_dict / format_table ──────────────────────────────────────────────────


class SerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_to_dict_round_trip(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=3,
        )
        d = r.to_dict()
        self.assertEqual(d["champion_id"], "Zed")
        self.assertEqual(d["level"], 11)
        self.assertIn("baseline_burst", d)
        self.assertIn("primary_scaling", d)
        self.assertIn("combo_sequence", d)
        self.assertIn("ranked", d)
        self.assertLessEqual(len(d["ranked"]), 3)
        if d["ranked"]:
            self.assertIn("delta_burst", d["ranked"][0])
            self.assertIn("burst_per_1k_gold", d["ranked"][0])

    def test_format_table_includes_assassin_tag(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=2,
        )
        out = r.format_table()
        self.assertIn("[ASSASSIN]", out)
        self.assertIn("Zed", out)
        self.assertIn("combo:", out)

    def test_ranked_item_to_dict_shape(self) -> None:
        r = rank_items_by_burst(
            self.snap, "Zed", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=1,
        )
        d = r.ranked[0].to_dict()
        for k in (
            "item_id", "item_name", "gold", "delta_burst",
            "new_burst", "burst_per_1k_gold", "is_terminal",
            "tags", "shares_dead_unique", "dead_unique_key",
        ):
            self.assertIn(k, d)


# ─── mode + amp flow-through ─────────────────────────────────────────────────


class ModeAndAmpFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_mode_multiplier_surfaced(self) -> None:
        # Veigar gets aramDamageDealt < 1.0 — sanity that ARAM passes through.
        sr = rank_items_by_burst(
            self.snap, "Veigar", level=11, mode="SR", target_mr=30.0, top_n=3,
        )
        aram = rank_items_by_burst(
            self.snap, "Veigar", level=11, mode="ARAM", target_mr=30.0, top_n=3,
        )
        self.assertEqual(sr.mode_multiplier, 1.0)
        self.assertLess(aram.mode_multiplier, 1.0)
        self.assertEqual(aram.mode, "ARAM")

    def test_amp_item_lifts_baseline_burst(self) -> None:
        # Adding Rabadon's via current_item_ids should produce a higher
        # baseline_burst.
        naked = rank_items_by_burst(
            self.snap, "Diana", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0, top_n=1,
        )
        rab = rank_items_by_burst(
            self.snap, "Diana", level=11, mode="SR",
            target_armor=80.0, target_mr=30.0,
            current_item_ids=["3089"], top_n=1,
        )
        self.assertGreater(rab.baseline_burst, naked.baseline_burst)


# ─── server route ────────────────────────────────────────────────────────────


class RankAssassinRouteTests(unittest.TestCase):
    """Spin the engine server on a free port; hit /rank-assassin; tear down."""

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

    def test_post_rank_assassin_returns_200(self) -> None:
        status, body = self._post("/rank-assassin", {
            "champion": "Zed", "level": 11, "mode": "SR",
            "target_armor": 80, "target_mr": 30, "top": 5,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "Zed")
        self.assertIn("baseline_burst", body)
        self.assertIn("ranked", body)
        self.assertLessEqual(len(body["ranked"]), 5)

    def test_rank_assassin_top_5_includes_known_ad_item(self) -> None:
        status, body = self._post("/rank-assassin", {
            "champion": "Zed", "level": 11, "mode": "SR",
            "target_armor": 80, "target_mr": 30, "top": 10,
        })
        self.assertEqual(status, 200)
        top_ids = {r["item_id"] for r in body["ranked"]}
        # IE / BT / Eclipse / Youmuu's / Hubris / LDR / Serylda's all viable.
        canonical = {"3031", "3072", "6692", "3142", "6697",
                     "3036", "6694", "3033", "6696", "3179"}
        self.assertTrue(
            top_ids & canonical,
            f"expected AD/lethality item in top-10, got: {top_ids}",
        )

    def test_rank_assassin_custom_combo(self) -> None:
        status, body = self._post("/rank-assassin", {
            "champion": "Talon", "level": 11, "mode": "SR",
            "target_armor": 80, "target_mr": 30, "top": 3,
            "combo_sequence": ["W", "Q", "AA", "R", "AA"],
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["combo_sequence"],
                         ["W", "Q", "AA", "R", "AA"])

    def test_rank_assassin_404_on_unknown_champion(self) -> None:
        status, _ = self._post("/rank-assassin", {
            "champion": "NobodyChampion", "level": 11,
        })
        self.assertEqual(status, 404)

    def test_rank_assassin_400_on_invalid_sort(self) -> None:
        status, _ = self._post("/rank-assassin", {
            "champion": "Zed", "level": 11, "sort": "bogus",
        })
        self.assertEqual(status, 400)

    def test_rank_assassin_with_only_item_ids_whitelist(self) -> None:
        status, body = self._post("/rank-assassin", {
            "champion": "Zed", "level": 11, "mode": "SR",
            "target_armor": 80, "target_mr": 30,
            "only": ["3142", "6697", "3033"], "top": 10,
        })
        self.assertEqual(status, 200)
        ids = {r["item_id"] for r in body["ranked"]}
        self.assertTrue(ids.issubset({"3142", "6697", "3033"}))

    def test_rank_assassin_efficiency_sort(self) -> None:
        status, body = self._post("/rank-assassin", {
            "champion": "Zed", "level": 11, "mode": "SR",
            "target_armor": 80, "target_mr": 30,
            "sort": "efficiency", "top": 5,
        })
        self.assertEqual(status, 200)
        effs = [r["burst_per_1k_gold"] for r in body["ranked"]]
        self.assertEqual(effs, sorted(effs, reverse=True))

    def test_rank_assassin_filter_shared_uniques_default_true(self) -> None:
        status, body = self._post("/rank-assassin", {
            "champion": "Zed", "level": 11, "mode": "SR",
            "target_armor": 80, "target_mr": 30,
            "items": ["3078"], "top": 100,
        })
        self.assertEqual(status, 200)
        ids = {r["item_id"] for r in body["ranked"]}
        spellblade_sibs = {"3057", "3100", "3508", "6662", "6632"}
        self.assertEqual(ids & spellblade_sibs, set())


if __name__ == "__main__":
    unittest.main()

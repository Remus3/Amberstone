"""Phase 3 — server route tests.

Spins up `start_server` on port 0 (kernel-assigned) in a daemon thread,
hits each route via stdlib `urllib.request`, asserts JSON shape and
4xx error mapping. Same DataSnapshot used by the rest of the test
suite.
"""
from __future__ import annotations

import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.server import start_server


def _start_test_server() -> tuple[str, int, "object"]:
    """Bind to an ephemeral port and spin a daemon serving thread.

    Returns ``(host, port, server)`` so callers can shut it down via
    ``server.shutdown()`` + ``server.server_close()``.
    """
    snap = DataSnapshot.load()
    srv = start_server(host="127.0.0.1", port=0, snapshot=snap)
    host, port = srv.server_address
    t = threading.Thread(target=srv.serve_forever, daemon=True,
                         name="DaemonSlayerTestServer")
    t.start()
    return host, port, srv


def _get_json(url: str) -> tuple[int, dict]:
    try:
        with urlopen(url, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _post_json(url: str, body: dict) -> tuple[int, dict]:
    raw = json.dumps(body).encode("utf-8")
    req = Request(url, data=raw, method="POST",
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


class ServerLifecycleTests(unittest.TestCase):
    """One server instance shared across the suite — start/stop is the
    expensive op (~30 ms snapshot load), tests themselves are quick."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.host, cls.port, cls.srv = _start_test_server()
        cls.base = f"http://{cls.host}:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.srv.shutdown()
        cls.srv.server_close()


class HealthRouteTests(ServerLifecycleTests):
    def test_health_returns_ok_with_engine_version_and_patch(self) -> None:
        status, body = _get_json(self.base + "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["engine_version"], ENGINE_VERSION)
        self.assertTrue(body["patch"])
        self.assertGreater(body["champions"], 100)
        self.assertGreater(body["items"], 100)

    def test_snapshot_returns_manifest_excerpt(self) -> None:
        status, body = _get_json(self.base + "/snapshot")
        self.assertEqual(status, 200)
        self.assertTrue(body["patch"])
        self.assertGreater(body["champions"], 100)
        self.assertIn("phase", body["manifest"])

    def test_index_html(self) -> None:
        from urllib.request import urlopen
        with urlopen(self.base + "/") as resp:
            self.assertEqual(resp.status, 200)
            ct = resp.headers.get("Content-Type", "")
            self.assertIn("text/html", ct)
            html = resp.read().decode("utf-8")
        self.assertIn("Daemon Slayer", html)
        self.assertIn(ENGINE_VERSION, html)


class StatsRouteTests(ServerLifecycleTests):
    def test_post_stats_naked(self) -> None:
        status, body = _post_json(self.base + "/stats",
                                  {"champion": "Aatrox", "level": 1})
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "Aatrox")
        self.assertEqual(body["level"], 1)
        self.assertEqual(body["item_ids"], [])
        self.assertIn("hp", body["stats"])
        self.assertIn("ad", body["stats"])

    def test_post_stats_with_items(self) -> None:
        status, body = _post_json(self.base + "/stats",
                                  {"champion": "Aatrox", "level": 11,
                                   "items": ["6692", "3006"]})
        self.assertEqual(status, 200)
        self.assertEqual(body["item_ids"], ["6692", "3006"])
        self.assertGreater(body["gold_spent"], 0)

    def test_get_stats_via_query(self) -> None:
        status, body = _get_json(
            self.base + "/stats?champion=Aatrox&level=11&items=6692,3006"
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["item_ids"], ["6692", "3006"])
        self.assertEqual(body["level"], 11)

    def test_unknown_champion_returns_404(self) -> None:
        status, body = _post_json(self.base + "/stats",
                                  {"champion": "Notarealchamp", "level": 1})
        self.assertEqual(status, 404)
        self.assertIn("error", body)

    def test_missing_champion_returns_400(self) -> None:
        status, body = _post_json(self.base + "/stats", {"level": 1})
        self.assertEqual(status, 400)
        self.assertIn("champion", body["error"])

    def test_invalid_json_body_returns_400(self) -> None:
        # Bypass _post_json to send malformed bytes.
        req = Request(self.base + "/stats", data=b"{not-json",
                      method="POST",
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=10) as resp:
                self.fail(f"expected 400, got {resp.status}")
        except HTTPError as e:
            self.assertEqual(e.code, 400)
            body = json.loads(e.read().decode("utf-8"))
            self.assertIn("invalid JSON", body["error"])


class DpsRouteTests(ServerLifecycleTests):
    def test_post_dps_returns_phase_dps(self) -> None:
        status, body = _post_json(self.base + "/dps",
                                  {"champion": "Aatrox", "level": 11,
                                   "items": ["6692", "3006", "3072", "3031"],
                                   "target_armor": 80})
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "Aatrox")
        self.assertEqual(body["target_armor"], 80.0)
        self.assertIn("weighted_dps", body)
        self.assertIn(body["phase"], ("early", "mid", "late"))
        self.assertIn("early", body["phase_dps"])
        self.assertIn("mid", body["phase_dps"])
        self.assertIn("late", body["phase_dps"])

    def test_dps_aram_mode_applies_modifier(self) -> None:
        status, body = _post_json(self.base + "/dps",
                                  {"champion": "Aatrox", "level": 11,
                                   "items": ["3006"], "mode": "ARAM",
                                   "target_armor": 0})
        self.assertEqual(status, 200)
        # Aatrox aramDamageDealt is 1.05 in 16.9.1
        self.assertGreater(body["mode_multiplier"], 1.0)

    def test_dps_invalid_phase_returns_400(self) -> None:
        status, body = _post_json(self.base + "/dps",
                                  {"champion": "Aatrox", "level": 11,
                                   "phase": "endgame"})
        self.assertEqual(status, 400)
        self.assertIn("phase", body["error"])

    def test_dps_unknown_item_returns_404(self) -> None:
        status, body = _post_json(self.base + "/dps",
                                  {"champion": "Aatrox", "level": 11,
                                   "items": ["999999999"]})
        self.assertEqual(status, 404)

    def test_dps_with_augments_raises_weighted_dps(self) -> None:
        status_bare, bare = _post_json(self.base + "/dps",
                                       {"champion": "Aatrox", "level": 11,
                                        "mode": "ARENA"})
        status_aug, aug = _post_json(self.base + "/dps",
                                     {"champion": "Aatrox", "level": 11,
                                      "mode": "ARENA",
                                      "augments": ["TheBrutalizer"]})
        self.assertEqual(status_bare, 200)
        self.assertEqual(status_aug, 200)
        self.assertGreater(aug["weighted_dps"], bare["weighted_dps"])


class RankRouteTests(ServerLifecycleTests):
    def test_post_rank_default_top_n_and_sort(self) -> None:
        status, body = _post_json(self.base + "/rank",
                                  {"champion": "Aatrox", "level": 11,
                                   "target_armor": 80, "top": 5})
        self.assertEqual(status, 200)
        self.assertEqual(body["sort_by"], "delta")
        self.assertEqual(len(body["ranked"]), 5)
        # Filter should keep a meaningful slice (terminal SR items only).
        self.assertGreater(body["candidates_evaluated"], 100)
        self.assertGreater(body["candidates_considered"],
                           body["candidates_evaluated"])

    def test_rank_efficiency_sort_orders_differ_from_delta(self) -> None:
        _, by_delta = _post_json(self.base + "/rank",
                                 {"champion": "Aatrox", "level": 11,
                                  "target_armor": 80, "top": 10,
                                  "sort": "delta"})
        _, by_eff = _post_json(self.base + "/rank",
                               {"champion": "Aatrox", "level": 11,
                                "target_armor": 80, "top": 10,
                                "sort": "efficiency"})
        delta_ids = [r["item_id"] for r in by_delta["ranked"]]
        eff_ids = [r["item_id"] for r in by_eff["ranked"]]
        self.assertNotEqual(delta_ids, eff_ids,
                            "sort=delta and sort=efficiency should produce "
                            "different orderings on the same query")

    def test_rank_invalid_sort_returns_400(self) -> None:
        status, body = _post_json(self.base + "/rank",
                                  {"champion": "Aatrox", "level": 11,
                                   "sort": "winrate"})
        self.assertEqual(status, 400)
        self.assertIn("sort", body["error"])

    def test_rank_only_whitelist_filters_correctly(self) -> None:
        status, body = _post_json(self.base + "/rank",
                                  {"champion": "Aatrox", "level": 11,
                                   "target_armor": 80,
                                   "only": ["3031", "3072"]})
        self.assertEqual(status, 200)
        ids = {r["item_id"] for r in body["ranked"]}
        self.assertTrue(ids.issubset({"3031", "3072"}))
        self.assertGreater(len(body["ranked"]), 0)

    def test_rank_full_build_returns_422(self) -> None:
        # 6 items already + slots default 6 → no room → ValueError → 422
        status, body = _post_json(self.base + "/rank",
                                  {"champion": "Aatrox", "level": 11,
                                   "items": ["3006", "3072", "3031",
                                             "3094", "3036", "3046"]})
        self.assertEqual(status, 422)

    def test_rank_accepts_augments_param(self) -> None:
        status, body = _post_json(self.base + "/rank",
                                  {"champion": "Aatrox", "level": 11,
                                   "mode": "ARENA",
                                   "augments": ["TheBrutalizer", "ItsCritical"],
                                   "top": 3})
        self.assertEqual(status, 200)
        self.assertEqual(len(body["ranked"]), 3)


class EhpRouteTests(ServerLifecycleTests):
    """Phase 1 (s174, 2026-05-12) — /ehp + /rank-tank route smoke tests."""

    def test_post_ehp_naked(self) -> None:
        status, body = _post_json(self.base + "/ehp", {
            "champion": "Malphite", "level": 11,
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "Malphite")
        self.assertGreater(body["hp"], 0)
        self.assertGreater(body["armor"], 0)
        self.assertGreater(body["physical_ehp"], body["hp"])
        # 50/50 default split — true_share is 0 when ad+ap == 1.0
        self.assertAlmostEqual(body["enemy_ad_share"], 0.5)
        self.assertAlmostEqual(body["enemy_ap_share"], 0.5)

    def test_post_ehp_pure_ad_enemy(self) -> None:
        status, body = _post_json(self.base + "/ehp", {
            "champion": "Malphite", "level": 11,
            "enemy_ad_share": 1.0, "enemy_ap_share": 0.0,
        })
        self.assertEqual(status, 200)
        # blended_ehp should equal physical_ehp when 100% AD
        self.assertAlmostEqual(body["blended_ehp"], body["physical_ehp"], places=2)

    def test_post_rank_tank_top_pick_is_armor_for_ad_enemy(self) -> None:
        status, body = _post_json(self.base + "/rank-tank", {
            "champion": "Malphite", "level": 11,
            "enemy_ad_share": 0.9, "enemy_ap_share": 0.1,
            "only": ["3075", "3110", "3047", "3143"],
            "top": 5,
        })
        self.assertEqual(status, 200)
        self.assertGreater(body["baseline_ehp"], 0)
        self.assertGreater(len(body["ranked"]), 0)
        ranked_ids = [r["item_id"] for r in body["ranked"]]
        self.assertTrue(set(ranked_ids).issubset(
            {"3075", "3110", "3047", "3143"}
        ))
        # Top pick should have a positive delta_ehp
        self.assertGreater(body["ranked"][0]["delta_ehp"], 0)

    def test_post_rank_tank_share_validation(self) -> None:
        status, body = _post_json(self.base + "/rank-tank", {
            "champion": "Malphite", "level": 11,
            "enemy_ad_share": 0.7, "enemy_ap_share": 0.7,
        })
        # share sum > 1.0 → engine raises ValueError → 422
        self.assertEqual(status, 422)


class RoutingTests(ServerLifecycleTests):
    def test_unknown_path_returns_404(self) -> None:
        status, body = _get_json(self.base + "/nope")
        self.assertEqual(status, 404)
        self.assertIn("nope", body["error"])

    def test_post_to_health_returns_404(self) -> None:
        # Health is GET-only; no POST handler registered.
        status, body = _post_json(self.base + "/health", {})
        self.assertEqual(status, 404)


class ChampionIdResolutionTests(ServerLifecycleTests):
    """s156: server-side display-name → DDragon-id fallback.
    Regression target — RC's coaches feed champion as the display name
    ('Kai'Sa', 'Wukong', 'Renata Glasc') from coaching_data.json. Before
    this fix, /rank returned 404 → daemon_slayer_picks never written →
    dashboard #ds-pill stayed hidden mid-game ('ds not loaded at all')."""

    def test_apostrophe_display_name_resolves(self) -> None:
        # Kai'Sa → DDragon ID 'Kaisa'. Apostrophe family covers
        # K'Sante, Rek'Sai, Cho'Gath, Kha'Zix, Vel'Koz, Kog'Maw, Bel'Veth.
        status, body = _post_json(self.base + "/rank",
                                  {"champion": "Kai'Sa", "level": 11,
                                   "mode": "SR", "top": 3})
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "Kaisa")
        self.assertEqual(body["champion_name"], "Kai'Sa")

    def test_renamed_id_resolves_via_display(self) -> None:
        # Wukong → MonkeyKing (DDragon-side rename).
        status, body = _post_json(self.base + "/rank",
                                  {"champion": "Wukong", "level": 11,
                                   "mode": "SR", "top": 1})
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "MonkeyKing")

    def test_space_display_name_resolves(self) -> None:
        # 'Renata Glasc' → 'Renata'.
        status, body = _post_json(self.base + "/rank",
                                  {"champion": "Renata Glasc", "level": 11,
                                   "mode": "SR", "top": 1})
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "Renata")

    def test_lowercase_apostrophe_resolves(self) -> None:
        # Case-insensitive lookup.
        status, body = _post_json(self.base + "/rank",
                                  {"champion": "kai'sa", "level": 11,
                                   "mode": "SR", "top": 1})
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "Kaisa")

    def test_alnum_stripped_resolves(self) -> None:
        # Strip-and-lowercase fallback for "kaisa" / "twistedfate" / etc.
        status, body = _post_json(self.base + "/rank",
                                  {"champion": "twistedfate", "level": 11,
                                   "mode": "SR", "top": 1})
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "TwistedFate")

    def test_ddragon_id_passthrough_unchanged(self) -> None:
        # Direct ID match is the fast path; no behavior change for
        # callers that already pass DDragon IDs.
        status, body = _post_json(self.base + "/rank",
                                  {"champion": "Kaisa", "level": 11,
                                   "mode": "SR", "top": 1})
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "Kaisa")

    def test_unknown_still_404s(self) -> None:
        # Resolver returns the input unchanged when no match — engine
        # then raises the canonical KeyError → 404. No silent successes.
        status, body = _post_json(self.base + "/rank",
                                  {"champion": "Notarealchamp", "level": 1,
                                   "mode": "SR", "top": 1})
        self.assertEqual(status, 404)

    def test_resolution_applies_to_dps_route(self) -> None:
        status, body = _post_json(self.base + "/dps",
                                  {"champion": "Kai'Sa", "level": 11,
                                   "mode": "SR"})
        self.assertEqual(status, 200)
        self.assertEqual(body["champion_id"], "Kaisa")


if __name__ == "__main__":
    unittest.main()

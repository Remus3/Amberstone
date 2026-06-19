"""Tests for ``dashboard.routes_draft_elo`` GET /api/draft-elo."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from dashboard import routes_draft_elo
from tests._draft_elo_fixture import DraftEloFixtureMixin


class _RouteHarness:
    def __init__(self, qs: str):
        self.path = f"/api/draft-elo?{qs}"
        self.sent_status = None
        self.sent_body = None
        self.sent_ct = None

    def _send(self, status, body, content_type):
        self.sent_status = status
        self.sent_body = body
        self.sent_ct = content_type


class InputValidationTests(unittest.TestCase):
    def setUp(self):
        routes_draft_elo._reset_caches()

    def test_missing_ally(self):
        h = _RouteHarness("enemy=1,2,3,4,5")
        routes_draft_elo._serve_draft_elo(h)
        self.assertEqual(h.sent_status, 400)
        payload = json.loads(h.sent_body)
        self.assertIn("ally", payload["error"])

    def test_wrong_count_enemy(self):
        h = _RouteHarness("ally=1,2,3,4,5&enemy=1,2,3")
        routes_draft_elo._serve_draft_elo(h)
        self.assertEqual(h.sent_status, 400)
        self.assertIn("enemy", json.loads(h.sent_body)["error"])

    def test_non_integer_ids(self):
        h = _RouteHarness("ally=1,2,3,4,abc&enemy=1,2,3,4,5")
        routes_draft_elo._serve_draft_elo(h)
        self.assertEqual(h.sent_status, 400)

    def test_non_integer_queue(self):
        h = _RouteHarness("ally=1,2,3,4,5&enemy=10,20,30,40,50&queue=ranked")
        routes_draft_elo._serve_draft_elo(h)
        self.assertEqual(h.sent_status, 400)


class HappyPathTests(DraftEloFixtureMixin, unittest.TestCase):
    def setUp(self):
        routes_draft_elo._reset_caches()

    def test_full_round_trip(self):
        h = _RouteHarness("ally=22,64,55,89,12&enemy=42,67,69,33,99")
        routes_draft_elo._serve_draft_elo(h)
        self.assertEqual(h.sent_status, 200)
        payload = json.loads(h.sent_body)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["ally"]["champs"]), 5)
        self.assertEqual(len(payload["enemy"]["champs"]), 5)
        self.assertEqual(len(payload["ally"]["champ_ratings"]), 5)
        self.assertEqual(len(payload["enemy"]["champ_ratings"]), 5)
        self.assertEqual(len(payload["ally"]["pair_ratings"]), 10)
        self.assertEqual(len(payload["enemy"]["pair_ratings"]), 10)
        self.assertEqual(len(payload["ally"]["matchup_ratings"]), 25)
        self.assertIn("predicted_wr", payload)
        self.assertIn("team_score", payload)
        self.assertIn("sample", payload)
        # Sample density floor is non-negative.
        self.assertGreaterEqual(payload["sample"]["min_solo"], 0)
        self.assertGreaterEqual(payload["sample"]["min_pair"], 0)
        # WR is in [0, 1].
        self.assertGreaterEqual(payload["predicted_wr"], 0.0)
        self.assertLessEqual(payload["predicted_wr"], 1.0)

    def test_cache_hit_second_call(self):
        h1 = _RouteHarness("ally=22,64,55,89,12&enemy=42,67,69,33,99")
        routes_draft_elo._serve_draft_elo(h1)
        h2 = _RouteHarness("ally=22,64,55,89,12&enemy=42,67,69,33,99")
        routes_draft_elo._serve_draft_elo(h2)
        self.assertEqual(h2.sent_status, 200)
        payload2 = json.loads(h2.sent_body)
        self.assertTrue(payload2.get("cached"))

    def test_cache_key_order_insensitive(self):
        """Sorted-id cache key: same teams in different order = same key."""
        h1 = _RouteHarness("ally=22,64,55,89,12&enemy=42,67,69,33,99")
        routes_draft_elo._serve_draft_elo(h1)
        # Permute both teams - should hit the cache (sorted_id key).
        h2 = _RouteHarness("ally=12,89,55,64,22&enemy=99,33,69,67,42")
        routes_draft_elo._serve_draft_elo(h2)
        payload2 = json.loads(h2.sent_body)
        self.assertTrue(payload2.get("cached"))

    def test_explicit_queue_path(self):
        h = _RouteHarness("ally=22,64,55,89,12&enemy=42,67,69,33,99&queue=420")
        routes_draft_elo._serve_draft_elo(h)
        self.assertEqual(h.sent_status, 200)
        payload = json.loads(h.sent_body)
        self.assertEqual(payload["queue_ids"], [420])


class BreakdownQueryParamTests(DraftEloFixtureMixin, unittest.TestCase):
    """Tests for the ?breakdown=1 hover-strip query param (2026-05-20
    BACKLOG/ROADMAP 109(b))."""

    def setUp(self):
        routes_draft_elo._reset_caches()

    def test_no_breakdown_omits_field(self):
        h = _RouteHarness("ally=22,64,55,89,12&enemy=42,67,69,33,99")
        routes_draft_elo._serve_draft_elo(h)
        self.assertEqual(h.sent_status, 200)
        payload = json.loads(h.sent_body)
        self.assertNotIn("top_contributions", payload)

    def test_breakdown_truthy_includes_field(self):
        h = _RouteHarness("ally=22,64,55,89,12&enemy=42,67,69,33,99&breakdown=1")
        routes_draft_elo._serve_draft_elo(h)
        self.assertEqual(h.sent_status, 200)
        payload = json.loads(h.sent_body)
        self.assertIn("top_contributions", payload)
        # Top-3 limit enforced at the route layer.
        self.assertLessEqual(len(payload["top_contributions"]), 3)

    def test_breakdown_shape(self):
        h = _RouteHarness("ally=22,64,55,89,12&enemy=42,67,69,33,99&breakdown=1")
        routes_draft_elo._serve_draft_elo(h)
        payload = json.loads(h.sent_body)
        entries = payload.get("top_contributions") or []
        # At least one entry expected for a realistic draft (10
        # ally-pair + 10 enemy-pair + 25 matchup rows feed the sort).
        self.assertTrue(entries, "expected at least one contribution row")
        first = entries[0]
        self.assertIn(first["kind"], ("ally-pair", "enemy-pair", "matchup"))
        self.assertIsInstance(first["a"], int)
        self.assertIsInstance(first["b"], int)
        self.assertIsInstance(first["delta"], (int, float))
        self.assertIsInstance(first["n"], int)

    def test_breakdown_sorted_by_abs_delta_desc(self):
        h = _RouteHarness("ally=22,64,55,89,12&enemy=42,67,69,33,99&breakdown=1")
        routes_draft_elo._serve_draft_elo(h)
        payload = json.loads(h.sent_body)
        entries = payload.get("top_contributions") or []
        if len(entries) >= 2:
            for i in range(len(entries) - 1):
                self.assertGreaterEqual(
                    abs(entries[i]["delta"]),
                    abs(entries[i + 1]["delta"]),
                    msg=f"contribution {i} should have larger abs(delta)",
                )

    def test_breakdown_falsy_omits_field(self):
        h = _RouteHarness("ally=22,64,55,89,12&enemy=42,67,69,33,99&breakdown=0")
        routes_draft_elo._serve_draft_elo(h)
        payload = json.loads(h.sent_body)
        self.assertNotIn("top_contributions", payload)

    def test_breakdown_cached_path_strips_field(self):
        """The cache always stores the full payload; a NO-breakdown
        request must still strip the field even on a cache HIT."""
        # Prime the cache with a breakdown=1 request.
        h1 = _RouteHarness("ally=22,64,55,89,12&enemy=42,67,69,33,99&breakdown=1")
        routes_draft_elo._serve_draft_elo(h1)
        # Now hit the cache without breakdown.
        h2 = _RouteHarness("ally=22,64,55,89,12&enemy=42,67,69,33,99")
        routes_draft_elo._serve_draft_elo(h2)
        payload = json.loads(h2.sent_body)
        self.assertTrue(payload.get("cached"))
        self.assertNotIn("top_contributions", payload)

    def test_breakdown_cached_path_returns_field(self):
        """Reverse: prime without breakdown, then ask for it - the
        cached payload retains the field internally so the breakdown
        request still gets the top-3."""
        h1 = _RouteHarness("ally=22,64,55,89,12&enemy=42,67,69,33,99")
        routes_draft_elo._serve_draft_elo(h1)
        h2 = _RouteHarness("ally=22,64,55,89,12&enemy=42,67,69,33,99&breakdown=1")
        routes_draft_elo._serve_draft_elo(h2)
        payload = json.loads(h2.sent_body)
        self.assertTrue(payload.get("cached"))
        self.assertIn("top_contributions", payload)

    def test_breakdown_truthy_variants(self):
        """``1``, ``true``, ``yes``, ``on`` all enable the breakdown."""
        for raw in ("1", "true", "TRUE", "yes", "on"):
            routes_draft_elo._reset_caches()
            h = _RouteHarness(
                f"ally=22,64,55,89,12&enemy=42,67,69,33,99&breakdown={raw}"
            )
            routes_draft_elo._serve_draft_elo(h)
            payload = json.loads(h.sent_body)
            self.assertIn("top_contributions", payload,
                          msg=f"breakdown={raw!r} should enable the field")


class DegradedDbTests(unittest.TestCase):
    def setUp(self):
        routes_draft_elo._reset_caches()

    def test_db_failure_returns_503(self):
        with patch("dashboard.routes_draft_elo._compute",
                   side_effect=RuntimeError("db missing")):
            h = _RouteHarness("ally=1,2,3,4,5&enemy=10,20,30,40,50")
            routes_draft_elo._serve_draft_elo(h)
        self.assertEqual(h.sent_status, 503)
        payload = json.loads(h.sent_body)
        self.assertFalse(payload["ok"])


class DispatchRegistrationTests(unittest.TestCase):
    def test_route_registered(self):
        from dashboard import _dispatch
        routes = _dispatch._gather_get()
        path = "/api/draft-elo"
        matched = False
        for predicate, _handler in routes:
            try:
                if predicate(path):
                    matched = True
                    break
            except Exception:  # noqa: BLE001
                continue
        self.assertTrue(matched, "/api/draft-elo not registered with dispatch")


if __name__ == "__main__":
    unittest.main()

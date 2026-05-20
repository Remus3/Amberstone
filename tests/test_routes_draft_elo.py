"""Tests for ``dashboard.routes_draft_elo`` GET /api/draft-elo."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from dashboard import routes_draft_elo


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


class HappyPathTests(unittest.TestCase):
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
            except Exception:
                continue
        self.assertTrue(matched, "/api/draft-elo not registered with dispatch")


if __name__ == "__main__":
    unittest.main()

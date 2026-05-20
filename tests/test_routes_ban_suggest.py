"""Tests for ``dashboard.routes_ban_suggest`` GET /api/ban-suggest."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from dashboard import routes_ban_suggest


class _Harness:
    def __init__(self, qs: str):
        self.path = f"/api/ban-suggest?{qs}"
        self.sent_status = None
        self.sent_body = None
        self.sent_ct = None

    def _send(self, status, body, content_type):
        self.sent_status = status
        self.sent_body = body
        self.sent_ct = content_type


class InputValidationTests(unittest.TestCase):
    def setUp(self):
        routes_ban_suggest._reset_caches()

    def test_missing_ally(self):
        h = _Harness("candidates=1,2,3")
        routes_ban_suggest._serve_ban_suggest(h)
        self.assertEqual(h.sent_status, 400)

    def test_missing_candidates(self):
        h = _Harness("ally=22,64&enemy=42")
        routes_ban_suggest._serve_ban_suggest(h)
        self.assertEqual(h.sent_status, 400)
        self.assertIn("candidate", json.loads(h.sent_body)["error"])

    def test_too_many_candidates(self):
        cands = ",".join(str(i) for i in range(1, 35))
        h = _Harness(f"ally=22,64,55,89,12&candidates={cands}")
        routes_ban_suggest._serve_ban_suggest(h)
        self.assertEqual(h.sent_status, 400)

    def test_non_integer_id(self):
        h = _Harness("ally=22,abc&candidates=1,2,3")
        routes_ban_suggest._serve_ban_suggest(h)
        self.assertEqual(h.sent_status, 400)


class HappyPathTests(unittest.TestCase):
    def setUp(self):
        routes_ban_suggest._reset_caches()

    def test_minimal_request(self):
        """Single ally + single candidate suffices."""
        h = _Harness("ally=22&candidates=64")
        routes_ban_suggest._serve_ban_suggest(h)
        self.assertEqual(h.sent_status, 200)
        payload = json.loads(h.sent_body)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["candidates"]), 1)
        c = payload["candidates"][0]
        self.assertEqual(c["champ_id"], 64)
        self.assertIn("solo_rating", c)
        self.assertIn("hurts_them_score", c)
        self.assertIn("helps_us_score", c)
        self.assertIn("min_solo_n", c)
        self.assertIn("min_pair_n", c)

    def test_full_5v5_with_candidates(self):
        h = _Harness("ally=22,64,55,89,12&enemy=42,67,69,33,99"
                     "&candidates=8,1,103,202,432")
        routes_ban_suggest._serve_ban_suggest(h)
        self.assertEqual(h.sent_status, 200)
        payload = json.loads(h.sent_body)
        self.assertEqual(len(payload["candidates"]), 5)
        # Each candidate carries both signal scores.
        for c in payload["candidates"]:
            self.assertIsInstance(c["hurts_them_score"], float)
            self.assertIsInstance(c["helps_us_score"], float)

    def test_candidate_self_skip(self):
        """A candidate matching an ally/enemy should still get scored
        (some operators want to know if a locked-in ally is the threat)."""
        h = _Harness("ally=22,64&enemy=42&candidates=22")
        routes_ban_suggest._serve_ban_suggest(h)
        self.assertEqual(h.sent_status, 200)
        payload = json.loads(h.sent_body)
        self.assertEqual(len(payload["candidates"]), 1)

    def test_cache_hit_second_call(self):
        h1 = _Harness("ally=22,64,55,89,12&candidates=8,1,103")
        routes_ban_suggest._serve_ban_suggest(h1)
        h2 = _Harness("ally=22,64,55,89,12&candidates=8,1,103")
        routes_ban_suggest._serve_ban_suggest(h2)
        self.assertEqual(h2.sent_status, 200)
        self.assertTrue(json.loads(h2.sent_body).get("cached"))

    def test_cache_key_order_insensitive(self):
        h1 = _Harness("ally=22,64,55,89,12&candidates=8,1,103")
        routes_ban_suggest._serve_ban_suggest(h1)
        h2 = _Harness("ally=12,89,55,64,22&candidates=103,8,1")
        routes_ban_suggest._serve_ban_suggest(h2)
        self.assertTrue(json.loads(h2.sent_body).get("cached"))


class DegradedDbTests(unittest.TestCase):
    def setUp(self):
        routes_ban_suggest._reset_caches()

    def test_db_failure_returns_503(self):
        with patch("dashboard.routes_ban_suggest._compute",
                   side_effect=RuntimeError("db down")):
            h = _Harness("ally=22&candidates=64")
            routes_ban_suggest._serve_ban_suggest(h)
        self.assertEqual(h.sent_status, 503)


class DispatchRegistrationTests(unittest.TestCase):
    def test_route_registered(self):
        from dashboard import _dispatch
        routes = _dispatch._gather_get()
        matched = False
        for predicate, _h in routes:
            try:
                if predicate("/api/ban-suggest"):
                    matched = True
                    break
            except Exception:
                continue
        self.assertTrue(matched, "/api/ban-suggest not registered")


if __name__ == "__main__":
    unittest.main()

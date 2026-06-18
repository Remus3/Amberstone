"""Tests for ``dashboard.routes_duration_winrate`` GET /api/duration-winrate.

The corpus scan itself (``core.duration_winrate.compute_duration_winrate``) is
covered by tests/test_duration_winrate.py. These tests cover the ROUTE layer
only - query parsing, the 5min (mode, champion) in-process response cache, the
``cached`` / ``elapsed_ms`` envelope fields, and the no-raw-error-leak 500 path
- by patching ``compute_duration_winrate`` to a deterministic stub, so they
touch NO real rewind_history.db (clean-checkout / CI safe;
reference_clean_checkout_probe).
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from dashboard import routes_duration_winrate as rdw

_COMPUTE = "dashboard.routes_duration_winrate.duration_winrate.compute_duration_winrate"


class _RouteHarness:
    def __init__(self, qs: str = ""):
        self.path = "/api/duration-winrate" + (f"?{qs}" if qs else "")
        self.sent_status = None
        self.sent_body = None
        self.sent_ct = None

    def _send(self, status, body, content_type):
        self.sent_status = status
        self.sent_body = body
        self.sent_ct = content_type


def _stub(**kw):
    """A fresh compute-shaped dict each call (the route mutates its return)."""
    return {
        "ok": True,
        "mode": kw.get("mode"),
        "champion": kw.get("champion"),
        "n": 10,
        "buckets": [{"label": "20-25m", "games": 10, "wins": 6, "winrate": 60.0}],
    }


class _PatchedComputeCase(unittest.TestCase):
    """Base: patch compute to the stub + clear the module cache per test."""

    def setUp(self):
        rdw._reset_caches()
        self._p = patch(_COMPUTE, side_effect=_stub)
        self.compute = self._p.start()
        self.addCleanup(self._p.stop)
        self.addCleanup(rdw._reset_caches)


class ParsingTests(_PatchedComputeCase):
    def test_default_mode_is_aram(self):
        h = _RouteHarness("")
        rdw._serve_duration_winrate(h)
        self.assertEqual(h.sent_status, 200)
        self.assertEqual(h.sent_ct, "application/json")
        self.compute.assert_called_once_with(mode="aram", champion=None)

    def test_valid_mode_passthrough(self):
        h = _RouteHarness("mode=sr")
        rdw._serve_duration_winrate(h)
        self.assertEqual(h.sent_status, 200)
        self.compute.assert_called_once_with(mode="sr", champion=None)

    def test_bad_mode_400_compute_not_called(self):
        h = _RouteHarness("mode=urf")
        rdw._serve_duration_winrate(h)
        self.assertEqual(h.sent_status, 400)
        self.assertEqual(h.sent_ct, "application/json")
        self.assertFalse(json.loads(h.sent_body)["ok"])
        self.compute.assert_not_called()

    def test_champion_int_passthrough(self):
        h = _RouteHarness("champion=64")
        rdw._serve_duration_winrate(h)
        self.assertEqual(h.sent_status, 200)
        self.compute.assert_called_once_with(mode="aram", champion=64)
        self.assertEqual(json.loads(h.sent_body)["champion"], 64)

    def test_champion_non_int_400_compute_not_called(self):
        h = _RouteHarness("champion=ashe")
        rdw._serve_duration_winrate(h)
        self.assertEqual(h.sent_status, 400)
        self.assertFalse(json.loads(h.sent_body)["ok"])
        self.compute.assert_not_called()

    def test_champion_omitted_is_null(self):
        h = _RouteHarness("mode=aram")
        rdw._serve_duration_winrate(h)
        self.assertIsNone(json.loads(h.sent_body)["champion"])
        self.compute.assert_called_once_with(mode="aram", champion=None)

    def test_bad_mode_checked_before_champion(self):
        # mode error short-circuits, so a bad champion is never reached.
        h = _RouteHarness("mode=urf&champion=ashe")
        rdw._serve_duration_winrate(h)
        self.assertEqual(h.sent_status, 400)
        self.assertIn("mode", json.loads(h.sent_body)["error"])


class EnvelopeTests(_PatchedComputeCase):
    def test_first_call_not_cached_with_elapsed_ms(self):
        h = _RouteHarness("")
        rdw._serve_duration_winrate(h)
        payload = json.loads(h.sent_body)
        self.assertFalse(payload["cached"])
        self.assertIsInstance(payload["elapsed_ms"], int)
        self.assertGreaterEqual(payload["elapsed_ms"], 0)


class CacheTests(_PatchedComputeCase):
    def test_second_same_key_call_is_cached_no_recompute(self):
        h1 = _RouteHarness("")
        rdw._serve_duration_winrate(h1)
        self.assertFalse(json.loads(h1.sent_body)["cached"])
        h2 = _RouteHarness("")
        rdw._serve_duration_winrate(h2)
        self.assertEqual(h2.sent_status, 200)
        self.assertTrue(json.loads(h2.sent_body)["cached"])
        self.assertEqual(self.compute.call_count, 1)

    def test_cache_key_separates_by_champion(self):
        rdw._serve_duration_winrate(_RouteHarness("champion=64"))
        h = _RouteHarness("champion=99")
        rdw._serve_duration_winrate(h)
        self.assertFalse(json.loads(h.sent_body)["cached"])
        self.assertEqual(self.compute.call_count, 2)

    def test_cache_key_separates_by_mode(self):
        rdw._serve_duration_winrate(_RouteHarness("mode=aram"))
        h = _RouteHarness("mode=sr")
        rdw._serve_duration_winrate(h)
        self.assertFalse(json.loads(h.sent_body)["cached"])
        self.assertEqual(self.compute.call_count, 2)

    def test_reset_caches_forces_recompute(self):
        rdw._serve_duration_winrate(_RouteHarness(""))
        rdw._reset_caches()
        h = _RouteHarness("")
        rdw._serve_duration_winrate(h)
        self.assertFalse(json.loads(h.sent_body)["cached"])
        self.assertEqual(self.compute.call_count, 2)


class ErrorHandlingTests(unittest.TestCase):
    def setUp(self):
        rdw._reset_caches()
        self.addCleanup(rdw._reset_caches)

    def test_compute_raises_500_no_raw_leak(self):
        secret = "rewind_history.db at C:/secret/path exploded"
        with patch(_COMPUTE, side_effect=RuntimeError(secret)):
            h = _RouteHarness("")
            rdw._serve_duration_winrate(h)
        self.assertEqual(h.sent_status, 500)
        payload = json.loads(h.sent_body)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "internal error - see logs")
        self.assertNotIn("secret", h.sent_body.decode("utf-8"))


class DispatchRegistrationTests(unittest.TestCase):
    def test_route_registered(self):
        from dashboard import _dispatch
        routes = _dispatch._gather_get()
        matched = any(_safe_match(pred, "/api/duration-winrate")
                      for pred, _handler in routes)
        self.assertTrue(
            matched, "/api/duration-winrate not registered with dispatch")


def _safe_match(pred, path: str) -> bool:
    try:
        return bool(pred(path))
    except Exception:
        return False


if __name__ == "__main__":
    unittest.main()

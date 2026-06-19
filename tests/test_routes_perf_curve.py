"""Tests for ``dashboard.routes_perf_curve`` GET /api/perf-curve.

The corpus scan itself (``core.perf_curve.compute_perf_curve``) is covered by
tests/test_perf_curve.py. These cover the ROUTE layer only - query parsing
(mode + metric + champion), the 5min (mode, metric, champion) response cache,
the cached / elapsed_ms envelope, and the no-raw-error-leak 500 path - by
patching compute_perf_curve to a deterministic stub (touches NO real
rewind_history.db; clean-checkout / CI safe).
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from dashboard import routes_perf_curve as rpc

_COMPUTE = "dashboard.routes_perf_curve.perf_curve.compute_perf_curve"


class _RouteHarness:
    def __init__(self, qs: str = ""):
        self.path = "/api/perf-curve" + (f"?{qs}" if qs else "")
        self.sent_status = None
        self.sent_body = None
        self.sent_ct = None

    def _send(self, status, body, content_type):
        self.sent_status = status
        self.sent_body = body
        self.sent_ct = content_type


def _stub(**kw):
    return {
        "ok": True,
        "mode": kw.get("mode"),
        "metric": kw.get("metric"),
        "champion": kw.get("champion"),
        "n_games": 10,
        "min_games_n": 5,
        "minutes": [{"minute": 1, "win_avg": 1000.0, "win_n": 6,
                     "loss_avg": 600.0, "loss_n": 4}],
    }


class _PatchedComputeCase(unittest.TestCase):
    def setUp(self):
        rpc._reset_caches()
        self._p = patch(_COMPUTE, side_effect=_stub)
        self.compute = self._p.start()
        self.addCleanup(self._p.stop)
        self.addCleanup(rpc._reset_caches)


class ParsingTests(_PatchedComputeCase):
    def test_defaults_aram_gold(self):
        h = _RouteHarness("")
        rpc._serve_perf_curve(h)
        self.assertEqual(h.sent_status, 200)
        self.compute.assert_called_once_with(mode="aram", champion=None, metric="gold")

    def test_valid_mode_and_metric_passthrough(self):
        h = _RouteHarness("mode=sr&metric=cs")
        rpc._serve_perf_curve(h)
        self.assertEqual(h.sent_status, 200)
        self.compute.assert_called_once_with(mode="sr", champion=None, metric="cs")

    def test_bad_mode_400(self):
        h = _RouteHarness("mode=urf")
        rpc._serve_perf_curve(h)
        self.assertEqual(h.sent_status, 400)
        self.assertFalse(json.loads(h.sent_body)["ok"])
        self.compute.assert_not_called()

    def test_bad_metric_400(self):
        h = _RouteHarness("metric=damage")
        rpc._serve_perf_curve(h)
        self.assertEqual(h.sent_status, 400)
        self.assertIn("metric", json.loads(h.sent_body)["error"])
        self.compute.assert_not_called()

    def test_champion_int_passthrough(self):
        h = _RouteHarness("champion=64")
        rpc._serve_perf_curve(h)
        self.assertEqual(h.sent_status, 200)
        self.compute.assert_called_once_with(mode="aram", champion=64, metric="gold")

    def test_champion_non_int_400(self):
        h = _RouteHarness("champion=ashe")
        rpc._serve_perf_curve(h)
        self.assertEqual(h.sent_status, 400)
        self.compute.assert_not_called()

    def test_mode_checked_before_metric(self):
        h = _RouteHarness("mode=urf&metric=damage")
        rpc._serve_perf_curve(h)
        self.assertEqual(h.sent_status, 400)
        self.assertIn("mode", json.loads(h.sent_body)["error"])


class EnvelopeTests(_PatchedComputeCase):
    def test_first_call_not_cached_with_elapsed_ms(self):
        h = _RouteHarness("")
        rpc._serve_perf_curve(h)
        payload = json.loads(h.sent_body)
        self.assertFalse(payload["cached"])
        self.assertIsInstance(payload["elapsed_ms"], int)


class CacheTests(_PatchedComputeCase):
    def test_second_same_key_is_cached(self):
        rpc._serve_perf_curve(_RouteHarness(""))
        h = _RouteHarness("")
        rpc._serve_perf_curve(h)
        self.assertTrue(json.loads(h.sent_body)["cached"])
        self.assertEqual(self.compute.call_count, 1)

    def test_cache_key_separates_by_metric(self):
        rpc._serve_perf_curve(_RouteHarness("metric=gold"))
        h = _RouteHarness("metric=cs")
        rpc._serve_perf_curve(h)
        self.assertFalse(json.loads(h.sent_body)["cached"])
        self.assertEqual(self.compute.call_count, 2)

    def test_cache_key_separates_by_mode(self):
        rpc._serve_perf_curve(_RouteHarness("mode=aram"))
        h = _RouteHarness("mode=sr")
        rpc._serve_perf_curve(h)
        self.assertFalse(json.loads(h.sent_body)["cached"])
        self.assertEqual(self.compute.call_count, 2)


class ErrorHandlingTests(unittest.TestCase):
    def setUp(self):
        rpc._reset_caches()
        self.addCleanup(rpc._reset_caches)

    def test_compute_raises_500_no_raw_leak(self):
        secret = "rewind_history.db at C:/secret/path exploded"
        with patch(_COMPUTE, side_effect=RuntimeError(secret)):
            h = _RouteHarness("")
            rpc._serve_perf_curve(h)
        self.assertEqual(h.sent_status, 500)
        self.assertEqual(json.loads(h.sent_body)["error"], "internal error - see logs")
        self.assertNotIn("secret", h.sent_body.decode("utf-8"))


class DispatchRegistrationTests(unittest.TestCase):
    def test_route_registered(self):
        from dashboard import _dispatch
        routes = _dispatch._gather_get()
        matched = any(_safe_match(pred, "/api/perf-curve")
                      for pred, _handler in routes)
        self.assertTrue(matched, "/api/perf-curve not registered with dispatch")


def _safe_match(pred, path: str) -> bool:
    try:
        return bool(pred(path))
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    unittest.main()

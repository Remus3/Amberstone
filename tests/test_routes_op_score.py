"""Tests for ``dashboard.routes_op_score`` GET /api/op-score-curve.

The corpus scan itself (``core.op_score_curve.compute_op_score_curve``) is
covered by tests/test_op_score_curve.py. These cover the ROUTE layer only -
query parsing (mode + champion), the 5min (mode, champion) response cache, the
cached / elapsed_ms envelope, and the no-raw-error-leak 500 path - by patching
compute_op_score_curve to a deterministic stub (touches NO real
rewind_history.db; clean-checkout / CI safe).
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from dashboard import routes_op_score as ros

_COMPUTE = "dashboard.routes_op_score.op_score_curve.compute_op_score_curve"


class _RouteHarness:
    def __init__(self, qs: str = ""):
        self.path = "/api/op-score-curve" + (f"?{qs}" if qs else "")
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
        "metric": "opscore",
        "champion": kw.get("champion"),
        "n_games": 10,
        "min_games_n": 5,
        "weights": {"gold": 0.35, "xp": 0.2, "cs": 0.2, "combat": 0.25},
        "minutes": [{"minute": 1, "win_avg": 80.0, "win_n": 6,
                     "loss_avg": 60.0, "loss_n": 4}],
    }


class _PatchedComputeCase(unittest.TestCase):
    def setUp(self):
        ros._reset_caches()
        self._p = patch(_COMPUTE, side_effect=_stub)
        self.compute = self._p.start()
        self.addCleanup(self._p.stop)
        self.addCleanup(ros._reset_caches)


class ParsingTests(_PatchedComputeCase):
    def test_defaults_aram(self):
        h = _RouteHarness("")
        ros._serve_op_score(h)
        self.assertEqual(h.sent_status, 200)
        self.compute.assert_called_once_with(mode="aram", champion=None)

    def test_valid_mode_passthrough(self):
        h = _RouteHarness("mode=sr")
        ros._serve_op_score(h)
        self.assertEqual(h.sent_status, 200)
        self.compute.assert_called_once_with(mode="sr", champion=None)

    def test_bad_mode_400(self):
        h = _RouteHarness("mode=urf")
        ros._serve_op_score(h)
        self.assertEqual(h.sent_status, 400)
        self.assertFalse(json.loads(h.sent_body)["ok"])
        self.compute.assert_not_called()

    def test_champion_int_passthrough(self):
        h = _RouteHarness("champion=64")
        ros._serve_op_score(h)
        self.assertEqual(h.sent_status, 200)
        self.compute.assert_called_once_with(mode="aram", champion=64)

    def test_champion_non_int_400(self):
        h = _RouteHarness("champion=ashe")
        ros._serve_op_score(h)
        self.assertEqual(h.sent_status, 400)
        self.compute.assert_not_called()


class EnvelopeTests(_PatchedComputeCase):
    def test_first_call_not_cached_with_elapsed_ms(self):
        h = _RouteHarness("")
        ros._serve_op_score(h)
        payload = json.loads(h.sent_body)
        self.assertFalse(payload["cached"])
        self.assertIsInstance(payload["elapsed_ms"], int)


class CacheTests(_PatchedComputeCase):
    def test_second_same_key_is_cached(self):
        ros._serve_op_score(_RouteHarness(""))
        h = _RouteHarness("")
        ros._serve_op_score(h)
        self.assertTrue(json.loads(h.sent_body)["cached"])
        self.assertEqual(self.compute.call_count, 1)

    def test_cache_key_separates_by_mode(self):
        ros._serve_op_score(_RouteHarness("mode=aram"))
        h = _RouteHarness("mode=sr")
        ros._serve_op_score(h)
        self.assertFalse(json.loads(h.sent_body)["cached"])
        self.assertEqual(self.compute.call_count, 2)

    def test_cache_key_separates_by_champion(self):
        ros._serve_op_score(_RouteHarness("champion=64"))
        h = _RouteHarness("champion=99")
        ros._serve_op_score(h)
        self.assertFalse(json.loads(h.sent_body)["cached"])
        self.assertEqual(self.compute.call_count, 2)


class ErrorHandlingTests(unittest.TestCase):
    def setUp(self):
        ros._reset_caches()
        self.addCleanup(ros._reset_caches)

    def test_compute_raises_500_no_raw_leak(self):
        secret = "rewind_history.db at C:/secret/path exploded"
        with patch(_COMPUTE, side_effect=RuntimeError(secret)):
            h = _RouteHarness("")
            ros._serve_op_score(h)
        self.assertEqual(h.sent_status, 500)
        self.assertEqual(json.loads(h.sent_body)["error"], "internal error - see logs")
        self.assertNotIn("secret", h.sent_body.decode("utf-8"))


class DispatchRegistrationTests(unittest.TestCase):
    def test_route_registered(self):
        from dashboard import _dispatch
        routes = _dispatch._gather_get()
        matched = any(_safe_match(pred, "/api/op-score-curve")
                      for pred, _handler in routes)
        self.assertTrue(matched, "/api/op-score-curve not registered with dispatch")


def _safe_match(pred, path: str) -> bool:
    try:
        return bool(pred(path))
    except Exception:
        return False


if __name__ == "__main__":
    unittest.main()

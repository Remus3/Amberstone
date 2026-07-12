"""Tests for ``dashboard.routes_bench_rank_tier`` GET /api/rank-tier-bench.

The route surfaces a SELECTED rank-tier's average metrics (cs / kda / kp),
mode-specific, for the reworked overlay stats panel (overlay item 8). The data
reader (``core.rank_tier_bench``) runs on a committed estimate seed; these route
tests stub it to a deterministic grid + source so they touch no disk / live
endpoint. Mirrors tests/test_routes_bench_role_bracket.py.

Contract:
  GET /api/rank-tier-bench?tier=&mode=&bracket=
  -> {ok, tier, mode, bracket, role, source, n, stats:{cs,kda,kp:{avg}},
      cached, elapsed_ms}
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from dashboard import routes_bench_rank_tier as rrt

_GRID = "dashboard.routes_bench_rank_tier.bench.rank_tier_grid"
_SOURCE = "dashboard.routes_bench_rank_tier.bench.source"

_METRIC_KEYS = ("cs", "kda", "kp")


def _mode_block(cs: float, kda: float, kp: float) -> dict:
    """A laneless (role='all') mode block with both brackets holding the same
    estimate (the seed is bracket-agnostic)."""
    cell = {"cs": {"avg": cs}, "kda": {"avg": kda}, "kp": {"avg": kp}}
    return {"all": {"early": dict(cell), "mid": dict(cell)}}


def _stub_grid(tier: str, mode: str) -> dict:
    """Gold SR/ARAM populated; everything else empty (the no-benchmark path)."""
    if tier == "gold" and mode == "SR":
        return _mode_block(205, 2.5, 58)
    if tier == "gold" and mode == "ARAM":
        return _mode_block(55, 2.4, 62)
    return {}


class _RouteHarness:
    def __init__(self, qs: str = ""):
        self.path = "/api/rank-tier-bench" + (f"?{qs}" if qs else "")
        self.sent_status = None
        self.sent_body = None
        self.sent_ct = None

    def _send(self, status, body, content_type):
        self.sent_status = status
        self.sent_body = body
        self.sent_ct = content_type


class _PatchedCase(unittest.TestCase):
    def setUp(self):
        rrt._reset_caches()
        self._pg = patch(_GRID, side_effect=lambda t, m: _stub_grid(t, m))
        self._ps = patch(_SOURCE, return_value="static")
        self.grid = self._pg.start()
        self.source = self._ps.start()
        self.addCleanup(self._pg.stop)
        self.addCleanup(self._ps.stop)
        self.addCleanup(rrt._reset_caches)


class ParsingTests(_PatchedCase):
    def test_empty_tier_is_off_state(self):
        h = _RouteHarness("tier=&mode=SR")
        rrt._serve_rank_tier_bench(h)
        self.assertEqual(h.sent_status, 200)
        p = json.loads(h.sent_body)
        self.assertTrue(p["ok"])
        self.assertEqual(p["tier"], "")
        self.assertEqual(p["n"], 0)
        self.assertIsNone(p["stats"]["cs"]["avg"])

    def test_valid_tier_mode(self):
        h = _RouteHarness("tier=gold&mode=SR&bracket=mid")
        rrt._serve_rank_tier_bench(h)
        self.assertEqual(h.sent_status, 200)
        p = json.loads(h.sent_body)
        self.assertEqual(p["tier"], "gold")
        self.assertEqual(p["mode"], "SR")
        self.assertEqual(p["role"], "all")
        self.assertEqual(p["stats"]["cs"]["avg"], 205)
        self.assertEqual(p["stats"]["kda"]["avg"], 2.5)
        self.assertEqual(p["stats"]["kp"]["avg"], 58)
        self.assertEqual(p["n"], 3)

    def test_tier_case_insensitive(self):
        h = _RouteHarness("tier=GOLD&mode=aram")
        rrt._serve_rank_tier_bench(h)
        self.assertEqual(h.sent_status, 200)
        p = json.loads(h.sent_body)
        self.assertEqual(p["tier"], "gold")
        self.assertEqual(p["mode"], "ARAM")
        self.assertEqual(p["stats"]["cs"]["avg"], 55)

    def test_bad_tier_400(self):
        h = _RouteHarness("tier=radiant&mode=SR")
        rrt._serve_rank_tier_bench(h)
        self.assertEqual(h.sent_status, 400)
        self.assertFalse(json.loads(h.sent_body)["ok"])

    def test_bracket_defaults_to_mid(self):
        h = _RouteHarness("tier=gold&mode=SR&bracket=bogus")
        rrt._serve_rank_tier_bench(h)
        self.assertEqual(json.loads(h.sent_body)["bracket"], "mid")

    def test_early_bracket_passthrough(self):
        h = _RouteHarness("tier=gold&mode=SR&bracket=early")
        rrt._serve_rank_tier_bench(h)
        self.assertEqual(json.loads(h.sent_body)["bracket"], "early")


class NoBenchmarkTests(_PatchedCase):
    def test_arena_mode_is_no_benchmark(self):
        # Arena is a real mode with no seed -> soft empty, never a 400.
        h = _RouteHarness("tier=gold&mode=ARENA")
        rrt._serve_rank_tier_bench(h)
        self.assertEqual(h.sent_status, 200)
        p = json.loads(h.sent_body)
        self.assertTrue(p["ok"])
        self.assertEqual(p["mode"], "")
        self.assertEqual(p["n"], 0)
        self.assertEqual(set(p["stats"].keys()), set(_METRIC_KEYS))
        self.assertIsNone(p["stats"]["kda"]["avg"])

    def test_tier_with_no_cell_is_empty(self):
        h = _RouteHarness("tier=iron&mode=SR")  # not populated in the stub
        rrt._serve_rank_tier_bench(h)
        p = json.loads(h.sent_body)
        self.assertTrue(p["ok"])
        self.assertEqual(p["n"], 0)
        self.assertIsNone(p["stats"]["cs"]["avg"])


class ContractShapeTests(_PatchedCase):
    def setUp(self):
        super().setUp()
        h = _RouteHarness("tier=gold&mode=SR&bracket=mid")
        rrt._serve_rank_tier_bench(h)
        self.payload = json.loads(h.sent_body)

    def test_ok_true(self):
        self.assertTrue(self.payload["ok"])

    def test_source_echoed(self):
        self.assertEqual(self.payload["source"], "static")

    def test_stats_has_metric_keys(self):
        self.assertEqual(set(self.payload["stats"].keys()), set(_METRIC_KEYS))

    def test_each_stat_has_avg(self):
        for k in _METRIC_KEYS:
            self.assertIn("avg", self.payload["stats"][k], k)

    def test_envelope_fields(self):
        self.assertFalse(self.payload["cached"])
        self.assertIsInstance(self.payload["elapsed_ms"], int)
        self.assertGreaterEqual(self.payload["elapsed_ms"], 0)


class CacheTests(_PatchedCase):
    def test_second_same_call_is_cached(self):
        rrt._serve_rank_tier_bench(_RouteHarness("tier=gold&mode=SR&bracket=mid"))
        h = _RouteHarness("tier=gold&mode=SR&bracket=mid")
        rrt._serve_rank_tier_bench(h)
        self.assertTrue(json.loads(h.sent_body)["cached"])

    def test_cache_key_separates_by_bracket(self):
        rrt._serve_rank_tier_bench(_RouteHarness("tier=gold&mode=SR&bracket=mid"))
        h = _RouteHarness("tier=gold&mode=SR&bracket=early")
        rrt._serve_rank_tier_bench(h)
        self.assertFalse(json.loads(h.sent_body)["cached"])


class ErrorHandlingTests(unittest.TestCase):
    def setUp(self):
        rrt._reset_caches()
        self.addCleanup(rrt._reset_caches)

    def test_reader_raises_500_no_raw_leak(self):
        secret = "rank_tier_averages.json at C:/secret/path exploded"
        with patch(_SOURCE, return_value="static"), \
                patch(_GRID, side_effect=RuntimeError(secret)):
            h = _RouteHarness("tier=gold&mode=SR")
            rrt._serve_rank_tier_bench(h)
        self.assertEqual(h.sent_status, 500)
        p = json.loads(h.sent_body)
        self.assertFalse(p["ok"])
        self.assertEqual(p["error"], "internal error - see logs")
        self.assertNotIn("secret", h.sent_body.decode("utf-8"))


class DispatchRegistrationTests(unittest.TestCase):
    def test_route_registered(self):
        from dashboard import _dispatch
        routes = _dispatch._gather_get()
        matched = any(_safe_match(pred, "/api/rank-tier-bench")
                      for pred, _handler in routes)
        self.assertTrue(
            matched, "/api/rank-tier-bench not registered with dispatch")


def _safe_match(pred, path: str) -> bool:
    try:
        return bool(pred(path))
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    unittest.main()

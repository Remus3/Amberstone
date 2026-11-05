"""True-audit regressions for dashboard.routes_bench_rank_tier (s144 cycle 114).

GET /api/rank-tier-bench feeds the overlay stats panel's benchmark column. The
route is the last boundary before the browser, and the static seed reaches it
UNVALIDATED (core.rank_tier_bench._load_static_grid returns the seed's "tiers"
dict as parsed; only the live rows are value-checked in _fold_rows). Findings:

  RM-1453 a non-finite avg (json.loads accepts NaN / Infinity) was forwarded,
             and json.dumps re-emits a bare NaN token that a browser JSON.parse
             rejects - the WHOLE body, not one cell.
  RM-1454 a bool / string / list / negative avg was forwarded and counted in
             `n`; the panel's _fmt renders Number(true) as "1".
  RM-1455 a malformed grid (non-dict grid, "all" bucket or bracket cell)
             raised AttributeError -> 500 instead of the documented soft empty.
  RM-1456 the cache-hit path called h._send (a socket write) while holding
             _CACHE_LOCK, so one stalled client blocked every other request.
  RM-1457 the cache TTL and elapsed_ms ran on the wall clock: a backward
             step made elapsed_ms negative and froze a cache entry past its TTL.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from dashboard import routes_bench_rank_tier as rrt

_GRID = "dashboard.routes_bench_rank_tier.bench.rank_tier_grid"
_SOURCE = "dashboard.routes_bench_rank_tier.bench.source"
_KEYS = ("cs", "kda", "kp")


def _strict_loads(body: bytes) -> dict:
    """Parse the way a browser JSON.parse does: NaN / Infinity are errors."""
    def _reject(tok):
        raise ValueError(f"non-standard JSON token {tok}")
    return json.loads(body.decode("utf-8"), parse_constant=_reject)


class _H:
    def __init__(self, qs: str = "tier=gold&mode=SR&bracket=mid"):
        self.path = "/api/rank-tier-bench?" + qs
        self.sent_status = None
        self.sent_body = None
        self.lock_held_during_send = None

    def _send(self, status, body, content_type):
        self.sent_status = status
        self.sent_body = body
        self.lock_held_during_send = rrt._CACHE_LOCK.locked()


def _serve(grid, qs: str = "tier=gold&mode=SR&bracket=mid") -> _H:
    h = _H(qs)
    with patch(_SOURCE, return_value="static"), \
            patch(_GRID, side_effect=lambda t, m: grid):
        rrt._serve_rank_tier_bench(h)
    return h


def _block(cs, kda, kp) -> dict:
    return {"all": {"mid": {"cs": {"avg": cs}, "kda": {"avg": kda},
                            "kp": {"avg": kp}}}}


class _Base(unittest.TestCase):
    def setUp(self):
        rrt._reset_caches()
        self.addCleanup(rrt._reset_caches)


class NonFiniteAvgTests(_Base):
    """RM-1453."""

    def test_nan_avg_keeps_body_strict_json(self):
        h = _serve(_block(float("nan"), 2.5, 58))
        self.assertEqual(h.sent_status, 200)
        p = _strict_loads(h.sent_body)
        self.assertIsNone(p["stats"]["cs"]["avg"])
        self.assertEqual(p["stats"]["kda"]["avg"], 2.5)
        self.assertEqual(p["n"], 2)

    def test_infinities_dropped(self):
        h = _serve(_block(float("inf"), float("-inf"), 58))
        p = _strict_loads(h.sent_body)
        self.assertIsNone(p["stats"]["cs"]["avg"])
        self.assertIsNone(p["stats"]["kda"]["avg"])
        self.assertEqual(p["n"], 1)


class JunkAvgTypeTests(_Base):
    """RM-1454."""

    def test_bool_avg_is_not_an_average(self):
        p = _strict_loads(_serve(_block(True, False, 58)).sent_body)
        self.assertIsNone(p["stats"]["cs"]["avg"])
        self.assertIsNone(p["stats"]["kda"]["avg"])
        self.assertEqual(p["n"], 1)

    def test_string_and_list_avgs_dropped(self):
        p = _strict_loads(_serve(_block("205", [1], {"x": 1})).sent_body)
        for k in _KEYS:
            self.assertIsNone(p["stats"][k]["avg"], k)
        self.assertEqual(p["n"], 0)

    def test_negative_avg_dropped(self):
        p = _strict_loads(_serve(_block(-5, 2.5, 58)).sent_body)
        self.assertIsNone(p["stats"]["cs"]["avg"])
        self.assertEqual(p["n"], 2)

    def test_zero_and_float_avgs_kept(self):
        p = _strict_loads(_serve(_block(0, 2.5, 58)).sent_body)
        self.assertEqual(p["stats"]["cs"]["avg"], 0)
        self.assertEqual(p["n"], 3)


class MalformedGridTests(_Base):
    """RM-1455: a malformed grid degrades to the soft empty, never a 500."""

    def _assert_soft_empty(self, grid):
        h = _serve(grid)
        self.assertEqual(h.sent_status, 200, grid)
        p = _strict_loads(h.sent_body)
        self.assertTrue(p["ok"])
        self.assertEqual(p["n"], 0)
        self.assertEqual(set(p["stats"]), set(_KEYS))
        for k in _KEYS:
            self.assertEqual(p["stats"][k], {"avg": None})

    def test_all_bucket_is_a_list(self):
        self._assert_soft_empty({"all": ["mid"]})

    def test_bracket_cell_is_a_list(self):
        self._assert_soft_empty({"all": {"mid": [1, 2]}})

    def test_bracket_cell_is_a_string(self):
        self._assert_soft_empty({"all": {"mid": "cs"}})

    def test_grid_is_none(self):
        self._assert_soft_empty(None)

    def test_grid_is_a_list(self):
        self._assert_soft_empty([{"all": {}}])

    def test_metric_value_not_a_dict(self):
        self._assert_soft_empty({"all": {"mid": {"cs": 205, "kda": [2.5],
                                                 "kp": None}}})


class SendOutsideLockTests(_Base):
    """RM-1456: no socket write while _CACHE_LOCK is held."""

    def test_cache_hit_sends_outside_the_lock(self):
        grid = _block(205, 2.5, 58)
        _serve(grid)                       # prime
        h = _serve(grid)                   # cache hit
        self.assertTrue(json.loads(h.sent_body)["cached"])
        self.assertFalse(h.lock_held_during_send)

    def test_cache_miss_sends_outside_the_lock(self):
        h = _serve(_block(205, 2.5, 58))
        self.assertFalse(json.loads(h.sent_body)["cached"])
        self.assertFalse(h.lock_held_during_send)

    def test_cached_payload_not_mutated_by_a_hit(self):
        grid = _block(205, 2.5, 58)
        _serve(grid)
        _serve(grid)
        with rrt._CACHE_LOCK:
            stored = next(iter(rrt._CACHE.values()))[1]
        self.assertNotIn("cached", stored)
        self.assertNotIn("elapsed_ms", stored)


class MonotonicClockTests(_Base):
    """RM-1457."""

    def test_backward_wall_clock_never_negative_elapsed(self):
        ticks = iter(range(10_000_000, 0, -3600))   # wall clock steps BACK

        def _wall():
            return float(next(ticks))

        with patch("dashboard.routes_bench_rank_tier.time.time",
                   side_effect=_wall):
            h = _serve(_block(205, 2.5, 58))
        p = json.loads(h.sent_body)
        self.assertGreaterEqual(p["elapsed_ms"], 0)

    def test_cache_expires_on_the_route_clock(self):
        now = [1000.0]
        grid = _block(205, 2.5, 58)
        with patch.object(rrt, "_clock", side_effect=lambda: now[0]):
            _serve(grid)
            self.assertTrue(json.loads(_serve(grid).sent_body)["cached"])
            now[0] += rrt._CACHE_TTL_S + 1.0
            self.assertFalse(json.loads(_serve(grid).sent_body)["cached"])

    def test_route_clock_is_monotonic(self):
        import time
        self.assertIs(rrt._clock, time.monotonic)


if __name__ == "__main__":
    unittest.main()

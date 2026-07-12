"""Tests for ``dashboard.routes_bench_role_bracket`` GET /api/role-bracket-bench.

The route surfaces the operator's OWN role x game-time-bracket personal averages
(level / cs / teamfight / kda) for the WP-A4 vertical "You vs benchmark" stats
panel. The data reader (``core.role_bracket_bench.role_bracket_grid``) reads the
rewind match corpus (gitignored, absent on CI); these route tests stub it to a
deterministic grid so they touch NO real DB (clean-checkout / CI safe). One
contract test reads the REAL corpus and SKIPS when it is absent.

Contract (per docs/OVERLAY_BUILD_MASTER_PLAN.md WP-A4a):
  GET /api/role-bracket-bench?role=&bracket=
  -> {ok, role, bracket, n, stats:{lvl,cs,tf,kda:{avg,...}}, cached, elapsed_ms}
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from dashboard import routes_bench_role_bracket as rbb

_GRID = "dashboard.routes_bench_role_bracket.bench.role_bracket_grid"

_STAT_KEYS = ("lvl", "cs", "tf", "kda")


def _cell(lvl: float, cs: float, tf: float, kda: float, n: int) -> dict:
    return {
        "n": n,
        "lvl": {"avg": lvl, "p50": lvl, "n": n},
        "cs": {"avg": cs, "p50": cs, "n": n},
        "tf": {"avg": tf, "p50": tf, "n": n},
        "kda": {"avg": kda, "p50": kda, "n": n},
    }


def _stub_grid() -> dict:
    """A small role x bracket grid. mid has both brackets; bot has only mid; top
    is entirely absent (the empty-cell path). The "late" bracket was retired in
    the overlay item 8 lock-step (early < 14:00, else mid)."""
    return {
        "mid": {
            "early": _cell(12, 150, 55.0, 3.1, 8),
            "mid": _cell(15, 210, 58.0, 3.4, 20),
        },
        "bot": {"mid": _cell(14, 240, 50.0, 2.8, 30)},
    }


class _RouteHarness:
    def __init__(self, qs: str = ""):
        self.path = "/api/role-bracket-bench" + (f"?{qs}" if qs else "")
        self.sent_status = None
        self.sent_body = None
        self.sent_ct = None

    def _send(self, status, body, content_type):
        self.sent_status = status
        self.sent_body = body
        self.sent_ct = content_type


class _PatchedCase(unittest.TestCase):
    def setUp(self):
        rbb._reset_caches()
        self._p = patch(_GRID, side_effect=lambda: _stub_grid())
        self.grid = self._p.start()
        self.addCleanup(self._p.stop)
        self.addCleanup(rbb._reset_caches)


class ParsingTests(_PatchedCase):
    def test_defaults_when_empty(self):
        h = _RouteHarness("role=&bracket=")
        rbb._serve_role_bracket_bench(h)
        self.assertEqual(h.sent_status, 200)
        self.assertEqual(h.sent_ct, "application/json")
        p = json.loads(h.sent_body)
        self.assertIn(p["role"], rbb.VALID_ROLES)
        self.assertIn(p["bracket"], rbb.VALID_BRACKETS)

    def test_valid_passthrough(self):
        h = _RouteHarness("role=mid&bracket=early")
        rbb._serve_role_bracket_bench(h)
        self.assertEqual(h.sent_status, 200)
        p = json.loads(h.sent_body)
        self.assertEqual(p["role"], "mid")
        self.assertEqual(p["bracket"], "early")

    def test_bad_role_400(self):
        h = _RouteHarness("role=wizard&bracket=mid")
        rbb._serve_role_bracket_bench(h)
        self.assertEqual(h.sent_status, 400)
        self.assertFalse(json.loads(h.sent_body)["ok"])

    def test_bad_bracket_400(self):
        h = _RouteHarness("role=mid&bracket=instant")
        rbb._serve_role_bracket_bench(h)
        self.assertEqual(h.sent_status, 400)
        self.assertFalse(json.loads(h.sent_body)["ok"])

    def test_role_alias_normalized(self):
        # common UI aliases map onto the canonical role keys
        for raw, canon in (("adc", "bot"), ("middle", "mid"), ("sup", "support")):
            rbb._reset_caches()
            h = _RouteHarness(f"role={raw}&bracket=mid")
            rbb._serve_role_bracket_bench(h)
            self.assertEqual(h.sent_status, 200, raw)
            self.assertEqual(json.loads(h.sent_body)["role"], canon, raw)


class ContractShapeTests(_PatchedCase):
    def setUp(self):
        super().setUp()
        h = _RouteHarness("role=mid&bracket=mid")
        rbb._serve_role_bracket_bench(h)
        self.payload = json.loads(h.sent_body)

    def test_ok_true(self):
        self.assertTrue(self.payload["ok"])

    def test_role_bracket_echoed(self):
        self.assertEqual(self.payload["role"], "mid")
        self.assertEqual(self.payload["bracket"], "mid")

    def test_stats_has_four_keys(self):
        self.assertEqual(set(self.payload["stats"].keys()), set(_STAT_KEYS))

    def test_each_stat_has_avg(self):
        for k in _STAT_KEYS:
            self.assertIn("avg", self.payload["stats"][k], k)

    def test_kda_avg_shape(self):
        # the plan's named contract: stats.kda carries an avg
        self.assertIn("avg", self.payload["stats"]["kda"])
        self.assertIsInstance(self.payload["stats"]["kda"]["avg"], (int, float))

    def test_n_present(self):
        self.assertIn("n", self.payload)
        self.assertEqual(self.payload["n"], 20)


class EmptyCellTests(_PatchedCase):
    def test_absent_role_is_ok_n_zero(self):
        h = _RouteHarness("role=top&bracket=mid")  # top absent in the stub grid
        rbb._serve_role_bracket_bench(h)
        self.assertEqual(h.sent_status, 200)
        p = json.loads(h.sent_body)
        self.assertTrue(p["ok"])
        self.assertEqual(p["n"], 0)
        self.assertEqual(set(p["stats"].keys()), set(_STAT_KEYS))
        # an empty cell still carries the stat keys (avg None) so the panel
        # renders an empty column rather than crashing on a missing key.
        self.assertIsNone(p["stats"]["lvl"].get("avg"))


class EnvelopeTests(_PatchedCase):
    def test_first_call_not_cached_with_elapsed_ms(self):
        h = _RouteHarness("role=mid&bracket=mid")
        rbb._serve_role_bracket_bench(h)
        p = json.loads(h.sent_body)
        self.assertFalse(p["cached"])
        self.assertIsInstance(p["elapsed_ms"], int)
        self.assertGreaterEqual(p["elapsed_ms"], 0)


class CacheTests(_PatchedCase):
    def test_second_same_call_is_cached(self):
        rbb._serve_role_bracket_bench(_RouteHarness("role=mid&bracket=mid"))
        h = _RouteHarness("role=mid&bracket=mid")
        rbb._serve_role_bracket_bench(h)
        self.assertTrue(json.loads(h.sent_body)["cached"])
        self.assertEqual(self.grid.call_count, 1)

    def test_cache_key_separates_by_cell(self):
        rbb._serve_role_bracket_bench(_RouteHarness("role=mid&bracket=mid"))
        h = _RouteHarness("role=bot&bracket=mid")
        rbb._serve_role_bracket_bench(h)
        self.assertFalse(json.loads(h.sent_body)["cached"])
        self.assertEqual(self.grid.call_count, 2)


class ErrorHandlingTests(unittest.TestCase):
    def setUp(self):
        rbb._reset_caches()
        self.addCleanup(rbb._reset_caches)

    def test_reader_raises_500_no_raw_leak(self):
        secret = "rewind_history.db at C:/secret/path exploded"
        with patch(_GRID, side_effect=RuntimeError(secret)):
            h = _RouteHarness("role=mid&bracket=mid")
            rbb._serve_role_bracket_bench(h)
        self.assertEqual(h.sent_status, 500)
        p = json.loads(h.sent_body)
        self.assertFalse(p["ok"])
        self.assertEqual(p["error"], "internal error - see logs")
        self.assertNotIn("secret", h.sent_body.decode("utf-8"))


class DispatchRegistrationTests(unittest.TestCase):
    def test_route_registered(self):
        from dashboard import _dispatch
        routes = _dispatch._gather_get()
        matched = any(_safe_match(pred, "/api/role-bracket-bench")
                      for pred, _handler in routes)
        self.assertTrue(
            matched, "/api/role-bracket-bench not registered with dispatch")


class LiveDataContractTests(unittest.TestCase):
    """Contract test against the REAL rewind corpus. Proves the live grid shape
    agrees with the wire contract. SKIPS when the gitignored DB is absent (CI)."""

    def setUp(self):
        rbb._reset_caches()
        self.addCleanup(rbb._reset_caches)

    def test_live_grid_contract(self):
        from core import role_bracket_bench as bench
        if not bench.corpus_present():
            self.skipTest("rewind_history.db not present")
        grid = bench.role_bracket_grid()
        # at least one populated cell over the real corpus
        any_cell = any(grid.get(r, {}).get(b) for r in bench.VALID_ROLES
                       for b in bench.VALID_BRACKETS)
        self.assertTrue(any_cell, "real corpus should populate >=1 role/bracket cell")
        h = _RouteHarness("role=bot&bracket=mid")
        rbb._serve_role_bracket_bench(h)
        self.assertEqual(h.sent_status, 200)
        p = json.loads(h.sent_body)
        self.assertTrue(p["ok"])
        self.assertEqual(set(p["stats"].keys()), set(_STAT_KEYS))


def _safe_match(pred, path: str) -> bool:
    try:
        return bool(pred(path))
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    unittest.main()

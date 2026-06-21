"""Tests for ``dashboard.routes_champ_benchmarks`` GET /api/champ-benchmarks.

The reader itself (``core.benchmarks.rows_for_mode``) is covered by
tests/test_benchmarks.py. These tests cover the ROUTE layer only - query
parsing, the 5min (mode,) in-process response cache, the contract shaping
(only the 5 column metrics shaped into stats, the games >= min_games gate,
the cached / elapsed_ms envelope fields), and the no-raw-error-leak 500 path
- by patching ``rows_for_mode`` to a deterministic stub, so they touch NO real
champion_benchmarks.json (clean-checkout / CI safe).

One contract test reads the REAL data file (it is checked in, not gitignored)
to prove the live shape agrees with the wire contract.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard import routes_champ_benchmarks as rcb

_ROWS = "dashboard.routes_champ_benchmarks.benchmarks.rows_for_mode"

# The 5 column metrics the contract shapes into stats.
_COLS = ["cs_at_10", "gold_at_10", "gold_at_15", "kill_participation_pct", "level_at_10"]


def _metric(p50: float, n: int = 12) -> dict:
    return {"p25": p50 - 1, "p50": p50, "p75": p50 + 1, "avg": p50,
            "n": n, "weighted_n": float(n)}


def _stub_rows(mode: str) -> list[dict]:
    """Two gated champs + one below the gate + one missing a column metric."""
    return [
        {"champion": "Vayne", "games": 50,
         "metrics": {m: _metric(6.0 + i) for i, m in enumerate(_COLS)}},
        {"champion": "Jinx", "games": 12,
         # drop gold_at_15 to prove a missing column is null/omitted, not crash
         "metrics": {m: _metric(7.0) for m in _COLS if m != "gold_at_15"}},
        {"champion": "Teemo", "games": 2,  # below min_games gate (3) -> excluded
         "metrics": {m: _metric(5.0) for m in _COLS}},
    ]


class _RouteHarness:
    def __init__(self, qs: str = ""):
        self.path = "/api/champ-benchmarks" + (f"?{qs}" if qs else "")
        self.sent_status = None
        self.sent_body = None
        self.sent_ct = None

    def _send(self, status, body, content_type):
        self.sent_status = status
        self.sent_body = body
        self.sent_ct = content_type


class _PatchedCase(unittest.TestCase):
    def setUp(self):
        rcb._reset_caches()
        self._p = patch(_ROWS, side_effect=_stub_rows)
        self.rows = self._p.start()
        self.addCleanup(self._p.stop)
        self.addCleanup(rcb._reset_caches)


class ParsingTests(_PatchedCase):
    def test_default_mode_is_sr(self):
        h = _RouteHarness("")
        rcb._serve_champ_benchmarks(h)
        self.assertEqual(h.sent_status, 200)
        self.assertEqual(h.sent_ct, "application/json")
        self.assertEqual(json.loads(h.sent_body)["mode"], "sr")

    def test_valid_mode_passthrough(self):
        h = _RouteHarness("mode=sr")
        rcb._serve_champ_benchmarks(h)
        self.assertEqual(h.sent_status, 200)
        self.assertEqual(json.loads(h.sent_body)["mode"], "sr")

    def test_bad_mode_400(self):
        h = _RouteHarness("mode=urf")
        rcb._serve_champ_benchmarks(h)
        self.assertEqual(h.sent_status, 400)
        self.assertEqual(h.sent_ct, "application/json")
        self.assertFalse(json.loads(h.sent_body)["ok"])

    def test_arena_mode_valid(self):
        h = _RouteHarness("mode=arena")
        rcb._serve_champ_benchmarks(h)
        self.assertEqual(h.sent_status, 200)
        self.assertEqual(json.loads(h.sent_body)["mode"], "arena")


class ContractShapeTests(_PatchedCase):
    def setUp(self):
        super().setUp()
        h = _RouteHarness("mode=sr")
        rcb._serve_champ_benchmarks(h)
        self.payload = json.loads(h.sent_body)

    def test_ok_true(self):
        self.assertTrue(self.payload["ok"])

    def test_metrics_list_present(self):
        self.assertEqual(self.payload["metrics"], _COLS)

    def test_min_games_is_three(self):
        self.assertEqual(self.payload["min_games"], 3)

    def test_rows_is_list(self):
        self.assertIsInstance(self.payload["rows"], list)

    def test_n_matches_row_count(self):
        self.assertEqual(self.payload["n"], len(self.payload["rows"]))

    def test_sample_gate_excludes_low_games(self):
        names = [r["champion"] for r in self.payload["rows"]]
        self.assertIn("Vayne", names)
        self.assertIn("Jinx", names)
        self.assertNotIn("Teemo", names)  # games=2 < min_games

    def test_no_row_below_min_games(self):
        for r in self.payload["rows"]:
            self.assertGreaterEqual(r["games"], 3)

    def test_each_row_has_champion_games_stats(self):
        for r in self.payload["rows"]:
            self.assertIn("champion", r)
            self.assertIn("games", r)
            self.assertIn("stats", r)
            self.assertIsInstance(r["stats"], dict)

    def test_stats_only_contain_column_metrics(self):
        for r in self.payload["rows"]:
            for k in r["stats"]:
                self.assertIn(k, _COLS)

    def test_present_stat_has_p50(self):
        vayne = next(r for r in self.payload["rows"] if r["champion"] == "Vayne")
        self.assertIn("p50", vayne["stats"]["cs_at_10"])

    def test_missing_metric_omitted_or_null(self):
        jinx = next(r for r in self.payload["rows"] if r["champion"] == "Jinx")
        val = jinx["stats"].get("gold_at_15")
        self.assertIsNone(val)  # omitted or explicit null - both read as None

    def test_rows_sorted_by_games_desc(self):
        games = [r["games"] for r in self.payload["rows"]]
        self.assertEqual(games, sorted(games, reverse=True))


class EnvelopeTests(_PatchedCase):
    def test_first_call_not_cached_with_elapsed_ms(self):
        h = _RouteHarness("")
        rcb._serve_champ_benchmarks(h)
        payload = json.loads(h.sent_body)
        self.assertFalse(payload["cached"])
        self.assertIsInstance(payload["elapsed_ms"], int)
        self.assertGreaterEqual(payload["elapsed_ms"], 0)


class CacheTests(_PatchedCase):
    def test_second_same_mode_call_is_cached(self):
        rcb._serve_champ_benchmarks(_RouteHarness("mode=sr"))
        h = _RouteHarness("mode=sr")
        rcb._serve_champ_benchmarks(h)
        self.assertTrue(json.loads(h.sent_body)["cached"])
        self.assertEqual(self.rows.call_count, 1)

    def test_cache_key_separates_by_mode(self):
        rcb._serve_champ_benchmarks(_RouteHarness("mode=sr"))
        h = _RouteHarness("mode=aram")
        rcb._serve_champ_benchmarks(h)
        self.assertFalse(json.loads(h.sent_body)["cached"])
        self.assertEqual(self.rows.call_count, 2)


class EmptyModeTests(_PatchedCase):
    def test_empty_rows_ok_true_n_zero(self):
        with patch(_ROWS, return_value=[]):
            rcb._reset_caches()
            h = _RouteHarness("mode=arena")
            rcb._serve_champ_benchmarks(h)
        payload = json.loads(h.sent_body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["n"], 0)
        self.assertEqual(payload["rows"], [])


class ErrorHandlingTests(unittest.TestCase):
    def setUp(self):
        rcb._reset_caches()
        self.addCleanup(rcb._reset_caches)

    def test_reader_raises_500_no_raw_leak(self):
        secret = "champion_benchmarks.json at C:/secret/path exploded"
        with patch(_ROWS, side_effect=RuntimeError(secret)):
            h = _RouteHarness("")
            rcb._serve_champ_benchmarks(h)
        self.assertEqual(h.sent_status, 500)
        payload = json.loads(h.sent_body)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "internal error - see logs")
        self.assertNotIn("secret", h.sent_body.decode("utf-8"))


class DispatchRegistrationTests(unittest.TestCase):
    def test_route_registered(self):
        from dashboard import _dispatch
        routes = _dispatch._gather_get()
        matched = any(_safe_match(pred, "/api/champ-benchmarks")
                      for pred, _handler in routes)
        self.assertTrue(
            matched, "/api/champ-benchmarks not registered with dispatch")


class LiveDataContractTests(unittest.TestCase):
    """Contract test against the REAL checked-in champion_benchmarks.json.

    Proves the live data shape agrees with the wire contract for the populated
    mode (sr). No mock - exercises core.benchmarks.rows_for_mode end-to-end.
    """

    def setUp(self):
        rcb._reset_caches()
        self.addCleanup(rcb._reset_caches)

    def test_sr_contract_holds_on_real_data(self):
        path = (Path(__file__).resolve().parent.parent / "data"
                / "coach_reference" / "champion_benchmarks.json")
        if not path.is_file():
            self.skipTest("champion_benchmarks.json not present")
        h = _RouteHarness("mode=sr")
        rcb._serve_champ_benchmarks(h)
        self.assertEqual(h.sent_status, 200)
        payload = json.loads(h.sent_body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], "sr")
        self.assertGreater(payload["n"], 0, "real sr corpus should be non-empty")
        for r in payload["rows"]:
            self.assertGreaterEqual(r["games"], 3)
            self.assertIn("stats", r)


def _safe_match(pred, path: str) -> bool:
    try:
        return bool(pred(path))
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    unittest.main()

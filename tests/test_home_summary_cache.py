"""Route TTL cache for /api/home/summary (dashboard/routes_history.py).

Why this exists: _serve_home_summary re-ran a SQLite aggregate over
data/match_history.db (about 17 MB) on EVERY hit, and web/js/main.js:3106
polls the route every 20000ms per open tab. Measured in-process cost of
dashboard.builders._build_home_summary on the live DB this run: 9.0ms min /
20.3ms avg / 83.8ms max over 7 calls (cold first call 83.8ms).

These tests pin INVARIANTS, never wall-clock time:
  (a) a second call inside the TTL does not re-enter the builder;
  (b) a call after the TTL expires rebuilds;
  (c) distinct ?mode= values never share a cache entry;
  (d) the TTL constant stays in the operator-agreed 15-30s band;
  (e) a builder failure is NOT cached (the 500 path must not poison
      the entry, or one transient DB error would stick for the TTL).

The clock is injected by replacing the module-level ``time`` binding, so no
test sleeps and the real time module is never mutated.

Verified API surface (nothing here is assumed):
  dashboard/routes_history.py:83   _serve_home_summary(h)
  dashboard/routes_history.py:70   _parse_home_mode(path) -> str | None
  dashboard/routes_history.py:67   _HOME_MODES = {"SR", "ARAM", "ARENA"}
  dashboard/builders_home.py:185   _build_home_summary(mode_filter=None) -> dict
  web/js/main.js:3106              _HOME intervalMs: 20000
The stub-handler shape (``path`` attribute + ``_send(status, body, ctype)``)
mirrors tests/test_routes_post_game_rubric_obj.py:30-37.
ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dashboard import routes_history as rh  # noqa: E402


class _StubHandler:
    """Minimal BaseHTTPRequestHandler stand-in - the route only uses these."""

    def __init__(self, path: str):
        self.path = path
        self.responses: list[tuple[int, bytes, str]] = []

    def _send(self, status: int, body: bytes,
              content_type: str = "application/json") -> None:
        self.responses.append((status, body, content_type))


class _FakeClock:
    """Replaces the module-level ``time`` binding, not the time module."""

    def __init__(self, now: float = 1000.0):
        self.now = now

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _CountingBuilder:
    """Stands in for _build_home_summary and records every entry."""

    def __init__(self):
        self.calls: list[str | None] = []

    def __call__(self, mode_filter=None):
        self.calls.append(mode_filter)
        return {"mode_filter": mode_filter or "ALL",
                "call_index": len(self.calls)}


class HomeSummaryCacheTests(unittest.TestCase):

    def setUp(self):
        rh._CACHE.clear()
        self.addCleanup(rh._CACHE.clear)
        self.clock = _FakeClock()
        self.builder = _CountingBuilder()

    def _serve(self, path: str = "/api/home/summary"):
        with mock.patch.object(rh, "time", self.clock), \
                mock.patch.object(rh, "_build_home_summary", self.builder):
            h = _StubHandler(path)
            rh._serve_home_summary(h)
            return h.responses

    # -- (a) hit inside the TTL --------------------------------------

    def test_second_call_inside_ttl_does_not_rebuild(self):
        first = self._serve()
        second = self._serve()
        self.assertEqual(len(self.builder.calls), 1,
                         "the second call re-entered the builder")
        self.assertEqual(first[0][0], 200)
        self.assertEqual(second[0][0], 200)
        self.assertEqual(json.loads(first[0][1]), json.loads(second[0][1]))

    def test_many_calls_inside_ttl_collapse_to_one_build(self):
        for _ in range(12):
            self._serve()
        self.assertEqual(len(self.builder.calls), 1)

    def test_cached_payload_survives_caller_mutation(self):
        served = self._serve()
        payload = json.loads(served[0][1])
        payload["call_index"] = 999
        again = json.loads(self._serve()[0][1])
        self.assertEqual(again["call_index"], 1)

    # -- (b) rebuild after expiry ------------------------------------

    def test_call_after_ttl_expiry_rebuilds(self):
        self._serve()
        self.clock.advance(rh._CACHE_TTL_S + 1.0)
        self._serve()
        self.assertEqual(len(self.builder.calls), 2)

    def test_call_just_inside_expiry_still_hits(self):
        self._serve()
        self.clock.advance(rh._CACHE_TTL_S - 0.5)
        self._serve()
        self.assertEqual(len(self.builder.calls), 1)

    # -- (c) per-mode keying -----------------------------------------

    def test_distinct_modes_do_not_share_an_entry(self):
        sr = json.loads(self._serve("/api/home/summary?mode=SR")[0][1])
        aram = json.loads(self._serve("/api/home/summary?mode=ARAM")[0][1])
        self.assertEqual(len(self.builder.calls), 2)
        self.assertEqual(self.builder.calls, ["SR", "ARAM"])
        self.assertEqual(sr["mode_filter"], "SR")
        self.assertEqual(aram["mode_filter"], "ARAM")

    def test_unfiltered_all_is_its_own_entry(self):
        self._serve("/api/home/summary")
        self._serve("/api/home/summary?mode=SR")
        self.assertEqual(self.builder.calls, [None, "SR"])

    def test_every_home_mode_gets_its_own_entry(self):
        for mode in sorted(rh._HOME_MODES):
            self._serve(f"/api/home/summary?mode={mode}")
        self.assertEqual(len(self.builder.calls), len(rh._HOME_MODES))
        self.assertEqual(sorted(rh._CACHE), sorted(rh._HOME_MODES))

    def test_non_whitelisted_mode_shares_the_unfiltered_entry(self):
        # _parse_home_mode maps tft / garbage to None, so they must land on
        # the SAME entry as an absent ?mode= - not a per-string cache key.
        self._serve("/api/home/summary?mode=tft")
        self._serve("/api/home/summary?mode=garbage")
        self._serve("/api/home/summary")
        self.assertEqual(self.builder.calls, [None])

    def test_mode_parsing_is_case_insensitive_into_one_entry(self):
        self._serve("/api/home/summary?mode=aram")
        self._serve("/api/home/summary?mode=ARAM")
        self.assertEqual(self.builder.calls, ["ARAM"])

    # -- (d) TTL band ------------------------------------------------

    def test_ttl_sits_in_the_agreed_band(self):
        self.assertGreaterEqual(rh._CACHE_TTL_S, 15.0)
        self.assertLessEqual(rh._CACHE_TTL_S, 30.0)

    def test_cache_triple_is_present(self):
        self.assertIsInstance(rh._CACHE, dict)
        self.assertTrue(hasattr(rh._CACHE_LOCK, "acquire"))
        self.assertTrue(hasattr(rh._CACHE_LOCK, "release"))

    # -- (e) failures are not cached ---------------------------------

    def test_builder_failure_returns_500_and_is_not_cached(self):
        def _boom(mode_filter=None):
            raise RuntimeError("db exploded")

        with mock.patch.object(rh, "time", self.clock), \
                mock.patch.object(rh, "_build_home_summary", _boom):
            h = _StubHandler("/api/home/summary")
            rh._serve_home_summary(h)
        self.assertEqual(h.responses[0][0], 500)
        self.assertEqual(rh._CACHE, {},
                         "a failed build poisoned the cache")

        served = self._serve()
        self.assertEqual(served[0][0], 200)
        self.assertEqual(len(self.builder.calls), 1)

    def test_error_body_stays_generic(self):
        def _boom(mode_filter=None):
            raise RuntimeError(r"C:\secret\path leaked")

        with mock.patch.object(rh, "time", self.clock), \
                mock.patch.object(rh, "_build_home_summary", _boom):
            h = _StubHandler("/api/home/summary")
            rh._serve_home_summary(h)
        self.assertEqual(json.loads(h.responses[0][1]),
                         {"error": rh._GENERIC_ERR})


if __name__ == "__main__":
    unittest.main()

"""Deep-audit cycle 8 P2 W1 dashboard slice B regression tests.

Covers the /api/state hot-path pipeline fixes:

  1. _adaptation_latch.compute() no-raise contract: a malformed opponent
     creep_score (None / non-numeric) must not raise out of compute() -
     it is called UNWRAPPED at dashboard/_state_builder.py:263, so a
     raise 500s /api/state at the 15:00 latch tick.
     (API: dashboard/_adaptation_latch.py:47 reset, :109 compute)

  2. _screen_read.trigger_screen_read() inflight wedge: if the pending
     _write raises (os.replace WinError 5 flake is a known Windows
     reality), _inflight stayed True forever and every later SCREEN READ
     click silently no-opped until restart.
     (API: dashboard/_screen_read.py:157 trigger_screen_read,
      :177 _reset_inflight_for_test, :134 _write)

  3. routes_state SSE build dedupe: _serve_state_stream re-built state
     per subscriber per 1s tick, bypassing the 1s TTL payload cache
     _serve_state uses - N tabs = N duplicate full builds/sec. Both
     paths now share _state_payload_cached().
     (API: dashboard/routes_state.py:63 _STATE_CACHE_PAYLOAD,
      :74 _timed_build_state, :89 _serve_state, :119 _serve_state_stream)

  4. routes_coach query-param hardening: GET /api/coach/trace?limit=abc
     and /api/replay/matches?limit=abc 500ed (raw ValueError leak)
     instead of degrading to the documented defaults.
     (API: dashboard/routes_coach.py:40 _serve_coach_trace,
      :56 _serve_replay_matches; core/coach_trace.py:114 read_recent,
      core/replay_history.py:91 list_matches)

  5. raw error-string cap: handler except branches sent unbounded
     str(exc) to the UI; capped to 200 chars matching the sibling
     [:200] pattern. Representative: _serve_analyze_post
     (dashboard/routes_state.py:697).

No asyncio anywhere (suite rule: never asyncio.run on the main thread).
"""
from __future__ import annotations

import json
import time
import unittest
from unittest import mock


class FakeHandler:
    """Minimal stand-in for the BaseHTTPRequestHandler the routes take.

    Routes only use h.path and h._send(code, body, ctype) (see
    dashboard/routes_coach.py:44-49, routes_state.py:99).
    """

    def __init__(self, path: str = "/"):
        self.path = path
        self.sent: list[tuple[int, bytes, str]] = []

    def _send(self, code: int, body: bytes, ctype: str,
              cache_control: str | None = None) -> None:
        self.sent.append((code, body, ctype))

    @property
    def last(self) -> tuple[int, bytes, str]:
        return self.sent[-1]


# ---------------------------------------------------------------------------
# 1. _adaptation_latch no-raise contract
# ---------------------------------------------------------------------------

class LatchMalformedOpponentTests(unittest.TestCase):
    def setUp(self):
        from dashboard import _adaptation_latch as latch
        self.latch = latch
        latch.reset()

    def tearDown(self):
        self.latch.reset()

    def _summary(self, opp_cs):
        return {
            "game_time_s": 900,
            "game_id": "g-latch-b",
            "cs": 50,
            "players": [
                {"position": "MIDDLE", "team": "ORDER",
                 "creep_score": 40, "is_active": True},
                {"position": "MIDDLE", "team": "CHAOS",
                 "creep_score": opp_cs, "is_active": False},
            ],
        }

    def test_none_opponent_creep_score_does_not_raise(self):
        # Pre-fix: int(None) -> TypeError escaped compute() and 500ed
        # /api/state (called unwrapped at _state_builder.py:263).
        out = self.latch.compute(self._summary(None))
        self.assertEqual(out.get("cs_at_10"), 50)
        self.assertNotIn("csd_at_15", out)

    def test_string_opponent_creep_score_does_not_raise(self):
        out = self.latch.compute(self._summary("abc"))
        self.assertEqual(out.get("cs_at_10"), 50)
        self.assertNotIn("csd_at_15", out)

    def test_valid_opponent_still_latches(self):
        out = self.latch.compute(self._summary(40))
        self.assertEqual(out.get("csd_at_15"), 10)


# ---------------------------------------------------------------------------
# 2. _screen_read inflight wedge
# ---------------------------------------------------------------------------

class ScreenReadInflightWedgeTests(unittest.TestCase):
    def setUp(self):
        from dashboard import _screen_read as sr
        self.sr = sr
        sr._reset_inflight_for_test()

    def tearDown(self):
        self.sr._reset_inflight_for_test()

    def test_write_failure_resets_inflight_and_reraises(self):
        # Pre-fix: an OSError out of the pending _write left _inflight
        # True forever (the worker thread that resets it never started).
        with mock.patch.object(self.sr, "_write",
                               side_effect=OSError("access denied")):
            with self.assertRaises(OSError):
                self.sr.trigger_screen_read()
        self.assertFalse(self.sr._inflight,
                         "inflight flag must be reset after a write failure")
        # And the NEXT trigger must work (no permanent wedge).
        with mock.patch.object(self.sr, "_write"), \
             mock.patch.object(self.sr.threading, "Thread") as thr:
            thr.return_value.start.return_value = None
            self.assertTrue(self.sr.trigger_screen_read())

    def test_thread_start_failure_also_resets_inflight(self):
        with mock.patch.object(self.sr, "_write"), \
             mock.patch.object(self.sr.threading, "Thread",
                               side_effect=RuntimeError("no threads")):
            with self.assertRaises(RuntimeError):
                self.sr.trigger_screen_read()
        self.assertFalse(self.sr._inflight)


# ---------------------------------------------------------------------------
# 3. routes_state shared payload cache (SSE dedupe)
# ---------------------------------------------------------------------------

class StatePayloadCacheTests(unittest.TestCase):
    def setUp(self):
        from dashboard import routes_state as rs
        self.rs = rs
        rs._STATE_CACHE_PAYLOAD = None
        rs._STATE_CACHE_TS = 0.0

    def tearDown(self):
        self.rs._STATE_CACHE_PAYLOAD = None
        self.rs._STATE_CACHE_TS = 0.0

    def test_state_payload_cached_dedupes_builds(self):
        calls = []
        with mock.patch.object(self.rs, "_timed_build_state",
                               side_effect=lambda: calls.append(1) or {"k": 1}):
            p1 = self.rs._state_payload_cached()
            p2 = self.rs._state_payload_cached()
        self.assertEqual(len(calls), 1, "second call within TTL must reuse")
        self.assertEqual(p1, p2)
        self.assertEqual(json.loads(p1.decode("utf-8")), {"k": 1})

    def test_state_payload_cached_rebuilds_after_ttl(self):
        calls = []
        with mock.patch.object(self.rs, "_timed_build_state",
                               side_effect=lambda: calls.append(1) or {"k": len(calls)}):
            self.rs._state_payload_cached()
            self.rs._STATE_CACHE_TS = time.time() - 2.0  # force expiry
            self.rs._state_payload_cached()
        self.assertEqual(len(calls), 2)

    def test_serve_state_uses_shared_cache(self):
        calls = []
        h1, h2 = FakeHandler("/api/state"), FakeHandler("/api/state")
        with mock.patch.object(self.rs, "_timed_build_state",
                               side_effect=lambda: calls.append(1) or {"k": 1}):
            self.rs._serve_state(h1)
            self.rs._serve_state(h2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(h1.last[0], 200)
        self.assertEqual(h2.last[0], 200)

    def test_sse_stream_consumes_shared_cache(self):
        # Structural pin: the SSE loop body must go through the shared
        # cache helper instead of a private _timed_build_state call, so
        # N subscribers cannot fan out N duplicate builds per tick.
        names = self.rs._serve_state_stream.__code__.co_names
        self.assertIn("_state_payload_cached", names)


# ---------------------------------------------------------------------------
# 4. routes_coach query-param hardening
# ---------------------------------------------------------------------------

class CoachQueryParamTests(unittest.TestCase):
    def test_coach_trace_malformed_limit_degrades_to_default(self):
        import core.coach_trace as ct
        from dashboard import routes_coach as rc
        h = FakeHandler("/api/coach/trace?limit=abc")
        with mock.patch.object(ct, "read_recent", return_value=[]) as rr:
            rc._serve_coach_trace(h)
        self.assertEqual(h.last[0], 200,
                         "malformed limit must not 500 the trace tab")
        rr.assert_called_once_with(50)

    def test_coach_trace_valid_limit_passes_through(self):
        import core.coach_trace as ct
        from dashboard import routes_coach as rc
        h = FakeHandler("/api/coach/trace?limit=7")
        with mock.patch.object(ct, "read_recent", return_value=[]) as rr:
            rc._serve_coach_trace(h)
        self.assertEqual(h.last[0], 200)
        rr.assert_called_once_with(7)

    def test_replay_matches_malformed_limit_degrades_to_default(self):
        import core.replay_history as rh
        from dashboard import routes_coach as rc
        h = FakeHandler("/api/replay/matches?limit=abc")
        with mock.patch.object(rh, "list_matches", return_value=[]) as lm:
            rc._serve_replay_matches(h)
        self.assertEqual(h.last[0], 200,
                         "malformed limit must not 500 the replay list")
        lm.assert_called_once_with(limit=25, queue_filter=None)


# ---------------------------------------------------------------------------
# 5. raw error-string cap (representative: /api/analyze)
# ---------------------------------------------------------------------------

class ErrorStringCapTests(unittest.TestCase):
    def test_analyze_error_string_capped(self):
        import urllib.request as ur
        from dashboard import routes_state as rs
        h = FakeHandler("/api/analyze")
        with mock.patch.object(ur, "urlopen",
                               side_effect=Exception("x" * 1000)):
            rs._serve_analyze_post(h, {})
        code, body, _ = h.last
        self.assertEqual(code, 500)
        err = json.loads(body.decode("utf-8")).get("error", "")
        self.assertLessEqual(len(err), 200,
                             "raw error strings to the UI must be capped")


if __name__ == "__main__":
    unittest.main()

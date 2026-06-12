"""Tests for dashboard/routes_ward_heat.py - the /api/ward-heat backend
that powers the UX-research-recommended Ward-Coverage Heat Strip panel.

Covers:
  * Response shape on an empty rolling window (the producer is not
    wired yet, so this is the load-bearing default-state contract)
  * Response shape with seeded events (wards / counts / uncovered)
  * Query param parsing (window_s default, custom, non-numeric -> 400,
    out-of-range -> 400)
  * 2s response cache hit / miss lifecycle
  * Cache keys split per window_s
  * 500 on unexpected internal exception (fail-soft envelope)
  * Route is registered in the dispatcher
"""
from __future__ import annotations

import json
import time
import unittest

from core import ward_events
from dashboard import routes_ward_heat


class StubHandler:
    """Same shape as test_routes_spike_curve.StubHandler."""

    def __init__(self, path: str = ""):
        self.path = path
        self.last_status: int | None = None
        self.last_body: bytes | None = None
        self.last_ct: str | None = None

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.last_status = status
        self.last_body = body
        self.last_ct = content_type

    def parsed(self) -> dict:
        if not self.last_body:
            return {}
        return json.loads(self.last_body.decode("utf-8"))


def _do(path: str) -> StubHandler:
    h = StubHandler(path=path)
    routes_ward_heat._serve_ward_heat(h)
    return h


class WardHeatBase(unittest.TestCase):
    def setUp(self):
        # Fresh cache + buffer each test.
        routes_ward_heat._reset_caches()
        ward_events.reset()


class EmptyDefaultTests(WardHeatBase):
    def test_empty_response_envelope(self):
        h = _do("/api/ward-heat")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.last_ct, "application/json")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["wards"], [])
        self.assertEqual(body["window_s"], 90.0)
        # Every lane bucket seeded to 0 - no null-guards needed frontend
        for side in ("ally", "enemy"):
            for lane in ("top", "mid", "bot", "jg", "unknown"):
                self.assertEqual(body["counts"][side][lane], 0)
        # Default 60s uncovered window with an empty buffer: all 4 named
        # lanes are uncovered on both sides.
        self.assertEqual(
            body["lanes_uncovered_ally"], ["top", "mid", "bot", "jg"])
        self.assertEqual(
            body["lanes_uncovered_enemy"], ["top", "mid", "bot", "jg"])
        self.assertEqual(body["buffer_size"], 0)
        self.assertIn("now_s",       body)
        self.assertIn("elapsed_ms",  body)
        self.assertFalse(body["cached"])


class SeededDataTests(WardHeatBase):
    def test_recent_events_surface_in_response(self):
        # Seed at a fresh-ish epoch so the default 90s window keeps them.
        now = time.time()
        ward_events.record_ward("ally",  "mid", "yellow",  ts=now - 5.0)
        ward_events.record_ward("ally",  "top", "control", ts=now - 4.0)
        ward_events.record_ward("enemy", "bot", "yellow",  ts=now - 3.0)
        h = _do("/api/ward-heat")
        body = h.parsed()
        self.assertEqual(body["ok"], True)
        self.assertEqual(len(body["wards"]), 3)
        self.assertEqual(body["counts"]["ally"]["mid"],  1)
        self.assertEqual(body["counts"]["ally"]["top"],  1)
        self.assertEqual(body["counts"]["enemy"]["bot"], 1)
        # Uncovered: ally got mid+top, missing bot+jg.
        self.assertEqual(body["lanes_uncovered_ally"], ["bot", "jg"])
        # Enemy got bot, missing top+mid+jg.
        self.assertEqual(body["lanes_uncovered_enemy"], ["top", "mid", "jg"])
        self.assertEqual(body["buffer_size"], 3)


class WindowParamTests(WardHeatBase):
    def test_default_window_is_90s(self):
        body = _do("/api/ward-heat").parsed()
        self.assertEqual(body["window_s"], 90.0)

    def test_custom_window_honored(self):
        body = _do("/api/ward-heat?window_s=30").parsed()
        self.assertEqual(body["window_s"], 30.0)

    def test_non_numeric_window_400(self):
        h = _do("/api/ward-heat?window_s=banana")
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertFalse(body["ok"])
        self.assertIn("numeric", body["error"])

    def test_window_too_small_400(self):
        h = _do("/api/ward-heat?window_s=1")
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertFalse(body["ok"])

    def test_window_too_large_400(self):
        h = _do("/api/ward-heat?window_s=9999")
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertFalse(body["ok"])

    def test_window_uncovered_clamped_to_window_s(self):
        # If the caller asks for a 30s window, the 'uncovered' lookback
        # should also be 30s (not the default 60s). Sanity-check that
        # mechanic with a 45s-old ward: at window_s=30 mid is uncovered;
        # at window_s=90 mid is still covered.
        # Two separate observations because the buffer is global module
        # state and recent_wards lazy-evicts past-window entries; reset
        # between them so each call starts on a fresh snapshot.
        now = time.time()
        ward_events.record_ward("ally", "mid", "yellow", ts=now - 45.0)
        body_narrow = _do("/api/ward-heat?window_s=30").parsed()
        self.assertIn("mid", body_narrow["lanes_uncovered_ally"])

        ward_events.reset()
        routes_ward_heat._reset_caches()
        ward_events.record_ward("ally", "mid", "yellow", ts=now - 45.0)
        body_wide = _do("/api/ward-heat?window_s=90").parsed()
        self.assertNotIn("mid", body_wide["lanes_uncovered_ally"])


class CacheTests(WardHeatBase):
    def test_second_call_within_ttl_is_cached(self):
        first = _do("/api/ward-heat").parsed()
        self.assertFalse(first["cached"])
        second = _do("/api/ward-heat").parsed()
        self.assertTrue(second["cached"])
        # Buffer state matches the first call's snapshot
        self.assertEqual(first["buffer_size"], second["buffer_size"])

    def test_different_window_busts_cache(self):
        first  = _do("/api/ward-heat?window_s=60").parsed()
        second = _do("/api/ward-heat?window_s=30").parsed()
        # Distinct keys -> both report cached=False on first hit each.
        self.assertFalse(first["cached"])
        self.assertFalse(second["cached"])

    def test_cache_expires_after_ttl(self):
        first = _do("/api/ward-heat").parsed()
        self.assertFalse(first["cached"])
        # Manually rewind the cache entry past the TTL.
        with routes_ward_heat._CACHE_LOCK:
            for key, (cached_at, payload) in list(routes_ward_heat._CACHE.items()):
                routes_ward_heat._CACHE[key] = (
                    cached_at - (routes_ward_heat._CACHE_TTL_S + 1.0),
                    payload,
                )
        second = _do("/api/ward-heat").parsed()
        self.assertFalse(second["cached"])


class FailSoftTests(WardHeatBase):
    def test_unexpected_exception_returns_500_envelope(self):
        # Force _build_payload to blow up; verify the route returns a
        # structured 500 instead of propagating.
        original = routes_ward_heat._build_payload

        def boom(*_a, **_kw):
            raise RuntimeError("ward producer is on fire")
        routes_ward_heat._build_payload = boom
        try:
            h = _do("/api/ward-heat")
        finally:
            routes_ward_heat._build_payload = original
        self.assertEqual(h.last_status, 500)
        body = h.parsed()
        self.assertFalse(body["ok"])
        # Cycle 8 slice E: raw exception text must NOT reach the client
        # (leak class per dashboard/_handler.do_POST policy); the route
        # logs the raw error and serves a generic envelope.
        self.assertNotIn("on fire", body["error"])
        self.assertEqual(body["error"], "internal error - see logs")


class DispatchRegistrationTests(WardHeatBase):
    def test_route_registered_in_dispatch(self):
        # _gather_get() is the canonical route list the live server uses
        # so this asserts the new module is wired into the dispatcher
        # (not just exposing its own GET_ROUTES).
        from dashboard import _dispatch
        # Clear the cached registry so the dispatcher rebuilds with the
        # latest module list - matters when tests run after other tests
        # that imported the dispatcher early.
        _dispatch._GET_CACHE = None
        routes = _dispatch._gather_get()
        # Every entry is (matcher, handler); confirm /api/ward-heat
        # matches one of them.
        self.assertTrue(
            any(matcher("/api/ward-heat") for matcher, _ in routes),
            "/api/ward-heat is not registered in dashboard._dispatch",
        )


if __name__ == "__main__":
    unittest.main()

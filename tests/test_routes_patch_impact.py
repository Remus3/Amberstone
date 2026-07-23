"""Tests for ``dashboard.routes_patch_impact`` GET /api/patch-impact.

The aggregation itself (``core.patch_impact.compute_patch_impact``) is covered
by tests/test_patch_impact.py. These cover the ROUTE layer only - query
parsing, the on-disk patch-name allowlist, the 5min response cache, the
envelope fields, and the no-raw-error-leak 500 path - with compute + the
snapshot listing both patched, so nothing here reads data/ (clean-checkout /
CI safe; reference_clean_checkout_probe).
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from dashboard import routes_patch_impact as rpi

_COMPUTE = "dashboard.routes_patch_impact.patch_impact.compute_patch_impact"
_PATCHES = "dashboard.routes_patch_impact.patch_impact.available_patches"


class _RouteHarness:
    def __init__(self, qs: str = ""):
        self.path = "/api/patch-impact" + (f"?{qs}" if qs else "")
        self.sent_status = None
        self.sent_body = None
        self.sent_ct = None

    def _send(self, status, body, content_type):
        self.sent_status = status
        self.sent_body = body
        self.sent_ct = content_type

    def json(self):
        return json.loads(self.sent_body.decode("utf-8"))


def _stub(**kw):
    return {
        "ok": True,
        "mode": kw.get("mode"),
        "old_patch": kw.get("old_patch"),
        "new_patch": kw.get("new_patch"),
        "top_n": kw.get("top_n"),
        "min_games": kw.get("min_games"),
        "n_matches": 42,
        "changed_items": 8,
        "reason": None,
        "champions": [],
    }


class _Base(unittest.TestCase):
    def setUp(self):
        rpi._reset_caches()
        self._c = patch(_COMPUTE, side_effect=_stub)
        self.compute = self._c.start()
        self.addCleanup(self._c.stop)
        self._p = patch(_PATCHES, return_value=["16.13.1", "16.14.1"])
        self.patches = self._p.start()
        self.addCleanup(self._p.stop)
        self.addCleanup(rpi._reset_caches)

    def get(self, qs=""):
        h = _RouteHarness(qs)
        rpi._serve_patch_impact(h)
        return h


class ParsingTests(_Base):
    def test_defaults(self):
        h = self.get()
        self.assertEqual(h.sent_status, 200)
        body = h.json()
        self.assertEqual(body["mode"], "aram")
        self.assertEqual(body["top_n"], rpi.patch_impact.DEFAULT_TOP_N)
        self.assertEqual(body["min_games"], rpi.patch_impact.DEFAULT_MIN_GAMES)
        self.assertIsNone(body["old_patch"])

    def test_each_valid_mode_passes_through(self):
        for mode in ("sr", "aram", "arena"):
            rpi._reset_caches()
            self.assertEqual(self.get(f"mode={mode}").json()["mode"], mode)

    def test_bad_mode_is_400(self):
        h = self.get("mode=urf")
        self.assertEqual(h.sent_status, 400)
        self.assertFalse(h.json()["ok"])

    def test_non_int_top_is_400(self):
        self.assertEqual(self.get("top=lots").sent_status, 400)

    def test_out_of_range_top_is_400(self):
        self.assertEqual(self.get("top=0").sent_status, 400)
        rpi._reset_caches()
        self.assertEqual(self.get(f"top={rpi.MAX_TOP + 1}").sent_status, 400)

    def test_out_of_range_min_games_is_400(self):
        self.assertEqual(self.get("min_games=0").sent_status, 400)

    def test_top_and_min_games_reach_compute(self):
        self.get("top=3&min_games=9")
        self.assertEqual(self.compute.call_args.kwargs["top_n"], 3)
        self.assertEqual(self.compute.call_args.kwargs["min_games"], 9)


class PatchAllowlistTests(_Base):
    def test_known_patch_pair_passes_through(self):
        body = self.get("old=16.13.1&new=16.14.1").json()
        self.assertEqual((body["old_patch"], body["new_patch"]),
                         ("16.13.1", "16.14.1"))

    def test_unknown_patch_is_400_and_never_reaches_compute(self):
        h = self.get("old=99.99.9")
        self.assertEqual(h.sent_status, 400)
        self.compute.assert_not_called()

    def test_a_traversal_style_patch_name_is_rejected(self):
        # ds_patch_diff._resolve() accepts any existing directory, so the route
        # must gate on the on-disk allowlist rather than hand the string over.
        h = self.get("new=../../../Windows")
        self.assertEqual(h.sent_status, 400)
        self.compute.assert_not_called()


class CacheTests(_Base):
    def test_second_identical_call_is_served_from_cache(self):
        first = self.get("mode=sr").json()
        second = self.get("mode=sr").json()
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(self.compute.call_count, 1)

    def test_a_different_key_misses_the_cache(self):
        self.get("mode=sr")
        self.get("mode=aram")
        self.assertEqual(self.compute.call_count, 2)

    def test_cached_payload_still_carries_a_fresh_elapsed_ms(self):
        self.get()
        body = self.get().json()
        self.assertIn("elapsed_ms", body)
        self.assertIsInstance(body["elapsed_ms"], int)

    def test_cache_eviction_keeps_the_dict_bounded(self):
        for i in range(rpi._CACHE_MAX + 5):
            self.get(f"top={(i % rpi.MAX_TOP) + 1}&min_games={i + 1}")
        self.assertLessEqual(len(rpi._CACHE), rpi._CACHE_MAX)


class FailureTests(_Base):
    def test_compute_raising_yields_a_500_with_no_raw_text(self):
        self.compute.side_effect = RuntimeError("C:/secret/rewind_history.db")
        h = self.get()
        self.assertEqual(h.sent_status, 500)
        body = h.json()
        self.assertFalse(body["ok"])
        self.assertNotIn("secret", body["error"])

    def test_a_500_is_not_cached(self):
        self.compute.side_effect = RuntimeError("boom")
        self.get()
        self.assertEqual(len(rpi._CACHE), 0)


class RegistrationTests(unittest.TestCase):
    def test_route_is_registered_in_the_dispatch_get_chain(self):
        from dashboard import _dispatch
        hits = [fn for matcher, fn in _dispatch._gather_get()
                if matcher("/api/patch-impact")]
        self.assertEqual(hits, [rpi._serve_patch_impact])


if __name__ == "__main__":
    unittest.main()

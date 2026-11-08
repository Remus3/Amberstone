"""True-audit regressions for GET /api/patch-impact (S144-T-626).

dashboard/routes_patch_impact.py is a GET route on :8888 (a LAN peer reaches
it with any query) whose live client is web/js/panels/patch_impact.js. Each
class pins one finding of the s144 true-audit cycle 222 against the route
module; compute and the snapshot listing are patched, so nothing here reads
data/ (clean-checkout safe, like tests/test_routes_patch_impact.py).
"""
from __future__ import annotations

import json
import logging
import time
import unittest
from unittest.mock import patch

from dashboard import routes_patch_impact as rpi

_COMPUTE = "dashboard.routes_patch_impact.patch_impact.compute_patch_impact"
_PATCHES = "dashboard.routes_patch_impact.patch_impact.available_patches"


def _strict_loads(raw: bytes):
    """json.loads that refuses NaN / Infinity, as the browser's JSON.parse."""
    def _refuse(token):
        raise ValueError(f"non-finite token {token}")
    return json.loads(raw.decode("utf-8"), parse_constant=_refuse)


class _Harness:
    def __init__(self, qs: str = "", fail_send: BaseException | None = None):
        self.path = "/api/patch-impact" + (f"?{qs}" if qs else "")
        self.status = None
        self.body = None
        self.lock_held_at_send = None
        self._fail = fail_send

    def _send(self, status, body, content_type):
        self.lock_held_at_send = rpi._CACHE_LOCK.locked()
        if self._fail is not None:
            raise self._fail
        self.status = status
        self.body = body

    def json(self):
        return _strict_loads(self.body)


def _stub(**kw):
    return {
        "ok": True,
        "mode": kw.get("mode"),
        "old_patch": kw.get("old_patch") or "16.13.1",
        "new_patch": kw.get("new_patch") or "16.14.1",
        "top_n": kw.get("top_n"),
        "min_games": kw.get("min_games"),
        "n_matches": 42,
        "changed_items": 1,
        "reason": None,
        "champions": [],
    }


class _Base(unittest.TestCase):
    def setUp(self):
        rpi._reset_caches()
        self.addCleanup(rpi._reset_caches)
        self._c = patch(_COMPUTE, side_effect=_stub)
        self.compute = self._c.start()
        self.addCleanup(self._c.stop)
        self._p = patch(_PATCHES, return_value=["16.13.1", "16.14.1"])
        self.patches = self._p.start()
        self.addCleanup(self._p.stop)

    def get(self, qs="", **kw):
        h = _Harness(qs, **kw)
        rpi._serve_patch_impact(h)
        return h


class MonotonicCacheClockTests(_Base):
    """The 5 min TTL ran on time.time: a wall clock stepped back kept an
    entry fresh for the whole step, and elapsed_ms could go negative."""

    def test_entry_expires_on_the_monotonic_clock_whatever_the_wall_clock(self):
        mono = [1000.0]
        with patch.object(rpi.time, "monotonic", lambda: mono[0]), \
                patch.object(rpi.time, "time", lambda: 5000.0):
            self.get("mode=sr")
            mono[0] += rpi._CACHE_TTL_S + 1.0
            second = self.get("mode=sr")
        self.assertEqual(self.compute.call_count, 2)
        self.assertFalse(second.json()["cached"])

    def test_an_entry_stamped_in_the_future_is_never_served(self):
        mono = [1000.0]
        with patch.object(rpi.time, "monotonic", lambda: mono[0]):
            self.get("mode=sr")
            mono[0] = 500.0
            second = self.get("mode=sr")
        self.assertEqual(self.compute.call_count, 2)
        self.assertFalse(second.json()["cached"])

    def test_elapsed_ms_is_never_negative_when_the_wall_clock_steps_back(self):
        wall = iter([10_000.0, 9_000.0, 8_000.0, 7_000.0, 6_000.0, 5_000.0])
        with patch.object(rpi.time, "time", lambda: next(wall)):
            body = self.get().json()
        self.assertGreaterEqual(body["elapsed_ms"], 0)


class SendOutsideTheLockTests(_Base):
    """A cache hit was written to the socket while _CACHE_LOCK was held, so a
    client that stops reading held every other request behind the lock."""

    def test_a_miss_is_sent_without_the_lock(self):
        h = self.get()
        self.assertEqual(h.status, 200)
        self.assertFalse(h.lock_held_at_send)

    def test_a_hit_is_sent_without_the_lock(self):
        self.get()
        h = self.get()
        self.assertTrue(h.json()["cached"])
        self.assertFalse(h.lock_held_at_send)


class AsciiQueryShapeTests(_Base):
    """int() read "1_0", non-ASCII digits and a value padded with Unicode
    blanks (str.strip() eats U+3000) as a number, and mode took the same
    Unicode padding."""

    def _assert_400(self, qs, error):
        h = self.get(qs)
        self.assertEqual(h.status, 400, qs)
        self.assertEqual(h.json(), {"ok": False, "error": error}, qs)
        self.compute.assert_not_called()

    def test_underscore_digits_are_not_an_integer(self):
        self._assert_400("top=1_0", "top must be an integer")
        self._assert_400("min_games=1_0", "min_games must be an integer")

    def test_arabic_indic_digit_is_not_an_integer(self):
        self._assert_400("top=%D9%A5", "top must be an integer")

    def test_fullwidth_digit_is_not_an_integer(self):
        self._assert_400("min_games=%EF%BC%95", "min_games must be an integer")

    def test_ideographic_space_padding_is_not_stripped(self):
        self._assert_400("top=%E3%80%805", "top must be an integer")

    def test_mode_with_unicode_padding_is_refused(self):
        h = self.get("mode=%E3%80%80sr")
        self.assertEqual(h.status, 400)
        self.compute.assert_not_called()

    def test_a_very_long_digit_run_is_a_range_error_not_a_parse_error(self):
        # Same class as top=987654 (tests/test_routes_int_param_no_echo_s144q51):
        # a 5000-digit value used to hit int()'s digit limit and read as
        # "not an integer"; it is an out-of-range integer.
        self._assert_400("top=" + "9" * 5000, "top must be between 1 and 50")

    def test_ascii_padding_sign_and_leading_zero_still_parse(self):
        # Valid input is unchanged: ASCII blanks are stripped, an explicit
        # "+" and a leading zero read as before.
        for qs, want in (("top=%205%20", 5), ("top=+7", 7), ("top=09", 9),
                         ("top=%095", 5), ("top=" + "0" * 20 + "8", 8),
                         ("top=+" + "0" * 5000 + "3", 3), ("top=50", 50),
                         ("min_games=500", 500)):
            rpi._reset_caches()
            self.compute.reset_mock()
            h = self.get(qs)
            self.assertEqual(h.status, 200, qs)
            key = "min_games" if qs.startswith("min_games") else "top_n"
            self.assertEqual(self.compute.call_args.kwargs[key], want, qs)

    def test_negative_value_is_still_a_range_error(self):
        self._assert_400("top=-5", "top must be between 1 and 50")


class PatchListingTests(_Base):
    """available_patches() (a directory listing) ran on EVERY request: with
    no old / new, on a cache hit and after a parameter error."""

    def test_no_listing_without_old_or_new(self):
        self.get()
        self.get()
        self.patches.assert_not_called()

    def test_no_listing_after_a_parameter_error(self):
        self.assertEqual(self.get("top=zz&old=16.13.1").status, 400)
        self.patches.assert_not_called()

    def test_ill_shaped_patch_is_refused_before_the_listing(self):
        for value in ("x" * 5000, "16.14.1%E3%80%80", "..%2F..%2Fx", "16..1",
                      ".16.1", "16.1.", "%2Fetc", "1.2.3.4.5", "12345.1",
                      "1" * 5000):
            h = self.get(f"old={value}")
            self.assertEqual(h.status, 400, value)
            self.assertEqual(h.json()["error"], "old is not a snapshot on disk")
        self.patches.assert_not_called()
        self.compute.assert_not_called()

    def test_new_is_shape_checked_before_the_listing_too(self):
        h = self.get("new=..%2Fx")
        self.assertEqual(h.status, 400)
        self.assertEqual(h.json()["error"], "new is not a snapshot on disk")
        self.patches.assert_not_called()

    def test_old_is_judged_before_new_and_the_listing_runs_once(self):
        # Valid-input ordering is unchanged: an unlisted old is named even
        # when new is junk too, and one request lists the dirs at most once.
        h = self.get("old=99.9.9&new=abc")
        self.assertEqual(h.json()["error"], "old is not a snapshot on disk")
        self.assertEqual(self.patches.call_count, 1)
        self.patches.reset_mock()
        self.get("old=16.13.1&new=16.14.1")
        self.assertEqual(self.patches.call_count, 1)

    def test_a_listed_patch_still_passes(self):
        h = self.get("old=16.13.1&new=16.14.1")
        self.assertEqual(h.status, 200)
        self.assertEqual(self.compute.call_args.kwargs["old_patch"], "16.13.1")
        self.assertEqual(self.compute.call_args.kwargs["new_patch"], "16.14.1")

    def test_a_well_shaped_unlisted_patch_is_still_400(self):
        h = self.get("new=99.99.9")
        self.assertEqual(h.status, 400)
        self.assertEqual(h.json()["error"], "new is not a snapshot on disk")
        self.compute.assert_not_called()


class NonFiniteBodyTests(_Base):
    """A NaN / Infinity in a diffed snapshot value (json.loads accepts the
    tokens, and data/daemon_slayer snapshots carry them) was dumped as a bare
    token the browser's JSON.parse rejects for the WHOLE card, and cached."""

    def _nan_payload(self, **kw):
        out = _stub(**kw)
        out["champions"] = [{
            "champion_id": 1, "champion": "Annie", "name": "Annie",
            "games": 9, "wins": 5, "winrate": 54.5, "play_share": 10.0,
            "change_count": 2,
            "champion_changes": [{"field": "armor", "old": float("nan"),
                                  "new": float("inf")}],
            "ability_changes": [{"key": "Q", "field": "ratio",
                                 "old": [1.0, float("-inf")], "new": 2}],
            "build_changes": [], "item_changes": [],
        }]
        return out

    def test_non_finite_values_serve_as_null_in_strict_json(self):
        self.compute.side_effect = self._nan_payload
        h = self.get()
        self.assertEqual(h.status, 200)
        body = h.json()  # strict parse: raises on a bare NaN / Infinity
        champ = body["champions"][0]
        self.assertIsNone(champ["champion_changes"][0]["old"])
        self.assertIsNone(champ["champion_changes"][0]["new"])
        self.assertEqual(champ["ability_changes"][0]["old"], [1.0, None])
        self.assertEqual(champ["ability_changes"][0]["new"], 2)
        self.assertEqual(champ["winrate"], 54.5)

    def test_the_cached_copy_is_strict_too(self):
        self.compute.side_effect = self._nan_payload
        self.get()
        h = self.get()
        self.assertTrue(h.json()["cached"])
        self.assertIsNone(h.json()["champions"][0]["champion_changes"][0]["old"])

    def test_finite_payload_is_unchanged(self):
        def finite(**kw):
            out = self._nan_payload(**kw)
            out["champions"][0]["champion_changes"][0].update(old=1.5, new=-2)
            out["champions"][0]["ability_changes"][0]["old"] = [1.0, True, "x"]
            return out
        self.compute.side_effect = finite
        body = self.get().json()
        want = finite(mode="aram", top_n=rpi.patch_impact.DEFAULT_TOP_N,
                      min_games=rpi.patch_impact.DEFAULT_MIN_GAMES)
        body.pop("cached")
        body.pop("elapsed_ms")
        self.assertEqual(body, json.loads(json.dumps(want)))


class DegradedPayloadNotCachedTests(_Base):
    """A degraded compute result (a stated reason: the diff failed, no
    readable match history) was cached for 5 min like a real answer, so one
    transient failure blanked the card for the whole TTL (RM-443 class)."""

    def test_a_reason_bearing_payload_is_recomputed(self):
        def degraded(**kw):
            out = _stub(**kw)
            out["reason"] = "no readable match history yet"
            return out
        self.compute.side_effect = degraded
        first = self.get()
        second = self.get()
        self.assertEqual(first.status, 200)
        self.assertFalse(second.json()["cached"])
        self.assertEqual(self.compute.call_count, 2)
        self.assertEqual(len(rpi._CACHE), 0)

    def test_a_clean_payload_is_still_cached(self):
        self.get()
        self.assertTrue(self.get().json()["cached"])
        self.assertEqual(self.compute.call_count, 1)


class LastResortTests(_Base):
    """The last-resort arm logged the raw exception text with no type name
    and swallowed every failure of the error send."""

    def test_the_log_line_names_the_exception_type(self):
        self.compute.side_effect = RuntimeError("boom")
        with self.assertLogs(level=logging.WARNING) as cm:
            h = self.get()
        self.assertEqual(h.status, 500)
        self.assertEqual(h.json(),
                         {"ok": False, "error": "internal error - see logs"})
        self.assertTrue(any("RuntimeError" in line for line in cm.output),
                        cm.output)

    def test_an_exception_whose_str_raises_still_gets_the_fixed_500(self):
        class Nasty(Exception):
            def __str__(self):
                raise ValueError("no str")
        self.compute.side_effect = Nasty()
        with self.assertLogs(level=logging.WARNING):
            h = self.get()
        self.assertEqual(h.status, 500)
        self.assertEqual(h.json(),
                         {"ok": False, "error": "internal error - see logs"})

    def test_a_client_gone_during_send_does_not_raise(self):
        with self.assertLogs(level=logging.WARNING):
            self.get(fail_send=ConnectionResetError("gone"))

    def test_a_non_finite_value_in_an_unscrubbed_place_is_the_fixed_500(self):
        # Backstop: the body is dumped with allow_nan=False, so anything the
        # scrub did not see becomes the fixed 500, never a bare NaN token,
        # and nothing is cached.
        with patch.object(rpi, "_json_safe", lambda obj: obj):
            self.compute.side_effect = lambda **kw: dict(
                _stub(**kw), n_matches=float("nan"))
            with self.assertLogs(level=logging.WARNING):
                h = self.get()
        self.assertEqual(h.status, 500)
        self.assertEqual(len(rpi._CACHE), 0)


if __name__ == "__main__":
    unittest.main()

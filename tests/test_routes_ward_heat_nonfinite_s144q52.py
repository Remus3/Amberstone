"""RM-1325: /api/ward-heat must refuse a non-finite ``window_s``.

Defect (measured s144 queue cycle 85, re-measured cycle 86): the route's
``_parse_window`` did ``float(raw)`` and then a range check written as
``val < MIN or val > MAX``. ``float("nan")`` parses, and every comparison
against NaN is False, so ``window_s=nan`` passed the range check:

  * the 200 body carried ``"window_s": NaN``, a bare token that the
    browser's ``JSON.parse`` rejects for the WHOLE body;
  * NaN became the cache key, and NaN never equals itself, so every such
    request missed the cache and inserted a fresh entry.

``inf`` was already refused by the ``> MAX`` arm; it is pinned here too so
a later rewrite of the range check cannot reopen it.

The sibling sweep (every ``float(`` query parse under dashboard/routes_*.py)
found every other site already rejecting non-finite input; the second class
below pins each one so the sweep result is a test, not a sentence.
"""
from __future__ import annotations

import json
import unittest

from core import ward_events
from dashboard import routes_ward_heat

_NON_FINITE = (
    "nan", "NaN", "NAN", "-nan", "+nan", " nan ",
    "inf", "Infinity", "-inf", "-Infinity", "+inf", "1e400", "-1e400",
)

_RANGE_ERROR = "window_s must be in [5, 600]"


def _reject_constant(token: str):
    raise ValueError(f"non-standard JSON constant {token}")


class _StubHandler:
    def __init__(self, path: str):
        self.path = path
        self.last_status: int | None = None
        self.last_body: bytes | None = None

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.last_status = status
        self.last_body = body


def _do(path: str) -> _StubHandler:
    h = _StubHandler(path)
    routes_ward_heat._serve_ward_heat(h)
    return h


class WardHeatNonFiniteWindowTests(unittest.TestCase):
    def setUp(self):
        routes_ward_heat._reset_caches()
        ward_events.reset()

    def tearDown(self):
        routes_ward_heat._reset_caches()
        ward_events.reset()

    def test_parse_window_refuses_non_finite(self):
        for raw in _NON_FINITE:
            with self.subTest(raw=raw):
                _val, err = routes_ward_heat._parse_window({"window_s": [raw]})
                self.assertEqual(err, _RANGE_ERROR)

    def test_route_answers_400_with_strict_json_and_no_cache_entry(self):
        for raw in _NON_FINITE:
            with self.subTest(raw=raw):
                routes_ward_heat._reset_caches()
                h = _do(f"/api/ward-heat?window_s={raw.strip()}")
                self.assertEqual(h.last_status, 400)
                # Strict parse: a bare NaN / Infinity token raises here.
                body = json.loads(h.last_body.decode("utf-8"),
                                  parse_constant=_reject_constant)
                self.assertEqual(body, {"ok": False, "error": _RANGE_ERROR})
                self.assertEqual(routes_ward_heat._CACHE, {})

    def test_repeated_nan_requests_never_grow_the_cache(self):
        for _ in range(5):
            _do("/api/ward-heat?window_s=nan")
        self.assertEqual(len(routes_ward_heat._CACHE), 0)

    def test_finite_bounds_still_accepted(self):
        for raw, want in (("5", 5.0), ("600", 600.0), ("30.5", 30.5),
                          ("", 90.0)):
            with self.subTest(raw=raw):
                val, err = routes_ward_heat._parse_window({"window_s": [raw]})
                self.assertIsNone(err)
                self.assertEqual(val, want)
        h = _do("/api/ward-heat?window_s=30")
        self.assertEqual(h.last_status, 200)
        body = json.loads(h.last_body.decode("utf-8"),
                          parse_constant=_reject_constant)
        self.assertEqual(body["window_s"], 30.0)

    def test_finite_out_of_range_text_unchanged(self):
        for raw in ("4.99", "600.01", "-5", "0"):
            with self.subTest(raw=raw):
                _val, err = routes_ward_heat._parse_window({"window_s": [raw]})
                self.assertEqual(err, _RANGE_ERROR)


class SiblingQueryFloatParsersRejectNonFiniteTests(unittest.TestCase):
    """Sweep pins: each dashboard/routes_*.py helper that parses a query
    string with ``float(`` already refuses nan / inf. Measured s144 queue
    cycle 86; these pass on the base and exist so a regression in any one
    of them turns red."""

    def test_float_knob_parsers_return_their_fallback(self):
        from dashboard import routes_ds_combo, routes_ds_knobs, routes_ds_statcheck
        cases = (
            ("routes_ds_combo._parse_float",
             lambda s: routes_ds_combo._parse_float(s, default=7.0), 7.0),
            ("routes_ds_knobs._parse_float", routes_ds_knobs._parse_float, None),
            ("routes_ds_statcheck._as_float", routes_ds_statcheck._as_float, None),
        )
        for name, fn, fallback in cases:
            for raw in ("nan", "inf", "-inf", "1e400"):
                with self.subTest(fn=name, raw=raw):
                    self.assertEqual(fn(raw), fallback)

    def test_int_via_float_parsers_survive_non_finite(self):
        from dashboard import (
            routes_ds_combo,
            routes_ds_knobs,
            routes_ds_relscore,
            routes_ds_shape,
            routes_ds_statcheck,
        )
        cases = (
            ("routes_ds_combo._parse_level", routes_ds_combo._parse_level,
             routes_ds_combo._DEFAULT_LEVEL),
            ("routes_ds_knobs._parse_level", routes_ds_knobs._parse_level,
             routes_ds_knobs._DEFAULT_LEVEL),
            ("routes_ds_knobs._parse_budget", routes_ds_knobs._parse_budget, None),
            ("routes_ds_relscore._parse_level", routes_ds_relscore._parse_level,
             routes_ds_relscore._DEFAULT_LEVEL),
            ("routes_ds_shape._parse_knob", routes_ds_shape._parse_knob, 0),
            ("routes_ds_statcheck._as_int", routes_ds_statcheck._as_int, None),
        )
        for name, fn, fallback in cases:
            for raw in ("nan", "inf", "-inf", "1e400"):
                with self.subTest(fn=name, raw=raw):
                    self.assertEqual(fn(raw), fallback)


if __name__ == "__main__":
    unittest.main()

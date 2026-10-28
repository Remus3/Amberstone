"""s144 true-audit (RM-1113) - POST /api/build-plan never answers with a
body the browser cannot parse, and never lets one junk number cost the plan.

Findings pinned here (each red at the parent of the fix):

  G1  clock_s: ``float(payload["clock_s"])`` took a JSON Infinity / NaN (and
      the string "1e400") and echoed it into ``plan_meta.clock``; json.dumps
      then wrote a bare ``Infinity`` / ``NaN`` token, so the browser's
      JSON.parse rejected the WHOLE reply. A negative, a bool or a clock past
      1e6 s was echoed too. Now a clock is a finite number in 0..1e6, else 0.
  G2  knobs: ``int(knobs["armor"])`` raised OverflowError on a JSON Infinity
      (only TypeError / ValueError were caught), so one knob turned the reply
      into ok:false and the plan was lost; ``fight_length`` Infinity / NaN
      was echoed as a bare token; 1e300 became a 301-digit int echoed back and
      forwarded to DS as target_armor. A bool knob read as 1. Now a junk or
      out-of-range (|x| > 1e6) knob keeps its default.
  G3  _coerce_enemy_levels int()-truncated a level before fed_threat's strict
      level vocabulary saw it: 17.9 read as 17 and "1_7" as 17, and either
      could clear the fed economy cut. The raw values now pass through and
      fed_threat (core.build_planner.fed_threat._level) owns the coercion.
  G4  backstop: any other non-finite float reaching the success envelope (a
      NaN target_stats from the seed boundary, whose _Cap.json uses a
      NaN-accepting json.loads) now degrades to the ok:false error envelope,
      which is strict JSON, instead of an unparsable 200 body.
  G5  a non-list ``items`` / ``enemies`` iterated its characters ("3031" read
      as owned ids "3", "0", "3", "1"; "Zed" as enemies "Z", "e", "d"); a
      non-list is now [].

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import json
import math
import unittest

from dashboard import routes_build_plan
from tests.test_build_plan_contract import _fake_seed_fn


def _reject_constant(token):
    raise ValueError(f"non-JSON token {token!r} in the reply")


class _Handler:
    def __init__(self) -> None:
        self.status = 0
        self.body = b""

    def _send(self, status, body, content_type):
        self.status = status
        self.body = body

    def strict_json(self) -> dict:
        # The browser's JSON.parse: Infinity / -Infinity / NaN are rejected.
        return json.loads(self.body.decode("utf-8"),
                          parse_constant=_reject_constant)


def _post(payload, seed_fn=_fake_seed_fn, capture=None):
    orig = routes_build_plan._seed_fn_factory

    def _factory(**kw):
        if capture is not None:
            capture.append(kw)
        return seed_fn

    routes_build_plan._seed_fn_factory = _factory
    try:
        h = _Handler()
        routes_build_plan._serve_build_plan(h, payload)
        return h.strict_json()
    finally:
        routes_build_plan._seed_fn_factory = orig


def _base(**kw):
    p = {"champion": "Miss Fortune", "items": []}
    p.update(kw)
    return p


class ClockTests(unittest.TestCase):
    """G1 - plan_meta.clock is always a finite number in 0..1e6."""

    def test_non_finite_clock_reads_zero_and_reply_parses(self):
        for raw in (float("inf"), float("-inf"), float("nan"), "1e400",
                    "inf", "nan"):
            with self.subTest(raw=raw):
                resp = _post(_base(clock_s=raw))
                self.assertTrue(resp["ok"])
                self.assertEqual(resp["plan_meta"]["clock"], 0.0)

    def test_out_of_range_or_bool_clock_reads_zero(self):
        for raw in (-5, -0.5, 1e300, 10 ** 400, True, False):
            with self.subTest(raw=raw):
                resp = _post(_base(clock_s=raw))
                self.assertTrue(resp["ok"])
                self.assertEqual(resp["plan_meta"]["clock"], 0.0)

    def test_valid_clock_unchanged(self):
        for raw, want in ((0, 0.0), (754.5, 754.5), ("1200", 1200.0),
                          (1e6, 1e6)):
            with self.subTest(raw=raw):
                resp = _post(_base(clock_s=raw))
                self.assertEqual(resp["plan_meta"]["clock"], want)

    def test_coerce_clock_unit(self):
        c = routes_build_plan._coerce_clock
        self.assertEqual(c(None), 0.0)
        self.assertEqual(c({"a": 1}), 0.0)
        self.assertEqual(c(float("nan")), 0.0)
        self.assertEqual(c(1e6 + 1), 0.0)
        self.assertEqual(c(" 90 "), 90.0)
        self.assertEqual(c(90), 90.0)
        # -0.0 is echoed as 0.0, never as "-0.0".
        self.assertEqual(math.copysign(1.0, c(-0.0)), 1.0)


class KnobTests(unittest.TestCase):
    """G2 - one junk knob keeps its default; the plan survives."""

    def test_infinite_armor_knob_keeps_the_plan(self):
        for key in ("armor", "mr", "budget"):
            for raw in (float("inf"), float("-inf")):
                with self.subTest(key=key, raw=raw):
                    resp = _post(_base(knobs={key: raw}))
                    self.assertTrue(resp["ok"], resp.get("reason"))
                    self.assertTrue(resp["live"])
                    self.assertEqual(resp["knobs"][key], 0)

    def test_non_finite_fight_length_reads_default(self):
        for raw in (float("inf"), float("-inf"), float("nan"), "1e400"):
            with self.subTest(raw=raw):
                resp = _post(_base(knobs={"fight_length": raw}))
                self.assertTrue(resp["ok"])
                self.assertEqual(resp["knobs"]["fight_length"], 0.0)

    def test_out_of_range_or_bool_knob_reads_default(self):
        for raw in (1e300, 10 ** 400, -(10 ** 7), True):
            with self.subTest(raw=raw):
                resp = _post(_base(knobs={"armor": raw, "mr": raw,
                                          "budget": raw,
                                          "fight_length": raw}))
                self.assertTrue(resp["ok"])
                self.assertEqual(resp["knobs"],
                                 dict(routes_build_plan._DEFAULT_KNOBS))

    def test_huge_armor_knob_is_not_forwarded_to_ds(self):
        seen: list = []
        _post(_base(knobs={"armor": 1e300, "mr": 40}), capture=seen)
        self.assertEqual(seen[0]["target_overrides"], {"target_mr": 40.0})

    def test_valid_knobs_unchanged(self):
        resp = _post(_base(knobs={"armor": 90, "mr": "50", "budget": 8000.0,
                                  "fight_length": 4.5}))
        self.assertEqual(resp["knobs"], {"armor": 90, "mr": 50,
                                         "budget": 8000,
                                         "fight_length": 4.5})
        # Pre-existing behaviour kept: a fractional int knob truncates.
        resp = _post(_base(knobs={"armor": 90.7}))
        self.assertEqual(resp["knobs"]["armor"], 90)


class EnemyLevelTests(unittest.TestCase):
    """G3 - fed_threat, not the route, decides what a level is."""

    def _fed(self, level):
        # Me: item-less, level 1 (130 gold). Draven 7/1, item-less: a level
        # of 17 is a 2080-gold lead (clears GOLD_LEAD_CUT 2000); 0 is none.
        resp = _post(_base(level=1, enemies=["Draven"], enemy_items=[[]],
                           enemy_scores=[{"kills": 7, "deaths": 1}],
                           enemy_levels=[level]))
        return [h for h in resp["counter_hints"] if h.get("criterion") == "fed"]

    def test_valid_level_still_fires(self):
        self.assertTrue(self._fed(17))
        self.assertTrue(self._fed("17"))

    def test_fractional_or_underscored_level_is_not_truncated(self):
        for raw in (17.9, "1_7", float("inf"), 10 ** 400, True):
            with self.subTest(raw=raw):
                self.assertEqual(self._fed(raw), [])

    def test_coerce_enemy_levels_shape(self):
        f = routes_build_plan._coerce_enemy_levels
        self.assertIsNone(f({"a": 1}))
        self.assertIsNone(f("11"))
        self.assertEqual(f([11, "9"]), [11, "9"])


class StrictJsonBackstopTests(unittest.TestCase):
    """G4 - a non-finite value from the seed boundary never yields an
    unparsable 200 body."""

    def test_nan_target_stats_degrades_to_parsable_error_envelope(self):
        def _nan_seed(champion, owned_ids=None, **kw):
            out = dict(_fake_seed_fn(champion, owned_ids, **kw))
            out["target_stats"] = {"target_armor": float("nan")}
            return out

        resp = _post(_base(), seed_fn=_nan_seed)
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["reason"], "error")
        for key in ("live", "meta", "knobs", "plan_meta", "counter_hints"):
            self.assertIn(key, resp)

    def test_finite_target_stats_still_ok(self):
        resp = _post(_base())
        self.assertTrue(resp["ok"])
        ts = resp["plan_meta"]["target_stats"]
        self.assertTrue(all(math.isfinite(v) for v in ts.values()
                            if isinstance(v, float)))


class ListFieldTests(unittest.TestCase):
    """G5 - a non-list items / enemies is [], never its characters."""

    def test_string_items_are_not_split_into_characters(self):
        seen: list = []

        def _spy_seed(champion, owned_ids=None, **kw):
            seen.append(list(owned_ids or []))
            return _fake_seed_fn(champion, owned_ids, **kw)

        _post(_base(items="3031"), seed_fn=_spy_seed)
        self.assertTrue(seen)
        self.assertTrue(all(ids == [] for ids in seen), seen)

    def test_string_or_dict_enemies_are_not_iterated(self):
        for raw in ("Zed", {"Zed": 1}):
            seen: list = []
            with self.subTest(raw=raw):
                resp = _post(_base(enemies=raw), capture=seen)
                self.assertTrue(resp["ok"])
                self.assertEqual(seen[0]["enemies"], [])

    def test_list_fields_unchanged(self):
        seen: list = []
        _post(_base(items=["3031", 3006], enemies=["Zed", "", "Lux"]),
              capture=seen)
        self.assertEqual(seen[0]["enemies"], ["Zed", "Lux"])


if __name__ == "__main__":
    unittest.main()

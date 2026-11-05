"""True-audit regressions for dashboard/routes_ds_shape.py (RM-1447).

Each class pins one finding of the s144 true-audit cycle 112 audit:

  * DisplayNameTests      - the live caller (web/js/panels/active_match.js ->
    ds_shaper.js) sends the Live Client DISPLAY name ("Lee Sin", "Wukong");
    the route looked it up verbatim, so 4 of the 20 table rows (JarvanIV,
    LeeSin, MonkeyKing, XinZhao) silently served the 0.5 / 0.5 default.
  * NegativeKnobTests     - the utility baseline is 0.0, below the shaper's
    WEIGHT_MIN floor, so a NEGATIVE utility knob raised utility 0 -> 5 pct
    (the knob moved its own axis the wrong way); the shaper's clamp +
    renormalize did the same with two knobs (Darius damage -1 survivability
    -2: damage 65 -> 74) and with rows near the floor / cap. The whole
    5x5x5 knob grid now never moves an axis against its own knob.
  * MalformedTableTests   - a malformed archetype row (string, short list,
    NaN, negative, all-zero, bool) answered 500 or emitted bare NaN tokens
    (invalid JSON); it now falls back to the default pair, logged.
  * ChampionParamTests    - the champion param was echoed back unbounded and
    unchecked; an over-long or non-printable value is now a 400.
  * ElapsedClockTests     - elapsed_ms came from the wall clock and went
    negative on a clock step; it now uses a monotonic counter.
  * NestedErrorTests      - a failure inside the error reply itself was
    swallowed with no trace; it is now logged at debug.
"""
from __future__ import annotations

import json
import logging
import math
import time as _real_time
import types
import unittest

from agents.daemon_slayer import hybrid
from core import shaper
from dashboard import routes_ds_shape as rt
from tests._timing_budget import fleet_test_guard


class _H:
    def __init__(self, path: str, fail: bool = False):
        self.path = path
        self.fail = fail
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        if self.fail:
            raise OSError("socket gone")
        self.sent = (status, body, ctype)

    def body(self) -> dict:
        assert self.sent is not None

        def _no_constants(tok):
            raise AssertionError(f"non-JSON constant {tok!r} in reply")

        return json.loads(self.sent[1].decode("utf-8"),
                          parse_constant=_no_constants)


def _do(path: str) -> _H:
    h = _H(path)
    rt._serve_ds_shape(h)
    return h


class _TableOverride:
    """Swap hybrid's process cache for the duration of a test."""

    def __init__(self, table):
        self.table = table

    def __enter__(self):
        self.saved = hybrid._WEIGHTS_CACHE
        hybrid._WEIGHTS_CACHE = self.table
        return self

    def __exit__(self, *exc):
        hybrid._WEIGHTS_CACHE = self.saved
        return False


class DisplayNameTests(unittest.TestCase):
    _CASES = (
        ("Lee%20Sin", "LeeSin"),
        ("Jarvan%20IV", "JarvanIV"),
        ("Wukong", "MonkeyKing"),
        ("Xin%20Zhao", "XinZhao"),
    )

    def test_display_name_reaches_its_table_row(self) -> None:
        table = hybrid._load_archetype_weights()["champions"]
        for raw, cid in self._CASES:
            with self.subTest(raw=raw):
                h = _do(f"/api/ds-shape?champion={raw}")
                self.assertEqual(h.sent[0], 200)
                body = h.body()
                self.assertEqual(body["archetype_source"], "champion")
                self.assertEqual(body["champion"], cid)
                a, b = table[cid]
                self.assertAlmostEqual(body["baseline"]["damage"], a / (a + b))
                self.assertAlmostEqual(body["baseline"]["survivability"],
                                       b / (a + b))

    def test_canonical_id_still_passes_through(self) -> None:
        body = _do("/api/ds-shape?champion=LeeSin").body()
        self.assertEqual(body["archetype_source"], "champion")
        self.assertEqual(body["champion"], "LeeSin")


class NegativeKnobTests(unittest.TestCase):
    def test_negative_utility_never_raises_utility(self) -> None:
        for knob in (-1, -2):
            with self.subTest(knob=knob):
                body = _do(f"/api/ds-shape?champion=Darius&utility={knob}").body()
                self.assertEqual(body["knobs"]["utility"], knob)
                self.assertEqual(body["shaped"]["utility"], 0.0)
                self.assertEqual(body["shaped_pct"]["utility"], 0)
                # Only the held axis moved, so the other two are identity.
                for ax in ("damage", "survivability"):
                    self.assertAlmostEqual(body["shaped"][ax],
                                           body["baseline"][ax], delta=1e-9)

    # Rows near the WEIGHT_MIN floor / WEIGHT_MAX cap, where the shaper's
    # clamp + renormalize moved a SINGLE knob's axis the wrong way.
    _EDGE_ROWS = ([0.95, 0.05], [0.05, 0.95], [0.051, 0.949], [0.949, 0.051],
                  [1, 0], [0, 1], [0.9, 0.1], [0.5, 0.5])

    def _grid_violations(self, champ: str) -> list:
        bad = []
        rng = range(-2, 3)
        for d in rng:
            for s in rng:
                for u in rng:
                    knobs = {"damage": d, "survivability": s, "utility": u}
                    body = _do(f"/api/ds-shape?champion={champ}&damage={d}"
                               f"&survivability={s}&utility={u}").body()
                    shp, base = body["shaped"], body["baseline"]
                    if abs(sum(shp.values()) - 1.0) > 1e-9:
                        bad.append((champ, knobs, "sum", sum(shp.values())))
                    for ax, k in knobs.items():
                        if k < 0 and shp[ax] > base[ax] + 1e-12:
                            bad.append((champ, knobs, ax, "raised"))
                        if k > 0 and shp[ax] < base[ax] - 1e-12:
                            bad.append((champ, knobs, ax, "lowered"))
        return bad

    def test_no_knob_moves_its_axis_the_wrong_way_shipped_table(self) -> None:
        champs = ["Zzzznotachamp"] + sorted(
            hybrid._load_archetype_weights()["champions"])
        bad = []
        for champ in champs:
            bad.extend(self._grid_violations(champ))
        self.assertEqual(bad[:5], [], f"{len(bad)} violations")

    def test_no_knob_moves_its_axis_the_wrong_way_edge_rows(self) -> None:
        bad = []
        for row in self._EDGE_ROWS:
            table = {"default": [0.5, 0.5], "champions": {"Darius": row}}
            with _TableOverride(table):
                bad.extend((row,) + v for v in self._grid_violations("Darius"))
        self.assertEqual(bad[:5], [], f"{len(bad)} violations")

    def test_two_negative_knobs_never_raise_either(self) -> None:
        # Measured pre-fix: Darius damage -1, survivability -2 took damage
        # 0.65 -> 0.74 (the renormalization outran the knob).
        body = _do("/api/ds-shape?champion=Darius&damage=-1"
                   "&survivability=-2").body()
        self.assertLessEqual(body["shaped"]["damage"],
                             body["baseline"]["damage"] + 1e-12)
        self.assertLessEqual(body["shaped"]["survivability"],
                             body["baseline"]["survivability"] + 1e-12)

    def test_held_axis_keeps_the_others_shaping(self) -> None:
        body = _do("/api/ds-shape?champion=Darius&damage=1&utility=-2").body()
        self.assertEqual(body["shaped"]["utility"], 0.0)
        self.assertGreater(body["shaped"]["damage"], body["baseline"]["damage"])
        self.assertAlmostEqual(sum(body["shaped"].values()), 1.0, delta=1e-9)

    def test_positive_utility_still_raises_utility(self) -> None:
        body = _do("/api/ds-shape?champion=Darius&utility=1").body()
        self.assertGreater(body["shaped"]["utility"], 0.0)


class MalformedTableTests(unittest.TestCase):
    _BAD_ROWS = (
        "x", None, [0.6], [0.6, 0.4, 0.1], [math.nan, 0.4], [math.inf, 0.1],
        [-0.2, 1.2], [0, 0], [True, False], ["0.6", "0.4"], {"a": 1},
    )

    def test_bad_row_falls_back_to_default(self) -> None:
        for row in self._BAD_ROWS:
            with self.subTest(row=row):
                table = {"default": [0.5, 0.5], "champions": {"Darius": row}}
                with _TableOverride(table), self.assertLogs(
                        "rc.web_dashboard", level="WARNING"):
                    h = _do("/api/ds-shape?champion=Darius&damage=1")
                self.assertEqual(h.sent[0], 200)
                body = h.body()
                self.assertTrue(body["ok"])
                self.assertEqual(body["archetype_source"], "default")
                self.assertEqual(body["baseline"]["damage"], 0.5)
                self.assertEqual(body["baseline_pct"]["survivability"], 50)

    def test_bad_default_falls_back_to_balanced(self) -> None:
        for default in ("x", [math.nan, 0.5], [0, 0], None):
            with self.subTest(default=default):
                with _TableOverride({"default": default, "champions": {}}):
                    body = _do("/api/ds-shape?champion=Darius").body()
                self.assertEqual(body["archetype_source"], "default")
                self.assertEqual(body["baseline"]["damage"], 0.5)
                self.assertEqual(body["baseline"]["survivability"], 0.5)

    def test_non_dict_table_or_champions_degrades(self) -> None:
        # A list / str 'champions' CONTAINING the name passes a bare `in`
        # test and then fails the subscript, so it must be type-guarded.
        for table in ([1, 2], "x",
                      {"default": [0.5, 0.5], "champions": ["Darius"]},
                      {"default": [0.5, 0.5], "champions": "xDariusx"}):
            with self.subTest(table=table):
                with _TableOverride(table):
                    h = _do("/api/ds-shape?champion=Darius")
                self.assertEqual(h.sent[0], 200)
                self.assertEqual(h.body()["archetype_source"], "default")

    def test_valid_row_is_normalized_to_one(self) -> None:
        table = {"default": [0.5, 0.5], "champions": {"Darius": [3, 1]}}
        with _TableOverride(table):
            body = _do("/api/ds-shape?champion=Darius").body()
        self.assertEqual(body["archetype_source"], "champion")
        self.assertAlmostEqual(body["baseline"]["damage"], 0.75)
        self.assertEqual(body["baseline_pct"],
                         {"damage": 75, "survivability": 25, "utility": 0})


class ChampionParamTests(unittest.TestCase):
    def test_over_long_champion_is_400(self) -> None:
        h = _do("/api/ds-shape?champion=" + "A" * (rt._MAX_CHAMPION_LEN + 1))
        self.assertEqual(h.sent[0], 400)
        self.assertFalse(h.body()["ok"])

    def test_max_length_champion_is_served(self) -> None:
        h = _do("/api/ds-shape?champion=" + "A" * rt._MAX_CHAMPION_LEN)
        self.assertEqual(h.sent[0], 200)
        self.assertEqual(h.body()["archetype_source"], "default")

    def test_control_characters_are_400(self) -> None:
        for raw in ("Dar%00ius", "Dar%0Aius", "Dar%1Bius", "Dar%7Fius"):
            with self.subTest(raw=raw):
                h = _do(f"/api/ds-shape?champion={raw}")
                self.assertEqual(h.sent[0], 400)
                body = h.body()
                self.assertNotIn("champion", body)

    def test_knob_bounds_are_the_shapers(self) -> None:
        self.assertEqual((rt._KNOB_MIN, rt._KNOB_MAX),
                         (shaper.KNOB_MIN, shaper.KNOB_MAX))


class ElapsedClockTests(unittest.TestCase):
    def test_wall_clock_step_back_never_negative(self) -> None:
        ticks = iter([1_000_000.0, 10.0, 5.0, 1.0, 0.5, 0.1])
        fake = types.SimpleNamespace(
            time=lambda: next(ticks),
            perf_counter=_real_time.perf_counter,
            monotonic=_real_time.monotonic,
        )
        saved = rt.time
        rt.time = fake
        try:
            body = _do("/api/ds-shape?champion=Darius").body()
        finally:
            rt.time = saved
        # Both ends must read the same monotonic clock: a wall-clock read at
        # either end makes the difference meaningless (negative or huge).
        self.assertGreaterEqual(body["elapsed_ms"], 0)
        self.assertLess(body["elapsed_ms"], fleet_test_guard.budget(60) * 1000)


class NestedErrorTests(unittest.TestCase):
    def test_failed_error_reply_is_logged(self) -> None:
        h = _H("/api/ds-shape?champion=Darius", fail=True)
        with self.assertLogs("rc.web_dashboard", level="DEBUG") as cap:
            rt._serve_ds_shape(h)
        self.assertTrue(
            any("error reply" in r.getMessage() for r in cap.records),
            [r.getMessage() for r in cap.records],
        )


if __name__ == "__main__":
    logging.basicConfig()
    unittest.main()

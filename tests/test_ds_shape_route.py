"""Tests for dashboard/routes_ds_shape.py - OQ14 SHAPED-EMPHASIS preview.

Sibling of test_routes_ds_knobs.py; mirrors its StubHandler pattern. The
route is a thin, read-only wire over the ALREADY-SHIPPED pure primitive
core/shaper.apply_shaper - it emits a baseline archetype emphasis triple
(damage / survivability / utility) from the real per-champion
archetype_weights.json table and the shaped triple after the three
operator knobs apply. NO engine math, NO ENGINE_VERSION bump, NO DS
engine call, NO snapshot.

These tests pin the HTTP contract + the shaper INVARIANTS (not fragile
floats, per repo Testing Discipline):
  * RouteContractTests   - blank champion 400, JSON content-type, all keys.
  * ShapeInvariantTests  - damage+1 raises damage / lowers survivability;
    shaped sums to ~1.0; all-zero knobs are identity (shaped == baseline).
  * ArchetypeSourceTests - known champ -> "champion"; unknown -> "default"
    with a balanced 0.5/0.5/0.0 baseline.
  * ClampTests           - out-of-range knob (damage=9) clamps to +2, no crash.
  * AsciiHygieneTests    - no em/en-dashes or smart quotes in route + test.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_ds_shape as rt

_KNOWN = "Darius"          # in archetype_weights.json as [0.65, 0.35]
_UNKNOWN = "Zzzznotachamp"  # absent -> default [0.5, 0.5]


class StubHandler:
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
    rt._serve_ds_shape(h)
    return h


class RouteContractTests(unittest.TestCase):
    def test_blank_champion_returns_400(self) -> None:
        h = _do("/api/ds-shape?champion=")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_missing_champion_returns_400(self) -> None:
        h = _do("/api/ds-shape")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_response_is_json(self) -> None:
        h = _do(f"/api/ds-shape?champion={_KNOWN}")
        self.assertEqual(h.last_ct, "application/json")

    def test_response_has_all_keys(self) -> None:
        h = _do(f"/api/ds-shape?champion={_KNOWN}")
        body = h.parsed()
        for key in (
            "ok", "champion", "knobs", "baseline", "shaped",
            "baseline_pct", "shaped_pct",
        ):
            self.assertIn(key, body)
        # nested triples all carry the three literal axis keys
        for tri in ("baseline", "shaped", "baseline_pct", "shaped_pct"):
            for axis in ("damage", "survivability", "utility"):
                self.assertIn(axis, body[tri])


class ShapeInvariantTests(unittest.TestCase):
    def test_damage_up_raises_damage_lowers_survivability(self) -> None:
        h = _do(f"/api/ds-shape?champion={_KNOWN}&damage=1&survivability=0&utility=0")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertGreater(body["shaped"]["damage"], body["baseline"]["damage"])
        self.assertLess(
            body["shaped"]["survivability"], body["baseline"]["survivability"]
        )

    def test_shaped_sums_to_one(self) -> None:
        h = _do(f"/api/ds-shape?champion={_KNOWN}&damage=1&survivability=0&utility=0")
        body = h.parsed()
        total = sum(body["shaped"].values())
        self.assertAlmostEqual(total, 1.0, delta=1e-6)

    def test_all_zero_knobs_is_identity(self) -> None:
        h = _do(f"/api/ds-shape?champion={_KNOWN}&damage=0&survivability=0&utility=0")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["knobs"], {"damage": 0, "survivability": 0, "utility": 0})
        for axis in ("damage", "survivability", "utility"):
            self.assertAlmostEqual(
                body["shaped"][axis], body["baseline"][axis], delta=1e-9
            )

    def test_no_knobs_defaults_to_zero_identity(self) -> None:
        # Knobs omitted entirely default to 0 -> identity.
        h = _do(f"/api/ds-shape?champion={_KNOWN}")
        body = h.parsed()
        self.assertEqual(body["knobs"], {"damage": 0, "survivability": 0, "utility": 0})
        for axis in ("damage", "survivability", "utility"):
            self.assertAlmostEqual(
                body["shaped"][axis], body["baseline"][axis], delta=1e-9
            )


class ArchetypeSourceTests(unittest.TestCase):
    def test_known_champion_source(self) -> None:
        h = _do(f"/api/ds-shape?champion={_KNOWN}")
        body = h.parsed()
        self.assertEqual(body["archetype_source"], "champion")
        # Darius ships as [0.65, 0.35] -> baseline damage/surv, utility 0.
        self.assertAlmostEqual(body["baseline"]["damage"], 0.65, delta=1e-9)
        self.assertAlmostEqual(body["baseline"]["survivability"], 0.35, delta=1e-9)
        self.assertAlmostEqual(body["baseline"]["utility"], 0.0, delta=1e-9)

    def test_unknown_champion_uses_default_balanced(self) -> None:
        h = _do(f"/api/ds-shape?champion={_UNKNOWN}")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["archetype_source"], "default")
        # default [0.5, 0.5] -> damage == surv == 0.5, utility 0.
        self.assertAlmostEqual(body["baseline"]["damage"], 0.5, delta=1e-9)
        self.assertAlmostEqual(body["baseline"]["survivability"], 0.5, delta=1e-9)
        self.assertAlmostEqual(body["baseline"]["utility"], 0.0, delta=1e-9)

    def test_pct_are_ints(self) -> None:
        h = _do(f"/api/ds-shape?champion={_KNOWN}")
        body = h.parsed()
        for tri in ("baseline_pct", "shaped_pct"):
            for axis in ("damage", "survivability", "utility"):
                self.assertIsInstance(body[tri][axis], int)
        self.assertEqual(body["baseline_pct"]["damage"], 65)
        self.assertEqual(body["baseline_pct"]["survivability"], 35)
        self.assertEqual(body["baseline_pct"]["utility"], 0)


class ClampTests(unittest.TestCase):
    def test_out_of_range_knob_clamps(self) -> None:
        h = _do(f"/api/ds-shape?champion={_KNOWN}&damage=9")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["knobs"]["damage"], 2)

    def test_negative_out_of_range_knob_clamps(self) -> None:
        h = _do(f"/api/ds-shape?champion={_KNOWN}&survivability=-9")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["knobs"]["survivability"], -2)

    def test_non_numeric_knob_defaults_zero(self) -> None:
        h = _do(f"/api/ds-shape?champion={_KNOWN}&damage=abc")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["knobs"]["damage"], 0)


class AsciiHygieneTests(unittest.TestCase):
    # Codepoints (not literals) so THIS test file stays 7-bit ASCII:
    # em-dash, en-dash, left/right double + single smart quotes.
    _BANNED = tuple(chr(c) for c in (0x2014, 0x2013, 0x201C, 0x201D, 0x2018, 0x2019))

    def _check(self, rel: str) -> None:
        p = pathlib.Path(__file__).resolve().parent.parent / rel
        text = p.read_text(encoding="utf-8")
        for ch in self._BANNED:
            self.assertNotIn(ch, text, f"banned glyph U+{ord(ch):04X} in {rel}")

    def test_route_ascii(self) -> None:
        self._check("dashboard/routes_ds_shape.py")

    def test_test_ascii(self) -> None:
        self._check("tests/test_ds_shape_route.py")


if __name__ == "__main__":
    unittest.main()

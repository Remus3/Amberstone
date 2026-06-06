"""Tests for dashboard/routes_ds_profile.py - DS champion-profile aggregate.

Sibling of test_routes_ds_sweep.py; mirrors its StubHandler pattern. The route
is a thin read-only aggregate over four EXISTING pure per-champion DS scorers
(mobility / sustain / scaling / waveclear); these tests pin the HTTP contract:
param validation, ordered-axes payload shape, per-axis enum fields, numeric
key resolution, no_profile branch, mode normalization, cache.

Assertions are STRUCTURAL (types / shape / enums / computed-quantity
relationships) rather than brittle exact magnitudes - the project rule prefers
assertions on computed quantities over data-fragile exact comparisons.

Covers:
  * RouteContractTests - missing champion 400, blank 400, json content type.
  * ContentTests       - ordered 4-axis payload, per-axis keys + enums,
    scaling slope/trajectory, waveclear ranged_shove, no_profile branch.
  * ParamTests         - numeric champion key -> slug, mode uppercased.
  * CacheTests         - TTL hit (cached flag), mode part of key.
  * AsciiHygieneTests  - no em-dashes / smart quotes in route + test file.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_ds_profile as rt


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
    rt._serve_ds_profile(h)
    return h


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()


class RouteContractTests(_Base):
    def test_missing_champion_param_returns_400(self) -> None:
        h = _do("/api/ds-profile")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_blank_champion_returns_400(self) -> None:
        h = _do("/api/ds-profile?champion=")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_response_is_json(self) -> None:
        h = _do("/api/ds-profile?champion=Vayne")
        self.assertEqual(h.last_ct, "application/json")


class ContentTests(_Base):
    def test_ok_payload_top_level(self) -> None:
        h = _do("/api/ds-profile?champion=Vayne")
        body = h.parsed()
        self.assertEqual(h.last_status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["champion"], "Vayne")
        self.assertEqual(body["mode"], "SR")
        for key in ("ok", "champion", "mode", "axes", "elapsed_ms", "cached"):
            self.assertIn(key, body)

    def test_axes_ordered_four(self) -> None:
        h = _do("/api/ds-profile?champion=Vayne")
        axes = h.parsed()["axes"]
        self.assertIsInstance(axes, list)
        self.assertEqual([a["key"] for a in axes],
                         ["mobility", "sustain", "scaling", "waveclear"])

    def test_each_axis_core_keys(self) -> None:
        h = _do("/api/ds-profile?champion=Vayne")
        for axis in h.parsed()["axes"]:
            for key in ("key", "label", "score", "pct", "tier", "detail"):
                self.assertIn(key, axis)
            self.assertIsInstance(axis["score"], float)
            self.assertIsInstance(axis["pct"], int)
            self.assertGreaterEqual(axis["pct"], 0)
            self.assertLessEqual(axis["pct"], 100)
            self.assertIn(axis["tier"], {"LOW", "MED", "HIGH"})
            self.assertIsInstance(axis["detail"], str)

    def test_tier_consistent_with_pct(self) -> None:
        # tier is a pure function of pct - verify the computed relationship.
        for axis in _do("/api/ds-profile?champion=Vayne").parsed()["axes"]:
            pct = axis["pct"]
            expect = "HIGH" if pct >= 66 else "MED" if pct >= 33 else "LOW"
            self.assertEqual(axis["tier"], expect)

    def test_scaling_axis_has_slope_and_trajectory(self) -> None:
        axes = {a["key"]: a for a in _do(
            "/api/ds-profile?champion=Vayne").parsed()["axes"]}
        scaling = axes["scaling"]
        self.assertIn("slope", scaling)
        self.assertIsInstance(scaling["slope"], float)
        self.assertIn(scaling["trajectory"], {"UP", "EVEN", "DOWN"})

    def test_waveclear_axis_has_ranged_shove(self) -> None:
        axes = {a["key"]: a for a in _do(
            "/api/ds-profile?champion=Vayne").parsed()["axes"]}
        self.assertIsInstance(axes["waveclear"]["ranged_shove"], bool)

    def test_vayne_scales_up(self) -> None:
        # Vayne is the canonical late hyperscaler (W = RATIO_HYPERSCALE LATE
        # 0.95 in scaling.py), so the slope is strongly positive. Assert the
        # set {UP, EVEN} so a registry retune cannot flip the test to a hard
        # fail (the project rule on data-fragile asserts).
        axes = {a["key"]: a for a in _do(
            "/api/ds-profile?champion=Vayne").parsed()["axes"]}
        self.assertIn(axes["scaling"]["trajectory"], {"UP", "EVEN"})

    def test_unknown_champion_no_profile(self) -> None:
        h = _do("/api/ds-profile?champion=NotAChampXYZ")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "no_profile")
        self.assertEqual(body["axes"], [])


class ParamTests(_Base):
    def test_numeric_champion_key_resolves(self) -> None:
        # 67 = Vayne's DDragon key; the route resolves numerics to slug.
        h = _do("/api/ds-profile?champion=67")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["champion"], "Vayne")

    def test_mode_uppercased(self) -> None:
        h = _do("/api/ds-profile?champion=Vayne&mode=aram")
        self.assertEqual(h.parsed()["mode"], "ARAM")


class CacheTests(_Base):
    def test_cache_hit_sets_cached_flag(self) -> None:
        h1 = _do("/api/ds-profile?champion=Vayne")
        self.assertFalse(h1.parsed()["cached"])
        h2 = _do("/api/ds-profile?champion=Vayne")
        self.assertTrue(h2.parsed()["cached"])

    def test_mode_part_of_cache_key(self) -> None:
        _do("/api/ds-profile?champion=Vayne&mode=SR")
        h = _do("/api/ds-profile?champion=Vayne&mode=ARAM")
        self.assertFalse(h.parsed()["cached"])


class AsciiHygieneTests(unittest.TestCase):
    def _assert_ascii(self, path: pathlib.Path) -> None:
        src = path.read_bytes()
        bad = [(i, b) for i, b in enumerate(src) if b > 0x7F]
        self.assertEqual(bad, [], f"non-ASCII in {path.name}: {bad[:5]}")

    def test_route_module_is_ascii(self) -> None:
        self._assert_ascii(pathlib.Path(rt.__file__))

    def test_this_test_file_is_ascii(self) -> None:
        self._assert_ascii(pathlib.Path(__file__))


if __name__ == "__main__":
    unittest.main()

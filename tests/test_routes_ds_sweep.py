"""Tests for dashboard/routes_ds_sweep.py - DS stat-sweep graph (competitor
lift #3, docs/COMPETITOR_LIFT_2026-05-30.md).

Sibling of test_routes_cooldown_watch.py; mirrors its StubHandler pattern.
The route is a thin wire over
agents.daemon_slayer.dps_sweep.compute_dps_sweep (covered by
tests/test_ds_sweep_2026_05_30.py); these tests pin the HTTP contract:
param validation, payload shape, axis aliasing, default-build resolution,
cache.

Covers:
  * RouteContractTests - missing champion 400, unknown axis 400, unknown
    champion 200 no_points, json content type.
  * ContentTests       - ok payload shape, top-level fields, monotonic
    armor curve through the route, axis alias normalization.
  * ParamTests         - explicit item_ids honored, level/max/step parsed,
    numeric champion key resolved to slug.
  * CacheTests         - TTL hit (cached flag), axis part of key, item-order
    invariance.
  * AsciiHygieneTests  - no em-dashes / smart quotes in route + test file.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_ds_sweep as rt


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
    rt._serve_ds_sweep(h)
    return h


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()


class RouteContractTests(_Base):
    def test_missing_champion_param_returns_400(self) -> None:
        h = _do("/api/ds-sweep")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_blank_champion_returns_400(self) -> None:
        h = _do("/api/ds-sweep?champion=")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_unknown_axis_returns_400(self) -> None:
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=bogus")
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertFalse(body["ok"])
        self.assertIn("supported", body)

    def test_unknown_champion_returns_no_points(self) -> None:
        h = _do("/api/ds-sweep?champion=NotAChampionXYZ&axis=armor")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "no_points")
        self.assertEqual(body["points"], [])

    def test_response_is_json(self) -> None:
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=armor")
        self.assertEqual(h.last_ct, "application/json")


class ContentTests(_Base):
    def test_ok_payload_shape(self) -> None:
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=armor")
        body = h.parsed()
        self.assertEqual(h.last_status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["champion"], "Caitlyn")
        self.assertEqual(body["axis"], "target_armor")
        self.assertEqual(body["mode"], "SR")
        self.assertGreater(body["count"], 1)
        self.assertEqual(body["count"], len(body["points"]))

    def test_top_level_fields_present(self) -> None:
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=armor")
        body = h.parsed()
        for key in ("ok", "champion", "axis", "mode", "level",
                    "item_ids", "points", "count", "elapsed_ms", "cached"):
            self.assertIn(key, body)

    def test_point_shape(self) -> None:
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=armor")
        pt = h.parsed()["points"][0]
        self.assertEqual(set(pt), {"x", "dps", "phase"})

    def test_armor_curve_monotonic_non_increasing(self) -> None:
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=armor&step=50")
        dps = [p["dps"] for p in h.parsed()["points"]]
        for i in range(1, len(dps)):
            self.assertLessEqual(dps[i], dps[i - 1] + 1e-6)

    def test_default_build_resolved_when_items_omitted(self) -> None:
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=armor")
        # item_ids omitted -> route resolves a canonical archetype build.
        self.assertTrue(h.parsed()["item_ids"])

    def test_axis_alias_target_armor(self) -> None:
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=target_armor")
        self.assertEqual(h.parsed()["axis"], "target_armor")

    def test_axis_mr_normalizes(self) -> None:
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=mr")
        self.assertEqual(h.parsed()["axis"], "target_mr")

    def test_level_axis_ok(self) -> None:
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=level")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["axis"], "level")
        self.assertGreater(body["count"], 1)


class ParamTests(_Base):
    def test_explicit_item_ids_honored(self) -> None:
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=armor&item_ids=3094,3031")
        self.assertEqual(h.parsed()["item_ids"], ["3094", "3031"])

    def test_level_param_recorded(self) -> None:
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=armor&level=16")
        self.assertEqual(h.parsed()["level"], 16)

    def test_step_controls_point_count(self) -> None:
        coarse = _do("/api/ds-sweep?champion=Caitlyn&axis=armor&step=100")
        rt._reset_caches()
        fine = _do("/api/ds-sweep?champion=Caitlyn&axis=armor&step=25")
        self.assertGreater(fine.parsed()["count"], coarse.parsed()["count"])

    def test_numeric_champion_key_resolves(self) -> None:
        # 51 = Caitlyn's DDragon key; the route resolves numerics to slug.
        h = _do("/api/ds-sweep?champion=51&axis=armor")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["champion"], "Caitlyn")

    def test_mode_uppercased(self) -> None:
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=armor&mode=aram")
        self.assertEqual(h.parsed()["mode"], "ARAM")


class CacheTests(_Base):
    def test_cache_hit_sets_cached_flag(self) -> None:
        h1 = _do("/api/ds-sweep?champion=Caitlyn&axis=armor")
        self.assertFalse(h1.parsed()["cached"])
        h2 = _do("/api/ds-sweep?champion=Caitlyn&axis=armor")
        self.assertTrue(h2.parsed()["cached"])

    def test_axis_part_of_cache_key(self) -> None:
        _do("/api/ds-sweep?champion=Caitlyn&axis=armor")
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=mr")
        self.assertFalse(h.parsed()["cached"])

    def test_item_order_invariant(self) -> None:
        _do("/api/ds-sweep?champion=Caitlyn&axis=armor&item_ids=3094,3031")
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=armor&item_ids=3031,3094")
        self.assertTrue(h.parsed()["cached"])

    def test_level_part_of_cache_key(self) -> None:
        _do("/api/ds-sweep?champion=Caitlyn&axis=armor&level=11")
        h = _do("/api/ds-sweep?champion=Caitlyn&axis=armor&level=16")
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

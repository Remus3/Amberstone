"""Tests for dashboard/routes_ds_skill_order.py - DS ability max-order route.

Sibling of test_routes_ds_profile.py; mirrors its StubHandler pattern. The
route is a presentation-only lift over EXISTING local data - it reads the
shipped champions.json snapshot and surfaces each champion's ability max order
(e.g. "Q > E > W") plus ult levels. NO engine math, NO new dependency.

Assertions on the shipped 16.13.1 snapshot are computed-quantity relationships
(length / membership / permutation) plus two deterministic pins (Aatrox, Lux)
that are stable given the shipped skill_order arrays.

Covers:
  * RouteContractTests - missing champion 400, blank 400, json content type.
  * ContentTests       - 18-element skill_order, 3-element max_order permutation
    of {Q,W,E}, max_order_str join, ult_levels ints, Aatrox/Lux pins,
    no_skill_order branch.
  * ParamTests         - numeric DDragon key -> slug, mode uppercased.
  * CacheTests         - TTL hit (cached flag), mode part of key.
  * AsciiHygieneTests  - no non-ASCII bytes in route + test file.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_ds_skill_order as rt


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
    rt._serve_ds_skill_order(h)
    return h


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()


class RouteContractTests(_Base):
    def test_missing_champion_param_returns_400(self) -> None:
        h = _do("/api/ds-skill-order")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_blank_champion_returns_400(self) -> None:
        h = _do("/api/ds-skill-order?champion=")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_response_is_json(self) -> None:
        h = _do("/api/ds-skill-order?champion=Aatrox")
        self.assertEqual(h.last_ct, "application/json")


class ContentTests(_Base):
    def test_ok_payload_top_level(self) -> None:
        h = _do("/api/ds-skill-order?champion=Aatrox")
        body = h.parsed()
        self.assertEqual(h.last_status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["champion"], "Aatrox")
        self.assertEqual(body["mode"], "SR")
        for key in ("ok", "champion", "mode", "skill_order", "max_order",
                    "max_order_str", "ult_levels", "elapsed_ms", "cached"):
            self.assertIn(key, body)

    def test_skill_order_shape(self) -> None:
        so = _do("/api/ds-skill-order?champion=Aatrox").parsed()["skill_order"]
        self.assertIsInstance(so, list)
        self.assertEqual(len(so), 18)
        for x in so:
            self.assertIn(x, {"Q", "W", "E", "R"})

    def test_max_order_is_permutation_of_basics(self) -> None:
        mo = _do("/api/ds-skill-order?champion=Aatrox").parsed()["max_order"]
        self.assertIsInstance(mo, list)
        self.assertEqual(len(mo), 3)
        self.assertEqual(sorted(mo), ["E", "Q", "W"])

    def test_max_order_str_matches_join(self) -> None:
        body = _do("/api/ds-skill-order?champion=Aatrox").parsed()
        self.assertEqual(body["max_order_str"], " > ".join(body["max_order"]))

    def test_ult_levels_are_ints(self) -> None:
        ult = _do("/api/ds-skill-order?champion=Aatrox").parsed()["ult_levels"]
        self.assertIsInstance(ult, list)
        for v in ult:
            self.assertIsInstance(v, int)
        self.assertEqual(ult, [6, 11, 16])

    def test_aatrox_max_order_pin(self) -> None:
        body = _do("/api/ds-skill-order?champion=Aatrox").parsed()
        self.assertEqual(body["max_order"], ["Q", "E", "W"])
        self.assertEqual(body["max_order_str"], "Q > E > W")

    def test_lux_max_order_pin(self) -> None:
        body = _do("/api/ds-skill-order?champion=Lux").parsed()
        self.assertEqual(body["max_order"], ["E", "Q", "W"])
        self.assertEqual(body["max_order_str"], "E > Q > W")

    def test_unknown_champion_no_skill_order(self) -> None:
        h = _do("/api/ds-skill-order?champion=NotAChampXYZ")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "no_skill_order")
        self.assertEqual(body["skill_order"], [])


class ParamTests(_Base):
    def test_numeric_champion_key_resolves(self) -> None:
        # 266 = Aatrox's DDragon key; the route resolves numerics to slug.
        by_num = _do("/api/ds-skill-order?champion=266").parsed()
        self.assertEqual(by_num["champion"], "Aatrox")
        self.assertEqual(by_num["max_order"], ["Q", "E", "W"])

    def test_mode_uppercased(self) -> None:
        body = _do("/api/ds-skill-order?champion=Aatrox&mode=aram").parsed()
        self.assertEqual(body["mode"], "ARAM")


class CacheTests(_Base):
    def test_cache_hit_sets_cached_flag(self) -> None:
        h1 = _do("/api/ds-skill-order?champion=Aatrox")
        self.assertFalse(h1.parsed()["cached"])
        h2 = _do("/api/ds-skill-order?champion=Aatrox")
        self.assertTrue(h2.parsed()["cached"])

    def test_mode_part_of_cache_key(self) -> None:
        _do("/api/ds-skill-order?champion=Aatrox&mode=SR")
        h = _do("/api/ds-skill-order?champion=Aatrox&mode=ARAM")
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

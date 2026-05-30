"""Tests for dashboard/routes_spike_markers.py - live power-spike markers
(competitor lift #4, docs/COMPETITOR_LIFT_2026-05-30.md).

Sibling of test_routes_cooldown_watch.py; mirrors its StubHandler pattern.
The route is a thin wire over
agents.daemon_slayer.spike_markers.compute_spike_markers (covered by
agents/daemon_slayer/tests/test_spike_markers_2026_05_30.py); these tests
pin the HTTP contract: param validation, payload shape, crossed/next math
end-to-end, cache.

Requests pass item_count explicitly + rely on the engine's annotate_dps
default; the engine fail-softs the dps_at annotation so the route does not
require a resolvable DS snapshot to return a 200.

Covers:
  * RouteContractTests - missing champion 400, blank champion 400, json ct.
  * ContentTests - marker payload shape, crossed/next via live level +
    item_count, exactly one next.
  * ParamTests - level clamp, items proxy, minor breakpoints, mode echo.
  * CacheTests - TTL hit (cached flag), cache key sensitivity.
  * AsciiHygieneTests - no em-dashes / smart quotes in route + test file.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_spike_markers as rt


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
    rt._serve_spike_markers(h)
    return h


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()


class RouteContractTests(_Base):
    def test_missing_champion_param_returns_400(self) -> None:
        h = _do("/api/spike-markers")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_blank_champion_returns_400(self) -> None:
        h = _do("/api/spike-markers?champion=")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_response_is_json(self) -> None:
        h = _do("/api/spike-markers?champion=Jinx&level=8&item_count=1")
        self.assertEqual(h.last_ct, "application/json")
        self.assertEqual(h.last_status, 200)


class ContentTests(_Base):
    def test_payload_shape(self) -> None:
        h = _do("/api/spike-markers?champion=Jinx&level=8&item_count=1")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["champion"], "Jinx")
        self.assertEqual(body["level"], 8)
        self.assertEqual(body["count"], 6)
        self.assertIn("markers", body)
        self.assertIn("next", body)
        m0 = body["markers"][0]
        for k in ("kind", "threshold", "label", "crossed", "next"):
            self.assertIn(k, m0)

    def test_level_6_crossed_at_level_8(self) -> None:
        h = _do("/api/spike-markers?champion=Aatrox&level=8&item_count=0")
        markers = h.parsed()["markers"]
        lv = {m["threshold"]: m["crossed"]
              for m in markers if m["kind"] == "level"}
        self.assertTrue(lv[6])
        self.assertFalse(lv[11])
        self.assertFalse(lv[16])

    def test_exactly_one_next(self) -> None:
        h = _do("/api/spike-markers?champion=Jinx&level=8&item_count=1")
        markers = h.parsed()["markers"]
        nxt = [m for m in markers if m["next"]]
        self.assertEqual(len(nxt), 1)

    def test_next_field_populated(self) -> None:
        h = _do("/api/spike-markers?champion=Jinx&level=8&item_count=1")
        body = h.parsed()
        self.assertIsNotNone(body["next"])
        # gaps: lvl11=3 lvl16=8 item2=1 item3=2 -> nearest is item 2.
        self.assertEqual(body["next"]["kind"], "item")
        self.assertEqual(body["next"]["threshold"], 2)

    def test_all_crossed_next_null(self) -> None:
        h = _do("/api/spike-markers?champion=Jinx&level=18&item_count=3")
        body = h.parsed()
        self.assertIsNone(body["next"])
        self.assertTrue(all(m["crossed"] for m in body["markers"]))

    def test_item_markers_track_item_count(self) -> None:
        h = _do("/api/spike-markers?champion=Jinx&level=8&item_count=2")
        markers = h.parsed()["markers"]
        it = {m["threshold"]: m["crossed"]
              for m in markers if m["kind"] == "item"}
        self.assertTrue(it[1])
        self.assertTrue(it[2])
        self.assertFalse(it[3])


class ParamTests(_Base):
    def test_level_clamped_above_18(self) -> None:
        h = _do("/api/spike-markers?champion=Jinx&level=25&item_count=0")
        self.assertEqual(h.parsed()["level"], 18)

    def test_default_level_is_1(self) -> None:
        h = _do("/api/spike-markers?champion=Jinx")
        self.assertEqual(h.parsed()["level"], 1)

    def test_items_proxy_item_count(self) -> None:
        # No item_count -> engine proxies min(len(items), 3).
        h = _do("/api/spike-markers?champion=Jinx&level=8&items=3094,3031")
        markers = h.parsed()["markers"]
        it = {m["threshold"]: m["crossed"]
              for m in markers if m["kind"] == "item"}
        self.assertTrue(it[1])
        self.assertTrue(it[2])
        self.assertFalse(it[3])

    def test_minor_adds_breakpoints(self) -> None:
        h = _do("/api/spike-markers?champion=Jinx&level=8&item_count=0&minor=1")
        markers = h.parsed()["markers"]
        lv = sorted(m["threshold"] for m in markers if m["kind"] == "level")
        self.assertEqual(lv, [6, 9, 11, 13, 16, 18])

    def test_garbage_level_falls_to_default(self) -> None:
        h = _do("/api/spike-markers?champion=Jinx&level=abc")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["level"], 1)

    def test_garbage_item_count_proxies(self) -> None:
        # Garbage item_count -> None -> engine proxies from items (none).
        h = _do("/api/spike-markers?champion=Jinx&level=8&item_count=xyz")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["item_count_done"], 0)


class CacheTests(_Base):
    def test_cache_hit_sets_cached_flag(self) -> None:
        h1 = _do("/api/spike-markers?champion=Jinx&level=8&item_count=1")
        self.assertFalse(h1.parsed()["cached"])
        h2 = _do("/api/spike-markers?champion=Jinx&level=8&item_count=1")
        self.assertTrue(h2.parsed()["cached"])

    def test_level_part_of_cache_key(self) -> None:
        _do("/api/spike-markers?champion=Jinx&level=8&item_count=1")
        h = _do("/api/spike-markers?champion=Jinx&level=9&item_count=1")
        self.assertFalse(h.parsed()["cached"])

    def test_item_count_part_of_cache_key(self) -> None:
        _do("/api/spike-markers?champion=Jinx&level=8&item_count=1")
        h = _do("/api/spike-markers?champion=Jinx&level=8&item_count=2")
        self.assertFalse(h.parsed()["cached"])

    def test_items_order_invariant_cache(self) -> None:
        _do("/api/spike-markers?champion=Jinx&level=8&items=3094,3031")
        h = _do("/api/spike-markers?champion=Jinx&level=8&items=3031,3094")
        self.assertTrue(h.parsed()["cached"])

    def test_minor_part_of_cache_key(self) -> None:
        _do("/api/spike-markers?champion=Jinx&level=8&item_count=1")
        h = _do("/api/spike-markers?champion=Jinx&level=8&item_count=1&minor=1")
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

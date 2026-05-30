"""Tests for dashboard/routes_ds_knobs.py - DS engine-knobs control panel
(competitor lift #1, docs/COMPETITOR_LIFT_2026-05-30.md "Lift 1").

Sibling of test_routes_cooldown_watch.py; mirrors its StubHandler pattern.
The route is a thin wire over agents.daemon_slayer.rank.rank_items (the
in-process DPS scorer, covered by the DS suite); these tests pin the HTTP
contract: param validation, payload shape, knob echo, budget filter, cache.

The load-bearing test (KnobReRankTests) proves the knob actually re-ranks:
a HIGH target_armor for a marksman produces a different ranked set than a
LOW target_armor - the build genuinely shifts for the chosen fight model.

Covers:
  * RouteContractTests - missing champion 400, blank champion 400, JSON ct.
  * ContentTests - ok payload shape, knob echo, auto-source default,
    override-source flag, rows shape.
  * KnobReRankTests - high vs low armor re-ranks (set/order differs);
    budget cap bounds the row gold.
  * CacheTests - TTL hit (cached flag), knob is part of the cache key,
    item-order invariance.
  * AsciiHygieneTests - no em-dashes / smart quotes in route + test file.

These tests load the live DataSnapshot (data/daemon_slayer/current.txt) -
patch-stable assertions only (no hardcoded item names / dps numbers that
drift across patches); we assert on STRUCTURE and on the re-rank DELTA.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_ds_knobs as rt

_MARKSMAN = "Caitlyn"   # ranged marksman; resists strongly re-weight its build


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
    rt._serve_ds_knobs(h)
    return h


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()


class RouteContractTests(_Base):
    def test_missing_champion_param_returns_400(self) -> None:
        h = _do("/api/ds-knobs")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_blank_champion_returns_400(self) -> None:
        h = _do("/api/ds-knobs?champion=")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_response_is_json(self) -> None:
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}")
        self.assertEqual(h.last_ct, "application/json")


class ContentTests(_Base):
    def test_ok_payload_shape(self) -> None:
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["champion"], _MARKSMAN)
        self.assertIn("knobs", body)
        self.assertIn("rows", body)
        self.assertGreater(body["count"], 0)
        self.assertEqual(body["count"], len(body["rows"]))

    def test_row_shape(self) -> None:
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}")
        row = h.parsed()["rows"][0]
        for k in ("item_id", "name", "delta_dps", "new_dps", "gold", "scorer"):
            self.assertIn(k, row)
        self.assertEqual(row["scorer"], "dps")

    def test_knob_echo_auto_source_by_default(self) -> None:
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&mode=SR")
        knobs = h.parsed()["knobs"]
        self.assertEqual(knobs["mode"], "SR")
        self.assertEqual(knobs["armor_source"], "auto")
        self.assertEqual(knobs["mr_source"], "auto")
        self.assertIsNone(knobs["budget"])
        # auto curve fills a positive resist for SR.
        self.assertGreater(knobs["target_armor"], 0.0)

    def test_knob_echo_override_source(self) -> None:
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&target_armor=222&target_mr=88")
        knobs = h.parsed()["knobs"]
        self.assertEqual(knobs["armor_source"], "override")
        self.assertEqual(knobs["mr_source"], "override")
        self.assertEqual(knobs["target_armor"], 222.0)
        self.assertEqual(knobs["target_mr"], 88.0)

    def test_level_clamped_and_echoed(self) -> None:
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&level=99")
        self.assertEqual(h.parsed()["knobs"]["level"], 18)


class KnobReRankTests(_Base):
    def _ranked_ids(self, armor: float) -> list[str]:
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&mode=SR&target_armor={armor}")
        body = h.parsed()
        self.assertTrue(body["ok"])
        return [r["item_id"] for r in body["rows"]]

    def test_high_armor_reranks_vs_low_armor(self) -> None:
        # The load-bearing proof: cranking enemy armor changes how the DPS
        # ranker weights candidates for a ranged marksman, so the top-N set
        # OR its order must differ between a low- and a high-armor fight
        # model. (Asserting on set/order difference is patch-stable; exact
        # item names drift across patches.)
        low = self._ranked_ids(20.0)
        high = self._ranked_ids(280.0)
        self.assertTrue(low, "low-armor ranking was empty")
        self.assertTrue(high, "high-armor ranking was empty")
        self.assertNotEqual(
            low, high,
            "raising target_armor did not re-rank the build - the knob is a no-op",
        )

    def test_budget_cap_bounds_row_gold(self) -> None:
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&mode=SR&budget=1500")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["knobs"]["budget"], 1500)
        self.assertTrue(body["rows"], "budget=1500 ranked nothing")
        self.assertTrue(all(r["gold"] <= 1500 for r in body["rows"]),
                        "a ranked row exceeded the gold cap")

    def test_zero_budget_is_uncapped(self) -> None:
        # budget<=0 -> None (no cap); a >1500g item can surface.
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&mode=SR&budget=0")
        body = h.parsed()
        self.assertIsNone(body["knobs"]["budget"])


class CacheTests(_Base):
    def test_cache_hit_sets_cached_flag(self) -> None:
        h1 = _do(f"/api/ds-knobs?champion={_MARKSMAN}&target_armor=80")
        self.assertFalse(h1.parsed()["cached"])
        h2 = _do(f"/api/ds-knobs?champion={_MARKSMAN}&target_armor=80")
        self.assertTrue(h2.parsed()["cached"])

    def test_armor_knob_part_of_cache_key(self) -> None:
        _do(f"/api/ds-knobs?champion={_MARKSMAN}&target_armor=80")
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&target_armor=250")
        self.assertFalse(h.parsed()["cached"])

    def test_budget_knob_part_of_cache_key(self) -> None:
        _do(f"/api/ds-knobs?champion={_MARKSMAN}&budget=1500")
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&budget=3000")
        self.assertFalse(h.parsed()["cached"])

    def test_item_order_invariant_cache_key(self) -> None:
        _do(f"/api/ds-knobs?champion={_MARKSMAN}&items=3006,1055")
        h = _do(f"/api/ds-knobs?champion={_MARKSMAN}&items=1055,3006")
        self.assertTrue(h.parsed()["cached"])


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

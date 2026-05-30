"""Tests for dashboard/routes_ds_relscore.py - DS relative-score bar
(competitor lift #3, docs/COMPETITOR_LIFT_2026-05-30.md "Lift 3").

Sibling of test_routes_ds_knobs.py; mirrors its StubHandler pattern. The
route is a READ-ONLY wire over agents.daemon_slayer.rank.rank_items (the
in-process DPS scorer, covered by the DS suite); these tests pin the HTTP
contract: param validation, payload shape, the relative-score math, cache.

The load-bearing test (RelScoreMathTests) proves the bar math: the top row
reads 100.0 and score_pct is monotonic non-increasing down the rows, and
each row's score_pct equals its own delta_dps / top_delta_dps * 100 (the
computed quantity, NOT a fragile literal item name / dps number).

Covers:
  * RouteContractTests - missing champion 400, blank champion 400, JSON ct.
  * ContentTests - ok payload shape, target echo (auto-resolved), row shape.
  * RelScoreMathTests - top row == 100.0, monotonic non-increasing,
    score_pct == delta_dps / top_delta_dps * 100 (engine grounding).
  * CacheTests - TTL hit (cached flag), level part of cache key,
    item-order invariance.
  * AsciiHygieneTests - no em-dashes / smart quotes in route + test file.

These tests load the live DataSnapshot (data/daemon_slayer/current.txt) -
patch-stable assertions only (no hardcoded item names / dps numbers that
drift across patches); we assert on STRUCTURE and on the COMPUTED bar math.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_ds_relscore as rt

_MARKSMAN = "Caitlyn"   # ranged marksman; a strong DPS ranking spread


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
    rt._serve_ds_relscore(h)
    return h


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()


class RouteContractTests(_Base):
    def test_missing_champion_param_returns_400(self) -> None:
        h = _do("/api/ds-relscore")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_blank_champion_returns_400(self) -> None:
        h = _do("/api/ds-relscore?champion=")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_response_is_json(self) -> None:
        h = _do(f"/api/ds-relscore?champion={_MARKSMAN}")
        self.assertEqual(h.last_ct, "application/json")


class ContentTests(_Base):
    def test_ok_payload_shape(self) -> None:
        h = _do(f"/api/ds-relscore?champion={_MARKSMAN}")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["champion"], _MARKSMAN)
        self.assertIn("target", body)
        self.assertIn("rows", body)
        self.assertGreater(body["count"], 0)
        self.assertEqual(body["count"], len(body["rows"]))

    def test_row_shape(self) -> None:
        h = _do(f"/api/ds-relscore?champion={_MARKSMAN}")
        row = h.parsed()["rows"][0]
        for k in ("item_id", "name", "delta_dps", "score_pct", "gold"):
            self.assertIn(k, row)

    def test_target_auto_resolved_and_echoed(self) -> None:
        h = _do(f"/api/ds-relscore?champion={_MARKSMAN}&mode=SR")
        target = h.parsed()["target"]
        self.assertEqual(target["mode"], "SR")
        # auto curve fills a positive resist for SR (no operator override).
        self.assertGreater(target["armor"], 0.0)
        self.assertGreater(target["mr"], 0.0)

    def test_level_clamped_and_echoed(self) -> None:
        h = _do(f"/api/ds-relscore?champion={_MARKSMAN}&level=99")
        self.assertEqual(h.parsed()["target"]["level"], 18)


class RelScoreMathTests(_Base):
    def _body(self) -> dict:
        h = _do(f"/api/ds-relscore?champion={_MARKSMAN}&mode=SR")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertTrue(body["rows"], "ranking was empty")
        return body

    def test_top_row_is_100_pct(self) -> None:
        rows = self._body()["rows"]
        self.assertEqual(rows[0]["score_pct"], 100.0)

    def test_score_pct_monotonic_non_increasing(self) -> None:
        # Rows arrive sorted desc by delta, so score_pct must never rise
        # going down the list.
        rows = self._body()["rows"]
        pcts = [r["score_pct"] for r in rows]
        for a, b in zip(pcts, pcts[1:]):
            self.assertGreaterEqual(
                a, b, f"score_pct rose down the rows: {a} then {b}")

    def test_score_pct_equals_delta_ratio(self) -> None:
        # Engine grounding via the COMPUTED quantity: each row's score_pct
        # is its own delta_dps as a percent of the top row's delta_dps.
        rows = self._body()["rows"]
        top = float(rows[0]["delta_dps"])
        self.assertGreater(top, 0.0, "top delta_dps was non-positive")
        for r in rows:
            expect = round(float(r["delta_dps"]) / top * 100.0, 1)
            # The route rounds delta_dps to 1dp before storing; recompute
            # from the stored delta so the comparison is exact-to-rounding.
            self.assertAlmostEqual(
                r["score_pct"], expect, delta=0.2,
                msg=f"{r['item_id']} score_pct {r['score_pct']} != {expect}")

    def test_all_score_pcts_in_range(self) -> None:
        for r in self._body()["rows"]:
            self.assertGreaterEqual(r["score_pct"], 0.0)
            self.assertLessEqual(r["score_pct"], 100.0)


class CacheTests(_Base):
    def test_cache_hit_sets_cached_flag(self) -> None:
        h1 = _do(f"/api/ds-relscore?champion={_MARKSMAN}")
        self.assertFalse(h1.parsed()["cached"])
        h2 = _do(f"/api/ds-relscore?champion={_MARKSMAN}")
        self.assertTrue(h2.parsed()["cached"])

    def test_level_part_of_cache_key(self) -> None:
        _do(f"/api/ds-relscore?champion={_MARKSMAN}&level=6")
        h = _do(f"/api/ds-relscore?champion={_MARKSMAN}&level=16")
        self.assertFalse(h.parsed()["cached"])

    def test_item_order_invariant_cache_key(self) -> None:
        _do(f"/api/ds-relscore?champion={_MARKSMAN}&items=3006,1055")
        h = _do(f"/api/ds-relscore?champion={_MARKSMAN}&items=1055,3006")
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

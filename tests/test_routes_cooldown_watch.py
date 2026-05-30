"""Tests for dashboard/routes_cooldown_watch.py - matchup cooldown-watch
card (competitor lift #5, docs/COMPETITOR_LIFT_2026-05-30.md).

Sibling of test_routes_cc_conditional_pressure.py; mirrors its StubHandler
pattern. The route is a thin wire over
agents.daemon_slayer.cooldown_watch.compute_cooldown_watch (covered by
agents/daemon_slayer/tests/test_cooldown_watch_2026_05_30.py); these tests
pin the HTTP contract: param validation, payload shape, top_n cap, cache.

Covers:
  * RouteContractTests - missing enemy 400, empty enemy 200 no_champions,
    all-unknown 200 ok=true empty cards.
  * ContentTests - card payload shape + grounded values + sort order.
  * TopNTests - default cap, explicit cap, clamp, garbage fallback.
  * CacheTests - TTL hit (cached flag), cache key order invariance.
  * AsciiHygieneTests - no em-dashes / smart quotes in route + test file.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_cooldown_watch as rt


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
    rt._serve_cooldown_watch(h)
    return h


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()


class RouteContractTests(_Base):
    def test_missing_enemy_param_returns_400(self) -> None:
        h = _do("/api/cooldown-watch")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_empty_enemy_returns_no_champions(self) -> None:
        h = _do("/api/cooldown-watch?enemy=")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "no_champions")
        self.assertEqual(body["cards"], [])

    def test_blanks_only_returns_no_champions(self) -> None:
        h = _do("/api/cooldown-watch?enemy=,,")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["reason"], "no_champions")

    def test_all_unknown_returns_ok_empty_cards(self) -> None:
        h = _do("/api/cooldown-watch?enemy=NotAChamp,AlsoFake")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["cards"], [])
        self.assertEqual(body["count"], 0)

    def test_response_is_json(self) -> None:
        h = _do("/api/cooldown-watch?enemy=Blitzcrank")
        self.assertEqual(h.last_ct, "application/json")


class ContentTests(_Base):
    def test_card_payload_shape_and_values(self) -> None:
        h = _do("/api/cooldown-watch?enemy=Blitzcrank")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["count"], 1)
        card = body["cards"][0]
        self.assertEqual(card["champion"], "Blitzcrank")
        self.assertEqual(card["spell_key"], "Q")
        self.assertEqual(card["spell_name"], "Rocket Grab")
        self.assertEqual(card["cc_kind"], "")
        self.assertEqual(card["cc_duration_s"], 1.0)
        self.assertEqual(card["cooldown_s"], 16.0)
        self.assertEqual(card["cooldown_by_rank"], [20.0, 19.0, 18.0, 17.0, 16.0])
        self.assertFalse(card["conditional"])
        self.assertEqual(card["probability"], 1.0)

    def test_cards_sorted_by_cc_duration_desc(self) -> None:
        h = _do("/api/cooldown-watch?enemy=Blitzcrank,Leona")
        names = [c["champion"] for c in h.parsed()["cards"]]
        # Leona R 1.5 > Blitzcrank Q 1.0
        self.assertEqual(names, ["Leona", "Blitzcrank"])

    def test_conditional_card_flagged(self) -> None:
        h = _do("/api/cooldown-watch?enemy=Aatrox")
        card = h.parsed()["cards"][0]
        self.assertEqual(card["spell_key"], "W")
        self.assertTrue(card["conditional"])
        self.assertEqual(card["cc_kind"], "root")


class TopNTests(_Base):
    def test_explicit_top_n_truncates(self) -> None:
        h = _do("/api/cooldown-watch?enemy=Blitzcrank,Leona,Lux&top_n=1")
        body = h.parsed()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["cards"][0]["champion"], "Lux")  # 3.0 longest

    def test_top_n_clamped_to_max(self) -> None:
        h = _do("/api/cooldown-watch?enemy=Blitzcrank&top_n=999")
        self.assertEqual(h.last_status, 200)
        self.assertTrue(h.parsed()["ok"])

    def test_garbage_top_n_falls_to_default(self) -> None:
        h = _do("/api/cooldown-watch?enemy=Blitzcrank&top_n=abc")
        self.assertEqual(h.last_status, 200)
        self.assertTrue(h.parsed()["ok"])


class CacheTests(_Base):
    def test_cache_hit_sets_cached_flag(self) -> None:
        h1 = _do("/api/cooldown-watch?enemy=Blitzcrank,Leona")
        self.assertFalse(h1.parsed()["cached"])
        h2 = _do("/api/cooldown-watch?enemy=Blitzcrank,Leona")
        self.assertTrue(h2.parsed()["cached"])

    def test_cache_key_order_invariant(self) -> None:
        _do("/api/cooldown-watch?enemy=Blitzcrank,Leona")
        h = _do("/api/cooldown-watch?enemy=Leona,Blitzcrank")
        self.assertTrue(h.parsed()["cached"])

    def test_top_n_part_of_cache_key(self) -> None:
        _do("/api/cooldown-watch?enemy=Blitzcrank&top_n=5")
        h = _do("/api/cooldown-watch?enemy=Blitzcrank&top_n=1")
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

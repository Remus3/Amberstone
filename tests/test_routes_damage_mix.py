"""Tests for /api/damage-mix - UX-2 damage-source donut backend.

Two layers:

  - Aggregator (``core.damage_mix.compute_damage_mix``): ratio sanity
    on hand-picked builds (Garen full-AD -> heavy physical;
    Lux full-AP -> heavy magical), sum-to-1.0, cache hit/miss
    lifecycle, invalid champ / item / level handling.

  - Route (``dashboard.routes_damage_mix._serve_damage_mix``): 200 happy
    path shape; 400s on missing/invalid champ_id, items, level, and the
    >6-items cap; cached flag correctness.

The DS snapshot is loaded once and shared - we rely on the live
``data/daemon_slayer/current.txt`` pointer (patch 16.10.1 at the time of
writing) instead of stubbing the snapshot. Live snapshot keeps the test
honest about real engine output - a snapshot bump that drifts the math
will fail loudly here, which is exactly the signal we want.
"""
from __future__ import annotations

import json
import unittest
from typing import Optional

from agents.daemon_slayer.data_loader import DataSnapshot
from core import damage_mix
from core.damage_mix import (
    CHANNELS,
    MAX_ITEMS,
    clear_cache,
    compute_damage_mix,
    normalize_items,
    resolve_champ_id,
)
from dashboard import routes_damage_mix


_SNAPSHOT: Optional[DataSnapshot] = None


def _snap() -> DataSnapshot:
    global _SNAPSHOT
    if _SNAPSHOT is None:
        _SNAPSHOT = DataSnapshot.load()
    return _SNAPSHOT


# ---------------------------------------------------------------------
# Stub request handler (mirrors test_routes_watcher_manifest.StubHandler)
# ---------------------------------------------------------------------

class StubHandler:
    def __init__(self, path: str = ""):
        self.path = path
        self.last_status: Optional[int] = None
        self.last_body: Optional[bytes] = None
        self.last_ct: Optional[str] = None

    def _send(self, status, body, content_type):
        self.last_status = status
        self.last_body = body
        self.last_ct = content_type

    def parsed(self) -> dict:
        return json.loads(self.last_body.decode("utf-8")) if self.last_body else {}


# ---------------------------------------------------------------------
# Aggregator tests
# ---------------------------------------------------------------------

class AggregatorTests(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def test_ratios_sum_to_one_garen_full_ad(self):
        # Garen (id 86): Stridebreaker + Black Cleaver + Plated Steelcaps.
        # Pure AD build - expect dominant physical, no on-hit (no
        # per-attack proc items), tiny true sliver from R.
        mix, was_cached = compute_damage_mix(
            _snap(), 86, ["3074", "3071", "3047"], level=11,
        )
        self.assertFalse(was_cached)
        total_ratio = sum(mix.mix.values())
        self.assertAlmostEqual(total_ratio, 1.0, delta=1e-9)
        # Physical should be the dominant channel (>0.9 with this build).
        self.assertGreater(mix.mix["physical"], 0.9)
        self.assertEqual(mix.mix["magical"], 0.0)

    def test_ratios_sum_to_one_lux_full_ap(self):
        # Lux (id 99): Liandry's + Rabadon's + Sorcerer's Shoes - pure AP.
        # Expect magical dominant; physical comes only from AA which is
        # small for Lux (low AS, low AD).
        mix, _ = compute_damage_mix(
            _snap(), 99, ["3157", "3089", "3020"], level=11,
        )
        self.assertAlmostEqual(sum(mix.mix.values()), 1.0, delta=1e-9)
        self.assertGreater(mix.mix["magical"], 0.5)
        self.assertGreater(mix.mix["physical"], 0.0)  # AA still contributes

    def test_total_dps_positive_for_real_build(self):
        mix, _ = compute_damage_mix(
            _snap(), 86, ["3074", "3071"], level=11,
        )
        self.assertGreater(mix.total_dps, 0.0)

    def test_string_champ_id_also_accepted(self):
        # The route docstring promises numeric key OR string id; verify
        # both produce equivalent output.
        m_num, _ = compute_damage_mix(_snap(), 86, ["3074"], level=11)
        clear_cache()
        m_str, _ = compute_damage_mix(_snap(), "Garen", ["3074"], level=11)
        self.assertEqual(m_num.champ_id, m_str.champ_id)
        self.assertAlmostEqual(m_num.total_dps, m_str.total_dps, places=6)

    def test_unknown_champ_key_raises(self):
        with self.assertRaises(ValueError):
            compute_damage_mix(_snap(), 99999, ["3074"], level=11)

    def test_unknown_champ_str_raises(self):
        with self.assertRaises(ValueError):
            compute_damage_mix(_snap(), "NotAChamp", ["3074"], level=11)

    def test_unknown_item_raises(self):
        with self.assertRaises(ValueError):
            compute_damage_mix(_snap(), 86, ["99999999"], level=11)

    def test_too_many_items_raises(self):
        # 7 items - over the 6-cap
        items = ["3074", "3071", "3047", "3053", "3065", "3110", "3068"]
        with self.assertRaises(ValueError):
            compute_damage_mix(_snap(), 86, items, level=11)

    def test_level_clamp(self):
        # below 1
        with self.assertRaises(ValueError):
            compute_damage_mix(_snap(), 86, ["3074"], level=0)
        # above 18
        with self.assertRaises(ValueError):
            compute_damage_mix(_snap(), 86, ["3074"], level=19)

    def test_cache_hit_returns_was_cached_true_on_second_call(self):
        # First call: miss.
        m1, c1 = compute_damage_mix(_snap(), 86, ["3074"], level=11)
        self.assertFalse(c1)
        # Second call same key: hit.
        m2, c2 = compute_damage_mix(_snap(), 86, ["3074"], level=11)
        self.assertTrue(c2)
        # Result identity is preserved across hits.
        self.assertEqual(m1.total_dps, m2.total_dps)

    def test_cache_isolated_per_level(self):
        compute_damage_mix(_snap(), 86, ["3074"], level=6)
        # Different level - should be a miss.
        _, cached = compute_damage_mix(_snap(), 86, ["3074"], level=11)
        self.assertFalse(cached)

    def test_use_cache_false_skips_cache(self):
        compute_damage_mix(_snap(), 86, ["3074"], level=11)
        # use_cache=False ignores the populated entry and recomputes.
        _, cached = compute_damage_mix(
            _snap(), 86, ["3074"], level=11, use_cache=False,
        )
        self.assertFalse(cached)

    def test_resolve_champ_id_numeric_and_string(self):
        snap = _snap()
        self.assertEqual(resolve_champ_id(snap, 86), "Garen")
        self.assertEqual(resolve_champ_id(snap, "86"), "Garen")
        self.assertEqual(resolve_champ_id(snap, "Garen"), "Garen")

    def test_resolve_champ_id_empty_raises(self):
        with self.assertRaises(ValueError):
            resolve_champ_id(_snap(), "")
        with self.assertRaises(ValueError):
            resolve_champ_id(_snap(), "   ")

    def test_normalize_items_strips_blank(self):
        # blanks tolerated; final list has 3 items
        items = normalize_items(_snap(), ["3074", "", "3071", "3047"])
        self.assertEqual(items, ("3074", "3071", "3047"))

    def test_normalize_items_max_cap(self):
        # exactly 6 is fine, 7 raises
        self.assertEqual(
            len(normalize_items(_snap(),
                ["3074", "3071", "3047", "3053", "3065", "3110"])),
            6,
        )
        with self.assertRaises(ValueError):
            normalize_items(_snap(),
                ["3074", "3071", "3047", "3053", "3065", "3110", "3068"])

    def test_channels_constant(self):
        # If this list ever drifts, the JS donut wiring breaks - keep
        # the contract pinned via a test.
        self.assertEqual(
            CHANNELS,
            ("physical", "magical", "true", "on_hit"),
        )

    def test_max_items_is_six(self):
        self.assertEqual(MAX_ITEMS, 6)


# ---------------------------------------------------------------------
# Route handler tests
# ---------------------------------------------------------------------

class RouteTests(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def test_happy_path_garen(self):
        h = StubHandler("/api/damage-mix?champ_id=86&items=3074,3071,3047&level=11")
        routes_damage_mix._serve_damage_mix(h)
        self.assertEqual(h.last_status, 200)
        self.assertIn("application/json", h.last_ct)
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["champ_id"], "Garen")
        self.assertEqual(body["champ_key"], 86)
        self.assertEqual(body["items"], ["3074", "3071", "3047"])
        self.assertEqual(body["level"], 11)
        self.assertIn("mix", body)
        self.assertIn("physical", body["mix"])
        self.assertIn("magical", body["mix"])
        self.assertIn("true", body["mix"])
        self.assertIn("on_hit", body["mix"])
        self.assertEqual(body["cached"], False)
        self.assertEqual(body["cache_key"], "Garen:3074,3071,3047")

    def test_cached_flag_flips_on_repeat(self):
        h1 = StubHandler("/api/damage-mix?champ_id=86&items=3074&level=11")
        routes_damage_mix._serve_damage_mix(h1)
        self.assertEqual(h1.parsed()["cached"], False)
        h2 = StubHandler("/api/damage-mix?champ_id=86&items=3074&level=11")
        routes_damage_mix._serve_damage_mix(h2)
        self.assertEqual(h2.parsed()["cached"], True)

    def test_missing_champ_id_returns_400(self):
        h = StubHandler("/api/damage-mix?items=3074")
        routes_damage_mix._serve_damage_mix(h)
        self.assertEqual(h.last_status, 400)
        self.assertEqual(h.parsed()["error"], "champ_id_required")

    def test_empty_champ_id_returns_400(self):
        h = StubHandler("/api/damage-mix?champ_id=&items=3074")
        routes_damage_mix._serve_damage_mix(h)
        self.assertEqual(h.last_status, 400)

    def test_unknown_champ_returns_400(self):
        h = StubHandler("/api/damage-mix?champ_id=99999&items=3074")
        routes_damage_mix._serve_damage_mix(h)
        self.assertEqual(h.last_status, 400)
        self.assertIn("unknown champ", h.parsed()["error"])

    def test_missing_items_returns_400_items_required(self):
        h = StubHandler("/api/damage-mix?champ_id=86")
        routes_damage_mix._serve_damage_mix(h)
        self.assertEqual(h.last_status, 400)
        self.assertEqual(h.parsed()["error"], "items_required")

    def test_empty_items_returns_400_items_required(self):
        h = StubHandler("/api/damage-mix?champ_id=86&items=")
        routes_damage_mix._serve_damage_mix(h)
        self.assertEqual(h.last_status, 400)
        self.assertEqual(h.parsed()["error"], "items_required")

    def test_commas_only_items_returns_400(self):
        h = StubHandler("/api/damage-mix?champ_id=86&items=,,,")
        routes_damage_mix._serve_damage_mix(h)
        self.assertEqual(h.last_status, 400)
        self.assertEqual(h.parsed()["error"], "items_required")

    def test_invalid_item_id_returns_400(self):
        h = StubHandler("/api/damage-mix?champ_id=86&items=99999999")
        routes_damage_mix._serve_damage_mix(h)
        self.assertEqual(h.last_status, 400)
        self.assertIn("unknown item", h.parsed()["error"])

    def test_too_many_items_returns_400(self):
        items = ",".join(["3074", "3071", "3047", "3053", "3065", "3110", "3068"])
        h = StubHandler(f"/api/damage-mix?champ_id=86&items={items}")
        routes_damage_mix._serve_damage_mix(h)
        self.assertEqual(h.last_status, 400)
        self.assertIn("too many items", h.parsed()["error"])

    def test_level_out_of_range_returns_400(self):
        h = StubHandler("/api/damage-mix?champ_id=86&items=3074&level=99")
        routes_damage_mix._serve_damage_mix(h)
        self.assertEqual(h.last_status, 400)
        self.assertIn("level_out_of_range", h.parsed()["error"])

    def test_level_non_numeric_returns_400(self):
        h = StubHandler("/api/damage-mix?champ_id=86&items=3074&level=abc")
        routes_damage_mix._serve_damage_mix(h)
        self.assertEqual(h.last_status, 400)
        self.assertIn("level_invalid", h.parsed()["error"])

    def test_default_level_is_11(self):
        h = StubHandler("/api/damage-mix?champ_id=86&items=3074")
        routes_damage_mix._serve_damage_mix(h)
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["level"], 11)

    def test_mode_param_accepted(self):
        h = StubHandler("/api/damage-mix?champ_id=86&items=3074&mode=ARAM")
        routes_damage_mix._serve_damage_mix(h)
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["mode"], "ARAM")

    def test_response_ratios_sum_to_one(self):
        h = StubHandler("/api/damage-mix?champ_id=99&items=3157,3089,3020")
        routes_damage_mix._serve_damage_mix(h)
        body = h.parsed()
        s = sum(body["mix"].values())
        self.assertAlmostEqual(s, 1.0, delta=1e-9)

    def test_route_registered_in_dispatch(self):
        # Wiring sanity: the route must appear in the GET cache after
        # the dispatcher gathers everything.
        from dashboard import _dispatch
        _dispatch._GET_CACHE = None  # force re-gather
        routes_list = _dispatch._gather_get()
        # Each entry is (matcher, fn) - look for one whose matcher
        # accepts "/api/damage-mix".
        matched = any(matcher("/api/damage-mix") for matcher, _ in routes_list)
        self.assertTrue(
            matched,
            "/api/damage-mix is not registered in dispatch GET routes",
        )


if __name__ == "__main__":
    unittest.main()

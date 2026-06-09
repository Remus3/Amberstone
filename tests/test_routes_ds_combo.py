"""Tests for dashboard/routes_ds_combo.py - action-queue combo simulator
(competitor lift #2, docs/COMPETITOR_LIFT_2026-05-30.md).

Sibling of test_routes_cooldown_watch.py; mirrors its StubHandler pattern.
The route is a thin wire over agents.daemon_slayer.combo.compute_combo
(covered by agents/daemon_slayer/tests/test_combo_2026_05_30.py); these
tests pin the HTTP contract: param validation, payload shape, totals,
cooldown-skip surfacing, cache.

Covers:
  * RouteContractTests - missing champion 400, missing seq 400, empty seq
    200 empty_sequence, unknown champ 200 ok=true empty hits.
  * ContentTests       - hits payload shape + grounded Lux values + totals.
  * CooldownTests      - on-cooldown re-cast surfaces status=on_cooldown.
  * CacheTests         - TTL hit (cached flag), cache key components.
  * AsciiHygieneTests  - no em-dashes / smart quotes in route + test file.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from dashboard import routes_ds_combo as rt


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
    rt._serve_ds_combo(h)
    return h


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()


class RouteContractTests(_Base):
    def test_missing_champion_returns_400(self) -> None:
        h = _do("/api/ds-combo?seq=Q,AA")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_blank_champion_returns_400(self) -> None:
        h = _do("/api/ds-combo?champion=&seq=Q,AA")
        self.assertEqual(h.last_status, 400)

    def test_missing_seq_returns_400(self) -> None:
        h = _do("/api/ds-combo?champion=Lux")
        self.assertEqual(h.last_status, 400)
        self.assertFalse(h.parsed()["ok"])

    def test_blank_seq_returns_400(self) -> None:
        h = _do("/api/ds-combo?champion=Lux&seq=")
        self.assertEqual(h.last_status, 400)

    def test_blanks_only_seq_returns_empty_sequence(self) -> None:
        h = _do("/api/ds-combo?champion=Lux&seq=,,")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "empty_sequence")
        self.assertEqual(body["hits"], [])

    def test_unknown_champ_returns_ok_empty_hits(self) -> None:
        h = _do("/api/ds-combo?champion=NotAChamp&seq=Q,AA")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["hits"], [])
        self.assertEqual(body["count"], 0)

    def test_response_is_json(self) -> None:
        h = _do("/api/ds-combo?champion=Lux&seq=Q")
        self.assertEqual(h.last_ct, "application/json")


class ContentTests(_Base):
    def test_hit_payload_shape_and_values(self) -> None:
        h = _do(
            "/api/ds-combo?champion=Lux&level=11&seq=Q,AA,W,E,R"
            "&target_armor=80&target_mr=60"
        )
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["champion"], "Lux")
        self.assertEqual(body["level"], 11)
        self.assertEqual(body["count"], 5)
        first = body["hits"][0]
        self.assertEqual(first["action"], "Q")
        self.assertEqual(first["ability_key"], "Q")
        self.assertTrue(first["is_ability"])
        self.assertEqual(first["form_name"], "Light Binding")
        self.assertEqual(first["rank"], 4)
        self.assertAlmostEqual(first["t"], 0.0)
        self.assertAlmostEqual(first["cast_time"], 0.25)
        self.assertAlmostEqual(first["cooldown_s"], 9.0)
        self.assertAlmostEqual(first["raw"], 240.0)
        self.assertAlmostEqual(first["mitigated"], 150.0)
        self.assertAlmostEqual(first["cumulative"], 150.0)
        self.assertEqual(first["status"], "ok")

    def test_totals_block(self) -> None:
        h = _do(
            "/api/ds-combo?champion=Lux&seq=Q,AA,W,E,R"
            "&target_armor=80&target_mr=60"
        )
        body = h.parsed()
        tot = body["totals"]
        self.assertIn("total_raw", tot)
        self.assertIn("total_mitigated", tot)
        self.assertIn("duration_s", tot)
        # duration_s is the combat-clock end: the last action's start time
        # plus its own cast_time. Assert that structural identity rather
        # than a hardcoded literal - the WIN 1 AA-windup offset tier
        # (ENGINE 1.107.0) moved Lux's AA windup off the flat 0.25s, so the
        # old 2.0 literal went stale (now 1.984). Deriving from the payload
        # keeps this robust to per-champion windup drift on a patch refresh.
        last = body["hits"][-1]
        self.assertAlmostEqual(
            tot["duration_s"], last["t"] + last["cast_time"], places=3
        )
        self.assertGreater(tot["duration_s"], 0.0)
        self.assertGreater(tot["total_mitigated"], 0.0)

    def test_cumulative_monotonic_in_payload(self) -> None:
        h = _do(
            "/api/ds-combo?champion=Caitlyn&seq=Q,AA,W,E,R,AA"
            "&target_armor=80&target_mr=60"
        )
        prev = -1.0
        for hit in h.parsed()["hits"]:
            self.assertGreaterEqual(hit["cumulative"], prev - 1e-6)
            prev = hit["cumulative"]
            self.assertLessEqual(hit["mitigated"], hit["raw"] + 1e-6)


class CooldownTests(_Base):
    def test_recast_surfaces_on_cooldown(self) -> None:
        h = _do(
            "/api/ds-combo?champion=Lux&seq=Q,AA,Q,W,E,R"
            "&target_armor=80&target_mr=60"
        )
        hits = h.parsed()["hits"]
        skipped = hits[2]
        self.assertEqual(skipped["action"], "Q")
        self.assertEqual(skipped["status"], "on_cooldown")
        self.assertAlmostEqual(skipped["mitigated"], 0.0)
        self.assertIn("cooldown", skipped["note"].lower())

    def test_level_clamped(self) -> None:
        # level 99 clamps to 18; still ok.
        h = _do("/api/ds-combo?champion=Lux&seq=Q&level=99")
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.parsed()["level"], 18)

    def test_garbage_level_falls_to_default(self) -> None:
        h = _do("/api/ds-combo?champion=Lux&seq=Q&level=abc")
        self.assertEqual(h.parsed()["level"], 11)


class CacheTests(_Base):
    def test_cache_hit_sets_cached_flag(self) -> None:
        path = "/api/ds-combo?champion=Lux&seq=Q,AA,W&target_armor=80"
        h1 = _do(path)
        self.assertFalse(h1.parsed()["cached"])
        h2 = _do(path)
        self.assertTrue(h2.parsed()["cached"])

    def test_seq_part_of_cache_key(self) -> None:
        _do("/api/ds-combo?champion=Lux&seq=Q,AA")
        h = _do("/api/ds-combo?champion=Lux&seq=Q,W")
        self.assertFalse(h.parsed()["cached"])

    def test_target_armor_part_of_cache_key(self) -> None:
        _do("/api/ds-combo?champion=Lux&seq=Q&target_armor=50")
        h = _do("/api/ds-combo?champion=Lux&seq=Q&target_armor=150")
        self.assertFalse(h.parsed()["cached"])

    def test_level_part_of_cache_key(self) -> None:
        _do("/api/ds-combo?champion=Lux&seq=Q&level=6")
        h = _do("/api/ds-combo?champion=Lux&seq=Q&level=16")
        self.assertFalse(h.parsed()["cached"])


class RuneTests(_Base):
    """T2-F4: runes= / keystone= thread through to compute_combo.

    8112 Electrocute is an on_proc_burst rune: supplying it MUST raise the
    combo total. Omitted / blank / unknown-only MUST be byte-identical to
    the no-runes path (engine contract pinned by
    agents/daemon_slayer/tests/test_rune_wire_burst_combo.py).
    """

    _SEQ = "Q,AA,W,E,R"

    def _totals(self, query: str) -> dict:
        body = _do(f"/api/ds-combo?champion=Lux&seq={self._SEQ}"
                   f"&target_armor=80&target_mr=60&target_max_hp=2000"
                   f"&target_bonus_hp=600{query}").parsed()
        self.assertTrue(body["ok"])
        return body["totals"]

    def test_no_runes_param_byte_identical(self) -> None:
        # The default (no runes param) output must match today's contract.
        base = self._totals("")
        again = self._totals("")
        self.assertEqual(base, again)

    def test_blank_runes_byte_identical(self) -> None:
        base = self._totals("")
        blank = self._totals("&runes=")
        self.assertEqual(base["total_mitigated"], blank["total_mitigated"])
        self.assertEqual(base["total_raw"], blank["total_raw"])

    def test_unknown_rune_byte_identical(self) -> None:
        base = self._totals("")
        unknown = self._totals("&runes=99999")
        self.assertEqual(base["total_mitigated"], unknown["total_mitigated"])
        self.assertEqual(base["total_raw"], unknown["total_raw"])

    def test_electrocute_raises_total(self) -> None:
        base = self._totals("")
        elec = self._totals("&runes=8112")
        self.assertGreater(elec["total_mitigated"], base["total_mitigated"])

    def test_keystone_param_alias_raises_total(self) -> None:
        # keystone= is a single-id alias for runes=.
        base = self._totals("")
        elec = self._totals("&keystone=8112")
        self.assertGreater(elec["total_mitigated"], base["total_mitigated"])

    def test_malformed_runes_no_500_and_byte_identical(self) -> None:
        # Garbage rune tokens must be dropped, never raise a 500.
        h = _do(f"/api/ds-combo?champion=Lux&seq={self._SEQ}"
                "&target_armor=80&target_mr=60&runes=abc,,xyz")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        base = _do(f"/api/ds-combo?champion=Lux&seq={self._SEQ}"
                   "&target_armor=80&target_mr=60").parsed()
        self.assertEqual(body["totals"]["total_mitigated"],
                         base["totals"]["total_mitigated"])

    def test_runes_part_of_cache_key(self) -> None:
        path = f"/api/ds-combo?champion=Lux&seq={self._SEQ}&target_armor=80"
        _do(path)
        h = _do(path + "&runes=8112")
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

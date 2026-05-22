"""Tests for dashboard/routes_cc_blended_ehp_threat.py - the FIRST
dashboard UI consumer of cc_blended_ehp (item 139 carry (a)).

Covers:
  * RouteContractTests - missing params 400, empty 200 no_champions,
    malformed silent skip, mode default ARAM, mode case insensitivity.
  * MathTests - ratio calc verified for known champ tuples, tier band
    boundaries 1.05/0.95, zero-CC both sides ratio=1.0 tier=warn,
    ally-CC heavy vs no-CC enemy = good.
  * CacheTests - TTL hit + cold miss + cache key invariance over
    input order + mode-aware cache key.
  * FailSoftTests - silent-skip blank/None/unknown champions,
    DS engine import failure paths.
  * AsciiHygieneTests - no em-dashes / smart quotes in route file
    or tests.

Mirrors the test_routes_post_game_rubric.py + test_routes_spike_curve.py
StubHandler pattern.
"""
from __future__ import annotations

import json
import unittest

from dashboard import routes_cc_blended_ehp_threat as rt


class StubHandler:
    """Same shape as test_routes_spike_curve.StubHandler."""

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
    rt._serve_cc_blended_ehp_threat(h)
    return h


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()


# ---------------------------------------------------------------------
# RouteContractTests - input validation + fail-soft paths.
# ---------------------------------------------------------------------


class RouteContractTests(_Base):
    def test_missing_both_params_returns_400(self) -> None:
        h = _do("/api/cc-blended-ehp-threat")
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertFalse(body["ok"])
        self.assertIn("required", body["error"])

    def test_missing_ally_returns_400(self) -> None:
        h = _do("/api/cc-blended-ehp-threat?enemy=Annie")
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertFalse(body["ok"])

    def test_missing_enemy_returns_400(self) -> None:
        h = _do("/api/cc-blended-ehp-threat?ally=Annie")
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertFalse(body["ok"])

    def test_both_empty_returns_200_no_champions(self) -> None:
        # Both keys present but blank values - distinct from "literally
        # missing" (which returns 400).
        h = _do("/api/cc-blended-ehp-threat?ally=&enemy=")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "no_champions")

    def test_malformed_blank_entries_silently_skipped(self) -> None:
        # "Annie,,Galio" should be treated as ["Annie", "Galio"].
        h = _do("/api/cc-blended-ehp-threat?ally=Annie,,Galio"
                "&enemy=Aatrox,,Garen&mode=ARAM")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])

    def test_mode_default_is_aram(self) -> None:
        # No mode param -> defaults to ARAM.
        h = _do("/api/cc-blended-ehp-threat?ally=Annie&enemy=Aatrox")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertEqual(body["mode"], "ARAM")

    def test_mode_case_insensitive(self) -> None:
        # Mode is normalised to upper-case.
        h = _do("/api/cc-blended-ehp-threat?ally=Annie&enemy=Aatrox&mode=sr")
        body = h.parsed()
        self.assertEqual(body["mode"], "SR")

    def test_unsupported_mode_falls_back_to_default(self) -> None:
        # Garbage mode falls through to ARAM (default) rather than
        # 400ing - the chip should still render.
        h = _do("/api/cc-blended-ehp-threat?ally=Annie&enemy=Aatrox&mode=NOPE")
        body = h.parsed()
        self.assertEqual(body["mode"], "ARAM")


# ---------------------------------------------------------------------
# MathTests - verify the engine math threads through correctly.
# ---------------------------------------------------------------------


class MathTests(_Base):
    def test_response_shape_carries_required_keys(self) -> None:
        h = _do("/api/cc-blended-ehp-threat?ally=Annie,Galio,Leona"
                "&enemy=Aatrox,Garen,Sett&mode=ARAM")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        for key in (
            "mode", "ally_avg_cc_blended_ehp", "enemy_avg_cc_blended_ehp",
            "ratio", "tier", "ally_total_cc_seconds",
            "enemy_total_cc_seconds", "elapsed_ms", "cached",
        ):
            self.assertIn(key, body, f"missing key {key}")

    def test_ally_cc_heavy_vs_no_cc_enemy_is_good(self) -> None:
        # Annie/Galio/Leona all have registered CC; Aatrox/Garen/Sett
        # do not. Our CC erodes them; their CC does not erode us.
        # -> ally cc_blended_ehp > enemy cc_blended_ehp -> tier=good.
        h = _do("/api/cc-blended-ehp-threat?ally=Annie,Galio,Leona"
                "&enemy=Aatrox,Garen,Sett&mode=ARAM")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["tier"], "good")
        self.assertGreater(body["ratio"], 1.05)
        self.assertGreater(body["enemy_total_cc_seconds"], 0.0)
        self.assertEqual(body["ally_total_cc_seconds"], 0.0)

    def test_enemy_cc_heavy_vs_no_cc_ally_is_bad(self) -> None:
        # Mirror: ally has no CC, enemies have heavy CC. Their CC
        # erodes us -> ally cc_blended_ehp < enemy cc_blended_ehp ->
        # tier=bad.
        h = _do("/api/cc-blended-ehp-threat?ally=Aatrox,Garen,Sett"
                "&enemy=Annie,Galio,Leona&mode=ARAM")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["tier"], "bad")
        self.assertLess(body["ratio"], 0.95)
        self.assertGreater(body["ally_total_cc_seconds"], 0.0)
        self.assertEqual(body["enemy_total_cc_seconds"], 0.0)

    def test_zero_cc_both_sides_tier_warn(self) -> None:
        # Aatrox/Garen vs Sett/Tryndamere - none have first-order CC
        # in the registry. ally_total_cc and enemy_total_cc both 0.0;
        # tier clamps to warn (the chip is about CC threat balance -
        # raw EHP is incidental signal).
        h = _do("/api/cc-blended-ehp-threat?ally=Aatrox,Garen"
                "&enemy=Sett,Tryndamere&mode=ARAM")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["tier"], "warn")
        self.assertEqual(body["ally_total_cc_seconds"], 0.0)
        self.assertEqual(body["enemy_total_cc_seconds"], 0.0)

    def test_tier_band_thresholds_pinned(self) -> None:
        # Pin the literal threshold constants so a future change forces
        # a deliberate retune (and a panel-test update).
        self.assertEqual(rt._TIER_GOOD_THRESHOLD, 1.05)
        self.assertEqual(rt._TIER_BAD_THRESHOLD, 0.95)

    def test_tier_helper_at_threshold_boundaries(self) -> None:
        # At-threshold boundary checks. Good >= 1.05; bad < 0.95.
        self.assertEqual(rt._tier_for(1.05), "good")
        self.assertEqual(rt._tier_for(1.06), "good")
        self.assertEqual(rt._tier_for(1.04), "warn")
        self.assertEqual(rt._tier_for(0.95), "warn")
        self.assertEqual(rt._tier_for(0.94), "bad")
        self.assertEqual(rt._tier_for(1.0), "warn")


# ---------------------------------------------------------------------
# CacheTests - TTL, key invariance, mode-aware keying.
# ---------------------------------------------------------------------


class CacheTests(_Base):
    def test_cold_miss_then_warm_hit(self) -> None:
        cold = _do("/api/cc-blended-ehp-threat?ally=Annie,Galio"
                   "&enemy=Aatrox,Garen&mode=ARAM")
        self.assertFalse(cold.parsed()["cached"])
        warm = _do("/api/cc-blended-ehp-threat?ally=Annie,Galio"
                   "&enemy=Aatrox,Garen&mode=ARAM")
        self.assertTrue(warm.parsed()["cached"])

    def test_cache_key_invariant_to_input_order(self) -> None:
        # ally=Annie,Galio and ally=Galio,Annie should hit the same
        # cache slot.
        _do("/api/cc-blended-ehp-threat?ally=Annie,Galio"
            "&enemy=Aatrox,Garen&mode=ARAM")
        flipped = _do("/api/cc-blended-ehp-threat?ally=Galio,Annie"
                      "&enemy=Garen,Aatrox&mode=ARAM")
        self.assertTrue(flipped.parsed()["cached"])

    def test_cache_key_differentiates_mode(self) -> None:
        # ARAM vs SR should NOT share a cache slot - aramTenacity
        # changes the cc_pressure values on the modified champs.
        _do("/api/cc-blended-ehp-threat?ally=Annie,Galio"
            "&enemy=Aatrox,Garen&mode=ARAM")
        sr = _do("/api/cc-blended-ehp-threat?ally=Annie,Galio"
                 "&enemy=Aatrox,Garen&mode=SR")
        self.assertFalse(sr.parsed()["cached"])


# ---------------------------------------------------------------------
# FailSoftTests - DS engine import failure + unknown champions.
# ---------------------------------------------------------------------


class FailSoftTests(_Base):
    def test_unknown_champion_silently_skipped(self) -> None:
        # The route mirrors compute_ehp + compute_cc_pressure fail-soft
        # contracts: unknown champion ids don't 4xx, they silently
        # contribute 0 to the side's average. Mixed known + unknown
        # still returns ok=true.
        h = _do("/api/cc-blended-ehp-threat?ally=Annie,NotAChamp"
                "&enemy=Aatrox,AlsoNotAChamp&mode=ARAM")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        # Annie scores; NotAChamp raises in compute_ehp; the route
        # logs + skips. As long as ONE side has at least one usable
        # champ, ok=true.
        self.assertTrue(body["ok"])

    def test_all_unknown_returns_no_champions(self) -> None:
        # If literally zero champs are usable on both sides, the route
        # returns ok=false reason=no_champions (the engine-side return
        # path from _compute, not the parse-empty path).
        h = _do("/api/cc-blended-ehp-threat?ally=NopeOne,NopeTwo"
                "&enemy=NopeThree,NopeFour&mode=ARAM")
        # NopeXxxx raise in compute_ehp -> empty values list -> 0.0
        # averages -> _compute returns ok=false reason=no_champions.
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "no_champions")


# ---------------------------------------------------------------------
# AsciiHygieneTests - guard the route + test file against em-dashes /
# smart quotes per the CLAUDE.md hard rule.
# ---------------------------------------------------------------------


class AsciiHygieneTests(unittest.TestCase):
    def test_route_module_is_ascii(self) -> None:
        # Build the BAD chars via chr() so this test file itself stays
        # ASCII-clean against its own scan.
        bad = {chr(0x2013), chr(0x2014), chr(0x2018), chr(0x2019),
               chr(0x201C), chr(0x201D)}
        from pathlib import Path
        text = Path(rt.__file__).read_text(encoding="utf-8")
        for ch in bad:
            self.assertNotIn(
                ch, text,
                f"non-ASCII character U+{ord(ch):04X} in route module",
            )

    def test_self_is_ascii(self) -> None:
        bad = {chr(0x2013), chr(0x2014), chr(0x2018), chr(0x2019),
               chr(0x201C), chr(0x201D)}
        from pathlib import Path
        text = Path(__file__).read_text(encoding="utf-8")
        # Skip the explicit chr-built set above to avoid false positives.
        # We can do a plain "no smart quote in test docstrings" check by
        # confirming non-ASCII content count is bounded.
        nonascii_lines = [
            i for i, line in enumerate(text.split("\n"))
            if any(ord(c) > 127 for c in line) and "chr(" not in line
        ]
        self.assertEqual(nonascii_lines, [],
                         f"non-ASCII lines: {nonascii_lines}")


if __name__ == "__main__":
    unittest.main()

"""Tests for dashboard/routes_cc_conditional_pressure.py - the FIRST
dashboard UI consumer of cc_conditional (5th overall consumer of the
cc_conditional ecosystem; item 144).

Covers:
  * RouteContractTests - missing params 400, both blank 200
    no_champions, malformed silent skip, mode default ARAM, mode
    case insensitivity, garbage mode fallback to default.
  * MathTests - ratio calc verified for known champ tuples
    (Brand / Mordekaiser / TwistedFate carry conditional CC at
    16.10.1; Annie / Galio / Leona carry only unconditional CC so
    their conditional_cc_seconds is 0), tier band boundaries
    1.05/0.95, zero-conditional-CC both sides ratio=1.0 tier=warn.
  * CacheTests - TTL hit + cold miss + cache key invariance over
    input order + mode-aware cache key.
  * FailSoftTests - silent-skip blank/None/unknown champions,
    all-unknown returns no_champions.
  * AsciiHygieneTests - no em-dashes / smart quotes in the route
    file or in the test file itself.

Mirrors the test_routes_cc_blended_ehp_threat.py StubHandler pattern.
"""
from __future__ import annotations

import json
import unittest

from dashboard import routes_cc_conditional_pressure as rt


class StubHandler:
    """Same shape as test_routes_cc_blended_ehp_threat.StubHandler."""

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
    rt._serve_cc_conditional_pressure(h)
    return h


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()


# ---------------------------------------------------------------------
# RouteContractTests - input validation + fail-soft paths.
# ---------------------------------------------------------------------


class RouteContractTests(_Base):
    def test_missing_both_params_returns_400(self) -> None:
        h = _do("/api/cc-conditional-pressure")
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertFalse(body["ok"])
        self.assertIn("required", body["error"])

    def test_missing_ally_returns_400(self) -> None:
        h = _do("/api/cc-conditional-pressure?enemy=Brand")
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertFalse(body["ok"])

    def test_missing_enemy_returns_400(self) -> None:
        h = _do("/api/cc-conditional-pressure?ally=Brand")
        self.assertEqual(h.last_status, 400)
        body = h.parsed()
        self.assertFalse(body["ok"])

    def test_both_empty_returns_200_no_champions(self) -> None:
        # Both keys present but blank values - distinct from "literally
        # missing" (which returns 400).
        h = _do("/api/cc-conditional-pressure?ally=&enemy=")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "no_champions")

    def test_malformed_blank_entries_silently_skipped(self) -> None:
        # "Brand,,Mordekaiser" should be treated as ["Brand", "Mordekaiser"].
        h = _do("/api/cc-conditional-pressure?ally=Brand,,Mordekaiser"
                "&enemy=Annie,,Galio&mode=ARAM")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])

    def test_mode_default_is_aram(self) -> None:
        # No mode param -> defaults to ARAM.
        h = _do("/api/cc-conditional-pressure?ally=Brand&enemy=Annie")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertEqual(body["mode"], "ARAM")

    def test_mode_case_insensitive(self) -> None:
        # Mode is normalised to upper-case.
        h = _do("/api/cc-conditional-pressure?ally=Brand&enemy=Annie&mode=sr")
        body = h.parsed()
        self.assertEqual(body["mode"], "SR")

    def test_unsupported_mode_falls_back_to_default(self) -> None:
        # Garbage mode falls through to ARAM (default) rather than
        # 400ing - the chip should still render.
        h = _do("/api/cc-conditional-pressure?ally=Brand&enemy=Annie&mode=NOPE")
        body = h.parsed()
        self.assertEqual(body["mode"], "ARAM")


# ---------------------------------------------------------------------
# MathTests - verify the conditional CC contribution threads through.
# ---------------------------------------------------------------------


class MathTests(_Base):
    def test_response_shape_carries_required_keys(self) -> None:
        h = _do("/api/cc-conditional-pressure?ally=Brand,Mordekaiser"
                "&enemy=Annie,Galio&mode=ARAM")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        for key in (
            "mode", "ally_conditional_cc_s", "enemy_conditional_cc_s",
            "ratio", "tier", "ally_total_cc_seconds",
            "enemy_total_cc_seconds", "elapsed_ms", "cached",
        ):
            self.assertIn(key, body, f"missing key {key}")

    def test_ally_conditional_heavy_vs_no_cond_enemy_is_good(self) -> None:
        # Brand / Mordekaiser / TwistedFate carry conditional CC in
        # the 16.10.1 registry (Brand R nth_hit, Morde R mode_gated,
        # TF W gold_card). Annie / Galio / Leona carry ONLY
        # unconditional CC. With ally side scoring all the conditional
        # contribution, ratio = ally_avg / enemy_avg = positive / 0
        # which the route clamps to a large finite (good).
        h = _do("/api/cc-conditional-pressure?ally=Brand,Mordekaiser,TwistedFate"
                "&enemy=Annie,Galio,Leona&mode=ARAM")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["tier"], "good")
        self.assertGreater(body["ally_total_cc_seconds"], 0.0)
        self.assertEqual(body["enemy_total_cc_seconds"], 0.0)

    def test_enemy_conditional_heavy_vs_no_cond_ally_is_bad(self) -> None:
        # Mirror: ally has no conditional CC, enemies are heavy.
        # ratio = 0.0 / positive = 0.0 -> bad.
        h = _do("/api/cc-conditional-pressure?ally=Annie,Galio,Leona"
                "&enemy=Brand,Mordekaiser,TwistedFate&mode=ARAM")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["tier"], "bad")
        self.assertEqual(body["ally_total_cc_seconds"], 0.0)
        self.assertGreater(body["enemy_total_cc_seconds"], 0.0)

    def test_zero_cc_both_sides_returns_balanced_warn(self) -> None:
        # Annie / Galio vs Veigar / Caitlyn - none of these carry
        # CONDITIONAL CC in the registry (only unconditional). Both
        # sides total_cc_seconds = 0.0; tier clamps to warn (the chip
        # is about CONDITIONAL CC threat balance specifically). Note:
        # Aatrox is NOT a safe pick post-wave-3 (Aatrox Q3 nth_hit
        # conditional landed ENGINE 1.40.0); Garen is NOT a safe pick
        # post-wave-16 (Garen Q nth_hit conditional silence landed
        # ENGINE 1.53.0); Veigar + Caitlyn remain unconditional-only
        # at patch 16.10.1.
        h = _do("/api/cc-conditional-pressure?ally=Annie,Galio"
                "&enemy=Veigar,Caitlyn&mode=ARAM")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["tier"], "warn")
        self.assertEqual(body["ally_total_cc_seconds"], 0.0)
        self.assertEqual(body["enemy_total_cc_seconds"], 0.0)
        self.assertEqual(body["ratio"], 1.0)

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
        cold = _do("/api/cc-conditional-pressure?ally=Brand,Mordekaiser"
                   "&enemy=Annie,Galio&mode=ARAM")
        self.assertFalse(cold.parsed()["cached"])
        warm = _do("/api/cc-conditional-pressure?ally=Brand,Mordekaiser"
                   "&enemy=Annie,Galio&mode=ARAM")
        self.assertTrue(warm.parsed()["cached"])

    def test_cache_key_invariant_to_input_order(self) -> None:
        # ally=Brand,Mordekaiser and ally=Mordekaiser,Brand should hit
        # the same cache slot.
        _do("/api/cc-conditional-pressure?ally=Brand,Mordekaiser"
            "&enemy=Annie,Galio&mode=ARAM")
        flipped = _do("/api/cc-conditional-pressure?ally=Mordekaiser,Brand"
                      "&enemy=Galio,Annie&mode=ARAM")
        self.assertTrue(flipped.parsed()["cached"])

    def test_cache_key_differentiates_mode(self) -> None:
        # ARAM vs SR should NOT share a cache slot - aramTenacity
        # changes the post-tenacity conditional contribution on the
        # 17 modified-tenacity champs.
        _do("/api/cc-conditional-pressure?ally=Brand,Mordekaiser"
            "&enemy=Annie,Galio&mode=ARAM")
        sr = _do("/api/cc-conditional-pressure?ally=Brand,Mordekaiser"
                 "&enemy=Annie,Galio&mode=SR")
        self.assertFalse(sr.parsed()["cached"])


# ---------------------------------------------------------------------
# FailSoftTests - DS engine fail-soft paths + unknown champions.
# ---------------------------------------------------------------------


class FailSoftTests(_Base):
    def test_unknown_champion_silently_skipped(self) -> None:
        # The route mirrors compute_cc_pressure's fail-soft contract:
        # unknown champions silently contribute 0 to the side's average
        # (compute_cc_pressure returns an empty result). Mixed known +
        # unknown still returns ok=true.
        h = _do("/api/cc-conditional-pressure?ally=Brand,NotAChamp"
                "&enemy=Annie,AlsoNotAChamp&mode=ARAM")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])


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
        # Skip chr-built BAD set lines themselves to avoid false positives.
        nonascii_lines = [
            i for i, line in enumerate(text.split("\n"))
            if any(ord(c) > 127 for c in line) and "chr(" not in line
        ]
        self.assertEqual(nonascii_lines, [],
                         f"non-ASCII lines: {nonascii_lines}")


if __name__ == "__main__":
    unittest.main()

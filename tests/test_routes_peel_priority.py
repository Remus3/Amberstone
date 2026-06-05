"""Tests for dashboard/routes_peel_priority.py - the FIRST live consumer
of the item-304 ally-amplification axis (Phase D, peel-target verdict).

The route pairs a live (or supplied) ALLY roster against
``agents.daemon_slayer.allyamp.compute_allyamp`` and emits a peel-target
verdict: who is the team's highest buff-throughput ally (protect_target)
and which allies can hard-save a teammate (saves_ally PROTECT mechanisms).

Covers:
  * RouteContractTests - ally absent triggers the live auto-read; ally
    present-but-blank returns no_champions; mode default SR + case
    folding; response-shape keys.
  * MathTests - known roster (Lulu / Soraka / Taric / Vayne / MasterYi)
    ranks Taric top (1.204, PROTECT, saves_ally), zeros the selfish
    carries; selfish-only roster yields protect_target None.
  * LiveAutoReadTests - _live_ally_roster monkeypatched: a populated
    roster reports source=live; an empty roster returns no_live_roster.
  * CacheTests - cold miss then warm hit, order-invariant cache key.
  * AsciiHygieneTests - no em-dashes / smart quotes in route or test.

Mirrors the test_routes_cc_conditional_pressure.StubHandler pattern.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from core.archetype_picks import canonical_champion_id
from dashboard import routes_peel_priority as rt


class StubHandler:
    """Same shape as test_routes_cc_conditional_pressure.StubHandler."""

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
    rt._serve_peel_priority(h)
    return h


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        rt._reset_caches()


# ---------------------------------------------------------------------
# RouteContractTests - input validation + the live auto-read fork.
# ---------------------------------------------------------------------


class RouteContractTests(_Base):
    def test_ally_param_blank_returns_no_champions(self) -> None:
        # ally key present but empty -> distinct from absent (which would
        # trigger the live auto-read).
        h = _do("/api/peel-priority?ally=")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "no_champions")

    def test_blank_entries_silently_skipped(self) -> None:
        h = _do("/api/peel-priority?ally=Lulu,,Soraka")
        self.assertEqual(h.last_status, 200)
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["ranked"]), 2)

    def test_mode_default_is_sr(self) -> None:
        h = _do("/api/peel-priority?ally=Lulu")
        body = h.parsed()
        self.assertEqual(body["mode"], "SR")

    def test_mode_case_insensitive(self) -> None:
        h = _do("/api/peel-priority?ally=Lulu&mode=aram")
        body = h.parsed()
        self.assertEqual(body["mode"], "ARAM")

    def test_response_shape_keys(self) -> None:
        h = _do("/api/peel-priority?ally=Lulu,Taric")
        body = h.parsed()
        for key in (
            "ok", "mode", "source", "ranked", "protect_target",
            "hard_saves", "verdict", "elapsed_ms", "cached",
        ):
            self.assertIn(key, body, f"missing key {key}")
        self.assertEqual(body["source"], "param")


# ---------------------------------------------------------------------
# MathTests - the ally-amp pairing + peel verdict.
# ---------------------------------------------------------------------


class MathTests(_Base):
    def test_taric_tops_a_mixed_roster_and_saves_ally(self) -> None:
        h = _do("/api/peel-priority?ally=Lulu,Soraka,Taric,Vayne,MasterYi")
        body = h.parsed()
        self.assertTrue(body["ok"])
        pt = body["protect_target"]
        self.assertIsNotNone(pt)
        self.assertEqual(pt["champion"], "Taric")
        self.assertTrue(pt["saves_ally"])
        self.assertEqual(pt["top_kind"], "PROTECT")
        self.assertAlmostEqual(pt["allyamp_score"], 1.204, places=3)

    def test_ranked_is_sorted_descending(self) -> None:
        h = _do("/api/peel-priority?ally=Vayne,Lulu,Taric,Soraka,MasterYi")
        ranked = h.parsed()["ranked"]
        scores = [r["allyamp_score"] for r in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(ranked[0]["champion"], "Taric")

    def test_selfish_champ_scores_zero(self) -> None:
        h = _do("/api/peel-priority?ally=Lulu,Vayne")
        ranked = {r["champion"]: r for r in h.parsed()["ranked"]}
        self.assertEqual(ranked["Vayne"]["allyamp_score"], 0.0)
        self.assertEqual(ranked["Vayne"]["top_kind"], "")

    def test_hard_saves_lists_protect_source(self) -> None:
        h = _do("/api/peel-priority?ally=Lulu,Taric,Soraka")
        hs = h.parsed()["hard_saves"]
        self.assertEqual(len(hs), 1)
        self.assertEqual(hs[0]["champion"], "Taric")
        self.assertEqual(hs[0]["source"], "R")

    def test_two_hard_saves_sorted_by_value(self) -> None:
        # Zilean R PROTECT SINGLE 0.9 cond -> 1.0*0.65*0.9*0.5 = 0.2925
        # Taric  R PROTECT TEAM   0.92 cond -> 1.0*1.0*0.92*0.5 = 0.46
        h = _do("/api/peel-priority?ally=Zilean,Taric")
        hs = h.parsed()["hard_saves"]
        self.assertEqual([x["champion"] for x in hs], ["Taric", "Zilean"])

    def test_selfish_only_roster_has_no_protect_target(self) -> None:
        h = _do("/api/peel-priority?ally=Vayne,MasterYi,Zed")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertIsNone(body["protect_target"])
        self.assertEqual(body["hard_saves"], [])
        self.assertIn("no ally buff", body["verdict"].lower())

    def test_verdict_names_protect_target(self) -> None:
        h = _do("/api/peel-priority?ally=Lulu,Soraka,Taric")
        self.assertIn("Taric", h.parsed()["verdict"])


# ---------------------------------------------------------------------
# LiveAutoReadTests - the ally-param-absent live roster fork.
# ---------------------------------------------------------------------


class LiveAutoReadTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        self._orig = rt._live_ally_roster

    def tearDown(self) -> None:
        rt._live_ally_roster = self._orig

    def test_absent_ally_reads_live_roster(self) -> None:
        rt._live_ally_roster = lambda: ["Janna", "Lulu"]
        h = _do("/api/peel-priority")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["source"], "live")
        self.assertEqual(len(body["ranked"]), 2)

    def test_absent_ally_no_game_returns_no_live_roster(self) -> None:
        rt._live_ally_roster = lambda: []
        h = _do("/api/peel-priority")
        body = h.parsed()
        self.assertEqual(h.last_status, 200)
        self.assertFalse(body["ok"])
        self.assertEqual(body["reason"], "no_live_roster")


# ---------------------------------------------------------------------
# CacheTests - TTL hit + order-invariant key.
# ---------------------------------------------------------------------


class CacheTests(_Base):
    def test_cold_miss_then_warm_hit(self) -> None:
        cold = _do("/api/peel-priority?ally=Lulu,Taric&mode=SR")
        self.assertFalse(cold.parsed()["cached"])
        warm = _do("/api/peel-priority?ally=Lulu,Taric&mode=SR")
        self.assertTrue(warm.parsed()["cached"])

    def test_cache_key_invariant_to_order(self) -> None:
        _do("/api/peel-priority?ally=Lulu,Taric&mode=SR")
        flipped = _do("/api/peel-priority?ally=Taric,Lulu&mode=SR")
        self.assertTrue(flipped.parsed()["cached"])


# ---------------------------------------------------------------------
# CanonicalIdTests - the display-name -> DDragon-id bridge the live path
# needs so multi-word registry champs are not silently missed.
# ---------------------------------------------------------------------


class CanonicalIdTests(unittest.TestCase):
    def test_multi_word_display_names_resolve(self) -> None:
        # The 4 ally-amp registry champs whose Live Client display name
        # differs from the canonical DDragon id. TahmKench is a PROTECT
        # hard-save - missing it live would drop a saves_ally call.
        self.assertEqual(canonical_champion_id("Tahm Kench"), "TahmKench")
        self.assertEqual(canonical_champion_id("Nunu & Willump"), "Nunu")
        self.assertEqual(canonical_champion_id("Renata Glasc"), "Renata")
        self.assertEqual(canonical_champion_id("Jarvan IV"), "JarvanIV")

    def test_display_only_alias_resolves(self) -> None:
        # Wukong (display) -> MonkeyKing (canonical id).
        self.assertEqual(canonical_champion_id("Wukong"), "MonkeyKing")

    def test_canonical_id_passthrough(self) -> None:
        self.assertEqual(canonical_champion_id("TahmKench"), "TahmKench")
        self.assertEqual(canonical_champion_id("Seraphine"), "Seraphine")
        self.assertEqual(canonical_champion_id("MasterYi"), "MasterYi")

    def test_unknown_passthrough_and_blank(self) -> None:
        self.assertEqual(canonical_champion_id("NotAChamp"), "NotAChamp")
        self.assertEqual(canonical_champion_id(""), "")


# ---------------------------------------------------------------------
# LiveRosterCanonicalizationTests - the REAL _live_ally_roster: drop self
# in display space, canonicalize survivors, end-to-end through the route.
# ---------------------------------------------------------------------


class LiveRosterCanonicalizationTests(_Base):
    def test_live_roster_drops_self_and_canonicalizes(self) -> None:
        fake = {
            "ally_team": ["Tahm Kench", "Caitlyn", "Master Yi"],
            "champion": "Caitlyn",
        }
        with mock.patch("dashboard._liveclient.liveclient_summary",
                        return_value=fake):
            self.assertEqual(rt._live_ally_roster(), ["TahmKench", "MasterYi"])

    def test_live_path_scores_multi_word_hard_save(self) -> None:
        # End-to-end: a live roster with "Tahm Kench" must score his
        # PROTECT hard-save, not silently miss it on the display-name form.
        fake = {
            "ally_team": ["Tahm Kench", "Caitlyn", "Master Yi"],
            "champion": "Caitlyn",
        }
        with mock.patch("dashboard._liveclient.liveclient_summary",
                        return_value=fake):
            h = _do("/api/peel-priority")
        body = h.parsed()
        self.assertTrue(body["ok"])
        self.assertEqual(body["source"], "live")
        self.assertEqual(body["protect_target"]["champion"], "TahmKench")
        self.assertEqual(len(body["hard_saves"]), 1)
        self.assertEqual(body["hard_saves"][0]["champion"], "TahmKench")
        self.assertEqual(body["hard_saves"][0]["source"], "R")


# ---------------------------------------------------------------------
# AsciiHygieneTests - CLAUDE.md hard rule.
# ---------------------------------------------------------------------


class AsciiHygieneTests(unittest.TestCase):
    def test_route_module_is_ascii(self) -> None:
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
        nonascii_lines = [
            i for i, line in enumerate(text.split("\n"))
            if any(ord(c) > 127 for c in line) and "chr(" not in line
        ]
        self.assertEqual(nonascii_lines, [],
                         f"non-ASCII lines: {nonascii_lines}")


if __name__ == "__main__":
    unittest.main()

"""Regression guards for the CC-blended EHP threat panel (item 139
carry (a)).

Backend dashboard/routes_cc_blended_ehp_threat.py shipped 2026-05-22 +
its own test suite (tests/test_routes_cc_blended_ehp_threat.py). This
file pins the four-file wiring that hooks the FIRST dashboard UI
consumer of cc_blended_ehp into the Suggestions card of the champ-
select view so a future refactor that drops one of the wires reverts
the surface to invisible:

  - web/js/panels/champ_select.js renders #csv-sugg-cc-blended-ehp-threat
    in the center My Pick card body, below the DS-vs-Enemy-Comp build
    (operator 2026-05-31 #8; moved out of the Assessment card in
    web/index.html).
  - web/js/panels/cc_blended_ehp_threat.js exports the API contract
    (fetchCcBlendedEhpThreat, getCachedCcBlendedEhpThreat,
    getCcBlendedEhpThreatCacheCount, renderCcBlendedEhpThreat,
    resolveChampNames).
  - web/js/panels/champ_select.js imports the panel module + calls
    _csvRenderCcBlendedEhpThreat from _csvRenderSuggestions, and
    counts the cache state in the section signature so the panel re-
    renders on land.
  - web/css/panels/cc_blended_ehp_threat.css carries the tier-tinted
    styles + is @import'd into web/css/dashboard.css.

These are grep-based smoke checks - cheap, fast, enough to catch a
missing wire. They mirror the test_ban_suggest_toggle_panel_dom.py
pattern.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "cc_blended_ehp_threat.js"
CHAMP_SELECT_JS = WEB / "js" / "panels" / "champ_select.js"
PANEL_CSS = WEB / "css" / "panels" / "cc_blended_ehp_threat.css"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# ChipMountTests - the HTML scaffold lands in the right place.
# ---------------------------------------------------------------------


class ChipMountTests(unittest.TestCase):
    # QA 2026-07-03 slice A (B8, docs/qa/CHAMP_SELECT_QA_2026-07-03.md):
    # the chip mount moved into the static TEAM ANALYSIS cluster
    # (#csv-team-analysis) in the Assessment card of web/index.html.
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(CHAMP_SELECT_JS)
        cls.html = _read(INDEX_HTML)

    def test_chip_mount_present_in_cluster(self) -> None:
        cluster_at = self.html.index('id="csv-team-analysis"')
        body_at = self.html.index('id="csv-ta-body"')
        chip_at = self.html.index('id="csv-sugg-cc-blended-ehp-threat"')
        self.assertLess(cluster_at, body_at)
        self.assertLess(body_at, chip_at)

    def test_chip_removed_from_mypick_body_render(self) -> None:
        # The JS-rebuilt My Pick body no longer carries the mount markup.
        self.assertNotIn('id="csv-sugg-cc-blended-ehp-threat"', self.text)

    def test_chip_hidden_by_default(self) -> None:
        idx = self.html.index('id="csv-sugg-cc-blended-ehp-threat"')
        tail = self.html[idx:idx + 400]
        self.assertIn("hidden", tail)

    def test_chip_carries_initial_data_cc_tier(self) -> None:
        self.assertIn('data-cc-tier="warn"', self.html)


# ---------------------------------------------------------------------
# JsConsumptionTests - the panel module ships the expected API +
# champ_select.js consumes it.
# ---------------------------------------------------------------------


class JsConsumptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.panel_text = _read(PANEL_JS)
        cls.cs_text = _read(CHAMP_SELECT_JS)

    def test_panel_exports_fetch(self) -> None:
        self.assertIn("export function fetchCcBlendedEhpThreat",
                      self.panel_text)

    def test_panel_exports_get_cached(self) -> None:
        self.assertIn("export function getCachedCcBlendedEhpThreat",
                      self.panel_text)

    def test_panel_exports_cache_count(self) -> None:
        self.assertIn("export function getCcBlendedEhpThreatCacheCount",
                      self.panel_text)

    def test_panel_exports_render(self) -> None:
        self.assertIn("export function renderCcBlendedEhpThreat",
                      self.panel_text)

    def test_panel_exports_resolve_names(self) -> None:
        self.assertIn("export function resolveChampNames",
                      self.panel_text)

    def test_panel_imports_champs(self) -> None:
        # resolveChampNames needs the CHAMPS.byId map to convert
        # numeric LCU ids to canonical DDragon slugs.
        self.assertIn("import { CHAMPS } from '../lib/items_index.js'",
                      self.panel_text)

    def test_champ_select_imports_panel(self) -> None:
        self.assertIn("from './cc_blended_ehp_threat.js'", self.cs_text)
        self.assertIn("fetchCcBlendedEhpThreat", self.cs_text)
        self.assertIn("renderCcBlendedEhpThreat", self.cs_text)
        self.assertIn("resolveChampNames", self.cs_text)

    def test_champ_select_calls_renderer(self) -> None:
        self.assertIn("_csvRenderCcBlendedEhpThreat(cs)", self.cs_text)

    def test_champ_select_reads_state_my_team_and_their_team(self) -> None:
        # The helper reads cs.my_team + cs.their_team - the canonical
        # champ-select state shape. Pinned so a future state-shape
        # rename doesn't silently break the chip.
        # Locate the helper body
        idx = self.cs_text.index("function _csvRenderCcBlendedEhpThreat")
        # Walk to the closing brace - search for the first standalone
        # closing brace that follows the function open. Cheaper: just
        # grep within a generous window.
        body = self.cs_text[idx:idx + 3000]
        self.assertIn("cs.my_team", body)
        self.assertIn("cs.their_team", body)

    def test_section_signature_includes_ccbe_cache_count(self) -> None:
        # The cache-count component lets _csvBuildSectionSig coalesce
        # re-renders on land.
        self.assertIn("getCcBlendedEhpThreatCacheCount", self.cs_text)
        self.assertIn("ccbe:", self.cs_text)


# ---------------------------------------------------------------------
# CssTierVariantsTests - tier-tinted CSS variants present + dashboard
# imports the panel CSS.
# ---------------------------------------------------------------------


class CssTierVariantsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.panel_css = _read(PANEL_CSS)
        cls.dashboard_css = _read(DASHBOARD_CSS)

    def test_three_tier_variants_present(self) -> None:
        self.assertIn('[data-cc-tier="good"]', self.panel_css)
        self.assertIn('[data-cc-tier="warn"]', self.panel_css)
        self.assertIn('[data-cc-tier="bad"]', self.panel_css)

    def test_tier_variants_use_signal_tokens(self) -> None:
        # Mirror the design-tokens.css semantic palette - the chip
        # should NOT hardcode color hexes (carry the dashboard's
        # semantic var() refs for consistency).
        self.assertIn("var(--signal-good", self.panel_css)
        self.assertIn("var(--signal-warn", self.panel_css)
        self.assertIn("var(--signal-bad", self.panel_css)

    def test_dashboard_imports_panel_css(self) -> None:
        self.assertIn("./panels/cc_blended_ehp_threat.css",
                      self.dashboard_css)

    def test_panel_hidden_rule_present(self) -> None:
        # data-cc-tier carries the color; the [hidden] attribute is the
        # visibility gate that JS controls. Without this rule the chip
        # would still occupy layout space when hidden.
        self.assertIn("[hidden]", self.panel_css)


# ---------------------------------------------------------------------
# AsciiHygieneTests - the new JS + CSS files MUST be pure-ASCII
# (CLAUDE.md hard rule). The test FILE itself is also scanned to catch
# accidental smart quotes in docstrings.
# ---------------------------------------------------------------------


class AsciiHygieneTests(unittest.TestCase):
    # Build the BAD set via chr() so this test file stays ASCII-clean
    # against its own scan.
    _BAD = (chr(0x2013), chr(0x2014), chr(0x2018), chr(0x2019),
            chr(0x201C), chr(0x201D))

    def _scan(self, path: Path) -> list[int]:
        text = path.read_text(encoding="utf-8")
        return [i for i, c in enumerate(text) if c in self._BAD]

    def test_panel_js_is_ascii(self) -> None:
        bad = self._scan(PANEL_JS)
        self.assertEqual(bad, [], f"non-ASCII chars in {PANEL_JS.name}")

    def test_panel_css_is_ascii(self) -> None:
        bad = self._scan(PANEL_CSS)
        self.assertEqual(bad, [], f"non-ASCII chars in {PANEL_CSS.name}")

    def test_self_is_ascii(self) -> None:
        # The test file should be clean too (skip the chr()-built _BAD
        # tuple line itself).
        text = Path(__file__).read_text(encoding="utf-8")
        offending_lines = []
        for i, line in enumerate(text.split("\n")):
            if "chr(0x" in line:
                continue
            if any(c in self._BAD for c in line):
                offending_lines.append(i)
        self.assertEqual(offending_lines, [])


if __name__ == "__main__":
    unittest.main()

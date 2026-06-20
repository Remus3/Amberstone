"""Regression guards for the CC-conditional pressure panel (item 144 -
FIRST dashboard UI consumer of cc_conditional, 5th overall consumer of
the cc_conditional ecosystem).

Backend dashboard/routes_cc_conditional_pressure.py shipped 2026-05-22
+ its own test suite (tests/test_routes_cc_conditional_pressure.py).
This file pins the four-file wiring that hooks the FIRST dashboard UI
consumer of cc_conditional into the Suggestions card of the champ-
select view so a future refactor that drops one of the wires reverts
the surface to invisible:

  - web/js/panels/champ_select.js renders #csv-sugg-cc-conditional-pressure
    in the center My Pick card body, below the DS-vs-Enemy-Comp build and
    after the #csv-sugg-cc-blended-ehp-threat chip (operator 2026-05-31 #8;
    moved out of the Assessment card in web/index.html).
  - web/js/panels/cc_conditional_pressure.js exports the API contract
    (fetchCcConditionalPressure, getCachedCcConditionalPressure,
    getCcConditionalPressureCacheCount, renderCcConditionalPressure,
    resolveChampNames).
  - web/js/panels/champ_select.js imports the panel module + calls
    _csvRenderCcConditionalPressure from _csvRenderSuggestions, and
    counts the cache state in the section signature so the panel re-
    renders on land.
  - web/css/panels/cc_conditional_pressure.css carries the tier-tinted
    styles + is @import'd into web/css/dashboard.css.

These are grep-based smoke checks - cheap, fast, enough to catch a
missing wire. Mirrors the test_cc_blended_ehp_threat_panel_dom.py
pattern.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "cc_conditional_pressure.js"
CHAMP_SELECT_JS = WEB / "js" / "panels" / "champ_select.js"
PANEL_CSS = WEB / "css" / "panels" / "cc_conditional_pressure.css"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# ChipMountTests - the HTML scaffold lands in the right place.
# ---------------------------------------------------------------------


class ChipMountTests(unittest.TestCase):
    # Operator 2026-05-31 (#8): the chip mount moved from web/index.html
    # (Assessment card) into the champ_select.js My Pick card body render.
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(CHAMP_SELECT_JS)
        cls.html = _read(INDEX_HTML)

    def test_chip_mount_present(self) -> None:
        self.assertIn('id="csv-sugg-cc-conditional-pressure"', self.text)
        self.assertIn("cc-conditional-pressure", self.text)

    def test_chip_removed_from_index_html(self) -> None:
        # Moved out of the Assessment card; must not be duplicated there.
        self.assertNotIn('id="csv-sugg-cc-conditional-pressure"', self.html)

    def test_chip_hidden_by_default(self) -> None:
        idx = self.text.index('id="csv-sugg-cc-conditional-pressure"')
        tail = self.text[idx:idx + 400]
        self.assertIn("hidden", tail)

    def test_chip_carries_initial_data_cc_cond_tier(self) -> None:
        self.assertIn('data-cc-cond-tier="warn"', self.text)

    def test_chip_below_build_order(self) -> None:
        # New location: in the My Pick body, after the DS-vs-Enemy-Comp
        # build (boHtml) so the flow is build -> CC cards.
        bo_at = self.text.index("${boHtml}")
        chip_at = self.text.index('id="csv-sugg-cc-conditional-pressure"')
        self.assertLess(bo_at, chip_at)

    def test_chip_below_blended_ehp_threat(self) -> None:
        # cc-blended chip THEN cc-conditional chip in the same render.
        blended_at = self.text.index('id="csv-sugg-cc-blended-ehp-threat"')
        cond_at = self.text.index('id="csv-sugg-cc-conditional-pressure"')
        self.assertLess(blended_at, cond_at)


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
        self.assertIn("export function fetchCcConditionalPressure",
                      self.panel_text)

    def test_panel_exports_get_cached(self) -> None:
        self.assertIn("export function getCachedCcConditionalPressure",
                      self.panel_text)

    def test_panel_exports_cache_count(self) -> None:
        self.assertIn("export function getCcConditionalPressureCacheCount",
                      self.panel_text)

    def test_panel_exports_render(self) -> None:
        self.assertIn("export function renderCcConditionalPressure",
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
        self.assertIn("from './cc_conditional_pressure.js'", self.cs_text)
        self.assertIn("fetchCcConditionalPressure", self.cs_text)
        self.assertIn("renderCcConditionalPressure", self.cs_text)
        self.assertIn("getCachedCcConditionalPressure", self.cs_text)
        self.assertIn("getCcConditionalPressureCacheCount", self.cs_text)

    def test_champ_select_calls_renderer(self) -> None:
        self.assertIn("_csvRenderCcConditionalPressure(cs)", self.cs_text)

    def test_champ_select_reads_state_my_team_and_their_team(self) -> None:
        # The helper reads cs.my_team + cs.their_team - the canonical
        # champ-select state shape. Pinned so a future state-shape
        # rename doesn't silently break the chip.
        idx = self.cs_text.index("function _csvRenderCcConditionalPressure")
        body = self.cs_text[idx:idx + 3000]
        self.assertIn("cs.my_team", body)
        self.assertIn("cs.their_team", body)

    def test_section_signature_includes_ccp_cache_count(self) -> None:
        # The cache-count component lets _csvBuildSectionSig coalesce
        # re-renders on land.
        self.assertIn("getCcConditionalPressureCacheCount", self.cs_text)
        self.assertIn("ccp:", self.cs_text)


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
        self.assertIn('[data-cc-cond-tier="good"]', self.panel_css)
        self.assertIn('[data-cc-cond-tier="warn"]', self.panel_css)
        self.assertIn('[data-cc-cond-tier="bad"]', self.panel_css)

    def test_tier_variants_use_signal_tokens(self) -> None:
        # Mirror the design-tokens.css semantic palette - the chip
        # should NOT hardcode color hexes (carry the dashboard's
        # semantic var() refs for consistency).
        self.assertIn("var(--signal-good", self.panel_css)
        self.assertIn("var(--signal-warn", self.panel_css)
        self.assertIn("var(--signal-bad", self.panel_css)

    def test_dashboard_imports_panel_css(self) -> None:
        self.assertIn("./panels/cc_conditional_pressure.css",
                      self.dashboard_css)

    def test_panel_hidden_rule_present(self) -> None:
        # data-cc-cond-tier carries the color; the [hidden] attribute
        # is the visibility gate that JS controls. Without this rule
        # the chip would still occupy layout space when hidden.
        self.assertIn("[hidden]", self.panel_css)

    def test_no_orphan_ratio_selectors(self) -> None:
        # item 213 (2026-05-28) replaced the ratio summary line with the
        # plain-language verdict line; renderCcConditionalPressure no
        # longer emits .cc-conditional-pressure-ratio / -ratio-value.
        # R6 ui-audit (2026-06-19) removed the orphaned CSS. Guard it
        # stays gone so a refactor can't resurrect dead selectors.
        self.assertNotIn(".cc-conditional-pressure-ratio", self.panel_css)

    def test_font_sizes_are_tokenized(self) -> None:
        # Every font-size resolves through a --fs-* token (no sub-floor
        # hardcoded px). R6 typography audit 2026-06-19.
        import re
        decls = re.findall(r"font-size\s*:\s*([^;]+);", self.panel_css)
        self.assertTrue(decls)
        for d in decls:
            self.assertIn(
                "var(--fs-", d,
                f"non-token font-size in cc_conditional_pressure.css: {d!r}")


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

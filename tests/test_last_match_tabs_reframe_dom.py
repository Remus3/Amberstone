"""Grep-based smoke tests for the s220 PGR S4 tabs reframe.

The Post Game Review tabbed section was reframed 4 -> 3:

  - Comp     -> Build         (rosters with full per-player items)
  - Chart    -> Graph (part)  (team-aggregate bars)
  - Timeline -> Graph (part)  (per-minute sparklines + objective ribbon)
  - Timeline -> AI Analysis   (WPA "Phases that mattered")
  - Insights -> AI Analysis   (3-column Quick Review)

Review remains a NAV button (routes to deep-review page), not a panel.

Legacy localStorage values (comp / chart / timeline / insights) migrate
to the new ids in `_migrateLegacyTab` so an operator who last viewed
"timeline" lands on Graph rather than blanking out.

Mirrors the cheap text-search precedent set by
``tests/test_draft_elo_panel_dom.py`` +
``tests/test_last_match_score_card_dom.py``.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL_JS   = ROOT / "web" / "js" / "panels" / "last_match.js"
PANEL_CSS  = ROOT / "web" / "css" / "panels" / "last_match.css"
INDEX_HTML = ROOT / "web" / "index.html"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TabStripTests(unittest.TestCase):
    """The 3 new tabs in the strip: Build / Graph / AI Analysis. The
    Review nav button stays at the right edge of the strip."""

    def test_three_canonical_tabs_present(self):
        html = _read(INDEX_HTML)
        self.assertIn('data-tab="build"', html)
        self.assertIn('data-tab="graph"', html)
        self.assertIn('data-tab="ai-analysis"', html)

    def test_legacy_tab_ids_removed(self):
        """The pre-S4 data-tab values (comp / chart / timeline /
        insights) MUST be removed from the tab strip + the panel divs
        or the saved-tab whitelist will reactivate them."""
        html = _read(INDEX_HTML)
        for legacy in ("comp", "chart", "timeline", "insights"):
            self.assertNotIn(f'data-tab="{legacy}"', html,
                             f"legacy data-tab={legacy!r} still in tab strip")
            self.assertNotIn(f'data-tab-panel="{legacy}"', html,
                             f"legacy data-tab-panel={legacy!r} still in HTML")

    def test_ai_analysis_tab_starts_active(self):
        """AI Analysis is the default landing tab as of the R30 autopsy-first
        reframe (ledger 604, `021318cd`): the view opens on the WPA/win-prob
        autopsy, not the Build roster scoreboard (gemini's named trap). Build
        receded to 3rd. (s220 S4 made Build default; R30 moved it.)"""
        html = _read(INDEX_HTML)
        strip = html.split('class="lm-tabs-strip"', 1)[1].split("</div>", 1)[0]
        self.assertIn('class="lm-tab is-active" data-tab="ai-analysis"', strip)
        # Build is still present but is NOT the default-active tab anymore.
        self.assertNotIn('class="lm-tab is-active" data-tab="build"', strip)

    def test_review_nav_button_stays(self):
        """The Review nav routes to a deep-review page (lm-tab-nav class)
        and is NOT a tabbed panel - do not remove."""
        html = _read(INDEX_HTML)
        self.assertIn('id="lm-go-to-review"', html)
        self.assertIn('class="lm-tab lm-tab-nav"', html)


class PanelMountTests(unittest.TestCase):
    """The 3 new panels mount the existing content trees - element IDs
    for the inner content stay the same so JS doesn't have to rewire."""

    def test_build_panel_hosts_team_roster(self):
        html = _read(INDEX_HTML)
        build = html.split('data-tab-panel="build"', 1)[1].split(
            'data-tab-panel="graph"', 1)[0]
        # Roster table + ally/enemy lists + MVP cards stay in Build.
        self.assertIn('id="lm-tc-table"',      build)
        self.assertIn('id="lm-tc-ally-list"',  build)
        self.assertIn('id="lm-tc-enemy-list"', build)
        self.assertIn('id="lm-tc-ally-mvp"',   build)
        self.assertIn('id="lm-tc-enemy-mvp"',  build)

    def test_graph_panel_merges_chart_and_timeline_visuals(self):
        html = _read(INDEX_HTML)
        graph = html.split('data-tab-panel="graph"', 1)[1].split(
            'data-tab-panel="ai-analysis"', 1)[0]
        # Chart bars + Timeline sparklines + Objective ribbon all here.
        self.assertIn('id="lm-chart-wrap"',     graph)
        self.assertIn('id="lm-chart-list"',     graph)
        self.assertIn('id="lm-tl-wrap"',        graph)
        self.assertIn('id="lm-tl-charts"',      graph)
        self.assertIn('id="lm-tl-ribbon"',      graph)
        # WPA is NOT in Graph - it landed in AI Analysis.
        self.assertNotIn('id="lm-wpa-wrap"',    graph)
        # Quick Review is NOT in Graph either.
        self.assertNotIn('class="lm-qr-cols"',  graph)

    def test_ai_analysis_hosts_wpa_then_quick_review(self):
        html = _read(INDEX_HTML)
        ai = html.split('data-tab-panel="ai-analysis"', 1)[1].split(
            "</div>\n        </div>", 1)[0]
        self.assertIn('id="lm-wpa-wrap"', ai)
        self.assertIn('class="lm-qr-cols"', ai)
        # WPA above Quick Review (heuristic-insights ordering).
        wpa_at = ai.index('id="lm-wpa-wrap"')
        qr_at  = ai.index('class="lm-qr-cols"')
        self.assertLess(wpa_at, qr_at,
                        "WPA Phases must precede Quick Review in AI Analysis")

    def test_ai_analysis_has_quick_review_three_columns(self):
        html = _read(INDEX_HTML)
        ai = html.split('data-tab-panel="ai-analysis"', 1)[1].split(
            "</div>\n        </div>", 1)[0]
        self.assertIn('id="lm-qr-right"',    ai)
        self.assertIn('id="lm-qr-wrong"',    ai)
        self.assertIn('id="lm-qr-chronic"',  ai)


class LegacyMigrationTests(unittest.TestCase):
    """An operator who last viewed Timeline pre-S4 should land on Graph
    after the reframe ships, not on a blank panel. _migrateLegacyTab
    handles the localStorage round-trip."""

    def test_js_defines_valid_tabs_constant(self):
        js = _read(PANEL_JS)
        self.assertIn('const _VALID_TABS = ["build", "graph", "ai-analysis"]', js)

    def test_js_defines_migrate_legacy_tab(self):
        js = _read(PANEL_JS)
        self.assertIn("function _migrateLegacyTab(", js)

    def test_migration_maps_each_legacy_id(self):
        js = _read(PANEL_JS)
        body = js.split("function _migrateLegacyTab(", 1)[1].split("\n}", 1)[0]
        # Mapping doctrine: comp -> build, chart -> graph, timeline ->
        # graph (visuals home), insights -> ai-analysis. Encoded so a
        # future schema move is visible at the test level.
        self.assertRegex(body, r'case\s+"comp":\s*return\s+"build"')
        self.assertRegex(body, r'case\s+"chart":\s*return\s+"graph"')
        self.assertRegex(body, r'case\s+"timeline":\s*return\s+"graph"')
        self.assertRegex(body, r'case\s+"insights":\s*return\s+"ai-analysis"')

    def test_wire_uses_migrated_value(self):
        js = _read(PANEL_JS)
        wire = js.split("export function wireLastMatchOnce(", 1)[1].split(
            "\n}\n", 1)[0]
        self.assertIn("_migrateLegacyTab(", wire)
        # The migrated value is what gates _activateTab + persists back
        # to localStorage so the legacy id doesn't re-trigger every load.
        self.assertIn("_VALID_TABS.includes(migrated)", wire)
        self.assertIn("localStorage.setItem(_TAB_LS_KEY, migrated)", wire)

    def test_no_legacy_whitelist_array(self):
        """The pre-S4 hard-coded array ["comp", "chart", "timeline",
        "insights"] MUST be gone - it would shadow the new whitelist."""
        js = _read(PANEL_JS)
        self.assertNotIn('"comp", "chart", "timeline", "insights"', js)

    def test_set_empty_state_does_not_reference_dead_id(self):
        """s220 S5 carry-forward: lm-build-pending was a dead id in the
        _setEmptyState forEach loop (no matching element in index.html;
        getElementById no-ops). RM-339: lm-tl-pending was dead in this
        same list on the day this test was written - S4 had already
        merged the Timeline placeholder into lm-chart-pending, which is
        itself in the list, so "the 3 live pending ids" was only ever 2
        and this test asserted the PRESENCE of a dead id. The forEach is
        now pinned to the 2 ids that really have elements in index.html.
        (_setTimeline keeps its own lm-tl-pending lookup - that one is a
        deliberate optional no-op, documented in web/index.html beside
        the merged placeholder.)"""
        js = _read(PANEL_JS)
        ses = js.split("function _setEmptyState(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn('["lm-tc-pending","lm-chart-pending"]', ses)
        self.assertNotIn("lm-build-pending", ses)
        self.assertNotIn("lm-tl-pending", ses)


class CssNoLegacySelectorsTests(unittest.TestCase):
    """No CSS rule may hard-code the old data-tab-panel="comp" /
    "chart" / "timeline" / "insights" values. The selectors are attr-
    agnostic so this is just a guard against future style refactors."""

    def test_css_has_no_legacy_attr_selectors(self):
        css = _read(PANEL_CSS)
        for legacy in ("comp", "chart", "timeline", "insights"):
            self.assertNotIn(f'data-tab-panel="{legacy}"', css,
                             f"CSS hard-codes legacy panel id {legacy!r}")
            self.assertNotIn(f'data-tab="{legacy}"', css,
                             f"CSS hard-codes legacy tab id {legacy!r}")


class AsciiHygieneTests(unittest.TestCase):
    """No em/en-dashes, smart quotes, or emoji slipped into the touched
    files. BAD dict built via chr() so this file stays clean against
    its own scan."""

    BAD = {
        chr(0x2013): "EN DASH",
        chr(0x2014): "EM DASH",
        chr(0x2018): "LEFT SINGLE QUOTE",
        chr(0x2019): "RIGHT SINGLE QUOTE",
        chr(0x201C): "LEFT DOUBLE QUOTE",
        chr(0x201D): "RIGHT DOUBLE QUOTE",
    }

    def _scan(self, path: Path) -> list[str]:
        text = path.read_text(encoding="utf-8")
        return [name for ch, name in self.BAD.items() if ch in text]

    def test_panel_js_is_ascii_clean(self):
        self.assertEqual([], self._scan(PANEL_JS))

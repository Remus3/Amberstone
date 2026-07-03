"""Regression guards for the personal best-build champ-select card.

Surfaces the operator's OWN winning items on their LOCKED champion (the
Overlay App E personal-WR build override, local-data half; docs/COMPETITOR_LIFT_
2026-06-16.md). The backend already ships + has its own suites
(core/personal_build_wr.py -> tests/test_personal_build_wr.py;
dashboard/routes_personal_build.py -> tests/test_routes_personal_build.py).
This file pins the five-file FRONTEND wiring that hooks the card into the
Suggestions card of champ-select so a future refactor that drops one of the
wires reverts the surface to invisible:

  - web/index.html declares #csv-personal-build inside .csv-card-suggestions,
    after the cooldown-watch / cc-pairing cards and above #csv-sugg-pickorder.
  - web/js/panels/personal_build.js exports the API contract
    (fetchPersonalBuild, getCachedPersonalBuild, getPersonalBuildCacheCount,
    renderPersonalBuild).
  - web/js/panels/champ_select.js imports the panel + calls
    _csvRenderPersonalBuild + reads cs.my_champion + counts cache state in
    the section signature.
  - web/css/panels/personal_build.css carries the card styling.
  - web/css/dashboard.css @import's the panel css.

Grep-based smoke checks - cheap, fast, enough to catch a missing wire.
Mirrors test_cooldown_watch_panel_dom.py.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "personal_build.js"
CHAMP_SELECT_JS = WEB / "js" / "panels" / "champ_select.js"
PANEL_CSS = WEB / "css" / "panels" / "personal_build.css"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class MountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_mount_present(self) -> None:
        self.assertIn('id="csv-personal-build"', self.text)
        self.assertIn("personal-build", self.text)

    def test_hidden_by_default(self) -> None:
        idx = self.text.index('id="csv-personal-build"')
        self.assertIn("hidden", self.text[idx:idx + 200])

    def test_inside_suggestions_card(self) -> None:
        # QA 2026-07-03 slice A (A2): the ghost pick-order wrapper that
        # used to close the card stack is gone; the skill-order mount is
        # the surviving downstream anchor.
        sugg_open = self.text.index("csv-card-suggestions")
        card_at = self.text.index('id="csv-personal-build"')
        skill_at = self.text.index('id="csv-sugg-ds-skill-order"')
        self.assertLess(sugg_open, card_at)
        self.assertLess(card_at, skill_at)


class JsConsumptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.panel_text = _read(PANEL_JS)
        cls.cs_text = _read(CHAMP_SELECT_JS)

    def test_panel_exports_fetch(self) -> None:
        self.assertIn("export function fetchPersonalBuild", self.panel_text)

    def test_panel_exports_get_cached(self) -> None:
        self.assertIn("export function getCachedPersonalBuild", self.panel_text)

    def test_panel_exports_cache_count(self) -> None:
        self.assertIn("export function getPersonalBuildCacheCount",
                      self.panel_text)

    def test_panel_exports_render(self) -> None:
        self.assertIn("export function renderPersonalBuild", self.panel_text)

    def test_champ_select_imports_panel(self) -> None:
        self.assertIn("from './personal_build.js'", self.cs_text)
        self.assertIn("fetchPersonalBuild", self.cs_text)
        self.assertIn("renderPersonalBuild", self.cs_text)
        self.assertIn("getCachedPersonalBuild", self.cs_text)
        self.assertIn("getPersonalBuildCacheCount", self.cs_text)

    def test_champ_select_calls_renderer(self) -> None:
        self.assertIn("_csvRenderPersonalBuild(cs)", self.cs_text)

    def test_champ_select_reads_my_champion(self) -> None:
        idx = self.cs_text.index("function _csvRenderPersonalBuild")
        body = self.cs_text[idx:idx + 2000]
        self.assertIn("cs.my_champion", body)

    def test_section_signature_includes_pbw_cache_count(self) -> None:
        self.assertIn("getPersonalBuildCacheCount", self.cs_text)
        self.assertIn("pbw:", self.cs_text)

    # --- R34 (popular-vs-winning lift) -------------------------------------
    # The served payload carries `most_common_build` (the operator's most
    # FREQUENT completed build) but the panel previously dropped it. Surface
    # it as the popular-vs-winrate dichotomy: a "usual build" line,
    # a per-row marker for items in the usual build, and a survivorship insight.
    def test_panel_reads_most_common_build(self) -> None:
        self.assertIn("most_common_build", self.panel_text)

    def test_panel_renders_usual_build_line(self) -> None:
        self.assertIn("pbw-usual", self.panel_text)

    def test_panel_renders_insight_callout(self) -> None:
        self.assertIn("pbw-insight", self.panel_text)

    def test_panel_exports_insight_helper(self) -> None:
        # The survivorship insight is computed from served data; exposed on
        # __test so the popular-vs-winning logic is unit-coverable.
        self.assertIn("_usualBuildInsight", self.panel_text)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.panel_css = _read(PANEL_CSS)
        cls.dashboard_css = _read(DASHBOARD_CSS)

    def test_card_class_present(self) -> None:
        self.assertIn(".personal-build", self.panel_css)
        self.assertIn(".pbw-row", self.panel_css)

    def test_usual_build_styled(self) -> None:
        # R34: the popular-build line + the survivorship insight carry styling.
        self.assertIn(".pbw-usual", self.panel_css)
        self.assertIn(".pbw-insight", self.panel_css)

    def test_uses_signal_tokens(self) -> None:
        self.assertIn("var(--signal-good", self.panel_css)

    def test_dashboard_imports_panel_css(self) -> None:
        self.assertIn("./panels/personal_build.css", self.dashboard_css)

    def test_hidden_rule_present(self) -> None:
        self.assertIn("[hidden]", self.panel_css)

    def test_font_sizes_are_tokenized(self) -> None:
        # Every font-size resolves through a --fs-* token (no hardcoded px).
        import re
        decls = re.findall(r"font-size\s*:\s*([^;]+);", self.panel_css)
        self.assertTrue(decls)
        for d in decls:
            self.assertIn(
                "var(--fs-", d,
                f"non-token font-size in personal_build.css: {d!r}")


class AsciiHygieneTests(unittest.TestCase):
    _BAD = (chr(0x2013), chr(0x2014), chr(0x2018), chr(0x2019),
            chr(0x201C), chr(0x201D))

    def _scan(self, path: Path) -> list[int]:
        text = path.read_text(encoding="utf-8")
        return [i for i, c in enumerate(text) if c in self._BAD]

    def test_panel_js_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_JS), [])

    def test_panel_css_is_ascii(self) -> None:
        self.assertEqual(self._scan(PANEL_CSS), [])


if __name__ == "__main__":
    unittest.main()

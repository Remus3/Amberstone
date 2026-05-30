"""Regression guards for the matchup cooldown-watch panel (competitor
lift #5, docs/COMPETITOR_LIFT_2026-05-30.md).

Backend dashboard/routes_cooldown_watch.py + its engine module
agents/daemon_slayer/cooldown_watch.py ship with their own suites
(tests/test_routes_cooldown_watch.py +
agents/daemon_slayer/tests/test_cooldown_watch_2026_05_30.py). This file
pins the four-file frontend wiring that hooks the card into the
Suggestions card of champ-select so a future refactor that drops one of
the wires reverts the surface to invisible:

  - web/index.html declares #csv-sugg-cooldown-watch inside
    .csv-card-suggestions, BELOW #csv-sugg-cc-conditional-pressure and
    ABOVE #csv-sugg-pickorder.
  - web/js/panels/cooldown_watch.js exports the API contract
    (fetchCooldownWatch, getCachedCooldownWatch,
    getCooldownWatchCacheCount, renderCooldownWatch).
  - web/js/panels/champ_select.js imports the panel + calls
    _csvRenderCooldownWatch + counts cache state in the section signature.
  - web/css/panels/cooldown_watch.css is @import'd into dashboard.css.

Grep-based smoke checks - cheap, fast, enough to catch a missing wire.
Mirrors test_cc_conditional_pressure_panel_dom.py.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "cooldown_watch.js"
CHAMP_SELECT_JS = WEB / "js" / "panels" / "champ_select.js"
PANEL_CSS = WEB / "css" / "panels" / "cooldown_watch.css"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class ChipMountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_mount_present(self) -> None:
        self.assertIn('id="csv-sugg-cooldown-watch"', self.text)
        self.assertIn("cooldown-watch", self.text)

    def test_hidden_by_default(self) -> None:
        idx = self.text.index('id="csv-sugg-cooldown-watch"')
        self.assertIn("hidden", self.text[idx:idx + 200])

    def test_inside_suggestions_card(self) -> None:
        sugg_open = self.text.index("csv-card-suggestions")
        chip_at = self.text.index('id="csv-sugg-cooldown-watch"')
        pickorder_at = self.text.index('id="csv-sugg-pickorder"')
        self.assertLess(sugg_open, chip_at)
        self.assertLess(chip_at, pickorder_at)

    def test_below_cc_conditional_pressure(self) -> None:
        cond_at = self.text.index('id="csv-sugg-cc-conditional-pressure"')
        cdw_at = self.text.index('id="csv-sugg-cooldown-watch"')
        self.assertLess(cond_at, cdw_at)


class JsConsumptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.panel_text = _read(PANEL_JS)
        cls.cs_text = _read(CHAMP_SELECT_JS)

    def test_panel_exports_fetch(self) -> None:
        self.assertIn("export function fetchCooldownWatch", self.panel_text)

    def test_panel_exports_get_cached(self) -> None:
        self.assertIn("export function getCachedCooldownWatch",
                      self.panel_text)

    def test_panel_exports_cache_count(self) -> None:
        self.assertIn("export function getCooldownWatchCacheCount",
                      self.panel_text)

    def test_panel_exports_render(self) -> None:
        self.assertIn("export function renderCooldownWatch", self.panel_text)

    def test_champ_select_imports_panel(self) -> None:
        self.assertIn("from './cooldown_watch.js'", self.cs_text)
        self.assertIn("fetchCooldownWatch", self.cs_text)
        self.assertIn("renderCooldownWatch", self.cs_text)
        self.assertIn("getCachedCooldownWatch", self.cs_text)
        self.assertIn("getCooldownWatchCacheCount", self.cs_text)

    def test_champ_select_calls_renderer(self) -> None:
        self.assertIn("_csvRenderCooldownWatch(cs)", self.cs_text)

    def test_champ_select_reads_their_team(self) -> None:
        idx = self.cs_text.index("function _csvRenderCooldownWatch")
        body = self.cs_text[idx:idx + 2000]
        self.assertIn("cs.their_team", body)

    def test_section_signature_includes_cdw_cache_count(self) -> None:
        self.assertIn("getCooldownWatchCacheCount", self.cs_text)
        self.assertIn("cdw:", self.cs_text)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.panel_css = _read(PANEL_CSS)
        cls.dashboard_css = _read(DASHBOARD_CSS)

    def test_card_class_present(self) -> None:
        self.assertIn(".cooldown-watch", self.panel_css)
        self.assertIn(".cdw-row", self.panel_css)
        self.assertIn(".cdw-cd", self.panel_css)

    def test_uses_signal_tokens(self) -> None:
        self.assertIn("var(--signal-warn", self.panel_css)

    def test_dashboard_imports_panel_css(self) -> None:
        self.assertIn("./panels/cooldown_watch.css", self.dashboard_css)

    def test_hidden_rule_present(self) -> None:
        self.assertIn("[hidden]", self.panel_css)


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

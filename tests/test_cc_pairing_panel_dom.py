"""Regression guards for the ally CC-pairing panel (CS1, 2026-06-08).

Backend dashboard/routes_cc_pairing.py + its engine module
agents/daemon_slayer/cc_pairing.py ship with their own suites
(tests/test_routes_cc_pairing.py + agents/daemon_slayer/tests/test_cc_pairing.py).
This file pins the four-file frontend wiring that hooks the card into the
Suggestions card of champ-select so a future refactor that drops one of
the wires reverts the surface to invisible:

  - web/index.html declares #csv-sugg-cc-pairing inside
    .csv-card-suggestions, BELOW #csv-sugg-bans and ABOVE
    #csv-sugg-pickorder (next to its enemy-threat twin cooldown-watch).
  - web/js/panels/cc_pairing.js exports the API contract
    (fetchCcPairing, getCachedCcPairing, getCcPairingCacheCount,
    renderCcPairing).
  - web/js/panels/champ_select.js imports the panel + calls
    _csvRenderCcPairing + counts cache state in the section signature.
  - web/css/panels/cc_pairing.css is @import'd into dashboard.css.

Grep-based smoke checks - cheap, fast, enough to catch a missing wire.
Mirrors test_cooldown_watch_panel_dom.py.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "cc_pairing.js"
CHAMP_SELECT_JS = WEB / "js" / "panels" / "champ_select.js"
PANEL_CSS = WEB / "css" / "panels" / "cc_pairing.css"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class ChipMountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_mount_present(self) -> None:
        self.assertIn('id="csv-sugg-cc-pairing"', self.text)
        self.assertIn("cc-pairing", self.text)

    def test_hidden_by_default(self) -> None:
        idx = self.text.index('id="csv-sugg-cc-pairing"')
        self.assertIn("hidden", self.text[idx:idx + 200])

    def test_inside_suggestions_card(self) -> None:
        sugg_open = self.text.index("csv-card-suggestions")
        chip_at = self.text.index('id="csv-sugg-cc-pairing"')
        pickorder_at = self.text.index('id="csv-sugg-pickorder"')
        self.assertLess(sugg_open, chip_at)
        self.assertLess(chip_at, pickorder_at)

    def test_below_bans_section(self) -> None:
        bans_at = self.text.index('id="csv-sugg-bans"')
        pair_at = self.text.index('id="csv-sugg-cc-pairing"')
        self.assertLess(bans_at, pair_at)


class JsConsumptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.panel_text = _read(PANEL_JS)
        cls.cs_text = _read(CHAMP_SELECT_JS)

    def test_panel_exports_fetch(self) -> None:
        self.assertIn("export function fetchCcPairing", self.panel_text)

    def test_panel_exports_get_cached(self) -> None:
        self.assertIn("export function getCachedCcPairing", self.panel_text)

    def test_panel_exports_cache_count(self) -> None:
        self.assertIn("export function getCcPairingCacheCount",
                      self.panel_text)

    def test_panel_exports_render(self) -> None:
        self.assertIn("export function renderCcPairing", self.panel_text)

    def test_champ_select_imports_panel(self) -> None:
        self.assertIn("from './cc_pairing.js'", self.cs_text)
        self.assertIn("fetchCcPairing", self.cs_text)
        self.assertIn("renderCcPairing", self.cs_text)
        self.assertIn("getCachedCcPairing", self.cs_text)
        self.assertIn("getCcPairingCacheCount", self.cs_text)

    def test_champ_select_calls_renderer(self) -> None:
        self.assertIn("_csvRenderCcPairing(cs)", self.cs_text)

    def test_champ_select_reads_my_team(self) -> None:
        idx = self.cs_text.index("function _csvRenderCcPairing")
        body = self.cs_text[idx:idx + 2000]
        self.assertIn("cs.my_team", body)

    def test_section_signature_includes_pair_cache_count(self) -> None:
        self.assertIn("getCcPairingCacheCount", self.cs_text)
        self.assertIn("ccpair:", self.cs_text)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.panel_css = _read(PANEL_CSS)
        cls.dashboard_css = _read(DASHBOARD_CSS)

    def test_card_class_present(self) -> None:
        self.assertIn(".cc-pairing", self.panel_css)
        self.assertIn(".ccpair-row", self.panel_css)
        self.assertIn(".ccpair-enablers", self.panel_css)

    def test_uses_signal_tokens(self) -> None:
        self.assertIn("var(--signal-good", self.panel_css)

    def test_uses_font_scale_tokens(self) -> None:
        self.assertIn("var(--fs-", self.panel_css)

    def test_dashboard_imports_panel_css(self) -> None:
        self.assertIn("./panels/cc_pairing.css", self.dashboard_css)

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

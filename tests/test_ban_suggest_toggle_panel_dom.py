"""Deletion guards for the HURTS-THEM / HELPS-US ban-suggest toggle.

History: item 109 shipped the dual-score toggle; the 2026-07-03 champ-select
QA (rulings A2+A7 in docs/qa/CHAMP_SELECT_QA_2026-07-03.md) removed it -
the toggle lived inside the hidden A2 ghost surface (display:none since
2026-05-23), dead UI. Slice A cut the champ-select mount + wiring, which
orphaned the frontend module (sole consumer); the operator-approved
follow-up cleanup (LEDGER 765) then DELETED
web/js/panels/ban_suggest_toggle.js + its CSS. The backend
(dashboard/routes_ban_suggest.py) STAYS - covered by its own route tests.

These grep guards pin the deleted state so a partial re-wire cannot drift
back in silently.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "ban_suggest_toggle.js"
PANEL_CSS = WEB / "css" / "panels" / "ban_suggest_toggle.css"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"
CHAMP_SELECT_JS = WEB / "js" / "panels" / "champ_select.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class ModuleDeletedTests(unittest.TestCase):
    def test_panel_js_deleted(self) -> None:
        self.assertFalse(PANEL_JS.exists(), f"{PANEL_JS} should be deleted")

    def test_panel_css_deleted(self) -> None:
        self.assertFalse(PANEL_CSS.exists(), f"{PANEL_CSS} should be deleted")

    def test_dashboard_css_import_removed(self) -> None:
        self.assertNotIn("panels/ban_suggest_toggle.css", _read(DASHBOARD_CSS))


class IndexHtmlRemovedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_toggle_block_removed(self) -> None:
        self.assertNotIn('id="csv-sugg-bs-toggle"', self.text)
        self.assertNotIn('id="csv-sugg-bs-mode"', self.text)
        self.assertNotIn('id="csv-sugg-bs-list"', self.text)

    def test_ghost_bans_wrapper_removed(self) -> None:
        # A2: the hidden bans grid + pick-order advisory wrappers are gone.
        self.assertNotIn('id="csv-sugg-bans-grid"', self.text)
        self.assertNotIn('id="csv-sugg-pickorder"', self.text)


class ChampSelectWiringRemovedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(CHAMP_SELECT_JS)

    def test_import_removed(self) -> None:
        self.assertNotIn("from './ban_suggest_toggle.js'", self.text)
        for sym in (
            "fetchBanSuggest",
            "getCachedBanSuggest",
            "getBanSuggestCacheCount",
            "renderBanSuggestModeChip",
            "renderBanSuggestList",
        ):
            self.assertNotIn(sym, self.text)

    def test_render_helper_removed(self) -> None:
        self.assertNotIn("function _csvRenderBanSuggestToggle", self.text)

    def test_ghost_bans_fetch_removed(self) -> None:
        # A2: the global-top-bans fetch that fed the hidden grid is gone.
        self.assertNotIn("_csvFetchBanSuggestions", self.text)
        self.assertNotIn("_CSV_BANSUGG_CACHE", self.text)

    def test_section_signature_folds_removed(self) -> None:
        self.assertNotIn("bsdual:", self.text)
        self.assertNotIn("bsugg:", self.text)

    def test_no_other_js_consumer(self) -> None:
        for f in (WEB / "js").rglob("*.js"):
            self.assertNotIn(
                "from './ban_suggest_toggle.js'", _read(f),
                f"{f} imports the deleted ban_suggest_toggle.js",
            )


class BackendKeptTests(unittest.TestCase):
    def test_route_module_still_exists(self) -> None:
        self.assertTrue(
            (ROOT / "dashboard" / "routes_ban_suggest.py").exists(),
            "backend route module must stay (operator kept all backends)",
        )


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self) -> None:
        raw = Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()

"""Regression guards for the HURTS-THEM / HELPS-US ban-suggest toggle -
updated for the 2026-07-03 champ-select QA (slice A, rulings A2+A7 in
docs/qa/CHAMP_SELECT_QA_2026-07-03.md).

A7: the dual-score ban toggle lived inside the hidden A2 ghost surface
(display:none since 2026-05-23) - dead UI. Slice A REMOVED the champ-select
mount (#csv-sugg-bs-toggle) + the champ_select.js wiring
(_csvRenderBanSuggestToggle + the fetchBanSuggest import + the bsdual sig
fold). The backend (dashboard/routes_ban_suggest.py) and the frontend
module (web/js/panels/ban_suggest_toggle.js) STAY. This file pins BOTH
directions:

  - web/index.html no longer carries #csv-sugg-bs-toggle / bs-mode-chip /
    bs-list mounts.
  - web/js/panels/champ_select.js no longer imports or renders the toggle.
  - web/js/panels/ban_suggest_toggle.js still exports its full API
    contract (currently orphaned - champ select was its sole consumer).

Grep-based smoke checks - cheap, fast, enough to catch a re-wire drift.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "ban_suggest_toggle.js"
CHAMP_SELECT_JS = WEB / "js" / "panels" / "champ_select.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


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


class PanelJsTests(unittest.TestCase):
    """The module keeps its API contract (backend + module stay)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(PANEL_JS)

    def test_exports_fetch(self) -> None:
        self.assertIn("export function fetchBanSuggest", self.text)

    def test_exports_render_mode_chip(self) -> None:
        self.assertIn("export function renderBanSuggestModeChip", self.text)

    def test_exports_render_list(self) -> None:
        self.assertIn("export function renderBanSuggestList", self.text)

    def test_exports_mode_helpers(self) -> None:
        self.assertIn("export function getBanSuggestMode", self.text)
        self.assertIn("export function setBanSuggestMode", self.text)

    def test_exports_cache_count(self) -> None:
        self.assertIn("export function getCachedBanSuggest", self.text)
        self.assertIn("export function getBanSuggestCacheCount", self.text)

    def test_hits_correct_endpoint(self) -> None:
        self.assertIn('"/api/ban-suggest?"', self.text)


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


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self) -> None:
        raw = Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()

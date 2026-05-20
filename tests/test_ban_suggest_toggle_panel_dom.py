"""Regression guards for the HURTS-THEM / HELPS-US ban-suggest toggle.

Backend `dashboard/routes_ban_suggest.py` shipped 2026-05-20 commit
6e7b7e5 returning BOTH ratings per candidate; the frontend toggle
chip + sortable candidate list is item 109 carry-forward (a). The
backend has its own test suite (tests/test_routes_ban_suggest.py);
this file pins the four-file wiring that hooks the panel into the
Suggestions card of the champ-select view so a future refactor that
drops one of the wires reverts the surface to invisible:

  - web/index.html declares #csv-sugg-bs-toggle + #csv-sugg-bs-mode +
    #csv-sugg-bs-list inside the .csv-card-suggestions block
  - web/js/panels/ban_suggest_toggle.js exports the API contract
    (fetchBanSuggest, renderBanSuggestModeChip, renderBanSuggestList,
    getBanSuggestMode, setBanSuggestMode, getBanSuggestCacheCount)
  - web/js/panels/champ_select.js imports the panel module + calls it
    from _csvRenderSuggestions, and counts the cache state in the
    section signature so the panel re-renders on land
  - web/css/panels/ban_suggest_toggle.css carries the styles + is
    @import'd into web/css/dashboard.css

These are grep-based smoke checks - cheap, fast, enough to catch a
missing wire. They mirror the test_augment_reco_panel_dom.py pattern.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "ban_suggest_toggle.js"
CHAMP_SELECT_JS = WEB / "js" / "panels" / "champ_select.js"
PANEL_CSS = WEB / "css" / "panels" / "ban_suggest_toggle.css"
DASHBOARD_CSS = WEB / "css" / "dashboard.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class IndexHtmlTests(unittest.TestCase):
    """The toggle block + sub-elements must live inside the Suggestions
    card (.csv-card-suggestions) above the legacy bans grid."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_toggle_block_present(self) -> None:
        self.assertIn('id="csv-sugg-bs-toggle"', self.text)
        self.assertIn("bs-toggle-block", self.text)

    def test_mode_chip_present(self) -> None:
        self.assertIn('id="csv-sugg-bs-mode"', self.text)
        self.assertIn("bs-mode-chip", self.text)

    def test_list_container_present(self) -> None:
        self.assertIn('id="csv-sugg-bs-list"', self.text)
        self.assertIn('class="bs-list"', self.text)

    def test_block_hidden_by_default(self) -> None:
        # Ships hidden; JS reveals only when an ally is locked + the
        # candidate pool has landed.
        idx = self.text.index('id="csv-sugg-bs-toggle"')
        # The hidden attribute should appear on the same element
        # (within the next 200 chars - tag is short).
        tail = self.text[idx:idx + 400]
        self.assertIn("hidden", tail)

    def test_default_mode_attr(self) -> None:
        # Default mode chip data attr surfaces "hurts_them" for first
        # paint; the panel module re-stamps from localStorage.
        self.assertIn('data-bs-mode="hurts_them"', self.text)

    def test_block_is_inside_suggestions_card(self) -> None:
        sugg_open = self.text.index('csv-card-suggestions')
        block_at = self.text.index('id="csv-sugg-bs-toggle"')
        # The legacy bans grid follows the toggle (toggle is ABOVE it).
        legacy_at = self.text.index('id="csv-sugg-bans-grid"')
        self.assertLess(sugg_open, block_at)
        self.assertLess(block_at, legacy_at)


class PanelJsTests(unittest.TestCase):
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
        # The backend wire is /api/ban-suggest (NOT the legacy global-
        # top-bans /api/champ-select/ban-suggestions).
        self.assertIn('"/api/ban-suggest?"', self.text)

    def test_reads_dual_score_fields(self) -> None:
        # Both ratings + sample-density floors come through from the
        # backend response. The panel must read every field it shows.
        for field in (
            "hurts_them_score",
            "helps_us_score",
            "min_solo_n",
            "min_pair_n",
            "candidates",
            "champ_id",
        ):
            self.assertIn(field, self.text)

    def test_has_idempotency_guard(self) -> None:
        # Dashboard render idempotency rule - sig-dedup gate is
        # mandatory + a test seam reset helper.
        self.assertIn("_BS_SIG", self.text)
        self.assertIn("export function _resetBanSuggest", self.text)

    def test_persists_mode_via_localstorage(self) -> None:
        # Mode chip survives champ-select refresh + next session.
        self.assertIn("rc-cs-bansugg-mode", self.text)
        self.assertIn("localStorage", self.text)

    def test_mode_has_two_options(self) -> None:
        # Both modes must be in the validation set.
        self.assertIn('"hurts_them"', self.text)
        self.assertIn('"helps_us"', self.text)


class ChampSelectWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(CHAMP_SELECT_JS)

    def test_imports_panel(self) -> None:
        # The import block must pull the 5 entrypoints used in the
        # render helper - any one drop is a regression.
        self.assertIn("from './ban_suggest_toggle.js'", self.text)
        for sym in (
            "fetchBanSuggest",
            "getCachedBanSuggest",
            "getBanSuggestCacheCount",
            "renderBanSuggestModeChip",
            "renderBanSuggestList",
        ):
            self.assertIn(sym, self.text)

    def test_render_helper_defined(self) -> None:
        self.assertIn("function _csvRenderBanSuggestToggle", self.text)

    def test_render_helper_called_from_suggestions(self) -> None:
        # Helper must be invoked from _csvRenderSuggestions so a
        # re-render of the Suggestions card refreshes the toggle.
        sugg_fn = self.text.index("function _csvRenderSuggestions")
        toggle_call = self.text.index("_csvRenderBanSuggestToggle(cs,",
                                       sugg_fn)
        sugg_end = self.text.index("\n}", toggle_call)
        self.assertLess(sugg_fn, toggle_call)
        self.assertLess(toggle_call, sugg_end)

    def test_section_signature_includes_dual_cache(self) -> None:
        # Without this, the rAF-coalesced re-render gate would bail
        # on the second tick after the ban-suggest fetch lands.
        self.assertIn("getBanSuggestCacheCount()", self.text)
        self.assertIn("bsdual:", self.text)


class CssTests(unittest.TestCase):
    def test_panel_css_has_core_rules(self) -> None:
        css = _read(PANEL_CSS)
        # The mode chip + list + per-row are all required for the
        # toggle to be operable - any one missing is a regression.
        for cls in (
            ".bs-toggle-block",
            ".bs-mode-chip",
            ".bs-mode-opt",
            ".bs-list",
            ".bs-row",
            ".bs-row-active",
            ".bs-row-other",
            ".bs-row-sample",
        ):
            self.assertIn(cls, css)

    def test_band_color_classes_match_signal_set(self) -> None:
        css = _read(PANEL_CSS)
        # Band colors mirror s106 personal_vs / draft_elo: red /
        # amber / green for score; low / mid / high for sample.
        for band in ("bs-band-red", "bs-band-amber", "bs-band-green"):
            self.assertIn(band, css)
        for s in ("bs-sample-low", "bs-sample-mid", "bs-sample-high"):
            self.assertIn(s, css)

    def test_dashboard_css_imports_panel(self) -> None:
        self.assertIn(
            "@import './panels/ban_suggest_toggle.css';",
            _read(DASHBOARD_CSS),
        )


class AsciiHygieneTests(unittest.TestCase):
    """The repo-wide no-em-dash hard rule (CLAUDE.md) - every
    new file must stay 7-bit ASCII clean."""

    def _assert_ascii(self, path: Path) -> None:
        raw = path.read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as exc:
            self.fail(f"{path.name} is not pure ASCII at byte {exc.start}: "
                      f"{raw[max(0, exc.start - 20):exc.start + 20]!r}")

    def test_panel_js_is_ascii(self) -> None:
        self._assert_ascii(PANEL_JS)

    def test_panel_css_is_ascii(self) -> None:
        self._assert_ascii(PANEL_CSS)


if __name__ == "__main__":
    unittest.main()

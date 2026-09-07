"""HIST1 + HIST2 DOM/source smoke tests.

HIST1 (ui-bug): clicking a populated match row on the Session OR History
page must open that match's detail. Pre-fix the rows rendered with NO
click handler (`_historyRenderMatches` + the `session-matches` loop in
main.js built the <li> and never wired a click), so the click was a
no-op. These guards pin the new wiring.

HIST2 (ui-ux): the click opens a DETACHED historical PGR
(#view-historical-pgr / historical_pgr.js) that renders the match "as if
it had just ended", SEPARATE from the live last-match PGR
(#view-last-match / last_match.js). The CRITICAL invariant is no-clobber:
the historical panel must own an entirely separate hpgr- prefixed DOM and
must NEVER reference any lm- element id, so opening a historical match
cannot mutate the operator's real most-recent-game PGR state.

These are cheap text-search guards over the JS / HTML / CSS source,
mirroring tests/test_last_match_score_card_dom.py +
tests/test_draft_elo_panel_dom.py. The live click -> detached-frame ->
back -> no-clobber behavior is covered end-to-end by the Playwright test
tests/snapshot_panels/test_historical_pgr_view.py.

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN_JS    = ROOT / "web" / "js" / "main.js"
HPGR_JS    = ROOT / "web" / "js" / "panels" / "historical_pgr.js"
LASTM_JS   = ROOT / "web" / "js" / "panels" / "last_match.js"
STATE_JS   = ROOT / "web" / "js" / "lib" / "state.js"
INDEX_HTML = ROOT / "web" / "index.html"
HOME_CSS   = ROOT / "web" / "css" / "panels" / "home.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class Hist1RowClickWiringTests(unittest.TestCase):
    """The Session + History match rows get a working click handler that
    routes to the detached historical PGR."""

    def test_main_defines_row_click_helper(self):
        js = _read(MAIN_JS)
        self.assertIn("function _wireMatchRowToHistoricalPgr(", js)

    def test_history_render_matches_wires_click(self):
        """_historyRenderMatches builds each row via _historyMatchRowEl, which
        wires the click. The R30 history refactor (`d015ef34`) extracted the
        row builder so the session list AND the filtered-matchup subset share
        one wired row, so the wiring call moved one level in. Pin both halves:
        the render uses the row builder, and the row builder wires the click."""
        js = _read(MAIN_JS)
        body = js.split("function _historyRenderMatches(", 1)[1].split("\n  }", 1)[0]
        self.assertIn("_historyMatchRowEl(", body)
        rowel = js.split("function _historyMatchRowEl(", 1)[1].split("\n  }", 1)[0]
        self.assertIn("_wireMatchRowToHistoricalPgr(", rowel)

    def test_session_render_wires_click(self):
        """The session-matches loop must wire the click too (the Session
        page rows were equally inert pre-fix)."""
        js = _read(MAIN_JS)
        # Scope to the session fetcher.
        body = js.split("function _sessionFetchAndRender(", 1)[1].split(
            "function _historyFetchAndRender", 1)[0]
        self.assertIn('document.getElementById("session-matches")', body)
        self.assertIn("_wireMatchRowToHistoricalPgr(", body)

    def test_click_helper_stashes_ts_and_routes(self):
        """The helper stashes the row timestamp + routes to the new view
        (hash + manual). The timestamp is the data source key."""
        js = _read(MAIN_JS)
        helper = js.split("function _wireMatchRowToHistoricalPgr(", 1)[1].split(
            "\n  }", 1)[0]
        self.assertIn('sessionStorage.setItem("rc-hpgr-match-ts"', helper)
        self.assertIn('"#historical-pgr"', helper)
        self.assertIn('_viewSaveManual("historical-pgr")', helper)
        self.assertIn("addEventListener(\"click\"", helper)

    def test_click_helper_keyboard_accessible(self):
        js = _read(MAIN_JS)
        helper = js.split("function _wireMatchRowToHistoricalPgr(", 1)[1].split(
            "\n  }", 1)[0]
        self.assertIn('addEventListener("keydown"', helper)
        self.assertIn('role', helper)
        self.assertIn('tabindex', helper)

    def test_inert_row_without_ts_is_skipped(self):
        """A row with no timestamp has no match key - the helper bails so
        we never route to a blank archive view."""
        js = _read(MAIN_JS)
        helper = js.split("function _wireMatchRowToHistoricalPgr(", 1)[1].split(
            "\n  }", 1)[0]
        self.assertIn("if (!li || !ts) return;", helper)

    def test_css_marks_clickable_row(self):
        css = _read(HOME_CSS)
        self.assertIn(".history-match-row-clickable", css)
        self.assertIn("cursor: pointer", css)


class Hist2DetachedViewTests(unittest.TestCase):
    """A separate #view-historical-pgr section + historical_pgr.js panel,
    registered as its own view."""

    def test_view_registered_in_view_ids(self):
        js = _read(STATE_JS)
        ids = js.split("VIEW_IDS", 1)[1].split("]", 1)[0]
        self.assertIn('"historical-pgr"', ids)

    def test_view_has_label(self):
        js = _read(STATE_JS)
        self.assertIn('"historical-pgr":', js)

    def test_index_mounts_detached_section(self):
        html = _read(INDEX_HTML)
        self.assertIn('id="view-historical-pgr"', html)
        self.assertIn('id="hpgr-body"', html)
        self.assertIn('id="hpgr-back"', html)

    def test_index_detached_section_uses_hpgr_ids(self):
        """The detached section's interactive/data ids are hpgr- prefixed
        so they cannot collide with the live PGR's lm- ids."""
        html = _read(INDEX_HTML)
        section = html.split('id="view-historical-pgr"', 1)[1].split(
            '</section>', 1)[0]
        for needed in ("hpgr-portrait", "hpgr-champion-name", "hpgr-grade-badge",
                       "hpgr-tc-table", "hpgr-tc-ally-list", "hpgr-tc-enemy-list"):
            self.assertIn(needed, section, f"{needed} missing from detached section")

    def test_main_imports_and_wires_panel(self):
        js = _read(MAIN_JS)
        self.assertIn("from './panels/historical_pgr.js'", js)
        self.assertIn("wireHistoricalPgrOnce", js)
        self.assertIn("renderHistoricalPgr", js)

    def test_applyview_branch_renders_from_stashed_ts(self):
        js = _read(MAIN_JS)
        branch = js.split('if (viewId === "historical-pgr")', 1)[1].split(
            "\n    }", 1)[0]
        self.assertIn('sessionStorage.getItem("rc-hpgr-match-ts")', branch)
        self.assertIn("renderHistoricalPgr(", branch)
        self.assertIn("wireHistoricalPgrOnce()", branch)

    def test_panel_fetches_by_match_ts(self):
        """The panel data source is /api/last-match?match_ts= - the
        HIST2-parameterized historical PGR builder."""
        js = _read(HPGR_JS)
        self.assertIn("/api/last-match", js)
        self.assertIn("match_ts=", js)
        self.assertIn("encodeURIComponent(ts)", js)

    def test_panel_back_routes_to_history(self):
        js = _read(HPGR_JS)
        self.assertIn('id="hpgr-back"', _read(INDEX_HTML))
        # Back handler navigates to History.
        self.assertIn('"#history"', js)


class Hist2NoClobberInvariantTests(unittest.TestCase):
    """The CRITICAL no-clobber guarantee: the historical panel must not
    touch ANY live-PGR lm- element id, and must not import the live PGR's
    render entry points (which mutate the lm- DOM + _lastData singleton)."""

    # Tokens that would mean the historical panel is writing the live PGR
    # DOM. We scan getElementById / querySelector targets specifically.
    _LM_ID_PATTERN = re.compile(r"""getElementById\(\s*["']lm-""")

    def test_panel_never_targets_lm_ids(self):
        js = _read(HPGR_JS)
        hits = self._LM_ID_PATTERN.findall(js)
        self.assertEqual(
            hits, [],
            "historical_pgr.js references a live-PGR lm- element id - that "
            "would clobber the live #view-last-match PGR state",
        )

    def test_panel_does_not_query_lm_class_roots_by_id(self):
        """No getElementById('lm-...') anywhere (covers the .lm-hero box -
        the historical panel uses its own #hpgr-hero)."""
        js = _read(HPGR_JS)
        self.assertNotIn('getElementById("lm-hero")', js)
        self.assertNotIn("getElementById('lm-hero')", js)

    def test_panel_does_not_import_live_pgr_render(self):
        """Importing fetchAndRenderLastMatch / renderLastMatch would run the
        live PGR render against the lm- DOM. The detached panel must own its
        render path, not borrow the singleton's. (A prose mention of the
        filename in a comment is fine - only an actual import statement is
        the clobber risk, so scan for the import form.)"""
        js = _read(HPGR_JS)
        self.assertNotIn("fetchAndRenderLastMatch", js)
        # No `import ... from '.../last_match.js'`.
        self.assertFalse(
            re.search(r"import[^;]*last_match\.js", js),
            "historical_pgr.js imports from last_match.js - that couples it "
            "to the live PGR render path",
        )

    def test_panel_has_its_own_state(self):
        """The panel keeps its own module-level current-ts/state so it is
        independent of last_match.js's _lastData."""
        js = _read(HPGR_JS)
        self.assertIn("let _currentTs", js)

    def test_back_does_not_refetch_live_pgr(self):
        """The Back handler must NOT call the live PGR fetch - the live
        state was never mutated, so re-fetching is unnecessary and would
        only mask a clobber bug. Guard that it is absent from the handler."""
        js = _read(HPGR_JS)
        back = js.split('id === "hpgr-back"', 1)[-1]  # fall through if absent
        # Whole-file guard is the real assertion (panel never imports it).
        self.assertNotIn("fetchAndRenderLastMatch", js)


class AsciiHygieneTests(unittest.TestCase):
    """No em/en-dashes, smart quotes, or emoji in the touched authored
    files. CLAUDE.md hard rule. Bad-glyph table via chr() so this file is
    ASCII-clean against its own scan."""

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

    def test_panel_js_ascii_clean(self):
        self.assertEqual([], self._scan(HPGR_JS))

    def test_panel_js_no_high_bytes(self):
        raw = HPGR_JS.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        self.assertEqual([], offenders[:5],
                         f"non-ASCII byte(s) in {HPGR_JS}")

    def test_test_file_ascii_clean(self):
        self.assertEqual([], self._scan(Path(__file__)))


if __name__ == "__main__":
    unittest.main()

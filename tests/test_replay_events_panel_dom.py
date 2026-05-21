"""Grep-based smoke tests for the s220 PGR S5 Replay event ribbon.

Three concerns this guards:

1. The Match-V5 timeline event ribbon mounts under #replay-events-section
   in the Replay view, with filter checkboxes wired for items/skills/
   wards opt-in and an event count chip.
2. PGR's "Review ->" button routes to view-replay (NOT a never-built
   "view-review" id) and stashes the match id to sessionStorage under
   the new rc-replay-focus-match key (pre-S5 was rc-review-focus-match,
   which was broken because VIEW_IDS never contained "review").
3. The cleanroom boundary on league_record (GPLv3) is documented in
   docs/adr/ADR-009 + a pointer comment in the frontend panel. If
   someone ever proposes vendoring league_record source, these tests
   surface the boundary.

Mirrors the cheap text-search precedent in
``tests/test_last_match_tabs_reframe_dom.py`` +
``tests/test_last_match_score_card_dom.py``.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML       = ROOT / "web" / "index.html"
EVENTS_JS        = ROOT / "web" / "js" / "panels" / "replay_events.js"
EVENTS_CSS       = ROOT / "web" / "css" / "panels" / "replay_events.css"
DEV_JS           = ROOT / "web" / "js" / "panels" / "dev.js"
LAST_MATCH_JS    = ROOT / "web" / "js" / "panels" / "last_match.js"
DASHBOARD_CSS    = ROOT / "web" / "css" / "dashboard.css"
ADR_DOC          = ROOT / "docs" / "adr" / "ADR-009-replay-events-cleanroom.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class EventRibbonMountTests(unittest.TestCase):
    """The event ribbon section + filter checkboxes mount inside the
    Replay view's main pane."""

    def test_section_id_mounted(self):
        html = _read(INDEX_HTML)
        self.assertIn('id="replay-events-section"', html)
        self.assertIn('id="replay-events-list"',    html)
        self.assertIn('id="replay-events-count"',   html)
        self.assertIn('id="replay-events-empty"',   html)

    def test_section_starts_hidden(self):
        html = _read(INDEX_HTML)
        # The hidden attribute keeps the section out of the way until a
        # match is loaded; loadReplayEvents flips it visible.
        block = html.split('id="replay-events-section"', 1)[1].split(">", 1)[0]
        self.assertIn("hidden", block)

    def test_filter_checkboxes_present(self):
        html = _read(INDEX_HTML)
        for cb_id in ("replay-evt-items", "replay-evt-skills", "replay-evt-wards"):
            self.assertIn(f'id="{cb_id}"', html, f"missing filter checkbox {cb_id}")

    def test_section_lives_inside_view_replay(self):
        html = _read(INDEX_HTML)
        replay = html.split('id="view-replay"', 1)[1].split("</section>", 1)[0]
        self.assertIn('id="replay-events-section"', replay,
                      "ribbon section must live inside view-replay")


class PgrReviewButtonRoutingTests(unittest.TestCase):
    """Pre-S5 the Review button routed to #review which is NOT in
    VIEW_IDS (it has 'replay'). Falls back to home silently. S5 fixes
    the route + renames the sessionStorage key for consistency."""

    def test_button_routes_to_hash_replay(self):
        js = _read(LAST_MATCH_JS)
        self.assertIn('location.hash = "#replay"', js)
        # Old wire is gone.
        self.assertNotIn('location.hash = "#review"', js)

    def test_button_saves_replay_view(self):
        js = _read(LAST_MATCH_JS)
        self.assertIn('_viewSaveManual("replay")', js)
        self.assertNotIn('_viewSaveManual("review")', js)

    def test_session_storage_key_uses_replay_namespace(self):
        js = _read(LAST_MATCH_JS)
        self.assertIn('rc-replay-focus-match', js)
        # Old key removed.
        self.assertNotIn('rc-review-focus-match', js)

    def test_html_comment_refreshed(self):
        html = _read(INDEX_HTML)
        self.assertIn('rc-replay-focus-match', html)
        self.assertNotIn('rc-review-focus-match', html)


class ReplayViewAutoSelectTests(unittest.TestCase):
    """The Replay view consumes sessionStorage.rc-replay-focus-match on
    refresh to auto-select the focused match - the wire from PGR's
    Review button into the existing _replayLoadMatch."""

    def test_refresh_reads_focus_session_storage(self):
        js = _read(DEV_JS)
        refresh = js.split("function _replayViewRefresh(", 1)[1].split(
            "function _replayLoadMatch(", 1)[0]
        self.assertIn('sessionStorage.getItem("rc-replay-focus-match")', refresh)
        # Clear-on-consume so a subsequent manual click isn't shadowed.
        self.assertIn('removeItem("rc-replay-focus-match")', refresh)
        self.assertIn("_replayLoadMatch", refresh)

    def test_load_match_fires_event_ribbon(self):
        js = _read(DEV_JS)
        load = js.split("function _replayLoadMatch(", 1)[1].split(
            "function ", 1)[0]
        self.assertIn("loadReplayEvents(matchId)", load)


class ReplayEventsPanelJsTests(unittest.TestCase):
    """The replay_events.js exports the two entry points dev.js calls."""

    def test_exports_load_and_wire_helpers(self):
        js = _read(EVENTS_JS)
        self.assertIn("export function loadReplayEvents(", js)
        self.assertIn("export function wireReplayEventsOnce(", js)

    def test_dev_js_imports_helpers(self):
        js = _read(DEV_JS)
        self.assertIn("import { loadReplayEvents, wireReplayEventsOnce }", js)
        self.assertIn("from './replay_events.js'", js)

    def test_panel_persists_include_to_localstorage(self):
        """Filter checkbox state survives a reload via localStorage."""
        js = _read(EVENTS_JS)
        self.assertIn("rc-replay-events-include", js)

    def test_panel_fetches_correct_endpoint(self):
        js = _read(EVENTS_JS)
        self.assertIn("/api/replay/events?match_id=", js)


class CleanroomBoundaryTests(unittest.TestCase):
    """The league_record (GPLv3) cleanroom boundary is documented in
    ADR-009 + pointer-referenced from the panel + route modules."""

    def test_adr_009_exists(self):
        self.assertTrue(ADR_DOC.exists(),
                        "docs/adr/ADR-009-replay-events-cleanroom.md missing")

    def test_adr_009_calls_out_gpl_no_vendor(self):
        adr = _read(ADR_DOC)
        self.assertIn("league_record", adr)
        self.assertIn("GPLv3", adr)
        # Either casing of "do NOT vendor" should match. We test the
        # phrase pieces independently so future style edits don't break.
        self.assertIn("vendor", adr.lower())
        self.assertIn("do not", adr.lower())

    def test_panel_js_points_to_adr(self):
        js = _read(EVENTS_JS)
        self.assertIn("ADR-009-replay-events-cleanroom.md", js)

    def test_panel_js_warns_no_vendor(self):
        js = _read(EVENTS_JS)
        self.assertIn("do NOT vendor", js)

    def test_css_imports_panel(self):
        css = _read(DASHBOARD_CSS)
        self.assertIn("./panels/replay_events.css", css)


class AsciiHygieneTests(unittest.TestCase):
    """No em/en-dashes, smart quotes, emoji in the touched files. BAD
    dict built via chr() so this file stays clean against its own scan."""

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

    def test_events_js_is_ascii_clean(self):
        self.assertEqual([], self._scan(EVENTS_JS))

    def test_events_css_is_ascii_clean(self):
        self.assertEqual([], self._scan(EVENTS_CSS))

    def test_adr_009_is_ascii_clean(self):
        self.assertEqual([], self._scan(ADR_DOC))

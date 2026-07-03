"""RC 2.0 stage E4 - champ-select counter-picks + ban-phase collapse pins.

Structure/grep pins for the two E4 deliverables (no live engine, fast +
deterministic):

  (1) COUNTER-PICKS vs the live enemy comp - a glanceable "pick into this
      comp" list driven by the existing counters index, fetched from the
      new /api/champ-select/counter-picks route and rendered in
      champ_select.js + mounted in index.html + styled in
      champ_select_view.css.

  (2) BAN-PHASE COLLAPSE - once the ban phase is DONE the banned-champions
      display collapses (does not keep eating full vertical space during
      the pick phase). Detection is a single named helper
      (_csvBanPhaseComplete) so the collapse condition is testable.

Drift here means a half-wired surface (route without render, render without
mount, or a collapse that lost its detection helper).
"""

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CS_JS = _ROOT / "web" / "js" / "panels" / "champ_select.js"
_INDEX = _ROOT / "web" / "index.html"
_CSS = _ROOT / "web" / "css" / "panels" / "champ_select_view.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class CounterPicksFetchTests(unittest.TestCase):
    """(1a) the JS fetch helper hits the new route."""

    def test_fetch_helper_exists(self) -> None:
        js = _read(_CS_JS)
        self.assertIn("_csvFetchCounterPicks", js)

    def test_fetch_hits_counter_picks_route(self) -> None:
        js = _read(_CS_JS)
        self.assertIn("/api/champ-select/counter-picks", js)

    def test_fetch_passes_enemies_param(self) -> None:
        js = _read(_CS_JS)
        # The helper must forward the live enemy ids as the `enemies=` query
        # param (the comp the counters are computed against).
        m = re.search(r"_csvFetchCounterPicks[\s\S]{0,1200}?enemies=", js)
        self.assertIsNotNone(m, "counter-picks fetch must send enemies= param")


class CounterPicksRenderTests(unittest.TestCase):
    """(1b) the render block + its mount + style."""

    def test_render_helper_exists(self) -> None:
        js = _read(_CS_JS)
        self.assertIn("_csvRenderCounterPicks", js)

    def test_render_called_from_suggestions(self) -> None:
        js = _read(_CS_JS)
        # The counter-picks block renders as part of the SR Suggestions
        # panel pass (same place the other comp-aware cards mount). Anchor the
        # regex to `_csvRenderSuggestions(` exactly so it does not match the
        # newer `_csvRenderSuggestionsNonSr` sibling (R30) - that NonSr path
        # intentionally HIDES counter-picks.
        m = re.search(r"function _csvRenderSuggestions\([\s\S]*?\n}", js)
        self.assertIsNotNone(m)
        self.assertIn("_csvRenderCounterPicks", m.group(0))

    def test_render_resolves_live_enemy_ids(self) -> None:
        js = _read(_CS_JS)
        block = re.search(r"function _csvRenderCounterPicks[\s\S]*?\n}", js)
        self.assertIsNotNone(block)
        # Must read the live enemy comp off the session (their_team).
        self.assertIn("their_team", block.group(0))

    def test_container_mounted_in_index(self) -> None:
        html = _read(_INDEX)
        self.assertIn('id="csv-sugg-counter-picks"', html)

    def test_css_styles_counter_block(self) -> None:
        css = _read(_CSS)
        self.assertIn(".csv-counter-pick", css)


class BanPhaseCollapseTests(unittest.TestCase):
    """(2) ban-phase-complete detection + the collapse wiring."""

    def test_detection_helper_exists(self) -> None:
        js = _read(_CS_JS)
        self.assertIn("_csvBanPhaseComplete", js)

    def test_detection_reads_active_round_and_phase(self) -> None:
        js = _read(_CS_JS)
        block = re.search(r"function _csvBanPhaseComplete[\s\S]*?\n}", js)
        self.assertIsNotNone(block, "_csvBanPhaseComplete must be a function")
        body = block.group(0)
        # The detector keys off the active round type flipping to "pick"
        # and/or the LCU phase moving past BAN_PICK.
        self.assertIn("active_round", body)
        self.assertIn("BAN_PICK", body)

    def test_pickban_uses_detection_helper(self) -> None:
        # QA 2026-07-03 slice A (A2): the ghost bans grid left
        # _csvRenderSuggestions; the Pick & Ban card is the remaining
        # consumer of the ban-phase detection helper.
        js = _read(_CS_JS)
        self.assertIn("function _csvRenderPickBan", js)
        self.assertIn("_csvBanPhaseComplete", js)

    def test_collapse_class_applied(self) -> None:
        js = _read(_CS_JS)
        # The banned-list display gets a collapse class when the ban phase
        # is complete so CSS can shrink it out of the pick-phase eyeline.
        self.assertIn("is-collapsed", js)

    def test_css_collapses_banned_grid(self) -> None:
        css = _read(_CSS)
        # A rule that hides/collapses the banned display when collapsed.
        self.assertIn("is-collapsed", css)


class AsciiHygieneTests(unittest.TestCase):
    def test_touched_sources_ascii(self) -> None:
        for p in (_CS_JS, _CSS):
            data = p.read_bytes()
            bad = [i for i, b in enumerate(data) if b > 127]
            self.assertEqual(bad, [], f"{p.name} non-ASCII at {bad[:5]}")

    def test_self_is_ascii(self) -> None:
        data = Path(__file__).read_bytes()
        self.assertEqual([b for b in data if b > 127], [])


if __name__ == "__main__":
    unittest.main()

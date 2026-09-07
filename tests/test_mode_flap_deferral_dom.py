"""Regression guard for the onState->onHealth mode-flap deferral.

Bug (2026-05-17): in any non-game state where build_state preflips
``mode_key`` (ARAM/Arena lobby + champ-select) the dashboard received
two disagreeing mode authorities - onState carrying the correct preflip
``mode_key`` (e.g. "aram") and onHealth deriving "client" from a health
envelope whose preflip mirror wasn't applied (the :8891 file_ingest
mirror can fail/lag; /api/health is never mirrored). Both write
``body[data-mode]`` on independent cadences, so it flapped aram<->client
~1x/sec and every mode-gated header-row-2 pill (ds / augments / trigger
/ archetype-nudge), the mode pill, and the panel titles flickered on/off
on every view (shared header).

The fix makes ``/api/state.mode_key`` (the canonical resolver) win:
onState stamps ``state.lastStateMode`` + ts, and onHealth defers its
"client" downgrade while a recent onState asserted a preflip/in-game
mode. This is pure JS with no JS test runner in-repo, so - same pattern
as test_archetype_nudge_chip_dom - these are grep-based smoke checks
that trip if a future refactor drops the wiring.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
STATE_JS = WEB / "js" / "lib" / "state.js"
MAIN_JS = WEB / "js" / "main.js"
HEADER_CSS = WEB / "css" / "panels" / "header.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class StateJsTests(unittest.TestCase):
    """state.js must declare the two tracking fields onHealth reads."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(STATE_JS)

    def test_last_state_mode_field_declared(self) -> None:
        self.assertIn("lastStateMode:", self.text)

    def test_last_state_mode_ts_field_declared(self) -> None:
        self.assertIn("lastStateModeTs:", self.text)


class OnStateRecordsModeKeyTests(unittest.TestCase):
    """onState must stamp the mode_key + timestamp on every envelope."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(MAIN_JS)

    def test_onstate_records_last_state_mode(self) -> None:
        self.assertIn("state.lastStateMode = env.mode", self.text)

    def test_onstate_records_timestamp(self) -> None:
        self.assertIn("state.lastStateModeTs = Date.now()", self.text)


class OnHealthDeferralTests(unittest.TestCase):
    """onHealth must defer the 'client' downgrade to a recent preflip
    mode_key. We assert on the structural shape so a refactor that
    weakens any leg (the client guard, the in-game set, the staleness
    bound, or the early return) trips the test."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(MAIN_JS)

    def test_guards_on_client_tag(self) -> None:
        self.assertIn('tag === "client"', self.text)

    def test_checks_last_state_mode_is_in_game(self) -> None:
        # The deferral only fires when onState's last mode_key was a
        # real in-game / preflip tag.
        self.assertRegex(
            self.text,
            r'\["aram",\s*"arena",\s*"brawl",\s*"sr",\s*"tft"\]'
            r'\.includes\(state\.lastStateMode\)',
        )

    def test_has_staleness_bound(self) -> None:
        # Without a staleness ceiling a dead /api/state would wedge the
        # mode in-game forever; the bound lets return-to-client through.
        self.assertRegex(
            self.text,
            r"Date\.now\(\)\s*-\s*\(state\.lastStateModeTs\s*\|\|\s*0\)\)\s*<\s*8000",
        )

    def test_deferral_short_circuits_before_setmode(self) -> None:
        # The guard block must `return` before the unconditional
        # setMode(tag) so the "client" write is actually suppressed.
        # Find the deferral block and assert a `return;` precedes the
        # final setMode(tag) call.
        idx_guard = self.text.find('tag === "client"')
        idx_setmode = self.text.find("setMode(tag);", idx_guard)
        self.assertGreater(idx_guard, 0, "deferral guard not found")
        self.assertGreater(idx_setmode, idx_guard, "setMode(tag) not found after guard")
        between = self.text[idx_guard:idx_setmode]
        self.assertIn("return;", between)

    def test_deferral_logs_for_observability(self) -> None:
        # ?dbg=1 / console operators need to see the suppressed write.
        self.assertIn("mode=client(deferred", self.text)


class RowTwoPillViewGateTests(unittest.TestCase):
    """(2026-07-04) Header row 2 was removed on all pages - the four
    in-game-only row-2 pills (ds / augments / trigger / archetype-nudge)
    no longer exist, so the s150-era view-gate CSS block went with them.
    Absence guards so a merge cannot resurrect the orphaned selectors
    (4e5b2575 removed-surface precedent). The onState/onHealth deferral
    above is UNCHANGED - the mode pill + panel titles still need it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(HEADER_CSS)

    def test_view_gate_block_absent(self) -> None:
        for sel in (
            'body:not([data-view="active-match"]) header .ds-pill',
            'body:not([data-view="active-match"]) header .augments-pill',
            'body:not([data-view="active-match"]) header .trigger-pill',
            'body:not([data-view="active-match"]) header .archetype-nudge-chip',
        ):
            self.assertNotIn(sel, self.text,
                             f"orphaned row-2 view-gate selector resurrected: {sel}")

    def test_row_two_pill_classes_absent(self) -> None:
        for cls_name in (".ds-pill", ".augments-pill", ".trigger-pill",
                         ".archetype-nudge-chip"):
            self.assertNotIn(cls_name, self.text,
                             f"row-2 pill class {cls_name} resurrected in header.css")


if __name__ == "__main__":
    unittest.main()

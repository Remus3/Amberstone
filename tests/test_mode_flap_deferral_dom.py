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
    """Second half of the same bug: with the flap fixed, body[data-mode]
    is stably "aram"/"arena" during the s150 lobby/CS pre-flip (by
    design - it primes the coach panels). The four in-game-only row-2
    pills were only mode-gated (client/tft), so stable-preflip-mode
    leaked them onto every pre-game page. They must be view-gated to
    active-match ONLY (no last-match exception - operator: "only the
    active game page"), mirroring the s162 telemetry-pill view-gate."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(HEADER_CSS)

    def test_view_gate_block_present_for_all_four_pills(self) -> None:
        for sel in (
            'body:not([data-view="active-match"]) header .ds-pill',
            'body:not([data-view="active-match"]) header .augments-pill',
            'body:not([data-view="active-match"]) header .trigger-pill',
            'body:not([data-view="active-match"]) header .archetype-nudge-chip',
        ):
            self.assertIn(sel, self.text, f"missing view-gate selector: {sel}")

    def test_view_gate_is_active_match_only_not_last_match(self) -> None:
        # The four-pill block must NOT carry the :not([data-view="last-
        # match"]) exception the s162 telemetry block has - these are
        # meaningless on Post Game Review.
        idx = self.text.find(
            'body:not([data-view="active-match"]) header .ds-pill'
        )
        self.assertGreater(idx, 0)
        block = self.text[idx:idx + 400]
        self.assertNotIn('.ds-pill,\nbody:not([data-view="last-match"])', block)
        self.assertNotIn(
            'body:not([data-view="active-match"]):not([data-view="last-match"]) header .ds-pill',
            self.text,
        )

    def test_view_gate_hides_with_important(self) -> None:
        idx = self.text.find(
            'body:not([data-view="active-match"]) header .archetype-nudge-chip'
        )
        self.assertGreater(idx, 0)
        decl = self.text[idx:idx + 220]
        self.assertRegex(decl, r"display:\s*none\s*!important;")


if __name__ == "__main__":
    unittest.main()

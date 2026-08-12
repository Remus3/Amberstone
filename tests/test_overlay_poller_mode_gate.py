"""S7 overlay-poller mode-gate split guard.

The E6 poller (setupMinimapPoller in web/js/main.js) is the ONLY unconditional
in-game feed that stamps the /api/state TOP-LEVEL coaching siblings
(coach / lead_projection / callouts / liveclient) onto state.latest and renders
the four DATA-gated coaching mounts - rn-lead / rn-callouts / rn-choices /
w-spike. The :8891 WS push does not carry those siblings and the HTTP-fallback /
LCU / SSE pollers short-circuit while the WS feed is fresh, so this poll is the
sole feed in a live game.

Before S7 the poller gated everything on ["sr", "aram", "brawl"], so an in-game
ARENA or TFT overlay never fed the four coaching mounts and they stayed dark.
The fix is a TWO-GATE split:
  * NARROW gate ["sr", "aram", "brawl"]: the minimap surfaces (minimap_rect /
    minimap_dots / zoi + renderMinimapRect / renderMinimapZoi). Arena + TFT have
    no minimap ZOI, so these must NOT widen - the minimap renderers must never
    start firing off-mode.
  * WIDER gate ["sr", "aram", "brawl", "arena", "tft"]: the coaching siblings +
    renderLead / renderCallouts / renderCoachChoices / renderSpikeCue.

These source-pin assertions (regex/index over the poller IIFE body, mirroring
tests/test_overlay_route_smoke.py) pin the split so a re-merge back to one gate,
or a minimap renderer leaking into the arena/tft block, goes red in CI instead
of dark (or double-firing) in-game. main.js is a side-effectful boot module and
the poller is a non-exported IIFE, so a source-pin is the strongest headless
proof available - no jsdom in the tree; the .mjs suites only cover exported
pure logic.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MAIN_JS = REPO / "web" / "js" / "main.js"

NARROW_GATE = '["sr", "aram", "brawl"].includes(st.mode_key)'
WIDE_GATE = '["sr", "aram", "brawl", "arena", "tft"].includes(st.mode_key)'

# The PAINTING call sites specifically. 2026-07-20: the poller also calls both
# renderers with an explicit null on the clear-on-exit path (the stale-box fix,
# tests/test_overlay_minimap_clear_on_exit.py) - a null call hides the widget,
# it never paints off-mode, so the "exactly once" pin keys off the data-bearing
# argument rather than the bare renderer name.
MINIMAP_RENDERERS = (
    "renderMinimapRect(state.latest.minimap_rect)",
    "renderMinimapZoi(state.latest.zoi)",
)
COACHING_RENDERERS = (
    "renderLead(st)",
    "renderCallouts(st)",
    "renderCoachChoices(st)",
    # Riot compliance 2026-08-11: renderSpikeCue was removed from this poller
    # with the w-spike cue itself (banned power-spike notification).
)
MINIMAP_STAMPS = (
    "state.latest.minimap_rect = st.minimap_rect",
    "state.latest.minimap_dots = st.minimap_dots",
)
COACHING_STAMPS = (
    "state.latest.lead_projection = st.lead_projection",
    "state.latest.callouts = st.callouts",
    "state.latest.coach = st.coach",
)


def _poller_region() -> str:
    """Slice out the setupMinimapPoller IIFE body (up to the next IIFE)."""
    js = MAIN_JS.read_text(encoding="utf-8")
    start = js.index("function setupMinimapPoller")
    end = js.index("function setupVoiceToggle", start)
    return js[start:end]


class PollerRegionTests(unittest.TestCase):
    """The poller IIFE must still exist - it is the sole in-game coaching feed."""

    def test_poller_region_is_findable(self):
        region = _poller_region()
        self.assertIn("pollMinimap", region)
        self.assertGreater(len(region), 200)


class TwoGateSplitTests(unittest.TestCase):
    """Both gates present exactly once, narrow first, wider second."""

    def setUp(self):
        self.region = _poller_region()

    def test_narrow_minimap_gate_present_once(self):
        # The narrow literal ends in "]" right after "brawl", so it does NOT
        # substring-match inside the wider literal (which has a comma there).
        self.assertEqual(
            1, self.region.count(NARROW_GATE),
            "expected exactly one narrow ['sr','aram','brawl'] gate in poller",
        )

    def test_wide_coaching_gate_present_once(self):
        self.assertEqual(
            1, self.region.count(WIDE_GATE),
            "expected exactly one wider ['sr','aram','brawl','arena','tft'] "
            "gate in poller - the coaching-mount feed must cover arena + tft",
        )

    def test_narrow_gate_precedes_wide_gate(self):
        self.assertLess(
            self.region.index(NARROW_GATE), self.region.index(WIDE_GATE),
            "minimap (narrow) block must come before the coaching (wider) block",
        )


class MinimapStaysNarrowTests(unittest.TestCase):
    """The minimap renderers + stamps must stay SR/ARAM/brawl-only. If either
    renderer moved past the wider gate it would start firing for arena/tft,
    which have no minimap - a regression."""

    def setUp(self):
        self.region = _poller_region()
        self.wide_idx = self.region.index(WIDE_GATE)
        self.narrow_idx = self.region.index(NARROW_GATE)

    def test_minimap_renderers_appear_once_in_narrow_block(self):
        for token in MINIMAP_RENDERERS:
            with self.subTest(token=token):
                self.assertEqual(
                    1, self.region.count(token),
                    f"{token} must appear exactly once (narrow block only)",
                )
                idx = self.region.index(token)
                self.assertGreater(idx, self.narrow_idx)
                self.assertLess(
                    idx, self.wide_idx,
                    f"{token} leaked past the wider gate - would fire on "
                    "arena/tft which have no minimap",
                )

    def test_minimap_stamps_live_in_narrow_block(self):
        for token in MINIMAP_STAMPS:
            with self.subTest(token=token):
                idx = self.region.index(token)
                self.assertGreater(idx, self.narrow_idx)
                self.assertLess(idx, self.wide_idx)


class CoachingWidenedTests(unittest.TestCase):
    """The four coaching renderers + their sibling stamps must sit in the
    wider block so an in-game arena/tft overlay feeds them."""

    def setUp(self):
        self.region = _poller_region()
        self.wide_idx = self.region.index(WIDE_GATE)

    def test_coaching_renderers_are_in_wider_block(self):
        for token in COACHING_RENDERERS:
            with self.subTest(token=token):
                self.assertIn(token, self.region)
                self.assertGreater(
                    self.region.index(token), self.wide_idx,
                    f"{token} must live under the arena/tft-inclusive gate",
                )

    def test_coaching_stamps_are_in_wider_block(self):
        for token in COACHING_STAMPS:
            with self.subTest(token=token):
                self.assertIn(token, self.region)
                self.assertGreater(self.region.index(token), self.wide_idx)


# NOTE: no whole-file ASCII check on main.js - it carries accepted non-ASCII
# box-draw dividers (U+2500 "--" section rules) + a section sign repo-wide, so
# tests/test_overlay_route_smoke.py deliberately ASCII-checks overlay.css /
# overlay_pulse.js / overlay_state.js and NOT main.js. The S7 edit itself is
# pure ASCII (verified) and precommit_gate.py enforces banned-glyph hygiene on
# staged lines at commit time.


if __name__ == "__main__":
    unittest.main()

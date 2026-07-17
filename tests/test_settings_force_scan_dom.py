"""Regression guards for RC2 P3.5 - the Settings force-scan control.

Overlay item 4 Section B (docs/specs/2026-07-11-overlay-item4-client-settings-reorg-design.md
-> "Coaching actions (not needed / not required)") REMOVED the COACHING
ACTIONS card - and with it the "Force vision scan" button - from the Settings
view. This is a VISUAL removal, not a feature rip-out: the dev.js wiring and
the POST /api/command {command: "force_vision"} backend route are intentionally
left intact (guarded by `if (fsBtn)`), so the command path survives for a
possible future re-surfacing and DevJsWiringTests / HeaderCssTests below still
pass. IndexHtmlTests now guards the REMOVAL from #settings-body.

Grep-based smoke checks - same shape as test_screen_read_dom.py.
"""
from __future__ import annotations

import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
INDEX = WEB / "index.html"
DEV = WEB / "js" / "panels" / "dev.js"
HEADER_CSS = WEB / "css" / "panels" / "header.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class IndexHtmlTests(unittest.TestCase):
    """Item 4 Section B: the COACHING ACTIONS card + force-scan button are
    removed from the Settings surface. Guard the removal so the card is not
    re-added without an explicit design decision."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.t = _read(INDEX)

    def test_coaching_actions_card_removed(self) -> None:
        self.assertNotIn("COACHING ACTIONS", self.t)

    def test_force_scan_button_removed(self) -> None:
        self.assertNotIn('id="set-force-scan-btn"', self.t)
        self.assertNotIn('id="set-force-scan-status"', self.t)


class DevJsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.t = _read(DEV)

    def test_posts_force_vision_command(self) -> None:
        self.assertIn('"/api/command"', self.t)
        self.assertIn('command: "force_vision"', self.t)

    def test_binds_the_button(self) -> None:
        self.assertIn('"set-force-scan-btn"', self.t)

    def test_token_header_aware(self) -> None:
        # Mirrors the screen_read / loop-control token pattern.
        self.assertIn("rc_dash_token", self.t)

    def test_ascii_only(self) -> None:
        # Scoped to the P3.5-authored block - dev.js at large carries
        # pre-existing functional box-drawing / middot glyphs (NOT in the
        # banned set: em/en-dash + smart quotes only) whose presence is
        # out of this task's scope.
        start = self.t.index("// COACHING ACTIONS (RC2 P3.5)")
        self.t[start:start + 1400].encode("ascii")


class HeaderCssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.t = _read(HEADER_CSS)

    def test_action_button_style_present(self) -> None:
        self.assertIn(".set-action-btn", self.t)

    def test_hit_target_floor(self) -> None:
        # The button must carry the --hit-min fingertip floor in its block.
        i = self.t.index(".set-action-btn")
        self.assertIn("--hit-min", self.t[i:i + 240])


if __name__ == "__main__":
    unittest.main()

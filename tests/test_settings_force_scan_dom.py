"""Regression guards for RC2 P3.5 - the Settings-without-hotkeys surface.

The one action that used to require a hotkey (Ctrl+Tab -> forced coach
vision scan, core/hotkeys.py) now has a no-hotkey UI control on the
Settings view. The backend route already existed
(POST /api/command {command: "force_vision"} -> dashboard/_writers.py
force_vision_scan); the live dashboard had simply dropped the button the
legacy dashboard carried (web/legacy_index.html btn-scan).

Four-surface wiring that makes the control usable:

  - web/index.html declares a COACHING ACTIONS settings card with the
    "Force vision scan" button + a status span, inside #settings-body
  - web/js/panels/dev.js _settingsRefresh wires the button to POST the
    force_vision command (token-header aware, cooldown-guarded)
  - web/css/panels/header.css carries the .set-action-btn style at the
    --hit-min fingertip floor

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
    @classmethod
    def setUpClass(cls) -> None:
        cls.t = _read(INDEX)

    def test_card_and_button_declared(self) -> None:
        self.assertIn("COACHING ACTIONS", self.t)
        self.assertIn('id="set-force-scan-btn"', self.t)
        self.assertIn('id="set-force-scan-status"', self.t)

    def test_button_lives_in_settings_body(self) -> None:
        body = self.t.index('id="settings-body"')
        # The settings view ends where the replay view section begins.
        replay = self.t.index('id="view-replay"')
        btn = self.t.index('id="set-force-scan-btn"')
        self.assertTrue(body < btn < replay)

    def test_no_hotkey_note_present(self) -> None:
        # The surface's whole point: reachable WITHOUT the Ctrl+Tab hotkey.
        self.assertIn("Ctrl+Tab", self.t)

    def test_button_is_a_real_button(self) -> None:
        i = self.t.index('id="set-force-scan-btn"')
        # Look back a little for the opening tag.
        self.assertIn("<button", self.t[i - 60:i + 20])


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

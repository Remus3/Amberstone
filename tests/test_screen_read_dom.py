"""Regression guards for the s240 on-demand VLM coach frontend wiring
(AUTONOMOUS_AUDIT opportunity #3).

The backend is covered by test_screen_read.py. NOT covered there is the
four-surface wiring that makes the feature usable:

  - web/index.html declares the SCREEN READ button + dedicated pill
    inside the RIGHT NOW panel
  - web/js/panels/screen_read.js exports renderScreenRead + POSTs the
    screen_read command + dedups on a signature
  - web/js/main.js imports it and calls renderScreenRead(st) at the
    SAME three /api/state consumption points as renderArchetypeNudge
  - web/css/panels/right_now.css carries the .rn-sr-* styles

An ESM split / render refactor / CSS purge that drops one of these
would silently break the feature. Grep-based smoke checks - cheap,
fast, enough to catch a missing wire. Same shape as the s239
test_personal_record_dom.py guard.
"""
from __future__ import annotations

import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
INDEX = WEB / "index.html"
PANEL = WEB / "js" / "panels" / "screen_read.js"
MAIN = WEB / "js" / "main.js"
RN_CSS = WEB / "css" / "panels" / "right_now.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class IndexHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.t = _read(INDEX)

    def test_button_and_pill_declared(self) -> None:
        self.assertIn('id="rn-sr-btn"', self.t)
        self.assertIn('id="rn-sr-pill"', self.t)

    def test_pill_hidden_by_default(self) -> None:
        # Pill must start hidden - it only appears once triggered.
        i = self.t.index('id="rn-sr-pill"')
        self.assertIn("hidden", self.t[i:i + 120])

    def test_lives_in_right_now_panel(self) -> None:
        rn = self.t.index('id="right-now"')
        nxt = self.t.index('id="next"')
        self.assertTrue(rn < self.t.index('id="rn-sr-btn"') < nxt)


class PanelJsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.t = _read(PANEL)

    def test_exports_render(self) -> None:
        self.assertIn("export function renderScreenRead(", self.t)

    def test_posts_screen_read_command(self) -> None:
        self.assertIn('"/api/command"', self.t)
        self.assertIn('command: "screen_read"', self.t)

    def test_signature_dedupe(self) -> None:
        self.assertIn("_lastSig", self.t)

    def test_status_branches_present(self) -> None:
        for s in ('"pending"', '"ok"', "is-error", "is-pending", "is-ok"):
            self.assertIn(s, self.t)

    def test_error_code_mapping(self) -> None:
        for code in ("no_fresh_frame", "no_api_key", "vision_failed"):
            self.assertIn(code, self.t)

    def test_ascii_only(self) -> None:
        # s239 lesson - authored frontend content is 7-bit ASCII.
        self.t.encode("ascii")


class MainJsWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.t = _read(MAIN)

    def test_imports_panel(self) -> None:
        self.assertIn(
            "import { renderScreenRead } from './panels/screen_read.js';",
            self.t)

    def test_three_callsites_cover_state_consumers(self) -> None:
        # The feature must render at every /api/state consumption point
        # (SSE / HTTP fallback / LCU poller) - otherwise the pill goes
        # stale on whichever path is live. Assert >= the 3 known
        # callsites, parity vs renderTeamContext (the canonical sibling;
        # the old renderArchetypeNudge comparator was retired with
        # header row 2, 2026-07-04).
        n_sr = self.t.count("renderScreenRead(st)")
        n_tc = self.t.count("renderTeamContext(st)")
        self.assertGreaterEqual(n_sr, 3)
        self.assertEqual(n_sr, n_tc)


class RightNowCssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.t = _read(RN_CSS)

    def test_styles_present(self) -> None:
        for sel in (".rn-screenread", ".rn-sr-btn", ".rn-sr-pill",
                    ".rn-sr-pill.is-error", ".rn-sr-pill.is-pending"):
            self.assertIn(sel, self.t)

    def test_s240_block_is_ascii(self) -> None:
        # Scoped to the s240-authored block - the file at large carries
        # pre-existing legacy non-ASCII whose purge is a separate
        # operator-gated pass (CLAUDE.md), out of this task's scope.
        start = self.t.index("/* s240 - on-demand VLM coach.")
        self.t[start:].encode("ascii")


if __name__ == "__main__":
    unittest.main()

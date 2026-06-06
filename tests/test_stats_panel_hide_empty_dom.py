"""DOM-contract tests for the in-game STATS empty-row hider (item 281).

Cheap grep-style smoke. Mirrors test_callouts_panel_dom.py - regexes the
right_now.js SOURCE via pathlib + unittest. The in-game renderStats(p)
shows ~60 metric rows, most with no live producer, painting a wall of "-"
mid-game. A post-setv pass hides any .stats-row whose value is an empty
sentinel and collapses a group whose rows are all hidden. These tests pin
that the hide-empty helper exists, is scoped to STATS groups, references
the "-" and "- / -" sentinels, toggles display, and is wired into
renderStats - plus ASCII hygiene on the file (hard rule).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PANEL_JS = REPO / "web" / "js" / "panels" / "right_now.js"


class HideEmptyHelperTests(unittest.TestCase):
    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_helper_defined(self):
        # A dedicated empty-row hider exists (function declaration).
        self.assertRegex(self.js, r"function\s+_hideEmptyStatRows\s*\(")

    def test_scopes_to_stats_group_rows(self):
        # Strictly queries STATS-group rows, not .stats-row app-wide.
        self.assertIn(".stats-group .stats-row", self.js)

    def test_references_both_sentinels(self):
        # Both the plain "-" and the cannon "- / -" sentinels are handled.
        self.assertIn('"- / -"', self.js)
        self.assertIn('"-"', self.js)

    def test_toggles_display_none_and_shown(self):
        # Hides via display none and restores via empty string (no innerHTML).
        self.assertIn('display = "none"', self.js)
        self.assertIn('display = ""', self.js)

    def test_collapses_empty_group_title(self):
        # An all-hidden group also hides its section header (no orphan title).
        self.assertIn("stats-group-title", self.js)

    def test_helper_invoked_in_renderStats(self):
        # The hider runs at the END of renderStats, after the setv calls.
        rs = re.search(
            r"function\s+renderStats\s*\([^)]*\)\s*\{(.*?)\n\}",
            self.js,
            re.DOTALL,
        )
        self.assertIsNotNone(rs, "renderStats body not found")
        body = rs.group(1)
        self.assertIn("_hideEmptyStatRows(", body)
        # Invocation comes after the first setv call (post-population pass).
        self.assertLess(body.index("setv("), body.index("_hideEmptyStatRows("))


class AsciiHygieneTests(unittest.TestCase):
    """No em/en-dash, no smart quotes in right_now.js (hard rule).

    NOTE: right_now.js legitimately carries coach/UI glyphs (warn/check/
    arrow priority marks, the middle-dot row separator, box-drawing in
    comments, the U+2212 minus sign). Those are pre-existing functional
    content, not banned. The enforceable hard rule is no em/en-dashes and
    no smart quotes - asserting zero non-ASCII bytes would falsely flag
    those glyphs, so we check the banned set instead.
    """

    BAD = {
        chr(0x2013): "en-dash",
        chr(0x2014): "em-dash",
        chr(0x2018): "left smart quote",
        chr(0x2019): "right smart quote",
        chr(0x201C): "left smart dq",
        chr(0x201D): "right smart dq",
    }

    def test_panel_js_no_banned_chars(self):
        text = PANEL_JS.read_text(encoding="utf-8")
        for ch, name in self.BAD.items():
            self.assertNotIn(ch, text, f"{name} in right_now.js")


if __name__ == "__main__":
    unittest.main()

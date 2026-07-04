"""DELETION GUARD (DOM) for the OQ13 weekly digest card (HOME_QA C2).

The QA ruling removed the "THIS WEEK by mode" card from the home view: the
`#home-weekly-digest` DOM node + `#home-weekly-digest-body`, the
`_homeRenderWeeklyDigest` render fn + its wiring, and the
`.home-weekly-digest*` CSS block are all gone. This was the DOM-contract
test for that card; per the LEDGER 766 champ-select precedent it is
converted to a deletion guard that FAILS if any of those symbols reappear.

ASCII-only authored content (CLAUDE.md hard rule).
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN_JS = ROOT / "web" / "js" / "main.js"
HOME_CSS = ROOT / "web" / "css" / "panels" / "home.css"
INDEX_HTML = ROOT / "web" / "index.html"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class HtmlCardRemovedTests(unittest.TestCase):
    def test_card_dom_removed(self):
        html = _read(INDEX_HTML)
        self.assertNotIn('id="home-weekly-digest"', html,
                         "index.html still carries the weekly-digest card")
        self.assertNotIn('id="home-weekly-digest-body"', html,
                         "index.html still carries the digest body node")


class MainJsRendererRemovedTests(unittest.TestCase):
    def test_renderer_removed(self):
        js = _read(MAIN_JS)
        self.assertNotIn("function _homeRenderWeeklyDigest", js,
                         "main.js still defines _homeRenderWeeklyDigest")
        self.assertNotIn("_homeRenderWeeklyDigest(", js,
                         "main.js still calls _homeRenderWeeklyDigest")


class HomeCssRemovedTests(unittest.TestCase):
    def test_css_block_removed(self):
        css = _read(HOME_CSS)
        # The OQ13 slice B live rules are gone (a HOME_QA breadcrumb comment
        # naming the removed selectors may remain, but no live rule may).
        self.assertNotIn(".home-weekly-digest {", css)
        self.assertNotIn(".home-weekly-digest-head", css)
        self.assertNotIn("#home-weekly-digest-body", css)


class AsciiHygieneTests(unittest.TestCase):
    """No em/en-dashes or smart quotes in this guard file."""

    BAD = {
        chr(0x2013): "EN DASH",
        chr(0x2014): "EM DASH",
        chr(0x2018): "LEFT SINGLE QUOTE",
        chr(0x2019): "RIGHT SINGLE QUOTE",
        chr(0x201C): "LEFT DOUBLE QUOTE",
        chr(0x201D): "RIGHT DOUBLE QUOTE",
    }

    def test_guard_file_is_ascii_clean(self):
        text = Path(__file__).read_text(encoding="utf-8")
        offenders = [name for ch, name in self.BAD.items() if ch in text]
        self.assertEqual([], offenders, f"non-ASCII glyphs: {offenders}")


if __name__ == "__main__":
    unittest.main()

"""Absence guard: the shared header has exactly ONE row on all pages.

Operator round-2 ruling (2026-07-04): "the 2nd row of the main UI on all
pages can be dropped and empty its contents". Row 2 (HP/MP bar groups,
gold pill, augments pill, DS pill, archetype-nudge chip, trigger pill)
was dead vertical chrome on the companion surface - the in-game surface
is the ?overlay=1 HUD, which display:none's the WHOLE header anyway
(web/css/overlay.css body[data-shell="overlay"] header).

Guards (4e5b2575 removed-surface precedent):
  - index.html header carries exactly one .header-row and no
    .header-row-2 marker or row-2 element ids.
  - The retired FE pollers are gone (trigger_pill.js 2Hz
    /api/decisions/heartbeat poll must not restart).

Backends are intentionally untouched: /api/decisions/heartbeat,
/api/archetype-nudge/dismiss and the archetype_nudge + aug_reco fields
in /api/state all remain (covered by their own suites).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
INDEX_HTML = WEB / "index.html"

_ROW2_IDS = (
    'id="hp-group"', 'id="hp-bar-vis"', 'id="hp-bar-fill"', 'id="hp-bar"',
    'id="mp-group"', 'id="mp-bar-vis"', 'id="mp-bar-fill"', 'id="mp-bar"',
    'id="gold-pill"', 'id="gold-val"',
    'id="augments-pill"',
    'id="ds-pill"',
    'id="archetype-nudge-chip"',
    'id="trigger-pill"',
)


class HeaderSingleRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = INDEX_HTML.read_text(encoding="utf-8")

    def test_exactly_one_header_row(self) -> None:
        header = self.text.split("<header>", 1)[1].split("</header>", 1)[0]
        rows = re.findall(r'class="header-row\b', header)
        self.assertEqual(
            len(rows), 1,
            f"header must carry exactly ONE .header-row, found {len(rows)}")

    def test_no_header_row_2_marker(self) -> None:
        self.assertNotIn("header-row-2", self.text)

    def test_no_row_two_element_ids(self) -> None:
        for needle in _ROW2_IDS:
            self.assertNotIn(
                needle, self.text,
                f"retired row-2 element {needle} resurrected in index.html")


class RetiredModuleTests(unittest.TestCase):
    def test_trigger_pill_module_gone(self) -> None:
        self.assertFalse(
            (WEB / "js" / "panels" / "trigger_pill.js").exists(),
            "trigger_pill.js (2Hz heartbeat poller) must stay retired")

    def test_archetype_nudge_chip_module_gone(self) -> None:
        self.assertFalse(
            (WEB / "js" / "panels" / "archetype_nudge_chip.js").exists(),
            "archetype_nudge_chip.js must stay retired")

    def test_main_js_imports_gone(self) -> None:
        main_js = (WEB / "js" / "main.js").read_text(encoding="utf-8")
        self.assertNotIn("trigger_pill.js", main_js)
        self.assertNotIn("archetype_nudge_chip.js", main_js)


if __name__ == "__main__":
    unittest.main()

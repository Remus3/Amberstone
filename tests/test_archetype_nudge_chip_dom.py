"""Absence guards for the retired s184.1 archetype-nudge chip surface.

Header row 2 was dropped on all pages 2026-07-04 (operator round-2
ruling: dead chrome on the companion; in-game glances live on the
?overlay=1 HUD, which display:none's the whole header). The chip's
RENDER surface went with it:

  - web/index.html no longer declares the chip element
  - web/js/panels/archetype_nudge_chip.js was deleted
  - web/js/main.js no longer imports/calls renderArchetypeNudge
  - web/css/panels/map_state.css no longer carries the chip styles

The s184 BACKEND is untouched and stays covered elsewhere
(test_archetype_mismatch + test_routes_archetype_nudge +
test_state_builder_archetype_nudge): /api/state.archetype_nudge is
still stamped and POST /api/archetype-nudge/dismiss still exists.

These guards follow the 4e5b2575 orphan-cleanup precedent: a removed
surface converts its wiring pins into absence pins so a partial revert
(e.g. a merge resurrecting the CSS block or the dead import) trips CI.
"""
from __future__ import annotations

import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
INDEX_HTML = WEB / "index.html"
PANEL_JS = WEB / "js" / "panels" / "archetype_nudge_chip.js"
MAIN_JS = WEB / "js" / "main.js"
MAP_CSS = WEB / "css" / "panels" / "map_state.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class IndexHtmlAbsenceTests(unittest.TestCase):
    """The chip element must NOT come back to index.html."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(INDEX_HTML)

    def test_chip_element_absent(self) -> None:
        self.assertNotIn('id="archetype-nudge-chip"', self.text)
        self.assertNotIn('class="archetype-nudge-chip"', self.text)

    def test_chip_sub_elements_absent(self) -> None:
        self.assertNotIn('id="archetype-nudge-chip-text"', self.text)
        self.assertNotIn('id="archetype-nudge-chip-x"', self.text)


class PanelJsAbsenceTests(unittest.TestCase):
    """The panel module file was deleted with the surface."""

    def test_module_file_deleted(self) -> None:
        self.assertFalse(
            PANEL_JS.exists(),
            "archetype_nudge_chip.js was retired with header row 2 - "
            "a resurrected module needs a new render surface first")


class MainJsAbsenceTests(unittest.TestCase):
    """main.js must not import or call the retired renderer."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(MAIN_JS)

    def test_import_absent(self) -> None:
        self.assertNotIn("panels/archetype_nudge_chip.js", self.text)

    def test_callsites_absent(self) -> None:
        self.assertNotIn("renderArchetypeNudge", self.text)


class CssAbsenceTests(unittest.TestCase):
    """map_state.css must not re-grow the chip style blocks."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _read(MAP_CSS)

    def test_chip_rules_absent(self) -> None:
        self.assertNotIn(".archetype-nudge-chip {", self.text)
        self.assertNotIn(".archetype-nudge-chip-x {", self.text)
        self.assertNotIn(".archetype-nudge-chip[hidden]", self.text)


if __name__ == "__main__":
    unittest.main()

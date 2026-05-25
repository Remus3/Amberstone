"""Item 185 Slice A: Page #3 Replay flex-allocation re-tune.

Item 184 carry (b) (item 162 carry c): the 10-row participant table
collapsed to ~0 visible rows when the 15-event timeline ribbon
saturated `.replay-events-list { max-height: 480px }`. The flex-
allocation edge surfaced after the v2.1 typography migration bumped
champ-icon 28 -> 38 + item-icon 22 -> 30 + row min-height -> --hit-min
(42px) per items 159 + 182.

Item 185 fix:
- `.replay-grid-wrap` gains `min-height: 360px` so the participant
  grid always shows ~6-7 rows even when the timeline ribbon is at
  saturation. flex: 1 still grows the grid when the timeline is
  short.
- `.replay-events-list max-height` 480 -> 320 to leave room for the
  grid + matches a more realistic 9-10-event visible window with
  scroll for the long tail.

If a future maintainer reverts either declaration these grep pins
catch it before the flex-allocation edge re-surfaces.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIMITIVES_CSS = ROOT / "web" / "css" / "panels" / "primitives.css"
EVENTS_CSS     = ROOT / "web" / "css" / "panels" / "replay_events.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class ReplayGridWrapMinHeightTests(unittest.TestCase):
    """`.replay-grid-wrap` carries a min-height floor so 6+ participant
    rows stay visible even when the timeline ribbon saturates."""

    def test_grid_wrap_has_min_height_floor(self):
        css = _read(PRIMITIVES_CSS)
        idx = css.find(".replay-grid-wrap")
        self.assertGreater(idx, 0, ".replay-grid-wrap selector must exist")
        block_end = css.find("}", idx)
        self.assertGreater(block_end, idx)
        block = css[idx:block_end]
        self.assertIn("min-height: 360px", block)

    def test_grid_wrap_keeps_flex_grow(self):
        css = _read(PRIMITIVES_CSS)
        idx = css.find(".replay-grid-wrap")
        block_end = css.find("}", idx)
        block = css[idx:block_end]
        self.assertIn("flex: 1", block)
        self.assertIn("overflow: auto", block)


class ReplayEventsListMaxHeightTests(unittest.TestCase):
    """`.replay-events-list` max-height capped at 320px (was 480) so
    the timeline ribbon does not crowd out the participant grid in
    the ~780px replay-main-pane viewport."""

    def test_events_list_max_height_is_320(self):
        css = _read(EVENTS_CSS)
        idx = css.find(".replay-events-list")
        self.assertGreater(idx, 0, ".replay-events-list selector must exist")
        block_end = css.find("}", idx)
        block = css[idx:block_end]
        self.assertIn("max-height: 320px", block)
        self.assertNotIn("max-height: 480px", block)

    def test_events_list_keeps_vertical_scroll(self):
        css = _read(EVENTS_CSS)
        idx = css.find(".replay-events-list")
        block_end = css.find("}", idx)
        block = css[idx:block_end]
        self.assertIn("overflow-y: auto", block)


class AsciiHygieneTests(unittest.TestCase):
    """Item 185 Slice A CSS edits introduce 0 non-ASCII bytes."""

    def test_primitives_css_ascii_clean_on_edited_block(self):
        css = _read(PRIMITIVES_CSS)
        idx = css.find(".replay-grid-wrap")
        block_end = css.find("}", idx)
        block = css[idx:block_end + 1]
        for ch in block:
            self.assertLess(ord(ch), 128, f"non-ASCII byte in .replay-grid-wrap block: U+{ord(ch):04X}")

    def test_events_css_ascii_clean_on_edited_block(self):
        css = _read(EVENTS_CSS)
        idx = css.find(".replay-events-list")
        block_end = css.find("}", idx)
        block = css[idx:block_end + 1]
        for ch in block:
            self.assertLess(ord(ch), 128, f"non-ASCII byte in .replay-events-list block: U+{ord(ch):04X}")


if __name__ == "__main__":
    unittest.main()

"""Overlay widget fixed-size + on-screen-fit guard (operator 2026-06-29).

Three in-game overlay reports, one root cause cluster:
  1. the #ovset Opacity slider "can not be adjusted - clicking does nothing":
     the w-ovds settings widget was 822px tall anchored at y=780, so the slider
     (content-offset ~286px) rendered at y~1066 - BELOW the 1080 viewport, i.e.
     off-screen / unclickable.
  2. "the widgets keep shifting slightly every match": .ovx-widget was
     width:fit-content, so per-match content (champion names, item rows, CS/KDA,
     callout text) resized the box.
  3. "fixed maximum panel size: not changing sizes": no height bound, so the
     build module (891px) + settings (822px) spilled off-screen.

Fix (grep-locked here; the live render is proven by the snapshot_panels
Playwright sibling): .ovx-widget gets a FIXED width (var --ovx-w, default 210)
instead of fit-content, and a max-height (var --ovx-maxh) that overlay_layout
._applyPos sets = (viewport bottom - the widget anchor) with overflow-y:auto, so
no widget runs past the screen bottom; the w-ovds default is repositioned onto
the screen.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OVERLAY_CSS = REPO / "web" / "css" / "overlay.css"
LAYOUT_JS = REPO / "web" / "js" / "lib" / "overlay_layout.js"


class FixedWidth(unittest.TestCase):
    def setUp(self):
        self.css = OVERLAY_CSS.read_text(encoding="utf-8")

    def test_width_is_fixed_var_not_fit_content(self):
        # The .ovx-widget rule uses a fixed width var, not content-driven sizing.
        self.assertIn("width: var(--ovx-w", self.css)

    def test_no_fit_content_width_on_widget(self):
        # Guard the regression: the old width:fit-content is gone from the rule.
        block = self.css[self.css.index(".ovx-widget {"):]
        block = block[: block.index("}")]
        self.assertNotIn("fit-content", block,
                         "ovx-widget width must not be fit-content (it shifts)")


class CappedHeight(unittest.TestCase):
    def setUp(self):
        self.css = OVERLAY_CSS.read_text(encoding="utf-8")
        self.js = LAYOUT_JS.read_text(encoding="utf-8")

    def test_css_max_height_var(self):
        self.assertIn("max-height: var(--ovx-maxh", self.css)

    def test_css_overflow_scrolls(self):
        self.assertIn("overflow-y: auto", self.css)

    def test_applypos_sets_maxh_from_viewport(self):
        # _applyPos derives --ovx-maxh from the viewport height minus the anchor.
        body = self.js[self.js.index("function _applyPos"):]
        body = body[: body.index("\nfunction ", 1)]
        self.assertIn("--ovx-maxh", body)
        self.assertIn("innerHeight", body)


class SettingsWidgetOnScreen(unittest.TestCase):
    def test_w_ovds_default_y_on_screen(self):
        # The w-ovds (settings + fight-model) default must anchor high enough that
        # its controls (the opacity slider) sit on a 1080 screen, not at y=780.
        js = LAYOUT_JS.read_text(encoding="utf-8")
        m = re.search(r'id:\s*"w-ovds".*?y:\s*(\d+)', js)
        self.assertIsNotNone(m, "w-ovds registry entry not found")
        self.assertLessEqual(int(m.group(1)), 300,
                             "w-ovds default y too low - its slider falls off-screen")


if __name__ == "__main__":
    unittest.main()

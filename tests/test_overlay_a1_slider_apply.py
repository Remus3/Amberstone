"""A1 (OVERLAY_BUILD_MASTER_PLAN WP-A1): the overlay opacity + per-panel scale
sliders must move pixels in a plain browser, not only inside the Electron shell.

Break-points fixed:
  U1.1 #ovset-opacity had NO page-side consumer - writeOverlaySettings now also
       sets the --rc-overlay-opacity CSS var on <body> (gated on !window.rcShell
       so the Electron window-opacity authority in rc-shell/src/main.js does not
       double-dim), and overlay.css consumes it on body[data-shell="overlay"].
  U1.3 per-panel scale used transform:scale, which does NOT change the layout
       box, so a scaled-up panel clipped against the 210px slot (overflow:hidden
       clips pre-transform). overlay.css now drives scale via `zoom`
       (layout-affecting) so the slot grows with scale.
  U1.2 launcher reachability is already wired (the launcher gets data-rc-zone and
       [data-rc-zone] is in the rc-shell ZONE_SELECTOR) - guarded here so a
       future edit cannot silently strip it.

Grep-style contract test, mirroring tests/test_overlay_settings_panel_dom.py:
pathlib reads + substring/regex asserts, no DOM emulation (there is no jsdom/node
harness for web/js page code; the rc-shell node tests cover the shell half).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HELPER_JS = REPO / "web" / "js" / "lib" / "overlay_settings.js"
OVERLAY_CSS = REPO / "web" / "css" / "overlay.css"
LAYOUT_JS = REPO / "web" / "js" / "lib" / "overlay_layout.js"


class GlobalOpacityAppliesPageSide(unittest.TestCase):
    """U1.1: the global opacity slider dims the overlay in a plain browser."""

    def setUp(self):
        self.helper = HELPER_JS.read_text(encoding="utf-8")
        self.css = OVERLAY_CSS.read_text(encoding="utf-8")

    def test_writeoverlaysettings_sets_the_body_css_var(self):
        # writeOverlaySettings applies the resolved opacity page-side as a CSS var
        # so a plain-browser preview (no Electron window opacity) actually dims.
        self.assertIn("--rc-overlay-opacity", self.helper)
        self.assertIn("setProperty", self.helper)

    def test_page_side_apply_is_gated_off_inside_rcshell(self):
        # Inside the Electron shell, overlayWindow.setOpacity is the authority
        # (rc-shell/src/main.js applyOverlayOpacity); the page-side var must be
        # gated so it never double-dims. The gate keys on the bridge being absent.
        self.assertIn("!window.rcShell", self.helper)

    def test_overlay_css_consumes_the_opacity_var(self):
        m = re.search(
            r'body\[data-shell="overlay"\]\s*\{[^}]*var\(--rc-overlay-opacity',
            self.css,
            re.DOTALL,
        )
        self.assertIsNotNone(
            m, "body[data-shell=overlay] must consume var(--rc-overlay-opacity ...)"
        )


class PerPanelScaleIsLayoutAffecting(unittest.TestCase):
    """U1.3: scaling a panel must grow its slot, not clip against 210px."""

    def setUp(self):
        self.css = OVERLAY_CSS.read_text(encoding="utf-8")

    def test_scale_drives_zoom_not_transform(self):
        # zoom changes the used layout box (no clip); transform:scale does not.
        self.assertIn("zoom: var(--ovx-scale", self.css)

    def test_scale_does_not_use_transform_scale(self):
        self.assertNotIn("transform: scale(var(--ovx-scale", self.css)


class LauncherReachabilityGuard(unittest.TestCase):
    """U1.2 (regression lock): the launcher stays a click-through zone so it is
    reachable mid-game in PASSIVE without the global ACTIVE hotkey."""

    def setUp(self):
        self.layout = LAYOUT_JS.read_text(encoding="utf-8")

    def test_launcher_id_and_zone(self):
        self.assertIn('"#w-launcher"', self.layout)
        # the launcher mount opts into the generic [data-rc-zone] hover hook.
        m = re.search(
            r'el\.id = "w-launcher".*?setAttribute\("data-rc-zone"',
            self.layout,
            re.DOTALL,
        )
        self.assertIsNotNone(
            m, "the launcher mount must set data-rc-zone for PASSIVE reachability"
        )


class ScaledPanelPositionIsZoomCompensated(unittest.TestCase):
    """Item 9 (2026-07-11): `zoom: var(--ovx-scale)` scales a FIXED panel's
    top/left/bottom by the scale too (empirically: zoom:0.5 renders top:500 at
    viewport 250), so a scaled-down panel's position collapses toward the
    top-left and it can no longer be dragged to the screen bottom (operator: the
    draggable 'floor' shifted up with scale). The applied position must be divided
    by the panel scale so the panel lands where dropped at any scale; size stays
    zoom-scaled so the panel still shrinks. _scalePos(v, 1) == v keeps every
    existing unscaled panel untouched (zero regression).
    """

    def setUp(self):
        self.layout = LAYOUT_JS.read_text(encoding="utf-8")

    def test_scale_compensation_helper_defined(self):
        self.assertIn("function _scalePos(", self.layout)

    def test_apply_pos_compensates_both_anchors_for_scale(self):
        body = self.layout.split("function _applyPos(")[1].split("\nfunction ")[0]
        # bottom-anchor (left, bottom) + top-anchor (left, top) = at least 4
        # position values routed through the scale-compensating helper.
        self.assertGreaterEqual(
            body.count("_scalePos("), 4,
            "_applyPos must divide left/top/bottom by the panel scale so a "
            "scaled panel stays reachable to the screen edges")

    def test_drag_move_compensates_for_scale(self):
        body = self.layout.split("function _installDrag(")[1].split(
            "\nfunction ")[0]
        self.assertIn(
            "_scalePos(", body,
            "the live drag must track 1:1 for a scaled panel (divide by scale)")


class AsciiTests(unittest.TestCase):
    def _assert_ascii(self, path: Path):
        data = path.read_bytes()
        bad = [(i, b) for i, b in enumerate(data) if b > 0x7F]
        self.assertEqual(bad[:5], [], f"non-ASCII bytes in {path.name}")

    def test_helper_ascii(self):
        self._assert_ascii(HELPER_JS)

    def test_overlay_css_ascii(self):
        self._assert_ascii(OVERLAY_CSS)

    def test_this_file_ascii(self):
        self._assert_ascii(Path(__file__).resolve())


if __name__ == "__main__":
    unittest.main()

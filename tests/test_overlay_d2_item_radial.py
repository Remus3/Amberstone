"""D2 (OVERLAY_BUILD_MASTER_PLAN WP-D2): right-click radial 5-action menu on
build-module item icons.

Right-clicking any build-module item icon opens a 5-wedge radial (modeled on the
champ_select trade popup singleton at champ_select.js:303 + champ_select_view.css
:864) with the operator-brief actions: N=Build-Earlier, E=Build-Later,
S=Defer-Once, W=Keep, center=Silence (Kurtenbach - the 4 ordering actions on the
high-accuracy cardinal axes, Silence on the center so a sloppy flick cannot mute
by accident). Each action writes the planner's per-item override store (in-memory,
per-match); the LIVE row re-renders applying the shifts so a reorder survives the
4s rerank tick. D3 makes the SERVER replan honor + persist these + adds the reset
control - D2 ships the radial + store + client-side application.

Coexistence (overlay_layout.js:241 _installHideMenu is ACTIVE-gated contextmenu
hide; active_match.js META strip contextmenu = _cycleMeta): the icon-level
contextmenu must preventDefault + stopPropagation so the radial neither dismisses
the overlay (ACTIVE) nor cycles the META archetype.

Grep-style contract test (no jsdom/node harness), mirroring
tests/test_overlay_d1_item_tooltip.py. Semantics of applyItemOverrides are proven
by a node ESM probe + the Playwright UI-audit at build time, not here.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ACTIVE_MATCH_JS = REPO / "web" / "js" / "panels" / "active_match.js"
RADIAL_JS = REPO / "web" / "js" / "lib" / "overlay_item_radial.js"
OVERRIDES_JS = REPO / "web" / "js" / "lib" / "item_overrides.js"

_ACTIONS = ("earlier", "later", "defer", "keep", "silence")


class RadialModuleExists(unittest.TestCase):
    def setUp(self):
        self.js = RADIAL_JS.read_text(encoding="utf-8")

    def test_module_present(self):
        self.assertTrue(RADIAL_JS.is_file(), "overlay_item_radial.js missing")

    def test_install_export(self):
        self.assertIn("export function installItemRadial", self.js)

    def test_singleton_on_html(self):
        self.assertIn("documentElement.appendChild", self.js)

    def test_five_actions_present(self):
        # Each wedge carries a data-action set from the _WEDGES action strings.
        self.assertIn('setAttribute("data-action"', self.js.replace("'", '"'))
        for a in _ACTIONS:
            self.assertIn(f'"{a}"', self.js, f"radial action {a} missing")

    def test_outside_click_dismiss(self):
        # A document-level click listener closes the open radial.
        self.assertIn("document.addEventListener", self.js)


class RadialCoexistence(unittest.TestCase):
    def setUp(self):
        self.js = RADIAL_JS.read_text(encoding="utf-8")

    def test_contextmenu_guarded(self):
        # preventDefault + stopPropagation so the radial neither hides the
        # overlay (ACTIVE _installHideMenu) nor cycles META (_cycleMeta).
        self.assertIn("contextmenu", self.js)
        self.assertIn("preventDefault", self.js)
        self.assertIn("stopPropagation", self.js)

    def test_body_zoom_aware(self):
        self.assertIn("getBoundingClientRect", self.js)
        self.assertIn("zoom", self.js)


class OverrideStore(unittest.TestCase):
    def setUp(self):
        self.js = OVERRIDES_JS.read_text(encoding="utf-8")

    def test_store_exported(self):
        self.assertIn("export const ITEM_OVERRIDES", self.js)

    def test_action_setters_exported(self):
        for fn in ("buildEarlier", "buildLater", "deferItem", "keepItem",
                   "silenceItem"):
            self.assertIn(f"export function {fn}", self.js,
                          f"{fn} setter not exported")

    def test_apply_exported(self):
        # The pure reorder the LIVE render runs so a shift survives a rerank.
        self.assertIn("export function applyItemOverrides", self.js)

    def test_clear_exported(self):
        # D3's reset control + game-end clear hook both call this.
        self.assertIn("export function clearItemOverrides", self.js)


class RadialWiring(unittest.TestCase):
    def setUp(self):
        self.js = ACTIVE_MATCH_JS.read_text(encoding="utf-8")

    def test_imports(self):
        self.assertIn("overlay_item_radial.js", self.js)
        self.assertIn("installItemRadial", self.js)
        self.assertIn("item_overrides.js", self.js)
        self.assertIn("applyItemOverrides", self.js)

    def test_radial_wired_into_dsicon(self):
        start = self.js.index("function _dsIcon")
        nxt = self.js.index("\nfunction ", start + 1)
        self.assertIn("installItemRadial", self.js[start:nxt],
                      "installItemRadial not called inside _dsIcon")

    def test_overrides_applied_in_render(self):
        start = self.js.index("function _renderAmBuildBody")
        nxt = self.js.index("\nfunction ", start + 1)
        self.assertIn("applyItemOverrides", self.js[start:nxt],
                      "applyItemOverrides not used in _renderAmBuildBody")


class OverlayInteractivity(unittest.TestCase):
    """The radial must be reachable + clickable in the in-game overlay widget
    (rc-shell click-through). clickthrough_zones.js ZONE_SELECTOR makes any
    [data-rc-zone] element flip the window interactive on hover, so both the
    LIVE strip (to open the radial) and the radial itself (to click a wedge)
    must carry data-rc-zone."""

    def test_radial_is_zone(self):
        self.assertIn("data-rc-zone", RADIAL_JS.read_text(encoding="utf-8"))

    def test_live_strip_is_zone(self):
        js = ACTIVE_MATCH_JS.read_text(encoding="utf-8")
        self.assertIn('strip.setAttribute("data-rc-zone"', js,
                      "LIVE strip must be a data-rc-zone for the overlay radial")

    def test_zone_selector_covers_data_rc_zone(self):
        # Anti-drift: the rc-shell zone selector must still include the generic
        # [data-rc-zone] hook the radial + LIVE strip rely on.
        cz = (REPO / "rc-shell" / "src" / "clickthrough_zones.js").read_text(
            encoding="utf-8")
        self.assertIn("[data-rc-zone]", cz)


class AsciiHygiene(unittest.TestCase):
    def test_authored_files_ascii(self):
        for p in (RADIAL_JS, OVERRIDES_JS, Path(__file__)):
            raw = p.read_bytes()
            for i, b in enumerate(raw):
                self.assertLess(b, 0x80,
                                f"{p.name} non-ASCII byte 0x{b:02x} at offset {i}")


if __name__ == "__main__":
    unittest.main()

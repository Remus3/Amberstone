"""D3 (OVERLAY_BUILD_MASTER_PLAN WP-D3): "reset item status" control + the
game-end clear of the per-match item-override store.

D2 shipped the right-click radial + the in-memory override store
(web/js/lib/item_overrides.js: shift / defer / keep / silence). D3 adds an
on-screen "Reset item status" button to the overlay #ovset settings strip
(web/js/panels/overlay_ds_controls.js) that wipes that store and emits one
overlay action-log line (action: "reset-item-status"), plus a between-games
clear so the store does not leak overrides from the previous game into the
next champ-select / game. The reset control reuses the already-audited
.ovset-act class so the UI-audit hit-floor / typography pass by construction.

Grep-style contract test (no jsdom/node harness), mirroring
tests/test_overlay_d2_item_radial.py + test_overlay_settings_panel_dom.py:
pathlib reads + substring/regex asserts only.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PANEL_JS = REPO / "web" / "js" / "panels" / "overlay_ds_controls.js"
PANEL_CSS = REPO / "web" / "css" / "panels" / "overlay_ds_controls.css"
ACTIVE_MATCH_JS = REPO / "web" / "js" / "panels" / "active_match.js"


class ResetControlPresent(unittest.TestCase):
    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_button_id_present(self):
        self.assertIn('id="ovset-reset-items"', self.js)

    def test_reuses_audited_act_class(self):
        # The new button reuses the already-audited .ovset-act class so the
        # hit-floor + typography pass without new CSS.
        self.assertIn("ovset-act", self.js)

    def test_label_present(self):
        self.assertIn("Reset item status", self.js)


class ResetControlWired(unittest.TestCase):
    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_imports_clear_from_overrides_module(self):
        self.assertIn("clearItemOverrides", self.js)
        self.assertIn("../lib/item_overrides.js", self.js)

    def test_click_clears_store_and_emits_action(self):
        # The button calls clearItemOverrides() then fires one overlay ACTION.
        self.assertIn("clearItemOverrides(", self.js)
        self.assertIn("sendOverlayAction(", self.js)
        self.assertIn('action: "reset-item-status"', self.js)


class GameEndClearsOverrides(unittest.TestCase):
    def setUp(self):
        self.js = ACTIVE_MATCH_JS.read_text(encoding="utf-8")

    def test_import_extends_overrides_module(self):
        # The existing item_overrides.js import now also pulls clearItemOverrides
        # alongside applyItemOverrides.
        m = re.search(
            r"import\s*\{([^}]*)\}\s*from\s*'\.\./lib/item_overrides\.js'", self.js
        )
        self.assertIsNotNone(m, "item_overrides.js import line not found")
        names = m.group(1)
        self.assertIn("applyItemOverrides", names)
        self.assertIn("clearItemOverrides", names)

    def test_clear_called_inside_render(self):
        # The between-games clear lives in renderActiveMatch (the !isLive path).
        start = self.js.index("function renderActiveMatch")
        self.assertIn("clearItemOverrides(", self.js[start:],
                      "clearItemOverrides not called inside renderActiveMatch")


class ResetReusesAuditedClass(unittest.TestCase):
    def setUp(self):
        self.panel = PANEL_JS.read_text(encoding="utf-8")
        self.css = PANEL_CSS.read_text(encoding="utf-8")

    def test_button_uses_act_class(self):
        self.assertIn("ovset-act", self.panel)

    def test_act_meets_hit_floor(self):
        # The audited .ovset-act block carries the --hit-min game-distance floor;
        # the reset button inherits it (no new CSS). Mirrors the D2 sibling regex.
        m = re.search(
            r"\.ovset-act\s*\{[^}]*min-height:\s*var\(--hit-min", self.css, re.DOTALL
        )
        self.assertIsNotNone(m, ".ovset-act must set min-height: var(--hit-min ...)")


class AsciiHygiene(unittest.TestCase):
    """Repo hard rule: authored bytes stay 7-bit ASCII (no em/en dashes, no
    smart quotes). Byte-level on the touched + new files."""

    def test_authored_files_ascii(self):
        for p in (PANEL_JS, ACTIVE_MATCH_JS, Path(__file__)):
            raw = p.read_bytes()
            for i, b in enumerate(raw):
                self.assertLess(b, 0x80,
                                f"{p.name} non-ASCII byte 0x{b:02x} at offset {i}")


if __name__ == "__main__":
    unittest.main()

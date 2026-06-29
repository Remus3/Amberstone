"""D1 (OVERLAY_BUILD_MASTER_PLAN WP-D1): hover tooltip on build-module item icons.

A native-feel custom tooltip (the page has only `title=` attrs today) that shows
an item's name + stats + passive on hover of any build-module icon. Content is
pulled from the `/api/dictionary/items` DDragon dict already fetched by
items_index.js (B3 reads the same dict for ITEM_RECIPES) - no new server route,
no extra round trip.

Doctrine (master plan WP-D1 + overlay_layout body-zoom caveat):
  - Singleton element appended to <html> (dodges body `zoom`, mirrors the
    champ_select trade popup at champ_select.js:303).
  - Show delay 300-500ms after the cursor settles; immediate (<=100ms) hover
    highlight; hide grace ~0.5s; pointer-events:none so it never traps the
    cursor / never shows with nothing under it.
  - Anchors toward the screen edge, expanding away from the play area.
  - Name 16px bold; stats / passive body 13px.

Grep-style contract test (no jsdom/node harness for page code), mirroring
tests/test_overlay_b3_row_item_semantics.py. The live render is proven by the
Playwright UI-audit ritual, not here.

Blast-radius guard: _defIcon (THREATS/DEFENSE) keeps its own `title=` reason -
the tooltip wiring is the _dsIcon (build-module) path only.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ACTIVE_MATCH_JS = REPO / "web" / "js" / "panels" / "active_match.js"
ITEMS_INDEX_JS = REPO / "web" / "js" / "lib" / "items_index.js"
TOOLTIP_JS = REPO / "web" / "js" / "lib" / "overlay_tooltip.js"


def _deficon_slice(js: str) -> str:
    start = js.index("function _defIcon")
    nxt = js.index("\nfunction ", start + 1)
    return js[start:nxt]


class TooltipModuleExists(unittest.TestCase):
    def setUp(self):
        self.js = TOOLTIP_JS.read_text(encoding="utf-8")

    def test_module_present(self):
        self.assertTrue(TOOLTIP_JS.is_file(), "overlay_tooltip.js missing")

    def test_install_export(self):
        # The public entry point the build module wires onto each icon.
        self.assertIn("export function installItemTooltip", self.js)

    def test_singleton_on_html(self):
        # Appended to <html> (zoom:1), not body - the champ_select.js:303 trick.
        self.assertIn("documentElement.appendChild", self.js)

    def test_tip_never_traps_cursor(self):
        # pointer-events:none -> the tip can never sit under the cursor and
        # block a hover / show with nothing beneath it.
        self.assertIn("pointer-events:none", self.js.replace(" ", ""))


class TooltipTimingDoctrine(unittest.TestCase):
    def setUp(self):
        self.js = TOOLTIP_JS.read_text(encoding="utf-8")

    def test_show_delay_in_window(self):
        m = re.search(r"SHOW_DELAY\s*=\s*(\d+)", self.js)
        self.assertIsNotNone(m, "SHOW_DELAY constant missing")
        self.assertTrue(300 <= int(m.group(1)) <= 500,
                        f"SHOW_DELAY {m.group(1)} outside 300-500ms doctrine")

    def test_hide_grace_present(self):
        m = re.search(r"HIDE_GRACE\s*=\s*(\d+)", self.js)
        self.assertIsNotNone(m, "HIDE_GRACE constant missing")
        self.assertTrue(400 <= int(m.group(1)) <= 600,
                        f"HIDE_GRACE {m.group(1)} not ~0.5s")

    def test_deferred_show(self):
        self.assertIn("setTimeout", self.js)

    def test_immediate_highlight(self):
        # An <=100ms hover affordance applied synchronously on mouseenter,
        # before the deferred tooltip fires.
        self.assertIn("boxShadow", self.js)


class TooltipAnchoring(unittest.TestCase):
    def setUp(self):
        self.js = TOOLTIP_JS.read_text(encoding="utf-8")

    def test_measures_anchor(self):
        self.assertIn("getBoundingClientRect", self.js)

    def test_edge_aware(self):
        # Side chosen off the viewport half so the tip expands away from the
        # play area / minimap, then clamps to the viewport.
        self.assertIn("innerWidth", self.js)

    def test_body_zoom_correction(self):
        # Mirrors overlay_layout._bodyZoom / champ_select popup: correct for the
        # dashboard body zoom so the fixed tip lines up + matches visual size.
        self.assertIn("zoom", self.js)

    def test_font_sizes(self):
        self.assertIn("16px", self.js)  # name, bold
        self.assertIn("13px", self.js)  # stats / passive body


class TooltipContentFromDict(unittest.TestCase):
    def setUp(self):
        self.js = TOOLTIP_JS.read_text(encoding="utf-8")
        self.idx = ITEMS_INDEX_JS.read_text(encoding="utf-8")

    def test_details_store_exported(self):
        self.assertIn("export const ITEM_DETAILS", self.idx)

    def test_parser_exported(self):
        self.assertIn("export function parseItemTooltip", self.idx)

    def test_details_from_same_dict(self):
        # Populated off the SAME /api/dictionary/items loader B3 already runs.
        self.assertIn("/api/dictionary/items", self.idx)
        self.assertIn("ITEM_DETAILS.byId", self.idx)

    def test_parser_emits_name_stats_passive(self):
        # The three content channels the acceptance names.
        self.assertIn("name", self.idx)
        self.assertIn("stats", self.idx)
        self.assertIn("passive", self.idx)

    def test_parser_reads_ddragon_tags(self):
        # Parses the DDragon description HTML (<stats>...</stats> + passive prose).
        self.assertIn("<stats>", self.idx)

    def test_tooltip_consumes_details(self):
        self.assertIn("ITEM_DETAILS", self.js)
        self.assertIn("parseItemTooltip", self.js)


class TooltipWiring(unittest.TestCase):
    def setUp(self):
        self.js = ACTIVE_MATCH_JS.read_text(encoding="utf-8")

    def test_import(self):
        self.assertIn("installItemTooltip", self.js)
        self.assertIn("overlay_tooltip.js", self.js)

    def test_wired_into_dsicon(self):
        # The call lives inside the _dsIcon body (build-module icons).
        start = self.js.index("function _dsIcon")
        nxt = self.js.index("\nfunction ", start + 1)
        self.assertIn("installItemTooltip", self.js[start:nxt],
                      "installItemTooltip not called inside _dsIcon")


class BlastRadius(unittest.TestCase):
    """_defIcon keeps its own title reason - tooltip wiring is _dsIcon-only."""

    def setUp(self):
        self.js = ACTIVE_MATCH_JS.read_text(encoding="utf-8")

    def test_deficon_keeps_title_reason(self):
        sl = _deficon_slice(self.js)
        self.assertIn("rec.reason", sl)
        self.assertNotIn("installItemTooltip", sl)


class AsciiHygiene(unittest.TestCase):
    def test_authored_files_ascii(self):
        for p in (TOOLTIP_JS, Path(__file__)):
            raw = p.read_bytes()
            for i, b in enumerate(raw):
                self.assertLess(b, 0x80,
                                f"{p.name} non-ASCII byte 0x{b:02x} at offset {i}")


if __name__ == "__main__":
    unittest.main()

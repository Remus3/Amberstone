"""B3 (OVERLAY_BUILD_MASTER_PLAN WP-B3): Live row + Meta row item semantics.

Builds on the B2 3-row module:
  - Row1 LIVE + Row2 META: owned items render GREYED (.bm-owned, redundant-coded
    per WCAG 1.4.1 = opacity/grayscale + a check glyph + sorted-left position),
    the first non-grey icon is flagged "next".
  - Partial-component awareness: owning a component of a planned item renders a
    pip (.bm-pip) + a fractional ring (.bm-ring), computed client-side from the
    /api/dictionary/items recipe `from`-graph (items_index.js ITEM_RECIPES +
    componentProgress).
  - Row2 META + Row3 ULTIMATE always fetch /api/build-order with the server-
    default scorer (archetype: ""); the old right-click archetype cycle was
    removed (LEDGER 823) so operators cannot switch the in-game archetype.

Grep-style contract test (no jsdom/node harness for page code), mirroring
tests/test_overlay_b2_three_row_build_module.

Blast-radius guard: the THREATS/DEFENSE _defIcon must KEEP its OWNED badge - only
the build-module rows (the _dsIcon bm callers) switch to greying.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ACTIVE_MATCH_JS = REPO / "web" / "js" / "panels" / "active_match.js"
ITEMS_INDEX_JS = REPO / "web" / "js" / "lib" / "items_index.js"
BUILD_MODULE_CSS = REPO / "web" / "css" / "panels" / "build_module.css"


def _deficon_slice(js: str) -> str:
    """The body of _defIcon (THREATS/DEFENSE icon) - from its def to the next
    top-level function, so the blast-radius guard inspects ONLY that function."""
    start = js.index("function _defIcon")
    nxt = js.index("\nfunction ", start + 1)
    return js[start:nxt]


class OwnedGreying(unittest.TestCase):
    def setUp(self):
        self.js = ACTIVE_MATCH_JS.read_text(encoding="utf-8")

    def test_bm_owned_class(self):
        self.assertIn("bm-owned", self.js)

    def test_dsicon_takes_bm_opt(self):
        # _dsIcon gains an opt-in bm flag (the greying path is bm-only).
        self.assertIn("opts.bm", self.js)

    def test_redundant_check_glyph(self):
        # Greying is redundant-coded beyond opacity (WCAG 1.4.1).
        self.assertIn("bm-check", self.js)

    def test_next_flag(self):
        self.assertIn("bm-next", self.js)

    def test_owned_partition_helper(self):
        # Stable owned-first partition (sort-left) anchored to a real symbol.
        self.assertIn("_bmPartitionOwned", self.js)


class DefenseIconUntouched(unittest.TestCase):
    """THREATS/DEFENSE icons keep their OWNED badge - greying is bm-rows only."""

    def setUp(self):
        self.js = ACTIVE_MATCH_JS.read_text(encoding="utf-8")

    def test_def_icon_keeps_owned_badge(self):
        self.assertIn("OWNED", _deficon_slice(self.js))


class PartialComponent(unittest.TestCase):
    def setUp(self):
        self.js = ACTIVE_MATCH_JS.read_text(encoding="utf-8")
        self.idx = ITEMS_INDEX_JS.read_text(encoding="utf-8")
        self.css = BUILD_MODULE_CSS.read_text(encoding="utf-8")

    def test_recipe_loader(self):
        self.assertIn("ITEM_RECIPES", self.idx)
        self.assertIn("/api/dictionary/items", self.idx)

    def test_component_progress_export(self):
        self.assertIn("export function componentProgress", self.idx)

    def test_pip_and_ring_render(self):
        self.assertIn("bm-pip", self.js)
        self.assertIn("bm-ring", self.js)

    def test_ring_css(self):
        self.assertIn(".bm-ring", self.css)
        self.assertIn("conic-gradient", self.css)
        self.assertIn("--ring-pct", self.css)

    def test_pip_css(self):
        self.assertIn(".bm-pip", self.css)


class MetaAltCycleRemoved(unittest.TestCase):
    """LEDGER 823: the Row2 META right-click archetype-cycle was removed. Both
    the Meta and Ultimate rows now always request the server-default scorer
    (archetype: ""), matching the champ-select preview + the coach. This class
    is the anti-regression tripwire against the cycle being re-introduced."""

    def setUp(self):
        self.js = ACTIVE_MATCH_JS.read_text(encoding="utf-8")

    def test_meta_cycle_state_removed(self):
        # The _BM_META / metaIndex / _cycleMeta / ring machinery is gone.
        self.assertNotIn("_BM_META", self.js)
        self.assertNotIn("metaIndex", self.js)
        self.assertNotIn("_cycleMeta", self.js)

    def test_build_order_sends_default_archetype(self):
        # The build-order + ultimate fetches still send an archetype field,
        # now hard-pinned to "" so the server resolves the kit-axis default.
        self.assertIn('archetype: ""', self.js)

    def test_meta_strip_still_a_zone(self):
        # The strip stays an in-game clickable zone - the item-override radial
        # still lives on it (installItemRadial); only the archetype cycle went.
        self.assertIn("data-rc-zone", self.js)
        self.assertIn("installItemRadial", self.js)


class BuildModuleCssB3(unittest.TestCase):
    def setUp(self):
        self.css = BUILD_MODULE_CSS.read_text(encoding="utf-8")

    def test_owned_css(self):
        self.assertIn(".bm-owned", self.css)
        self.assertIn("grayscale", self.css)
        self.assertIn("opacity", self.css)

    def test_next_css(self):
        self.assertIn(".bm-next", self.css)


if __name__ == "__main__":
    unittest.main()

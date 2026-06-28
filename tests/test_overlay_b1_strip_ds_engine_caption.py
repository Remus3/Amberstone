"""B1 (OVERLAY_BUILD_MASTER_PLAN WP-B1): strip the DS ENGINE context caption +
the "no draft prior" empty-state from the in-game build pane.

Acceptance (plan WP-B1 + Section B intro):
  1. The in-game build pane (active_match.js `_renderAmBuildBody`) no longer
     renders the `DS ENGINE - vs <armor> - <mr> - <hp> - live - <n> enemies`
     caption header, nor the bare "DS ENGINE" empty-pane placeholder label.
  2. target_stats STILL flows to the adaptive module (Section C) - the
     `_dsTargetStatsCaption()` function is KEPT and still feeds the render
     signature (so enemy-itemization shifts still refresh the pane); only the
     visible caption render is removed.
  3. The draft-elo chip's "no draft prior" string is gone (the `de-empty` mount
     class stays - draft_elo.css + test_draft_elo_panel pin it).

Scope note (recorded): the plan also cited `build_order.js:136-140` (ctxLine) as
a "sibling caption", but that "DS vs Enemy Comp" card renders in CHAMP-SELECT
(champ_select.js imports buildOrderCardHtml), not the in-game build pane - it is
outside B1's stated "in-game build pane" goal and champ-select is settled-complete,
so it is intentionally left untouched here.

Grep-style contract test (no jsdom/node harness for page code), mirroring
tests/test_overlay_a5_enemy_spells_unname_widen.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ACTIVE_MATCH_JS = REPO / "web" / "js" / "panels" / "active_match.js"
DRAFT_ELO_JS = REPO / "web" / "js" / "panels" / "draft_elo.js"
DRAFT_ELO_CSS = REPO / "web" / "css" / "panels" / "draft_elo.css"


class DsEngineCaptionRemoved(unittest.TestCase):
    """No "DS ENGINE" branding renders in the in-game build pane."""

    def setUp(self):
        self.js = ACTIVE_MATCH_JS.read_text(encoding="utf-8")

    def test_no_ds_engine_literal(self):
        # Covers both the `DS ENGINE - ${caption}` header and the bare
        # "DS ENGINE" empty-pane placeholder label.
        self.assertNotIn("DS ENGINE", self.js)


class TargetStatsStillFlows(unittest.TestCase):
    """The caption function is kept + still feeds the render sig (Section C)."""

    def setUp(self):
        self.js = ACTIVE_MATCH_JS.read_text(encoding="utf-8")

    def test_caption_function_kept(self):
        self.assertIn("function _dsTargetStatsCaption", self.js)

    def test_caption_still_feeds_signature(self):
        # The sig still calls it, so target_stats changes still refresh the
        # pane even though the caption is no longer rendered.
        self.assertIn("_dsTargetStatsCaption()", self.js)

    def test_build_icons_still_render(self):
        # The DS pick icon strip is untouched - only the caption header is gone.
        self.assertIn("_dsIcon(", self.js)


class NoDraftPriorRemoved(unittest.TestCase):
    """The draft-elo chip no longer shows "no draft prior"."""

    def setUp(self):
        self.js = DRAFT_ELO_JS.read_text(encoding="utf-8")

    def test_no_draft_prior_string_gone(self):
        self.assertNotIn("no draft prior", self.js)

    def test_de_empty_class_kept(self):
        # The empty-state mount class stays (draft_elo.css + the panel test
        # pin it); only the prose inside is removed.
        self.assertIn("de-empty", self.js)

    def test_empty_chip_hidden_in_css(self):
        # Removing the text alone would leave a dimmed empty pill (the chip has
        # padding + bg + border); the empty-state chip is hidden outright.
        css = DRAFT_ELO_CSS.read_text(encoding="utf-8")
        m = re.search(
            r'\.draft-elo-chip\[data-de-state="empty"\][^{]*\{[^}]*'
            r"display:\s*none", css)
        self.assertIsNotNone(m, "empty draft-elo chip must be display:none")


if __name__ == "__main__":
    unittest.main()

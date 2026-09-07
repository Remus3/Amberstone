"""B2 (OVERLAY_BUILD_MASTER_PLAN WP-B2): horizontal 3-row build module scaffold.

Replaces the vertical in-game build list (active_match.js _renderAmBuildBody)
with a horizontal 3-row module:
  Row1 .bm-live  - iterative live plan (fed by /api/build-plan, WP-C5).
  Row2 .bm-meta  - static standard build (fed by /api/build-order order[]).
  Row3 .bm-knobs - the DS fight-model knobs (armor/MR/budget/fight-length),
                   reusing the ds_knobs.js /api/ds-knobs data layer.

Acceptance (plan WP-B2):
  - Module renders 3 horizontal rows (.bm-live, .bm-meta, .bm-knobs) under one
    .bm-module container.
  - Row1 + Row2 are horizontal item strips (.bm-strip, display:flex).
  - Row3 carries the armor/MR/budget/fight-length knobs.
  - The new web/css/panels/build_module.css is @imported in dashboard.css
    (the panel-import parity guard, test_dashboard_css_panel_imports_parity).

Grep-style contract test (no jsdom/node harness for page code), mirroring
tests/test_overlay_b1_strip_ds_engine_caption.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ACTIVE_MATCH_JS = REPO / "web" / "js" / "panels" / "active_match.js"
BUILD_MODULE_CSS = REPO / "web" / "css" / "panels" / "build_module.css"
DASHBOARD_CSS = REPO / "web" / "css" / "dashboard.css"


class ThreeRowModule(unittest.TestCase):
    """_renderAmBuildBody builds the named-row module container.

    BATCH A (aab70b67, 2026-07-06) dropped the FIGHT MODEL knob row from the
    build module per the operator EXAMPLE (the full knobs card still lives at
    csv-ds-knobs), so the module is now the "Daemon Slayer" + "Meta Build"
    named rows. The former test_knobs_row assertion on bm-knobs was retired
    with that redesign.
    """

    def setUp(self):
        self.js = ACTIVE_MATCH_JS.read_text(encoding="utf-8")

    def test_module_container(self):
        self.assertIn("bm-module", self.js)

    def test_live_row(self):
        self.assertIn("bm-live", self.js)

    def test_meta_row(self):
        self.assertIn("bm-meta", self.js)

    def test_horizontal_strip_class(self):
        # Row1 + Row2 are horizontal item strips.
        self.assertIn("bm-strip", self.js)


class RowFeeds(unittest.TestCase):
    """Each row pulls from its data source."""

    def setUp(self):
        self.js = ACTIVE_MATCH_JS.read_text(encoding="utf-8")

    def test_live_row_uses_build_plan(self):
        # Row1 keeps the WP-C5 live-plan feed (already wired).
        self.assertIn("_maybeRefreshBuildPlan", self.js)

    def test_meta_row_fetches_build_order(self):
        # Row2 standard build comes from /api/build-order order[].
        self.assertIn("/api/build-order", self.js)

    def test_knobs_row_reuses_ds_knobs(self):
        # Row3 reuses the ds_knobs.js /api/ds-knobs data layer, NOT a 2nd engine.
        self.assertIn("ds_knobs.js", self.js)
        self.assertIn("fetchDsKnobs", self.js)


class KnobsCarried(unittest.TestCase):
    """Row3 carries the four DS fight-model knobs."""

    def setUp(self):
        self.js = ACTIVE_MATCH_JS.read_text(encoding="utf-8")

    def test_four_knob_inputs(self):
        for knob_id in ("bm-armor", "bm-mr", "bm-budget", "bm-fight"):
            self.assertIn(knob_id, self.js, f"missing knob input id {knob_id}")


class BuildModuleCss(unittest.TestCase):
    """The new panel stylesheet exists, is horizontal, and is @imported."""

    def test_css_file_exists(self):
        self.assertTrue(BUILD_MODULE_CSS.is_file(),
                        "web/css/panels/build_module.css missing")

    def test_strip_is_flex(self):
        css = BUILD_MODULE_CSS.read_text(encoding="utf-8")
        self.assertIn(".bm-strip", css)
        self.assertIn("flex", css)

    def test_imported_in_dashboard_css(self):
        # Panel-import parity guard requires the @import.
        self.assertIn("build_module.css",
                      DASHBOARD_CSS.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

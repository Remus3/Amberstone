"""Overlay item 8 Phase 3: the rank-tier benchmark selector + its sync.

benchmarkRankTier is first-class in the shared overlay-settings helper
(web/js/lib/overlay_settings.js) and mirrors BOTH ways to the existing
rc-pgr-rank-tier key that PGR + desktop Settings already share; a same-origin
event repaints the stats panel in-window. The selector (and the relocated
compare-role override) live in the DS Settings strip
(web/js/panels/overlay_ds_controls.js).

Grep-style (pathlib reads + substring/regex asserts, no DOM emulation).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HELPER = REPO / "web" / "js" / "lib" / "overlay_settings.js"
DS_PANEL = REPO / "web" / "js" / "panels" / "overlay_ds_controls.js"
DS_CSS = REPO / "web" / "css" / "panels" / "overlay_ds_controls.css"

_TIERS = ("iron", "bronze", "silver", "gold", "platinum",
          "emerald", "diamond", "master", "grandmaster", "challenger")


class HelperFirstClass(unittest.TestCase):
    def setUp(self):
        self.js = HELPER.read_text(encoding="utf-8")

    def test_benchmark_rank_tier_default_field(self):
        self.assertIn("benchmarkRankTier", self.js)
        self.assertIn("roleOverride", self.js)

    def test_shared_key_and_event_exported(self):
        self.assertIn('PGR_RANK_KEY = "rc-pgr-rank-tier"', self.js)
        self.assertIn("RANK_TIER_EVENT", self.js)

    def test_dedicated_read_write_helpers(self):
        self.assertIn("export function readBenchmarkRankTier", self.js)
        self.assertIn("export function writeBenchmarkRankTier", self.js)
        self.assertIn("export function readRoleOverride", self.js)
        self.assertIn("export function writeRoleOverride", self.js)

    def test_mirrors_both_ways(self):
        # write path mirrors into the shared PGR key ...
        self.assertRegex(self.js, r"localStorage\.setItem\(\s*PGR_RANK_KEY")
        # ... and the read path prefers the shared PGR key (single source).
        self.assertIn("_readPgrRank", self.js)

    def test_fires_same_origin_event(self):
        self.assertRegex(self.js, r"dispatchEvent\(\s*new Event\(\s*RANK_TIER_EVENT")

    def test_all_ten_tiers_validated(self):
        for t in _TIERS:
            self.assertIn(f'"{t}"', self.js)


class DsSettingsControls(unittest.TestCase):
    def setUp(self):
        self.js = DS_PANEL.read_text(encoding="utf-8")

    def test_rank_and_role_selects_present(self):
        self.assertIn('id="ovset-rank-tier"', self.js)
        self.assertIn('id="ovset-role"', self.js)

    def test_uses_select_elements(self):
        self.assertIn("<select", self.js)

    def test_rank_options_cover_all_tiers(self):
        for t in _TIERS:
            self.assertIn(f'"{t}"', self.js)

    def test_off_and_auto_defaults(self):
        self.assertIn("- off -", self.js)
        self.assertIn("- auto -", self.js)

    def test_wires_through_shared_helpers(self):
        self.assertIn("writeBenchmarkRankTier", self.js)
        self.assertIn("writeRoleOverride", self.js)

    def test_reflects_current_values(self):
        # _applySettingsToDom sets the select values from the settings object.
        self.assertIn("benchmarkRankTier", self.js)
        self.assertIn("roleOverride", self.js)


class DsSettingsCss(unittest.TestCase):
    def setUp(self):
        self.css = DS_CSS.read_text(encoding="utf-8")

    def test_select_hit_floor(self):
        m = re.search(r"\.ovset-sel\s*>\s*select\s*\{[^}]*min-height:\s*var\(--hit-min",
                      self.css, re.DOTALL)
        self.assertIsNotNone(m, ".ovset-sel > select must set min-height: var(--hit-min ...)")

    def test_select_focus_ring(self):
        m = re.search(r"\.ovset-sel\s*>\s*select:focus-visible\s*\{[^}]*var\(--focus-ring",
                      self.css, re.DOTALL)
        self.assertIsNotNone(m, ".ovset-sel > select:focus-visible must use var(--focus-ring)")


class AsciiHygiene(unittest.TestCase):
    """Changed slice files stay 7-bit ASCII (hard rule)."""

    def _assert_ascii(self, path: Path):
        data = path.read_bytes()
        bad = [(i, b) for i, b in enumerate(data) if b > 0x7F]
        self.assertEqual(bad[:5], [], f"non-ASCII bytes in {path.name}")

    def test_helper_ascii(self):
        self._assert_ascii(HELPER)

    def test_ds_panel_ascii(self):
        self._assert_ascii(DS_PANEL)

    def test_ds_css_ascii(self):
        self._assert_ascii(DS_CSS)


if __name__ == "__main__":
    unittest.main()

"""Overlay item 8 rework: the overlay stats mini-panel benchmarks "You" against a
SELECTED rank-tier average (mode-specific) instead of the operator's own history.

This supersedes the WP-A4b personal-corpus characterization. Acceptance:
  1. NO panel name header (.sp-head gone) - the vertical table stands alone.
  2. The in-panel role <select> (.sp-role) is RETIRED - the rank-tier + compare-
     role selectors moved to DS Settings (overlay_ds_controls.js). The panel now
     carries NO <select> of its own; it READS the shared rc-pgr-rank-tier setting.
  3. Mode-specific rows: SR + ARAM = LVL / CS / KDA / KP ; Arena = LVL / KDA
     (no CS), each with a You cell + a Bench cell.
  4. The benchmark column feeds from GET /api/rank-tier-bench?tier=&mode=&bracket=,
     consuming stats.<key>.avg + the source() provenance badge; the bracket is
     derived from the live clock (lc.game_time_s) at the 840s / 1500s boundaries
     (the retired "late" >=2100s bucket is gone).
  5. The panel is widened (overlay.css max-width off 190px) + the .sp-src badge
     is styled; the .sp-role rule is gone (its hit-target/focus guard relocated
     to the DS Settings select - tests/test_overlay_stats_role_hit_target.py).

Grep-style contract test (pathlib reads + substring/regex asserts, no DOM
emulation - there is no jsdom/node harness for web/js page code).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PANEL_JS = REPO / "web" / "js" / "panels" / "stats_panel.js"
OVERLAY_CSS = REPO / "web" / "css" / "overlay.css"


def _rule(css: str, selector: str) -> str:
    """Body text of the first CSS rule whose head is `selector` (up to the next
    closing brace), comments stripped."""
    i = css.find(selector)
    assert i != -1, f"selector {selector!r} not found"
    j = css.find("}", i)
    assert j != -1, f"no closing brace after {selector!r}"
    return re.sub(r"/\*.*?\*/", "", css[i:j], flags=re.S)


class NameHeaderRemoved(unittest.TestCase):
    """The panel no longer carries its own name title."""

    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")
        self.css = OVERLAY_CSS.read_text(encoding="utf-8")

    def test_no_sp_head_class_in_js(self):
        self.assertNotIn("sp-head", self.js)

    def test_no_sp_head_rule_in_css(self):
        self.assertNotIn("sp-head", self.css)


class InPanelSelectorRetired(unittest.TestCase):
    """The in-panel role <select> (.sp-role) is gone - selection lives in DS
    Settings and the panel reads the shared rc-pgr-rank-tier setting."""

    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_no_sp_role_class(self):
        self.assertNotIn("sp-role", self.js)

    def test_no_inline_select_built(self):
        # The panel builds no <select> element of its own anymore.
        self.assertNotIn("<select", self.js)

    def test_reads_shared_rank_tier_setting(self):
        self.assertIn("readBenchmarkRankTier", self.js)
        self.assertIn("../lib/overlay_settings.js", self.js)

    def test_repaints_on_shared_change(self):
        # storage event (other windows) + the same-origin custom event (this one).
        self.assertIn("RANK_TIER_EVENT", self.js)
        self.assertIn('"storage"', self.js)
        self.assertIn("PGR_RANK_KEY", self.js)


class VerticalHeader(unittest.TestCase):
    """A bracket label + a provenance/tier badge drive the header row."""

    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_selrow_and_bracket_present(self):
        self.assertIn("sp-selrow", self.js)
        self.assertIn("sp-bracket", self.js)

    def test_source_badge_present(self):
        self.assertIn("sp-src", self.js)


class ModeSpecificRows(unittest.TestCase):
    """SR + ARAM = LVL/CS/KDA/KP ; Arena = LVL/KDA (no CS)."""

    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_rows_by_mode_sr_aram(self):
        pat = (
            r'SR:\s*\[\s*"lvl"\s*,\s*"cs"\s*,\s*"kda"\s*,\s*"kp"\s*\]\s*,\s*'
            r'ARAM:\s*\[\s*"lvl"\s*,\s*"cs"\s*,\s*"kda"\s*,\s*"kp"\s*\]'
        )
        self.assertRegex(self.js, pat)

    def test_rows_by_mode_arena_drops_cs(self):
        self.assertRegex(self.js, r'ARENA:\s*\[\s*"lvl"\s*,\s*"kda"\s*\]')

    def test_row_carries_data_row_key(self):
        self.assertIn('data-row="', self.js)

    def test_each_row_has_you_and_bench_cell(self):
        self.assertIn("sp-you", self.js)
        self.assertIn("sp-bench-cell", self.js)


class BenchmarkFeed(unittest.TestCase):
    """The benchmark column consumes the rank-tier route, bracket derived from
    the live clock, provenance carried."""

    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_rank_tier_route_called(self):
        self.assertIn("/api/rank-tier-bench", self.js)

    def test_no_stale_role_bracket_route(self):
        self.assertNotIn("/api/role-bracket-bench", self.js)

    def test_sends_tier_mode_bracket_params(self):
        self.assertIn("tier=", self.js)
        self.assertIn("mode=", self.js)
        self.assertIn("bracket=", self.js)

    def test_consumes_stats_avg(self):
        self.assertIn("avg", self.js)

    def test_carries_source_provenance(self):
        # the estimate-not-measured badge is load-bearing (coaching honesty).
        self.assertIn(".source", self.js)
        self.assertIn("estimate", self.js)

    def test_bracket_derived_from_game_time(self):
        self.assertIn("game_time_s", self.js)

    def test_bracket_boundaries_mirror_backend(self):
        # core.rank_tier_bench: < 840s early, else mid. 1500 is the nominal mid
        # label; the retired "late" 2100s bucket is gone.
        self.assertIn("840", self.js)
        self.assertIn("1500", self.js)
        self.assertNotIn("2100", self.js)
        self.assertNotIn('"late"', self.js)

    def test_idempotent_build_once_guard_retained(self):
        self.assertIn("dataset.built", self.js)


class ArenaGated(unittest.TestCase):
    """Arena has no seed -> the panel labels it "no benchmark"."""

    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_no_benchmark_label(self):
        self.assertIn("no benchmark", self.js)

    def test_arena_mode_mapped(self):
        self.assertIn("ARENA", self.js)


class RoleDetectionRetained(unittest.TestCase):
    """_detectRole survives the rework (spec: keep _detectRole)."""

    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_detect_role_present(self):
        self.assertIn("function _detectRole(", self.js)
        self.assertIn("_POS_ROLE", self.js)
        self.assertIn("_CLASS_ROLE", self.js)

    def test_override_from_ds_settings(self):
        self.assertIn("readRoleOverride", self.js)


class CssWidenedAndStyled(unittest.TestCase):
    """The panel stays widened off 190px; the badge + table classes are styled;
    the retired .sp-role rule is gone."""

    def setUp(self):
        self.css = OVERLAY_CSS.read_text(encoding="utf-8")

    def test_statspanel_no_longer_190(self):
        body = _rule(self.css, ".ovx-statspanel {")
        self.assertNotIn("190px", body)

    def test_statspanel_widened(self):
        # Phase-5 audit fix: the panel width moved from the inert max-width:220
        # (the .ovx-widget frame is a FIXED width:var(--ovx-w,210px), so
        # max-width could never widen it) to a per-widget --ovx-w:240px override
        # so the widest provenance badge ("GRANDMASTER ESTIMATE") fits un-clipped.
        body = _rule(self.css, ".ovx-statspanel {")
        self.assertIn("--ovx-w: 240px", body)

    def test_source_badge_styled(self):
        self.assertIn(".sp-src", self.css)

    def test_sp_role_rule_retired(self):
        self.assertNotIn(".sp-role", self.css)

    def test_table_classes_styled(self):
        for sel in (".sp-bracket", ".sp-colhead", ".sp-row",
                    ".sp-you", ".sp-bench-cell", ".sp-metric"):
            self.assertIn(sel, self.css)


class AsciiHygiene(unittest.TestCase):
    """stats_panel.js is pure 7-bit ASCII (hard rule)."""

    def test_panel_js_is_pure_ascii(self):
        text = PANEL_JS.read_text(encoding="utf-8")
        for i, ch in enumerate(text):
            self.assertLess(ord(ch), 128,
                            f"non-ASCII byte {ord(ch):#x} at offset {i}")

    BAD = {
        chr(0x2013): "en-dash", chr(0x2014): "em-dash",
        chr(0x2018): "left smart quote", chr(0x2019): "right smart quote",
        chr(0x201C): "left smart dq", chr(0x201D): "right smart dq",
    }

    def test_overlay_css_no_banned_chars(self):
        text = OVERLAY_CSS.read_text(encoding="utf-8")
        for ch, name in self.BAD.items():
            self.assertNotIn(ch, text, f"{name} in overlay.css")


if __name__ == "__main__":
    unittest.main()

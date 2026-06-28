"""A4b (OVERLAY_BUILD_MASTER_PLAN WP-A4b): the overlay stats mini-panel becomes a
vertical "You vs benchmark" table.

Acceptance (from the plan WP-A4 row + the next-session handoff):
  1. NO panel name header - the old `.sp-head` "STATS" title is gone.
  2. VERTICAL - a role-selector header (net-new `<select>`) over a stacked table.
  3. EXACTLY 4 rows keyed LVL / CS / TF / KDA, each carrying a You cell and a
     Benchmark cell (the two-column compare).
  4. The benchmark column feeds from GET /api/role-bracket-bench?role=&bracket=,
     consuming stats.<key>.avg; the bracket is derived from the live game clock
     (lc.game_time_s) mirroring the backend 1500s / 2100s boundaries.
  5. The panel is widened (overlay.css max-width lifted off 190px) to fit the
     three columns + the selector.

Grep-style contract test, mirroring tests/test_overlay_a3_coach_tag_strip.py +
tests/test_overlay_a2_no_enemy_summs.py: pathlib reads + substring/regex asserts,
no DOM emulation (there is no jsdom/node harness for web/js page code). The source
is pinned to the structure the plan requires; the data wiring is pinned by literal
presence of the route + the bracket boundaries.
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

    def test_no_uppercase_stats_title_literal(self):
        # The old scaffold rendered a literal "STATS" title; it is gone.
        self.assertNotIn("STATS", self.js)

    def test_no_sp_head_rule_in_css(self):
        self.assertNotIn("sp-head", self.css)


class VerticalSelectorStructure(unittest.TestCase):
    """A net-new role <select> header drives the benchmark column."""

    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_role_select_present(self):
        self.assertIn("<select", self.js)
        self.assertIn("sp-role", self.js)

    def test_five_canonical_roles_offered(self):
        # Pin the option set (the route's role param values) via the _ROLES
        # table literal - the rendered value="..." is built by concatenation so
        # it is not a source substring.
        pat = (
            r'_ROLES\s*=\s*\[\s*'
            r'\[\s*"top"\s*,\s*"Top"\s*\]\s*,\s*'
            r'\[\s*"jungle"\s*,\s*"Jungle"\s*\]\s*,\s*'
            r'\[\s*"mid"\s*,\s*"Mid"\s*\]\s*,\s*'
            r'\[\s*"bot"\s*,\s*"Bot"\s*\]\s*,\s*'
            r'\[\s*"support"\s*,\s*"Support"\s*\]\s*\]'
        )
        self.assertRegex(self.js, pat)

    def test_bracket_label_present(self):
        # The derived game-time bracket is surfaced beside the selector.
        self.assertIn("sp-bracket", self.js)


class FourCompareRows(unittest.TestCase):
    """Exactly the LVL/CS/TF/KDA rows, each with a You cell + a Bench cell."""

    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_rows_are_exactly_lvl_cs_tf_kda(self):
        # Pin the row set (order + count) via the _ROWS table literal.
        pat = (
            r'_ROWS\s*=\s*\[\s*'
            r'\[\s*"lvl"\s*,\s*"LVL"\s*\]\s*,\s*'
            r'\[\s*"cs"\s*,\s*"CS"\s*\]\s*,\s*'
            r'\[\s*"tf"\s*,\s*"TF"\s*\]\s*,\s*'
            r'\[\s*"kda"\s*,\s*"KDA"\s*\]\s*\]'
        )
        self.assertRegex(self.js, pat)

    def test_row_carries_data_row_key(self):
        self.assertIn('data-row="', self.js)

    def test_each_row_has_you_and_bench_cell(self):
        self.assertIn("sp-you", self.js)
        self.assertIn("sp-bench-cell", self.js)


class BenchmarkFeed(unittest.TestCase):
    """The benchmark column consumes the role x bracket route, bracket derived
    from the live clock."""

    def setUp(self):
        self.js = PANEL_JS.read_text(encoding="utf-8")

    def test_role_bracket_route_called(self):
        self.assertIn("/api/role-bracket-bench", self.js)

    def test_sends_role_and_bracket_params(self):
        self.assertIn("role=", self.js)
        self.assertIn("bracket=", self.js)

    def test_consumes_stats_avg(self):
        # Each benchmark cell headlines stats.<key>.avg.
        self.assertIn("avg", self.js)

    def test_bracket_derived_from_game_time(self):
        self.assertIn("game_time_s", self.js)

    def test_bracket_boundaries_mirror_backend(self):
        # core.role_bracket_bench: < 1500s early, < 2100s mid, else late.
        self.assertIn("1500", self.js)
        self.assertIn("2100", self.js)

    def test_idempotent_build_once_guard_retained(self):
        # The scaffold builds once; ticks update text in place (no churn).
        self.assertIn("dataset.built", self.js)


class CssWidenedAndStyled(unittest.TestCase):
    """The panel is widened off 190px and the new table classes are styled."""

    def setUp(self):
        self.css = OVERLAY_CSS.read_text(encoding="utf-8")

    def test_statspanel_no_longer_190(self):
        body = _rule(self.css, ".ovx-statspanel {")
        self.assertNotIn("190px", body)

    def test_statspanel_widened(self):
        body = _rule(self.css, ".ovx-statspanel {")
        self.assertIn("max-width: 220px", body)

    def test_new_table_classes_styled(self):
        for sel in (".sp-role", ".sp-bracket", ".sp-colhead",
                    ".sp-row", ".sp-you", ".sp-bench-cell", ".sp-metric"):
            self.assertIn(sel, self.css)


class AsciiHygiene(unittest.TestCase):
    """stats_panel.js is a clean new file - pure 7-bit ASCII (hard rule)."""

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

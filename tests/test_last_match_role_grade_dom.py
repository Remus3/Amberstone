"""Grep-based smoke tests for the item 131 Slice A per-role grade chip.

The Last Match (Post Game Review) view gains a 7th column in
.lm-hero-identity carrying the operator's S+/S/A/B/C/D grade for this
match. Source: core/post_game_rubric.py (item 131 Slice A) via
/api/post-game-rubric. Role-aware (ADC/SUP/JG/MID/TOP).

Mirrors tests/test_last_match_score_card_dom.py pattern. Cheap
text-search smoke guards the mount + JS wire + CSS variants from
regressing.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL_JS  = ROOT / "web" / "js" / "panels" / "last_match.js"
PANEL_CSS = ROOT / "web" / "css" / "panels" / "last_match.css"
INDEX_HTML = ROOT / "web" / "index.html"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class HeroRoleGradeBlockTests(unittest.TestCase):
    """The hero's 7th column carries the operator's per-role grade
    (S+/S/A/B/C/D) sourced from /api/post-game-rubric."""

    def test_index_mounts_hero_role_grade_block(self):
        html = _read(INDEX_HTML)
        self.assertIn('id="lm-hero-role-grade"', html)
        self.assertIn('id="lm-hero-role-grade-role"', html)
        self.assertIn('id="lm-hero-role-grade-value"', html)
        self.assertIn('id="lm-hero-role-grade-tier"', html)

    def test_hero_role_grade_starts_hidden(self):
        html = _read(INDEX_HTML)
        block = html.split('id="lm-hero-role-grade"', 1)[1].split(">", 1)[0]
        self.assertIn("hidden", block)

    def test_hero_role_grade_carries_data_tt_tooltip(self):
        html = _read(INDEX_HTML)
        block = html.split('id="lm-hero-role-grade"', 1)[1].split(">", 1)[0]
        self.assertIn("data-tt=", block)

    def test_js_wires_set_hero_role_grade_into_render(self):
        js = _read(PANEL_JS)
        self.assertIn("_setHeroRoleGrade(", js)
        render = js.split("function renderLastMatch", 1)[1].split("function ", 1)[0]
        self.assertIn("_setHeroRoleGrade(", render)

    def test_js_defines_set_hero_role_grade_function(self):
        js = _read(PANEL_JS)
        self.assertIn("function _setHeroRoleGrade(", js)

    def test_js_fetches_post_game_rubric_endpoint(self):
        js = _read(PANEL_JS)
        body = js.split("function _setHeroRoleGrade(", 1)[1].split("\n}", 1)[0]
        self.assertIn("/api/post-game-rubric", body)
        self.assertIn("match_id=", body)
        self.assertIn("encodeURIComponent", body)

    def test_js_consumes_role_total_score_grade_fields(self):
        js = _read(PANEL_JS)
        body = js.split("function _setHeroRoleGrade(", 1)[1].split("\n}", 1)[0]
        # The three response fields wired into the chip.
        self.assertIn("data.role", body)
        self.assertIn("data.total_score", body)
        self.assertIn("data.percentile_grade", body)

    def test_css_hero_role_grade_data_tier_variants(self):
        css = _read(PANEL_CSS)
        for tier in ("S+", "S", "A", "B", "C", "D"):
            self.assertIn(f'.lm-hero-role-grade[data-tier="{tier}"]', css,
                          f"missing tier color rule for {tier!r}")

    def test_css_hero_role_grade_hidden_rule(self):
        css = _read(PANEL_CSS)
        block = css.split(".lm-hero-role-grade[hidden]", 1)[1].split("}", 1)[0]
        self.assertIn("display: none", block)

    def test_hero_identity_grid_widens_to_seven_columns(self):
        css = _read(PANEL_CSS)
        block = css.split(".lm-hero-identity", 1)[1].split("}", 1)[0]
        # 6 'auto' tokens after the leading '72px' = portrait + name +
        # kda + result + grade + score + role-grade.
        self.assertIn(
            "grid-template-columns: 72px auto auto auto auto auto auto",
            block,
        )


class EmptyStateResetTests(unittest.TestCase):
    """_setEmptyState must clear the per-role grade chip alongside
    the existing hero score + MVP card clears."""

    def test_empty_state_hides_hero_role_grade(self):
        js = _read(PANEL_JS)
        body = js.split("function _setEmptyState(", 1)[1].split("\nfunction ", 1)[0]
        self.assertIn("lm-hero-role-grade", body)
        self.assertIn('heroRole.hidden = true', body)


class AsciiHygieneTests(unittest.TestCase):
    """The new wires + CSS must stay 7-bit ASCII (hard rule)."""

    BAD = (
        chr(0x2013), chr(0x2014),  # en/em dash
        chr(0x201C), chr(0x201D),  # smart double quotes
        chr(0x2018), chr(0x2019),  # smart single quotes
    )

    def _scan(self, path: Path) -> None:
        # Only scan the new additions: search for the section + assert
        # no banned glyph appears in it.
        text = path.read_text(encoding="utf-8")
        for ch in self.BAD:
            self.assertNotIn(ch, text, f"banned glyph {hex(ord(ch))} in {path.name}")

    def test_js_section_is_ascii(self):
        # Only check the new helper + reset block region by scoping to
        # the helper body string.
        js = _read(PANEL_JS)
        body = js.split("function _setHeroRoleGrade(", 1)[1].split("\n}", 1)[0]
        for ch in self.BAD:
            self.assertNotIn(ch, body)

    def test_css_section_is_ascii(self):
        css = _read(PANEL_CSS)
        body = css.split(".lm-hero-role-grade {", 1)[1].split(".lm-hero-result", 1)[0]
        for ch in self.BAD:
            self.assertNotIn(ch, body)


if __name__ == "__main__":
    unittest.main()

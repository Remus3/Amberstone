"""Grep-based smoke tests for the s220 PGR S3 aggregator-G-style score+MVP polish.

Three new affordances on the Post Game Review (Last Match) view:

1. Hero match-score block (operator's 0-100 + tier label).
2. Per-side MVP / SVP card above each roster (portrait + crown + score).
3. Per-row score chip (numeric 0-100 stacked under the MVP/SVP/#rank badge).

The aggregator G pattern is intentional: a single big number + tier label
should be the primary affordance, MVP card highlights the carry, the
per-row chip shows the rest of the lobby in context. These guards
catch a refactor that drops any of those wires.

Mirrors the cheap text-search precedent set by
``tests/test_draft_elo_panel_dom.py`` + ``tests/test_augment_reco_panel_dom.py``.

RC heuristic only - no Claude/Riot API. The scorer is _rosterScores
(already in last_match.js), so the three numbers (hero, MVP card,
per-row chip) are derived from the same function and stay consistent.
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


class HeroScoreBlockTests(unittest.TestCase):
    """The hero gets a new 6th column carrying the operator's 0-100 score
    + tier label. Must mount cleanly in the existing .lm-hero-identity
    grid and stay hidden until LCU enrichment lands."""

    def test_index_mounts_hero_score_block(self):
        html = _read(INDEX_HTML)
        self.assertIn('id="lm-hero-score"', html)
        self.assertIn('id="lm-hero-score-value"', html)
        self.assertIn('id="lm-hero-score-tier"', html)

    def test_hero_score_starts_hidden(self):
        html = _read(INDEX_HTML)
        # The empty-state default must hide it - the panel only flips
        # visible after _setHeroScore lands a real roster score.
        block = html.split('id="lm-hero-score"', 1)[1].split(">", 1)[0]
        self.assertIn("hidden", block)

    def test_hero_score_carries_data_tt_tooltip(self):
        html = _read(INDEX_HTML)
        # The factor breakdown lives in the hover tooltip - operator
        # asked for the score to be explainable on hover.
        block = html.split('id="lm-hero-score"', 1)[1].split(">", 1)[0]
        self.assertIn("data-tt=", block)

    def test_js_wires_set_hero_score_into_render(self):
        js = _read(PANEL_JS)
        self.assertIn("_setHeroScore(", js)
        # Must be called from renderLastMatch alongside the other setters.
        render = js.split("function renderLastMatch", 1)[1].split("function ", 1)[0]
        self.assertIn("_setHeroScore(", render)

    def test_js_defines_set_hero_score_function(self):
        js = _read(PANEL_JS)
        self.assertIn("function _setHeroScore(", js)

    def test_js_score_tier_buckets(self):
        """The 4 tier buckets are calibrated against _rosterScores'
        100-point scale. Tighten the thresholds in this test if the
        weights ever change so the visual tiers stay calibrated."""
        js = _read(PANEL_JS)
        body = js.split("function _scoreTier(", 1)[1].split("\n}", 1)[0]
        self.assertIn(">= 80", body)
        self.assertIn(">= 65", body)
        self.assertIn(">= 50", body)
        self.assertIn('"Excellent"', body)
        self.assertIn('"Good"', body)
        self.assertIn('"OK"', body)
        self.assertIn('"Bad"', body)

    def test_css_hero_score_data_tier_variants(self):
        css = _read(PANEL_CSS)
        for tier in ("excellent", "good", "ok", "bad"):
            self.assertIn(f'.lm-hero-score[data-tier="{tier}"]', css,
                          f"missing tier color rule for {tier!r}")

    def test_css_hero_score_hidden_rule(self):
        css = _read(PANEL_CSS)
        block = css.split(".lm-hero-score[hidden]", 1)[1].split("}", 1)[0]
        self.assertIn("display: none", block)

    def test_hero_identity_grid_widens_to_six_columns(self):
        css = _read(PANEL_CSS)
        # 6 'auto' tokens after the leading '72px' = portrait + name +
        # kda + result + grade + score. If a refactor drops back to 5,
        # the new score block has no grid slot.
        block = css.split(".lm-hero-identity", 1)[1].split("}", 1)[0]
        self.assertIn("72px auto auto auto auto auto", block)


class MvpCardTests(unittest.TestCase):
    """Per-side MVP/SVP card above each roster. Aggregator G pattern -
    portrait + crown + name + numeric score."""

    def test_index_mounts_ally_and_enemy_mvp_cards(self):
        html = _read(INDEX_HTML)
        self.assertIn('id="lm-tc-ally-mvp"', html)
        self.assertIn('id="lm-tc-enemy-mvp"', html)

    def test_mvp_cards_start_hidden(self):
        html = _read(INDEX_HTML)
        for cid in ("lm-tc-ally-mvp", "lm-tc-enemy-mvp"):
            block = html.split(f'id="{cid}"', 1)[1].split(">", 1)[0]
            self.assertIn("hidden", block, f"{cid} must start hidden")

    def test_js_renders_mvp_cards(self):
        js = _read(PANEL_JS)
        self.assertIn("function _renderMvpCard(", js)
        self.assertIn('_renderMvpCard("lm-tc-ally-mvp"',  js)
        self.assertIn('_renderMvpCard("lm-tc-enemy-mvp"', js)

    def test_js_mvp_card_uses_roster_scores(self):
        """The MVP card MUST source its score from _rosterScores so the
        hero / card / per-row chip all agree. A refactor that introduces
        a divergent scorer here is a bug."""
        js = _read(PANEL_JS)
        # rankSide reads scores from _rosterScores result; the card
        # receives the same meta entry. Probe the call path.
        team_comp = js.split("function _setTeamComp(", 1)[1].split("function ", 1)[0]
        self.assertIn("_rosterScores(roster)", team_comp)
        self.assertIn("_renderMvpCard(", team_comp)

    def test_js_mvp_card_emits_crown_svg(self):
        """Crown is rendered via inline SVG (NOT an emoji). The ASCII
        hard rule forbids Unicode glyphs in authored content."""
        js = _read(PANEL_JS)
        mvp = js.split("function _renderMvpCard(", 1)[1].split("\n}", 1)[0]
        self.assertIn("lm-tc-mvp-crown", mvp)
        self.assertIn("<svg", mvp)
        # No emoji in the file. Glyphs encoded via chr() so this test
        # file stays ASCII-clean against its own scan.
        for glyph in (chr(0x1F451),  # CROWN
                      chr(0x2606),   # WHITE STAR
                      chr(0x2605)):  # BLACK STAR
            self.assertNotIn(glyph, js, f"forbidden glyph U+{ord(glyph):04X} in last_match.js")

    def test_css_mvp_card_data_kind_variants(self):
        css = _read(PANEL_CSS)
        self.assertIn('.lm-tc-mvp[data-kind="mvp"]', css)
        self.assertIn('.lm-tc-mvp[data-kind="svp"]', css)

    def test_css_mvp_card_hidden_rule(self):
        css = _read(PANEL_CSS)
        block = css.split(".lm-tc-mvp[hidden]", 1)[1].split("}", 1)[0]
        self.assertIn("display: none", block)

    def test_css_mvp_score_tier_variants(self):
        css = _read(PANEL_CSS)
        for tier in ("excellent", "good", "ok", "bad"):
            self.assertIn(f'.lm-tc-mvp-score[data-tier="{tier}"]', css,
                          f"missing MVP score tier rule for {tier!r}")


class PerRowScoreChipTests(unittest.TestCase):
    """The MVP/SVP/#rank cell now stacks the badge text + the 0-100
    score. The score used to live only in the hover tooltip."""

    def test_js_score_cell_emits_badge_plus_value(self):
        js = _read(PANEL_JS)
        # Both branches of the scoreCell template (badge case + rank case)
        # must emit the new score-badge + score-value spans.
        cell = js.split("const scoreCell = m.badge", 1)[1].split(";", 1)[0]
        self.assertIn("lm-tc-score-badge", cell)
        self.assertIn("lm-tc-score-value", cell)

    def test_js_score_cell_rounds_numeric_score(self):
        """The chip shows an integer 0-100; the tooltip retains the
        decimal. Math.round keeps the chip narrow + readable."""
        js = _read(PANEL_JS)
        render_row = js.split("function _renderTcRow(", 1)[1].split("function ", 1)[0]
        self.assertIn("Math.round(m.score)", render_row)

    def test_css_score_cell_stacks_vertically(self):
        css = _read(PANEL_CSS)
        block = css.split(".lm-tc-score {", 1)[1].split("}", 1)[0]
        self.assertIn("flex-direction: column", block)

    def test_css_grid_row_widens_score_column(self):
        """The chip needs ~56px; the pre-S3 column was 46px and would
        clip the 3-digit edge case (score=100). Bump pinned here."""
        css = _read(PANEL_CSS)
        self.assertIn("40px 144px 56px 32px 84px 60px 70px 1fr", css)

    def test_css_grid_aug_row_widens_score_column(self):
        """The augment-mode (ARAM Mayhem / Arena) override must keep
        the same 56px score column so ally + enemy align."""
        css = _read(PANEL_CSS)
        self.assertIn("40px 144px 56px 32px 84px 60px auto 70px 1fr", css)


class EmptyStateResetTests(unittest.TestCase):
    """_setEmptyState (the no-match-found path) must clear all three
    affordances or a stale render lingers across view switches."""

    def test_empty_state_resets_hero_score(self):
        js = _read(PANEL_JS)
        empty = js.split("function _setEmptyState(", 1)[1].split("\n}", 1)[0]
        self.assertIn("lm-hero-score", empty)

    def test_empty_state_resets_mvp_cards(self):
        js = _read(PANEL_JS)
        empty = js.split("function _setEmptyState(", 1)[1].split("\n}", 1)[0]
        self.assertIn("lm-tc-ally-mvp", empty)
        self.assertIn("lm-tc-enemy-mvp", empty)


class AsciiHygieneTests(unittest.TestCase):
    """No em-dashes / en-dashes / smart quotes / emoji in the touched
    files. CLAUDE.md hard rule + ASCII-only authored content.

    Bad-glyph table is built via chr() so this file stays ASCII-clean
    itself (a literal-encoding version would fail its own scan)."""

    BAD = {
        chr(0x2013): "EN DASH",
        chr(0x2014): "EM DASH",
        chr(0x2018): "LEFT SINGLE QUOTE",
        chr(0x2019): "RIGHT SINGLE QUOTE",
        chr(0x201C): "LEFT DOUBLE QUOTE",
        chr(0x201D): "RIGHT DOUBLE QUOTE",
    }

    def _scan(self, path: Path) -> list[tuple[int, str]]:
        hits: list[tuple[int, str]] = []
        text = path.read_text(encoding="utf-8")
        for ch, name in self.BAD.items():
            if ch in text:
                hits.append((0, name))
        return hits

    def test_panel_js_is_ascii_clean(self):
        self.assertEqual([], self._scan(PANEL_JS))

    def test_panel_css_is_ascii_clean(self):
        self.assertEqual([], self._scan(PANEL_CSS))

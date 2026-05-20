"""Grep-based smoke tests for the per-row contribution hover strip
(2026-05-20 BACKLOG/ROADMAP 109(b), Draft Tool L pair-list + Diff15 pattern).

These guard the frontend wire so a future refactor that drops the
hover overlay (CSS :hover -> display rule removed, JS overlay renderer
forgotten, ?breakdown=1 query param dropped) is caught at test time
instead of vanishing silently from the dashboard.

Mirrors the cheap text-search precedent set by
``tests/test_augment_reco_panel_dom.py``.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL_JS = ROOT / "web" / "js" / "panels" / "draft_elo.js"
PANEL_CSS = ROOT / "web" / "css" / "panels" / "draft_elo.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class HoverOnlyContractTests(unittest.TestCase):
    """The hover strip MUST be hover-only - no JS state, no click-to-pin.

    Field consensus per the multi-agent research wave is that
    persistent draft sidebars clutter at 1920x1080. The CSS :hover
    selector is the load-bearing primitive; if a future change adds
    a JS click-to-pin handler or persistent show class, these guards
    fail.
    """

    def test_css_uses_hover_pseudo_class(self):
        css = _read(PANEL_CSS)
        self.assertIn(
            ".draft-elo-chip:hover .draft-elo-contributions",
            css,
            ":hover toggle missing - the overlay must be hover-only",
        )
        self.assertIn(
            "display: block",
            css.split(".draft-elo-chip:hover")[1].split("}")[0],
            "the :hover rule must toggle display to block",
        )

    def test_css_overlay_defaults_to_display_none(self):
        css = _read(PANEL_CSS)
        # The base rule for .draft-elo-contributions sets display: none.
        rule_block = css.split(
            ".draft-elo-chip .draft-elo-contributions"
        )[1].split("}")[0]
        self.assertIn("display: none", rule_block)

    def test_no_persistent_click_handlers(self):
        """JS file must not bind click-to-pin behavior. A persistent
        sidebar would need an onclick or addEventListener('click'); the
        hover-only contract forbids both."""
        js = _read(PANEL_JS)
        self.assertNotIn("addEventListener('click'", js)
        self.assertNotIn('addEventListener("click"', js)
        self.assertNotIn(".onclick", js)
        # No persistent visible-class flip either.
        self.assertNotIn("classList.add('pinned'", js)
        self.assertNotIn('classList.add("pinned"', js)

    def test_overlay_has_pointer_events_none(self):
        """A non-interactive overlay does not steal pointer focus."""
        css = _read(PANEL_CSS)
        self.assertIn("pointer-events: none", css)


class BackendWireContractTests(unittest.TestCase):
    """Frontend must request ?breakdown=1 so the route returns the
    top_contributions field."""

    def test_fetch_passes_breakdown_param(self):
        js = _read(PANEL_JS)
        self.assertIn("breakdown", js, "fetchDraftElo must include breakdown")
        # The query string is built via URLSearchParams - check the literal.
        self.assertIn('breakdown: "1"', js)

    def test_render_consumes_top_contributions(self):
        js = _read(PANEL_JS)
        self.assertIn("top_contributions", js)

    def test_overlay_uses_top_contributions_class(self):
        """Both the renderer and the CSS pin the class name
        ``.draft-elo-contributions``."""
        js = _read(PANEL_JS)
        css = _read(PANEL_CSS)
        self.assertIn("draft-elo-contributions", js)
        self.assertIn(".draft-elo-contributions", css)


class ContributionRowMarkupTests(unittest.TestCase):
    """The contribution row markup must carry kind + delta + n so the
    hover strip is readable."""

    def test_row_has_kind_data_attr(self):
        js = _read(PANEL_JS)
        self.assertIn('data-kind=', js)

    def test_row_renders_signed_delta(self):
        js = _read(PANEL_JS)
        # Both up + down sign classes exist.
        self.assertIn("de-contrib-up", js)
        self.assertIn("de-contrib-down", js)

    def test_row_renders_sample_count(self):
        js = _read(PANEL_JS)
        self.assertIn("de-contrib-n", js)

    def test_css_styles_all_three_kinds(self):
        css = _read(PANEL_CSS)
        self.assertIn('data-kind="ally-pair"', css)
        self.assertIn('data-kind="enemy-pair"', css)
        self.assertIn('data-kind="matchup"', css)

    def test_portrait_fallback_renders_id(self):
        """When CHAMPS lookup fails (early page boot, unknown id), the
        row falls back to the bare champ id."""
        js = _read(PANEL_JS)
        self.assertIn("de-portrait-fallback", js)


class AsciiHygieneTests(unittest.TestCase):
    """No em-dashes / en-dashes / smart quotes (CLAUDE.md hard rule).

    Tested by raw-byte sweep (every byte < 0x80) rather than a literal
    char-list so the test file itself stays ASCII-clean.
    """

    def test_panel_js_is_ascii(self):
        raw = PANEL_JS.read_bytes()
        for b in raw:
            self.assertLess(b, 0x80,
                            f"non-ASCII byte 0x{b:02x} in draft_elo.js")

    def test_panel_css_is_ascii(self):
        raw = PANEL_CSS.read_bytes()
        for b in raw:
            self.assertLess(b, 0x80,
                            f"non-ASCII byte 0x{b:02x} in draft_elo.css")


if __name__ == "__main__":
    unittest.main()

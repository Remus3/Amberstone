"""Grep-based contract tests for the design-tokens layer.

Three concerns this guards:

1. web/css/tokens.css exists and declares the full token surface
   (semantic colors + 4-tier font scale + 8px spacing grid + 3 pulse
   keyframes + the .tabular-nums utility).
2. web/css/dashboard.css imports tokens.css so the :root vars cascade
   to every panel; the existing primitives.css import is preserved
   (additive, not a replacement).
3. The swept panels (draft_elo / right_now) no
   longer reference the hardcoded hex literals #ff5050 / #f1b04a /
   #6ec977 (or the off-palette pill hex #fbbf24 / #4ade80 / #f0a3a3 for
   right_now), and instead consume var(--signal-*) tokens.
4. ASCII hygiene scan on tokens.css per the no-em-dash hard rule;
   BAD dict built via chr() so this test file stays clean against its
   own scan (mirrors test_replay_events_panel_dom.py pattern).

Mirrors the cheap text-search precedent in
``tests/test_replay_events_panel_dom.py`` +
``tests/test_last_match_tabs_reframe_dom.py``.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS_CSS    = ROOT / "web" / "css" / "tokens.css"
DASHBOARD_CSS = ROOT / "web" / "css" / "dashboard.css"
HEXTECH_CSS   = ROOT / "web" / "css" / "hextech.css"
BASE_CSS      = ROOT / "web" / "css" / "panels" / "base.css"
DRAFT_ELO_CSS = ROOT / "web" / "css" / "panels" / "draft_elo.css"
RIGHT_NOW_CSS = ROOT / "web" / "css" / "panels" / "right_now.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TokensFilePresenceTests(unittest.TestCase):
    """tokens.css exists and declares the full token surface."""

    def test_file_exists(self):
        self.assertTrue(TOKENS_CSS.exists(),
                        f"web/css/tokens.css must exist at {TOKENS_CSS}")

    def test_declares_root_block(self):
        css = _read(TOKENS_CSS)
        self.assertIn(":root {", css,
                      "tokens.css must declare a :root { ... } block")

    def test_declares_semantic_colors(self):
        css = _read(TOKENS_CSS)
        for token in (
            "--signal-good:",
            "--signal-warn:",
            "--signal-bad:",
            "--signal-dim:",
            "--signal-info:",
            "--signal-gold:",
            "--signal-good-soft:",
            "--signal-warn-soft:",
            "--signal-bad-soft:",
        ):
            self.assertIn(token, css, f"tokens.css missing {token} declaration")

    def test_semantic_color_hex_values(self):
        """The semantic hex literals must live HERE (and only here) so
        panels can repoint via var(). RC2 re-point: the signal hues now
        match the greenlit Hextech palette (docs/design/RC2_DESIGN.html)
        - good #37D08A, warn #E8A33D, bad #E84057 (was the neo-fintech
        #6ec977 / #f1b04a / #ff5050)."""
        css = _read(TOKENS_CSS)
        self.assertIn("#37D08A", css, "tokens.css must declare --signal-good hex #37D08A")
        self.assertIn("#E8A33D", css, "tokens.css must declare --signal-warn hex #E8A33D")
        self.assertIn("#E84057", css, "tokens.css must declare --signal-bad hex #E84057")

    def test_declares_4tier_font_scale(self):
        css = _read(TOKENS_CSS)
        for token in ("--fs-xs:", "--fs-sm:", "--fs-md:", "--fs-lg:", "--fs-xl:"):
            self.assertIn(token, css, f"tokens.css missing {token} declaration")

    def test_declares_8px_spacing_grid(self):
        css = _read(TOKENS_CSS)
        for token in (
            "--space-1:",
            "--space-2:",
            "--space-3:",
            "--space-4:",
            "--space-5:",
            "--space-6:",
        ):
            self.assertIn(token, css, f"tokens.css missing {token} declaration")

    def test_declares_pulse_tokens(self):
        css = _read(TOKENS_CSS)
        for token in ("--pulse-good:", "--pulse-warn:", "--pulse-bad:"):
            self.assertIn(token, css, f"tokens.css missing {token} declaration")

    def test_declares_pulse_keyframes(self):
        css = _read(TOKENS_CSS)
        for kf in (
            "@keyframes coach-pulse-good",
            "@keyframes coach-pulse-warn",
            "@keyframes coach-pulse-bad",
        ):
            self.assertIn(kf, css, f"tokens.css missing {kf}")

    def test_declares_tabular_nums_utility(self):
        css = _read(TOKENS_CSS)
        self.assertIn(".tabular-nums", css,
                      "tokens.css must expose the .tabular-nums opt-in utility")
        self.assertIn("font-variant-numeric: tabular-nums", css,
                      ".tabular-nums must set font-variant-numeric: tabular-nums")


class DashboardImportsTokens(unittest.TestCase):
    """dashboard.css imports tokens.css; existing primitives import is
    preserved (additive, not a replacement)."""

    def test_dashboard_imports_tokens(self):
        css = _read(DASHBOARD_CSS)
        self.assertIn("@import './tokens.css';", css,
                      "dashboard.css must import ./tokens.css")

    def test_dashboard_still_imports_primitives(self):
        css = _read(DASHBOARD_CSS)
        # primitives.css was the existing palette; the tokens layer is
        # additive, NOT a replacement.
        self.assertIn("primitives.css", css,
                      "primitives.css import must NOT have been removed")

    def test_tokens_import_before_panels(self):
        """tokens.css must be imported before the panel imports so
        the :root vars cascade."""
        css = _read(DASHBOARD_CSS)
        tokens_idx = css.find("@import './tokens.css';")
        # Find any panel import
        panel_idx = css.find("@import './panels/")
        self.assertGreater(tokens_idx, -1, "tokens.css import not found")
        self.assertGreater(panel_idx, -1, "panel imports not found")
        self.assertLess(tokens_idx, panel_idx,
                        "tokens.css must be imported before ./panels/* imports")


class BaseCssUndefinedVarsTests(unittest.TestCase):
    """RC2 keystone: the dashboard references var(--clock) + var(--label)
    at ~62 sites (item/header/home/panel_visibility panels) but the old
    neo-fintech palette never DEFINED them. base.css :root must now
    define both."""

    def test_clock_and_label_defined_in_base_root(self):
        css = _read(BASE_CSS)
        root_block = css.split(":root {", 1)[1].split("}", 1)[0]
        self.assertIn("--clock:", root_block,
                      "base.css :root must define --clock (referenced by panels)")
        self.assertIn("--label:", root_block,
                      "base.css :root must define --label (referenced by panels)")


class HextechCssTests(unittest.TestCase):
    """RC2 keystone: web/css/hextech.css exists, declares the reusable
    component primitives, and is imported by dashboard.css."""

    def test_file_exists(self):
        self.assertTrue(HEXTECH_CSS.exists(),
                        f"web/css/hextech.css must exist at {HEXTECH_CSS}")

    def test_declares_component_primitives(self):
        css = _read(HEXTECH_CSS)
        for sel in (".hx-card", ".hx-chip", ".hx-bar", ".hx-empty"):
            self.assertIn(sel, css,
                          f"hextech.css must declare the {sel} primitive")

    def test_imported_by_dashboard(self):
        css = _read(DASHBOARD_CSS)
        self.assertIn("@import './hextech.css';", css,
                      "dashboard.css must import ./hextech.css")

    def test_imported_after_tokens(self):
        """hextech.css consumes tokens; its import must come after
        tokens.css so the vars resolve first."""
        css = _read(DASHBOARD_CSS)
        tokens_idx  = css.find("@import './tokens.css';")
        hextech_idx = css.find("@import './hextech.css';")
        self.assertGreater(tokens_idx, -1, "tokens.css import not found")
        self.assertGreater(hextech_idx, -1, "hextech.css import not found")
        self.assertLess(tokens_idx, hextech_idx,
                        "hextech.css must be imported after tokens.css")


class DraftEloConsumesTokensTests(unittest.TestCase):
    """draft_elo.css uses var(--signal-*) for the 3 band colors and
    no longer references the hardcoded hex literals."""

    def test_no_hardcoded_band_hex(self):
        css = _read(DRAFT_ELO_CSS)
        # The 3 audit-flagged hex literals must not appear as bare
        # color values. (The hex letters could appear in a comment;
        # we just check the literal does not appear as a property value
        # by checking for "{ color: #xxxxxx" or "color: #xxxxxx;".)
        for hex_lit in ("#ff5050", "#f1b04a", "#6ec977"):
            self.assertNotIn(f"color: {hex_lit}", css,
                             f"draft_elo.css still uses bare color: {hex_lit};"
                             f" repoint to var(--signal-*).")

    def test_consumes_signal_vars(self):
        css = _read(DRAFT_ELO_CSS)
        self.assertIn("var(--signal-bad)",   css,
                      ".de-band-red must consume var(--signal-bad)")
        self.assertIn("var(--signal-warn)",  css,
                      ".de-band-amber must consume var(--signal-warn)")
        self.assertIn("var(--signal-good)",  css,
                      ".de-band-green must consume var(--signal-good)")

    def test_score_and_wr_use_tabular_nums(self):
        css = _read(DRAFT_ELO_CSS)
        # Both .de-score and .de-wr blocks should set
        # font-variant-numeric: tabular-nums so the digit columns stay
        # aligned across chips with different WR / score widths.
        de_score_block = css.split(".draft-elo-chip .de-score {", 1)[1].split("}", 1)[0]
        de_wr_block    = css.split(".draft-elo-chip .de-wr {", 1)[1].split("}", 1)[0]
        self.assertIn("tabular-nums", de_score_block,
                      ".de-score must set font-variant-numeric: tabular-nums")
        self.assertIn("tabular-nums", de_wr_block,
                      ".de-wr must set font-variant-numeric: tabular-nums")


class RightNowConsumesTokensTests(unittest.TestCase):
    """right_now.css uses var(--signal-*) for the .rn-sr-pill state
    colors (was off-palette #fbbf24 / #4ade80 / #f0a3a3)."""

    def test_no_hardcoded_pill_state_hex(self):
        css = _read(RIGHT_NOW_CSS)
        # The 3 audit-flagged off-palette pill hex literals must not
        # appear as bare color values in .rn-sr-pill state classes.
        for hex_lit in ("#fbbf24", "#4ade80", "#f0a3a3"):
            self.assertNotIn(f"color: {hex_lit}", css,
                             f"right_now.css still uses bare color: {hex_lit};"
                             f" repoint to var(--signal-*).")

    def test_consumes_signal_vars(self):
        css = _read(RIGHT_NOW_CSS)
        # .rn-sr-pill.is-pending -> warn; .is-ok -> good; .is-error -> bad
        self.assertIn("var(--signal-warn)", css,
                      ".rn-sr-pill.is-pending must consume var(--signal-warn)")
        self.assertIn("var(--signal-good)", css,
                      ".rn-sr-pill.is-ok must consume var(--signal-good)")
        self.assertIn("var(--signal-bad)",  css,
                      ".rn-sr-pill.is-error must consume var(--signal-bad)")


class AsciiHygieneTests(unittest.TestCase):
    """No em/en-dashes, smart quotes in tokens.css per the project
    hard rule. BAD dict built via chr() so this test file stays clean
    against its own scan."""

    BAD = {
        chr(0x2013): "EN DASH",
        chr(0x2014): "EM DASH",
        chr(0x2018): "LEFT SINGLE QUOTE",
        chr(0x2019): "RIGHT SINGLE QUOTE",
        chr(0x201C): "LEFT DOUBLE QUOTE",
        chr(0x201D): "RIGHT DOUBLE QUOTE",
    }

    def _scan(self, path: Path) -> list[str]:
        text = path.read_text(encoding="utf-8")
        return [name for ch, name in self.BAD.items() if ch in text]

    def test_tokens_css_is_ascii_clean(self):
        self.assertEqual([], self._scan(TOKENS_CSS),
                         "tokens.css contains forbidden non-ASCII characters")


if __name__ == "__main__":
    unittest.main()

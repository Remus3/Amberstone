"""Grep-based contract tests for the overlay Hextech palette re-point.

The Electron overlay is RC's ONLY user-facing surface (the 1920 dashboard is
RETIRED as a user surface, operator decision 2026-06-21). Its shared panels
(callouts.css / coach_choices.css) consume the tokens.css --signal-* semantic
tokens, whose :root values are the OLD fintech hues (#6ec977 / #f1b04a /
#ff5050 / #8a8cf0). This guards that overlay.css re-points those tokens to the
section-0 Hextech --ovx-* parts INSIDE the body[data-shell="overlay"] scope, so
every overlay-rendered chip / pill / band inherits Hextech without a raw color
literal landing on any widget rule (doctrine section 5 - palette is law).

Invariants locked here:
  - the new --ovx-warn Hextech token is defined in the section-0 block;
  - the overlay scope re-points --signal-good / --signal-bad / --signal-warn
    (plus info/gold/dim and the *-soft variants) to rgb(var(--ovx-*));
  - the overlay .rc-co-eta.rc-co-now rule re-binds the active objective chip to
    --ovx-cyan (objectives read cyan, not green);
  - the overlay #rn-lead .rc-lead-line carries a font-size override (the glance
    floor) and #rn-lead takes the Hextech nested backing;
  - no raw 6-digit hex color literal sits on a widget property in overlay.css
    (every hex lives in the --ovx-* token block);
  - ASCII hygiene (no em/en-dash, smart quotes) per the repo hard rule.

Mirrors the cheap text-search precedent in tests/test_design_tokens_css.py +
tests/test_overlay_css_typography_tokens.py.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERLAY_CSS = ROOT / "web" / "css" / "overlay.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _overlay_scope_blocks(css: str) -> str:
    """Concatenate the body of every `body[data-shell="overlay"] { ... }`
    rule whose selector is the bare shell scope (the token-declaring blocks),
    so token-override assertions only see overlay-scoped declarations."""
    blocks = re.findall(
        r'body\[data-shell="overlay"\]\s*\{([^{}]*)\}',
        css,
        re.DOTALL,
    )
    return "\n".join(blocks)


class OvxWarnTokenTests(unittest.TestCase):
    """The new amber Hextech token lives in the section-0 --ovx-* block."""

    def test_ovx_warn_token_defined(self):
        css = _read(OVERLAY_CSS)
        self.assertIn("--ovx-warn:", css,
                      "overlay.css must define the --ovx-warn Hextech token")

    def test_ovx_warn_hex_in_comment_only(self):
        """The #E8A33D hex annotates the token; it must not land on a widget
        property (it is consumed via rgb(var(--ovx-warn)))."""
        css = _read(OVERLAY_CSS)
        self.assertIn("232, 163, 61", css,
                      "--ovx-warn must carry the rgb parts 232, 163, 61")


class SemanticRepointTests(unittest.TestCase):
    """The overlay scope re-points the --signal-* semantic tokens to the
    Hextech --ovx-* parts so the shared panels inherit Hextech."""

    def test_repoints_core_signals(self):
        scope = _overlay_scope_blocks(_read(OVERLAY_CSS))
        for decl in (
            "--signal-good: rgb(var(--ovx-good));",
            "--signal-bad: rgb(var(--ovx-red));",
            "--signal-warn: rgb(var(--ovx-warn));",
        ):
            self.assertIn(decl, scope,
                          f"overlay scope must re-point {decl}")

    def test_repoints_info_to_cyan(self):
        scope = _overlay_scope_blocks(_read(OVERLAY_CSS))
        self.assertIn("--signal-info: rgb(var(--ovx-cyan));", scope,
                      "overlay --signal-info must re-point to --ovx-cyan (doctrine)")

    def test_repoints_gold_and_dim(self):
        scope = _overlay_scope_blocks(_read(OVERLAY_CSS))
        self.assertIn("--signal-gold: rgb(var(--ovx-gold));", scope,
                      "overlay --signal-gold must re-point to --ovx-gold")
        self.assertIn("--signal-dim: rgba(var(--ovx-text), 0.55);", scope,
                      "overlay --signal-dim must re-point to --ovx-text @0.55")

    def test_repoints_soft_variants(self):
        scope = _overlay_scope_blocks(_read(OVERLAY_CSS))
        for decl in (
            "--signal-good-soft: rgba(var(--ovx-good), 0.18);",
            "--signal-bad-soft: rgba(var(--ovx-red), 0.18);",
            "--signal-warn-soft: rgba(var(--ovx-warn), 0.18);",
        ):
            self.assertIn(decl, scope,
                          f"overlay scope must re-point soft variant {decl}")


class ObjectiveCyanRebindTests(unittest.TestCase):
    """The active objective ETA chip re-binds to cyan (objectives are cyan
    info, not the fintech green)."""

    def test_now_chip_references_ovx_cyan(self):
        css = _read(OVERLAY_CSS)
        m = re.search(
            r'body\[data-shell="overlay"\]\s+\.rc-co-eta\.rc-co-now\s*\{([^{}]*)\}',
            css,
            re.DOTALL,
        )
        self.assertIsNotNone(
            m, "overlay .rc-co-eta.rc-co-now rule not found")
        body = m.group(1)
        self.assertIn("--ovx-cyan", body,
                      "the NOW objective chip must reference --ovx-cyan")

    def test_upcoming_chip_recolored_off_grey(self):
        css = _read(OVERLAY_CSS)
        m = re.search(
            r'body\[data-shell="overlay"\]\s+\.rc-co-eta\s*\{([^{}]*)\}',
            css,
            re.DOTALL,
        )
        self.assertIsNotNone(
            m, "overlay .rc-co-eta base override rule not found")
        self.assertIn("--ovx-gold", m.group(1),
                      "the upcoming ETA chip must read as faint gold info")


class LeadPillFloorTests(unittest.TestCase):
    """The lead pill takes the Hextech nested backing + a font-size glance
    floor override."""

    def test_lead_line_font_size_override(self):
        css = _read(OVERLAY_CSS)
        m = re.search(
            r'body\[data-shell="overlay"\]\s+#rn-lead\s+\.rc-lead-line\s*\{([^{}]*)\}',
            css,
            re.DOTALL,
        )
        self.assertIsNotNone(
            m, "overlay #rn-lead .rc-lead-line font-size override not found")
        self.assertIn("font-size:", m.group(1),
                      "the lead line override must set a font-size")
        # No sub-floor below --fs-sm: the override must use a var() token, not
        # a bare sub-floor px literal.
        self.assertIn("var(--fs-sm)", m.group(1),
                      "lead line floor must use var(--fs-sm), not a bare px")

    def test_lead_pill_nested_backing(self):
        css = _read(OVERLAY_CSS)
        m = re.search(
            r'body\[data-shell="overlay"\]\s+#rn-lead\s*\{([^{}]*)\}',
            css,
            re.DOTALL,
        )
        self.assertIsNotNone(
            m, "overlay #rn-lead backing rule not found")
        self.assertIn("--ovx-bg-nested", m.group(1),
                      "the lead pill must take the Hextech nested backing")


class PaletteLawTests(unittest.TestCase):
    """No raw 6-digit hex color literal sits on a widget property in
    overlay.css - every hex lives in the --ovx-* token block (doctrine
    section 5)."""

    # A hex color used as a PROPERTY VALUE (e.g. `color: #abc123;` or
    # `border-color:#fff;`). Token-block hexes are annotations inside CSS
    # comments, which this pattern does not match.
    _HEX_VALUE = re.compile(r":\s*#[0-9a-fA-F]{3,6}\b")

    def test_no_hex_on_widget_property(self):
        css = _read(OVERLAY_CSS)
        # Strip CSS comments so the --ovx-* annotation hexes don't count.
        stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
        offenders = self._HEX_VALUE.findall(stripped)
        self.assertEqual(
            [], offenders,
            f"overlay.css uses raw hex color value(s) on a property: "
            f"{offenders} - route through an --ovx-* token")


class AsciiHygieneTests(unittest.TestCase):
    """No em/en-dashes or smart quotes in overlay.css per the project hard
    rule. BAD dict built via chr() so this test file stays clean against its
    own scan."""

    BAD = {
        chr(0x2013): "EN DASH",
        chr(0x2014): "EM DASH",
        chr(0x2212): "MINUS SIGN",
        chr(0x2018): "LEFT SINGLE QUOTE",
        chr(0x2019): "RIGHT SINGLE QUOTE",
        chr(0x201C): "LEFT DOUBLE QUOTE",
        chr(0x201D): "RIGHT DOUBLE QUOTE",
    }

    def test_overlay_css_is_ascii_clean(self):
        text = OVERLAY_CSS.read_text(encoding="utf-8")
        found = [name for ch, name in self.BAD.items() if ch in text]
        self.assertEqual(
            [], found,
            f"overlay.css contains forbidden non-ASCII characters: {found}")


if __name__ == "__main__":
    unittest.main()

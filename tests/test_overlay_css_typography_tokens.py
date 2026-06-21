"""
tests/test_overlay_css_typography_tokens.py

R8 (DIRECTOR REFILL 2026-06-19) - TYPOGRAPHY guard for the Electron overlay
surface. Addresses the R6 residual logged in docs/ORCHESTRATION_PLAN.md:
"overlay.css 12/13px hardcoded sub-floor sizes (Electron overlay surface,
separate audit pass)".

The overlay is a passive HUD read at GAME DISTANCE on a ~460px right-dock.
Its threat-ledger + chip-source font-sizes are DELIBERATE operator-exception
sub-floor values (item-184): 13px chips/countdowns/initials and a 12px sigil
glyph, already lifted up from the 9-11px dashboard cd_ledger densities. They
cannot bump to the global --fs-xs 16px floor (16px overflows the dense
threat ledger), so the correct treatment is TOKENIZATION - replace the bare
px literals with named, overlay-scoped CSS custom properties carrying their
rationale, instead of scattering magic numbers.

Design invariant locked here:
  - overlay.css carries NO bare px font-size literal (every font-size goes
    through a var(--fs-*) token);
  - the two overlay sub-floor tokens are defined AND referenced;
  - the sub-floor tokens are OVERLAY-SCOPED (body[data-shell="overlay"]),
    NOT added to the global tokens.css :root - the spec keeps the global
    font scale floored at --fs-xs 16px.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERLAY_CSS = ROOT / "web" / "css" / "overlay.css"
TOKENS_CSS = ROOT / "web" / "css" / "tokens.css"

# Every property declaration of the shape `font-size: <N>px` (a bare pixel
# literal, not a var() reference). The token DEFINITIONS (--fs-ov-chip: 13px)
# are custom-property declarations, not `font-size:` declarations, so this
# pattern deliberately does not match them.
_BARE_FONT_PX = re.compile(r"font-size:\s*\d+(?:\.\d+)?px", re.IGNORECASE)


def test_no_bare_subfloor_font_size_px_literals():
    """No `font-size: Npx` bare literal survives in overlay.css - every
    font-size resolves through a var(--fs-*) token (the R8 tokenization)."""
    css = OVERLAY_CSS.read_text(encoding="utf-8")
    offenders = _BARE_FONT_PX.findall(css)
    assert not offenders, (
        f"overlay.css still has bare px font-size literal(s): {offenders} - "
        "tokenize them through var(--fs-*)"
    )


def test_overlay_subfloor_tokens_defined():
    """The two overlay sub-floor type tokens are defined in overlay.css."""
    css = OVERLAY_CSS.read_text(encoding="utf-8")
    assert "--fs-ov-chip:" in css, "overlay sub-floor token --fs-ov-chip not defined"
    assert "--fs-ov-sigil:" in css, "overlay sub-floor token --fs-ov-sigil not defined"


def test_overlay_subfloor_tokens_referenced():
    """The 4 former hardcoded consumers now reference the tokens via var()."""
    css = OVERLAY_CSS.read_text(encoding="utf-8")
    assert css.count("var(--fs-ov-chip)") >= 3, (
        "expected >=3 var(--fs-ov-chip) refs (.rc-src + threat .cd-chip + "
        ".cd-row-initial)"
    )
    assert "var(--fs-ov-sigil)" in css, (
        "expected the threat .cd-chip-sigil to reference var(--fs-ov-sigil)"
    )


def test_overlay_subfloor_tokens_are_overlay_scoped_not_global():
    """Design intent: the sub-floor tokens live inside a
    body[data-shell="overlay"] rule (overlay-scoped), and the GLOBAL
    tokens.css :root keeps its floor at --fs-xs 16px (no sub-16 font token
    leaks into the shared scale)."""
    css = OVERLAY_CSS.read_text(encoding="utf-8")
    # Both tokens co-located inside an overlay-shell scoped block.
    scoped = re.search(
        r'body\[data-shell="overlay"\][^{}]*\{[^{}]*'
        r"--fs-ov-chip[^{}]*--fs-ov-sigil[^{}]*\}",
        css,
        re.DOTALL,
    )
    assert scoped, (
        "overlay sub-floor tokens must be defined inside a "
        'body[data-shell="overlay"] rule (overlay-scoped, not :root)'
    )

    # The global scale must not gain a sub-16px font token.
    tokens = TOKENS_CSS.read_text(encoding="utf-8")
    for m in re.finditer(r"--fs-[\w-]+:\s*(\d+)px", tokens):
        assert int(m.group(1)) >= 16, (
            f"tokens.css gained a sub-16px font token ({m.group(0)}); overlay "
            "sub-floor exceptions belong in overlay.css, not the global scale"
        )

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
PANELS_CSS = ROOT / "web" / "css" / "panels"

# The overlay-ONLY glance-cue panel stylesheets (each base rule is display:none
# and only body[data-shell="overlay"] shows it). They are siblings in the overlay
# CALL pane, so their chips MUST consume the overlay chip token --fs-ov-chip (13px)
# - NOT the dashboard chip token --fs-xs (16px), which out-shouts the w-call ACTION
# verb (--fs-ov-call 14px) and breaks the overlay typographic hierarchy. This is
# the same overlay-scoped-token doctrine R8 locked for overlay.css (the global
# tokens.css keeps its >=16px floor; overlay surfaces use the --fs-ov-* scale).
_OVERLAY_CUE_CSS = ("spike_cue.css", "objective_chips.css")

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


def test_overlay_cue_panels_use_overlay_chip_token():
    """R33 (DIRECTOR REFILL 2026-06-27) - the overlay-only glance cue panels
    (ward/spike/objective) size their chips on the overlay chip token
    var(--fs-ov-chip), not the dashboard var(--fs-xs). They are siblings in the
    overlay CALL pane; a 16px dashboard chip out-shouts the 14px w-call ACTION
    verb and breaks the overlay hierarchy (same doctrine R8 locked for
    overlay.css)."""
    for name in _OVERLAY_CUE_CSS:
        css = (PANELS_CSS / name).read_text(encoding="utf-8")
        assert "var(--fs-ov-chip" in css, (
            f"{name}: an overlay-only cue panel must size its chip on the overlay "
            "chip token var(--fs-ov-chip), not a dashboard font token"
        )
        # No font-size routed through the dashboard --fs-xs token on an
        # overlay-only surface (the overlay scale is --fs-ov-*).
        assert not re.search(r"font-size:\s*var\(--fs-xs\)", css), (
            f"{name}: overlay-only cue chip uses dashboard font-size "
            "var(--fs-xs) (16px); use the overlay token var(--fs-ov-chip) (13px)"
        )


def test_overlay_cue_panels_no_bare_subfloor_font_px():
    """No bare `font-size: Npx` literal in the overlay cue panel CSS - every
    font-size resolves through a var(--fs-*) token (mirrors the overlay.css
    guard). The relative-em glyph sizes (0.9em / 0.95em) are intentionally not
    pixel literals and are unaffected."""
    for name in _OVERLAY_CUE_CSS:
        css = (PANELS_CSS / name).read_text(encoding="utf-8")
        offenders = _BARE_FONT_PX.findall(css)
        assert not offenders, (
            f"{name} has bare px font-size literal(s): {offenders} - tokenize "
            "them through var(--fs-ov-chip)"
        )

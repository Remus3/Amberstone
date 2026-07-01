"""
tests/test_two_tier_tokens_oq5.py

OQ5 (QA46, operator-queue 2026-07-01) - two-tier design tokens in
web/css/tokens.css: a PRIMITIVE hue layer (rgb parts, the overlay.css
--ovx-* precedent) that the SEMANTIC tokens re-point at, with
byte-identical rendered output.

Byte-identity argument locked here:
  - each primitive's "R, G, B" parts convert EXACTLY to the historical
    hex it replaces (asserted numerically below);
  - each semantic token is a pure rgb()/rgba() wrapper over its primitive
    at the historical alpha, so every computed color is unchanged;
  - no JS reads the raw token values (web/js/lib/status.js emits
    "var(--signal-*)" indirection strings only, grep-verified 2026-07-01);
  - tests/snapshot_panels/ is the rendered-pixel proof.

The historical raw-hex semantic declarations must be GONE (the semantic
layer may no longer carry a color literal - that is the two-tier point).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "web" / "css" / "tokens.css"

# Primitive name -> (rgb parts, the historical hex it must equal).
PRIMITIVES = {
    "--prim-green": ("55, 208, 138", "#37D08A"),
    "--prim-amber": ("232, 163, 61", "#E8A33D"),
    "--prim-red":   ("232, 64, 87", "#E84057"),
    "--prim-slate": ("143, 163, 191", "#8FA3BF"),
    "--prim-blue":  ("124, 168, 255", "#7CA8FF"),
    "--prim-gold":  ("200, 170, 110", "#C8AA6E"),
    "--prim-teal":  ("10, 200, 185", "#0AC8B9"),
}

# Semantic declaration -> the exact re-pointed value.
SEMANTIC = {
    "--signal-good": "rgb(var(--prim-green))",
    "--signal-warn": "rgb(var(--prim-amber))",
    "--signal-bad": "rgb(var(--prim-red))",
    "--signal-dim": "rgb(var(--prim-slate))",
    "--signal-info": "rgb(var(--prim-blue))",
    "--signal-gold": "rgb(var(--prim-gold))",
    "--signal-good-soft": "rgba(var(--prim-green), 0.18)",
    "--signal-warn-soft": "rgba(var(--prim-amber), 0.18)",
    "--signal-bad-soft": "rgba(var(--prim-red), 0.18)",
    "--hextech-fill": "linear-gradient(90deg, rgb(var(--prim-teal)), rgb(var(--prim-gold)))",
    "--hextech-glow": "rgba(var(--prim-teal), 0.30)",
    "--hextech-border": "rgba(var(--prim-gold), 0.16)",
    "--pulse-good": "0 0 12px rgba(var(--prim-green), 0.35)",
    "--pulse-warn": "0 0 12px rgba(var(--prim-amber), 0.35)",
    "--pulse-bad": "0 0 12px rgba(var(--prim-red), 0.35)",
}

# The retired raw-literal semantic declarations (must be gone).
RETIRED = [
    "--signal-good: #37D08A",
    "--signal-warn: #E8A33D",
    "--signal-bad:  #E84057",
    "--signal-dim:  #8FA3BF",
    "--signal-info: #7CA8FF",
    "--signal-gold: #C8AA6E",
    "--signal-good-soft: rgba(55, 208, 138, 0.18)",
    "--pulse-good: 0 0 12px rgba(55, 208, 138, 0.35)",
]


def _css() -> str:
    return TOKENS.read_text(encoding="utf-8")


def _decl(css: str, name: str) -> str | None:
    m = re.search(re.escape(name) + r"\s*:\s*([^;]+);", css)
    return m.group(1).strip() if m else None


# ------------------------------------------------------------- primitives
def test_primitive_layer_declared():
    css = _css()
    for name, (parts, _hex) in PRIMITIVES.items():
        val = _decl(css, name)
        assert val is not None, f"tokens.css missing primitive {name}"
        assert re.sub(r"\s+", " ", val) == parts, (
            f"{name} = {val!r}, expected parts {parts!r}"
        )


def test_primitive_parts_equal_historical_hex():
    """Byte-identity: each parts triple converts exactly to the hex it
    replaced - the computed rgb() color is the same pixel value."""
    for name, (parts, hexval) in PRIMITIVES.items():
        nums = [int(x.strip()) for x in parts.split(",")]
        as_hex = "#" + "".join(f"{n:02X}" for n in nums)
        assert as_hex == hexval.upper(), (
            f"{name} parts {parts} -> {as_hex}, expected {hexval}"
        )


# -------------------------------------------------------------- semantics
def test_semantic_tokens_repoint_at_primitives():
    css = _css()
    for name, expected in SEMANTIC.items():
        val = _decl(css, name)
        assert val is not None, f"tokens.css missing semantic {name}"
        assert re.sub(r"\s+", " ", val) == expected, (
            f"{name} = {val!r}, expected {expected!r}"
        )


def test_retired_raw_literals_gone():
    css = _css()
    still = [r for r in RETIRED if r in css]
    assert not still, f"raw-literal semantic declaration(s) survive: {still}"


# ----------------------------------------------------------------- hygiene
def test_tokens_css_is_ascii():
    raw = TOKENS.read_bytes()
    bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
    assert not bad, f"tokens.css non-ASCII byte(s): {bad[:5]}"

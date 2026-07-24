"""Guard: R182 ui-audit-objectives - Objectives overlay surface ASCII lock.

The 5-phase overlay UI audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII /
HIERARCHY) of the in-game Objectives cluster - the respawn-timer chips
(objective_chips) and the radial ring gauges (objective_gauges), both mounted
overlay-only under `#am-obj-chips` / `#am-obj-gauges` - landed CLEAN: STRUCTURE
self-gates on body[data-shell="overlay"] with fixed geometry that never reflows
across alert tiers (the gauge CSS pins this explicitly), TYPOGRAPHY rides tokens
(--fs-ov-chip=13 documented overlay sub-floor, the one .og-eta 20px value is
ABOVE the 16px --fs-xs floor with inline rationale), HIT-TARGETS is N/A (pure
static readouts, zero clickables), and all four core files carry ZERO non-ASCII
bytes. This guard locks that clean state so a future edit cannot slip an em/en
dash or a smart quote into the surface.

Unlike the R180 roster surface, the Objectives files carry NO allowed-glyph
residual (no U+2500, no U+00D7), so the lock is total: every byte on the surface
is 7-bit ASCII.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# CLAUDE.md hard-rule banned glyphs: en dash, em dash, and the four smart quotes.
_BANNED = {0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D}

# The four core Objectives overlay surface files, all currently 100% ASCII.
_SURFACE = (
    "web/css/panels/objective_gauges.css",
    "web/css/panels/objective_chips.css",
    "web/js/panels/objective_gauges.js",
    "web/js/panels/objective_chips.js",
)


def _non_ascii(rel: str) -> list[int]:
    return [b for b in (ROOT / rel).read_bytes() if b > 127]


def test_objectives_surface_is_pure_ascii():
    for rel in _SURFACE:
        assert _non_ascii(rel) == [], rel


def test_no_banned_glyph_anywhere_in_objectives_surface():
    for rel in _SURFACE:
        txt = (ROOT / rel).read_text(encoding="utf-8")
        hits = sorted({hex(ord(c)) for c in txt if ord(c) in _BANNED})
        assert hits == [], (rel, hits)


def test_objectives_surface_has_no_allowed_glyph_residual():
    # Total lock: unlike the roster surface, Objectives carries no U+2500 /
    # U+00D7 residual. If any non-ASCII byte appears, the lock has been broken.
    for rel in _SURFACE:
        txt = (ROOT / rel).read_text(encoding="utf-8")
        residual = sorted({ord(c) for c in txt if ord(c) > 127})
        assert residual == [], (rel, [hex(c) for c in residual])

"""Guard: R180 ui-audit-roster - Player Roster / Matchup overlay surface ASCII lock.

The 5-phase overlay UI audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII /
HIERARCHY) of the in-game Roster (`.am-map-roster` in active_match) + the
champ-select Matchup card (ds_matchup) landed CLEAN: font-sizes ride tokens
(--fs-xs=16 above the 13px tertiary floor), hit-targets use --hit-min (42) with
the roster rows exempt as pointer-events:none readouts, and the four core
surface files carry ZERO non-ASCII bytes. This guard locks that clean state so
a future edit cannot slip an em/en dash or a smart quote into the surface.

The adjacent champ-select team_context.css keeps 20 U+2500 box-drawing rules in
its comment header (operator-allowed globally per test_u2500_hygiene.py scope
note) plus a single U+00D7 in a "5x5 grid" comment. Neither is a CLAUDE.md
hard-rule glyph (the ban is em/en dash + the four smart quotes), so they are
NOT swept here; this guard PINS that residual so no banned glyph can hide behind
the allowed set, and the U+00D7 stays flagged as the only shrinkable byte for a
future ASCII-purity pass.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# CLAUDE.md hard-rule banned glyphs: en dash, em dash, and the four smart quotes.
_BANNED = {0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D}

# The four core Roster / Matchup overlay surface files, all currently 100% ASCII.
_SURFACE = (
    "web/css/panels/active_match.css",
    "web/css/panels/ds_matchup.css",
    "web/js/panels/active_match.js",
    "web/js/panels/ds_matchup.js",
)


def _non_ascii(rel: str) -> list[int]:
    return [b for b in (ROOT / rel).read_bytes() if b > 127]


def test_roster_matchup_surface_is_pure_ascii():
    for rel in _SURFACE:
        assert _non_ascii(rel) == [], rel


def test_no_banned_glyph_anywhere_in_surface_including_team_context():
    # team_context.css is allowed its U+2500 + U+00D7 residual, but NO file on
    # the wider surface may carry an em/en dash or a smart quote.
    for rel in (*_SURFACE, "web/css/panels/team_context.css"):
        txt = (ROOT / rel).read_text(encoding="utf-8")
        hits = sorted({hex(ord(c)) for c in txt if ord(c) in _BANNED})
        assert hits == [], (rel, hits)


def test_team_context_residual_is_only_allowed_glyphs():
    # Pin the adjacent-file residual: exactly U+2500 (allowed rule) + U+00D7
    # (flagged FUTURE). If it shrinks to just U+2500, tighten this assertion.
    txt = (ROOT / "web/css/panels/team_context.css").read_text(encoding="utf-8")
    residual = sorted({ord(c) for c in txt if ord(c) > 127})
    assert residual == [0x00D7, 0x2500], [hex(c) for c in residual]

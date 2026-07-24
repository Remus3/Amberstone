"""Guard: R183 ui-audit-skill-order - Skill Order overlay surface ASCII lock.

The 5-phase overlay UI audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII /
HIERARCHY) of the DS Skill Order / ability-max-order card - the locked
champion's "Max: Q > E > W" headline plus the ult level-ups line, mounted in
the champ-select Suggestions card under `#csv-sugg-ds-skill-order` - landed
CLEAN: STRUCTURE is a flex-column card mirroring the ds-profile sibling
(head title + sub, max line, ult line), TYPOGRAPHY rides tokens (--fs-sm 18px,
--fs-xs 16px; no hardcoded px below the 16px --fs-xs floor), HIT-TARGETS is N/A
(pure static readout, zero clickables), and both surface files carry ZERO
non-ASCII bytes. The ability priority renders with the 7-bit ASCII '>' glyph -
no unicode arrows (repo ASCII hard rule). This guard locks that clean state so a
future edit cannot slip an em/en dash, a smart quote, or a unicode arrow into
the surface.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# CLAUDE.md hard-rule banned glyphs: en dash, em dash, and the four smart quotes.
_BANNED = {0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D}

# The two Skill Order overlay surface files, both currently 100% ASCII.
_SURFACE = (
    "web/js/panels/ds_skill_order.js",
    "web/css/panels/ds_skill_order.css",
)


def _non_ascii(rel: str) -> list[int]:
    return [b for b in (ROOT / rel).read_bytes() if b > 127]


def test_skill_order_surface_is_pure_ascii():
    for rel in _SURFACE:
        assert _non_ascii(rel) == [], rel


def test_no_banned_glyph_anywhere_in_skill_order_surface():
    for rel in _SURFACE:
        txt = (ROOT / rel).read_text(encoding="utf-8")
        hits = sorted({hex(ord(c)) for c in txt if ord(c) in _BANNED})
        assert hits == [], (rel, hits)


def test_skill_order_surface_has_no_allowed_glyph_residual():
    # Total lock: the Skill Order surface carries no U+2500 / U+00D7 residual.
    # If any non-ASCII byte appears, the lock has been broken.
    for rel in _SURFACE:
        txt = (ROOT / rel).read_text(encoding="utf-8")
        residual = sorted({ord(c) for c in txt if ord(c) > 127})
        assert residual == [], (rel, [hex(c) for c in residual])

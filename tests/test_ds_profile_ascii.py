"""Guard: R184 ui-audit-ds-profile - DS Profile champ-select card ASCII lock.

The 5-phase champ-select UI audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII /
HIERARCHY) of the DS Profile card - the LOCKED champion's kit shape rendered as
eight labelled horizontal bars (Mobility / Sustain / Scaling / Waveclear / Range
/ Zone / Objective / Duel), mounted in the champ-select Suggestions card under
`#csv-sugg-ds-profile` as a sibling of the ds-skill-order / cooldown-watch /
cc-conditional-pressure cards - landed CLEAN: STRUCTURE is a flex-column card of
grid rows (label | track | value | detail) with a sig-dedup gate over
champion|axis-key:pct:tier and fail-soft `hidden=true` on null / not-ok / empty
axes (HONEST NO-DATA), TYPOGRAPHY rides tokens (--fs-sm 18px on the head title,
--fs-xs 16px on every other row; no hardcoded font-size below the 16px --fs-xs
floor - the em/px values present are track height + radius + grid columns, not
font-sizes), HIT-TARGETS is N/A (pure static readout, zero clickables), and both
surface files carry ZERO non-ASCII bytes. The scaling trajectory renders with
7-bit ASCII words (up/flat/down) - no unicode arrows (repo ASCII hard rule). This
guard locks that clean state so a future edit cannot slip an em/en dash, a smart
quote, or a unicode arrow into the surface.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# CLAUDE.md hard-rule banned glyphs: en dash, em dash, and the four smart quotes.
_BANNED = {0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D}

# The two DS Profile champ-select surface files, both currently 100% ASCII.
_SURFACE = (
    "web/js/panels/ds_profile.js",
    "web/css/panels/ds_profile.css",
)


def _non_ascii(rel: str) -> list[int]:
    return [b for b in (ROOT / rel).read_bytes() if b > 127]


def test_ds_profile_surface_is_pure_ascii():
    for rel in _SURFACE:
        assert _non_ascii(rel) == [], rel


def test_no_banned_glyph_anywhere_in_ds_profile_surface():
    for rel in _SURFACE:
        txt = (ROOT / rel).read_text(encoding="utf-8")
        hits = sorted({hex(ord(c)) for c in txt if ord(c) in _BANNED})
        assert hits == [], (rel, hits)


def test_ds_profile_surface_has_no_allowed_glyph_residual():
    # Total lock: the DS Profile surface carries no U+2500 / U+00D7 residual.
    # If any non-ASCII byte appears, the lock has been broken.
    for rel in _SURFACE:
        txt = (ROOT / rel).read_text(encoding="utf-8")
        residual = sorted({ord(c) for c in txt if ord(c) > 127})
        assert residual == [], (rel, [hex(c) for c in residual])

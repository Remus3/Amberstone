"""P3 A3b-2 / item 428 - role/SR-profile prompt-substrate ASCII guard.

`role_profiles.py` (combo arrows U+2192 in role prose + U+2022 laning/ARAM
bullets) and `coach_integration/_profiles.py` + `coach_integration/_sr_prompt.py`
(U+2192 in CHAMPION_PROFILES mechanics text + the SR `full_build` join) carried
RAW non-ASCII bytes. Those were converted under the no-em-dash / ASCII-only repo
rule: arrows U+2192 -> "->", leading list bullets U+2022 -> "- " (a list marker,
NOT the GLYPH_MAP "*" = multiply), and the join separator -> " -> ".

Split-on safety: the ONLY repo consumers that re.split on the U+2192 char are
`coaches/aram_coach.py:147` (Haiku item_build wire) and
`scripts/audit_ddragon_items.py:86` (golden sim fixtures) - neither reads these
files, so converting the arrow here is non-load-bearing.

SCOPE = SOURCE BYTES only (the P3 byte-purge invariant). `_sr_prompt.py` and
`role_profiles.aram_item_context` still hold `\\uXXXX` ESCAPES (em-dashes /
U+2550 banners / U+2192) that emit non-ASCII at runtime; those are ASCII source
(out of P3 byte-scope, cycle-22 precedent) and are a deferred escaped-glyph
sub-slice - so this guard asserts source bytes, NOT emitted output.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_FILES = [
    _ROOT / "role_profiles.py",
    _ROOT / "coach_integration" / "_profiles.py",
    _ROOT / "coach_integration" / "_sr_prompt.py",
]
_ARROW = chr(0x2192)
_BULLET = chr(0x2022)


def test_profile_sources_are_pure_ascii():
    for f in _FILES:
        text = f.read_text(encoding="utf-8")
        bad = [
            (i + 1, ch)
            for i, line in enumerate(text.splitlines())
            for ch in line
            if ord(ch) > 0x7F
        ]
        assert not bad, f"{f.name} has non-ASCII glyphs: {bad[:10]}"


def test_no_raw_arrow_or_bullet_chars():
    # The literal U+2192 / U+2022 chars must never reappear as raw bytes in
    # these files (escapes are checked separately - they are ASCII source).
    for f in _FILES:
        src = f.read_text(encoding="utf-8")
        assert _ARROW not in src, f"{f.name} reintroduced a raw U+2192 arrow"
        assert _BULLET not in src, f"{f.name} reintroduced a raw U+2022 bullet"


def test_converted_tokens_pinned():
    rp = _FILES[0].read_text(encoding="utf-8")
    assert "Q->E->W" in rp           # Viktor combo arrow -> ASCII
    assert "- Do not fight." in rp    # leading bullet kept its space
    assert "- 1st item:" in rp        # ARAM_ITEM_RULES bullet
    sr = _FILES[2].read_text(encoding="utf-8")
    assert '" -> ".join(fb)' in sr    # full_build join separator

"""P2 W5 cycle 16: sweep slice-A's decorative non-ASCII glyphs to ASCII.

Slice A read the W5 ASCII lens narrowly and left these; B/C/D/E/F converted
the same decorative class. This brings the test corpus to a consistent state.
Only comments/docstrings/dividers - no executable string literals, no
load-bearing separators. The 2 load-bearing files are intentionally excluded.
"""
import pathlib

# Decorative-glyph -> ASCII map (union of what the slice agents normalized).
GLYPHS = {
    "→": "->",   # rightwards arrow
    "↔": "<->",  # left-right arrow
    "─": "-",    # box-drawings light horizontal
    "−": "-",    # minus sign
    "×": "x",    # multiplication sign
    "≈": "~",    # almost equal to
    "≥": ">=",   # greater-than or equal to
    "≤": "<=",   # less-than or equal to
}

TARGETS = [
    "tests/fu01_minimap/test_minimap_bbox.py",
    "tests/fu02_team_context/test_lcu_agent_refresh.py",
    "tests/phase2_smoke/test_daemon_slayer_resolver_modes.py",
    "tests/phase_b_champ_select/test_lcu_mastery.py",
    "tests/test_build_order.py",
    "tests/test_last_match_timeline.py",
]

for rel in TARGETS:
    p = pathlib.Path(rel)
    text = p.read_text(encoding="utf-8")
    orig = text
    for g, a in GLYPHS.items():
        text = text.replace(g, a)
    remaining = sorted({ch for ch in text if ord(ch) > 127})
    if remaining:
        print(f"WARN {rel}: residual non-ascii {[hex(ord(c)) for c in remaining]}")
    if text != orig:
        # LF only (repo EOL guard); atomic replace.
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        tmp.replace(p)
        print(f"swept {rel}")
    else:
        print(f"nochange {rel}")

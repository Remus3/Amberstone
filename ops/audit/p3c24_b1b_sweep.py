"""DEEP-AUDIT P3 cycle 24 (item 420) slice B1b - DS-engine ASCII string-glyph sweep.

Completes the DS-engine tree ASCII retro-sweep that B1a (cycle 23) started:
B1a swept comment + docstring tokens; B1b sweeps the residual STRING-token
glyphs (emit-notes / f-string display text / HTML help) plus the 4 registry
JSON _meta metadata fields. Per-hit judgement already done (every glyph is
display-only; sole structural consumer = tests/test_effects_expansion.py:3892,
updated in lockstep). Application is the same conservative GLYPH_MAP the cycle
19-23 sweeps used, with ONE per-hit override: beam.py's item-name list
separator " . " (U+00B7 middot) becomes " / " not "*" (middot-as-separator,
not middot-as-multiply).

Run from repo root. Writes LF atomically (reference_repo_eol_crlf_guard).
Proof of safety = ops/audit/p3c24_token_equiv.py (non-string tokens
byte-identical to HEAD; string tokens differ ONLY by this transform).
"""

import os
import sys
from pathlib import Path

# Subset of tools/p3_ascii_sweep.GLYPH_MAP - exactly the glyphs the DS-engine
# residual holds (verified via ops/audit census). Identical mappings.
GLYPH_MAP = {
    "×": "x",       # MULTIPLICATION SIGN
    "÷": "/",       # DIVISION SIGN
    "→": "->",      # RIGHTWARDS ARROW
    "≤": "<=",      # LESS-THAN OR EQUAL TO
    "≥": ">=",      # GREATER-THAN OR EQUAL TO
    "≠": "!=",      # NOT EQUAL TO
    "≈": "~",       # ALMOST EQUAL TO
    "−": "-",       # MINUS SIGN
    "·": "*",       # MIDDLE DOT (multiply, default)
    "•": "*",       # BULLET
    "✓": "ok",      # CHECK MARK
    "α": "alpha",   # GREEK SMALL ALPHA
    "β": "beta",    # GREEK SMALL BETA
}

PY_FILES = [
    "agents/daemon_slayer/_effects_data.py",
    "agents/daemon_slayer/burst.py",
    "agents/daemon_slayer/dps.py",
    "agents/daemon_slayer/ability_dps.py",
    "agents/daemon_slayer/hybrid.py",
    "agents/daemon_slayer/server.py",
    "agents/daemon_slayer/beam.py",
    "agents/daemon_slayer/ehp.py",
    "agents/daemon_slayer/rank.py",
]
JSON_FILES = [
    "agents/daemon_slayer/champion_block_index.json",
    "agents/daemon_slayer/champion_form_index.json",
    "agents/daemon_slayer/archetype_weights.json",
    "agents/daemon_slayer/champion_max_priority.json",
]


def transform(text: str, path: str) -> str:
    """The canonical B1b text transform (shared contract with the proof)."""
    # per-hit override: beam.py item-name separator middot -> " / "
    if path.replace("\\", "/").endswith("agents/daemon_slayer/beam.py"):
        text = text.replace(" · ", " / ")
    for glyph, ascii_ in GLYPH_MAP.items():
        text = text.replace(glyph, ascii_)
    return text


def _atomic_write_lf(path: Path, text: str) -> None:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    tmp = path.with_suffix(path.suffix + ".b1btmp")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(path)


def main() -> int:
    total_before = total_after = files_changed = 0
    for rel in PY_FILES + JSON_FILES:
        p = Path(rel)
        src = p.read_bytes().decode("utf-8")
        before = sum(1 for c in src if ord(c) > 127)
        out = transform(src, rel)
        after = sum(1 for c in out if ord(c) > 127)
        total_before += before
        total_after += after
        if out != src:
            _atomic_write_lf(p, out)
            files_changed += 1
        flag = "  <-- RESIDUAL NON-ASCII" if after else ""
        print(f"  {rel}: {before} -> {after} glyphs{flag}")
        if after:
            for c in out:
                if ord(c) > 127:
                    print(f"      UNMAPPED {hex(ord(c))}")
                    return 2
    print(f"TOTAL glyphs {total_before} -> {total_after}; files changed {files_changed}")
    return 0 if total_after == 0 else 2


if __name__ == "__main__":
    sys.exit(main())

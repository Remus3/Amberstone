"""P3 SAFE-BULK ASCII glyph sweep (DEEP-AUDIT phase P3, slice A).

Rewrites decorative non-ASCII glyphs to ASCII *inside Python COMMENT tokens
only*. Comments are never emitted to output, never asserted on by tests, and
never parsed - so a comment-token-scoped swap is a provable zero-behavior-change
edit (the cycle-16/17 in-line-balanced-swap discipline, made mechanical).

STRING-token glyphs are left untouched this slice - that auto-protects every
load-bearing emitted/regex-matched arrow (DS-engine dps.py note, aram_coach
item_build wire-split) which lives in a string, not a comment.

Usage:
  p3_ascii_sweep.py --dry-run <path...>     # report, no write
  p3_ascii_sweep.py --apply   <path...>     # rewrite in place (LF preserved)
  p3_ascii_sweep.py --unmapped <path...>    # list comment glyphs with NO mapping

Only glyphs in GLYPH_MAP are touched; an unmapped comment glyph is reported and
left as-is (conservative - never guess a substitution).
"""
from __future__ import annotations

import sys
import tokenize
from pathlib import Path

# Conservative, unambiguous decorative/divider/math substitutions.
GLYPH_MAP = {
    "─": "-", "═": "=", "│": "|",
    "┌": "+", "┐": "+", "└": "+", "┘": "+",
    "├": "+", "┤": "+", "┬": "+", "┴": "+", "┼": "+",
    "▼": "v", "▲": "^", "►": ">", "◄": "<",
    "▶": ">", "◀": "<", "▸": ">", "▾": "v", "▴": "^",
    "×": "x", "÷": "/", "≈": "~",
    "≤": "<=", "≥": ">=", "≠": "!=", "≡": "==",
    "≪": "<<", "≫": ">>",
    "±": "+/-", "−": "-", "·": "*", "•": "*",
    "∈": "in",
    "→": "->", "←": "<-", "↔": "<->",
    "↗": "->", "↘": "->", "↖": "<-", "↙": "<-",
    "↑": "^", "↓": "v", "⇒": "=>", "⇄": "<->", "↕": "^v",
    "α": "alpha", "β": "beta", "Σ": "sum", "Δ": "delta",
    "λ": "lambda",
    "✓": "ok", "✗": "x", "…": "...",
    "§": "S", "‹": "<", "›": ">", "※": "*",
    "⨝": "join",
}


def _is_ascii(s: str) -> bool:
    return all(ord(c) < 128 for c in s)


def _comment_spans(path: Path):
    """Return list of (row, start_col) for every COMMENT token in a .py file."""
    spans = []
    with open(path, "rb") as f:
        for tok in tokenize.tokenize(f.readline):
            if tok.type == tokenize.COMMENT:
                spans.append((tok.start[0], tok.start[1]))
    return spans


def sweep_file(path: Path, apply: bool):
    """Returns (changed_count, unmapped_set). Comment-token glyphs only."""
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    if _is_ascii(text):
        return 0, set()
    lines = text.split("\n")
    try:
        spans = _comment_spans(path)
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        print(f"  TOKENIZE-FAIL {path}: {exc}", file=sys.stderr)
        return 0, set()
    changed = 0
    unmapped = set()
    for row, col in spans:
        line = lines[row - 1]
        comment = line[col:]
        if _is_ascii(comment):
            continue
        out = []
        for ch in comment:
            if ord(ch) < 128:
                out.append(ch)
            elif ch in GLYPH_MAP:
                out.append(GLYPH_MAP[ch])
                changed += 1
            else:
                out.append(ch)
                unmapped.add(ch)
        lines[row - 1] = line[:col] + "".join(out)
    if apply and changed:
        path.write_bytes("\n".join(lines).encode("utf-8"))
    return changed, unmapped


def _iter_targets(paths):
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            yield from sorted(pp.rglob("*.py"))
        elif pp.suffix == ".py":
            yield pp


def main(argv):
    mode = argv[0] if argv else "--dry-run"
    targets = list(_iter_targets(argv[1:]))
    total = 0
    all_unmapped = {}
    for t in targets:
        try:
            changed, unmapped = sweep_file(t, apply=(mode == "--apply"))
        except Exception as exc:  # noqa: BLE001
            print(f"  ERR {t}: {exc}", file=sys.stderr)
            continue
        if changed:
            total += changed
            verb = "WROTE" if mode == "--apply" else "would-change"
            print(f"  {verb} {changed:5d}  {t.as_posix()}")
        for ch in unmapped:
            all_unmapped.setdefault(ch, []).append(t.as_posix())
    print(f"\nTOTAL comment-glyph substitutions: {total} across {len(targets)} files")
    if all_unmapped:
        print("\nUNMAPPED comment glyphs (left as-is):")
        for ch, files in sorted(all_unmapped.items()):
            print(f"  U+{ord(ch):04X} {ch!r}  in {len(files)} file(s): {files[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

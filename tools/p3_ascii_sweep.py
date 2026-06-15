"""P3 SAFE-BULK ASCII glyph sweep (DEEP-AUDIT phase P3, slice A).

Rewrites decorative non-ASCII glyphs to ASCII *inside Python COMMENT tokens
only*. Comments are never emitted to output, never asserted on by tests, and
never parsed - so a comment-token-scoped swap is a provable zero-behavior-change
edit (the cycle-16/17 in-line-balanced-swap discipline, made mechanical).

STRING-token glyphs are left untouched this slice - that auto-protects every
load-bearing emitted/regex-matched arrow (DS-engine dps.py note, aram_coach
item_build wire-split) which lives in a string, not a comment.

Slice A3a (cycle 21) adds an opt-in DOCSTRING mode: the same GLYPH_MAP applied
inside module / function / class docstring STRING tokens (located via AST, so
only true docstrings - never an f-string, never a split-on/regex-matched code
string). A docstring is not emitted to coach output, not split-on, not
regex-matched by production; its only consumers are argparse --help (cosmetic)
and a handful of tests that assertIn() ASCII substrings (immune to a decorative
glyph swap). Same provable-safe class as comments, suite-gated.

Usage:
  p3_ascii_sweep.py --dry-run  <path...>    # comment report, no write
  p3_ascii_sweep.py --apply    <path...>    # rewrite comment glyphs (LF preserved)
  p3_ascii_sweep.py --unmapped <path...>    # list comment glyphs with NO mapping
  p3_ascii_sweep.py --doc-dry  <path...>    # docstring report, no write
  p3_ascii_sweep.py --doc-apply <path...>   # rewrite docstring glyphs (LF preserved)
  p3_ascii_sweep.py --doc-unmapped <path...> # list docstring glyphs with NO mapping

Only glyphs in GLYPH_MAP are touched; an unmapped glyph is reported and left
as-is (conservative - never guess a substitution).
"""
from __future__ import annotations

import ast
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
    "✓": "ok", "✗": "x",  # checkmarks; ellipsis U+2026 added below via chr() (hygiene guard bans the literal)
    "§": "S", "‹": "<", "›": ">", "※": "*",
    "⨝": "join",
}
# U+2026 (horizontal ellipsis) keyed via chr() - the authored-source hygiene
# guard (tests/test_smart_quote_hygiene.py) bans the literal glyph in source.
GLYPH_MAP[chr(0x2026)] = "..."


def _is_ascii(s: str) -> bool:
    return all(ord(c) < 128 for c in s)


def _apply_map(s: str):
    """Map every GLYPH_MAP glyph in s to ASCII. Returns (out, changed, unmapped)."""
    out = []
    changed = 0
    unmapped = set()
    for ch in s:
        if ord(ch) < 128:
            out.append(ch)
        elif ch in GLYPH_MAP:
            out.append(GLYPH_MAP[ch])
            changed += 1
        else:
            out.append(ch)
            unmapped.add(ch)
    return "".join(out), changed, unmapped


LOG_ATTRS = {"debug", "info", "warning", "warn", "error", "critical", "exception"}
LOG_ROOTS = {"log", "logger", "logging", "_log", "_logger", "LOG", "LOGGER", "_LOG"}


def _attr_root_name(node):
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _is_log_or_print_call(call):
    """True iff call is print(...) or <log-root>.<level>(...). Diagnostic-only."""
    f = call.func
    if isinstance(f, ast.Name) and f.id == "print":
        return True
    if isinstance(f, ast.Attribute) and f.attr in LOG_ATTRS:
        return _attr_root_name(f.value) in LOG_ROOTS
    return False


def _logstr_node_spans(path: Path):
    """Abs (start,end) char offsets of every str-Constant inside a log/print call.

    Walks each target call and collects every string Constant descendant.
    Diagnostic log/console output is the closest string-class to a comment:
    never asserted on by a glyph (the only tests holding these glyphs are the
    deferred aram peer suite + the snapshot fixtures, neither of which logs),
    never split-on, never an LLM prompt.

    LIMITATION (CPython 3.14 / PEP 701): an f-string literal SEGMENT that follows
    an interpolation reports a shifted col_offset, so a glyph there is silently
    MISSED (never mis-spliced - the wrong slice maps to a no-op; py_compile and a
    residual re-scan both stay clean). Always re-scan with --log-dry after a
    --log-apply and hand-fix any residual in a post-interpolation f-string segment.
    """
    text = path.read_bytes().decode("utf-8")
    tree = ast.parse(text)
    lines = text.split("\n")
    offs = [0]
    for ln in lines:
        offs.append(offs[-1] + len(ln) + 1)
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_log_or_print_call(node):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    if sub.end_lineno is None:
                        continue
                    abs_s = offs[sub.lineno - 1] + sub.col_offset
                    abs_e = offs[sub.end_lineno - 1] + sub.end_col_offset
                    spans.append((abs_s, abs_e))
    return text, spans


def sweep_file_logstrings(path: Path, apply: bool):
    """Returns (changed_count, unmapped_set). Glyphs in log/print str-args only."""
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    if _is_ascii(text):
        return 0, set()
    try:
        text, spans = _logstr_node_spans(path)
    except (SyntaxError, ValueError) as exc:
        print(f"  AST-FAIL {path}: {exc}", file=sys.stderr)
        return 0, set()
    if not spans:
        return 0, set()
    edits = []
    changed = 0
    unmapped = set()
    for abs_s, abs_e in spans:
        seg = text[abs_s:abs_e]
        if _is_ascii(seg):
            continue
        out, n, um = _apply_map(seg)
        if n:
            edits.append((abs_s, abs_e, out))
            changed += n
            unmapped |= um
    if apply and edits:
        for abs_s, abs_e, out in sorted(edits, reverse=True):
            text = text[:abs_s] + out + text[abs_e:]
        path.write_bytes(text.encode("utf-8"))
    return changed, unmapped


def _docstring_spans(path: Path):
    """Return set of (start_row, end_row) for module/func/class docstrings."""
    tree = ast.parse(path.read_bytes().decode("utf-8"))
    spans = set()

    def _doc(node):
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(
            body[0].value, ast.Constant
        ) and isinstance(body[0].value.value, str):
            c = body[0].value
            spans.add((c.lineno, c.end_lineno or c.lineno))

    _doc(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            _doc(node)
    return spans


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
        out, n, um = _apply_map(comment)
        changed += n
        unmapped |= um
        lines[row - 1] = line[:col] + out
    if apply and changed:
        path.write_bytes("\n".join(lines).encode("utf-8"))
    return changed, unmapped


def sweep_file_docstrings(path: Path, apply: bool):
    """Returns (changed_count, unmapped_set). Docstring STRING-token glyphs only.

    Splices by absolute char offset (a docstring token may span many rows);
    replacements applied right-to-left so earlier offsets stay valid.
    """
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    if _is_ascii(text):
        return 0, set()
    try:
        spans = _docstring_spans(path)
    except (SyntaxError, ValueError) as exc:
        print(f"  AST-FAIL {path}: {exc}", file=sys.stderr)
        return 0, set()
    if not spans:
        return 0, set()
    lines = text.split("\n")
    offs = [0]
    for ln in lines:
        offs.append(offs[-1] + len(ln) + 1)  # +1 for the split '\n'
    edits = []
    changed = 0
    unmapped = set()
    try:
        toks = list(tokenize.tokenize(path.open("rb").readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        print(f"  TOKENIZE-FAIL {path}: {exc}", file=sys.stderr)
        return 0, set()
    for tok in toks:
        if tok.type != tokenize.STRING:
            continue
        srow, scol = tok.start
        erow, ecol = tok.end
        if not any(a <= srow and erow <= b for a, b in spans):
            continue
        if _is_ascii(tok.string):
            continue
        out, n, um = _apply_map(tok.string)
        if n:
            abs_s = offs[srow - 1] + scol
            abs_e = offs[erow - 1] + ecol
            edits.append((abs_s, abs_e, out))
            changed += n
            unmapped |= um
    if apply and edits:
        for abs_s, abs_e, out in sorted(edits, reverse=True):
            text = text[:abs_s] + out + text[abs_e:]
        path.write_bytes(text.encode("utf-8"))
    return changed, unmapped


def _iter_targets(paths):
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            yield from sorted(pp.rglob("*.py"))
        elif pp.suffix == ".py":
            yield pp


DOC_MODES = ("--doc-dry", "--doc-apply", "--doc-unmapped")
LOG_MODES = ("--log-dry", "--log-apply", "--log-unmapped")


def main(argv):
    mode = argv[0] if argv else "--dry-run"
    doc = mode in DOC_MODES
    logm = mode in LOG_MODES
    apply = mode in ("--apply", "--doc-apply", "--log-apply")
    if logm:
        fn, label = sweep_file_logstrings, "log/print-string"
    elif doc:
        fn, label = sweep_file_docstrings, "docstring"
    else:
        fn, label = sweep_file, "comment"
    targets = list(_iter_targets(argv[1:]))
    total = 0
    all_unmapped = {}
    for t in targets:
        try:
            changed, unmapped = fn(t, apply=apply)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERR {t}: {exc}", file=sys.stderr)
            continue
        if changed:
            total += changed
            verb = "WROTE" if apply else "would-change"
            print(f"  {verb} {changed:5d}  {t.as_posix()}")
        for ch in unmapped:
            all_unmapped.setdefault(ch, []).append(t.as_posix())
    print(f"\nTOTAL {label}-glyph substitutions: {total} across {len(targets)} files")
    if all_unmapped:
        print(f"\nUNMAPPED {label} glyphs (left as-is):")
        for ch, files in sorted(all_unmapped.items()):
            print(f"  U+{ord(ch):04X} {ch!r}  in {len(files)} file(s): {files[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

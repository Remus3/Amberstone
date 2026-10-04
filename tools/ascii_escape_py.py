"""Make tracked .py SOURCE 7-bit ASCII without changing what the code does (RM-300).

Sibling of tools/strip_em_dashes.py and tools/strip_smart_quotes.py. Those two
REPLACE a glyph with an ASCII look-alike, which is right for prose and wrong for
code: a non-ASCII character inside a string literal is a runtime VALUE (a
rendered arrow, a CJK summoner name in a test fixture, a regex character class,
a model prompt), and swapping it for '->' silently changes output that other
code and tests consume. So this tool works per TOKEN:

  * string literal (incl. f-string text) -> the same character as a Python
    escape (\\xNN, \\uNNNN, \\UNNNNNNNN). The source becomes ASCII, the value the
    interpreter builds is byte-identical, and the tool PROVES that by comparing
    the AST of the file before and after (``ast.dump`` equal) - a rewrite that
    changes any constant is refused.
  * comment or docstring -> an ASCII transliteration (prose, nobody consumes
    it as a value; an escape there would just be unreadable). A docstring IS a
    constant, so it is excluded from the AST-equality proof and nothing else is.
  * raw string -> REFUSED and reported. ``r"\\u2192"`` is a backslash and a 'u',
    not an arrow, so an escape would change the value. Fix those by hand (for a
    regex pattern, ``re`` itself understands \\uNNNN, so writing the escape in
    the raw string is correct there - and only there).

Exemptions come from ``tools/precommit_gate._ascii_exempt``, the SAME predicate
the commit gate uses, so the gate, this tool and the guard
(tests/test_py_source_ascii_rm300.py) have one reading of "authored".

Usage:
  python tools/ascii_escape_py.py              # dry-run census of tracked .py
  python tools/ascii_escape_py.py --apply      # rewrite in place (atomic)
  python tools/ascii_escape_py.py --apply a.py b.py   # only these files
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import io
import subprocess
import sys
import tokenize
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Prose transliterations for comments and docstrings. Anything not listed
# falls back to the literal text "U+XXXX", which is ASCII and still says what
# was there.
_PROSE = {
    0x00A0: " ", 0x00B7: "/", 0x00D7: "x", 0x00F7: "/",
    0x2013: " - ", 0x2014: " - ", 0x2018: "'", 0x2019: "'",
    0x201C: '"', 0x201D: '"', 0x2022: "*", 0x2026: "...",
    0x2190: "<-", 0x2192: "->", 0x2194: "<->", 0x2191: "^", 0x2193: "v",
    0x2212: "-", 0x2248: "~", 0x2260: "!=", 0x2264: "<=", 0x2265: ">=",
    0x2500: "-", 0x2550: "=", 0x2713: "ok", 0x2717: "x", 0x26A0: "!",
}


def _gate():
    spec = importlib.util.spec_from_file_location(
        "precommit_gate_for_ascii_escape", REPO / "tools" / "precommit_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _escape(ch: str) -> str:
    cp = ord(ch)
    if cp <= 0xFF:
        return f"\\x{cp:02x}"
    if cp <= 0xFFFF:
        return f"\\u{cp:04x}"
    return f"\\U{cp:08x}"


def _prose(ch: str) -> str:
    cp = ord(ch)
    return _PROSE.get(cp, f"U+{cp:04X}")


def _docstring_lines(tree: ast.AST) -> set[int]:
    """Every source line covered by a module / class / function docstring."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            out.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return out


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            first.value.value = ""
    return tree


def _is_raw(prefix_tok: str) -> bool:
    prefix = ""
    for c in prefix_tok:
        if c in "'\"":
            break
        prefix += c
    return "r" in prefix.lower()


class RawStringError(ValueError):
    pass


def convert(text: str, name: str = "<src>") -> str:
    """Return ``text`` with every non-ASCII character made ASCII per token kind.

    Raises RawStringError for non-ASCII inside a raw string, and ValueError if
    the rewrite would change any non-docstring constant (AST inequality).
    """
    if all(ord(c) < 128 for c in text):
        return text
    tree = ast.parse(text, name)
    doc_lines = _docstring_lines(tree)
    # readlines, not splitlines: splitlines also breaks on \x0c / \x1c..., which
    # tokenize does not, and the (row, col) positions below are tokenize's.
    lines = io.StringIO(text).readlines()
    # (row, col) -> replacement for each non-ASCII char, decided by its token.
    plan: dict[tuple[int, int], str] = {}
    fstring_raw: list[bool] = []
    toks = tokenize.generate_tokens(io.StringIO(text).readline)
    for tok in toks:
        tname = tokenize.tok_name[tok.type]
        if tname in ("FSTRING_START", "TSTRING_START"):
            fstring_raw.append(_is_raw(tok.string))
            continue
        if tname in ("FSTRING_END", "TSTRING_END"):
            fstring_raw.pop()
            continue
        if tok.type not in (tokenize.STRING, tokenize.COMMENT) and tname not in (
                "FSTRING_MIDDLE", "TSTRING_MIDDLE"):
            continue
        (sr, sc), (er, ec) = tok.start, tok.end
        for row in range(sr, er + 1):
            line = lines[row - 1]
            c0 = sc if row == sr else 0
            c1 = ec if row == er else len(line)
            for col in range(c0, c1):
                ch = line[col]
                if ord(ch) < 128:
                    continue
                if tok.type == tokenize.COMMENT:
                    plan[(row, col)] = _prose(ch)
                elif tok.type == tokenize.STRING and row in doc_lines:
                    plan[(row, col)] = _prose(ch)
                else:
                    if tok.type == tokenize.STRING and fstring_raw:
                        # A string nested in an f-string replacement field:
                        # a backslash there is a SyntaxError before 3.12
                        # (ruff target py39). Hoist it to a variable by hand.
                        raise RawStringError(
                            f"{name}:{row}: U+{ord(ch):04X} inside an f-string "
                            f"expression - hoist it to a variable by hand")
                    raw = (_is_raw(tok.string) if tok.type == tokenize.STRING
                           else fstring_raw[-1])
                    if raw:
                        raise RawStringError(
                            f"{name}:{row}: U+{ord(ch):04X} inside a raw string - "
                            f"fix by hand (an escape would change the value)")
                    plan[(row, col)] = _escape(ch)
    out_lines = []
    for i, line in enumerate(lines, 1):
        if all(ord(c) < 128 for c in line):
            out_lines.append(line)
            continue
        buf = []
        for col, ch in enumerate(line):
            if ord(ch) < 128:
                buf.append(ch)
            elif (i, col) in plan:
                buf.append(plan[(i, col)])
            else:
                raise ValueError(
                    f"{name}:{i}: U+{ord(ch):04X} outside any string or comment")
        out_lines.append("".join(buf))
    new = "".join(out_lines)
    before = ast.dump(_strip_docstrings(ast.parse(text, name)))
    after = ast.dump(_strip_docstrings(ast.parse(new, name)))
    if before != after:
        raise ValueError(f"{name}: rewrite changed a constant - refused")
    return new


def tracked_py() -> list[str]:
    proc = subprocess.run(["git", "ls-files", "-z", "--", "*.py"], cwd=str(REPO),
                          capture_output=True, check=True)
    gate = _gate()
    return sorted(r for r in proc.stdout.decode("utf-8").split("\0")
                  if r and not gate._ascii_exempt(r))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="rewrite in place")
    ap.add_argument("files", nargs="*", help="repo-relative paths (default: all tracked .py)")
    args = ap.parse_args(argv)
    rels = args.files or tracked_py()
    dirty = 0
    failed = 0
    for rel in rels:
        path = REPO / rel
        if not path.is_file():
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        n = sum(1 for c in text if ord(c) > 127)
        if not n:
            continue
        dirty += 1
        try:
            # Preserve the file's own newlines: decode/encode never translates.
            new = convert(text.replace("\r\n", "\n"), rel)
            if "\r\n" in text:
                new = new.replace("\n", "\r\n")
        except (ValueError, SyntaxError) as exc:
            failed += 1
            print(f"REFUSED {rel}: {exc}")
            continue
        print(f"{n:5d}  {rel}")
        if args.apply:
            tmp = path.with_name(path.name + ".ascii_tmp")
            tmp.write_bytes(new.encode("ascii"))
            tmp.replace(path)
    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"{mode}: {dirty} file(s) with non-ASCII, {failed} refused")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

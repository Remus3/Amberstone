"""S144-P-373 (RM-481 residual) - no production file open takes its mode from a variable.

The two tree ratchets for CRLF text writers (tests/test_text_writer_lf_ratchet_rm481_s144p279.py and
tests/test_text_mode_writer_newline_tree_ratchet_s144p243.py) read only a CONSTANT mode, and both name the gap:
``open(p, mode)`` with ``mode`` held in a variable is invisible to them, so a text-mode writer written that way
would emit CRLF on Windows (a text ``open(p, "w")`` without ``newline=`` translates every ``\\n``) and pass both.

Measured 2026-11-08 over every tracked ``*.py`` outside the test trees: ZERO such calls among the file-open
spellings below. (``os.open(path, flags)`` takes integer flags and no text layer, ``Image.open`` /
``opener.open(req)`` / ``RoundStore.open`` are not file openers, and none of them is a shape here.) This census
closes the named blind spot: a new open-family call whose mode is not a string literal fails the test unless it
passes ``newline=`` (then the line ending is decided at the call) or is a named row in ``_NAMED``.

Shapes read: builtin ``open`` / ``io.open`` / ``os.fdopen`` with a non-literal second positional argument, and any
``open`` / ``fdopen`` / ``NamedTemporaryFile`` / ``TemporaryFile`` / ``SpooledTemporaryFile`` call whose ``mode=``
keyword is not a string literal. A ``Path.open(mode)`` receiver cannot be told from ``opener.open(req)`` by name
alone, so it is a named blind spot, not a shape (the constant-mode ratchets already cover its literal form).
Other named blind spots (a verifier measured zero hits in each, 2026-11-08): the FIRST positional argument of
``NamedTemporaryFile`` / ``TemporaryFile`` as a variable, ``codecs.open`` / ``gzip.open``, and ``*args`` spreads.
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "docs/_archive/", "agents/agent3_testing/suite/")
_MODE_KW_CALLS = ("open", "fdopen", "NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile")

# (relpath, line-independent source text of the mode expression) -> why it is not a text writer. Empty: a new row
# needs its own proof that the file is read-only or binary, so the table is a place to explain, not to park.
_NAMED: dict[tuple[str, str], str] = {}


def _in_scope(rel: str) -> bool:
    return not (rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel)


def _is_literal_str(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def scan_source(src: str) -> list[tuple[int, str]]:
    """(line, unparsed mode expression) of every open-family call whose mode is not a string literal."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        kws = {k.arg: k.value for k in node.keywords}
        if "newline" in kws:
            continue
        mode: ast.AST | None = kws.get("mode")
        if mode is None and len(node.args) > 1:
            plain_open = isinstance(fn, ast.Name) and fn.id == "open"
            module_open = (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name)
                           and (fn.value.id, fn.attr) in (("io", "open"), ("os", "fdopen")))
            if plain_open or module_open:
                mode = node.args[1]
        if mode is None:
            continue
        name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
        if name not in _MODE_KW_CALLS or _is_literal_str(mode):
            continue
        hits.append((node.lineno, ast.unparse(mode)))
    return hits


def _tree_hits() -> list[tuple[str, int, str]]:
    files = [(relative_posix(p), p) for p in repo_files(REPO_ROOT, ("*.py",))]
    assert len(files) > 200, "the tracked-file walk returned almost nothing"
    out: list[tuple[str, int, str]] = []
    for rel, path in files:
        if not _in_scope(rel):
            continue
        try:
            hits = scan_source(Path(path).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        out.extend((rel, line, expr) for line, expr in hits)
    return out


def test_no_open_takes_its_mode_from_a_variable():
    new = [(rel, line, expr) for rel, line, expr in _tree_hits() if (rel, expr) not in _NAMED]
    assert not new, (
        "an open-family call with a non-literal mode hides from the CRLF ratchets - pass a literal mode "
        f"(and newline=\"\\n\" for a text write), or name the row in _NAMED: {new}"
    )


def test_every_named_row_still_offends():
    live = {(rel, expr) for rel, _line, expr in _tree_hits()}
    stale = sorted(set(_NAMED) - live)
    assert not stale, f"_NAMED rows that no longer match a call (drop them): {stale}"


def test_scanner_is_live():
    bad = {
        "open positional": "open(p, mode)",
        "open keyword": "open(p, mode=m)",
        "io.open": "import io\nio.open(p, m)",
        "os.fdopen": "import os\nos.fdopen(fd, m)",
        "NamedTemporaryFile": "import tempfile\ntempfile.NamedTemporaryFile(mode=m)",
        "conditional mode": "open(p, 'w' if x else 'a')",
    }
    for label, src in bad.items():
        assert scan_source(src), f"scanner missed {label}"
    quiet = [
        "open(p)",
        "open(p, 'w')",
        "open(p, mode='rb')",
        "open(p, mode, newline='\\n')",
        "os.open(path, flags)",
        "opener.open(req)",
        "Image.open(buf)",
        "RoundStore.open(path, readonly=True)",
        "os.fdopen(fd)",
    ]
    for src in quiet:
        assert not scan_source(src), f"scanner flagged a quiet shape: {src}"


def test_scanner_reads_the_mode_expression():
    assert scan_source("open(p, mode)") == [(1, "mode")]
    assert scan_source("x = 1\nopen(p, mode=m or 'r')") == [(2, "m or 'r'")]

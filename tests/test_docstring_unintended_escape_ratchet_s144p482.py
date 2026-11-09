"""S144-P-482 - a non-raw docstring never carries an unintended backslash escape, pinned.

In a non-raw docstring ``scripts\\build_x.py`` is not a Windows path: ``\\b`` is a backspace
character, ``\\t`` a tab, ``\\n`` a newline. Python keeps the source line intact, so a reader of the file
sees a path and ``help()`` / ``__doc__`` shows a control character. ruff's D301 reports it but ruff.toml
selects no D rule. Measured 2026-11-08 over every tracked production ``.py`` (AST walk, module / class /
function docstrings, non-raw prefix only): ruff D301 reports 80 docstrings, and 78 of them double every
backslash on purpose (``\\\\s``, ``C:\\\\x`` ...) - those are correct and are NOT findings here.
Exactly two carry a SINGLE backslash that Python then interprets:

- ``scripts/build_spell_cast_rates.py`` - ``scripts\\build_spell_cast_rates.py`` in a Run:: example (a
  backspace between ``scripts`` and ``uild``). Fixed with this guard.
- ``agents/daemon_slayer/_crit_conversion_overrides.py`` - a quoted wiki sample whose ``\\n`` is a
  newline inside the docstring. Daemon Slayer is lane/ds territory (a docstring edit there is a FILING),
  so it is the one named exception in ``_BASELINE``.

The rule: a docstring's source text may hold an odd run of backslashes only when the next character is a
line break or a quote. Any other single backslash (valid escape that changes the text, or an invalid one
that is a SyntaxWarning on Python 3.12+) must be doubled or the docstring made raw. ``_BASELINE`` only
shrinks: an entry that stops offending fails ``test_baseline_is_exact``.

Named blind spots: only docstrings are read (a plain string literal is a different decision - it may be
code), and a docstring built by concatenation or ``__doc__ =`` is not a docstring node.
"""
from __future__ import annotations

import ast
import re

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = (
    "tests/",
    "docs/_archive/",
    "ops/fleet_kit/",
    "agents/agent3_testing/suite/",
)
# file -> number of offending docstrings that stay. Only shrinks.
_BASELINE = {
    # lane/ds territory: the docstring quotes a wiki sample with a literal "\n". FILED, not edited here.
    "agents/daemon_slayer/_crit_conversion_overrides.py": 1,
}
_FIXED = ("scripts/build_spell_cast_rates.py",)

# An ODD run of backslashes (the last one is a lone escape introducer) not followed by a line break or quote.
_LONE_ESCAPE = re.compile(r"(?<!\\)(?:\\\\)*\\(?![\\\r\n'\"])")


def offending_docstrings(src: str) -> list[int]:
    """Line numbers of every non-raw docstring whose source holds a lone, interpreted backslash."""
    tree = ast.parse(src)
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if not (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            continue
        const = body[0].value
        segment = ast.get_source_segment(src, const) or ""
        quote_at = min((i for i in (segment.find('"'), segment.find("'")) if i >= 0), default=0)
        if "r" in segment[:quote_at].lower():
            continue
        if _LONE_ESCAPE.search(segment):
            hits.append(const.lineno)
    return hits


def _scan_tree() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(path)
        if rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel:
            continue
        try:
            src = path.read_text(encoding="utf-8")
            hits = offending_docstrings(src)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        if hits:
            out[rel] = len(hits)
    return out


def test_scanner_is_live():
    """An empty scan would pass for any reason, so prove it reports, accepts and skips correctly."""
    bad = 'def f():\n    """Run scripts\\build_x.py now."""\n'
    assert offending_docstrings(bad) == [2]
    assert offending_docstrings('def f():\n    """Run scripts\\\\build_x.py now."""\n') == []
    assert offending_docstrings('def f():\n    r"""Run scripts\\build_x.py now."""\n') == []
    assert offending_docstrings('def f():\n    """Run `x` \\\n    on one line."""\n') == []
    assert offending_docstrings('def f():\n    """Say \\"hi\\" twice."""\n') == []
    assert offending_docstrings('def f():\n    """Triple \\\\\\n escape."""\n') == [2]
    assert offending_docstrings('x = "scripts\\build_x.py"\n') == []


def test_no_new_offending_docstring():
    found = _scan_tree()
    extra = {k: v for k, v in found.items() if v > _BASELINE.get(k, 0)}
    assert not extra, f"docstring with an interpreted single backslash (double it or make it raw): {extra}"


def test_baseline_is_exact():
    found = _scan_tree()
    for rel, count in _BASELINE.items():
        assert found.get(rel, 0) == count, f"{rel}: baseline {count}, measured {found.get(rel, 0)}"


def test_fixed_files_stay_clean():
    found = _scan_tree()
    for rel in _FIXED:
        assert (REPO_ROOT / rel).is_file(), rel
        assert rel not in found, rel

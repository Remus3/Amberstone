"""RM-337 guard - DS tests must not name paths relative to the repo root.

THE DEFECT CLASS
----------------
A test in this directory that reaches for a file through a path literal
written relative to the REPO ROOT - for example
``open("agents/daemon_slayer/rune_procs.py")`` or
``Path("agents/daemon_slayer/champion_block_index.json").read_text()`` -
resolves ONLY when the running process happens to have the repo root as its
current working directory. Nothing guarantees that. The shipped Share/
package re-roots these same tests under ``Share/src/``, so a clean copy run
from any other directory raises FileNotFoundError before a single assertion
executes. Thirteen tests failed exactly that way, for a reason that had
nothing to do with what they assert.

THE CANONICAL FIX
-----------------
Anchor on ``__file__``, never on the CWD::

    _DS_DIR = Path(__file__).resolve().parents[1]
    src = (_DS_DIR / "rune_procs.py").read_text(encoding="utf-8")

``parents[1]`` is the daemon_slayer package directory whether the test sits
at ``agents/daemon_slayer/tests/`` in this repo or at ``Share/src/.../tests/``
in the shipped package, so the same line works in both trees and from any
CWD. A test that legitimately needs to name such a path AS DATA anchors it
the same way. The answer is never an ignore list - which is why this guard
deliberately carries NO skip list and NO per-file exemptions.

WHAT IS CHECKED
---------------
Every ``.py`` file under this directory is parsed with ``ast`` and every
``ast.Constant`` holding a ``str`` is inspected. Prose that merely DESCRIBES
such a path is fine; a literal USED as data is not. Two exemptions, both
mechanical rather than name-based:

  * ``#`` comments - invisible to the AST, so they cost nothing to exempt.
  * Docstrings - identified structurally as the leading ``ast.Expr`` of a
    module / class / function / async-function body and skipped by node
    identity. This module's own docstring is the live proof: it spells the
    banned path out three times above and the guard stays green.

This guard obeys the rule it enforces. Its own directory comes from
``Path(__file__).resolve().parent``, and the forbidden prefixes below are
BUILT by concatenation instead of being written out, so no constant in this
file begins with the banned prefix. Do not "simplify" either back into a
literal - the guard would then trip on itself.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_DS_DIR = Path(__file__).resolve().parents[1]

# Assembled at import time on purpose - see the module docstring. Spelled out
# as plain literals these would be the guard's own first two violations.
_TOP_PACKAGE = "agents"
_BANNED_PREFIXES = (_TOP_PACKAGE + "/", _TOP_PACKAGE + "\\")

# A glob that silently matches nothing reads as a green suite. This directory
# holds hundreds of test modules; anything under this floor means the scan
# broke, not that the tree got clean.
_MIN_SCANNED_FILES = 50

_DOCSTRING_HOLDERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _iter_test_files() -> list[Path]:
    """Every .py file under this test directory, located CWD-independently."""
    skip_parts = {"__pycache__", ".pytest_cache"}
    return sorted(p for p in _TESTS_DIR.rglob("*.py") if skip_parts.isdisjoint(p.parts))


def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    """id() of every module / class / function docstring Constant in ``tree``.

    Structural, not name-based: a docstring is the leading ``ast.Expr`` of a
    body, wrapping a ``str`` Constant. Nothing else qualifies, so a string
    used as data can never sneak into this set.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, _DOCSTRING_HOLDERS):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


class NoCwdRelativePathLiteralsTests(unittest.TestCase):
    """RM-337: no test module may carry a repo-root-relative path literal."""

    def test_scan_covers_the_directory(self) -> None:
        """The scan is non-vacuous and finds this very file."""
        files = _iter_test_files()
        self.assertGreater(
            len(files),
            _MIN_SCANNED_FILES,
            f"RM-337 guard scanned only {len(files)} .py files under {_TESTS_DIR} - "
            f"expected more than {_MIN_SCANNED_FILES}. The glob is broken, so a "
            f"green result here would prove nothing.",
        )
        self.assertIn(
            Path(__file__).resolve(),
            files,
            "RM-337 guard did not find itself in its own scan set - the walk is wrong.",
        )
        self.assertTrue(
            (_DS_DIR / "__init__.py").is_file(),
            f"RM-337 guard resolved the package dir to {_DS_DIR}, which has no "
            f"__init__.py - parents[1] is not the daemon_slayer package here.",
        )

    def test_no_repo_root_relative_path_literals(self) -> None:
        files = _iter_test_files()
        self.assertGreater(
            len(files),
            _MIN_SCANNED_FILES,
            f"RM-337 guard scanned only {len(files)} .py files under {_TESTS_DIR} - "
            f"expected more than {_MIN_SCANNED_FILES}. Refusing to pass vacuously.",
        )

        offenders: list[str] = []
        unparsable: list[str] = []

        for path in files:
            try:
                rel = path.relative_to(_TESTS_DIR).as_posix()
            except ValueError:  # pragma: no cover - rglob cannot escape its root
                rel = str(path)
            source = path.read_bytes()
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError as exc:
                unparsable.append(f"{rel}:{exc.lineno}: {type(exc).__name__}: {exc.msg}")
                continue
            exempt = _docstring_constant_ids(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if id(node) in exempt:
                    continue
                if node.value.startswith(_BANNED_PREFIXES):
                    offenders.append(f"{rel}:{node.lineno}: {node.value!r}")

        self.assertEqual(
            [],
            unparsable,
            "RM-337 guard could not parse these files, so it could not inspect "
            "them - a syntax error must never be swallowed into a silent pass:\n  "
            + "\n  ".join(unparsable),
        )

        self.assertEqual(
            [],
            offenders,
            f"RM-337: {len(offenders)} repo-root-relative path literal(s) found in "
            f"{_TESTS_DIR}. Each resolves only when the CWD happens to be the repo "
            f"root, so it raises FileNotFoundError from the shipped Share/ package "
            f"or any other directory. Fix each by anchoring on __file__:\n"
            f"    _DS_DIR = Path(__file__).resolve().parents[1]\n"
            f"    (_DS_DIR / 'rune_procs.py').read_text(encoding='utf-8')\n"
            f"Offending literals (file:line: literal):\n  " + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()

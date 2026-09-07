"""RM-337 guard - DS tests must not name paths relative to the repo root.

THE DEFECT CLASS
----------------
A test in this directory that reaches for a file through a path literal
written relative to the REPO ROOT - for example
``open("agents/daemon_slayer/rune_procs.py")`` or
``Path("agents/daemon_slayer/champion_block_index.json").read_text()`` -
resolves ONLY when the running process happens to have the repo root as its
current working directory. Nothing guarantees that: a run launched from any
other directory raises FileNotFoundError before a single assertion executes.
Thirteen tests failed exactly that way, for a reason that had nothing to do
with what they assert.

THE CANONICAL FIX
-----------------
Anchor on ``__file__``, never on the CWD::

    _DS_DIR = Path(__file__).resolve().parents[1]
    src = (_DS_DIR / "rune_procs.py").read_text(encoding="utf-8")

``parents[1]`` is the daemon_slayer package directory wherever the test tree
is rooted, so the same line works from any CWD and survives the package
being re-rooted or copied elsewhere.
A test that legitimately needs to name such a path AS DATA anchors it
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
    identity.

Do NOT cite this module's own docstring as proof that the docstring exemption
works. It is not: the test is ``startswith``, and this docstring's value begins
"RM-337 guard", so it would pass with the exemption deleted. That was measured -
disabling the exemption and re-scanning both trees still returns zero hits, so
the exemption is currently load-bearing NOWHERE in the repo. It is kept because
prose describing one of these paths is legitimate and must not be a failure; its
behaviour is pinned by the sibling tests below rather than by this file.

A path is normalised before the prefix test, because each of these is just as
CWD-relative as the bare form and an earlier revision of this guard missed all
four:

  * ``bytes`` constants - ``open()`` accepts a bytes path, so ``b"agents/x"``
    is a working CWD-relative open that an ``isinstance(value, str)`` test
    skips entirely.
  * a leading ``./`` or any number of ``../`` segments.
  * case - the check is case-insensitive, since this repo's tests run on a
    case-insensitive filesystem where ``Agents/x`` resolves.

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

# A glob that silently matches nothing reads as a green suite. This directory
# holds hundreds of test modules; anything under this floor means the scan
# broke, not that the tree got clean.
_MIN_SCANNED_FILES = 50

_DOCSTRING_HOLDERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _iter_test_files() -> list[Path]:
    """Every .py file under this test directory, located CWD-independently."""
    skip_parts = {"__pycache__", ".pytest_cache"}
    return sorted(p for p in _TESTS_DIR.rglob("*.py") if skip_parts.isdisjoint(p.parts))


def _is_repo_root_relative(value: str | bytes) -> bool:
    """True when ``value`` is a path literal written relative to the repo root.

    Normalises the four shapes that are equally CWD-relative but evade a bare
    ``str.startswith`` on the raw value - see the module docstring.
    """
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return False
    text = value.replace("\\", "/")
    while text.startswith("./") or text.startswith("../"):
        text = text[2:] if text.startswith("./") else text[3:]
    return text.lower().startswith(_TOP_PACKAGE + "/")


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


def _offenders_in_source(source: bytes | str, label: str) -> list[str]:
    """Offending literals in one module's source. Raises SyntaxError if unparsable.

    Split out from the file walk so the exemption and normalisation behaviour is
    pinned directly by the tests below, rather than only in passing by whatever
    happens to be on disk.
    """
    tree = ast.parse(source, filename=label)
    exempt = _docstring_constant_ids(tree)
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if not isinstance(node.value, (str, bytes)):
            continue
        if id(node) in exempt:
            continue
        if _is_repo_root_relative(node.value):
            out.append(f"{label}:{node.lineno}: {node.value!r}")
    return out

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
            try:
                found = _offenders_in_source(path.read_bytes(), rel)
            except SyntaxError as exc:
                unparsable.append(f"{rel}:{exc.lineno}: {type(exc).__name__}: {exc.msg}")
                continue
            offenders.extend(found)

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
            f"root, so it raises FileNotFoundError from any other directory. "
            f"Fix each by anchoring on __file__:\n"
            f"    _DS_DIR = Path(__file__).resolve().parents[1]\n"
            f"    (_DS_DIR / 'rune_procs.py').read_text(encoding='utf-8')\n"
            f"Offending literals (file:line: literal):\n  " + "\n  ".join(offenders),
        )


class GuardBehaviourTests(unittest.TestCase):
    """Pin what the module docstring asserts, so neither claim goes unbacked.

    Every fixture here builds the banned prefix by concatenation for the same
    reason the guard itself does - written out, they would be violations.
    """

    PKG = _TOP_PACKAGE

    def _scan(self, src: str) -> list[str]:
        return _offenders_in_source(src, "fixture.py")

    def test_plain_literal_is_caught(self) -> None:
        self.assertTrue(self._scan(f'_p = "{self.PKG}/daemon_slayer/x.json"'))

    def test_bytes_literal_is_caught(self) -> None:
        """open() takes a bytes path, so this one actually works at runtime."""
        self.assertTrue(self._scan(f'_p = b"{self.PKG}/daemon_slayer/x.json"'))

    def test_dot_slash_and_dotdot_prefixes_are_caught(self) -> None:
        for prefix in ("./", "../", "../../"):
            with self.subTest(prefix=prefix):
                self.assertTrue(
                    self._scan(f'_p = "{prefix}{self.PKG}/daemon_slayer/x.json"')
                )

    def test_case_variation_is_caught(self) -> None:
        """The filesystem these tests run on is case-insensitive."""
        self.assertTrue(
            self._scan(f'_p = "{self.PKG.capitalize()}/daemon_slayer/x.json"')
        )

    def test_backslash_separator_is_caught(self) -> None:
        """A Windows-style separator is the same defect.

        The separator is built with chr(92) rather than written out, so this
        file carries no backslash-escaped fixture for a reader to decode.
        """
        sep = chr(92)
        src = '_p = r"' + self.PKG + sep + 'daemon_slayer' + sep + 'x.json"'
        self.assertTrue(self._scan(src))

    def test_comment_is_not_caught(self) -> None:
        nl = chr(10)
        src = '# see ' + self.PKG + '/daemon_slayer/x.json' + nl + '_p = 1'
        self.assertEqual([], self._scan(src))

    def test_docstring_is_not_caught(self) -> None:
        """A docstring whose VALUE STARTS with the banned prefix.

        This is the case the exemption exists for, and the one no file in
        the repo currently exercises - which is exactly why it is pinned
        here rather than left to the on-disk tree to demonstrate.
        """
        nl = chr(10)
        q = chr(34) * 3
        src = q + self.PKG + '/daemon_slayer/x.json described' + q + nl + '_p = 1'
        self.assertEqual([], self._scan(src))

    def test_exemption_does_not_leak_to_non_docstrings(self) -> None:
        """A second, non-leading string statement is data, not a docstring."""
        nl = chr(10)
        q = chr(34) * 3
        src = (q + 'real docstring' + q + nl
               + chr(34) + self.PKG + '/daemon_slayer/x.json' + chr(34) + nl)
        self.assertTrue(self._scan(src))

    def test_unrelated_relative_literal_is_not_caught(self) -> None:
        """Scope is the documented one - the prefix, not every relative path."""
        self.assertEqual([], self._scan('_p = "champion_block_index.json"'))


if __name__ == "__main__":
    unittest.main()

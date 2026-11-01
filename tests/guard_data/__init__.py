"""Shared guard-test DATA, one file per path-prefix area (MAIN ORDER item RC-2).

tests/test_web_ascii_sweep.py was touched by 84 commits in a week and every
lane collided on it, because the rows every guard run compares against lived
inside the test module. The rows now live here, one directory per guard:

  tests/guard_data/web_live_half/  read by tests/test_web_ascii_sweep.py
  tests/guard_data/atomic_write/   read by tests/test_atomic_write_guard_rm258_rm261.py

Each directory's __init__.py DECLARES its areas, and its loader FAILS (never
returns an empty result) on: no areas declared, a declared area with no file, an
area file with no rows, a duplicate row, a row in the wrong area, or any file
on disk that no declaration names. Comparison is by name set, so nothing here
depends on directory listing order. Pinned by tests/test_guard_data_split_rc2.py.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Every guard directory. A directory nothing declares would be data no guard
# reads, so tests/test_guard_data_split_rc2.py fails on one.
GUARDS = ("atomic_write", "web_live_half")

_IGNORED_FILES = frozenset({"__init__.py"})
_IGNORED_DIRS = frozenset({"__pycache__"})


class GuardDataError(AssertionError):
    """The data a guard depends on is missing, empty or unreferenced."""


def _list_dir(directory: Path) -> list[Path]:
    return list(directory.iterdir())


def check_area_files(directory: Path, suffix: str, declared) -> None:
    """Fail unless the files on disk are exactly the declared areas."""
    stems = set(declared)
    if not stems:
        raise GuardDataError(f"{directory}: no areas declared")
    if not directory.is_dir():
        raise GuardDataError(f"{directory}: data directory is missing")
    found: set[str] = set()
    for entry in _list_dir(directory):
        if entry.is_dir():
            if entry.name not in _IGNORED_DIRS:
                raise GuardDataError(f"{entry}: unexpected directory in a data dir")
        elif entry.name not in _IGNORED_FILES:
            found.add(entry.name)
    expected = {stem + suffix for stem in stems}
    missing = sorted(expected - found)
    if missing:
        raise GuardDataError(f"{directory}: declared area file(s) missing: {missing}")
    unreferenced = sorted(found - expected)
    if unreferenced:
        raise GuardDataError(
            f"{directory}: file(s) no area declares, so no loader reads them: "
            f"{unreferenced} - declare the area in that directory's __init__.py")


def load_literal_rows(path: Path):
    """The one `ROWS = <set or dict literal>` of a data module, un-imported.

    ast, not import: a duplicate row in a literal collapses silently once it
    is evaluated, so it is counted here while the source still shows it."""
    try:
        tree = ast.parse(path.read_bytes().decode("ascii"))
    except (OSError, ValueError, SyntaxError) as exc:
        raise GuardDataError(f"{path}: unreadable data file: {exc}") from exc
    assigns = [n for n in tree.body
               if isinstance(n, ast.Assign) and len(n.targets) == 1
               and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "ROWS"]
    if len(assigns) != 1:
        raise GuardDataError(f"{path}: needs exactly one ROWS assignment")
    node = assigns[0].value
    if isinstance(node, ast.Set):
        count = len(node.elts)
    elif isinstance(node, ast.Dict):
        count = len(node.keys)
    else:
        raise GuardDataError(f"{path}: ROWS must be a set or dict literal")
    try:
        rows = ast.literal_eval(node)
    except ValueError as exc:
        raise GuardDataError(f"{path}: ROWS is not a literal: {exc}") from exc
    if not rows:
        raise GuardDataError(f"{path}: area has no rows - delete the file and "
                             "its declaration if the area is really gone")
    if len(rows) != count:
        raise GuardDataError(f"{path}: duplicate row ({count} written, {len(rows)} distinct)")
    return rows

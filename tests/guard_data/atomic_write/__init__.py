"""Allowlists of tests/test_atomic_write_guard_rm258_rm261.py, one file per area.

Why path prefixes, not lane names: every row names a repo path, whichever lane
added it, and the churn measured is tools/ conversions, so tools/ splits by kind.

`tools_unclassified` only shrinks. When a last row leaves, delete the file and
its AREAS row (a declared area with no rows fails); that kind alone may then be
empty, because `tests/test_atomic_write_guard_rm258_rm261.py` has its own
exactness test. The other kinds must always have rows. `audit_unclassified`
(ops/audit/) shrank to empty in s144 and was retired that way.
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from tests.guard_data import GuardDataError, check_area_files, load_literal_rows

HERE = Path(__file__).resolve().parent
SUFFIX = ".py"

SANCTIONED = "sanctioned"
RUNTIME_TOOLS = "runtime_tools"
TOOLS_UNCLASSIFIED = "tools_unclassified"
EXCLUDED_PREFIXES = "excluded_prefixes"

# Area file stem -> (kind, the path prefix every row must carry; "" = any).
AREAS = {
    "excluded_prefixes": (EXCLUDED_PREFIXES, ""),
    "runtime_tools": (RUNTIME_TOOLS, "tools/"),
    "sanctioned_core": (SANCTIONED, "core/"),
    "sanctioned_ops": (SANCTIONED, "ops/"),
    "sanctioned_tools": (SANCTIONED, "tools/"),
    "tools_unclassified": (TOOLS_UNCLASSIFIED, "tools/"),
}
_MUST_HAVE_ROWS = (SANCTIONED, RUNTIME_TOOLS, EXCLUDED_PREFIXES)


class AtomicWriteData(NamedTuple):
    sanctioned: dict
    runtime_tools: frozenset
    tools_unclassified: frozenset
    excluded_prefixes: tuple


def _is_text(value) -> bool:
    return isinstance(value, str) and bool(value)


def _check_sanctioned(path: Path, rows, prefix: str) -> None:
    if not isinstance(rows, dict):
        raise GuardDataError(f"{path}: a sanctioned area is a dict literal")
    for key, reason in rows.items():
        if not (isinstance(key, tuple) and len(key) == 2 and all(map(_is_text, key))):
            raise GuardDataError(f"{path}: bad key {key!r}, want (relpath, function)")
        if not _is_text(reason):
            raise GuardDataError(f"{path}: {key!r} has no reason")
        if not key[0].startswith(prefix):
            raise GuardDataError(f"{path}: {key[0]} does not belong under {prefix}")


def _check_paths(path: Path, rows, prefix: str) -> None:
    if not isinstance(rows, set):
        raise GuardDataError(f"{path}: this area is a set literal")
    for row in rows:
        if not _is_text(row):
            raise GuardDataError(f"{path}: bad row {row!r}")
        if not row.startswith(prefix):
            raise GuardDataError(f"{path}: {row} does not belong under {prefix}")


def load(directory: Path = HERE, areas=None) -> AtomicWriteData:
    """Merge every declared area; order of declaration or listing is irrelevant."""
    table = AREAS if areas is None else areas
    check_area_files(directory, SUFFIX, table)
    merged: dict = {SANCTIONED: {}, RUNTIME_TOOLS: set(),
                    TOOLS_UNCLASSIFIED: set(), EXCLUDED_PREFIXES: set()}
    for stem in sorted(table):
        kind, prefix = table[stem]
        path = directory / (stem + SUFFIX)
        rows = load_literal_rows(path)
        if kind == SANCTIONED:
            _check_sanctioned(path, rows, prefix)
        else:
            _check_paths(path, rows, prefix)
        overlap = merged[kind].keys() & rows.keys() if kind == SANCTIONED else merged[kind] & rows
        if overlap:
            raise GuardDataError(f"{path}: row(s) already in another area: {sorted(overlap)}")
        merged[kind].update(rows)
    for kind in _MUST_HAVE_ROWS:
        if not merged[kind]:
            raise GuardDataError(f"{directory}: no {kind} rows found - the guard "
                                 "would pass over nothing")
    return AtomicWriteData(
        sanctioned=merged[SANCTIONED],
        runtime_tools=frozenset(merged[RUNTIME_TOOLS]),
        tools_unclassified=frozenset(merged[TOOLS_UNCLASSIFIED]),
        excluded_prefixes=tuple(sorted(merged[EXCLUDED_PREFIXES])),
    )

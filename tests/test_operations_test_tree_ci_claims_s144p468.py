"""docs/OPERATIONS.md says which test trees CI runs; ci.yml is the authority (S144-P-468).

The "Test trees" section of docs/OPERATIONS.md carries a table whose last column
is "Run by any CI job?" and a paragraph saying which trees are "outside both
local suites AND run by no CI job". Both were written before RM-407 (2026-09-11,
commit 3eb4bd1da) wired `tools/tests` into ci.yml, and were never corrected:
the table said **no** for `tools/tests` and the paragraph said 359 + 348 = 707
tests ran in no CI job, while ci.yml has carried the step "orphan tree gated:
tools/tests (RM-407)" ever since. A reader deciding whether a red in that tree
would be seen in CI got the wrong answer.

The counts in that section are a dated measurement and deliberately unguarded
(the section says so). What is a checkable claim, and was wrong, is the
yes / no CI column. This guard joins it to the real parse of ci.yml through the
same `_pytest_targets` / `_is_covered` helpers that
tests/test_ci_collects_orphan_suite_trees.py uses to guard the workflow side, so
the doc can neither claim coverage ci.yml does not give nor deny coverage it
does. It reads no count.
"""
from __future__ import annotations

import re

from tests import _repo_walk
from tests.test_ci_collects_orphan_suite_trees import (
    _ci_text,
    _is_covered,
    _pytest_targets,
)

REPO_ROOT = _repo_walk.REPO_ROOT
OPERATIONS = REPO_ROOT / "docs" / "OPERATIONS.md"
DOCS_GUARDS = REPO_ROOT / ".github" / "workflows" / "docs-guards.yml"

_NO_CI_CLAUSE = "run by no CI job"
_WINDOW = 260


def _ci_targets() -> list[str]:
    text = _ci_text() + "\n" + DOCS_GUARDS.read_text(encoding="utf-8")
    return _pytest_targets(text)


def _table_rows(text: str) -> dict[str, str]:
    """Tree -> normalised last-column cell for every `| `<tree>` | ... |` row."""
    rows: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        tree = cells[0].strip("`")
        # First word only: a cell may carry a trailing note, e.g. "yes (RM-407)".
        words = cells[-1].replace("*", "").strip().lower().split()
        rows[tree] = words[0] if words else ""
    return rows


def _no_ci_windows(text: str) -> list[str]:
    """The text just before every 'run by no CI job' clause, whitespace-collapsed."""
    flat = re.sub(r"\s+", " ", text)
    out = []
    start = 0
    while True:
        at = flat.find(_NO_CI_CLAUSE, start)
        if at < 0:
            return out
        out.append(flat[max(0, at - _WINDOW):at])
        start = at + len(_NO_CI_CLAUSE)


def test_table_rows_are_read_and_name_the_five_trees():
    rows = _table_rows(OPERATIONS.read_text(encoding="utf-8"))
    for tree in (
        "tests",
        "agents/daemon_slayer/tests",
        "agents/agent3_testing/suite",
        "tools/tests",
        "oss/win32_atomic_io/tests",
    ):
        assert tree in rows, f"OPERATIONS table lost its row for {tree}"
        assert rows[tree] in {"yes", "no"}, (tree, rows[tree])


def test_ci_column_matches_ci_yml():
    rows = _table_rows(OPERATIONS.read_text(encoding="utf-8"))
    targets = _ci_targets()
    assert targets, "ci.yml parse found no pytest target (vacuous)"
    wrong = {
        tree: (cell, "ci.yml covers it" if _is_covered(targets, tree) else "ci.yml does not")
        for tree, cell in rows.items()
        if (cell == "yes") != _is_covered(targets, tree)
    }
    assert not wrong, f"OPERATIONS 'Run by any CI job?' column disagrees with CI: {wrong}"


def test_no_ci_clause_names_no_tree_that_ci_runs():
    text = OPERATIONS.read_text(encoding="utf-8")
    windows = _no_ci_windows(text)
    assert windows, "the 'run by no CI job' clause is gone; revisit this guard"
    targets = _ci_targets()
    named = [
        tree
        for window in windows
        for tree in _table_rows(text)
        if f"`{tree}`" in window and _is_covered(targets, tree)
    ]
    assert not named, f"'{_NO_CI_CLAUSE}' sits next to trees CI does run: {named}"


def test_window_helper_reads_its_input():
    sample = "the `a/b` tree and `c/d` are outside both suites AND run by no CI job."
    (window,) = _no_ci_windows(sample)
    assert "`a/b`" in window and "`c/d`" in window
    assert _no_ci_windows("nothing here") == []


def test_table_helper_reads_its_input():
    sample = (
        "| `x/y` | 1 | no | no | **no** |\n"
        "| `z` | 2 | no | no | yes (RM-407, a note) |\n"
        "| other |\n"
    )
    assert _table_rows(sample) == {"x/y": "no", "z": "yes"}

"""RM-1398 - no tracked .py carries an assert that cannot fail.

Measured 2026-11-04 over every tracked .py: two vacuous asserts, both in
tests/test_inbox_responder_runner.py, both spelled `<real check> or True`:

- test_real_spawner_named_once_outside_docstring_and_imports asserted
  `doc is not None and "REAL-SPAWN RULE" not in doc or True`. The `or True`
  made the whole line a no-op; the next line (`in doc`) would only have
  raised a TypeError on a missing docstring, not a clear failure.
- test_cycle_ids_are_distinct_within_one_injected_second asserted
  `world.held(result.cycle_id).name == first or True`. `held_dir` is
  `<root>/held/<cycle_id>`, so `.name` equals the result's own cycle id by
  construction; the line proved nothing about whether the injected id was the
  one the run used. It now asserts `result.cycle_id == first`.

A passing assert that cannot fail reads as coverage in a review and is none,
which is the same failure as a guard that scans nothing. The AST rule below
bans three shapes: an assert whose test is a truthy constant (`assert True`,
`assert 1`), a non-empty tuple (`assert (cond, "msg")`, always true), and an
`or` chain with a truthy constant operand. The walker is proven non-vacuous
with `self_check` and the rule is proven to bite with synthetic sources.
"""
from __future__ import annotations

import ast

import pytest

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix, self_check


def _vacuity(test: ast.expr) -> str | None:
    if isinstance(test, ast.Constant) and test.value:
        return "truthy constant"
    if isinstance(test, ast.Tuple) and test.elts:
        return "non-empty tuple"
    if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        for operand in test.values:
            if isinstance(operand, ast.Constant) and operand.value:
                return "or-chain with a truthy constant"
    return None


def scan_source(src: str) -> list[tuple[int, str]]:
    """(line, kind) of every vacuous assert in `src`."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assert):
            kind = _vacuity(node.test)
            if kind:
                out.append((node.lineno, kind))
    return sorted(out)


def test_walker_reaches_the_tree():
    self_check()
    files = list(iter_repo_files(REPO_ROOT, ("*.py",)))
    assert len(files) > 500, len(files)
    assert any(relative_posix(p) == "tests/test_inbox_responder_runner.py" for p in files)


def test_no_tracked_python_file_carries_a_vacuous_assert():
    offenders: list[str] = []
    for path in iter_repo_files(REPO_ROOT, ("*.py",)):
        src = path.read_bytes().decode("utf-8")
        for line, kind in scan_source(src):
            offenders.append(f"{relative_posix(path)}:{line} {kind}")
    assert not offenders, offenders


@pytest.mark.parametrize("src, kind", [
    ("assert True\n", "truthy constant"),
    ("assert 1\n", "truthy constant"),
    ("assert x == 1 or True\n", "or-chain with a truthy constant"),
    ("assert x is not None and y or 1\n", "or-chain with a truthy constant"),
    ("assert (x == 1, 'msg')\n", "non-empty tuple"),
])
def test_rule_bites_each_vacuous_shape(src, kind):
    assert scan_source(src) == [(1, kind)]


@pytest.mark.parametrize("src", [
    "assert x == 1\n",
    "assert x or y\n",
    "assert x is not None, 'why'\n",
    "assert not False or x\n",
    "assert (x, y) == (1, 2)\n",
    "assert x == 1 or y == 2\n",
    "assert False, 'unreachable'\n",
    "assert 0 or x\n",
])
def test_rule_spares_real_asserts(src):
    assert scan_source(src) == []

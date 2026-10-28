"""Guard: the P1-L4 target-state caller test cites dps.py by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. A section comment in
``tests/test_target_state_caller_p1l4.py`` said the engine treats
``target_armor`` as ABSOLUTE at ``dps.py:574``. That was true at 78810c50f
(2026-05-19): line 574 was the ``effective_target_armor(target_armor,
item_effects, level)`` call. At HEAD that call sits near line 1048, so the
line named unrelated code.

The tests below pin the claim by symbol instead, and pin the claim itself:
``compute_dps`` hands its own ``target_armor`` parameter straight to
``effective_target_armor`` with no champion base added.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DPS = REPO / "agents" / "daemon_slayer" / "dps.py"
TARGET = REPO / "tests" / "test_target_state_caller_p1l4.py"
_LINE_CITE = re.compile(r"(?<![\w.])dps\.py:\d")


def _compute_dps() -> ast.FunctionDef:
    for node in ast.parse(DPS.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.FunctionDef) and node.name == "compute_dps":
            return node
    raise AssertionError("dps.py has no def compute_dps")


def test_pattern_matches_the_rotted_shape():
    assert _LINE_CITE.search("# (dps.py:574 effective_target_armor(")
    for sample in (
        "``dps.compute_dps``",
        "an ability_dps.py:12 cite is not this pattern",
        "an ehp_dps.py:3 cite is not this pattern",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_dps_line_cite_left_in_p1l4_test():
    hits = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(TARGET.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_p1l4_test_names_the_symbol():
    text = TARGET.read_text(encoding="utf-8")
    assert "dps.compute_dps" in text
    assert "effective_target_armor(target_armor" in text


def test_compute_dps_passes_raw_target_armor():
    fn = _compute_dps()
    assert "target_armor" in {a.arg for a in fn.args.args + fn.args.kwonlyargs}
    first_args = [
        n.args[0]
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "effective_target_armor"
        and n.args
    ]
    assert first_args, "compute_dps no longer calls effective_target_armor"
    for arg in first_args:
        assert isinstance(arg, ast.Name) and arg.id == "target_armor", ast.dump(arg)

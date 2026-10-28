"""Guard: the RM-325 mode case-fold test cites DS modules by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The RM-325 test
``agents/daemon_slayer/tests/test_engine_mode_case_fold_rm325.py`` cited the
five direct ``build_champion`` callers as ``antitank.py:856``, ``cli.py:58``,
``fight_report.py:312``, ``matchup.py:153`` and ``server.py:443``, and the bare
ARAM gate as ``engine.py:254``. All six were true at c9bea8b07 (2026-09-01).
At HEAD the fight_report call sits at line 322, the server call at 503 and
the gate at 286, so three of the cited lines named unrelated code.

The tests below pin the cites by symbol instead, and pin the claims
themselves: each named caller calls ``build_champion`` directly,
``engine._apply_mode_modifiers`` holds the bare ``mode != "ARAM"`` gate, and
``engine.build_champion`` folds ``mode`` through ``canonical_mode`` BEFORE it
calls ``_apply_mode_modifiers``.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = DS / "tests" / "test_engine_mode_case_fold_rm325.py"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d")

_CALLERS = (
    ("antitank", "compute_antitank_live"),
    ("cli", "_cmd_stats"),
    ("fight_report", "compute_fight_report"),
    ("matchup", "_defensive_stats"),
    ("server", "_route_stats"),
)


def _fn(module: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((DS / f"{module}.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{module}.py has no top-level def {name}")


def _calls(fn: ast.FunctionDef, name: str) -> list[int]:
    return [
        n.lineno
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == name
    ]


def test_pattern_matches_the_rotted_shape():
    assert _LINE_CITE.search("``fight_report.py:312``,")
    for sample in (
        "``fight_report.compute_fight_report``",
        "a pkg.engine.py:3 cite is not this pattern",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_rm325_test():
    hits = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(TARGET.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_rm325_test_names_the_symbols():
    text = TARGET.read_text(encoding="utf-8")
    for module, name in _CALLERS:
        assert f"{module}.{name}" in text, f"{module}.{name}"
    assert "engine._apply_mode_modifiers" in text


def test_each_named_caller_calls_build_champion_directly():
    for module, name in _CALLERS:
        assert _calls(_fn(module, name), "build_champion"), f"{module}.{name}"


def test_apply_mode_modifiers_holds_the_bare_aram_gate():
    fn = _fn("engine", "_apply_mode_modifiers")
    gates = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Compare)
        and isinstance(n.left, ast.Name)
        and n.left.id == "mode"
        and len(n.ops) == 1
        and isinstance(n.ops[0], ast.NotEq)
        and isinstance(n.comparators[0], ast.Constant)
        and n.comparators[0].value == "ARAM"
    ]
    assert gates, "_apply_mode_modifiers no longer gates on mode != 'ARAM'"


def test_build_champion_folds_mode_before_mode_modifiers():
    fn = _fn("engine", "build_champion")
    fold_lines = [
        n.lineno
        for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "mode" for t in n.targets)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "canonical_mode"
    ]
    assert fold_lines, "build_champion no longer assigns mode = canonical_mode(mode)"
    modifier_lines = _calls(fn, "_apply_mode_modifiers")
    assert modifier_lines, "build_champion no longer calls _apply_mode_modifiers"
    assert min(fold_lines) < min(modifier_lines)

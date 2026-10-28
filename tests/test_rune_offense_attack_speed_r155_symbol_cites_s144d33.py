"""Guard: the R155 rune attack-speed test cites engine.py by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The R155 test
``agents/daemon_slayer/tests/test_rune_offense_attack_speed_r155.py`` cited
``engine.py:196`` as the line that resolves ``stats["as"]`` as
``base_as * (1 + bonus)`` and ``engine.py:439`` as the line that zeroes
``as_pct`` for an AS-locked champion. Both were true at 730d3b6a4
(2026-07-21). At HEAD those statements sit near lines 201 and 490, so the
cited lines named unrelated code.

The tests below pin the cites by symbol instead, and pin the claims
themselves: ``engine._combine_items`` assigns ``out["as"]`` from
``base_as * (1 + ...)``, and ``engine.build_champion`` zeroes
``item_totals["as_pct"]`` under ``as_lock.locks_as`` BEFORE it calls
``_combine_items``.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "agents" / "daemon_slayer" / "engine.py"
TARGET = (
    REPO / "agents" / "daemon_slayer" / "tests"
    / "test_rune_offense_attack_speed_r155.py"
)
_LINE_CITE = re.compile(r"(?<![\w.])engine\.py:\d")


def _engine_fn(name: str) -> ast.FunctionDef:
    for node in ast.parse(ENGINE.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"engine.py has no def {name}")


def _subscript_key(node: ast.AST, base: str) -> str | None:
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == base
        and isinstance(node.slice, ast.Constant)
    ):
        return node.slice.value
    return None


def test_pattern_matches_the_rotted_shape():
    assert _LINE_CITE.search("``engine.py:196`` resolves it")
    for sample in (
        "``engine._combine_items``",
        "a ds_engine.py:3 cite is not this pattern",
        "a foo.engine.py:3 cite is not this pattern",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_engine_line_cite_left_in_r155_test():
    hits = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(TARGET.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_r155_test_names_the_symbols():
    text = TARGET.read_text(encoding="utf-8")
    assert "engine._combine_items" in text
    assert "engine.build_champion" in text


def test_combine_items_resolves_final_as_from_base():
    fn = _engine_fn("_combine_items")
    rhs = [
        n.value
        for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(_subscript_key(t, "out") == "as" for t in n.targets)
        and isinstance(n.value, ast.BinOp)
        and isinstance(n.value.op, ast.Mult)
    ]
    assert rhs, "_combine_items no longer assigns out['as'] = <x> * <y>"
    left = rhs[0].left
    assert isinstance(left, ast.Name) and left.id == "base_as", ast.dump(left)
    right = rhs[0].right
    assert isinstance(right, ast.BinOp) and isinstance(right.op, ast.Add)


def test_build_champion_zeroes_as_pct_under_lock_before_combine():
    fn = _engine_fn("build_champion")
    zero_lines = [
        n.lineno
        for n in ast.walk(fn)
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.Attribute)
        and n.test.attr == "locks_as"
        for s in n.body
        if isinstance(s, ast.Assign)
        and any(_subscript_key(t, "item_totals") == "as_pct" for t in s.targets)
        and isinstance(s.value, ast.Constant)
        and s.value.value == 0.0
    ]
    assert zero_lines, "build_champion no longer zeroes item_totals['as_pct'] on locks_as"
    combine_lines = [
        n.lineno
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_combine_items"
    ]
    assert combine_lines, "build_champion no longer calls _combine_items"
    assert min(zero_lines) < min(combine_lines)

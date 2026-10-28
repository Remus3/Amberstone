"""Guard: the R70 Zeke's burst test cites by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0 (cited -> line before this edit).
test_item_magic_burst_zekes_r70.py rests its "pure DATA pin" claim on two
line cites that had both drifted: the ItemEffect fields
``magic_burst_base`` / ``magic_burst_ap_ratio`` at
``_effects_types.py:793-794`` -> 854-855, and ``total_magic_burst_damage``
at ``effects.py:349`` -> a def at 648. A cite that resolves today rots on
the next insert above it, so both go.

The tests below pin the claim itself: the two fields read only inside
``total_magic_burst_damage``, and that helper is called only by
``compute_burst_damage`` under its ``assume_magic_burst`` gate. A second
consumer turns this red rather than leaving the prose stale.
"""
from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path

from agents.daemon_slayer._effects_types import ItemEffect

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = DS / "tests" / "test_item_magic_burst_zekes_r70.py"
# ``_effects_types.py:793-794`` and ``effects.py:349``. Not the port shape
# ``:8860``, which is no cite.
_LINE_CITE = re.compile(r"\w\.(?:py|md):\d|\bat line \d")
_FIELDS = ("magic_burst_base", "magic_burst_ap_ratio")
_HELPER = "total_magic_burst_damage"
_GATE = "assume_magic_burst"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _engine_trees():
    for path in sorted(DS.glob("*.py")):
        yield path, ast.parse(_source(path))


def _enclosing_function(tree: ast.AST, node: ast.AST) -> str:
    best = None
    for fn in ast.walk(tree):
        if (
            isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            and fn.lineno <= node.lineno <= fn.end_lineno
            and (best is None or fn.lineno > best.lineno)
        ):
            best = fn
    return best.name if best else "<module>"


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "``magic_burst_ap_ratio`` since 1.152.0, _effects_types.py:793-794;",
        "gate via ``total_magic_burst_damage`` at effects.py:349). Pure DATA pin -",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "the ``ItemEffect.magic_burst_ap_ratio`` field in _effects_types.py",
        "``effects.total_magic_burst_damage``",
        "DS ``:8860`` serves the main checkout",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_target():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(_source(TARGET).splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_fields_are_item_effect_fields_defaulting_zero():
    fields = {f.name: f for f in dataclasses.fields(ItemEffect)}
    for name in _FIELDS:
        assert fields[name].default == 0.0, name


def test_fields_are_read_only_by_the_helper():
    readers = sorted(
        {
            f"{path.name}:{_enclosing_function(tree, node)}"
            for path, tree in _engine_trees()
            for node in ast.walk(tree)
            if (isinstance(node, ast.Attribute) and node.attr in _FIELDS)
            or (isinstance(node, ast.Constant) and node.value in _FIELDS)
        }
    )
    assert readers == [f"effects.py:{_HELPER}"], readers


def test_helper_is_called_only_by_compute_burst_damage_under_the_gate():
    calls = []
    for path, tree in _engine_trees():
        gated = {
            id(inner)
            for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == _GATE
            for stmt in node.body
            for inner in ast.walk(stmt)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _HELPER in (
                getattr(node.func, "id", None),
                getattr(node.func, "attr", None),
            ):
                calls.append(
                    (
                        path.name,
                        _enclosing_function(tree, node),
                        id(node) in gated,
                    )
                )
    assert calls == [("burst.py", "compute_burst_damage", True)], calls

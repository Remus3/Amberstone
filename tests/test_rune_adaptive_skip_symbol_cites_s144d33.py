"""Guard: the rune adaptive-skip prose cites burst.py by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. Three files carried the same claim -
"every consumer of the rune_procs registry skips proc_type 'adaptive'" - and
pinned it with line cites:

- ``burst.py:1034``: in ``_rune_offense_grants.py`` (module docstring),
  ``dps.py`` (the R145 comment in the stat fold) and
  ``tests/test_rune_offense_grants_r145.py`` (module docstring and the
  ``DivergenceFromRuneProcsIsDeliberateAndOneSidedTests`` docstring). Written
  by aa97e7ac1 (2026-07-20), where it named the ``if proc is None or
  proc.proc_type == "adaptive": continue`` skip in ``compute_burst_damage``'s
  rune-proc loop. That skip now sits 57 lines lower.
- ``burst.py:1030`` (``_rune_offense_grants.py``, the ranged-stack paragraph),
  written by 9637ba74c (2026-07-21), where it landed on the attackrange read
  one line above ``compute_burst_damage``'s ``_caster_role`` derivation.
- ``fight_report.py:45`` (``_rune_offense_grants.py``), written by aa97e7ac1,
  where it named the comment over ``_BURST_PROC_TYPES``. It now points at the
  ``_DEFAULT_SEQUENCE`` line.

At HEAD every claim still holds. The prose now names the symbols, and the
tests below pin each claim to the code, so a moved or renamed gate fails here.

Scope: those three files' ``burst.py:<n>`` and ``fight_report.py:<n>`` cites
only. Their ``rune_procs.py:<n>`` cites were correct at HEAD and are not
this guard's.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
BURST = DS / "burst.py"
FIGHT_REPORT = DS / "fight_report.py"

CITING = (
    DS / "_rune_offense_grants.py",
    DS / "dps.py",
    DS / "tests" / "test_rune_offense_grants_r145.py",
)

_LINE_CITE = re.compile(r"(?<![A-Za-z_])(?:burst|fight_report)\.py:\d")

# Phrases only the replacement prose carries, per citing file.
_NAMED_IN_PROSE = {
    "_rune_offense_grants.py": (
        "``burst.compute_burst_damage`` (its rune-proc loop) -> ``if proc is None",
        '``fight_report._BURST_PROC_TYPES`` -> "adaptive" is not in that set:',
        "``burst.compute_burst_damage`` derives its\n``_caster_role`` from attackrange",
    ),
    "dps.py": (
        "skips exactly that proc_type (burst.compute_burst_damage's rune-proc\n"
        "    # loop),",
    ),
    "test_rune_offense_grants_r145.py": (
        "(``burst.compute_burst_damage``'s rune-proc loop)",
        "that proc_type (``burst.compute_burst_damage``'s rune-proc loop)",
    ),
}


def _compute_burst_damage() -> ast.FunctionDef:
    tree = ast.parse(BURST.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "compute_burst_damage":
            return node
    raise AssertionError("burst.py has no top-level def compute_burst_damage")


def _is_adaptive_compare(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Attribute)
        and node.left.attr == "proc_type"
        and isinstance(node.left.value, ast.Name)
        and node.left.value.id == "proc"
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.Eq)
        and isinstance(node.comparators[0], ast.Constant)
        and node.comparators[0].value == "adaptive"
    )


def test_no_line_cites_left() -> None:
    for path in CITING:
        hits = [
            f"{path.name}:{n}: {line.strip()}"
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if _LINE_CITE.search(line)
        ]
        assert not hits, "line cites left:\n" + "\n".join(hits)


def test_replacement_prose_names_the_symbols() -> None:
    for path in CITING:
        text = path.read_text(encoding="utf-8")
        for phrase in _NAMED_IN_PROSE[path.name]:
            assert phrase in text, f"{path.name} lost: {phrase!r}"


def test_compute_burst_damage_rune_loop_skips_adaptive() -> None:
    loops = [
        node for node in ast.walk(_compute_burst_damage())
        if isinstance(node, ast.For)
        and any(
            isinstance(stmt, ast.Assign)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr == "get"
            and isinstance(stmt.value.func.value, ast.Name)
            and stmt.value.func.value.id == "RUNE_PROCS"
            for stmt in node.body
        )
    ]
    assert loops, "compute_burst_damage has no loop reading RUNE_PROCS.get"
    skips = [
        stmt for loop in loops for stmt in loop.body
        if isinstance(stmt, ast.If)
        and isinstance(stmt.test, ast.BoolOp)
        and isinstance(stmt.test.op, ast.Or)
        and any(_is_adaptive_compare(v) for v in stmt.test.values)
        and len(stmt.body) == 1
        and isinstance(stmt.body[0], ast.Continue)
    ]
    assert skips, "the RUNE_PROCS loop no longer skips proc_type == 'adaptive'"


def test_compute_burst_damage_derives_caster_role_from_attackrange() -> None:
    fn = _compute_burst_damage()
    found = False
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_caster_role" for t in node.targets)
        ):
            calls = [
                c for c in ast.walk(node.value)
                if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Name)
                and c.func.id == "attackrange_is_ranged"
            ]
            found = found or bool(calls)
    assert found, "compute_burst_damage no longer derives _caster_role via attackrange_is_ranged"


def test_fight_report_burst_proc_types_exclude_adaptive() -> None:
    tree = ast.parse(FIGHT_REPORT.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = (
            node.targets if isinstance(node, ast.Assign)
            else [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if any(isinstance(t, ast.Name) and t.id == "_BURST_PROC_TYPES" for t in targets):
            members = {
                c.value for c in ast.walk(node.value)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)
            }
            assert members, "_BURST_PROC_TYPES has no string members"
            assert "adaptive" not in members
            return
    raise AssertionError("fight_report.py has no module-level _BURST_PROC_TYPES")

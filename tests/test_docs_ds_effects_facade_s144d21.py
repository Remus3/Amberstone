"""Guard (RM-996): the ``effects.py`` module-map row counts its real logic fns.

``docs/DAEMON_SLAYER.md`` described ``effects.py`` as holding "the 14
effect-aggregation logic fns (``collect_effects``, ``total_*``,
``effective_target_armor/mr``)". That was exact at the s246 facade split
(``685b89350``: ``collect_effects``, 11 ``total_*``, the two
``effective_target_*``), but later work added ``dedupe_context`` and seven more
``total_*`` aggregators, so at 2026-10-27 the module defines 22 public logic
fns, 18 of them ``total_*``. No test read the number.

Every figure is re-derived here from the module's own AST (top-level public
``def`` statements), never from a literal, so the next added aggregator fails
this guard instead of rotting the row. ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"
_EFFECTS = _REPO_ROOT / "agents" / "daemon_slayer" / "effects.py"
_ROW_PREFIX = "| `effects.py` |"


def _public_fns() -> list[str]:
    tree = ast.parse(_EFFECTS.read_text(encoding="utf-8"))
    return [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    ]


def _row() -> str:
    rows = [ln for ln in _DOC.read_text(encoding="utf-8").splitlines() if ln.startswith(_ROW_PREFIX)]
    assert len(rows) == 1, f"expected exactly one module-map row starting {_ROW_PREFIX!r}, got {len(rows)}"
    return rows[0]


def test_effects_defines_public_logic_fns():
    # Anchor: an empty AST walk would make every count below agree with a 0.
    fns = _public_fns()
    assert "collect_effects" in fns
    assert any(name.startswith("total_") for name in fns)


def test_row_total_matches_public_fn_count():
    match = re.search(r"the (\d+) public effect-aggregation logic fns", _row())
    assert match, "effects.py row no longer states 'the N public effect-aggregation logic fns'"
    assert int(match.group(1)) == len(_public_fns())


def test_row_total_star_count_matches_module():
    match = re.search(r"the (\d+) `total_\*`", _row())
    assert match, "effects.py row no longer states 'the N `total_*`'"
    assert int(match.group(1)) == sum(1 for name in _public_fns() if name.startswith("total_"))


def test_row_names_every_non_total_public_fn():
    row = _row()
    missing = [
        name for name in _public_fns()
        if not name.startswith("total_") and f"`{name}`" not in row
    ]
    assert not missing, f"effects.py row does not name public fns {missing}"


def test_row_named_fns_exist_in_module():
    # The reverse direction: a fn the row names that the module dropped.
    named = set(re.findall(r"`([a-z][a-z0-9_]*)`", _row()))
    gone = sorted(named - set(_public_fns()))
    assert not gone, f"effects.py row names fns the module does not define: {gone}"

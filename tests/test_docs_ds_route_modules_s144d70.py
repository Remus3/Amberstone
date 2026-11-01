"""Guard: the docs/DAEMON_SLAYER.md module map names the module behind each route.

RM-1289. The module map listed ``server.py``'s routes and a row per scorer
core module, but 14 modules that back :8860 routes had no row at all: the
fight report and 1v1 matchup (``/v2/*``), the 11 additive scored-axis routes
and the three DSP live-consumer routes (measured at ENGINE 1.290.0 by reading
which module each ``_POST_ROUTES`` handler calls). A reader following a route
to its code had to grep. ``focus_board.py`` is a module with NO route (RM-843
owns the route), and the docs did not say so.

The row is found by its first cell, each ``/route`` = ``module.py`` pair on it
is parsed, and the pairs are compared with what the handlers really call,
derived from the AST of ``server.py`` (no hand-kept list in this guard):

  * a route is owed a pair when its handler calls a sibling module that no
    OTHER module-map row names;
  * the pair's module is that module, and it exists on disk;
  * no pair names a route the server does not register;
  * ``focus_board.py`` is named as route-less, and it stays route-less until
    this row is updated (a registered ``/focus-board`` fails the guard).

ASCII only.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.test_docs_daemon_slayer_drift import _SERVER

_ROOT = Path(__file__).resolve().parent.parent
_DOC = _ROOT / "docs" / "DAEMON_SLAYER.md"
_PKG = _SERVER.parent
_ROW_HEAD = "| Route-backing modules"
_PAIR = re.compile(r"`(/[^`]+)` = `([A-Za-z_]+\.py)`")
_MODULE = re.compile(r"`([A-Za-z_]+\.py)`")


def _rows() -> list[str]:
    return [ln for ln in _DOC.read_text(encoding="utf-8").splitlines()
            if ln.startswith("|")]


def _our_row() -> str:
    hits = [r for r in _rows() if r.startswith(_ROW_HEAD)]
    assert len(hits) == 1, f"expected exactly one {_ROW_HEAD!r} row, got {len(hits)}"
    return hits[0]


def _documented_elsewhere() -> set[str]:
    own = _our_row()
    return {m for r in _rows() if r != own for m in _MODULE.findall(r)}


def _handler_modules() -> dict[str, set[str]]:
    """route -> sibling modules its handler body references (AST, not a list)."""
    tree = ast.parse(_SERVER.read_text(encoding="utf-8"))
    alias: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.level == 1 and n.module:
            for a in n.names:
                alias[a.asname or a.name] = n.module
    handlers: dict[str, str] = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_POST_ROUTES":
            for k, v in zip(n.value.keys, n.value.values):
                handlers[k.value] = v.id
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    out: dict[str, set[str]] = {}
    for route, name in handlers.items():
        used = set()
        for x in ast.walk(fns[name]):
            if isinstance(x, ast.Name) and x.id in alias:
                used.add(alias[x.id])
            elif (isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name)
                    and x.value.id in alias):
                used.add(alias[x.value.id])
        out[route] = {m for m in used if (_PKG / f"{m}.py").exists()}
    return out


def _owed() -> dict[str, str]:
    elsewhere = {m[:-3] for m in _documented_elsewhere()}
    owed = {}
    for route, mods in _handler_modules().items():
        missing = mods - elsewhere
        if missing:
            assert len(missing) == 1, f"{route} has two undocumented modules: {missing}"
            owed[route] = f"{next(iter(missing))}.py"
    return owed


def test_anchor_owed_routes_are_found():
    """An empty derivation would pass every check below vacuously."""
    owed = _owed()
    assert len(owed) >= 10, owed
    assert owed["/cc-output"] == "cc_output.py"
    assert owed["/v2/fight-report"] == "fight_report.py"


def test_row_exists_and_pairs_parse():
    pairs = _PAIR.findall(_our_row())
    assert len(pairs) >= 10, pairs


def test_row_pairs_equal_what_the_handlers_call():
    documented = dict(_PAIR.findall(_our_row()))
    assert documented == _owed()


def test_every_named_module_exists_on_disk():
    for route, module in _PAIR.findall(_our_row()):
        assert (_PKG / module).is_file(), (route, module)


def test_focus_board_is_named_routeless_and_is_routeless():
    row = _our_row()
    assert "`focus_board.py`" in row
    assert "no route" in row
    assert "/focus-board" not in _handler_modules(), (
        "a /focus-board route is registered: update the docs row, then this guard"
    )

"""S144-P-354 - every production winreg key open is closed on every path.

A ``winreg`` key is a ``PyHKEY``: nothing closes it promptly when the code between the open and a
straight-line ``Close()`` raises (``QueryValueEx`` raises ``OSError`` for an absent value, which
is the normal case for a policy key). This census enumerates every call of ``winreg.OpenKey``,
``OpenKeyEx``, ``CreateKey``, ``CreateKeyEx`` and ``ConnectRegistry`` (also ``_winreg`` and a
``from winreg import`` name) in the tracked non-test ``.py`` and requires each to be one of:

- WITH: the call is the context expression of a ``with`` item (``with winreg.OpenKey(...) as k``).
- WITH_NAME: the call is assigned to a name and the same function enters ``with <name>:``.
- FINALLY: the enclosing function calls ``Close`` or ``CloseKey`` in a ``finally`` block.

Measured 2026-11-07 over the git index: see ``_SITES``. ``ops/fleet_kit/`` (vendored,
byte-pinned), ``tests/``, ``agents/agent3_testing/suite/`` and ``docs/_archive/`` are out of
scope. Stated limits: WITH_NAME means the function enters a ``with`` on that name, not that
nothing can raise between the open and the ``with`` (the pair is adjacent at the one site);
FINALLY means a ``Close`` in any ``finally`` of the function, not on THIS key, and WITH_NAME
does not check order; ``import winreg as x`` is not seen; a ``getattr``-built call or a ctypes ``RegOpenKeyEx`` is not seen (the measured count of
``Reg*`` ctypes calls in production is zero and the same scan below keeps it there).
"""
from __future__ import annotations

import ast
import functools

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "agents/agent3_testing/suite/", "docs/_archive/")

_OPENERS = frozenset({"OpenKey", "OpenKeyEx", "CreateKey", "CreateKeyEx", "ConnectRegistry"})
_MODULES = frozenset({"winreg", "_winreg"})
_CLOSERS = frozenset({"Close", "CloseKey"})
_CTYPES_REG = ("RegOpenKeyEx", "RegOpenKey", "RegCreateKeyEx", "RegCloseKey")

# file -> number of winreg opener calls (measured 2026-11-07).
_SITES = {
    "core/recycle_bin.py": 2,
    "ops/loop/headless_env.py": 1,
    "tools/gated_b29_window_parity.py": 1,
}


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST | None:
    cur = parents.get(node)
    while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
        cur = parents.get(cur)
    return cur


def _imported_openers(tree: ast.AST) -> frozenset[str]:
    """Local names bound by ``from winreg import OpenKey [as x]``."""
    names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module in _MODULES:
            names.update(a.asname or a.name for a in n.names if a.name in _OPENERS)
    return frozenset(names)


def _is_opener(call: ast.Call, bare: frozenset[str]) -> bool:
    f = call.func
    if isinstance(f, ast.Attribute) and f.attr in _OPENERS:
        return isinstance(f.value, ast.Name) and f.value.id in _MODULES
    return isinstance(f, ast.Name) and f.id in bare


def _closes_in_finally(scope: ast.AST) -> bool:
    for t in ast.walk(scope):
        if not isinstance(t, ast.Try):
            continue
        for stmt in t.finalbody:
            for m in ast.walk(stmt):
                if (isinstance(m, ast.Call) and isinstance(m.func, ast.Attribute)
                        and m.func.attr in _CLOSERS):
                    return True
                if (isinstance(m, ast.Call) and isinstance(m.func, ast.Name)
                        and m.func.id in _CLOSERS):
                    return True
    return False


def _facts(source: str) -> list[tuple[str, str, set[str]]]:
    """For each opener call: (enclosing function, API, safe shapes it follows)."""
    tree = ast.parse(source)
    parents = _parents(tree)
    bare = _imported_openers(tree)
    out: list[tuple[str, str, set[str]]] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or not _is_opener(n, bare):
            continue
        fn = _enclosing_function(n, parents)
        scope = fn if fn is not None else tree
        held: set[str] = set()
        parent = parents.get(n)
        if isinstance(parent, ast.withitem) and parent.context_expr is n:
            held.add("WITH")
        if isinstance(parent, ast.Assign) and len(parent.targets) == 1 \
                and isinstance(parent.targets[0], ast.Name):
            name = parent.targets[0].id
            for w in ast.walk(scope):
                if isinstance(w, (ast.With, ast.AsyncWith)) and any(
                        isinstance(i.context_expr, ast.Name) and i.context_expr.id == name
                        for i in w.items):
                    held.add("WITH_NAME")
        if _closes_in_finally(scope):
            held.add("FINALLY")
        api = n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
        out.append((getattr(fn, "name", "<module>"), api, held))
    return out


def _ctypes_reg_calls(source: str) -> list[str]:
    tree = ast.parse(source)
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and n.attr in _CTYPES_REG:
            hits.append(n.attr)
        elif isinstance(n, ast.Name) and n.id in _CTYPES_REG:
            hits.append(n.id)
    return hits


@functools.lru_cache(maxsize=1)
def _tree_scan() -> tuple[dict[str, list[tuple[str, str, set[str]]]], dict[str, list[str]]]:
    facts: dict[str, list[tuple[str, str, set[str]]]] = {}
    ctypes_reg: dict[str, list[str]] = {}
    for p in repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(p)
        if rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel:
            continue
        try:
            src = p.read_text(encoding="utf-8")
            rows = _facts(src)
            regs = _ctypes_reg_calls(src)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        if rows:
            facts[rel] = rows
        if regs:
            ctypes_reg[rel] = regs
    return facts, ctypes_reg


def test_walk_is_not_vacuous():
    files = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert "core/recycle_bin.py" in files
    assert len(_tree_scan()[0]) >= 3


def test_every_winreg_open_site_is_pinned_by_file_and_count():
    facts, _ = _tree_scan()
    assert {f: len(v) for f, v in facts.items()} == _SITES, (
        "a winreg key open appeared or went: review how it is closed (a with item, a with on "
        "the bound name, or a finally), then update _SITES")


def test_every_winreg_key_is_closed_on_every_path():
    facts, _ = _tree_scan()
    unsafe = {}
    for rel, rows in facts.items():
        bad = [f"{fn}:{api}" for fn, api, held in rows if not held]
        if bad:
            unsafe[rel] = bad
    assert not unsafe, (
        "a winreg key whose Close() an exception skips (not a with item, no with on the bound "
        f"name, no Close in a finally): {unsafe}")


def test_no_ctypes_registry_call_in_production():
    """The raw RegOpenKeyEx family hands back a bare HKEY nothing closes: held at zero."""
    assert _tree_scan()[1] == {}


def test_detector_classifies_each_shape():
    with_item = ("import winreg\ndef f():\n    with winreg.OpenKey(1, 'x') as k:\n        pass\n")
    assert _facts(with_item) == [("f", "OpenKey", {"WITH"})]
    named = ("import winreg\ndef f():\n    k = winreg.OpenKey(1, 'x')\n    with k:\n"
             "        pass\n")
    assert _facts(named) == [("f", "OpenKey", {"WITH_NAME"})]
    fin = ("import winreg\ndef f():\n    k = winreg.OpenKeyEx(1, 'x')\n    try:\n        pass\n"
           "    finally:\n        k.Close()\n")
    assert _facts(fin) == [("f", "OpenKeyEx", {"FINALLY"})]
    bare = ("from winreg import CreateKey as ck\ndef f():\n    with ck(1, 'x'):\n        pass\n")
    assert _facts(bare) == [("f", "ck", {"WITH"})]


def test_detector_flags_a_straight_line_close_as_unsafe():
    """Positive control: a close after a call that can raise, outside a finally, is unsafe."""
    leak = ("import winreg\ndef f():\n    k = winreg.OpenKey(1, 'x')\n"
            "    v = winreg.QueryValueEx(k, 'y')\n    k.Close()\n    return v\n")
    assert _facts(leak) == [("f", "OpenKey", set())]
    # a Close in a try BODY (not finally) does not cover the key
    body = ("import winreg\ndef f():\n    k = winreg.OpenKey(1, 'x')\n    try:\n"
            "        k.Close()\n    finally:\n        pass\n")
    assert _facts(body) == [("f", "OpenKey", set())]
    # a with on some OTHER name does not cover it
    other = ("import winreg\ndef f(o):\n    k = winreg.OpenKey(1, 'x')\n    with o:\n"
             "        pass\n")
    assert _facts(other) == [("f", "OpenKey", set())]
    # a same-named method on something that is not winreg is not an opener
    assert _facts("def f(db):\n    db.OpenKey(1)\n") == []
    assert _ctypes_reg_calls("def f(adv):\n    adv.RegOpenKeyEx(1)\n") == ["RegOpenKeyEx"]

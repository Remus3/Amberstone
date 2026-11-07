"""S144-P-348 - every direct production ``socket.socket`` / ``socket.create_connection`` call closes its socket on every path.

A probe socket that raises between ``socket.socket(...)`` and a straight-line ``.close()`` leaks
a descriptor, and these probes run on timers (the supervisor port check, the vision
single-instance guard, the rc_facts SessionStart probe). This census enumerates every direct
socket constructor in the tracked non-test ``.py`` and requires each to be one of:

- WITH: the call is the context expression of a ``with`` item (closed on every path).
- FINALLY: the enclosing function calls ``.close()`` inside the ``finally`` block of a ``try``
  (the socket is built before the ``try`` so the constructor itself cannot leak).

A bare straight-line ``.close()`` is NOT enough: it is skipped by an exception. Measured
2026-11-07 over the git index (alias-aware AST): 5 ``socket.socket`` calls in 5 files (3 FINALLY,
tools/run_packaged_smoke.py already WITH, and vision_server/__init__.py, a straight-line close that
this row converted to WITH) plus 2 ``socket.create_connection`` calls (ops/launcher/service_host.py,
ops/loop/headless_env.py) already under ``with``; ``websocket.create_connection`` is a different
module and is not seen. ``ops/fleet_kit/`` (vendored, byte-pinned), ``tests/``,
``agents/agent3_testing/suite/`` and ``docs/_archive/`` are out of scope. Stated limits: a
direct call through the module, an alias or ``from socket import socket`` only; a socket stored
on an attribute or returned is not proven closed by its owner (none exist at this measurement,
and a new one fails as unnamed-shape because it is neither WITH nor FINALLY); a subclass
construction is not seen (vision_server/_pool.py builds a ``_ReadCappedSocket`` from an accepted fd);
FINALLY means the enclosing function closes in some finally, not that nothing runs between the
constructor and the ``try`` (a ``setsockopt`` / ``settimeout`` on a fresh socket in
agents/_supervisor_common.py and tools/rc_facts.py), which is accepted as unreachable-in-practice.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "agents/agent3_testing/suite/", "docs/_archive/")
_CTORS = ("socket", "create_connection")

# file -> number of direct socket constructor calls (measured 2026-11-07).
_SITES = {
    "agents/_supervisor_common.py": 1,
    "core/port_handoff.py": 1,
    "ops/launcher/service_host.py": 1,
    "ops/loop/headless_env.py": 1,
    "tools/rc_facts.py": 1,
    "tools/run_packaged_smoke.py": 1,
    "vision_server/__init__.py": 1,
}


def _aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    mods: set[str] = set()
    funcs: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods.update((a.asname or a.name) for a in n.names if a.name == "socket")
        elif isinstance(n, ast.ImportFrom) and n.module == "socket":
            funcs.update((a.asname or a.name) for a in n.names if a.name in _CTORS)
    return mods, funcs


def _is_ctor(call: ast.Call, mods: set[str], funcs: set[str]) -> bool:
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr in _CTORS
            and isinstance(f.value, ast.Name) and f.value.id in mods) or (
        isinstance(f, ast.Name) and f.id in funcs)


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST | None:
    cur = parents.get(node)
    while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
        cur = parents.get(cur)
    return cur


def _is_with_item(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> bool:
    p = parents.get(call)
    return isinstance(p, ast.withitem) and p.context_expr is call


def _closes_in_finally(scope: ast.AST) -> bool:
    for n in ast.walk(scope):
        if isinstance(n, ast.Try):
            for stmt in n.finalbody:
                for m in ast.walk(stmt):
                    if (isinstance(m, ast.Call) and isinstance(m.func, ast.Attribute)
                            and m.func.attr == "close"):
                        return True
    return False


def _facts(source: str) -> list[set[str]]:
    """For each socket constructor call in ``source``: the safe shapes it follows."""
    tree = ast.parse(source)
    mods, funcs = _aliases(tree)
    parents = _parents(tree)
    out: list[set[str]] = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and _is_ctor(n, mods, funcs)):
            continue
        held: set[str] = set()
        if _is_with_item(n, parents):
            held.add("WITH")
        fn = _enclosing_function(n, parents)
        if fn is not None and _closes_in_finally(fn):
            held.add("FINALLY")
        out.append(held)
    return out


def _tree_facts() -> dict[str, list[set[str]]]:
    out: dict[str, list[set[str]]] = {}
    for p in repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(p)
        if rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel:
            continue
        try:
            facts = _facts(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        if facts:
            out[rel] = facts
    return out


def test_walk_is_not_vacuous():
    files = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert "core/port_handoff.py" in files
    assert len(_tree_facts()) >= 5


def test_every_socket_site_is_pinned_by_file_and_count():
    tree = _tree_facts()
    assert {f: len(v) for f, v in tree.items()} == _SITES, (
        "a socket constructor appeared or went: review its close shape (WITH or a close in "
        "finally), then update _SITES")


def test_every_socket_closes_on_every_path():
    unsafe = {rel: [i for i, held in enumerate(v) if not held]
              for rel, v in _tree_facts().items() if any(not h for h in v)}
    assert not unsafe, (
        "a socket whose close is skipped by an exception (no `with`, no close in a finally); "
        f"wrap it in `with` or close in a finally: {unsafe}")


def test_detector_classifies_each_shape():
    with_ = "import socket\ndef f():\n    with socket.socket() as s:\n        s.connect(('h', 1))\n"
    assert _facts(with_) == [{"WITH"}]
    fin = ("import socket as so\ndef f():\n    s = so.socket()\n    try:\n        s.bind(('h', 1))\n"
           "    finally:\n        s.close()\n")
    assert _facts(fin) == [{"FINALLY"}]
    conn = "from socket import create_connection\ndef f():\n    with create_connection(('h', 1)):\n        pass\n"
    assert _facts(conn) == [{"WITH"}]


def test_detector_flags_a_straight_line_close_as_unsafe():
    """Positive control: a close after the connect, outside any finally, holds NO safe shape."""
    leak = ("import socket\ndef f():\n    s = socket.socket()\n    s.settimeout(1)\n"
            "    ok = s.connect_ex(('h', 1)) == 0\n    s.close()\n    return ok\n")
    assert _facts(leak) == [set()]
    # a different module's constructor is not a socket
    assert _facts("import websocket\nwebsocket.create_connection('u')\n") == []

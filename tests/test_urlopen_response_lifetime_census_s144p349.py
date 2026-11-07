"""S144-P-349 - every production ``urlopen`` call closes its response on every path.

``urllib.request.urlopen`` returns a live socket-backed response. A bare
``urlopen(req).read()`` or ``r = urlopen(req); ... r.read()`` leaves that response to the garbage
collector: CPython closes it on refcount zero, but an exception between the call and the read
keeps the frame (and the socket) alive in the traceback, and any other interpreter emits a
ResourceWarning. The long-running callers (the Live Client relay uploads every few seconds) are
where a leak would accumulate. This census enumerates every ``urlopen`` call in the tracked
non-test ``.py`` and requires each to be one of:

- WITH: the call is the context expression of a ``with`` item.
- SEAM: the call is the value of a ``return`` in a function named in ``_SEAMS`` - a one-line
  indirection so a test can inject a transport failure; its callers hold the response in ``with``.

Measured 2026-11-07 over the git index: 84 ``urlopen`` calls in 55 files; 79 were already WITH,
4 were a bare ``.read()`` / assign-then-read (tools/calibrate_vision.py twice,
tools/liveclient_relay.py, tools/recover_match_via_match_v5.py) and were converted to WITH by this
row, and 1 is the SEAM (dashboard/routes_loadout.py ``_urlopen``). ``ops/fleet_kit/`` (vendored,
byte-pinned), ``tests/``, ``agents/agent3_testing/suite/`` and ``docs/_archive/`` are out of scope.

Stated limits: the match is on the callee NAME ``urlopen`` (module attribute, ``from ... import``
or a local alias of that name), so ``opener.open(...)`` on a ``build_opener`` object is not seen
(lib/wiki_consent.py returns one to its caller, ops/launcher/updater.py is PKG-owned), and a
renamed alias (``fetch = urlopen``) is not seen. A response used as WITH is closed on a normal
exit and on an exception; an ``HTTPError`` raised by ``urlopen`` itself is a response the caller
reads and drops, which this census does not model.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "agents/agent3_testing/suite/", "docs/_archive/")

# (file, function) -> why a bare returned urlopen is acceptable.
_SEAMS = {
    ("dashboard/routes_loadout.py", "_urlopen"):
        "test seam over urllib.request.urlopen; its caller wraps the result in `with`",
}


def _is_urlopen(call: ast.Call) -> bool:
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr == "urlopen") or (
        isinstance(f, ast.Name) and f.id == "urlopen")


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]):
    cur = parents.get(node)
    while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
        cur = parents.get(cur)
    return cur


def _shapes(source: str) -> list[tuple[int, str, str | None]]:
    """(line, shape, enclosing function name) for each urlopen call; shape is WITH, RETURN or BARE."""
    tree = ast.parse(source)
    parents = _parents(tree)
    out = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and _is_urlopen(n)):
            continue
        p = parents.get(n)
        fn = _enclosing_function(n, parents)
        fname = fn.name if fn is not None else None
        if isinstance(p, ast.withitem) and p.context_expr is n:
            shape = "WITH"
        elif isinstance(p, ast.Return):
            shape = "RETURN"
        else:
            shape = "BARE"
        out.append((n.lineno, shape, fname))
    return sorted(out)


def _tree_shapes() -> dict[str, list[tuple[int, str, str | None]]]:
    out: dict[str, list[tuple[int, str, str | None]]] = {}
    for p in repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(p)
        if rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel:
            continue
        try:
            shapes = _shapes(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        if shapes:
            out[rel] = shapes
    return out


def test_walk_is_not_vacuous():
    tree = _tree_shapes()
    assert "tools/liveclient_relay.py" in tree
    assert "dashboard/routes_loadout.py" in tree
    assert sum(len(v) for v in tree.values()) >= 60


def test_every_urlopen_response_is_closed_on_every_path():
    bad = []
    for rel, shapes in _tree_shapes().items():
        for line, shape, fname in shapes:
            if shape == "WITH":
                continue
            if shape == "RETURN" and (rel, fname) in _SEAMS:
                continue
            bad.append(f"{rel}:{line} ({shape} in {fname})")
    assert not bad, (
        "an urlopen response that is not the context expression of a `with` (or a named "
        f"returning seam) is left to the garbage collector; wrap it in `with`: {bad}")


def test_every_seam_row_is_live():
    """A seam row that matches no returned urlopen is a dead exemption a new bare call could hide behind."""
    tree = _tree_shapes()
    for (rel, fname), why in _SEAMS.items():
        assert why
        assert any(shape == "RETURN" and fn == fname for _l, shape, fn in tree.get(rel, [])), (rel, fname)


def test_detector_classifies_each_shape():
    with_ = "import urllib.request as u\ndef f(r):\n    with u.urlopen(r, timeout=1) as x:\n        return x.read()\n"
    assert [s for _l, s, _f in _shapes(with_)] == ["WITH"]
    imp = "from urllib.request import urlopen\ndef f(r):\n    with urlopen(r) as x:\n        pass\n"
    assert [s for _l, s, _f in _shapes(imp)] == ["WITH"]
    ret = "import urllib.request\ndef _urlopen(r):\n    return urllib.request.urlopen(r)\n"
    assert _shapes(ret) == [(3, "RETURN", "_urlopen")]


def test_detector_flags_a_bare_response_as_unsafe():
    """Positive controls: chained read, assign-then-read and a bare statement all hold BARE."""
    chained = "import urllib.request\ndef f(r):\n    return urllib.request.urlopen(r).read()\n"
    assert [s for _l, s, _f in _shapes(chained)] == ["BARE"]
    assigned = "import urllib.request\ndef f(r):\n    x = urllib.request.urlopen(r)\n    return x.read()\n"
    assert [s for _l, s, _f in _shapes(assigned)] == ["BARE"]
    stmt = "from urllib.request import urlopen\nurlopen('http://h')\n"
    assert [s for _l, s, _f in _shapes(stmt)] == ["BARE"]
    # an unrelated callee is not a urlopen
    assert _shapes("import webbrowser\nwebbrowser.open('u')\n") == []

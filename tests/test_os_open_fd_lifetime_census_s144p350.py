"""S144-P-350 - every production ``os.open`` returns a descriptor that is closed on every path.

``os.open`` hands back a bare integer: nothing closes it when the code between the open and a
straight-line ``os.close(fd)`` raises (``os.write`` on a full disk, a failed ``fstat``), so the
descriptor stays open for the life of the process. The singleton-lock claims below run in
long-lived supervisors and loop launchers. This census enumerates every ``os.open`` call in the
tracked non-test ``.py`` and requires each to be one of:

- FDOPEN: the descriptor is handed to ``os.fdopen`` as a ``with`` item (the file object owns it).
- FINALLY: the enclosing function calls ``os.close(<that name>)`` inside a ``finally`` body (the
  open sits before the ``try``, so the open itself cannot leak).
- NAMED: a row in ``_NAMED`` below: the descriptor is deliberately not closed here because an
  owner outlives the function (a held lock on ``self``, a returned descriptor, a wrapper whose
  ``close()`` closes it). A NAMED row states who closes it.

A straight-line ``os.close`` is NOT enough (it is skipped by an exception) and is refused.
Measured 2026-11-07 over the git index (alias-aware AST): 17 ``os.open`` calls in 13 files; 12 in
the safe shapes after this row (it converted agents/_supervisor_common.py x2 and
ops/loop/drain_waves_2_3.py from a straight-line close to a finally) and 5 NAMED. ``os.fdopen``
on a descriptor that did not come from ``os.open`` (the two Win32 ``CreateFileW`` +
``msvcrt.open_osfhandle`` helpers) is a different source and is not seen. ``ops/fleet_kit/``
(vendored, byte-pinned), ``tests/``, ``agents/agent3_testing/suite/`` and ``docs/_archive/`` are
out of scope. Stated limits: a direct ``os.open`` through the ``os`` module, an alias or
``from os import open`` only; FINALLY means a finally in the same function closes the name, not
that no statement runs between the open and the ``try``.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "agents/agent3_testing/suite/", "docs/_archive/")

# file -> number of os.open calls (measured 2026-11-07).
_SITES = {
    "agents/_supervisor_common.py": 3,
    "core/operator_notify.py": 1,
    "ops/launcher/first_run.py": 3,
    "ops/launcher/service_host.py": 1,
    "ops/launcher/update_cycle.py": 1,
    "ops/loop/drain_waves_2_3.py": 1,
    "ops/loop/inbox_tick.py": 1,
    "ops/loop/slots.py": 1,
    "ops/rc_supervisor.py": 1,
    "ops/rc_transactional_deploy.py": 1,
    "tools/inbox_responder_runner.py": 1,
    "tools/rc_facts.py": 1,
    "tools/sibling_name_sweep.py": 1,
}

# (file, function) -> who closes the descriptor. Every row names a real owner.
_NAMED = {
    ("ops/launcher/first_run.py", "hold_dir"): (
        "two os.open calls; the descriptor goes into a HeldDir whose close() runs os.close, and "
        "the not-a-directory branch closes it before returning None"),
    ("ops/launcher/first_run.py", "_open_new"): (
        "returns the creating descriptor; the caller closes it in a finally"),
    ("ops/launcher/service_host.py", "acquire"): (
        "a held singleton lock: the descriptor is kept on self._fd and closed by release(); "
        "the failure branch closes it before returning False"),
    ("ops/rc_supervisor.py", "acquire"): (
        "FROZEN file, read only: the same held-lock shape, kept on self._fd and closed on "
        "release; the failure branch closes it before returning False"),
}


def _aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    mods: set[str] = set()
    funcs: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods.update((a.asname or a.name) for a in n.names if a.name == "os")
        elif isinstance(n, ast.ImportFrom) and n.module == "os":
            funcs.update((a.asname or a.name) for a in n.names if a.name == "open")
    return mods, funcs


def _is_open(call: ast.Call, mods: set[str], funcs: set[str]) -> bool:
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr == "open"
            and isinstance(f.value, ast.Name) and f.value.id in mods) or (
        isinstance(f, ast.Name) and f.id in funcs)


def _is_os_call(call: ast.Call, attr: str, mods: set[str]) -> bool:
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr == attr
            and isinstance(f.value, ast.Name) and f.value.id in mods)


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST | None:
    cur = parents.get(node)
    while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
        cur = parents.get(cur)
    return cur


def _assigned_name(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> str | None:
    p = parents.get(call)
    if isinstance(p, ast.Assign) and len(p.targets) == 1 and isinstance(p.targets[0], ast.Name):
        return p.targets[0].id
    return None


def _first_arg_is(call: ast.Call, name: str) -> bool:
    return bool(call.args) and isinstance(call.args[0], ast.Name) and call.args[0].id == name


def _fdopen_with(scope: ast.AST, name: str, mods: set[str]) -> bool:
    for n in ast.walk(scope):
        if isinstance(n, ast.withitem):
            e = n.context_expr
            if isinstance(e, ast.Call) and _is_os_call(e, "fdopen", mods) and _first_arg_is(e, name):
                return True
    return False


def _closed_in_finally(scope: ast.AST, name: str, mods: set[str]) -> bool:
    for n in ast.walk(scope):
        if isinstance(n, ast.Try):
            for stmt in n.finalbody:
                for m in ast.walk(stmt):
                    if (isinstance(m, ast.Call) and _is_os_call(m, "close", mods)
                            and _first_arg_is(m, name)):
                        return True
    return False


def _facts(source: str) -> list[tuple[str, set[str]]]:
    """For each os.open call in ``source``: (enclosing function name, safe shapes it follows)."""
    tree = ast.parse(source)
    mods, funcs = _aliases(tree)
    parents = _parents(tree)
    out: list[tuple[str, set[str]]] = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and _is_open(n, mods, funcs)):
            continue
        fn = _enclosing_function(n, parents)
        name = _assigned_name(n, parents)
        held: set[str] = set()
        if fn is not None and name is not None:
            if _fdopen_with(fn, name, mods):
                held.add("FDOPEN")
            if _closed_in_finally(fn, name, mods):
                held.add("FINALLY")
        out.append((getattr(fn, "name", "<module>"), held))
    return out


def _tree_facts() -> dict[str, list[tuple[str, set[str]]]]:
    out: dict[str, list[tuple[str, set[str]]]] = {}
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
    assert "ops/loop/inbox_tick.py" in files
    assert len(_tree_facts()) >= 10


def test_every_os_open_site_is_pinned_by_file_and_count():
    tree = _tree_facts()
    assert {f: len(v) for f, v in tree.items()} == _SITES, (
        "an os.open call appeared or went: review how its descriptor is closed (FDOPEN, a "
        "finally, or a NAMED owner), then update _SITES")


def test_every_os_open_descriptor_is_closed_on_every_path():
    unsafe = {}
    for rel, rows in _tree_facts().items():
        bad = [fn for fn, held in rows if not held and (rel, fn) not in _NAMED]
        if bad:
            unsafe[rel] = bad
    assert not unsafe, (
        "an os.open descriptor whose close is skipped by an exception (no os.fdopen `with`, no "
        "os.close(fd) in a finally, no NAMED owner); close it in a finally: "
        f"{unsafe}")


def test_every_named_row_is_a_real_unsafe_site_with_a_reason():
    """A NAMED row must still be needed (the site holds no safe shape) and carry a reason."""
    tree = _tree_facts()
    for (rel, fn), why in _NAMED.items():
        assert why.strip(), (rel, fn)
        rows = [held for name, held in tree.get(rel, []) if name == fn]
        assert rows, f"{rel}:{fn} has no os.open any more - drop the row"
        assert any(not held for held in rows), (
            f"{rel}:{fn} now closes in a finally or an fdopen with - drop the row")


def test_detector_classifies_each_shape():
    fin = ("import os\ndef f(p):\n    fd = os.open(p, 0)\n    try:\n        os.write(fd, b'x')\n"
           "    finally:\n        os.close(fd)\n")
    assert _facts(fin) == [("f", {"FINALLY"})]
    fdo = "import os as o\ndef f(p):\n    fd = o.open(p, 0)\n    with o.fdopen(fd, 'w') as fh:\n        fh.write('x')\n"
    assert _facts(fdo) == [("f", {"FDOPEN"})]
    frm = ("from os import open as oo, close\nimport os\ndef f(p):\n    fd = oo(p, 0)\n    try:\n        pass\n"
           "    finally:\n        os.close(fd)\n")
    assert _facts(frm) == [("f", {"FINALLY"})]


def test_detector_flags_a_straight_line_close_as_unsafe():
    """Positive control: a close after a write, outside any finally, holds NO safe shape."""
    leak = ("import os\ndef f(p):\n    fd = os.open(p, 0)\n    os.write(fd, b'x')\n    os.close(fd)\n")
    assert _facts(leak) == [("f", set())]
    # a close of a DIFFERENT name in a finally does not cover this descriptor
    other = ("import os\ndef f(p, q):\n    fd = os.open(p, 0)\n    try:\n        pass\n"
             "    finally:\n        os.close(q)\n")
    assert _facts(other) == [("f", set())]
    # a different module's open is not an fd open
    assert _facts("import gzip\ngzip.open('x')\n") == []


# ---- behaviour: a failed os.write no longer strands the descriptor -------------------------

def _track_close_and_fail_write(monkeypatch):
    import os

    opened: list[int] = []
    closed: list[int] = []
    real_open, real_close = os.open, os.close

    def _open(*a, **k):
        fd = real_open(*a, **k)
        opened.append(fd)
        return fd

    def _close(fd):
        closed.append(fd)
        return real_close(fd)

    def _write(fd, data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "open", _open)
    monkeypatch.setattr(os, "close", _close)
    monkeypatch.setattr(os, "write", _write)
    return opened, closed


def test_drain_waves_take_lock_closes_the_fd_when_the_write_fails(tmp_path, monkeypatch):
    import pytest

    from ops.loop import drain_waves_2_3 as dw

    monkeypatch.setattr(dw, "LOCK", tmp_path / "lock" / "drain.lock")
    opened, closed = _track_close_and_fail_write(monkeypatch)
    with pytest.raises(OSError):
        dw._take_lock()
    assert opened and closed == opened


def test_supervisor_acquire_lock_closes_the_fd_when_the_write_fails(tmp_path, monkeypatch):
    import pytest

    from agents import _supervisor_common as sc

    monkeypatch.setattr(sc, "STATE_DIR", tmp_path)
    monkeypatch.setattr(sc, "_reap_orphan_lockfile_tmps", lambda: None)
    monkeypatch.setattr(sc, "_sentinel_path", lambda: tmp_path / "supervisor.sentinel")
    opened, closed = _track_close_and_fail_write(monkeypatch)
    with pytest.raises(OSError):
        sc.acquire_lock()
    assert opened and closed == opened

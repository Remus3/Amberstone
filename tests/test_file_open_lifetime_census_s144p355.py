"""S144-P-355 - every production file open is closed on every path.

A file object that is not a ``with`` item stays open when the code between the open and a
straight-line ``close()`` raises. The runtime holds files for the life of long-running
watchers, so a stranded handle is a real lock on a log or a sidecar. This census enumerates
every file-object open in the tracked non-test ``.py`` and requires each to be one of:

- WITH: the call is itself a ``with`` item.
- WITH_NAME: the call is assigned to a name and the same function has ``with <name>`` (the open
  sits before the ``with``, so the open itself cannot leak).
- FINALLY: the same function calls ``<name>.close()`` inside a ``finally`` body.
- NAMED: a row in ``_NAMED`` below: the file is returned or kept on ``self`` and an owner
  outlives the function, or it is a process-lifetime log sink. A NAMED row states who closes it.

Measured 2026-11-07 over the git index (AST, alias-aware for ``open``): 209 file opens in 140
files, 194 of them ``with`` items and 15 not (5 WITH_NAME, 10 NAMED rows in 9 functions; this
row converted tools/p3_ascii_sweep.py's ``tokenize.tokenize(path.open("rb").readline)`` to a
``with`` and closed the handle tools/lcu_push_watcher._open_shared stranded when the ``seek``
after the open raised). The kinds seen:
builtin ``open``, ``io.open``, ``codecs`` / ``gzip`` / ``bz2`` / ``lzma`` / ``tarfile`` ``.open``,
``os.fdopen`` and ``zipfile.ZipFile``, plus a ``<receiver>.open(`` method call (``Path.open``)
whose first argument is a mode string (``Image.open(src)`` and ``RoundStore.open(path)`` are not
file opens and are not seen).

Stated limits: ``Image.open`` is a different library with its own lazy-file rule and is not
seen; ``os.open`` descriptors are S144-P-350 and CreateFileW handles are S144-P-352;
``urlopen`` responses are S144-P-349. WITH_NAME and FINALLY mean the same function holds the
shape, not that no statement runs between the open and the ``with``. ``ops/fleet_kit/``
(vendored, byte-pinned), ``tests/``, ``agents/agent3_testing/suite/`` and ``docs/_archive/``
are out of scope.
"""
from __future__ import annotations

import ast
import re

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "agents/agent3_testing/suite/", "docs/_archive/")
_OPEN_MODULES = {"io", "codecs", "gzip", "bz2", "lzma", "tarfile"}
_MODE = re.compile(r"^[rwaxbt+U]{1,4}$")

_MEASURED_TOTAL = 209
_MEASURED_NOT_WITH = 15

_SINK = ("a process-lifetime --log-file sink for a one-shot CLI: it replaces sys.stdout and "
         "sys.stderr for the whole run and is released at interpreter exit, so no function "
         "outlives it to close it")

# (file, function) -> who closes it. Every row names a real owner.
_NAMED = {
    ("core/live_session_recorder.py", "_open_append"): (
        "returns an append handle; the one caller keeps it on self._fh, closes it on a failed "
        "header write, and _close_file closes it otherwise"),
    ("tft/sources/tft_log.py", "_open_shared"): (
        "returns the shared-delete reader (POSIX open and the Win32 os.fdopen branch); both "
        "callers (tft_log's tail reader and gated_tft15_planner) use it as a with item"),
    ("tools/lcu_push_watcher.py", "_win_open_shared_delete"): (
        "returns the os.fdopen reader to _open_shared"),
    ("tools/lcu_push_watcher.py", "_open_shared"): (
        "returns the reader to main(), which closes it on midnight rollover and after the poll "
        "loop; a seek that fails after the open closes it here before returning None"),
    ("tools/build_rank_baselines.py", "main"): _SINK,
    ("tools/ladder_role_scout.py", "main"): _SINK,
    ("tools/timeline_ingest.py", "main"): _SINK,
    ("tools/replay_roster_pull.py", "_open_log_sink"): _SINK + "; main() holds the returned stream",
    ("tools/console_flash_detector.py", "__init__"): (
        "the _Stream class owns the handle; the detector's run closes the stream in a finally "
        "around _capture, so every exit path including a raise closes it (S144-P-356)"),
}


def _open_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Names that mean builtin ``open`` after ``from io import open as x`` style imports."""
    funcs = {"open"}
    mods: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module in _OPEN_MODULES:
            funcs.update((a.asname or a.name) for a in n.names if a.name == "open")
        elif isinstance(n, ast.Import):
            mods.update((a.asname or a.name) for a in n.names if a.name in _OPEN_MODULES)
    return funcs, mods | _OPEN_MODULES


def _is_path_open(call: ast.Call) -> bool:
    """``<expr>.open(...)`` shaped like ``Path.open``: a mode string first (or ``mode=``), or only
    keywords (``encoding=``) and no positional argument. ``Image.open(src)``, ``RoundStore.open(
    path)`` and ``opener.open(req)`` pass a non-mode first argument and are not file opens."""
    if call.args:
        a = call.args[0]
        return isinstance(a, ast.Constant) and isinstance(a.value, str) and bool(_MODE.match(a.value))
    return all(k.arg is not None for k in call.keywords)


def _kind(call: ast.Call, funcs: set[str], mods: set[str]) -> str | None:
    f = call.func
    if isinstance(f, ast.Name) and f.id in funcs:
        return "open"
    if not isinstance(f, ast.Attribute):
        return None
    if isinstance(f.value, ast.Name):
        v = f.value.id
        if f.attr == "open" and v in mods:
            return f"{v}.open"
        if v == "os" and f.attr == "fdopen":
            return "os.fdopen"
        if v == "zipfile" and f.attr == "ZipFile":
            return "ZipFile"
    if f.attr == "open" and _is_path_open(call):
        return "path.open"
    return None


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


def _with_name(scope: ast.AST, name: str) -> bool:
    for n in ast.walk(scope):
        if isinstance(n, ast.withitem):
            e = n.context_expr
            if isinstance(e, ast.Name) and e.id == name:
                return True
    return False


def _closed_in_finally(scope: ast.AST, name: str) -> bool:
    for n in ast.walk(scope):
        if isinstance(n, ast.Try):
            for stmt in n.finalbody:
                for m in ast.walk(stmt):
                    f = getattr(m, "func", None)
                    if (isinstance(m, ast.Call) and isinstance(f, ast.Attribute)
                            and f.attr == "close" and isinstance(f.value, ast.Name)
                            and f.value.id == name):
                        return True
    return False


def _facts(source: str) -> list[tuple[str, str, set[str]]]:
    """For each file open in ``source``: (kind, enclosing function name, safe shapes it follows)."""
    tree = ast.parse(source)
    funcs, mods = _open_aliases(tree)
    parents = _parents(tree)
    out: list[tuple[str, str, set[str]]] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        kind = _kind(n, funcs, mods)
        if kind is None:
            continue
        fn = _enclosing_function(n, parents)
        held: set[str] = set()
        if isinstance(parents.get(n), ast.withitem):
            held.add("WITH")
        else:
            name = _assigned_name(n, parents)
            if fn is not None and name is not None:
                if _with_name(fn, name):
                    held.add("WITH_NAME")
                if _closed_in_finally(fn, name):
                    held.add("FINALLY")
        out.append((kind, getattr(fn, "name", "<module>"), held))
    return out


def _tree_facts() -> dict[str, list[tuple[str, str, set[str]]]]:
    out: dict[str, list[tuple[str, str, set[str]]]] = {}
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
    assert "core/live_session_recorder.py" in files
    tree = _tree_facts()
    total = sum(len(v) for v in tree.values())
    assert total >= 100, total
    assert any("WITH" in held for rows in tree.values() for _, _, held in rows)


def test_the_measured_counts_hold():
    tree = _tree_facts()
    total = sum(len(v) for v in tree.values())
    not_with = sum(1 for v in tree.values() for _, _, held in v if "WITH" not in held)
    assert (total, not_with) == (_MEASURED_TOTAL, _MEASURED_NOT_WITH), (
        "a file open appeared or went: review how it is closed (WITH, WITH_NAME, FINALLY or a "
        "NAMED owner), then update the measured counts in the docstring and here")


def test_every_file_open_is_closed_on_every_path():
    unsafe = {}
    for rel, rows in _tree_facts().items():
        bad = [(kind, fn) for kind, fn, held in rows if not held and (rel, fn) not in _NAMED]
        if bad:
            unsafe[rel] = bad
    assert not unsafe, (
        "a file object whose close is skipped by an exception (not a with item, no `with name`, "
        "no name.close() in a finally, no NAMED owner); wrap it in a with block or close it in "
        f"a finally: {unsafe}")


def test_every_named_row_is_a_real_unsafe_site_with_a_reason():
    """A NAMED row must still be needed (the site holds no safe shape) and carry a reason."""
    tree = _tree_facts()
    for (rel, fn), why in _NAMED.items():
        assert why.strip(), (rel, fn)
        rows = [held for _, name, held in tree.get(rel, []) if name == fn]
        assert rows, f"{rel}:{fn} has no file open any more - drop the row"
        assert any(not held for held in rows), (
            f"{rel}:{fn} now holds a safe shape - drop the row")


def test_detector_classifies_each_shape():
    w = "def f(p):\n    with open(p) as fh:\n        return fh.read()\n"
    assert _facts(w) == [("open", "f", {"WITH"})]
    wn = "def f(p):\n    fh = open(p, 'rb')\n    with fh:\n        return fh.read()\n"
    assert _facts(wn) == [("open", "f", {"WITH_NAME"})]
    fin = ("import gzip\ndef f(p):\n    fh = gzip.open(p)\n    try:\n        return fh.read()\n"
           "    finally:\n        fh.close()\n")
    assert _facts(fin) == [("gzip.open", "f", {"FINALLY"})]
    pa = "def f(p):\n    with p.open('rb') as fh:\n        return fh.read()\n"
    assert _facts(pa) == [("path.open", "f", {"WITH"})]
    z = "import zipfile\ndef f(b):\n    zf = zipfile.ZipFile(b)\n    with zf:\n        pass\n"
    assert _facts(z) == [("ZipFile", "f", {"WITH_NAME"})]
    fd = "import os\ndef f(fd):\n    with os.fdopen(fd) as fh:\n        pass\n"
    assert _facts(fd) == [("os.fdopen", "f", {"WITH"})]


def test_detector_flags_a_straight_line_close_as_unsafe():
    """Positive control: a close after a read, outside any finally, holds NO safe shape."""
    leak = "def f(p):\n    fh = open(p)\n    data = fh.read()\n    fh.close()\n    return data\n"
    assert _facts(leak) == [("open", "f", set())]
    # a bare open() whose result is consumed in place holds no shape either
    chained = "def f(p):\n    return open(p).read()\n"
    assert _facts(chained) == [("open", "f", set())]
    # a close of a DIFFERENT name in a finally does not cover this handle
    other = ("def f(p, q):\n    fh = open(p)\n    try:\n        pass\n    finally:\n"
             "        q.close()\n")
    assert _facts(other) == [("open", "f", set())]
    # a with on a DIFFERENT name does not cover it
    wrong = "def f(p, q):\n    fh = open(p)\n    with q:\n        pass\n"
    assert _facts(wrong) == [("open", "f", set())]
    # another library's open is not a file open
    # (a one-letter filename that looks like a mode is the stated limit of the mode test)
    assert _facts("from PIL import Image\nImage.open('a.png')\nimport webbrowser\nwebbrowser.open('http://u')\n") == []

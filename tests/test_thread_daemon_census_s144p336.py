"""S144-P-336 - every thread RC starts in production code says whether it is a daemon, held at zero.

A ``threading.Thread`` or ``threading.Timer`` that is not a daemon keeps the interpreter alive after ``main`` returns.
RC's background processes run under ``pythonw.exe`` with no console, so a non-daemon worker left in a sleep loop is a
process that never exits and a supervisor restart that finds the old pid still holding the port. Measured 2026-11-07
over every tracked production ``.py``: 57 files start threads, and every one of them already sets ``daemon`` (a
``daemon=`` keyword, or a ``<name>.daemon = ...`` assignment in the same scope; the three assignment forms are
``agents/daemon_slayer/server.py`` ``process_request`` (from ``self.daemon_threads``), ``core/live_item_tape_store.py`` and
``lib/rewind_live_writer.py``). ``ThreadPoolExecutor`` workers are out of scope (the interpreter joins them at exit). The four
``Thread`` subclasses (the ``_RequestThread`` helpers) each mention ``daemon`` in their body. This pins that: a new
thread that leaves the choice to the default (non-daemon) fails here.

Detector (AST over every tracked ``.py`` outside ``tests/``, ``docs/`` and the vendored ``ops/fleet_kit/``; a call in a
string, comment or docstring never counts):
- a call ``Thread(...)`` / ``Timer(...)`` (bare or ``<module>.``-qualified) is clean when it passes ``daemon=``, or is the
  value of an assignment whose target gets ``.daemon = ...`` / ``.setDaemon(...)`` anywhere in the enclosing function (or
  module body for a module-level thread);
- a ``class X(Thread)`` is clean when ``daemon`` appears as an attribute, keyword or name anywhere in the class body.

The baseline is empty. A thread that must be non-daemon (it owns a flush the process must wait for) passes
``daemon=False`` explicitly, which is clean: the rule is that the choice is written down, not what it is.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_SKIP_PREFIXES = ("tests/", "docs/", "ops/fleet_kit/")
_THREAD_CALLS = {"Thread", "Timer"}


def _call_name(call: ast.Call) -> str | None:
    fn = call.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return None


def _scope_of(node: ast.AST, parents: dict[ast.AST, ast.AST], tree: ast.AST) -> ast.AST:
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur
        cur = parents.get(cur)
    return tree


def _sets_daemon_on(scope: ast.AST, target_src: str) -> bool:
    for n in ast.walk(scope):
        if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in targets:
                if (isinstance(t, ast.Attribute) and t.attr == "daemon"
                        and ast.unparse(t.value) == target_src):
                    return True
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "setDaemon" and ast.unparse(n.func.value) == target_src):
            return True
    return False


def _mentions_daemon(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and n.attr == "daemon":
            return True
        if isinstance(n, ast.keyword) and n.arg == "daemon":
            return True
        if isinstance(n, ast.Name) and n.id == "daemon":
            return True
    return False


def _scan(source: str) -> list[tuple[int, str]]:
    """``(lineno, description)`` for each thread whose daemon choice is not written down."""
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = {b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "") for b in node.bases}
            if "Thread" in bases and not _mentions_daemon(node):
                out.append((node.lineno, f"class {node.name}(Thread)"))
        elif isinstance(node, ast.Call) and _call_name(node) in _THREAD_CALLS:
            if any(k.arg == "daemon" for k in node.keywords):
                continue
            parent = parents.get(node)
            if isinstance(parent, (ast.Assign, ast.AnnAssign)):
                targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
                scope = _scope_of(node, parents, tree)
                if any(_sets_daemon_on(scope, ast.unparse(t)) for t in targets):
                    continue
            out.append((node.lineno, f"{_call_name(node)}(...)"))
    return out


def test_every_production_thread_states_its_daemon_flag():
    files = [p for p in repo_files(REPO_ROOT, ("*.py",))
             if not relative_posix(p).startswith(_SKIP_PREFIXES) and "/tests/" not in relative_posix(p)]
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    hits: list[str] = []
    seen = 0
    starts = 0
    for p in files:
        try:
            src = p.read_text(encoding="utf-8")
            found = _scan(src)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        seen += 1
        starts += src.count("Thread(") + src.count("Timer(")
        hits.extend(f"{relative_posix(p)}:{n} {what}" for n, what in found)
    assert seen > 100, "the parse walk returned almost nothing"
    assert starts > 20, "the walk saw almost no thread start, so an empty hit list proves nothing"
    assert not hits, f"thread with no daemon= / .daemon assignment (write the choice down): {hits}"


def test_the_detector_flags_each_unset_shape():
    cases = {
        "import threading\nthreading.Thread(target=f).start()\n": [(2, "Thread(...)")],
        "from threading import Thread\nt = Thread(target=f)\nt.start()\n": [(2, "Thread(...)")],
        "import threading\nt = threading.Timer(1, f)\nt.start()\n": [(2, "Timer(...)")],
        "import threading\nclass W(threading.Thread):\n    def run(self):\n        pass\n": [(2, "class W(Thread)")],
        # a different object's flag does not clear this thread
        "import threading\nt = threading.Thread(target=f)\nu.daemon = True\n": [(2, "Thread(...)")],
        # an assignment in another function does not clear this scope
        "import threading\n"
        "def a():\n    t = threading.Thread(target=f)\n    t.start()\n"
        "def b():\n    t.daemon = True\n": [(3, "Thread(...)")],
    }
    for src, want in cases.items():
        assert _scan(src) == want, src


def test_the_detector_accepts_each_written_down_shape():
    clean = (
        "import threading\n"
        "threading.Thread(target=f, daemon=True).start()\n"
        "threading.Thread(target=f, daemon=False).start()\n"
        "t = threading.Thread(target=f)\nt.daemon = True\nt.start()\n"
        "u = threading.Timer(1, f)\nu.setDaemon(True)\n"
        "class S:\n    def go(self):\n        self.t = threading.Thread(target=f)\n        self.t.daemon = self.flag\n"
        "class W(threading.Thread):\n    def __init__(self):\n        super().__init__(daemon=True)\n"
        "doc = 'threading.Thread(target=f)'\n"
        "# threading.Thread(target=f)\n"
    )
    assert _scan(clean) == []

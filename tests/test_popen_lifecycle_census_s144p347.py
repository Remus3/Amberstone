"""S144-P-347 - every direct production ``subprocess.Popen`` call is a named row with a checked lifecycle.

S144-P-334 pins that each spawn passes ``creationflags``; S144-P-302 pins a ``timeout=`` on
the blocking calls (``run`` / ``check_output``). Neither says what happens to a ``Popen``
HANDLE, the one spawn shape that outlives its call: a pipe nobody drains stalls the child on a
full buffer, and a child nobody waits for or kills is a leaked handle (and a zombie off
Windows). This census enumerates every ``Popen`` in the tracked non-test ``.py`` and requires
a named row declaring which of five lifecycles it follows, then CHECKS the declaration
against the enclosing function's AST:

- WAITED: the enclosing function calls ``.wait(`` or ``.communicate(`` (bounded reap).
- TERMINATED: the enclosing function calls ``.terminate(`` or ``.kill(`` (stop, no reap: the
  caller is a short-lived CLI that exits next).
- DETACHED: fire-and-forget by design; none of stdin / stdout / stderr is ``PIPE`` (a piped
  stream with no reader is the hang), so the child can only outlive the caller harmlessly.
- OWNED: the handle is stored on an attribute (``self.proc = Popen(...)``) for another method
  to stop.
- A row may name two classes; every named class must hold.

Measured 2026-11-07 over the git index (alias-aware AST): 13 ``Popen`` calls in 13 production
files, plus ONE bare reference to ``subprocess.Popen`` that is not a call
(ops/launcher/service_host.py binds it as an injected default constructor and calls it through
``self._popen``; PKG-owned, so only pinned here as a reference count, its lifecycle is the
launcher's own tests'). ``ops/fleet_kit/`` (vendored, byte-pinned, never edited here), ``tests/`` and
``agents/agent3_testing/suite/`` (test code) and ``docs/_archive/`` are out of scope; two
docstring mentions (moon_vision_server.py, tools/inbox_responder_procs.py) are prose, not
calls, and are not seen. Stated limits: a DIRECT call through the module, an import alias or
``from subprocess import Popen`` only; a reference passed or stored and called later is counted
(``_REFERENCES``) but its lifecycle is not read; ``asyncio.create_subprocess_*`` and
``os.spawn*`` are not covered (none in non-test code, probed 2026-11-07); whether the OTHER
method that owns an OWNED handle actually stops it is not proven (named in the row reason).
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "agents/agent3_testing/suite/", "docs/_archive/")

# file -> (classes, reason). One Popen per file at this measurement; the count is pinned too.
_ROWS: dict[str, tuple[tuple[str, ...], str]] = {
    "coaches/voice_coach.py": (
        ("DETACHED",), "SAPI speech via a hidden powershell; all three streams DEVNULL, self-exits"),
    "core/daemon_slayer_client.py": (
        ("DETACHED",), "DS launcher relaunch; returns the pid, DsWatchdog tracks the port, not the handle"),
    "dashboard/_vision_watchdog.py": (
        ("DETACHED",), "vision server respawn; returns the pid, the watchdog probes :8889"),
    "ops/loop/lane_launcher.py": (
        ("DETACHED",), "lane runner (hidden powershell) outlives the launcher; _spawn returns the handle, all streams DEVNULL"),
    "ops/rc_dev_runtime.py": (
        ("WAITED",), "FROZEN; short liveness window via proc.wait(timeout=verify_alive_s), then fire-and-forget"),
    "ops/rc_supervisor.py": (
        ("OWNED",), "FROZEN; self.process is the supervised app, stopped by the supervisor's restart path"),
    "tools/console_flash_control.py": (
        ("WAITED",), "positive-control spawns, each proc.wait(timeout=30)"),
    "tools/credential_history_scan.py": (
        ("WAITED", "TERMINATED"), "cat-file --batch stream; finally kills a live child then waits"),
    "tools/dev_cli.py": (
        ("DETACHED",), "start.bat launch: the CLI returns immediately, nothing piped"),
    "tools/inbox_responder_procs.py": (
        ("WAITED",), "communicate(timeout), kill tree on timeout; piped streams drained by communicate"),
    "tools/perseus_recall.py": (
        ("TERMINATED",), "one-shot MCP stdio client; finally closes stdin and terminates, the CLI exits next"),
    "tools/perseus_sync.py": (
        ("OWNED",), "Vault.proc is a long-lived MCP stdio server; Vault.close() closes stdin and terminates"),
    "tools/run_packaged_smoke.py": (
        ("WAITED", "TERMINATED"), "PKG-owned smoke harness; waits for the host exit, kills on overrun"),
}

_SPAWN_ROW_COUNT = 13

# file -> number of bare ``subprocess.Popen`` references that are not a direct call (an injected
# constructor). Counted, not lifecycle-checked. Measured 2026-11-07.
_REFERENCES = {"ops/launcher/service_host.py": 1}


def _aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    mods: set[str] = set()
    funcs: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods.update((a.asname or a.name) for a in n.names if a.name == "subprocess")
        elif isinstance(n, ast.ImportFrom) and n.module == "subprocess":
            funcs.update((a.asname or a.name) for a in n.names if a.name == "Popen")
    return mods, funcs


def _is_popen(call: ast.Call, mods: set[str], funcs: set[str]) -> bool:
    f = call.func
    return (isinstance(f, ast.Attribute) and f.attr == "Popen"
            and isinstance(f.value, ast.Name) and f.value.id in mods) or (
        isinstance(f, ast.Name) and f.id in funcs)


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST | None:
    cur = parents.get(node)
    while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
        cur = parents.get(cur)
    return cur


def _method_calls(scope: ast.AST) -> set[str]:
    return {n.func.attr for n in ast.walk(scope)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


def _pipes_a_stream(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg in ("stdin", "stdout", "stderr"):
            v = kw.value
            if (isinstance(v, ast.Attribute) and v.attr == "PIPE") or (
                    isinstance(v, ast.Name) and v.id == "PIPE"):
                return True
    return False


def _stored_on_attribute(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> bool:
    p = parents.get(call)
    return isinstance(p, ast.Assign) and any(isinstance(t, ast.Attribute) for t in p.targets)


def _facts(source: str) -> list[set[str]]:
    """For each Popen call in ``source``: the lifecycle classes its code satisfies."""
    tree = ast.parse(source)
    mods, funcs = _aliases(tree)
    parents = _parents(tree)
    out: list[set[str]] = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and _is_popen(n, mods, funcs)):
            continue
        fn = _enclosing_function(n, parents)
        calls = _method_calls(fn) if fn is not None else set()
        held: set[str] = set()
        if calls & {"wait", "communicate"}:
            held.add("WAITED")
        if calls & {"terminate", "kill"}:
            held.add("TERMINATED")
        if not _pipes_a_stream(n):
            held.add("DETACHED")
        if _stored_on_attribute(n, parents):
            held.add("OWNED")
        out.append(held)
    return out


def _in_annotation(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """True when ``node`` sits inside a type annotation (a name, not a spawn)."""
    child, cur = node, parents.get(node)
    while cur is not None:
        if isinstance(cur, ast.AnnAssign) and cur.annotation is child:
            return True
        if isinstance(cur, ast.arg) and cur.annotation is child:
            return True
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)) and cur.returns is child:
            return True
        child, cur = cur, parents.get(cur)
    return False


def _bare_references(source: str) -> int:
    """``subprocess.Popen`` / imported ``Popen`` named but not called directly."""
    tree = ast.parse(source)
    mods, funcs = _aliases(tree)
    parents = _parents(tree)
    count = 0
    for n in ast.walk(tree):
        named = (isinstance(n, ast.Attribute) and n.attr == "Popen"
                 and isinstance(n.value, ast.Name) and n.value.id in mods) or (
            isinstance(n, ast.Name) and n.id in funcs and isinstance(n.ctx, ast.Load))
        if not named:
            continue
        p = parents.get(n)
        if isinstance(p, ast.Call) and p.func is n:
            continue
        if isinstance(p, ast.ImportFrom) or _in_annotation(n, parents):
            continue
        count += 1
    return count


def _tree_references() -> dict[str, int]:
    out: dict[str, int] = {}
    for p in repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(p)
        if rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel:
            continue
        try:
            n = _bare_references(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        if n:
            out[rel] = n
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
    assert "core/polled_json.py" in files
    assert "tools/perseus_recall.py" in files
    assert len(_tree_facts()) >= 5


def test_every_popen_is_a_named_row():
    tree = _tree_facts()
    unnamed = sorted(f for f in tree if f not in _ROWS)
    assert not unnamed, (
        "a new subprocess.Popen: add a _ROWS entry naming its lifecycle (WAITED / TERMINATED / "
        f"DETACHED / OWNED) and why: {unnamed}")
    stale = sorted(f for f in _ROWS if f not in tree)
    assert not stale, f"no longer spawn a Popen - drop from _ROWS: {stale}"
    assert len(_ROWS) == _SPAWN_ROW_COUNT
    grown = {f: len(v) for f, v in tree.items() if len(v) != 1}
    assert not grown, f"one Popen per row is pinned; a second needs its own row shape: {grown}"


def test_each_declared_lifecycle_holds_in_the_code():
    tree = _tree_facts()
    broken = {}
    for rel, (classes, _reason) in _ROWS.items():
        held = tree[rel][0]
        missing = [c for c in classes if c not in held]
        if missing:
            broken[rel] = missing
    assert not broken, (
        "a declared Popen lifecycle no longer holds (a piped detached child with no reader, a "
        f"wait that was removed, a handle no longer stored): {broken}")


def test_bare_popen_references_are_pinned():
    """An injected / stored ``subprocess.Popen`` is a spawn the call census cannot read."""
    assert _tree_references() == _REFERENCES, (
        "a subprocess.Popen reference that is not a direct call appeared or went: its lifecycle "
        "is unread by this census - review it, then update _REFERENCES")


def test_rows_are_well_formed_and_reasoned():
    known = {"WAITED", "TERMINATED", "DETACHED", "OWNED"}
    for rel, (classes, reason) in _ROWS.items():
        assert classes and set(classes) <= known, rel
        assert len(reason) >= 25, rel
        assert reason.isascii(), rel
        assert (REPO_ROOT / rel).is_file(), rel


def test_detector_classifies_each_shape():
    waited = "import subprocess\ndef f():\n    p = subprocess.Popen(['x'])\n    p.wait(timeout=3)\n"
    assert {"WAITED", "DETACHED"} <= _facts(waited)[0]
    comm = ("import subprocess as sp\ndef f():\n"
            "    p = sp.Popen(['x'], stdout=sp.PIPE)\n    return p.communicate()\n")
    held = _facts(comm)[0]
    assert "WAITED" in held and "DETACHED" not in held
    killed = ("from subprocess import Popen\ndef f():\n"
              "    p = Popen(['x'], stdin=-1)\n    p.kill()\n")
    assert "TERMINATED" in _facts(killed)[0]
    owned = ("import subprocess\nclass C:\n    def go(self):\n"
             "        self.p = subprocess.Popen(['x'], stderr=subprocess.PIPE)\n")
    held = _facts(owned)[0]
    assert "OWNED" in held and "DETACHED" not in held


def test_detector_flags_a_handle_with_no_lifecycle_at_all():
    """Positive control: a piped, never-waited, never-stopped local handle holds NO class."""
    leak = ("import subprocess\ndef f():\n"
            "    p = subprocess.Popen(['x'], stdout=subprocess.PIPE)\n    return p.pid\n")
    assert _facts(leak) == [set()]
    # a different module's Popen, and a non-call mention, are not spawns
    assert _facts("import os\nos.Popen(['x'])\n") == []
    assert _facts("import subprocess\nx = subprocess.Popen\n") == []

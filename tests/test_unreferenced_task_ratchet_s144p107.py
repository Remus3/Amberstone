"""RM-1407 - a fire-and-forget asyncio task keeps a strong reference, and a ratchet holds it.

The asyncio docs warn that the event loop keeps only a WEAK reference to a task:
a task nobody else holds can be garbage-collected mid-run, and a long-lived
loop silently stops. Measured 2026-11-04 with ``ruff check --select RUF006`` and
an AST scan of every tracked .py: exactly four statements in the tree called
``asyncio.create_task(...)`` and dropped the result, all in
``Supervisor.start()`` (agents/supervisor.py): the heartbeat, dispatch,
warm-UI-watchdog and task-queue-reconciler loops, i.e. the loops that keep the
lock sentinel fresh and drain the task queue. Nothing else in the tree dropped a
task: every other site assigns it.

``Supervisor.start()`` now appends each loop to ``self._bg_tasks``. This ratchet
bans a bare ``create_task`` / ``ensure_future`` expression statement anywhere in
the tracked tree, so the next one fails at the line.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_SPAWNERS = ("create_task", "ensure_future")


def _bare_spawns(tree: ast.AST) -> list[int]:
    """Line numbers of expression statements that spawn a task and drop it."""
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in _SPAWNERS:
            hits.append(node.lineno)
    return hits


def test_no_tracked_module_drops_a_spawned_task():
    scanned = 0
    offenders = []
    for path in repo_files(REPO_ROOT, ("*.py",)):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        scanned += 1
        offenders += [f"{relative_posix(path)}:{line}" for line in _bare_spawns(tree)]
    assert scanned > 500, "the walk reached too few modules to mean anything"
    assert offenders == [], (
        "a task nobody references can be garbage-collected mid-run; assign it "
        "(self._bg_tasks.append(...)):\n  " + "\n  ".join(offenders))


def test_the_detector_sees_a_bare_spawn():
    """Positive control: the scan is not vacuous."""
    src = (
        "import asyncio\n"
        "async def f():\n"
        "    asyncio.create_task(g())\n"
        "    t = asyncio.create_task(g())\n"
        "    asyncio.ensure_future(g())\n"
        "    self._bg.append(asyncio.create_task(g()))\n"
    )
    assert _bare_spawns(ast.parse(src)) == [3, 5]


def test_supervisor_holds_its_background_loops():
    """The four loops land in self._bg_tasks, initialised in __init__."""
    text = (REPO_ROOT / "agents" / "supervisor.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    sup = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Supervisor")
    init = next(n for n in sup.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    start = next(n for n in sup.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "start")
    assigned = {
        t.attr for n in ast.walk(init) if isinstance(n, (ast.AnnAssign, ast.Assign))
        for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
        if isinstance(t, ast.Attribute)
    }
    assert "_bg_tasks" in assigned
    held = set()
    for node in ast.walk(start):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_task"):
            for arg in node.args:
                if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
                    held.add(arg.func.attr)
    assert {"_heartbeat_loop", "_dispatch_loop", "_warm_ui_watchdog",
            "_task_queue_reconciler_loop"} <= held
    assert "_bg_tasks" in ast.unparse(start)

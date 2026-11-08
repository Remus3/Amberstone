"""S144-P-437 - every production blocking wait with no timeout is a named, reasoned row.

``Thread.join()``, ``Future.result()``, a synchronous ``Event.wait()`` / ``Condition.wait()`` and a ``Queue.get()`` with
no timeout block their thread for as long as the other side takes: a hung child, a wedged worker or a lost wake-up
parks the caller for the rest of the process. The existing censuses cover the neighbours (S144-P-301 network
timeouts, S144-P-302 subprocess timeouts, S144-P-351 lock acquires, S144-P-357 sleeps under a lock) but not these.

Measured 2026-11-08 over every tracked production ``.py`` (AST; a call in a string, comment or docstring never counts):
15 sites in 13 files, every one a named row in ``_ROWS`` below with the reason it cannot strand a request or the loop:
the daemon worker loops that park on their own queue or condition by design (``tft/rounds/store.py``,
``core/death_recap.py``, ``core/live_session_recorder.py``, ``vision_server/_pool.py``, ``core/focus_board_live.py``), the
foreground hotkey listener whose whole job is to block, and the ``Future.result()`` calls whose task is bounded by its
own timeouts or already complete.

Detector, a call is a site when it is none of: awaited, a ``wait`` passed to another call (``asyncio.wait_for(ev.wait(), t)``
hands a coroutine over, it does not block), or given any argument or ``timeout=`` keyword. Kinds: ``join`` (no arguments, so never ``str.join``), ``result``, ``wait``
(not awaited), and ``get`` only when the receiver's last name ends in ``q`` or ``queue`` (so ``cache.get()`` is ignored).
The row key is ``(file, kind, receiver source)``; the set is exact, so a site that goes away must be dropped.

Out of scope: ``tests/`` and ``*/tests/``, the vendored ``ops/fleet_kit/`` and the ``agents/agent3_testing/suite/`` test
harness (its two ``communicate()`` calls). Named blind spots: a wait reached through an alias or ``getattr``, and
``asyncio`` waits (an awaited wait is cancellable, which is why it is skipped).
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_SKIP_PREFIXES = ("tests/", "docs/", "ops/fleet_kit/", "agents/agent3_testing/suite/")

_ROWS = {
    ("core/death_recap.py", "get", "_queue"):
        "daemon worker loop: parks on its own queue between kill events by design",
    ("core/live_session_recorder.py", "get", "self._q"):
        "daemon recorder thread: parks on its own queue between samples by design",
    ("vision_server/_pool.py", "get", "self._queue"):
        "daemon pool worker: parks on its own queue between jobs by design",
    ("tft/rounds/store.py", "get", "self._q"):
        "daemon writer thread: parks on its own queue; a _STOP item ends it",
    ("tft/rounds/store.py", "wait", "self._run_gate"):
        "daemon writer thread: the gate is a pause switch the owner sets again on resume",
    ("core/focus_board_live.py", "wait", "_WORKER_COND"):
        "daemon worker: waits inside a with-block for a queued roster job or stop, the standard Condition loop",
    ("core/focus_board_live.py", "join", "thread"):
        "wait=True caller joins the daemon warm thread it just saw alive; the warm thread is the engine load itself",
    ("tools/keybind_listener.py", "wait", "keyboard"):
        "foreground hotkey listener: blocking until Ctrl+C is the program",
    ("dashboard/_state_builder.py", "result", "_lc_future"):
        "the liveclient round-trip has its own socket timeout; any failure falls back inline",
    ("core/vision_tesseract.py", "result", "fut"):
        "as_completed loop: the future is already done",
    ("tools/ddragon_mirror_refresh.py", "result", "fut"):
        "as_completed loop: the future is already done",
    ("ops/loop/repo_review.py", "result", "fut"):
        "as_completed loop: the future is already done",
    ("tft/cv/ocr_fields.py", "result", "fut"):
        "each OCR task is a tesseract call with its own timeout, inside a with-scoped pool",
    ("core/lcu_events.py", "result", "read"):
        "an asyncio future read only after asyncio.wait reported it done",
    ("ops/loop/drain_waves_2_3.py", "result", "fut"):
        "each slice is a kit spawn with its own run timeout, inside a with-scoped pool",
}


def _last_name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    return getattr(node, "id", "")


def _scan(source: str) -> list[tuple[int, str, str]]:
    """``(lineno, kind, receiver source)`` per unbounded blocking wait."""
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    out: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        kind = node.func.attr
        if kind not in {"join", "result", "wait", "get"} or node.args or node.keywords:
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Await) or (kind == "wait" and isinstance(parent, ast.Call)):
            continue
        recv = node.func.value
        if kind == "get" and not _last_name(recv).lower().endswith(("q", "queue")):
            continue
        out.append((node.lineno, kind, ast.unparse(recv)))
    return sorted(out)


def _production_files():
    return [p for p in repo_files(REPO_ROOT, ("*.py",))
            if not relative_posix(p).startswith(_SKIP_PREFIXES) and "/tests/" not in relative_posix(p)]


def test_every_unbounded_blocking_wait_is_a_named_row():
    files = _production_files()
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    found: dict[tuple[str, str, str], int] = {}
    for p in files:
        rel = relative_posix(p)
        try:
            sites = _scan(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for _lineno, kind, recv in sites:
            found[(rel, kind, recv)] = found.get((rel, kind, recv), 0) + 1
    assert len(found) >= 10, "the walk saw almost no wait, so an empty list proves nothing"
    new = sorted(set(found) - set(_ROWS))
    assert not new, (
        f"unbounded blocking wait with no timeout (pass timeout=, or name the row and its reason here): {new}")
    stale = sorted(set(_ROWS) - set(found))
    assert not stale, f"stale _ROWS entry (the wait is gone, drop it): {stale}"
    assert all(_ROWS.values()), "every row carries a reason"


def test_the_detector_flags_each_unbounded_shape():
    cases = {
        "t.join()\n": [(1, "join", "t")],
        "def f():\n    return self.fut.result()\n": [(2, "result", "self.fut")],
        "ev.wait()\n": [(1, "wait", "ev")],
        "item = self._q.get()\n": [(1, "get", "self._q")],
        "item = jobs_queue.get()\n": [(1, "get", "jobs_queue")],
        "import subprocess\nparts = x\n_cond.wait()\n": [(3, "wait", "_cond")],
    }
    for src, want in cases.items():
        assert _scan(src) == want, src


def test_the_detector_ignores_bounded_awaited_and_unrelated_shapes():
    clean = (
        "t.join(5)\n"
        "t.join(timeout=5)\n"
        "fut.result(timeout=1)\n"
        "ev.wait(0.5)\n"
        "q.get(timeout=1)\n"
        "q.get_nowait()\n"
        "''.join(parts)\n"
        "cache.get()\n"
        "async def f():\n"
        "    await ev.wait()\n"
        "    await asyncio.wait_for(ev.wait(), timeout=2)\n"
        "    f = asyncio.ensure_future(ev.wait())\n"
    )
    assert _scan(clean) == []

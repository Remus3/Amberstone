"""S144-P-357 - no production code sleeps while it holds a lock, except one named throttle.

A ``time.sleep`` inside ``with <lock>:`` keeps every other thread that wants the lock waiting for the
whole sleep. In RC that is a coach thread, a dashboard request thread or the supervisor tick stuck behind
a retry back-off. This census reads every tracked non-test ``.py`` and finds each ``time.sleep(...)`` /
``sleep(...)`` call that sits lexically inside a ``with`` whose item text names a lock (``lock``,
``mutex`` or ``sem`` in the unparsed expression, case-insensitive). A call counts as a sleep when its
last dotted name part, lower-cased, ends in ``sleep`` (``time.sleep``, ``sleep``, and a module-level alias
such as ``_sleep = time.sleep``) and the call is not ``asyncio.sleep`` (that one yields).

A def or lambda nested inside the ``with`` is NOT descended into: its body runs later, on whatever thread
calls it, not while the ``with`` holds the lock (``dashboard/routes_last_match.py`` ``_ensure_retry_thread``
defines its drain loop inside ``with _INGEST_RETRY_THREAD_LOCK`` and starts it as a daemon thread; the
sleep there is the thread's own tick, not a held-lock sleep).

Measured 2026-11-08 over the git index: about 730 lock ``with`` blocks, TWO real sites, each a named row in
``_ROWS`` with a kind check on the source rather than on the reason text:
- ``lib/http/client.py`` ``_rate_gate``: ``rate_lock`` is the per-host throttle itself - the lock exists to
  make concurrent callers queue behind the previous call's minimum interval - and it is SEPARATE from the
  breaker lock (``st.lock``), so a sleeping caller never blocks a breaker read or write. Checked: the sleep
  argument is derived from ``MIN_INTERVAL_SEC``, ``rate_lock`` is taken by exactly one ``with``, and no
  sleep runs under ``st.lock``.
- ``ops/loop/drain_waves_2_3.py`` ``_ensure_worktree``: ``_wt_lock`` serializes ``git worktree add`` and
  the back-off retry on a git lock error runs under it on purpose (a second thread must not hammer the
  same git lock). Checked: ``_wt_lock`` is taken by exactly one ``with`` (this function), the sleep is the
  module's ``_sleep`` alias of ``time.sleep``, and the retry loop is bounded by ``WT_ADD_TRIES``.

Stated limits: the lock test is on the NAME of the with item (a lock bound to a name without ``lock`` /
``mutex`` / ``sem`` in it is not seen); the sleep test is on the call name (an alias not ending in
``sleep`` is not seen); ``asyncio.sleep`` is out of scope (it yields); a sleep reached through a helper
called under the lock is not seen; ``.acquire()`` / ``.release()`` pairs are covered
by the S144-P-351 census for release only, not for what runs between them. ``ops/fleet_kit/`` (vendored,
byte-pinned), ``tests/``, ``agents/agent3_testing/suite/`` and ``docs/_archive/`` are out of scope.
"""
from __future__ import annotations

import ast

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "agents/agent3_testing/suite/", "docs/_archive/")
_LOCK_WORDS = ("lock", "mutex", "sem")

# (file, enclosing function) -> why the sleep under the lock is the design.
_ROWS = {
    ("lib/http/client.py", "_rate_gate"):
        "per-host rate_lock IS the throttle (callers queue behind the minimum interval); separate from "
        "the breaker lock",
    ("ops/loop/drain_waves_2_3.py", "_ensure_worktree"):
        "_wt_lock serializes git worktree add; the bounded git-lock back-off runs under it on purpose",
}


def _in_scope(rel: str) -> bool:
    return not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel


def _lockish(item: ast.withitem) -> bool:
    text = ast.unparse(item.context_expr).lower()
    return any(w in text for w in _LOCK_WORDS)


def _is_sleep(call: ast.Call) -> bool:
    name = ast.unparse(call.func)
    return name.lower().rsplit(".", 1)[-1].endswith("sleep") and name != "asyncio.sleep"


def _sleeps_held(with_node: ast.With | ast.AsyncWith) -> list[ast.Call]:
    """sleep calls in the with body that run while it holds the lock (nested defs/lambdas skipped)."""
    out: list[ast.Call] = []
    stack: list[ast.AST] = list(with_node.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Call) and _is_sleep(node):
            out.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return out


def sleep_under_lock(source: str) -> list[tuple[int, str]]:
    """(line, enclosing function) of every held-lock sleep in ``source``."""
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    found: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.With, ast.AsyncWith)) or not any(_lockish(i) for i in node.items):
            continue
        for call in _sleeps_held(node):
            cur: ast.AST | None = parents.get(call)
            fn = "<module>"
            while cur is not None:
                if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn = cur.name
                    break
                cur = parents.get(cur)
            found.add((call.lineno, fn))
    return sorted(found)


def _scan() -> tuple[dict[tuple[str, str], list[int]], int]:
    sites: dict[tuple[str, str], list[int]] = {}
    files = 0
    for path in repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(path)
        if not _in_scope(rel):
            continue
        files += 1
        for line, fn in sleep_under_lock(path.read_bytes().decode("utf-8")):
            sites.setdefault((rel, fn), []).append(line)
    return sites, files


@pytest.fixture(scope="module")
def scan():
    sites, files = _scan()
    # An empty walk must not pass: the scope reaches the tree this census exists for.
    assert files > 500, files
    return sites


def test_every_sleep_under_a_lock_is_a_named_row(scan):
    stray = sorted(f"{rel}:{lines} in {fn}" for (rel, fn), lines in scan.items() if (rel, fn) not in _ROWS)
    assert stray == [], (
        "a time.sleep inside a `with <lock>` blocks every other thread that wants the lock for the whole "
        "sleep - sleep outside the lock, or add a named row with its reason and a source check:\n  "
        + "\n  ".join(stray))


def test_no_row_is_stale(scan):
    stale = sorted(k for k in _ROWS if k not in scan)
    assert stale == [], f"named rows that no longer sleep under a lock - drop them: {stale}"


def test_rate_gate_row_matches_the_source():
    """The throttle row is held to its two facts on the source, not on the reason string."""
    src = (REPO_ROOT / "lib/http/client.py").read_bytes().decode("utf-8")
    tree = ast.parse(src)
    gate = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_rate_gate")
    sleeps = [c for c in ast.walk(gate) if isinstance(c, ast.Call) and ast.unparse(c.func) == "time.sleep"]
    assert len(sleeps) == 1
    arg = sleeps[0].args[0]
    assigned = [n for n in ast.walk(gate) if isinstance(n, ast.Assign)
                and ast.unparse(n.targets[0]) == ast.unparse(arg)]
    assert assigned and "MIN_INTERVAL_SEC" in ast.unparse(assigned[0].value), ast.unparse(arg)
    withs = [n for n in ast.walk(tree) if isinstance(n, ast.With)
             and any("rate_lock" in ast.unparse(i.context_expr) for i in n.items)]
    assert len(withs) == 1, "rate_lock must be taken by exactly one `with` (the throttle itself)"
    breaker = [n for n in ast.walk(tree) if isinstance(n, ast.With)
               and any(ast.unparse(i.context_expr) == "st.lock" for i in n.items)]
    assert breaker, "the breaker lock (st.lock) must stay a separate lock from rate_lock"
    assert not any(c for w in breaker for c in _sleeps_held(w)), "no sleep may run under the breaker lock"


def test_worktree_add_row_matches_the_source():
    """The back-off row is held to its facts on the source, not on the reason string."""
    tree = ast.parse((REPO_ROOT / "ops/loop/drain_waves_2_3.py").read_bytes().decode("utf-8"))
    withs = [n for n in ast.walk(tree) if isinstance(n, ast.With)
             and any("_wt_lock" in ast.unparse(i.context_expr) for i in n.items)]
    assert len(withs) == 1, "_wt_lock must be taken by exactly one `with` (the worktree add)"
    alias = [n for n in tree.body if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "_sleep"]
    assert alias and ast.unparse(alias[0].value) == "time.sleep"
    loops = [n for n in ast.walk(withs[0]) if isinstance(n, ast.For)]
    assert any("WT_ADD_TRIES" in ast.unparse(loop.iter) for loop in loops), "retry must stay bounded"


@pytest.mark.parametrize("snippet, expected", [
    ("import time\ndef f(lk):\n    with lk:\n        pass\n", 0),
    ("import time\ndef f(self):\n    with self._lock:\n        time.sleep(1)\n", 1),
    ("from time import sleep\ndef f(mutex):\n    with mutex:\n        sleep(2)\n", 1),
    ("import time\ndef f(self):\n    with self._lock:\n        pass\n    time.sleep(1)\n", 0),
    ("import time\ndef f(self):\n    with self._lock:\n        def g():\n            time.sleep(1)\n"
     "        return g\n", 0),
    ("import time\ndef f(self):\n    with open('x') as fh:\n        time.sleep(1)\n", 0),
    ("import time\ndef f(self):\n    with self._lock, open('x'):\n        for _ in range(2):\n"
     "            time.sleep(1)\n", 1),
    ("import time\n_sleep = time.sleep\ndef f(self):\n    with self._wt_lock:\n        _sleep(3)\n", 1),
    ("import time\ndef f(self):\n    with self._lock:\n        time.monotonic()\n", 0),
    ("import asyncio\nasync def f(self):\n    async with self._lock:\n        await asyncio.sleep(1)\n", 0),
])
def test_detector_positive_and_negative_controls(snippet, expected):
    assert len(sleep_under_lock(snippet)) == expected

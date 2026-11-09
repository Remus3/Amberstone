"""S144-P-363 - no production wait loop measures its own deadline on the wall clock, except two named rows.

``while time.time() < deadline`` ends early or runs long when the system clock steps (an NTP correction, a
manual change, a VM resume): a 12 s readiness poll can return at once, or a 120 s end-of-game wait can run
for hours. ``time.monotonic()`` cannot step, so an in-process timeout is measured on it. Wall time is right
only for a stamp that is stored, compared with a file mtime, or shown to someone; a ``while`` loop whose own
test calls ``time.time()`` is a timeout and not one of those.

This census reads every tracked non-test ``.py`` and finds each ``while`` whose test contains a
``time.time()`` call (``time.time() < deadline``, ``time.time() - start < seconds``,
``deadline > time.time()``). Measured 2026-11-08 over the git index: SIX sites. Four were converted to
``time.monotonic()`` in S144-P-363 (``lcu/lcu_postgame_collector.py`` ``_capture_after_trigger``,
``tools/gated_bench_swap_probe.py`` ``watch``, ``tools/overlay_legibility_preview.py`` and
``tools/pseudo_screen_overlay.py`` ``_wait_for_ready``). The other two, ``ops/loop/loop_controller.py``
``wait_for`` and ``wait_gone``, take a ``deadline_ts`` that ``ops/loop/executor.py`` builds, so the clock was
part of the seam's signature; S144-P-364 converted both ends together
(tests/test_loop_wait_deadline_monotonic_s144p364.py) and the census now has no named row.

Stated limits: only a ``while`` test is read (an ``if time.time() - t0 > limit`` after a blocking call is not
a wait loop and is out of scope); ``from time import time`` is not seen (the call is matched as the dotted
name ``time.time``); a deadline computed with ``time.time()`` outside the loop and compared inside it with
an unrelated name is still seen only through the in-test call. ``ops/fleet_kit/`` (vendored, byte-pinned),
``ops/launcher/`` (packaging, main-session owned), ``tests/``, ``agents/agent3_testing/suite/`` and
``docs/_archive/`` are out of scope.
"""
from __future__ import annotations

import ast

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "ops/launcher/", "agents/agent3_testing/suite/", "docs/_archive/")

# (file, enclosing function) -> why the wall-clock deadline is the design. Empty since S144-P-364 converted
# the two epoch-deadline rows (loop_controller wait_for / wait_gone and the executor that builds their deadline).
_ROWS: dict[tuple[str, str], str] = {}


def _in_scope(rel: str) -> bool:
    return not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel


def wallclock_wait_loops(source: str) -> list[tuple[int, str]]:
    """(line, enclosing function) of every ``while`` whose test calls ``time.time()``."""
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    found: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.While):
            continue
        if not any(isinstance(c, ast.Call) and ast.unparse(c.func) == "time.time" for c in ast.walk(node.test)):
            continue
        cur: ast.AST | None = parents.get(node)
        fn = "<module>"
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn = cur.name
                break
            cur = parents.get(cur)
        found.add((node.lineno, fn))
    return sorted(found)


def _scan() -> tuple[dict[tuple[str, str], list[int]], int]:
    sites: dict[tuple[str, str], list[int]] = {}
    files = 0
    for path in repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(path)
        if not _in_scope(rel):
            continue
        files += 1
        for line, fn in wallclock_wait_loops(path.read_bytes().decode("utf-8")):
            sites.setdefault((rel, fn), []).append(line)
    return sites, files


@pytest.fixture(scope="module")
def scan():
    sites, files = _scan()
    # An empty walk must not pass: the scope reaches the tree this census exists for.
    assert files > 500, files
    return sites


def test_every_wallclock_wait_loop_is_a_named_row(scan):
    stray = sorted(f"{rel}:{lines} in {fn}" for (rel, fn), lines in scan.items() if (rel, fn) not in _ROWS)
    assert stray == [], (
        "a while loop timed on time.time() ends early or runs long when the system clock steps - measure "
        "the deadline on time.monotonic(), or add a named row with its reason:\n  " + "\n  ".join(stray))


def test_no_row_is_stale(scan):
    stale = sorted(k for k in _ROWS if k not in scan)
    assert stale == [], f"named rows that no longer time a loop on time.time() - drop them: {stale}"


def test_the_loop_wait_seam_is_monotonic_at_both_ends():
    """S144-P-364: wait_for / wait_gone and the executor that builds their deadline share one clock."""
    tree = ast.parse((REPO_ROOT / "ops/loop/loop_controller.py").read_bytes().decode("utf-8"))
    for name in ("wait_for", "wait_gone"):
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        assert "deadline_ts" in [a.arg for a in fn.args.args], name
        assert "time.monotonic" in {ast.unparse(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call)}, name
    executor = (REPO_ROOT / "ops/loop/executor.py").read_bytes().decode("utf-8")
    assert 'deadline = time.monotonic() + self.cfg["cycle_deadline_sec"]' in executor
    assert "time.time()" not in executor


@pytest.mark.parametrize("snippet, expected", [
    ("import time\ndef f(d):\n    while time.time() < d:\n        pass\n", 1),
    ("import time\ndef f(s):\n    t0 = time.time()\n    while time.time() - t0 < s:\n        pass\n", 1),
    ("import time\ndef f(d):\n    while d > time.time():\n        pass\n", 1),
    ("import time\ndef f(d):\n    while time.monotonic() < d:\n        pass\n", 0),
    ("import time\ndef f(d):\n    while True:\n        stamp = time.time()\n        break\n", 0),
    ("import time\ndef f(d):\n    if time.time() > d:\n        pass\n", 0),
    ("import time\ndef f(d, ok):\n    while ok and time.time() < d:\n        pass\n", 1),
])
def test_detector_positive_and_negative_controls(snippet, expected):
    assert len(wallclock_wait_loops(snippet)) == expected

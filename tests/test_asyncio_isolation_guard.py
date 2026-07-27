"""RM-100 follow-up guard: exactly ONE off-main-thread coroutine runner.

Five near-identical local ``_run_coro`` / ``_run_poll_loop`` copies had
accreted as a workaround for the snapshot_panels ProactorEventLoop marker
(see tests/_asyncio_isolation.py for the root cause). They are consolidated
into that module. This file fails if a sixth copy is hand-rolled instead of
imported, and pins the behaviour the callers depend on.
"""
from __future__ import annotations

import ast
import asyncio
import threading
from pathlib import Path

import pytest

from tests._asyncio_isolation import run_coro, run_coro_capturing_thread

_TESTS_DIR = Path(__file__).resolve().parent
_BANNED_LOCAL_RUNNERS = {"_run_coro", "_run_poll_loop"}

# tests/_asyncio_isolation.py is the ONE place allowed to build a loop - it is
# the consolidation every other caller imports from.
_SANCTIONED_LOOP_MODULE = "_asyncio_isolation.py"

# asyncio.run() is the actual breakage mode under the snapshot_panels
# running-loop marker; new_event_loop/set_event_loop are the hand-rolled
# re-implementations of the sanctioned runner.
_BANNED_ASYNCIO_CALLS = {"run", "new_event_loop", "set_event_loop"}


# IsolatedAsyncioTestCase is the SAME breakage wearing a class statement.
# unittest drives its asyncSetUp through asyncio.Runner.run() on the MAIN
# thread, so it raises "Runner.run() cannot be called from a running event
# loop" under the snapshot_panels marker exactly as a bare asyncio.run() does.
_BANNED_ASYNC_BASES = {"IsolatedAsyncioTestCase"}


def _banned_async_test_bases(tree: ast.AST) -> list[tuple[int, str]]:
    """Locate classes deriving from IsolatedAsyncioTestCase.

    MEASURED 2026-07-27, and this is why the check exists: the call-based scan
    above walks ast.Call and therefore CANNOT see a base class. Seven tests in
    tests/preflip_mode/ inherited IsolatedAsyncioTestCase and failed with the
    identical RuntimeError the module docstring describes, while this guard
    reported green - it was blind to the most common way a unittest suite
    enters a loop on the main thread. The sibling test's docstring claimed it
    "catches the breakage itself, not by runner-function name"; it caught one
    spelling of it.

    Matches both `unittest.IsolatedAsyncioTestCase` (ast.Attribute) and a bare
    `IsolatedAsyncioTestCase` from `from unittest import ...` (ast.Name).
    Deliberately AST-based rather than a text grep, so the prose in a docstring
    explaining why NOT to use it does not flag itself.
    """
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            name = None
            if isinstance(base, ast.Attribute):
                name = base.attr
            elif isinstance(base, ast.Name):
                name = base.id
            if name in _BANNED_ASYNC_BASES:
                hits.append((node.lineno, f"class {node.name}({name})"))
    return hits


def _guarded_paths() -> list[Path]:
    """Every test module pytest imports, minus the sanctioned runner.

    Nested conftests are scanned too: tests/snapshot_panels/conftest.py is the
    fixture that arms the running-loop marker in the first place, so it is the
    likeliest place for a bare asyncio.run() to be added and the last place a
    root-only scan would catch it.
    """
    paths = list(_TESTS_DIR.rglob("test_*.py")) + list(_TESTS_DIR.rglob("conftest.py"))
    return sorted(p for p in paths if p.name != _SANCTIONED_LOOP_MODULE)


def _banned_loop_calls(tree: ast.AST) -> list[tuple[int, str]]:
    """Locate calls to the banned asyncio loop entry points.

    Only ast.Call nodes count. An attribute *assignment* on a Mock (for
    example ``_aio.get_event_loop.return_value.is_running.return_value = True``
    in test_silent_except_merge_hardening) is not a call and must not be
    flagged - it configures a double, it never touches a real loop.
    """
    module_aliases = set()
    direct_names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "asyncio":
                    module_aliases.add(alias.asname or "asyncio")
        elif isinstance(node, ast.ImportFrom) and node.module == "asyncio":
            for alias in node.names:
                if alias.name in _BANNED_ASYNCIO_CALLS:
                    direct_names[alias.asname or alias.name] = alias.name

    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _BANNED_ASYNCIO_CALLS
            and isinstance(func.value, ast.Name)
            and func.value.id in module_aliases
        ):
            hits.append((node.lineno, f"{func.value.id}.{func.attr}()"))
        elif isinstance(func, ast.Name) and func.id in direct_names:
            hits.append((node.lineno, f"{direct_names[func.id]}() (from asyncio import)"))
    return hits


def test_no_isolated_asyncio_testcase_under_tests():
    """The blind spot that let seven real failures through a green guard.

    tests/preflip_mode/{test_file_ingest_mirror,test_body_data_mode_no_flap}.py
    both derived IsolatedAsyncioTestCase. Alone they passed; in any run that
    also collected snapshot_panels - the nightly dual suite, or `-n 8` when one
    worker drew both files - all seven raised "Runner.run() cannot be called
    from a running event loop". Converted to plain TestCase driving the
    coroutines through run_coro, with assertions unchanged.
    """
    offenders = []
    for path in _guarded_paths():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for lineno, what in _banned_async_test_bases(tree):
            offenders.append(f"{path.relative_to(_TESTS_DIR)}:{lineno} {what}")
    assert not offenders, (
        "IsolatedAsyncioTestCase found under tests/ - it enters the event loop "
        "on the MAIN thread and dies under the snapshot_panels running-loop "
        "marker. Use a plain unittest.TestCase and drive the coroutine with "
        "run_coro from tests._asyncio_isolation:\n  " + "\n  ".join(offenders)
    )


def test_the_async_base_scan_actually_matches_both_spellings():
    """Negative control: a guard that matches nothing would pass forever.

    Pins that the scan really fires on both the qualified and the bare base,
    so a future 'fix' cannot be to quietly loosen it into never matching.
    """
    src = (
        "import unittest\n"
        "from unittest import IsolatedAsyncioTestCase\n"
        "class A(unittest.IsolatedAsyncioTestCase):\n    pass\n"
        "class B(IsolatedAsyncioTestCase):\n    pass\n"
        "class C(unittest.TestCase):\n    pass\n"
    )
    hits = _banned_async_test_bases(ast.parse(src))
    assert len(hits) == 2, hits
    assert {h[1] for h in hits} == {
        "class A(IsolatedAsyncioTestCase)",
        "class B(IsolatedAsyncioTestCase)",
    }


def test_the_async_base_scan_ignores_prose_mentions():
    """A docstring explaining why NOT to use it must not flag itself.

    This is the reason the check is AST-based and not a text grep - both
    converted files carry exactly such a docstring.
    """
    src = (
        'import unittest\n'
        'class D(unittest.TestCase):\n'
        '    """Plain TestCase, NOT IsolatedAsyncioTestCase - see the note."""\n'
        '    pass\n'
    )
    assert _banned_async_test_bases(ast.parse(src)) == []


def test_no_bare_asyncio_loop_entry_points_under_tests():
    """Pins the invariant behaviourally, not by runner-function name.

    Playwright's sync API leaves asyncio's running-loop marker set on the MAIN
    thread for the whole session (_sync_base.py calls _set_running_loop), so
    any asyncio.run() in tests/ that sorts after a snapshot_panels test raises
    "asyncio.run() cannot be called from a running event loop". Naming a
    hand-rolled runner something other than _run_coro dodges the name-based
    guard below; this one catches the breakage itself.
    """
    offenders = []
    for path in _guarded_paths():
        # utf-8-sig, not utf-8: a BOM-prefixed file on this Windows repo would
        # otherwise reach ast.parse as a stray U+FEFF and crash the guard with a
        # SyntaxError instead of reporting whatever it was meant to catch.
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for lineno, what in _banned_loop_calls(tree):
            offenders.append(f"{path.relative_to(_TESTS_DIR)}:{lineno} {what}")
    assert not offenders, (
        "bare asyncio loop entry points found under tests/ - use run_coro from "
        "tests._asyncio_isolation, which drives the coroutine on a fresh loop "
        "in a dedicated thread:\n  " + "\n  ".join(offenders)
    )


def test_no_local_coroutine_runner_copies_remain():
    """No test file re-defines a local off-thread coroutine runner.

    Import ``run_coro`` from tests._asyncio_isolation instead of hand-rolling
    a sixth copy.
    """
    offenders = []
    for path in sorted(_TESTS_DIR.rglob("test_*.py")):
        # utf-8-sig, not utf-8: a BOM-prefixed file on this Windows repo would
        # otherwise reach ast.parse as a stray U+FEFF and crash the guard with a
        # SyntaxError instead of reporting whatever it was meant to catch.
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            # An `async def _run_coro` is the same copy and slipped past a
            # FunctionDef-only check.
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in _BANNED_LOCAL_RUNNERS
            ):
                offenders.append(f"{path.relative_to(_TESTS_DIR)}:{node.lineno} {node.name}")
    assert not offenders, (
        "local coroutine-runner copies found - import run_coro from "
        "tests._asyncio_isolation instead:\n  " + "\n  ".join(offenders)
    )


def test_run_coro_returns_value_off_the_main_thread():
    main_ident = threading.get_ident()

    async def _work():
        return threading.get_ident()

    worker_ident = run_coro(_work())
    assert worker_ident != main_ident


def test_run_coro_reraises_worker_exception():
    """The isolation must not become a swallow - real failures still surface."""
    class _Boom(Exception):
        pass

    async def _work():
        raise _Boom("propagated")

    with pytest.raises(_Boom):
        run_coro(_work())


def test_run_coro_reraises_base_exception():
    """A non-Exception BaseException escapes `except Exception` and must
    still reach the caller (the shape test_lcu_loop_resilience pins)."""
    class _Boom(BaseException):
        pass

    async def _work():
        raise _Boom("propagated")

    with pytest.raises(_Boom):
        run_coro(_work())


def test_run_coro_times_out_on_a_hung_coroutine():
    async def _hang():
        await asyncio.Event().wait()

    with pytest.raises(TimeoutError):
        run_coro(_hang(), timeout=0.2)


def test_run_coro_capturing_thread_stamps_the_loop_thread():
    box: dict = {}

    async def _work():
        return threading.get_ident()

    inner = run_coro_capturing_thread(_work(), box)
    assert box["loop_thread"] == inner
    assert box["loop_thread"] != threading.get_ident()

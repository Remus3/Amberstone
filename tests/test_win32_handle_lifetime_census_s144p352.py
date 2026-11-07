"""S144-P-352 - every production Win32 handle open is closed on every path.

A ``ctypes`` handle is a bare integer: nothing closes it when the code between the open and a
straight-line ``CloseHandle`` raises, and a ``CreateFileW`` handle given to
``msvcrt.open_osfhandle`` stays open if that call raises (the fd that would own it never
exists). This census enumerates every call of ``OpenProcess``, ``OpenProcessToken``,
``CreateFileW``, ``CreateMutexW``, ``CreateJobObjectW`` and ``CreateToolhelp32Snapshot`` (called
as an attribute, or through a local alias such as ``create = k32.CreateFileW``) in the tracked
non-test ``.py`` and requires each to be one of:

- FINALLY: the enclosing function calls ``CloseHandle`` (attribute or alias) inside a ``finally``.
- EXCEPT: the enclosing function calls ``CloseHandle`` inside an ``except`` handler (the open is
  followed by a call that can raise, e.g. ``msvcrt.open_osfhandle``, and the handler releases it).
- NAMED: a row in ``_NAMED`` below: the handle is deliberately not closed here because an owner
  outlives the function (a returned handle whose callers close it in a finally, a handle kept on
  ``self``, a process-lifetime singleton mutex, a handle whose only follow-up is a close that
  cannot raise). A NAMED row states who closes it.

Measured 2026-11-07 over the git index (alias-aware AST): see ``_SITES``. ``ops/fleet_kit/``
(vendored, byte-pinned), ``tests/``, ``agents/agent3_testing/suite/`` and ``docs/_archive/`` are
out of scope. Stated limits: names are matched on the API name, not on the DLL it came from;
FINALLY / EXCEPT mean a ``CloseHandle`` in such a block of the same function, not that it closes
THIS handle (a second handle in one function shares the check); a ``getattr``-built call is not
seen.
"""
from __future__ import annotations

import ast
import functools
import sys
import types

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "agents/agent3_testing/suite/", "docs/_archive/")

_OPENERS = frozenset({
    "OpenProcess", "OpenProcessToken", "CreateFileW", "CreateMutexW", "CreateJobObjectW",
    "CreateToolhelp32Snapshot",
})
_CLOSER = "CloseHandle"

# file -> number of opener calls (measured 2026-11-07).
_SITES = {
    "core/operator_notify.py": 1,
    "core/vision_profiles.py": 1,
    "dashboard/routes_moon_sync.py": 1,
    "ops/launcher/first_run.py": 3,
    "ops/launcher/service_host.py": 5,
    "ops/launcher/updater.py": 1,
    "ops/loop/slots.py": 1,
    "ops/loop/winmutex.py": 1,
    "ops/rc_supervisor.py": 2,
    "tft/sources/tft_log.py": 1,
    "tools/console_flash_detector.py": 1,
    "tools/gated_b29_window_parity.py": 2,
    "tools/lcu_push_watcher.py": 1,
    "tools/moon_sync_poller.py": 2,
    "tools/rc_facts.py": 1,
    "tools/screen_agent.py": 1,
}

# (file, function) -> who closes the handle. Every row names a real owner.
_NAMED = {
    ("ops/launcher/first_run.py", "_win_open"): (
        "returns the handle; the callers release it through _win_close (hold_dir reads it with "
        "_win_info outside a try, so a raise there would strand it: filed, ops/launcher is "
        "main-session owned)"),
    ("ops/launcher/first_run.py", "_win_create_private_file"): (
        "the handle goes straight to msvcrt.open_osfhandle; the except arm releases it through "
        "_win_close before re-raising, and the fd owns it after that"),
    ("ops/launcher/service_host.py", "create"): (
        "the job handle is kept on the returned job object and closed by its close(); the "
        "SetInformationJobObject failure branch closes it before returning None"),
    ("ops/launcher/service_host.py", "__init__"): (
        "ParentWatch keeps the handle on self._handle for its life; close() releases it and "
        "main() calls close() in a finally"),
    ("ops/rc_supervisor.py", "_pid_alive"): (
        "FROZEN file, read only: nothing between OpenProcess and the close can raise past the "
        "enclosing except Exception"),
    ("ops/rc_supervisor.py", "_kill_pid"): (
        "FROZEN file, read only: TerminateProcess is the only call between the open and the "
        "close, inside an except Exception"),
    ("tools/gated_b29_window_parity.py", "_open_process"): (
        "returns (kernel32, handle, code); _read_elevation and _exe_path close it in a finally"),
    ("tools/moon_sync_poller.py", "_open_process"): (
        "returns (handle, error); _pid_alive_detail closes it in a finally through _close_handle"),
    ("tools/moon_sync_poller.py", "_acquire_singleton"): (
        "the singleton mutex is held for the life of the process in _singleton_handle; the "
        "already-exists branch closes the duplicate before returning False"),
}


def _alias_names(scope: ast.AST, wanted: frozenset[str]) -> dict[str, str]:
    """``name = <expr>.<API>`` bindings in ``scope``: local name -> API name."""
    out: dict[str, str] = {}
    for n in ast.walk(scope):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
                and isinstance(n.value, ast.Attribute) and n.value.attr in wanted):
            out[n.targets[0].id] = n.value.attr
    return out


def _api_of(call: ast.Call, aliases: dict[str, str], wanted: frozenset[str]) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute) and f.attr in wanted:
        return f.attr
    if isinstance(f, ast.Name):
        return aliases.get(f.id)
    return None


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST | None:
    cur = parents.get(node)
    while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
        cur = parents.get(cur)
    return cur


def _closes_in(blocks: list[list[ast.stmt]], aliases: dict[str, str]) -> bool:
    for body in blocks:
        for stmt in body:
            for m in ast.walk(stmt):
                if isinstance(m, ast.Call) and _api_of(m, aliases, frozenset({_CLOSER})):
                    return True
    return False


def _facts(source: str) -> list[tuple[str, str, set[str]]]:
    """For each opener call in ``source``: (enclosing function, API, safe shapes it follows)."""
    tree = ast.parse(source)
    parents = _parents(tree)
    out: list[tuple[str, str, set[str]]] = []
    open_aliases: dict[ast.AST, dict[str, str]] = {}
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        fn = _enclosing_function(n, parents)
        scope = fn if fn is not None else tree
        if scope not in open_aliases:
            open_aliases[scope] = _alias_names(scope, _OPENERS)
        api = _api_of(n, open_aliases[scope], _OPENERS)
        if api is None:
            continue
        close_aliases = _alias_names(scope, frozenset({_CLOSER}))
        held: set[str] = set()
        tries = [t for t in ast.walk(scope) if isinstance(t, ast.Try)]
        if _closes_in([t.finalbody for t in tries], close_aliases):
            held.add("FINALLY")
        if _closes_in([h.body for t in tries for h in t.handlers], close_aliases):
            held.add("EXCEPT")
        out.append((getattr(fn, "name", "<module>"), api, held))
    return out


@functools.lru_cache(maxsize=1)
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
    assert "ops/loop/winmutex.py" in files
    assert len(_tree_facts()) >= 10


def test_every_handle_open_site_is_pinned_by_file_and_count():
    tree = _tree_facts()
    assert {f: len(v) for f, v in tree.items()} == _SITES, (
        "a Win32 handle open appeared or went: review how it is closed (a finally, an except "
        "handler, or a NAMED owner), then update _SITES")


def test_every_handle_is_closed_on_every_path():
    unsafe = {}
    for rel, rows in _tree_facts().items():
        bad = [f"{fn}:{api}" for fn, api, held in rows if not held and (rel, fn) not in _NAMED]
        if bad:
            unsafe[rel] = bad
    assert not unsafe, (
        "a Win32 handle whose CloseHandle is skipped by an exception (no CloseHandle in a "
        "finally or an except handler of the function, no NAMED owner); close it in a finally: "
        f"{unsafe}")


def test_every_named_row_is_a_real_unsafe_site_with_a_reason():
    """A NAMED row must still be needed (the site holds no safe shape) and carry a reason."""
    tree = _tree_facts()
    for (rel, fn), why in _NAMED.items():
        assert why.strip(), (rel, fn)
        rows = [held for name, _api, held in tree.get(rel, []) if name == fn]
        assert rows, f"{rel}:{fn} has no handle open any more - drop the row"
        assert any(not held for held in rows), (
            f"{rel}:{fn} now closes in a finally or an except handler - drop the row")


def test_detector_classifies_each_shape():
    fin = ("def f(k32, pid):\n    h = k32.OpenProcess(1, False, pid)\n    try:\n        pass\n"
           "    finally:\n        k32.CloseHandle(h)\n")
    assert _facts(fin) == [("f", "OpenProcess", {"FINALLY"})]
    exc = ("def f(k32, msvcrt, p):\n    h = k32.CreateFileW(p)\n    try:\n"
           "        return msvcrt.open_osfhandle(h, 0)\n    except OSError:\n"
           "        k32.CloseHandle(h)\n        raise\n")
    assert _facts(exc) == [("f", "CreateFileW", {"EXCEPT"})]
    ali = ("def f(k32, p):\n    create = k32.CreateFileW\n    close = k32.CloseHandle\n"
           "    h = create(p)\n    try:\n        pass\n    finally:\n        close(h)\n")
    assert _facts(ali) == [("f", "CreateFileW", {"FINALLY"})]


def test_detector_flags_a_straight_line_close_as_unsafe():
    """Positive control: a close after a call that can raise, outside any finally, is unsafe."""
    leak = ("def f(k32, pid):\n    h = k32.OpenProcess(1, False, pid)\n    work(h)\n"
            "    k32.CloseHandle(h)\n")
    assert _facts(leak) == [("f", "OpenProcess", set())]
    # a CloseHandle in a try BODY (not finally / except) does not cover the handle
    body = ("def f(k32, pid):\n    h = k32.OpenProcess(1, False, pid)\n    try:\n"
            "        k32.CloseHandle(h)\n    finally:\n        pass\n")
    assert _facts(body) == [("f", "OpenProcess", set())]
    # an unrelated API with the same shape is not an opener
    assert _facts("def f(k):\n    k.GetCurrentProcess()\n") == []


# ---- behaviour: a failed open_osfhandle no longer strands the CreateFileW handle ------------

@pytest.mark.skipif(sys.platform != "win32", reason="Win32 handle path")
def test_lcu_push_watcher_closes_the_handle_when_open_osfhandle_fails(monkeypatch):
    import ctypes
    import msvcrt

    from tools import lcu_push_watcher as lpw

    closed: list[int] = []

    def _create(*_a):
        return 4321

    def _close(handle):
        closed.append(getattr(handle, "value", handle))
        return 1

    fake = types.SimpleNamespace(CreateFileW=_create, CloseHandle=_close)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_a, **_k: fake)

    def _boom(_h, _flags):
        raise OSError(24, "Too many open files")

    monkeypatch.setattr(msvcrt, "open_osfhandle", _boom)
    with pytest.raises(OSError):
        lpw._win_open_shared_delete(REPO_ROOT / "README.md")
    assert closed == [4321]


def test_moon_sync_poller_closes_the_probe_handle_when_the_exit_code_read_raises(monkeypatch):
    """The pid probe's handle is released even when the exit-code read raises.

    ``_close_handle`` is faked alongside ``_open_process``: the fake handle is a bare integer
    and closing it for real would close somebody's live OS handle in the pytest process.
    """
    from tools import moon_sync_poller as P

    closed: list[int] = []

    def _raise(_handle):
        raise OSError(6, "invalid handle")

    monkeypatch.setattr(P, "_win32_pid_probe_available", lambda: True)
    monkeypatch.setattr(P, "_open_process", lambda pid: (7, 0))
    monkeypatch.setattr(P, "_process_exit_code", _raise)
    monkeypatch.setattr(P, "_close_handle", closed.append)
    assert P._pid_alive_detail(4242) == (None, "unknown")
    assert closed == [7], "the opened handle must be closed even when the read raised"

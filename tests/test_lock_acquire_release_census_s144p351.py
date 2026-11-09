"""S144-P-351 - every production ``.acquire(`` call is paired with a release that survives an exception.

A lock taken and not released on an exception path wedges every later caller: a coach thread, the
supervisor loop or the launcher update cycle. This census enumerates every ``.acquire(`` call in
the tracked non-test ``.py`` and requires each (file, function) to be one of:

- FINALLY: the same function releases the SAME receiver (``.release()`` / ``.unlock()``) inside a
  ``finally`` block. Needs no row; this is the default shape.
- A named row in ``_ROWS`` whose kind carries its own check:
  - PROBE: acquire-then-release of the same receiver in one function to learn that nothing holds
    the lock (shutdown drain, test-only wait); the release is in the same function.
  - PAIRED: the acquire is in a class's ``__enter__`` / acquire helper and the class's ``__exit__``
    reaches a method that calls ``.release()``.
  - CLAIM: a one-shot hand-off token taken with ``blocking=False`` and never released by design
    (the winner owns the request; the loser returns), so it cannot block and holds nothing.
  - BUCKET: the receiver is not a lock but a rate-limit token bucket whose ``acquire`` has no
    matching ``release``.

Measured 2026-11-07 over the git index: 22 ``.acquire(`` calls in 17 files; 13 are FINALLY, 2 PROBE
(coaches/sr_coach.py, core/rank_tier_bench.py), 2 PAIRED (core/coaching_data_lock.py), 4 CLAIM
(agents/daemon_slayer/server.py x2, dashboard/server.py x2) and 1 BUCKET (core/riot_api.py).
``ops/fleet_kit/`` (vendored, byte-pinned), ``tests/``, ``agents/agent3_testing/suite/`` and
``docs/_archive/`` are out of scope.

Stated limits: the match is on the attribute name ``acquire`` (a ``from ... import acquire`` call
or ``getattr(lock, "acquire")`` is not seen); FINALLY proves a release of the same receiver text
sits in some ``finally`` of the function (a nested function's included - rank_tier_bench and
smoothed_rates_101qq release in a nested ``_run``), not that the acquire is lexically before that
``try`` or that this ``try`` covers it; rows are keyed by (file, function), so a second acquire in
a row's function is held to that row's kind check only; the ``with lock:`` form needs no census
and is not read.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "agents/agent3_testing/suite/", "docs/_archive/")
_RELEASERS = ("release", "unlock")

# (file, function) -> (kind, receiver text, why)
_ROWS = {
    ("coaches/sr_coach.py", "shutdown"):
        ("PROBE", "self._lock", "bounded 3 s drain of an in-flight coach call, released at once"),
    ("core/rank_tier_bench.py", "_await_refresh_for_tests"):
        ("PROBE", "_REFRESH_LOCK", "test-only wait for the refresher to go idle, released at once"),
    ("core/coaching_data_lock.py", "__enter__"):
        ("PAIRED", "self._tl", "released by _release_thread_lock, which __exit__ calls in a finally"),
    ("core/coaching_data_lock.py", "_acquire_file_lock"):
        ("PAIRED", "fl", "stored on the instance and released by _release_file_lock from __exit__"),
    ("agents/daemon_slayer/server.py", "_abandon_unstarted"):
        ("CLAIM", "claim", "one-shot request hand-off token, non-blocking"),
    ("agents/daemon_slayer/server.py", "_process_claimed"):
        ("CLAIM", "claim", "one-shot request hand-off token, non-blocking"),
    ("dashboard/server.py", "process_request_thread"):
        ("CLAIM", "claim", "one-shot request hand-off token, non-blocking"),
    ("dashboard/server.py", "_abandon_unstarted"):
        ("CLAIM", "claim", "one-shot request hand-off token, non-blocking"),
    ("core/riot_api.py", "_call_ex_inner"):
        ("BUCKET", "_BUCKET", "DualBucket rate-limit tokens: acquire spends a token, nothing to release"),
}

# PAIRED rows: (file, class) whose __exit__ must reach a method that calls .release().
_PAIRED_CLASS = {"core/coaching_data_lock.py": "_CombinedLock"}


def _recv(call: ast.Call) -> str:
    return ast.unparse(call.func.value)  # type: ignore[attr-defined]


def _is_attr_call(n: ast.AST, names: tuple[str, ...]) -> bool:
    return isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in names


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}


def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]):
    cur = parents.get(node)
    while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
        cur = parents.get(cur)
    return cur


def _finally_release_receivers(fn: ast.AST) -> set[str]:
    out: set[str] = set()
    for m in ast.walk(fn):
        if isinstance(m, ast.Try):
            for stmt in m.finalbody:
                for k in ast.walk(stmt):
                    if _is_attr_call(k, _RELEASERS):
                        out.add(_recv(k))  # type: ignore[arg-type]
    return out


def _any_release_receivers(fn: ast.AST) -> set[str]:
    return {_recv(k) for k in ast.walk(fn) if _is_attr_call(k, _RELEASERS)}  # type: ignore[arg-type]


def _sites(source: str) -> list[dict]:
    """One dict per ``.acquire(`` call: line, function name, receiver, FINALLY flag, facts."""
    tree = ast.parse(source)
    parents = _parents(tree)
    out = []
    for n in ast.walk(tree):
        if not _is_attr_call(n, ("acquire",)):
            continue
        fn = _enclosing_function(n, parents)
        recv = _recv(n)  # type: ignore[arg-type]
        nonblocking = any(
            k.arg == "blocking" and isinstance(k.value, ast.Constant) and k.value.value is False
            for k in n.keywords)  # type: ignore[attr-defined]
        out.append({
            "line": n.lineno, "fn": fn.name if fn is not None else None, "recv": recv,
            "finally": fn is not None and recv in _finally_release_receivers(fn),
            "released": fn is not None and recv in _any_release_receivers(fn),
            "nonblocking": nonblocking,
        })
    return sorted(out, key=lambda s: s["line"])


def _tree_sites() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(p)
        if rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel:
            continue
        try:
            sites = _sites(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        if sites:
            out[rel] = sites
    return out


def _row_obligation_failures(rel: str, site: dict, kind: str, recv: str) -> list[str]:
    """The falsifiable check of one named row; an empty list means it holds."""
    bad = []
    if site["recv"] != recv:
        bad.append(f"{rel}:{site['line']} receiver {site['recv']!r} != row {recv!r}")
    if kind == "PROBE" and not site["released"]:
        bad.append(f"{rel}:{site['line']} PROBE with no release of {recv} in {site['fn']}")
    if kind == "CLAIM":
        if not site["nonblocking"]:
            bad.append(f"{rel}:{site['line']} CLAIM acquire is not blocking=False")
        if site["released"]:
            bad.append(f"{rel}:{site['line']} CLAIM receiver is released in {site['fn']}")
    return bad


def test_walk_is_not_vacuous():
    tree = _tree_sites()
    assert "core/coaching_data_lock.py" in tree
    assert "ops/rc_supervisor.py" in tree
    assert sum(len(v) for v in tree.values()) >= 18


def test_every_acquire_releases_in_a_finally_or_is_a_named_row():
    bad = []
    for rel, sites in _tree_sites().items():
        for s in sites:
            if s["finally"]:
                continue
            row = _ROWS.get((rel, s["fn"]))
            if row is None:
                bad.append(f"{rel}:{s['line']} ({s['recv']}.acquire in {s['fn']})")
                continue
            bad.extend(_row_obligation_failures(rel, s, row[0], row[1]))
    assert not bad, (
        "a lock acquired with no release in a `finally` of the same function (and no named, "
        f"checked row) stays held when anything between acquire and release raises: {bad}")


def test_every_row_is_live():
    """A row that matches no un-finalled acquire is a dead exemption a new bare acquire could hide behind."""
    tree = _tree_sites()
    for (rel, fname), (kind, recv, why) in _ROWS.items():
        assert why.strip(), (rel, fname)
        hits = [s for s in tree.get(rel, ()) if s["fn"] == fname and not s["finally"]]
        assert hits, f"row {(rel, fname)} matches no acquire that lacks a finally release"


def test_paired_rows_have_an_exit_that_releases():
    for rel, cls in _PAIRED_CLASS.items():
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == cls)
        methods = {m.name: m for m in node.body if isinstance(m, ast.FunctionDef)}
        assert "__exit__" in methods, (rel, cls)
        called = {k.func.attr for k in ast.walk(methods["__exit__"])
                  if isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute)
                  and isinstance(k.func.value, ast.Name) and k.func.value.id == "self"}
        releasing = [name for name in called
                     if name in methods and _any_release_receivers(methods[name])]
        assert len(releasing) >= 2, (
            f"{rel} {cls}.__exit__ must reach both the thread-lock and the file-lock release "
            f"(reached {sorted(called)})")


def test_bucket_row_receiver_is_a_token_bucket_without_release():
    src = (REPO_ROOT / "core/riot_api.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "DualBucket")
    names = {m.name for m in cls.body if isinstance(m, ast.FunctionDef)}
    assert "acquire" in names and not names & set(_RELEASERS), names
    assigned = [n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_BUCKET" for t in n.targets)]
    assert assigned and isinstance(assigned[0].value, ast.Call)
    assert ast.unparse(assigned[0].value.func) == "DualBucket"


def test_detector_catches_a_bare_acquire_and_accepts_a_finally_release():
    bare = "def f(lock):\n    lock.acquire()\n    work()\n    lock.release()\n"
    safe = "def f(lock):\n    lock.acquire()\n    try:\n        work()\n    finally:\n        lock.release()\n"
    other = "def f(a, b):\n    a.acquire()\n    try:\n        work()\n    finally:\n        b.release()\n"
    assert _sites(bare)[0]["finally"] is False and _sites(bare)[0]["released"] is True
    assert _sites(safe)[0]["finally"] is True
    assert _sites(other)[0]["finally"] is False
    claim = "def f(c):\n    return c.acquire(blocking=False)\n"
    s = _sites(claim)[0]
    assert s["nonblocking"] is True and s["released"] is False
    assert _row_obligation_failures("x.py", s, "CLAIM", "c") == []
    assert _row_obligation_failures("x.py", _sites(bare)[0], "CLAIM", "lock")

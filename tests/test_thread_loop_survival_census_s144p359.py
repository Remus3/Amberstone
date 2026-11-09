"""S144-P-359 - a production thread whose target loops catches Exception inside the loop, or is a named row.

A worker thread that runs ``while ...:`` and lets one exception out of the loop body ends silently: under
``pythonw.exe`` nothing prints, the thread is gone, and whatever it kept fresh (a cache, a decision file, a
board) serves stale data for the rest of the process. The hotkey listener's decision-refresh thread
(S144-P-358) and ``core/metrics_cache.py`` ``_loop`` / ``_loop_async`` (this change) were both that shape.

Detector (AST over every tracked ``.py`` outside ``tests/``, ``docs/`` and the vendored ``ops/fleet_kit/``): for
each ``Thread(target=T)`` / ``Timer(interval, T)`` call whose target ``T`` resolves to a function defined in
the SAME file (a bare name, ``self.<name>``, ``<obj>.<name>``, or a loop variable over a literal tuple or list
of such names, the ``for fn in (a, b, c): Thread(target=fn)`` shape), take the function's OUTERMOST ``while``
statements (a ``while`` nested in another ``while`` of the same function is part of it; nested defs are not
descended into). A thread is:
- ``guarded``: every outermost ``while`` holds, somewhere in its body, a ``try`` with a handler that catches
  ``Exception``, ``BaseException`` or everything;
- ``oneshot``: the target has no ``while`` at all (it runs once and ends; an exception there ends a thread that
  was about to end);
- ``unguarded``: has a ``while`` with no such ``try``. Each one must be a row in ``_ROWS`` below, and the row's
  kind is CHECKED against the source, not taken on trust.
A target that does not resolve in the same file (a lambda, ``serve_forever``, a method defined in another
module) is counted and pinned by ``_UNRESOLVED``; it is a limit of this census, listed so a new one is a
decision.

One hop (S144-P-360): a target with no ``while`` of its own that calls a function defined in the SAME file
(a bare name or ``self.<name>`` / ``cls.<name>``, never ``<other>.<name>``) whose body has an outermost ``while`` takes that callee's
kind, so ``Thread(target=self._run)`` where ``_run`` is ``asyncio.run(self._async_loop())`` is checked through
``_async_loop``. Only the target's direct callees are followed (one hop, same file); the call is matched on the
callee's NAME (bare or on self / cls), so two same-file defs of one name are all checked. A Timer whose target creates another Timer
(self re-arming, a loop in disguise) is counted by ``_scan_timer_rearms`` and pinned at zero.

Stated limits: only ``while`` loops are seen (a ``for`` over a queue is not); a ``try`` anywhere inside the
loop counts, even one that guards only part of the body or whose handler re-raises; a callee in another
module, or two hops away, is not followed; a name that resolves to two same-file defs is checked as both.
"""
from __future__ import annotations

import ast
from typing import NamedTuple

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_SKIP_PREFIXES = ("tests/", "docs/", "ops/fleet_kit/")
_THREAD_CALLS = {"Thread", "Timer"}
_BROAD = {"Exception", "BaseException"}


class Site(NamedTuple):
    rel: str
    line: int
    target: str
    kind: str  # guarded | oneshot | unguarded | unresolved


def _call_name(call: ast.Call) -> str | None:
    fn = call.func
    if isinstance(fn, ast.Attribute):
        return fn.attr
    if isinstance(fn, ast.Name):
        return fn.id
    return None


def _target_expr(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == "target" or (name == "Timer" and kw.arg == "function"):
            return kw.value
    if name == "Timer" and len(call.args) >= 2:
        return call.args[1]
    if name == "Thread" and len(call.args) >= 2:
        return call.args[1]  # Thread(group, target, ...)
    return None


def _name_of(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Attribute):
        return expr.attr
    if isinstance(expr, ast.Name):
        return expr.id
    return None


def _own_nodes(func: ast.AST):
    """Every node of ``func`` without entering a nested def or lambda."""
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _outermost_whiles(func: ast.AST) -> list[ast.While]:
    whiles = [n for n in _own_nodes(func) if isinstance(n, ast.While)]
    inner = {id(n) for w in whiles for n in _own_nodes(w) if isinstance(n, ast.While)}
    return [w for w in whiles if id(w) not in inner]


def _is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    elts = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(_name_of(e) in _BROAD for e in elts)


def _loop_has_broad_try(loop: ast.While) -> bool:
    return any(isinstance(n, ast.Try) and any(_is_broad(h) for h in n.handlers) for n in _own_nodes(loop))


def _loop_var_names(tree: ast.AST, call: ast.Call, var: str) -> list[str]:
    """Names in the literal tuple/list a ``for <var> in (...)`` encloses ``call`` iterates."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.For) and isinstance(node.target, ast.Name) and node.target.id == var
                and isinstance(node.iter, (ast.Tuple, ast.List))
                and any(c is call for c in ast.walk(node))):
            return [n for n in (_name_of(e) for e in node.iter.elts) if n]
    return []


def _loop_kinds(fn: ast.AST) -> list[str]:
    loops = _outermost_whiles(fn)
    if not loops:
        return []
    return ["guarded" if all(_loop_has_broad_try(w) for w in loops) else "unguarded"]


def _same_file_callee(func: ast.expr) -> str | None:
    """The name of a call to a bare function or to ``self.<name>`` / ``cls.<name>``, else None.

    An attribute call on any other object (``asyncio.run(...)``, ``rec.run()``) is not matched by name: it
    would pair the call with an unrelated same-file def of the same name.
    """
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in ("self", "cls"):
        return func.attr
    return None


def _delegate_kinds(fn: ast.AST, defs: dict[str, list[ast.AST]]) -> list[str]:
    """Kinds of the looping same-file functions ``fn`` calls directly (one hop; ``fn`` itself excluded)."""
    kinds: list[str] = []
    seen: set[str] = set()
    for node in _own_nodes(fn):
        if not isinstance(node, ast.Call):
            continue
        callee = _same_file_callee(node.func)
        if not callee or callee in seen or callee not in defs:
            continue
        seen.add(callee)
        for cf in defs[callee]:
            if cf is not fn:
                kinds.extend(_loop_kinds(cf))
    return kinds


def _scan_source(rel: str, source: str) -> list[Site]:
    tree = ast.parse(source)
    defs: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.setdefault(node.name, []).append(node)
    out: list[Site] = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        name = _call_name(call)
        if name not in _THREAD_CALLS:
            continue
        expr = _target_expr(call, name)
        if expr is None:
            continue
        tname = _name_of(expr)
        names = [tname] if tname else []
        if isinstance(expr, ast.Name) and expr.id not in defs:
            names = _loop_var_names(tree, call, expr.id) or names
        if not names:
            out.append(Site(rel, call.lineno, type(expr).__name__, "unresolved"))
            continue
        for n in names:
            funcs = defs.get(n)
            if not funcs:
                out.append(Site(rel, call.lineno, n, "unresolved"))
                continue
            kinds = []
            for fn in funcs:
                own = _loop_kinds(fn)
                kinds.extend(own or _delegate_kinds(fn, defs) or ["oneshot"])
            kind = "unguarded" if "unguarded" in kinds else ("guarded" if "guarded" in kinds else "oneshot")
            out.append(Site(rel, call.lineno, n, kind))
    return out


def _scan_timer_rearms(source: str) -> list[tuple[int, str]]:
    """(line, target) of each Timer whose same-file target body creates another Timer."""
    tree = ast.parse(source)
    defs: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.setdefault(node.name, []).append(node)
    out: list[tuple[int, str]] = []
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and _call_name(call) == "Timer"):
            continue
        expr = _target_expr(call, "Timer")
        tname = _name_of(expr) if expr is not None else None
        for fn in defs.get(tname or "", []):
            if any(isinstance(n, ast.Call) and _call_name(n) == "Timer" for n in _own_nodes(fn)):
                out.append((call.lineno, tname or ""))
    return out


def _scan() -> list[Site]:
    sites: list[Site] = []
    for path in repo_files():
        rel = relative_posix(path)
        if not rel.endswith(".py") or rel.startswith(_SKIP_PREFIXES) or "/tests/" in rel:
            continue
        sites.extend(_scan_source(rel, path.read_text(encoding="utf-8")))
    return sites


# (file, target) -> kind. The kind is checked against the source in ``_ROW_CHECKS``; the reason is prose.
_ROWS = {
    ("core/death_recap.py", "_worker_loop"): (
        "total-body",
        "process_kill is one broad try (never raises) and _enqueue restarts a worker that is not alive",
    ),
    ("core/resource_manager.py", "_watchdog_loop"): (
        "total-tick",
        "the loop body is one call to _watchdog_tick, which is a single broad try (a probe or remediation "
        "hook failure is logged as an unmeasurable sample); the only other statement is Event.wait",
    ),
    ("dashboard/routes_team_context.py", "_fanout_worker"): (
        "finally-settles",
        "a bounded one-run roster walk, not a service loop: the while sits in a try/finally that settles "
        "the worker so the next POST starts a new one",
    ),
    ("tft/rounds/store.py", "_writer_main"): (
        "total-apply",
        "_apply catches Exception per op (its COMMIT / ROLLBACK paths catch sqlite3.Error only, a stated "
        "gap); a dead writer fills the bounded queue and later writes are counted as queue_full drops; the "
        "finally closes the connection and releases barrier waiters",
    ),
}

# Targets the same-file resolver cannot follow. Pinned so a new one is a decision, not an accident.
_UNRESOLVED = {
    ("agents/_supervisor_http.py", "serve_forever"),  # socketserver loop; handler errors go to handle_error
    ("app/_remediation.py", "_game_poll_worker"),  # defined in app/__init__.py; its loop holds broad trys
    ("coaches/_base_coach.py", "Lambda"),  # asyncio.run(self._poll_loop() / _vision_loop())
    ("dashboard/server.py", "serve_forever"),  # socketserver loop
    ("mc/server.py", "serve_forever"),  # socketserver loop
    ("tools/regen_ranged_marksman_builds_item213.py", "serve_forever"),  # one-shot tool's local server
    ("tools/replay_session.py", "serve_forever"),  # replay tool's local server
}


def _func(rel: str, name: str) -> ast.AST:
    tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    found = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    assert len(found) == 1, f"{rel} {name}: expected one def, found {len(found)}"
    return found[0]


def _body_without_docstring(fn: ast.AST) -> list[ast.stmt]:
    body = list(fn.body)  # type: ignore[attr-defined]
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
        body = body[1:]
    return [st for st in body if not isinstance(st, ast.Global)]


def _check_total_body() -> None:
    body = _body_without_docstring(_func("core/death_recap.py", "process_kill"))
    assert len(body) == 1 and isinstance(body[0], ast.Try) and any(_is_broad(h) for h in body[0].handlers), (
        "death_recap.process_kill must be a single broad try, or _worker_loop can die on a raise"
    )
    enqueue = _func("core/death_recap.py", "_enqueue")
    assert any(isinstance(n, ast.Attribute) and n.attr == "is_alive" for n in ast.walk(enqueue)), (
        "death_recap._enqueue must restart a worker that is not alive"
    )


def _check_total_tick() -> None:
    body = _body_without_docstring(_func("core/resource_manager.py", "_watchdog_tick"))
    assert len(body) == 1 and isinstance(body[0], ast.Try) and any(_is_broad(h) for h in body[0].handlers), (
        "resource_manager._watchdog_tick must be a single broad try, or _watchdog_loop can die on a raise"
    )


def _check_finally_settles() -> None:
    fn = _func("dashboard/routes_team_context.py", "_fanout_worker")
    tries = [n for n in _own_nodes(fn) if isinstance(n, ast.Try) and n.finalbody]
    assert any(
        any(isinstance(w, ast.While) for w in ast.walk(t))
        and any(isinstance(n, ast.Name) and n.id == "_settle_worker_locked"
                for st in t.finalbody for n in ast.walk(st))
        for t in tries
    ), "_fanout_worker's while must sit in a try whose finally calls _settle_worker_locked"


def _check_total_apply() -> None:
    fn = _func("tft/rounds/store.py", "_apply")
    assert any(isinstance(n, ast.Try) and any(_is_broad(h) for h in n.handlers) for n in _own_nodes(fn)), (
        "tft/rounds/store.py _apply must catch Exception per op, or _writer_main can die on a bad row"
    )
    writer = _func("tft/rounds/store.py", "_writer_main")
    assert any(isinstance(n, ast.Try) and n.finalbody for n in _own_nodes(writer)), (
        "_writer_main must close its connection in a finally"
    )


_ROW_CHECKS = {
    "total-body": _check_total_body,
    "total-tick": _check_total_tick,
    "finally-settles": _check_finally_settles,
    "total-apply": _check_total_apply,
}


def test_every_looping_thread_target_is_guarded_or_a_named_row():
    unguarded = {(s.rel, s.target) for s in _scan() if s.kind == "unguarded"}
    assert unguarded == set(_ROWS), (
        f"unnamed: {sorted(unguarded - set(_ROWS))}  stale rows: {sorted(set(_ROWS) - unguarded)}. "
        "A thread target with a while loop and no broad try inside it dies on its first raise "
        "(S144-P-358 / S144-P-359). Put a try/except Exception inside the loop, or add a row with a source check."
    )


def test_each_row_kind_is_checked_against_the_source():
    assert {kind for kind, _ in _ROWS.values()} == set(_ROW_CHECKS)
    for kind, _reason in _ROWS.values():
        _ROW_CHECKS[kind]()


def test_unresolved_targets_are_pinned():
    seen = {(s.rel, s.target) for s in _scan() if s.kind == "unresolved"}
    assert seen == _UNRESOLVED, f"new: {sorted(seen - _UNRESOLVED)}  gone: {sorted(_UNRESOLVED - seen)}"


def test_the_scan_sees_the_guarded_population():
    sites = _scan()
    guarded = {(s.rel, s.target) for s in sites if s.kind == "guarded"}
    # Anchors: loops this change or an earlier cycle depends on being seen as guarded, so an empty or
    # blind scan cannot pass the two tests above.
    assert ("core/metrics_cache.py", "_loop") in guarded
    assert ("tools/lcu_agent.py", "_state_push_loop") in guarded  # reached through a for-loop over names
    assert ("tools/hotkey_listener.py", "_refresh_loop") in guarded
    # S144-P-360: reached through one same-file delegate (target runs asyncio.run(<looping coroutine>)).
    assert ("core/obs_publisher.py", "_run") in guarded
    assert len(guarded) >= 25 and len(sites) >= 60


def test_detector_classifies_synthetic_sources():
    src = """
import threading
def good():
    while True:
        try:
            x()
        except Exception:
            pass
def narrow():
    while True:
        try:
            x()
        except ValueError:
            pass
def bare():
    while True:
        x()
def once():
    x()
def nested():
    while a:
        while b:
            x()
        try:
            y()
        except BaseException:
            pass
def outer():
    for fn in (good, bare):
        threading.Thread(target=fn).start()
    threading.Thread(target=narrow).start()
    threading.Timer(5, once).start()
    threading.Thread(target=nested).start()
    threading.Thread(target=lambda: 1).start()
"""
    got = {(s.target, s.kind) for s in _scan_source("x.py", src)}
    assert got == {("good", "guarded"), ("bare", "unguarded"), ("narrow", "unguarded"), ("once", "oneshot"),
                   ("nested", "guarded"), ("Lambda", "unresolved")}


def test_a_one_hop_delegate_takes_the_callees_kind():
    """S144-P-360: a target with no while of its own is classified by the looping same-file function it calls."""
    src = """
import threading
class A:
    def _loop_bad(self):
        while True:
            x()
    def _loop_ok(self):
        while True:
            try:
                x()
            except Exception:
                pass
    def run_bad(self):
        asyncio.run(self._loop_bad())
    def run_ok(self):
        self._loop_ok()
    def run_flat(self):
        helper()
    def recur(self):
        self.recur()
    def run(self):
        while True:
            x()
    def via_other_object(self):
        asyncio.run(main())
        rec.run()
    def start(self):
        threading.Thread(target=self.run_bad).start()
        threading.Thread(target=self.run_ok).start()
        threading.Thread(target=self.run_flat).start()
        threading.Thread(target=self.recur).start()
        threading.Thread(target=self.via_other_object).start()
"""
    got = {(s.target, s.kind) for s in _scan_source("x.py", src)}
    assert got == {("run_bad", "unguarded"), ("run_ok", "guarded"), ("run_flat", "oneshot"), ("recur", "oneshot"),
                   ("via_other_object", "oneshot")}


def test_the_delegate_hop_does_not_follow_two_hops_or_other_files():
    src = """
import threading
def deep():
    while True:
        x()
def mid():
    deep()
def top():
    mid()
def other():
    imported_module.looping_helper()
def start():
    threading.Thread(target=top).start()
    threading.Thread(target=other).start()
"""
    got = {(s.target, s.kind) for s in _scan_source("x.py", src)}
    assert got == {("top", "oneshot"), ("other", "oneshot")}  # documented limit: one hop, same file


def test_no_timer_target_re_arms_itself():
    """A Timer whose target starts another Timer is a loop with no while; none exists today (measured)."""
    found = []
    for path in repo_files():
        rel = relative_posix(path)
        if not rel.endswith(".py") or rel.startswith(_SKIP_PREFIXES) or "/tests/" in rel:
            continue
        found.extend((rel, line, tgt) for line, tgt in _scan_timer_rearms(path.read_text(encoding="utf-8")))
    assert found == [], (
        f"a self re-arming Timer is an unguarded loop the while-based census cannot see: {found}. "
        "Guard the re-arm in a try/finally or convert it to a thread loop with a broad try."
    )


def test_timer_rearm_detector_classifies_synthetic_sources():
    src = """
import threading
def tick():
    work()
    threading.Timer(5, tick).start()
def once():
    work()
def go():
    threading.Timer(1, tick).start()
    threading.Timer(1, once).start()
"""
    assert [t for _l, t in _scan_timer_rearms(src)] == ["tick", "tick"]

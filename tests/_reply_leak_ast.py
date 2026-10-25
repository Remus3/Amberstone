"""The reply-scrub source guards' shared AST detector (RM-824, RM-835, RM-837).

A guard asks: does an except-bound exception reach a reply shape - a dict
literal, a ``return`` value, a reply call or a reply-container mutation -
before any safe call? Each guard passes its own call sets; this module owns
the walk.

RM-837: the RM-824 / RM-835 walk went up from each use of the bound name to
the first reply node only, so a value ASSIGNED first never reached one
(``msg = str(exc)`` then ``return 400, {"error": msg}`` read clean). The walk
now taints what the exception flows into - an assignment target (a plain
name, a subscript store, an attribute path, an augmented assignment) or the
receiver of an ``append`` / ``extend`` / ``insert`` / ``update`` /
``setdefault`` call - and follows every later load of a tainted name in the
enclosing function the same way, to a fixed point, so a reply after the
handler and a second hop are seen too. A safe call still ends a path, so a
name derived through one (``kind = type(exc).__name__``) is not tainted.

Known limits, stated so a green sweep is not over-read (the first three
found by the RM-837 verifier): a ``for`` or ``with`` target is not tainted
(``for a in exc.args: return {"e": a}`` reads clean); only a load at or
after the tainting line is followed, so a reply earlier in the text that a
loop reaches later is missed; a receiver rooted in a call
(``h.state().update(e=str(exc))``) is not tainted, though a guard that lists
the method as a reply mutation still flags its line. The other way round,
the taint is flow-insensitive (a tainted name re-bound to a fixed value
still counts), and it does not cross a function boundary (a tainted value
returned to a caller that replies with it is seen only as the ``return``).
"""
from __future__ import annotations

import ast
from collections.abc import Iterable, Iterator

# The calls that carry a value into their receiver. A guard may also list
# some of them as reply mutations (flagged on their own line); either way the
# receiver is tainted.
TAINT_CALLS = frozenset({"append", "extend", "insert", "update", "setdefault"})
_ASSIGNS = (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def call_name(node: ast.Call) -> str:
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def _key(node: ast.AST) -> str | None:
    """The tracked name of a store or load: ``payload`` for ``payload`` and
    ``payload["a"]``, ``self.err`` for ``self.err`` and ``self.err["a"]``;
    None for anything rooted in a call or a literal."""
    while isinstance(node, (ast.Subscript, ast.Starred)):
        node = node.value
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join([node.id, *reversed(parts)])


def _target_keys(target: ast.AST) -> Iterator[str]:
    if isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _target_keys(elt)
        return
    key = _key(target)
    if key:
        yield key


def _scope_of(node: ast.AST, parents: dict) -> ast.AST:
    cur = node
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, _SCOPES):
            return cur
    return cur


def reply_leaks(src: str, *, safe_calls: Iterable[str],
                log_levels: Iterable[str], reply_calls: Iterable[str],
                mutation_calls: Iterable[str] = (),
                safe_attrs: Iterable[str] = ()) -> list[int]:
    """Lines where an except-bound name, or a name tainted from it, reaches a
    reply shape before any safe call. A log call is not a reply (its
    scrubbing is RM-811's guard)."""
    safe = set(safe_calls) | set(log_levels)
    reply = set(reply_calls)
    mutation = set(mutation_calls)
    safe_attrs = set(safe_attrs)
    tree = ast.parse(src)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    bad: set[int] = set()

    def follow(use: ast.AST, stop: ast.AST, taint: dict[str, int]) -> None:
        parent = parents.get(use)
        if isinstance(parent, ast.Attribute) and parent.attr in safe_attrs:
            return
        child = cur = use
        while cur is not stop and cur in parents:
            child, cur = cur, parents[cur]
            if isinstance(cur, ast.Call):
                name = call_name(cur)
                if name in safe:
                    return
                if name in reply:
                    bad.add(use.lineno)
                    return
                if name in mutation:
                    bad.add(use.lineno)
                if (name in TAINT_CALLS or name in mutation) \
                        and child is not cur.func \
                        and isinstance(cur.func, ast.Attribute):
                    key = _key(cur.func.value)
                    if key:
                        taint.setdefault(key, cur.lineno)
                        return
                if name in mutation:
                    return
            if isinstance(cur, (ast.Dict, ast.Return)):
                bad.add(use.lineno)
                return
            if isinstance(cur, _ASSIGNS):
                if child is cur.value:
                    targets = (cur.targets if isinstance(cur, ast.Assign)
                               else [cur.target])
                    for t in targets:
                        for key in _target_keys(t):
                            taint.setdefault(key, cur.lineno)
                return
            if isinstance(cur, ast.stmt):
                return

    for h in ast.walk(tree):
        if not (isinstance(h, ast.ExceptHandler) and h.name):
            continue
        taint: dict[str, int] = {}
        for stmt in h.body:
            for n in ast.walk(stmt):
                if isinstance(n, ast.Name) and n.id == h.name:
                    follow(n, h, taint)
        if not taint:
            continue
        scope = _scope_of(h, parents)
        loads = [n for n in ast.walk(scope)
                 if isinstance(n, (ast.Name, ast.Attribute))
                 and isinstance(n.ctx, ast.Load)]
        followed: set[int] = set()
        while True:
            size = len(taint)
            for n in loads:
                key = _key(n)
                if key in taint and n.lineno >= taint[key] \
                        and id(n) not in followed:
                    followed.add(id(n))
                    follow(n, scope, taint)
            if len(taint) == size:
                break
    return sorted(bad)


# RM-837: the four shapes measured reading clean at ca5b44e41 (an exception
# that reaches a reply through an assignment), plus a two-hop alias whose
# reply sits after the handler. One function per shape, so one shape's
# tainted name cannot flag another shape's reply line.
ASSIGNMENT_SHAPES = (
    "def a(h):\n"
    "    try:\n"
    "        pass\n"
    "    except ValueError as exc:\n"
    "        msg = str(exc)\n"
    "        return 400, {'error': msg}\n"                    # 6
    "def b(h, payload):\n"
    "    try:\n"
    "        pass\n"
    "    except OSError as exc:\n"
    "        payload['error'] = str(exc)\n"
    "        return 503, payload\n"                           # 12
    "def c(h, payload):\n"
    "    try:\n"
    "        pass\n"
    "    except KeyError as exc:\n"
    "        payload.update(error=str(exc))\n"
    "        return 503, payload\n"                           # 18
    "def d(h, payload):\n"
    "    try:\n"
    "        pass\n"
    "    except TypeError as exc:\n"
    "        payload['error'] += str(exc)\n"
    "        return 503, payload\n"                           # 24
    "def e(h):\n"
    "    try:\n"
    "        pass\n"
    "    except RuntimeError as exc:\n"
    "        detail = str(exc)\n"
    "        text = 'failed: ' + detail\n"
    "    h._send(500, text, 'text/plain')\n"                  # 31
)
# Names derived only through a safe call carry no exception text.
SAFE_ASSIGNMENTS = (
    "def f(h, payload):\n"
    "    try:\n"
    "        pass\n"
    "    except ValueError as exc:\n"
    "        kind = type(exc).__name__\n"
    "        log.warning('x: %s', scrub_log(str(exc)))\n"
    "        payload['kind'] = kind\n"
    "        return 400, {'error': f'bad input ({kind}) - see logs'}\n"
    "    except OSError as exc:\n"
    "        why = scrub_log(str(exc))\n"
    "        log.warning('steer: %s', why)\n"
    "        state = {'ok': False}\n"
    "        return 503, state\n"
    "    return 200, payload\n"
)

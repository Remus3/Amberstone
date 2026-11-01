"""RM-1284: the server.py module docstring lists every route and status.

The module docstring is the first thing a reader of ``server.py`` sees, and
its "Routes" block is hand-authored apart from the ``_POST_ROUTES`` dispatch
dict and ``Handler.do_GET``. Measured at ENGINE 1.290.0 it named 4 of the 31
POST routes, left out the GET-only ``/modifier-summary``, and its "Errors map
to" block omitted 408 (body read timeout) and 413 (body too large), both
raised in this file.

Every table is read STRUCTURALLY with ``ast`` (importing server.py drags in
the whole engine). Docstring route lines are matched as a whole
``METHOD /path`` token at line start, so ``/rank`` cannot be satisfied by
``/rank-tank``.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_SERVER = Path(__file__).resolve().parents[1] / "server.py"

_ROUTE_LINE_RE = re.compile(r"^\s+(GET|POST)\s+(/\S*)", re.M)
_STATUS_LINE_RE = re.compile(r"^\s+(\d{3}) - ", re.M)
_STATUS_CALLS = {"_ApiError", "_engine_reject", "_send_error"}


def _tree() -> ast.Module:
    return ast.parse(_SERVER.read_text(encoding="utf-8"))


def _docstring() -> str:
    doc = ast.get_docstring(_tree(), clean=False)
    assert doc, "server.py has no module docstring"
    return doc


def _doc_routes(method: str) -> list[str]:
    return [p for m, p in _ROUTE_LINE_RE.findall(_docstring()) if m == method]


def _post_routes() -> list[str]:
    for node in _tree().body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_POST_ROUTES":
                    assert isinstance(node.value, ast.Dict)
                    keys = [k.value for k in node.value.keys
                            if isinstance(k, ast.Constant)]
                    assert len(keys) == len(node.value.keys)
                    return keys
    raise AssertionError("_POST_ROUTES not found at module level")


def _get_only_routes() -> list[str]:
    """Paths ``Handler.do_GET`` compares ``path`` against by literal."""
    for node in ast.walk(_tree()):
        if isinstance(node, ast.FunctionDef) and node.name == "do_GET":
            found: list[str] = []
            for cmp in ast.walk(node):
                if not (isinstance(cmp, ast.Compare)
                        and isinstance(cmp.left, ast.Name)
                        and cmp.left.id == "path"):
                    continue
                for op, right in zip(cmp.ops, cmp.comparators):
                    if isinstance(op, ast.Eq) and isinstance(right, ast.Constant):
                        found.append(right.value)
                    elif isinstance(op, ast.In) and isinstance(right, ast.Tuple):
                        found.extend(e.value for e in right.elts
                                     if isinstance(e, ast.Constant))
            return [p for p in found if p]
    raise AssertionError("Handler.do_GET not found")


def _raised_statuses() -> set[int]:
    codes: set[int] = set()
    for node in ast.walk(_tree()):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        first = node.args[0]
        if name in _STATUS_CALLS and isinstance(first, ast.Constant) \
                and isinstance(first.value, int):
            codes.add(first.value)
    return codes


def test_enumerations_are_not_empty():
    # An empty walk would pass every subset assertion below vacuously.
    assert len(_post_routes()) >= 31
    assert {"/", "/health", "/snapshot", "/modifier-summary"} <= set(_get_only_routes())
    assert {400, 404, 408, 413, 422, 500} <= _raised_statuses()


def test_doc_post_lines_match_dispatch_order_and_are_unique():
    posted = _doc_routes("POST")
    assert len(posted) == len(set(posted)), "a POST line is listed twice"
    assert posted == _post_routes()


def test_doc_get_lines_match_do_get():
    listed = _doc_routes("GET")
    assert len(listed) == len(set(listed)), "a GET line is listed twice"
    assert listed == _get_only_routes()


def test_every_raised_status_is_documented():
    documented = {int(c) for c in _STATUS_LINE_RE.findall(_docstring())}
    missing = sorted(_raised_statuses() - documented)
    assert missing == [], f"statuses raised in server.py but undocumented: {missing}"


def test_host_gate_status_is_documented():
    # 421 comes from the shared HostAllowlistMixin (core/http_host_gate.py),
    # not a literal in this file, so it is pinned by name.
    assert 421 in {int(c) for c in _STATUS_LINE_RE.findall(_docstring())}

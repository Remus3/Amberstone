"""RM-1283: the DS index page (GET /) lists every dispatched route.

The ``_INDEX_HTML`` route table is the only self-describing surface :8860
serves, and it is hand-authored beside the ``_POST_ROUTES`` dispatch dict, so
a route added to one and not the other drifts silently. Measured at ENGINE
1.290.0: 29 of the 31 ``_POST_ROUTES`` keys had a ``POST`` row, and the two
DS V2 unified routes ``/v2/fight-report`` and ``/v2/matchup`` had none.

Both tables are read STRUCTURALLY from the source with ``ast`` (importing
server.py drags in the whole engine), and the HTML rows are matched as whole
``<tr><td>METHOD</td><td>PATH`` cells, never as a substring of the page, so
``/rank`` cannot be satisfied by ``/rank-tank``.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_SERVER = Path(__file__).resolve().parents[1] / "server.py"

_ROW_RE = re.compile(
    r"<tr><td>(GET|POST)</td><td>(?:<a href=[^>]*>)?(/[^<]*)(?:</a>)?</td>"
)


def _module_assign(name: str) -> ast.expr:
    tree = ast.parse(_SERVER.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return node.value
    raise AssertionError(f"{name} not found at module level in server.py")


def _post_routes() -> list[str]:
    value = _module_assign("_POST_ROUTES")
    assert isinstance(value, ast.Dict), "_POST_ROUTES is not a dict literal"
    keys = [k.value for k in value.keys if isinstance(k, ast.Constant)]
    assert len(keys) == len(value.keys), "a _POST_ROUTES key is not a literal"
    return keys


def _index_rows() -> list[tuple[str, str]]:
    value = _module_assign("_INDEX_HTML")
    assert isinstance(value, ast.Constant) and isinstance(value.value, str)
    return _ROW_RE.findall(value.value)


def test_enumerations_are_not_empty():
    # An empty walk would pass every subset assertion below vacuously.
    assert len(_post_routes()) >= 31
    assert len(_index_rows()) >= 31


def test_every_post_route_has_a_post_row():
    posted = {path for method, path in _index_rows() if method == "POST"}
    missing = [r for r in _post_routes() if r not in posted]
    assert missing == [], f"_POST_ROUTES keys with no POST row on GET /: {missing}"


def test_every_post_row_is_a_real_route():
    routes = set(_post_routes())
    extra = [p for m, p in _index_rows() if m == "POST" and p not in routes]
    assert extra == [], f"POST rows on GET / that dispatch nowhere: {extra}"


def test_post_rows_follow_dispatch_order_and_are_unique():
    posted = [p for m, p in _index_rows() if m == "POST"]
    assert len(posted) == len(set(posted)), "a POST row is listed twice"
    assert posted == _post_routes()


def test_v2_routes_are_listed():
    posted = {p for m, p in _index_rows() if m == "POST"}
    assert {"/v2/fight-report", "/v2/matchup"} <= posted

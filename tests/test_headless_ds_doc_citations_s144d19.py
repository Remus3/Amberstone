"""Guard (RM-994): the DS lane doc cites code by SYMBOL, and each symbol is real.

``tools/headless-ds.md`` is the prompt every DS lane worker runs. Its probe
traps and CLOSED set cited code by line number: ``server.py:2573`` for the
``/rank`` -> ``_route_rank`` mapping, six more route-table line numbers, and
``daemon_slayer_extract.py:1108`` for the ``--force`` flag. At HEAD the route
table sits near line 3026 and the flag near 2051, so every one pointed at
unrelated code. Section 7 also named ``build_orders/16.15.1/`` as the live
precompute dir after the patch had moved on, and section 3 recited a DS
test-module count the doc itself says must be measured, never written.

The checks below fail on a re-introduced ``<file>.py:<n>`` citation or a
patch-pinned build_orders path, and re-derive each symbol the doc names from
the source (``ast``, no server import), so a renamed route or flag fails here
instead of rotting. ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "tools" / "headless-ds.md"
_SERVER = _REPO_ROOT / "agents" / "daemon_slayer" / "server.py"
_EXTRACT = _REPO_ROOT / "tools" / "daemon_slayer_extract.py"

_ARCHETYPE_ROUTES = (
    "/rank-tank", "/rank-bruiser", "/rank-mage",
    "/rank-onhit", "/rank-assassin", "/rank-enchanter",
)


def _doc() -> str:
    return _DOC.read_text(encoding="utf-8")


def _post_routes() -> dict[str, str]:
    tree = ast.parse(_SERVER.read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_POST_ROUTES"
                        for t in node.targets)
                and isinstance(node.value, ast.Dict)):
            return {
                k.value: v.id
                for k, v in zip(node.value.keys, node.value.values)
                if isinstance(k, ast.Constant) and isinstance(v, ast.Name)
            }
    raise AssertionError("server.py has no module-level _POST_ROUTES dict")


def test_doc_cites_no_python_line_numbers():
    hits = re.findall(r"[\w/]+\.py:\d+", _doc())
    assert hits == [], f"line-number citations rot; cite the symbol: {hits}"


def test_doc_names_no_patch_pinned_build_orders_dir():
    hits = re.findall(r"build_orders/\d+\.\d+\.\d+/", _doc())
    assert hits == [], f"name the current.txt patch, not a literal: {hits}"


def test_doc_recites_no_ds_test_module_count():
    assert not re.search(r"\d+\s+test modules", _doc())


def test_doc_points_at_the_route_table_by_name():
    assert "_POST_ROUTES" in _doc()


def test_rank_route_is_route_rank():
    assert _post_routes()["/rank"] == "_route_rank"


@pytest.mark.parametrize("route", _ARCHETYPE_ROUTES)
def test_named_archetype_route_exists(route):
    assert f"`{route}`" in _doc()
    assert route in _post_routes()


def test_rank_hybrid_still_absent():
    assert "`/rank-hybrid` does not exist" in _doc()
    assert "/rank-hybrid" not in _post_routes()


def test_extract_force_flag_and_docstring_still_exist():
    src = _EXTRACT.read_text(encoding="utf-8")
    assert 'add_argument("--force"' in src
    docstring = ast.get_docstring(ast.parse(src)) or ""
    assert "--force" in docstring

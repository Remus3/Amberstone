"""Guard: the RM-200 scaling-HSP route-seam test cites by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The module docstring of
``agents/daemon_slayer/tests/test_scaling_hsp_route_seam_rm200.py`` carried
five line cites, written 2026-08-15 (1bade3596). Four had rotted at HEAD:
- ``ehp.py:1951`` (the ``sum_wielder_hsp_pct`` call in ``compute_ehp``) now
  sits at 1986.
- ``sustain.py:382`` (the same call in ``compute_sustain``) now sits at 390.
- ``server.py:656`` (the /ehp ``items`` parse in ``_route_ehp``) now sits at
  751; line 656 is an RM-86 comment in another route.
- ``server.py:2115`` (the /sustain ``items`` parse in ``_route_sustain``) now
  sits at 2315; line 2115 is a burst-route call.
The fifth, ``_hsp_amp.py:26`` (the keyword-only flag), was still true but
is pinned by symbol here with the rest.

The tests below pin the claims by symbol instead.
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from agents.daemon_slayer import _hsp_amp

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = DS / "tests" / "test_scaling_hsp_route_seam_rm200.py"
_LINE_CITE = re.compile(r"(?<![\w.])(?:_hsp_amp|ehp|sustain|server)\.py:\d")
_FLAG = "assume_scaling_hsp_grants"


def _target() -> str:
    return TARGET.read_text(encoding="utf-8")


def _func(module: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((DS / module).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{module} has no def {name}")


def _gated_helper_calls(func: ast.FunctionDef) -> list[bool]:
    """One entry per ``sum_wielder_hsp_pct`` call: True when it forwards the
    flag by name AND sits in the TRUE branch of an ``assume_hsp_amp`` test."""
    out = []

    def visit(node: ast.AST, gated: bool) -> None:
        if isinstance(node, (ast.If, ast.IfExp)):
            test = node.test
            terms = (
                test.values
                if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And)
                else [test]
            )
            arms = any(
                isinstance(t, ast.Name) and t.id == "assume_hsp_amp" for t in terms
            )
            visit(test, gated)
            body = node.body if isinstance(node.body, list) else [node.body]
            orelse = node.orelse if isinstance(node.orelse, list) else [node.orelse]
            for child in body:
                visit(child, gated or arms)
            for child in orelse:
                visit(child, gated)
            return
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "sum_wielder_hsp_pct"
        ):
            forwards = any(
                kw.arg == _FLAG and isinstance(kw.value, ast.Name)
                and kw.value.id == _FLAG
                for kw in node.keywords
            )
            out.append(forwards and gated)
        for child in ast.iter_child_nodes(node):
            visit(child, gated)

    visit(func, False)
    return out


def test_pattern_matches_the_rotted_shape():
    for sample in (
        "at R197 (``_hsp_amp.py:26``)",
        "``ehp.py:1951`` and ``sustain.py:382``",
        "(``server.py:656`` for /ehp",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "``server._route_ehp``",
        "a rune_ehp.py:12 cite is not this pattern",
        "a test_ehp.py:9 cite is not this pattern",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(_target().splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_target_names_the_symbols():
    text = " ".join(_target().split())
    assert "``ehp.compute_ehp`` and ``sustain.compute_sustain``" in text
    assert "(``server._route_ehp`` for /ehp, ``server._route_sustain``" in text


def test_helper_flag_is_keyword_only_default_off():
    param = inspect.signature(_hsp_amp.sum_wielder_hsp_pct).parameters[_FLAG]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is False


def test_both_owners_forward_the_flag_inside_the_flat_lane():
    for module, name in (("ehp.py", "compute_ehp"), ("sustain.py", "compute_sustain")):
        calls = _gated_helper_calls(_func(module, name))
        assert calls, f"{name} no longer calls sum_wielder_hsp_pct"
        assert all(calls), (name, calls)


def test_both_routes_carry_items_and_parse_the_flag():
    for name in ("_route_ehp", "_route_sustain"):
        src = ast.unparse(_func("server.py", name))
        assert "_coerce_str_list(body.get('items'), 'items')" in src, name
        assert f"_opt_bool(body, '{_FLAG}', False)" in src, name
        assert f"{_FLAG}={_FLAG}" in src, name

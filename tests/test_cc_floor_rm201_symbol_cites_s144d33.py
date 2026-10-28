"""Guard: the RM-201 CC-floor route-seam test cites by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The module docstring of
``agents/daemon_slayer/tests/test_cc_floor_route_seam_rm201.py`` (written
2026-08-15, 03a51f54e) and one assertion message carried twelve line cites.
Eight had rotted at HEAD:
- ``ehp.py:2525`` (the ``compute_cc_pressure`` call in ``compute_ehp``,
  cited four times, once in the assertion message) now sits at 2569.
- ``dashboard/routes_cc_conditional_pressure.py`` ``(:207)`` (the call in
  ``_side_conditional``) now sits at 209.
- ``server.py:661`` (the /ehp ``enemies`` parse in ``_route_ehp``) now sits
  at 756, and ``server.py:661-662`` (``enemies`` + ``include_conditional``)
  at 756-757.
- ``server.py:826`` (the ``enemy_champions=enemies`` forward) now sits at 975.
The other four (``cc_pressure.py:237`` and the ``(:101)`` / ``(:137)`` /
``(:185)`` caller cites) were still true, but are pinned by symbol here with
the rest.

The tests below pin the claims by symbol instead.
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

from agents.daemon_slayer import cc_pressure

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = DS / "tests" / "test_cc_floor_route_seam_rm201.py"
_LINE_CITE = re.compile(
    r"(?<![\w.])(?:cc_pressure|ehp|server)\.py:\d|\(:\d+\)"
)
_CALLERS = (
    ("agents/daemon_slayer/ehp.py", "ehp.compute_ehp", "compute_ehp"),
    (
        "core/cc_blended_ehp_context.py",
        "core/cc_blended_ehp_context.cc_blended_ehp_impact_line",
        "cc_blended_ehp_impact_line",
    ),
    (
        "core/cc_conditional_impact_context.py",
        "core/cc_conditional_impact_context.cc_conditional_impact_line",
        "cc_conditional_impact_line",
    ),
    (
        "core/enemy_cc_threat_context.py",
        "core/enemy_cc_threat_context.enemy_cc_threat_line",
        "enemy_cc_threat_line",
    ),
    (
        "dashboard/routes_cc_conditional_pressure.py",
        "dashboard/routes_cc_conditional_pressure._side_conditional",
        "_side_conditional",
    ),
)


def _target() -> str:
    return TARGET.read_text(encoding="utf-8")


def _func(path: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((REPO / path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path} has no top-level def {name}")


def _cc_calls(func: ast.FunctionDef) -> list[ast.Call]:
    return [
        node for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "compute_cc_pressure"
    ]


def test_pattern_matches_the_rotted_shape():
    for sample in (
        "since ENGINE 1.150.0 (cc_pressure.py:237).",
        "``ehp.compute_ehp``     (ehp.py:2525)",
        "``core/cc_blended_ehp_context.py``     (:101)",
        "reads ``enemies`` (server.py:661) and",
        "already parsed both (server.py:661-662).",
        '"ehp.py:2525 did not run - the /ehp cc block',
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "``server._route_ehp``",
        "no live :8860, no sockets",
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


def test_target_names_every_caller_by_symbol():
    text = _target()
    for _path, symbol, _name in _CALLERS:
        assert f"* ``{symbol}``" in text, symbol


def test_every_named_caller_calls_compute_cc_pressure():
    for path, symbol, name in _CALLERS:
        assert _cc_calls(_func(path, name)), symbol


def test_floor_flag_is_keyword_only_default_off():
    params = inspect.signature(cc_pressure.compute_cc_pressure).parameters
    for flag in ("include_conditional", "apply_cc_floor"):
        assert params[flag].kind is inspect.Parameter.KEYWORD_ONLY, flag
        assert params[flag].default is False, flag


def test_compute_ehp_forwards_both_flags_by_name():
    calls = _cc_calls(_func("agents/daemon_slayer/ehp.py", "compute_ehp"))
    assert len(calls) == 1, len(calls)
    kws = {
        kw.arg: kw.value.id
        for kw in calls[0].keywords
        if isinstance(kw.value, ast.Name)
    }
    assert kws.get("include_conditional") == "include_conditional", kws
    assert kws.get("apply_cc_floor") == "apply_cc_floor", kws


def test_route_ehp_parses_both_transport_keys_and_forwards():
    src = ast.unparse(_func("agents/daemon_slayer/server.py", "_route_ehp"))
    assert "_coerce_str_list(body.get('enemies'), 'enemies')" in src
    assert "_opt_bool(body, 'include_conditional', False)" in src
    assert "_opt_bool(body, 'apply_cc_floor', False)" in src
    for fwd in (
        "enemy_champions=enemies",
        "include_conditional=include_conditional",
        "apply_cc_floor=apply_cc_floor",
    ):
        assert fwd in src, fwd

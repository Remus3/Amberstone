"""Guard: DS-adjacent client modules cite the engine by symbol, not by line (RM-1053).

Measured 2026-10-31 at ENGINE 1.290.0. Four DS-adjacent modules and three of
their test files still cited code as ``<file>.py:<n>`` (plus one bare
``(:1458, :1540)`` pair), and six of the nine cites had drifted:

- ``core/build_order_precompute.py`` (x3), ``tests/test_build_order_archetype_provenance.py``:
  ``core/build_order.py:594`` for the archetype normalization. Still right at
  HEAD by luck; now ``plan_build_order``'s ``arch = ...`` line.
- ``core/build_order_precompute.py``, ``tests/test_build_order_starter_tier_guard.py``:
  ``agents/daemon_slayer/rank.py:687`` for ``_filter_candidates`` (def near 741).
- ``core/build_order.py``, ``tests/test_build_order_score_by_plumb.py``:
  ``server.py:639-643`` for the /rank-tank ``score_by`` parse (now in
  ``_route_rank_tank``, near 1076), and ``(:1458, :1540)`` for
  ``rank_for_primary_archetype`` (def near 2960).
- ``tools/daemon_slayer_build_orders_generate.py``: ``core/build_order.py:571-576``
  for the ``score_by`` fallback (now ``score_by_resolved``, near 601).
- ``core/daemon_slayer_client.py``: ``routes_ds_profile.py:204`` (205),
  ``ds_capability_gap.py:164`` and ``laning_verdicts.py:295`` (296),
  ``routes_ds_matchup.py:170`` (172) for the live ``compute_sustain`` /
  ``matchup`` callers.

The tests below pin the symbol cites, re-derive every restated claim by AST,
and ratchet the seven files to zero line cites.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

_PY_LINE = re.compile(r"(?<![\w./])[\w/]+\.py:\d")
_BARE_COLON = re.compile(r"\(:\d{3,}")

TARGETS = {
    "core/build_order_precompute.py": (
        "``plan_build_order`` in ``core/build_order.py``",
        "``_filter_candidates`` in",
        "``plan_build_order`` (``core/build_order.py``) does",
        "plan_build_order (core/build_order.py) normalizes",
    ),
    "core/daemon_slayer_client.py": (
        "``_compute_results`` in ``dashboard/routes_ds_profile.py``",
        "``_detect_sustain_gap`` in ``core/ds_capability_gap.py``",
        "``laning_choices`` in ``core/laning_verdicts.py`` and ``_compute`` in",
    ),
    "core/build_order.py": ("``_route_rank_tank`` in server.py",),
    "tools/daemon_slayer_build_orders_generate.py": (
        "``score_by_resolved`` fallback",
    ),
    "tests/test_build_order_archetype_provenance.py": (
        "(``plan_build_order`` in",
    ),
    "tests/test_build_order_score_by_plumb.py": (
        "``_route_rank_tank`` in server.py",
        "``score_by`` parameter, passed on to ``rank_tank_for``",
    ),
    "tests/test_build_order_starter_tier_guard.py": (
        "``_filter_candidates`` in",
    ),
}


def _tree(rel: str) -> ast.Module:
    return ast.parse((REPO / rel).read_text(encoding="utf-8"))


def _func(rel: str, name: str) -> ast.FunctionDef:
    for node in _tree(rel).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not defined at top level of {rel}")


def _called_names(func: ast.AST) -> set[str]:
    out = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def _assigns(func: ast.AST, name: str) -> list[ast.expr]:
    out = []
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    out.append(node.value)
    return out


def test_patterns_match_the_rotted_shapes():
    for sample in (
        "(``core/build_order.py:594``)",
        "(agents/daemon_slayer/rank.py:687",
        "(server.py:639-643)",
        "``dashboard/routes_ds_matchup.py:170``.",
    ):
        assert _PY_LINE.search(sample), sample
    assert _BARE_COLON.search("``rank_for_primary_archetype`` (:1458, :1540)")
    for sample in ("test_x.py::TestY", "``core.build_order``", "1%:2%", "(:12)"):
        assert not _PY_LINE.search(sample), sample
        assert not _BARE_COLON.search(sample), sample


@pytest.mark.parametrize("rel", sorted(TARGETS))
def test_targets_cite_by_symbol(rel):
    text = (REPO / rel).read_text(encoding="utf-8")
    hits = [
        i for i, line in enumerate(text.splitlines(), 1)
        if _PY_LINE.search(line) or _BARE_COLON.search(line)
    ]
    assert hits == [], (rel, hits)
    for needle in TARGETS[rel]:
        assert needle in text, (rel, needle)


def test_plan_build_order_normalizes_and_stores_the_archetype():
    func = _func("core/build_order.py", "plan_build_order")
    (arch,) = _assigns(func, "arch")
    assert ast.unparse(arch) == "(archetype or 'carry').strip().lower() or 'carry'"
    stored = [
        kw for node in ast.walk(func) if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "archetype" and isinstance(kw.value, ast.Name)
        and kw.value.id == "arch"
    ]
    assert stored, "plan_build_order never passes archetype=arch"


def test_plan_build_order_resolves_unknown_score_by_to_the_default():
    func = _func("core/build_order.py", "plan_build_order")
    values = [ast.unparse(v) for v in _assigns(func, "score_by_resolved")]
    assert "str(score_by or SCORE_BY_DEFAULT)" in values
    assert "SCORE_BY_DEFAULT" in values


def test_rank_tank_route_parses_score_by():
    func = _func("agents/daemon_slayer/server.py", "_route_rank_tank")
    parsed = [
        node for node in ast.walk(func)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "_opt_str" and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "score_by"
    ]
    assert parsed


def test_filter_candidates_is_the_rank_pool_filter():
    _func("agents/daemon_slayer/rank.py", "_filter_candidates")


def test_rank_for_primary_archetype_forwards_score_by_to_the_tank_ranker():
    func = _func("core/daemon_slayer_client.py", "rank_for_primary_archetype")
    assert "score_by" in [a.arg for a in func.args.args + func.args.kwonlyargs]
    forwarded = [
        node for node in ast.walk(func)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "rank_tank_for"
        and any(kw.arg == "score_by" for kw in node.keywords)
    ]
    assert forwarded


@pytest.mark.parametrize(
    "rel,func,callee",
    [
        ("dashboard/routes_ds_profile.py", "_compute_results", "compute_sustain"),
        ("core/ds_capability_gap.py", "_detect_sustain_gap", "compute_sustain"),
        ("core/laning_verdicts.py", "laning_choices", "matchup"),
        ("dashboard/routes_ds_matchup.py", "_compute", "matchup"),
    ],
)
def test_named_live_callers_call_the_cited_compute(rel, func, callee):
    assert callee in _called_names(_func(rel, func))

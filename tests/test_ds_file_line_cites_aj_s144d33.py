"""Guard: the SLICE A seam-forwarding test cites by symbol (RM-1053).

Measured 2026-10-31 at ENGINE 1.290.0. tests/test_seam_forwarding_slice_a.py
(51e6dd0cf, 2026-07-25) carried ten ``<file>.py:<n>`` cites plus one prose
"lines 279-299" cite into core/build_order.py, core/daemon_slayer_client.py,
coach_integration/archetype_dispatch.py and three test files. The production
cites had all drifted:

- ``core/build_order.py:574`` / ``:574-575`` for the AD/AP-aware boots pick
  and its 0.5 / 0.5 default (now the ``_select_boots`` call inside
  ``plan_build_order``, near 677-683) and ``:618`` for the
  ``filter_shared_uniques`` re-pin (near 728).
- ``core/daemon_slayer_client.py:1399-1411`` / ``:1410`` for the
  ``rank_for_primary_archetype`` seam flags and the
  ``apply_squishy_burst_target`` default (near 2962-3012), and ``:329-330``
  for the two ``score_by`` values. That pair is the route's closed set,
  ``_DS_PREVIEW_SCORE_BY_VALUES`` in dashboard/routes_state.py; the engine's
  ``_route_rank_tank`` has since grown "cc_blended" and "sustain" (R194),
  so the prose says so.
- ``coach_integration/archetype_dispatch.py:282-299`` and "lines 279-299" for
  the ``if flag: seams[...] = True`` idiom (now ``dispatch_for_coach``'s
  ``seams`` dict, near 312-330).

Only the three test-file cites (``test_routes_ds_preview_scorer.py:21``,
``test_build_order.py:419``, ``test_ds_preview_e2e_p1l21.py:191``) still
landed; they cite by symbol now too, so the file ratchets to zero. The change
is comment and docstring only. The tests below ratchet the file, pin the
symbol cites and re-derive every restated claim by AST.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = "tests/test_seam_forwarding_slice_a.py"

_PY_LINE = re.compile(r"(?<![\w./])[\w/]+\.py:\d")
_PROSE_LINE = re.compile(r"\blines? ~?\d{2,}")

NEEDLES = (
    "flat ranking (its ``seams`` dict)",
    "the ``_select_boots`` call inside\n``core.build_order.plan_build_order``",
    "(its keyword-only seam flags in core/daemon_slayer_client.py)",
    "``_DS_PREVIEW_SCORE_BY_VALUES`` in\n    dashboard/routes_state.py",
    "the ``seams`` dict in ``dispatch_for_coach``",
    '``extra.get("enemy_ad_share", 0.5)``',
    "``test_routes_state_has_no_in_process_engine_import``",
    "the ``_Handler`` of tests/test_routes_ds_preview_scorer.py",
    "``_Stats`` in tests/test_build_order.py",
    "the ``rank_for_primary_archetype`` default in\n# core/daemon_slayer_client.py",
    '``call_kwargs["filter_shared_uniques"] = True`` AFTER',
)


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _tree(rel: str) -> ast.Module:
    return ast.parse(_text(rel))


def _top(rel: str, name: str) -> ast.AST:
    for node in _tree(rel).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not defined at top level of {rel}")


def _top_tuple(rel: str, name: str) -> tuple:
    for node in _tree(rel).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not assigned at top level of {rel}")


def _kw_defaults(func: ast.FunctionDef) -> dict:
    out = dict(zip([a.arg for a in func.args.kwonlyargs], func.args.kw_defaults))
    pos = func.args.args
    out.update(zip([a.arg for a in pos[len(pos) - len(func.args.defaults):]],
                   func.args.defaults))
    return out


def _calls_named(func: ast.AST, name: str) -> list[ast.Call]:
    return [
        n for n in ast.walk(func)
        if isinstance(n, ast.Call) and ast.unparse(n.func) == name
    ]


def test_patterns_match_the_rotted_shapes():
    for sample in (
        "(core/daemon_slayer_client.py:1399-1411).",
        "at ``core/build_order.py:574``.",
        "already used at coach_integration/archetype_dispatch.py:282-299.",
        "# Handler stub mirrors tests/test_routes_ds_preview_scorer.py:21.",
    ):
        assert _PY_LINE.search(sample), sample
    assert _PROSE_LINE.search("the flat ranking (lines 279-299) but")
    for sample in (
        "test_x.py::TestY",
        "``core.build_order``",
        "level=11, item_ids=[]",
        "two lines of setup",
    ):
        assert not _PY_LINE.search(sample), sample
        assert not _PROSE_LINE.search(sample), sample


def test_target_cites_by_symbol():
    text = _text(TARGET)
    hits = [
        i for i, line in enumerate(text.splitlines(), 1)
        if _PY_LINE.search(line) or _PROSE_LINE.search(line)
    ]
    assert hits == [], hits
    assert len(NEEDLES) == 11
    for needle in NEEDLES:
        assert needle in text, needle


def test_route_seam_keys_are_client_parameter_names():
    # "Body key names ... are EXACTLY the rank_for_primary_archetype
    # parameter names."
    rel = "dashboard/routes_state.py"
    keys = (
        _top_tuple(rel, "_DS_PREVIEW_SEAM_BOOLS")
        + _top_tuple(rel, "_DS_PREVIEW_SEAM_FLOATS")
        + _top_tuple(rel, "_DS_PREVIEW_SEAM_TRISTATE")
        + ("score_by",)
    )
    assert len(keys) == 13
    params = _kw_defaults(_top("core/daemon_slayer_client.py",
                               "rank_for_primary_archetype"))
    assert set(keys) <= set(params), sorted(set(keys) - set(params))


def test_score_by_values_and_client_defaults():
    rel = "dashboard/routes_state.py"
    assert _top_tuple(rel, "_DS_PREVIEW_SCORE_BY_VALUES") == (
        "blended", "team_blended")
    client = "core/daemon_slayer_client.py"
    rfpa = _kw_defaults(_top(client, "rank_for_primary_archetype"))
    assert ast.literal_eval(rfpa["score_by"]) == "blended"
    squishy = rfpa["apply_squishy_burst_target"]
    assert isinstance(squishy, ast.Constant) and squishy.value is True
    route = _top("agents/daemon_slayer/server.py", "_route_rank_tank")
    allow = [
        ast.literal_eval(n.comparators[0]) for n in ast.walk(route)
        if isinstance(n, ast.Compare) and ast.unparse(n.left) == "score_by"
        and isinstance(n.ops[0], ast.NotIn)
    ]
    assert allow == [("blended", "cc_blended", "team_blended", "sustain")]


def test_dispatch_seams_idiom():
    func = _top("coach_integration/archetype_dispatch.py", "dispatch_for_coach")
    forwarded = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Name):
            continue
        for stmt in node.body:
            if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                    and ast.unparse(stmt.targets[0]) == f"seams['{node.test.id}']"
                    and isinstance(stmt.value, ast.Constant)
                    and stmt.value.value is True):
                forwarded.add(node.test.id)
    assert {"exempt_offclass_by_win", "prefer_kit_axis_by_win",
            "widen_carry_pool"} <= forwarded, sorted(forwarded)


def test_plan_build_order_boots_and_repin():
    func = _top("core/build_order.py", "plan_build_order")
    boots = _calls_named(func, "_select_boots")
    assert len(boots) == 1
    kw = {k.arg: ast.unparse(k.value) for k in boots[0].keywords}
    assert kw["enemy_ad_share"] == "float(extra.get('enemy_ad_share', 0.5))"
    assert kw["enemy_ap_share"] == "float(extra.get('enemy_ap_share', 0.5))"
    repins = [
        n for n in ast.walk(func) if isinstance(n, ast.Assign)
        and ast.unparse(n.targets[0]) == "call_kwargs['filter_shared_uniques']"
        and isinstance(n.value, ast.Constant) and n.value.value is True
    ]
    assert len(repins) == 1
    splats = [
        n for n in ast.walk(func) if isinstance(n, ast.Call)
        and ast.unparse(n.func) == "call_kwargs.update"
        and [ast.unparse(a) for a in n.args] == ["extra"]
    ]
    assert splats, "call_kwargs.update(extra) not found"
    assert all(s.lineno < repins[0].lineno for s in splats)


def test_test_file_symbols():
    _top("tests/test_routes_ds_preview_scorer.py", "_Handler")
    _top("tests/test_build_order.py", "_Stats")
    guard = _top("tests/test_ds_preview_e2e_p1l21.py", "TestNoEngineSplitBrain")
    names = {n.name for n in guard.body if isinstance(n, ast.FunctionDef)}
    assert "test_routes_state_has_no_in_process_engine_import" in names

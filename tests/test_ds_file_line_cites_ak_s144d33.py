"""Guard: six DS-adjacent test files cite by symbol (RM-1053).

Measured 2026-10-31 at ENGINE 1.290.0. Six test files carried fourteen
``<file>.py:<n>`` cites (plus two bare ``:<a>-<b>`` partners) into the DS
client, the build planner, the build-order modules and the relscore route,
and most had drifted:

- tests/test_ds_unpaired_enemy_share.py: ``daemon_slayer_client.py:279`` for
  the "pair sums to <= 1.0" rule (now a psutil helper; the rule lives in the
  ``rank_tank_for`` docstring and ``_resolve_enemy_shares``).
- tests/test_planner_beam_search.py: ``rank.py:244-303`` (``RankedItem`` is
  near 516), ``routes_state.py:592-597`` (the row projection is in
  ``_serve_ds_preview_post``, near 1175), ``test_ds_preview_e2e_p1l21.py:
  191-205`` twice, and ``core/build_order.py:34-48, 6 families``. The engine
  has nine families, and the family-literal ban listed seven: last_whisper
  and void_pen were never scanned for. The ban is now derived from
  ``ITEM_EFFECTS``, and the engine-import scan covers every
  core/build_planner module, not four of ten.
- tests/test_replan_kept_items_rm483.py: planner.py / replan.py / is_kept
  line ranges and ``core/build_order.py:34-48``.
- tests/test_build_order_precompute.py: ``build_order_precompute.py:472``
  (``load_build_order_precompute`` is near 722).
- tests/test_routes_ds_relscore.py and
  tests/test_routes_ds_relscore_full_build.py: ``routes_ds_relscore.py:195``
  / ``:253``, ``daemon_slayer_resolver.py:144-151`` and
  ``_liveclient.py:191`` (the last is history: that list is filtered now).

The tests below ratchet the six files to zero line cites, pin the symbol
cites, and re-derive every restated claim by AST.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_PY_LINE = re.compile(r"(?<![\w./])[\w/]+\.py:\s?\d")
_PROSE_LINE = re.compile(r"\blines? ~?\d{2,}")
_BARE_PARTNER = re.compile(r"(?<![\w/.])\s:\d{2,}")

NEEDLES = {
    "tests/test_ds_unpaired_enemy_share.py": (
        "documented in the ``rank_tank_for``\ndocstring and in "
        "``_resolve_enemy_shares``, core/daemon_slayer_client.py",
    ),
    "tests/test_planner_beam_search.py": (
        "(``RankedItem`` in agents/daemon_slayer/rank.py)",
        "``_serve_ds_preview_post`` (dashboard/routes_state.py)",
        "``TestNoEngineSplitBrain.test_routes_state_has_no_in_process_"
        "engine_import``\n     in tests/test_ds_preview_e2e_p1l21.py",
        "# TestNoEngineSplitBrain.test_routes_state_has_no_in_process_"
        "engine_import\n        # in tests/test_ds_preview_e2e_p1l21.py",
        "the family count is re-derived by",
        "banned = self._banned_families()",
    ),
    "tests/test_replan_kept_items_rm483.py": (
        "normalized by ``_resolve_forced``) already",
        "\"re-plan the remaining build\" call in\n"
        "core/build_planner/replan.py at a18bdb66a",
        "(``ItemOverrideStore.is_kept``)",
        "the \"No-double rule is\nengine-authoritative\" paragraph",
    ),
    "tests/test_build_order_precompute.py": (
        "(`load_build_order_precompute` in\n    "
        "core/build_order_precompute.py)",
    ),
    "tests/test_routes_ds_relscore.py": (
        "(``_compute`` in dashboard/routes_ds_relscore.py)",
    ),
    "tests/test_routes_ds_relscore_full_build.py": (
        "``log.warning(\"api/ds-relscore compute: %s\",\nexc)`` in "
        "``_serve_ds_relscore``",
        "``_NON_INVENTORY_BASE_IDS`` in core/daemon_slayer_resolver.py",
        "``dashboard._liveclient.liveclient_summary`` applied no filter",
    ),
}


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _tree(rel: str) -> ast.Module:
    return ast.parse(_text(rel))


def _top(rel: str, name: str) -> ast.AST:
    for node in _tree(rel).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not defined at top level of {rel}")


def _method(cls: ast.ClassDef, name: str) -> ast.FunctionDef:
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{cls.name}.{name} not defined")


def _calls_named(func: ast.AST, name: str) -> list[ast.Call]:
    return [
        n for n in ast.walk(func)
        if isinstance(n, ast.Call) and ast.unparse(n.func) == name
    ]


def test_patterns_match_the_rotted_shapes():
    for sample in (
        "``daemon_slayer_client.py:279``), so",
        "(rank.py:244-303) so the planner",
        "tests/test_ds_preview_e2e_p1l21.py:191-205) - DS",
        "(core/build_order.py:34-48,",
        "test_build_order_precompute.py: 59",
    ):
        assert _PY_LINE.search(sample), sample
    assert _BARE_PARTNER.search("``ItemOverrideStore.is_kept`` :298-300)")
    assert _BARE_PARTNER.search("``_resolve_forced`` :189-222) already")
    for sample in (
        "test_x.py::TestY",
        "``core.build_order``",
        "a {ranked[], order[]} shape",
        "ENGINE 1.290.0",
        "beam_width=6, depth=4",
    ):
        assert not _PY_LINE.search(sample), sample
        assert not _PROSE_LINE.search(sample), sample
        assert not _BARE_PARTNER.search(sample), sample


def test_targets_cite_by_symbol():
    assert len(NEEDLES) == 6
    for rel, needles in NEEDLES.items():
        text = _text(rel)
        hits = [
            i for i, line in enumerate(text.splitlines(), 1)
            if _PY_LINE.search(line) or _PROSE_LINE.search(line)
            or _BARE_PARTNER.search(line)
        ]
        assert hits == [], (rel, hits)
        for needle in needles:
            assert needle in text, (rel, needle)


def test_share_pair_rule_is_where_cited():
    client = "core/daemon_slayer_client.py"
    tank_doc = ast.get_docstring(_top(client, "rank_tank_for")) or ""
    assert "summing to <= 1.0" in tank_doc
    resolve_doc = ast.get_docstring(_top(client, "_resolve_enemy_shares")) or ""
    assert "sum to <= 1.0" in resolve_doc


def test_ranked_item_and_route_projection():
    ranked = _top("agents/daemon_slayer/rank.py", "RankedItem")
    fields = {
        n.target.id for n in ranked.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    }
    assert {"item_id", "item_name", "gold", "delta_dps", "is_terminal",
            "unique_passive_key"} <= fields
    route = _top("dashboard/routes_state.py", "_serve_ds_preview_post")
    projections = [
        {ast.literal_eval(k) for k in n.keys if k is not None}
        for n in ast.walk(route)
        if isinstance(n, ast.Dict) and n.keys
        and all(isinstance(k, ast.Constant) for k in n.keys)
        and "unique_passive_key" in {ast.literal_eval(k) for k in n.keys}
    ]
    assert len(projections) == 1, projections
    assert "unique_passive_key" in projections[0]
    # "drops some of these"
    assert "is_terminal" not in projections[0]
    assert fields - projections[0]


def test_split_brain_guard_symbol():
    cls = _top("tests/test_ds_preview_e2e_p1l21.py", "TestNoEngineSplitBrain")
    _method(cls, "test_routes_state_has_no_in_process_engine_import")


def test_build_order_docstring_paragraph():
    doc = ast.get_docstring(_tree("core/build_order.py")) or ""
    assert "No-double rule is engine-authoritative" in doc
    func = _top("core/build_order.py", "plan_build_order")
    pins = [
        n for n in ast.walk(func) if isinstance(n, ast.Assign)
        and ast.unparse(n.targets[0]) == "call_kwargs['filter_shared_uniques']"
    ]
    assert pins


def test_planner_family_ban_is_engine_derived():
    cls = _top("tests/test_planner_beam_search.py", "StructuralGuardTests")
    helper = _method(cls, "_engine_families")
    assert any(
        isinstance(n, ast.ImportFrom)
        and n.module == "agents.daemon_slayer.effects"
        and [a.name for a in n.names] == ["ITEM_EFFECTS"]
        for n in ast.walk(helper)
    )
    scan = _method(cls, "test_no_unique_family_literal_in_source")
    assert _calls_named(scan, "self._banned_families")
    imports = _method(cls, "test_no_in_process_engine_import")
    assert "glob('*.py')" in ast.unparse(imports)
    _method(cls, "test_family_ban_covers_every_engine_family")


def test_replan_symbols():
    planner = "core/build_planner/planner.py"
    plan_build = _top(planner, "plan_build")
    params = {a.arg for a in plan_build.args.args + plan_build.args.kwonlyargs}
    assert "forced_item_ids" in params
    _top(planner, "_resolve_forced")
    replan = "core/build_planner/replan.py"
    _method(_top(replan, "ItemOverrideStore"), "is_kept")
    tick = _method(_top(replan, "ReplanLoop"), "tick")
    calls = _calls_named(tick, "plan_build")
    assert calls and all(
        "forced_item_ids" in {k.arg for k in c.keywords} for c in calls)


def test_precompute_loader_is_fail_soft():
    func = _top("core/build_order_precompute.py", "load_build_order_precompute")
    soft = [
        h for h in ast.walk(func) if isinstance(h, ast.ExceptHandler)
        and any(isinstance(s, ast.Return) and isinstance(s.value, ast.Dict)
                and not s.value.keys for s in h.body)
    ]
    assert len(soft) >= 2


def test_relscore_symbols():
    rel = "dashboard/routes_ds_relscore.py"
    compute = _top(rel, "_compute")
    assert "score_pct = round(float(r.delta_dps) / top_delta * 100.0, 1)" in (
        ast.unparse(compute))
    serve = _top(rel, "_serve_ds_relscore")
    msgs = [
        ast.literal_eval(c.args[0]) for c in _calls_named(serve, "log.warning")
        if c.args and isinstance(c.args[0], ast.Constant)
    ]
    assert "api/ds-relscore compute: %s" in msgs
    resolver = _tree("core/daemon_slayer_resolver.py")
    names = {
        t.id for n in resolver.body if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name)
    }
    assert "_NON_INVENTORY_BASE_IDS" in names
    text = _text("core/daemon_slayer_resolver.py")
    s156 = text.index("(s156): items that occupy non-inventory slots")
    assert s156 < text.index("_NON_INVENTORY_BASE_IDS = ")
    summary = _top("dashboard/_liveclient.py", "liveclient_summary")
    assert any(
        isinstance(n, ast.Assign)
        and [ast.unparse(t) for t in n.targets] == ["owned_item_ids"]
        for n in ast.walk(summary)
    )

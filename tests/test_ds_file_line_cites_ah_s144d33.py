"""Guard: DS-adjacent consumers cite the DS engine, client and planner by symbol (RM-1053).

Measured 2026-10-31 at ENGINE 1.290.0. Twelve modules outside the DS package
cited the DS engine, the DS client, the build-order planner or the
/api/ds-preview route as ``<file>.py:<n>``: 31 cites in all, plus
``core/archetype_mismatch.py:109`` and ``planner.py:12-15`` beside them,
swept with them. The ``routes_state.py:548-549`` split-brain cite recurs in
six of the twelve (``dashboard/routes_build_plan.py`` included). Five still
landed on their target; the rest had drifted, and one pointed at a row that
no longer exists:

- ``core/daemon_slayer_client.py:1410`` / ``:1399-1411`` for the
  ``rank_for_primary_archetype`` seam parameters (def near 2962, the
  ``apply_squishy_burst_target`` default near 3012).
- ``coach_integration/archetype_dispatch.py:282-299`` for the ``seams``
  forwarding block of ``dispatch_for_coach`` (near 310-335).
- ``core/build_order_variants.py:333`` (``compute_variant_cell``, 335).
- ``core/build_order.py:574-575`` / ``:618-619`` / ``:410-418`` /
  ``:34-48`` for ``plan_build_order``'s boots pick (676), its
  ``filter_shared_uniques`` re-pin (722), its early returns (585) and the
  module docstring's no-double-rule item (still exactly 34-48, x2).
- ``core/build_planner/kit_synergy.py:164-198`` for ``_resolve_ds_patch`` /
  ``_load_items`` (182-229).
- ``dashboard/routes_state.py:548-549`` / ``:548`` / ``:592-597`` for the
  split-brain guard and the ds-preview ``ranked[]`` projection
  (``_serve_ds_preview_post``, near 1170).
- ``agents/daemon_slayer/rank.py:248`` / ``:250`` / ``:476`` (``RankedItem``
  near 516, ``_filter_candidates`` near 741), ``kit_synergy.py:485`` /
  ``:217-218`` (``synergy_score`` 787, ``_resolve_item`` 246),
  ``core/daemon_slayer_resolver.py:144-151`` (``NON_INVENTORY_IDS`` 247),
  ``agents/daemon_slayer/server.py:98`` (``DEFAULT_PORT`` 114) and
  ``core/daemon_slayer_client.py:32`` (36).
- ``agents/daemon_slayer/_effects_data.py:5344-5345`` for a 2033 Corrupting
  Potion row: that file carries no 2033 row at 1.290.0.
- Right only by luck: ``stats.py:126`` (``clamp_level``) and
  ``stats.py:107-108`` x2 (two ``ITEM_STAT_KEY_MAP`` rows).
- ``core/build_planner/scoring.py`` also said "6 families" beside the
  no-double cite while the cited docstring lists 7; the count is dropped here
  (the cited docstring carries its own) and filed for a measured re-count.

The tests below pin the symbol cites, re-derive every restated claim by AST,
and ratchet the files: the four whose every cite was DS-targeted go to zero
``<file>.py:<n>`` cites; the other eight go to zero DS-targeted cites (their
remaining non-DS cites are a separate slice).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

_PY_LINE = re.compile(r"(?<![\w./])[\w/]+\.py:\d")
_DS_LINE = re.compile(
    r"(?:daemon_slayer[\w/]*|archetype_dispatch|(?<![\w/])stats|routes_state"
    r"|build_order(?:_variants)?|kit_synergy|(?<![\w/])rank)\.py:\d"
)

# Every cite in these files was DS-targeted: ratchet them to zero line cites.
FULL = {
    "coach_integration/archetype_dispatch.py": (
        "``apply_squishy_burst_target`` default of",
        "``compute_variant_cell`` in core/build_order_variants.py",
        "its ``_select_boots`` call in core/build_order.py",
        "re-pin in core/build_order.py",
    ),
    "core/build_planner/scoring.py": (
        "``test_routes_state_has_no_in_process_engine_import``",
        "(``_serve_ds_preview_post`` in\n    routes_state.py)",
        "the no-double-rule item of the core/build_order.py",
        "(``RankedItem.delta_dps`` in rank.py)",
        "(``_resolve_item`` in kit_synergy.py)",
        "by the ``_is_terminal`` filter in",
        "``_NON_SIGNAL_ITEM_IDS`` in core/archetype_mismatch.py",
        "(``RankedItem.dps_per_1k_gold`` in rank.py)",
    ),
    "dashboard/routes_ds_relscore.py": (
        "(s156, ``NON_INVENTORY_IDS`` in core/daemon_slayer_resolver.py)",
        "documented at ``NON_INVENTORY_IDS`` in core/daemon_slayer_resolver.py;",
    ),
    "dashboard/routes_ds_statcheck.py": (
        "(``clamp_level`` in agents/daemon_slayer/stats.py)",
    ),
}

# These keep non-DS line cites for now: ratchet only the DS-targeted ones.
PARTIAL = {
    "dashboard/routes_build_plan.py": (
        "SPLIT-BRAIN (``test_routes_state_has_no_in_process_engine_import`` in",
        "core/build_planner/planner.py\nmodule docstring): this route",
    ),
    "core/champion_movespeed.py": (
        "(``ITEM_STAT_KEY_MAP`` in agents/daemon_slayer/stats.py)",
        "(``ITEM_STAT_KEY_MAP`` in agents/daemon_slayer/\n    stats.py)",
    ),
    "core/ports.py": (
        "Defined as `DEFAULT_PORT` in `agents/daemon_slayer/server.py`",
    ),
    "dashboard/routes_state.py": (
        "parameter name (the ``rank_for_primary_archetype`` signature",
        "idiom as the ``seams`` block of ``dispatch_for_coach`` in",
        "defaults TRUE (the ``rank_for_primary_archetype`` default in",
    ),
    "core/build_planner/__init__.py": (
        "``test_routes_state_has_no_in_process_engine_import``",
    ),
    "core/build_planner/champ_kit_data.py": (
        "``test_routes_state_has_no_in_process_engine_import``",
        "mirror ``_resolve_ds_patch`` / ``_load_items`` in",
    ),
    "core/build_planner/kit_synergy.py": (
        "``test_routes_state_has_no_in_process_engine_import``",
    ),
    "core/build_planner/planner.py": (
        "``test_routes_state_has_no_in_process_engine_import``",
        "early returns at the top of ``plan_build_order`` in",
        "core/build_order.py module docstring) - a candidate",
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


def _top_assign(rel: str, name: str) -> ast.expr:
    for node in _tree(rel).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
        if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and node.target.id == name and node.value is not None):
            return node.value
    raise AssertionError(f"{name} not assigned at top level of {rel}")


def _defaults(func: ast.FunctionDef) -> dict:
    args = func.args
    out = {}
    pos = args.posonlyargs + args.args
    for a, d in zip(pos[len(pos) - len(args.defaults):], args.defaults):
        out[a.arg] = d
    for a, d in zip(args.kwonlyargs, args.kw_defaults):
        if d is not None:
            out[a.arg] = d
    return out


def _subscript_assigns(func: ast.AST, target: str, key: str) -> list[ast.Assign]:
    out = []
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                        and t.value.id == target
                        and isinstance(t.slice, ast.Constant)
                        and t.slice.value == key):
                    out.append(node)
    return out


def test_patterns_match_the_rotted_shapes():
    for sample in (
        "(core/daemon_slayer_client.py:1410 -",
        "(dashboard/routes_state.py:548-549;",
        "    stats.py:107-108): FlatMovementSpeedMod",
        "(rank.py:248)",
        "core/build_order_variants.py:333 had",
        "(kit_synergy.py:217-218)",
        "`agents/daemon_slayer/server.py:98`",
    ):
        assert _DS_LINE.search(sample), sample
        assert _PY_LINE.search(sample), sample
    for sample in (
        "core/vision_tracker.py:55",
        "core/archetype_picks.py:174-220",
        "`dashboard/server.py:28`",
        "situational.py:407",
        "frank.py:12",
    ):
        assert not _DS_LINE.search(sample), sample
    for sample in ("test_x.py::TestY", "``core.build_order``", "1%:2%"):
        assert not _PY_LINE.search(sample), sample


@pytest.mark.parametrize("rel", sorted(FULL))
def test_full_targets_cite_by_symbol(rel):
    text = _text(rel)
    hits = [i for i, line in enumerate(text.splitlines(), 1) if _PY_LINE.search(line)]
    assert hits == [], (rel, hits)
    for needle in FULL[rel]:
        assert needle in text, (rel, needle)


@pytest.mark.parametrize("rel", sorted(PARTIAL))
def test_partial_targets_cite_ds_by_symbol(rel):
    text = _text(rel)
    hits = [i for i, line in enumerate(text.splitlines(), 1) if _DS_LINE.search(line)]
    assert hits == [], (rel, hits)
    for needle in PARTIAL[rel]:
        assert needle in text, (rel, needle)


def test_rank_for_primary_archetype_squishy_default_true_and_preview_keys_are_params():
    func = _top("core/daemon_slayer_client.py", "rank_for_primary_archetype")
    defaults = _defaults(func)
    d = defaults["apply_squishy_burst_target"]
    assert isinstance(d, ast.Constant) and d.value is True
    params = {a.arg for a in func.args.args + func.args.kwonlyargs}
    for table in ("_DS_PREVIEW_SEAM_BOOLS", "_DS_PREVIEW_SEAM_TRISTATE"):
        keys = ast.literal_eval(_top_assign("dashboard/routes_state.py", table))
        assert keys and set(keys) <= params, (table, set(keys) - params)


def test_compute_variant_cell_forces_squishy_swap_off():
    func = _top("core/build_order_variants.py", "compute_variant_cell")
    hits = _subscript_assigns(func, "rank_kwargs", "apply_squishy_burst_target")
    assert [ast.unparse(h.value) for h in hits] == ["False"]


def test_dispatch_for_coach_seams_block_forwards_only_non_defaults():
    func = _top("coach_integration/archetype_dispatch.py", "dispatch_for_coach")
    for key in ("widen_carry_pool", "apply_target_vuln", "assume_magic_burst"):
        (hit,) = _subscript_assigns(func, "seams", key)
        assert ast.unparse(hit.value) == "True"
    tri = _subscript_assigns(func, "seams", "apply_squishy_burst_target")
    assert [ast.unparse(h.value) for h in tri] == ["bool(apply_squishy_burst_target)"]
    tests = [
        ast.unparse(n.test) for n in ast.walk(func) if isinstance(n, ast.If)
    ]
    assert "apply_squishy_burst_target is not None" in tests


def test_plan_build_order_boots_pick_reads_the_damage_split():
    func = _top("core/build_order.py", "plan_build_order")
    calls = [
        n for n in ast.walk(func) if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name) and n.func.id == "_select_boots"
    ]
    assert calls
    kws = {kw.arg for kw in calls[0].keywords}
    assert {"enemy_ad_share", "enemy_ap_share"} <= kws


def test_plan_build_order_repins_filter_shared_uniques_after_the_splat():
    func = _top("core/build_order.py", "plan_build_order")
    pins = _subscript_assigns(func, "call_kwargs", "filter_shared_uniques")
    assert pins and all(ast.unparse(p.value) == "True" for p in pins)
    updates = [
        n.lineno for n in ast.walk(func) if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute) and n.func.attr == "update"
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "call_kwargs"
    ]
    assert updates and max(p.lineno for p in pins) > min(updates)


def test_plan_build_order_early_returns_none():
    func = _top("core/build_order.py", "plan_build_order")
    first = next(s for s in func.body if not isinstance(s, ast.Expr))
    assert isinstance(first, ast.If)
    assert ast.unparse(first.test) == "not champion or not str(champion).strip()"
    assert ast.unparse(first.body[0]) == "return None"


def test_build_order_docstring_carries_the_no_double_rule_item():
    doc = ast.get_docstring(_tree("core/build_order.py")) or ""
    assert "No-double rule is engine-authoritative" in doc


def test_split_brain_guard_test_exists():
    cls_hits = [
        n for n in ast.walk(_tree("tests/test_ds_preview_e2e_p1l21.py"))
        if isinstance(n, ast.FunctionDef)
        and n.name == "test_routes_state_has_no_in_process_engine_import"
    ]
    assert cls_hits


def test_ds_preview_projection_is_built_in_serve_ds_preview_post():
    func = _top("dashboard/routes_state.py", "_serve_ds_preview_post")
    keys = {
        k.value for n in ast.walk(func) if isinstance(n, ast.Dict)
        for k in n.keys if isinstance(k, ast.Constant)
    }
    assert {"item_id", "delta_dps", "gold", "unique_passive_key"} <= keys


def test_ranked_item_fields_and_terminal_filter():
    cls = _top("agents/daemon_slayer/rank.py", "RankedItem")
    fields = {
        n.target.id for n in cls.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    }
    assert {"delta_dps", "dps_per_1k_gold", "is_terminal"} <= fields
    func = _top("agents/daemon_slayer/rank.py", "_filter_candidates")
    called = {
        n.func.id for n in ast.walk(func)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "_is_terminal" in called


def test_kit_synergy_symbols():
    for name in ("synergy_score", "_resolve_ds_patch", "_load_items"):
        _top("core/build_planner/kit_synergy.py", name)
    func = _top("core/build_planner/kit_synergy.py", "_resolve_item")
    tests = [ast.unparse(n.test) for n in ast.walk(func) if isinstance(n, ast.If)]
    assert "isinstance(item, dict)" in tests


def test_non_inventory_ids_is_derived_and_used_by_relscore():
    value = _top_assign("core/daemon_slayer_resolver.py", "NON_INVENTORY_IDS")
    assert isinstance(value, ast.Call)
    assert ast.unparse(value.func) == "_derive_non_inventory_ids"
    assert "from core.daemon_slayer_resolver import NON_INVENTORY_IDS" in _text(
        "dashboard/routes_ds_relscore.py"
    )


def test_clamp_level_raises_value_error_out_of_range():
    func = _top("agents/daemon_slayer/stats.py", "clamp_level")
    raised = {
        ast.unparse(n.exc.func) for n in ast.walk(func)
        if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
    }
    assert "ValueError" in raised


def test_item_stat_key_map_carries_the_ms_rows():
    table = ast.literal_eval(_top_assign("agents/daemon_slayer/stats.py", "ITEM_STAT_KEY_MAP"))
    assert table["FlatMovementSpeedMod"] == ("ms", "flat")
    assert table["PercentMovementSpeedMod"] == ("ms", "pct")


@pytest.mark.parametrize(
    "rel", ["agents/daemon_slayer/server.py", "core/daemon_slayer_client.py"]
)
def test_ds_default_port_is_8860(rel):
    value = _top_assign(rel, "DEFAULT_PORT")
    assert isinstance(value, ast.Constant) and value.value == 8860


def test_corrupting_potion_is_in_the_curated_consumables():
    value = _top_assign("core/archetype_mismatch.py", "_NON_SIGNAL_ITEM_IDS")
    ids = {
        n.value for n in ast.walk(value)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert "2033" in ids

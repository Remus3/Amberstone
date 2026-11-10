"""S144-P-570: nine private module constants had ZERO readers repo-wide.

An AST scan of private (single underscore) module-level assignments whose name
occurs exactly once in every tracked text file found these. Each was assigned
and never read, imported, patched by a test or named in a doc. Removing them
changes no behaviour; this guard keeps them gone and pins the one behaviour a
removed constant used to misdescribe: the build planner's gold term divides by
a literal 30 inside ``_gold_term`` (the dead ``_GOLD_NORM = 18000.0`` and its
comment claimed an 18k-build normalization that no code applied).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

REMOVED = {
    "coaches/loadout_resolver.py": ["_MELEE_ATTACKRANGE_CEILING"],
    "core/build_planner/scoring.py": ["_GOLD_NORM"],
    "core/feature_policy.py": ["_SAFE_DEFAULT"],
    "core/hud_settings.py": ["_DEFAULT_PERSISTED"],
    "dashboard/routes_loadout.py": ["_PUSH_FLAG_FALSE", "_PUSH_FLAG_TRUE"],
    "dashboard/routes_lobby_aux.py": ["_MATCH_DB"],
    "ops/rc_self_monitor.py": ["_PULSE_STALE_S"],
    "tools/hotfix_ranged_only_melee_loadouts.py": ["_MELEE_CEILING"],
    "tools/hz_mismatch_diagnose.py": ["_REWIND_EXCLUDED_MODES"],
}


def _module_level_names(rel: str) -> set[str]:
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


@pytest.mark.parametrize("rel", sorted(REMOVED))
def test_removed_constants_stay_gone(rel):
    assert REMOVED[rel], "anchor: every entry names at least one constant"
    present = _module_level_names(rel)
    assert present, "anchor: the module must still have module-level names"
    back = [n for n in REMOVED[rel] if n in present]
    assert not back, f"{rel} re-added a constant with no reader: {back}"


def test_gold_term_normalizes_by_thirty():
    from core.build_planner import scoring

    rows = {1: {"dps_per_1k_gold": 30.0}, 2: {"dps_per_1k_gold": 15.0}}
    assert scoring._gold_term([1], rows) == pytest.approx(1.0)
    assert scoring._gold_term([1, 2], rows) == pytest.approx(0.75)

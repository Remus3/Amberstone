"""Guard: RM-169 + P2-W1-dash-D tests cite DS scorers by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. Two RC test modules explained the DS
mode path with line cites; every cite had drifted, every claim still held.

- ``test_rm169_matchup_mode_characterization.py`` (6484f8102, cites as of
  b3df73741, both 2026-08-06):
  ``laning_scenario_precompute.py:545`` (the ``compute_matchup`` call in
  ``_matchup``, now near 576), ``engine.py:458`` (the "not plugged in" note in
  ``build_champion``, now near 531), ``engine.py:254`` (the ``mode != "ARAM"``
  early return in ``_apply_mode_modifiers``, now near 286), ``engine.py:295``
  (``apply_mode_modifiers: bool = False``, now near 333), ``burst.py:674-676``
  (``mode_mult`` in ``compute_burst_damage``, now near 699-701),
  ``ability_dps.py:1134-1140`` x2 (``mode_mult`` in ``compute_ability_dps``,
  now near 1192-1196) and ``ability_dps.py:1350`` x2 (the
  ``get_spell_casts_per_sec`` read, now near 1420). It also named an earlier
  draft's ``matchup.py`` line range in passing.
- ``test_p2w1_dash_d.py`` (f2887158a, 2026-06-12): ``burst.py:539`` (the
  ``mode == "ARAM"`` gate on ``mode_mult``, now near 700). Its claim that the
  engine compares case-sensitively was true then and is not now: RM-325
  (c9bea8b07) folds ``mode`` through ``data_loader.canonical_mode`` at the
  scorer entry, so the prose now says so.

The prose now names the functions, and the tests below pin each claim to the
code, so a moved or renamed seam fails here instead of leaving prose that lies.
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import core.laning_scenario_precompute as lsp
from agents.daemon_slayer import ability_dps, burst, engine

REPO = Path(__file__).resolve().parent.parent
RM169 = REPO / "tests" / "test_rm169_matchup_mode_characterization.py"
P2W1 = REPO / "tests" / "test_p2w1_dash_d.py"

_LINE_CITE = re.compile(r"\w\.py:\d")
_DS_LINE_CITE = re.compile(r"(burst|engine|ability_dps)\.py:\d")

# Phrases only the replacement prose carries, per citing file.
_NAMED_IN_PROSE = {
    RM169: (
        "``core/laning_scenario_precompute.py``'s ``_matchup``",
        "``engine.build_champion``\nappends",
        "table read in ``ability_dps.compute_ability_dps`` via",
        "(``mode_mult`` in ``burst.compute_burst_damage``)",
        "because engine.build_champion appends",
        "ability_dps.compute_ability_dps -> ult_rates.get_spell_casts_per_sec",
        "(build_champion's apply_mode_modifiers defaults False)",
    ),
    P2W1: (
        "(``mode_mult`` in\n        burst.compute_burst_damage)",
        "data_loader.canonical_mode, RM-325",
    ),
}


def test_citing_files_exist() -> None:
    assert RM169.is_file(), RM169
    assert P2W1.is_file(), P2W1


def test_no_line_cites_left() -> None:
    hits = _LINE_CITE.findall(RM169.read_text(encoding="utf-8"))
    assert not hits, f"{RM169.name}: line cites {hits}"
    hits = _DS_LINE_CITE.findall(P2W1.read_text(encoding="utf-8"))
    assert not hits, f"{P2W1.name}: DS line cites {hits}"


def test_replacement_prose_names_the_symbols() -> None:
    for path, phrases in _NAMED_IN_PROSE.items():
        text = path.read_text(encoding="utf-8")
        for phrase in phrases:
            assert phrase in text, f"{path.name}: missing {phrase!r}"


def test_laning_matchup_helper_calls_compute_matchup() -> None:
    src = inspect.getsource(lsp._matchup)
    assert "return compute_matchup(" in src
    assert "mode=mode" in src


def test_build_champion_notes_arena_not_plugged_in() -> None:
    src = inspect.getsource(engine.build_champion)
    gate = src.index('if mode not in ("SR", "ARAM"):')
    assert "modifier table not plugged in for this mode" in src[gate:gate + 150]


def test_apply_mode_modifiers_returns_early_outside_aram() -> None:
    src = inspect.getsource(engine._apply_mode_modifiers)
    assert 'if mode != "ARAM":\n        return scaled, notes' in src


def test_build_champion_mode_modifiers_flag_defaults_off() -> None:
    default = inspect.signature(engine.build_champion).parameters[
        "apply_mode_modifiers"
    ].default
    assert default is False


def _mode_mult_gates(func: object) -> int:
    """Count ``if mode == "ARAM":`` blocks that assign ``mode_mult``."""
    tree = ast.parse(inspect.getsource(func).lstrip())
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "mode"
            and isinstance(test.ops[0], ast.Eq)
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "ARAM"
        ):
            continue
        if any(
            isinstance(stmt, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "mode_mult"
                for t in stmt.targets
            )
            for stmt in node.body
        ):
            count += 1
    return count


def test_mode_mult_is_aram_gated_on_both_paths() -> None:
    assert _mode_mult_gates(burst.compute_burst_damage) == 1
    assert _mode_mult_gates(ability_dps.compute_ability_dps) == 1


def test_ability_dps_reads_the_per_mode_cast_rate_table() -> None:
    src = inspect.getsource(ability_dps.compute_ability_dps)
    assert (
        "get_spell_casts_per_sec(resolved.champion_name, key, mode)" in src
    )


def test_burst_folds_mode_case_at_entry() -> None:
    src = inspect.getsource(burst.compute_burst_damage)
    fold = src.index("mode = canonical_mode(mode)")
    assert fold < src.index('if mode == "ARAM":')

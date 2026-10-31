"""Guard: build-planner fed / kit and NEXT BUY fallback cite by symbol (RM-1053).

Measured 2026-10-31 at ENGINE 1.290.0. Three DS-adjacent modules carried
eight ``<file>.py:<n>`` cites (two of them the same range). Five of the
seven distinct targets had drifted off their target; the other
two (``build_order_precompute.py:79`` and ``laning_verdicts.py:197``) still
land on or one line beside their target and are converted with the rest:

- core/build_planner/fed_threat.py (written 2026-07-17):
  ``situational.py:407`` for the C3 fed counter-build hint (the
  ``if ep.fed:`` branch of ``counter_build_hints`` now sits about ten lines
  lower); ``game_reader/snapshot_normalizer.py:300-304`` for the scoreboard
  fields (that range is now a removal comment; the reads live in
  ``_NormalizerMixin._process_game``); ``situational.py:39`` for the
  private-helper import precedent (the ``_load_stat_index`` import is one
  line lower).
- core/build_planner/kit_synergy.py (written 2026-06-28), twice:
  ``core/archetype_picks.py:174-220`` for the patch + items loader it
  mirrors (``_resolve_ds_patch`` and ``_load_damage_axes`` have moved down
  by about thirty lines).
- core/next_buy_fallback.py (written 2026-07-24):
  ``core/build_order_precompute.py:79`` for the canonical-id keyed table
  (still on the docstring NOTE today, but the keying is done by
  ``generate_table``); ``core/laning_scenario_precompute.py:247`` for the
  neutral "balanced" bucket (first written as ``:355``, the
  ``champ_orders.get(_BUILD_BUCKET)`` read; re-pointed to ``:247`` at
  f526495d9 on 2026-08-08, where it was exact; ``_BUILD_BUCKET`` now sits
  three lines lower); ``core/laning_verdicts.py:197`` for the same
  preference (it was the ``champ_orders.get("balanced")`` read; now the
  comment line just above the ``champ_orders.get("balanced")`` read inside
  ``_next_build_item``).

The tests below ratchet the three files to zero line cites, pin the symbol
cites, and re-derive every restated claim by AST.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_PY_LINE = re.compile(r"(?<![\w./])[\w/]+\.py:\s?\d")
_PROSE_LINE = re.compile(r"\blines? ~?\d{2,}")

FED = "core/build_planner/fed_threat.py"
KIT = "core/build_planner/kit_synergy.py"
NBF = "core/next_buy_fallback.py"

NEEDLES = {
    FED: (
        "fires on it: the ``if ep.fed:`` branch of\n"
        "    ``counter_build_hints`` in situational.py)",
        "(``_NormalizerMixin._process_game`` in\n"
        "    game_reader/snapshot_normalizer.py reads the same fields)",
        "the ``_load_stat_index`` import in\n    situational.py)",
    ),
    KIT: (
        "Data is loaded by MIRRORING ``_resolve_ds_patch`` / "
        "``_load_damage_axes`` in\ncore/archetype_picks.py",
        "# Item data loader - mirrors ``_resolve_ds_patch`` / "
        "``_load_damage_axes`` in\n# core/archetype_picks.py.",
    ),
    NBF: (
        "(``generate_table`` in core/build_order_precompute.py)",
        "``_BUILD_BUCKET`` in\n# core/laning_scenario_precompute.py and the "
        "``_next_build_item`` preference in\n# core/laning_verdicts.py.",
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


def _assigned(rel: str, name: str) -> object:
    values = [
        n.value for n in _tree(rel).body if isinstance(n, ast.Assign)
        and [ast.unparse(t) for t in n.targets] == [name]
    ]
    assert len(values) == 1, (rel, name, len(values))
    return ast.literal_eval(values[0])


def test_patterns_match_the_rotted_shapes():
    for sample in (
        "    counter-build hint fires on it, ``situational.py:407``), plus",
        "    (game_reader/snapshot_normalizer.py:300-304 reads the same",
        "    private-helper import precedent: situational.py:39), overlaid",
        "Data is loaded by MIRRORING core/archetype_picks.py:174-220 - the",
        "    (core/build_order_precompute.py:79) is canonical-id keyed:",
        "# core/laning_scenario_precompute.py:247 and core/laning_verdicts.py:197.",
    ):
        assert _PY_LINE.search(sample), sample
    for sample in (
        "``counter_build_hints`` in situational.py",
        "``core.archetype_picks.canonical_champion_id``",
        "ENGINE 1.290.0",
        "docs/specs/2026-07-17-ds-c3-fed-counter-hint-design.md",
    ):
        assert not _PY_LINE.search(sample), sample
        assert not _PROSE_LINE.search(sample), sample


def test_targets_cite_by_symbol():
    assert len(NEEDLES) == 3
    for rel, needles in NEEDLES.items():
        text = _text(rel)
        hits = [
            i for i, line in enumerate(text.splitlines(), 1)
            if _PY_LINE.search(line) or _PROSE_LINE.search(line)
        ]
        assert hits == [], (rel, hits)
        for needle in needles:
            assert needle in text, (rel, needle)


def test_fed_hint_branch_in_counter_build_hints():
    func = _top("core/build_planner/situational.py", "counter_build_hints")
    branches = [
        n for n in ast.walk(func)
        if isinstance(n, ast.If) and ast.unparse(n.test) == "ep.fed"
    ]
    assert len(branches) == 1
    assert "criterion='fed'" in ast.unparse(branches[0])


def test_process_game_reads_the_scoreboard_fields():
    cls = _top("game_reader/snapshot_normalizer.py", "_NormalizerMixin")
    body = ast.unparse(_method(cls, "_process_game"))
    for field in ("'scores'", "'level'", "'items'", "'kills'", "'deaths'"):
        assert field in body, field


def test_situational_imports_a_private_helper():
    imports = [
        n for n in _tree("core/build_planner/situational.py").body
        if isinstance(n, ast.ImportFrom) and n.module == "core.enemy_aware_stats"
    ]
    assert [a.name for n in imports for a in n.names] == ["_load_stat_index"]


def test_kit_synergy_mirrors_the_archetype_picks_loader():
    for rel in ("core/archetype_picks.py", KIT):
        patch = ast.unparse(_top(rel, "_resolve_ds_patch"))
        assert "'current.txt'" in patch, rel
    _top("core/archetype_picks.py", "_load_damage_axes")
    loader = ast.unparse(_top(KIT, "_load_items"))
    assert "_resolve_ds_patch()" in loader
    assert "'items.json'" in loader


def test_generate_table_keys_by_canonical_id():
    func = ast.unparse(_top("core/build_order_precompute.py", "generate_table"))
    assert "build_orders[archetype_picks.canonical_champion_id(champ)]" in func


def test_balanced_is_the_neutral_bucket_everywhere():
    assert _assigned(NBF, "_PREFERRED_BUCKET") == "balanced"
    assert _assigned("core/laning_scenario_precompute.py", "_BUILD_BUCKET") == "balanced"
    verdict = ast.unparse(_top("core/laning_verdicts.py", "_next_build_item"))
    assert "champ_orders.get('balanced')" in verdict

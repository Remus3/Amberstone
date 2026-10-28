"""Guard: AD-axis / wiki-registry line cites become symbol cites (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. Five DS files still cited the engine
by line number, and at HEAD every cite had drifted off its line:

- ``agents/daemon_slayer/_ad_axis_ability.py`` (8 cites, 84ed2b617 and
  cef82ebac): ``hybrid.py:50`` was ``hybrid``'s module-level
  ``from .rank import``; ``dps.py:911`` was ``compute_dps``'s function-level
  ``from .ability_dps import rank_at_level``; ``ability_dps.py:385`` /
  ``377`` / ``371`` / ``372-373`` were ``_mitigation_factor``'s MIXED branch,
  its ``(damage_type or "MAGIC").upper()`` idiom and its TRUE branch;
  ``ability_dps.py:1261`` was ``compute_ability_dps``'s
  ``dps = post_mit * measured``; ``ability_dps.py:1376-1381`` was its
  ``item_proc_dps`` fold into ``total_dps``.
- ``agents/daemon_slayer/_ability_wiki_damage_registry.py`` (2 cites):
  ``rank.py:1118-1131`` was ``rank_items``'s ``reweight`` branch computing
  ``baseline_burst``; ``ability_dps.py:371,384`` was ``_mitigation_factor``.
- ``agents/daemon_slayer/rank.py`` (4 cites, all in ``rank_items``'s
  RM-36 / RM-38 comment block): ``dps.py:34`` was the ``dps`` module
  docstring's "Ability damage is **not** included"; ``ability_dps.py:148``
  was ``ability_dps``'s module-level ``from .rank import``; ``dps.py:911``
  as above; ``dps.py:890`` was ``compute_dps``'s ``if apply_crit_conversion:``.
- ``agents/daemon_slayer/onhit_dps.py``: ``ability_dps.py:1261`` as above.
- ``agents/daemon_slayer/tests/test_ability_wiki_damage_locke_zaahen.py``:
  ``rank.py:1118-1131`` as above.

Every claim still holds; the prose now names the function and the branch,
and each claim is pinned below so a rename or a moved gate fails here.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
AD_AXIS = DS / "_ad_axis_ability.py"
REGISTRY = DS / "_ability_wiki_damage_registry.py"
RANK = DS / "rank.py"
ONHIT = DS / "onhit_dps.py"
LOCKE = DS / "tests" / "test_ability_wiki_damage_locke_zaahen.py"

# ``hybrid.py:50``, ``(dps.py:911)``, ``ability_dps.py:371,384``,
# ``rank.py:1118-1131``; the boundary keeps a longer module name
# (the on-hit module, a ``test_rank`` file) out.
_LINE_CITE = re.compile(r"(?<![A-Za-z_])(?:hybrid|dps|ability_dps|rank)\.py:\d")

# Phrases only the replacement prose carries, per file.
_NAMED_IN_PROSE = {
    AD_AXIS: (
        "``hybrid`` imports\n``rank`` at module level, so the dependency only runs one way.",
        "``dps.compute_dps`` already uses for ``ability_dps.rank_at_level``.",
        "50/50 across armor and MR by construction (its MIXED branch).",
        "(``compute_ability_dps`` sets each\n    row's ``dps = post_mit * measured``)",
        "The filter reuses ``ability_dps._mitigation_factor``'s canonical\n"
        "    normalization idiom verbatim",
        "``item_proc_dps`` (``compute_ability_dps``'s\n    ``_periodic_proc_dps`` fold)",
        "1.0 for TRUE before any resist is read, so a TRUE row",
        "across armor and MR (its MIXED branch), and a full",
    ),
    REGISTRY: (
        "(the ``reweight`` branch of ``rank.rank_items``), so every one",
        "armor/MR (``ability_dps._mitigation_factor``).",
    ),
    RANK: (
        "auto-attack-only by design (the ``dps`` module docstring)",
        "# Same idiom as ``compute_dps``'s function-level ``rank_at_level`` import.",
        "# (``compute_dps``'s ``if apply_crit_conversion:`` branch performs no",
    ),
    ONHIT: (
        "``matches.game_duration_s``; ``compute_ability_dps`` sets each row's\n"
        "``dps = post_mit * measured``)",
    ),
    LOCKE: (
        "reads, in the ``reweight`` branch\n  of ``rank.rank_items``).",
    ),
}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _module(path: Path) -> ast.Module:
    return ast.parse(_text(path))


def _function(path: Path, name: str) -> ast.FunctionDef:
    for node in _module(path).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path.name} has no top-level def {name}")


def _sources(node: ast.AST) -> list[str]:
    return [ast.unparse(n) for n in ast.walk(node) if isinstance(n, ast.stmt)]


def _imports_from(nodes, module: str) -> list[ast.ImportFrom]:
    return [
        n for n in nodes
        if isinstance(n, ast.ImportFrom) and n.level == 1 and n.module == module
    ]


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "``rank`` (hybrid.py:50), so",
        "``dps.py:911`` already uses",
        "(``ability_dps.py:1376-1381``)",
        "armor/MR (``ability_dps.py:371,384``)",
        "(``rank.py:1118-1131``)",
        "by design (dps.py:34), so",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        # Built by concatenation so this file never carries the RM-1050
        # guard's own banned shape.
        "onhit_dps" + ".py:17",
        "test_rank.py:2",
        "SPEC_rm98_cast_rate_time_base.md:76-89",
        "port :8860",
        "``dps.py``",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left():
    hits = [
        f"{path.name}:{i}: {line.strip()}"
        for path in _NAMED_IN_PROSE
        for i, line in enumerate(_text(path).splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "line cites came back:\n" + "\n".join(hits)


def test_replacement_prose_present():
    missing = [
        f"{path.name}: {phrase!r}"
        for path, phrases in _NAMED_IN_PROSE.items()
        for phrase in phrases
        if phrase not in _text(path)
    ]
    assert not missing, "replacement prose gone:\n" + "\n".join(missing)


def test_import_direction_claims():
    assert _imports_from(_module(DS / "hybrid.py").body, "rank")
    assert _imports_from(_module(DS / "ability_dps.py").body, "rank")
    assert not _imports_from(_module(RANK).body, "_ad_axis_ability")
    rank_items = _function(RANK, "rank_items")
    term = next(
        n for n in ast.walk(rank_items)
        if isinstance(n, ast.FunctionDef) and n.name == "_ad_axis_term"
    )
    assert _imports_from(ast.walk(term), "_ad_axis_ability")
    compute_dps = _function(DS / "dps.py", "compute_dps")
    lazy = _imports_from(ast.walk(compute_dps), "ability_dps")
    assert any(a.name == "rank_at_level" for n in lazy for a in n.names)


def test_mitigation_factor_claims():
    src = "\n".join(_sources(_function(DS / "ability_dps.py", "_mitigation_factor")))
    assert "dt = (damage_type or 'MAGIC').upper()" in src
    assert "if dt == 'TRUE':\n    return 1.0" in src
    assert (
        "return 0.5 * _armor_factor(target_armor) + 0.5 * _armor_factor(target_mr)"
        in src
    )
    filt = "\n".join(_sources(_function(AD_AXIS, "physical_ability_damage")))
    assert "(row.damage_type or 'MAGIC').upper() in AD_AXIS_CREDITED_DAMAGE_TYPES" in filt


def test_compute_ability_dps_claims():
    src = _sources(_function(DS / "ability_dps.py", "compute_ability_dps"))
    assert "dps = post_mit * measured" in src
    assert any(s.startswith("item_proc_dps = _periodic_proc_dps(") for s in src)
    assert "total_dps += item_proc_dps" in src


def test_rank_items_reweight_burst_claims():
    rank_items = _function(RANK, "rank_items")
    src = _sources(rank_items)
    assert "reweight = fight_length is not None and fight_length > 0.0" in src
    branches = [
        n for n in ast.walk(rank_items)
        if isinstance(n, ast.If) and ast.unparse(n.test) == "reweight"
    ]
    assert any(
        ast.unparse(s).startswith("baseline_burst = _safe_burst(")
        for b in branches
        for s in b.body
    )


def test_compute_dps_claims():
    assert "Ability damage is **not** included" in ast.get_docstring(_module(DS / "dps.py"))
    compute_dps = _function(DS / "dps.py", "compute_dps")
    gates = [
        n for n in ast.walk(compute_dps)
        if isinstance(n, ast.If) and ast.unparse(n.test) == "apply_crit_conversion"
    ]
    assert len(gates) == 1
    assert _imports_from(gates[0].body, "_crit_conversion_overrides")

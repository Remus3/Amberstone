"""Guard: abilities / ability_dps / hps line cites become symbol cites (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. Two files still cited the ability
engine by line number, and at HEAD every cite had drifted off its line:

- ``agents/daemon_slayer/tests/test_ad_axis_ability_damage_rm39.py`` (7 cites,
  6bdaae307): ``ability_dps.py:371`` / ``372`` / ``372-373`` / ``377`` were
  ``_mitigation_factor``'s ``(damage_type or "MAGIC").upper()`` idiom, its
  TRUE branch and its MIXED branch; ``ability_dps.py:1376-1381`` (twice) was
  ``compute_ability_dps``'s ``item_proc_dps`` fold into ``total_dps``.
- ``agents/daemon_slayer/server.py`` (8 cites): ``abilities.py:1006`` /
  ``1302-1315`` (041984580) were ``AbilitiesSnapshot.load``'s
  ``apply_ability_base_overrides`` kwarg and the keyless ``load_default``;
  ``ability_dps.py:960 / :949`` (041984580) were ``compute_ability_dps``'s
  ``apply_passive_aura_damage`` and ``abilities_snapshot`` parameters - the
  old prose said both seams were "accepted by compute_ability_dps", which
  for the override seam is true only through ``abilities_snapshot``, so the
  new prose says so; ``ability_dps.py:299-300`` (c891a657b) was
  ``AbilityContext.from_build`` setting ``caster_max_mp`` / ``caster_bonus_mp``;
  ``hps.py:685`` / ``520`` / ``863`` (7e1697e46) were ``compute_hps``'s
  ability fold, its ``apply_ability_hsp_amp`` parameter and
  ``rank_items_by_hps``.

Every claim still holds; the prose now names the function and the branch,
and each claim is pinned below so a rename or a moved gate fails here.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
RM39 = DS / "tests" / "test_ad_axis_ability_damage_rm39.py"
SERVER = DS / "server.py"

# ``ability_dps.py:371``, ``(abilities.py:1006)``, ``(hps.py:685)``; the
# boundary keeps a longer module name (``_ability_hps.py:1``) out.
_LINE_CITE = re.compile(r"(?<![A-Za-z_])(?:abilities|ability_dps|hps)\.py:\d")

# Phrases only the replacement prose carries, per file.
_NAMED_IN_PROSE = {
    RM39: (
        "``ability_dps._mitigation_factor`` idiom",
        "returns a flat 1.0 for TRUE\nbefore any resist is read",
        "(``compute_ability_dps`` adds its ``_periodic_proc_dps``",
        "``_mitigation_factor`` returns 1.0 for TRUE, so",
        "``_mitigation_factor`` - a None damage_type normalizes",
        "across armor and MR (its MIXED\n        branch)",
        "(``compute_ability_dps``'s ``_periodic_proc_dps``\n        fold)",
    ),
    SERVER: (
        "(a bare ``AbilitiesSnapshot.load()`` behind a\n    module ``_cache``)",
        "caster_max_mp (set by ``AbilityContext.from_build``).",
        "caster_bonus_mp (set beside it in ``AbilityContext.from_build``).",
        "through\n    # its ``abilities_snapshot`` parameter)",
        "(``compute_hps``'s\n    # ``ability_hps_total`` fold).",
        "(``compute_hps`` takes it as a\n    # parameter)",
    ),
}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function(path: Path, name: str, cls: str | None = None) -> ast.FunctionDef:
    body = ast.parse(_text(path)).body
    if cls is not None:
        body = next(
            n.body for n in body if isinstance(n, ast.ClassDef) and n.name == cls
        )
    for node in body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path.name} has no def {cls + '.' if cls else ''}{name}")


def _params(fn: ast.FunctionDef) -> set[str]:
    args = fn.args
    return {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}


def _sources(fn: ast.FunctionDef) -> list[str]:
    return [ast.unparse(n) for n in ast.walk(fn) if isinstance(n, ast.stmt)]


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "``ability_dps.py:371`` idiom",
        "(ability_dps.py:1376-1381)",
        "(abilities.py:1302-1315)",
        "(hps.py:685).",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in ("_ability_hps.py:12", "port :8860", "``hps.py``"):
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


def test_mitigation_factor_claims():
    src = "\n".join(_sources(_function(DS / "ability_dps.py", "_mitigation_factor")))
    assert "dt = (damage_type or 'MAGIC').upper()" in src
    assert "if dt == 'TRUE':\n    return 1.0" in src
    assert (
        "return 0.5 * _armor_factor(target_armor) + 0.5 * _armor_factor(target_mr)"
        in src
    )


def test_item_proc_fold_is_total_only():
    fn = _function(DS / "ability_dps.py", "compute_ability_dps")
    src = _sources(fn)
    assert any(s.startswith("item_proc_dps = _periodic_proc_dps(") for s in src)
    assert "total_dps += item_proc_dps" in src
    spell_rows = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and ast.unparse(n.func) == "AbilitySpellDps"
    ]
    assert spell_rows
    assert not any("item_proc_dps" in ast.unparse(n) for n in spell_rows)


def test_abilities_override_claims():
    abilities = DS / "abilities.py"
    load = _function(abilities, "load", cls="AbilitiesSnapshot")
    assert "apply_ability_base_overrides" in _params(load)
    load_default = _function(abilities, "load_default")
    assert not _params(load_default)
    assert "_cache = AbilitiesSnapshot.load()" in _sources(load_default)


def test_ability_context_carries_mana():
    src = "\n".join(_sources(_function(DS / "ability_dps.py", "from_build", cls="AbilityContext")))
    assert "caster_max_mp=caster_max_mp" in src
    assert "caster_bonus_mp=caster_bonus_mp" in src


def test_ability_dps_route_seam_claims():
    params = _params(_function(DS / "ability_dps.py", "compute_ability_dps"))
    assert {"apply_passive_aura_damage", "abilities_snapshot"} <= params
    assert "apply_ability_base_overrides" not in params
    route = "\n".join(_sources(_function(SERVER, "_route_ability_dps")))
    assert "abilities_snapshot=_ABIL_CACHE.get(apply_ability_base_overrides)" in route
    assert "apply_passive_aura_damage=apply_passive_aura_damage" in route


def test_hps_claims():
    hps = DS / "hps.py"
    compute = _function(hps, "compute_hps")
    assert "apply_ability_hsp_amp" in _params(compute)
    assert "ability_hps_total = a.total_ability_hps" in _sources(compute)
    ranker = _function(hps, "rank_items_by_hps")
    assert "apply_ability_hsp_amp" not in ast.unparse(ranker)
    owners = [
        f"{path.name}:{node.name}"
        for path in sorted(DS.glob("*.py"))
        for node in ast.walk(ast.parse(_text(path)))
        if isinstance(node, ast.FunctionDef)
        and "apply_ability_hsp_amp" in _params(node)
    ]
    assert owners == ["hps.py:compute_hps"], owners

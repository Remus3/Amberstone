"""Guard: kit_conversion and matchup cite by symbol (part r).

Measured 2026-10-30 at ENGINE 1.290.0. Fourteen line cites in two DS modules had
all rotted:

- ``kit_conversion.py`` cited ``abilities.py:220-235`` / ``:237-263`` for the
  ``AbilityForm`` fields and ``from_dict`` (now :218 / :247), ``:379`` / ``:375``
  for the ``_passive_damage_overrides`` seeding comment and the
  ``conditional_probability`` field (now :394 / :390), ``hybrid.py:69`` for the
  no-``core``-import rule (now :98), ``ehp.py:2194`` / ``ehp.py:2193`` for
  ``_GOLD_PER_HP`` / ``_GOLD_PER_MR`` (now :2822 / :2821) and
  ``hybrid.py:73-79`` for ``_damage_axis`` (now :116), plus a bare
  ``:128-129`` for its own Olaf note (now :131). The ``_damage_axis`` cite also
  restated a fact that is no longer true: ``hybrid._damage_axis`` reads the
  kit's ``lolmath.damage_distribution`` FIRST, so ``damage_objective`` mirrors
  only its rating-split fallback.
- ``matchup.py`` cited ``engine.py:458`` (and a bare ``:458``) for the ARENA
  "modifier table not plugged in" note (now :531), ``engine.py:106`` for
  ``_resolve_mode_addends`` (now :111), ``engine.py:225`` for
  ``_apply_mode_modifiers`` (now :253) and ``engine.py:450`` for its
  unconditional call (now :523).

The tests below pin the cites, and the facts they restated, by symbol.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.daemon_slayer import (
    _passive_damage_overrides,
    abilities,
    ehp,
    engine,
    hybrid,
    kit_conversion,
)

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|(?<![\w.]):\d|\blines? \d")

TARGETS = {
    "kit_conversion.py": (
        "(the ``abilities.AbilityForm`` dataclass declares 16 fields and its "
        "``from_dict`` parses exactly those,",
        "effects_descriptions\", the comment above its "
        "``_PASSIVE_DAMAGE_OVERRIDES`` registry)",
        "(``PassiveDamageEntry.conditional_probability: float = 1.0``)",
        "(the same rule ``hybrid`` states above ``_damage_axis``).",
        "FlatHPPoolMod matches ``ehp._GOLD_PER_HP`` exactly. NOTE "
        "``ehp._GOLD_PER_MR`` is 18.0",
        "Reproduces the ``_KIT_CONVERSION[\"Olaf\"]`` note (\"nothing is "
        "off-axis for him except AP\") exactly.",
        "the FALLBACK branch of ``hybrid._damage_axis``",
        "reads the kit's ``lolmath.damage_distribution`` FIRST",
    ),
    "matchup.py": (
        "because ``engine.build_champion`` appends",
        "``engine._resolve_mode_addends`` is the ARENA/Swiftplay stat-growth "
        "ADDEND lane",
        "``engine._apply_mode_modifiers`` is the ARAM MULTIPLIER lane, is "
        "called UNCONDITIONALLY in ``build_champion``,",
        "so that note fires even on calls",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def test_pattern_matches_the_old_shapes():
    for sample in (
        "declares 16 fields at ``abilities.py:220-235`` and ``from_dict`` at "
        "``:237-263``",
        'effects_descriptions", ``:379``) and its continuous-fraction contract',
        "(``conditional_probability: float = 1.0``, ``:375``). This is also",
        "(the ``hybrid.py:69`` rule).",
        "# crit. FlatHPPoolMod matches ehp.py:2194 _GOLD_PER_HP exactly.",
        "    uses (``hybrid.py:73-79``), reimplemented locally rather than",
        '# the beta term. Reproduces the Olaf note at :128-129 ("nothing is',
        "``.notes`` differs on 173 of 173 ARENA calls, because "
        "``engine.py:458`` appends",
        "(engine.py:106) is the ARENA/Swiftplay stat-growth ADDEND lane",
        "MULTIPLIER lane, is called UNCONDITIONALLY at engine.py:450, and",
        "champions, axes hp_base/hp_lvl/dam_lvl/arm_lvl/as_lvl), so :458 fires",
    ):
        assert _LINE_CITE.search(sample), sample
    for symbols in TARGETS.values():
        for sample in symbols:
            assert not _LINE_CITE.search(sample), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (DS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    flat = _flat((DS / name).read_text(encoding="utf-8"))
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"


def test_ability_form_has_16_fields_and_drops_effects_descriptions():
    names = [f.name for f in dataclasses.fields(abilities.AbilityForm)]
    assert len(names) == 16
    assert "effects_descriptions" not in names
    src = inspect.getsource(abilities.AbilityForm.from_dict)
    assert "effects_descriptions" not in src


def test_passive_overrides_precedent_still_stands():
    src = inspect.getsource(_passive_damage_overrides)
    seed = src.index("# Seeded 2026-05-31 against verbatim effects_descriptions")
    registry = src.index("_PASSIVE_DAMAGE_OVERRIDES: dict[")
    assert 0 < registry - seed < 1000
    fields = {
        f.name: f.default
        for f in dataclasses.fields(_passive_damage_overrides.PassiveDamageEntry)
    }
    assert fields["conditional_probability"] == 1.0


def _imports_core(name: str) -> bool:
    tree = ast.parse((DS / name).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "core" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "core":
            return True
    return False


def test_no_core_import_rule_stands_in_both_modules():
    assert "self-contained (no ``core`` import)" in _flat(
        inspect.getsource(hybrid)
    )
    assert not _imports_core("hybrid.py")
    assert not _imports_core("kit_conversion.py")


def test_olaf_note_and_hybrid_ad_off_axis_set_agree():
    note = kit_conversion._KIT_CONVERSION["Olaf"].note
    assert "nothing is off-axis for him except AP" in note
    assert kit_conversion._OFF_AXIS_KEYS["hybrid_ad"] == {"FlatMagicDamageMod"}


def test_gold_per_stat_agreement_and_divergence_stand():
    assert kit_conversion._GOLD_PER["FlatHPPoolMod"] == ehp._GOLD_PER_HP
    assert ehp._GOLD_PER_MR == 18.0
    assert kit_conversion._GOLD_PER["FlatSpellBlockMod"] == 20.0


def _snapshot(record: dict) -> SimpleNamespace:
    return SimpleNamespace(champions={"X": record})


def test_damage_objective_is_only_the_rating_fallback_of_damage_axis():
    rated_ad_kit_ap = {
        "info": {"attack": 7, "magic": 3},
        "lolmath": {"damage_distribution": {"magical": 0.8, "physical": 0.2}},
    }
    snap = _snapshot(rated_ad_kit_ap)
    assert hybrid._damage_axis(snap, "X") == "ap"
    assert kit_conversion.damage_objective(snap, "X") == "ad"
    rating_only = _snapshot({"info": {"attack": 3, "magic": 7}})
    assert hybrid._damage_axis(rating_only, "X") == "ap"
    assert kit_conversion.damage_objective(rating_only, "X") == "ap"


def test_build_champion_mode_lanes_stand():
    src = inspect.getsource(engine.build_champion)
    assert 'if mode not in ("SR", "ARAM"):' in src
    assert "modifier table not plugged in for this mode" in src
    assert re.search(
        r"_resolve_mode_addends\(snapshot, champion_id, mode\)\s*"
        r"if apply_mode_modifiers",
        src,
    )
    fn = ast.parse(src).body[0]
    top_level_calls = [
        node.value.func.id
        for node in fn.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    ]
    assert "_apply_mode_modifiers" in top_level_calls
    aram_src = inspect.getsource(engine._apply_mode_modifiers)
    assert re.search(r'if mode != "ARAM":\s*return scaled, notes', aram_src)

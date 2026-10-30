"""Guard: hybrid and the item mana / bonus-HP lanes cite by symbol (part q).

Measured 2026-10-30 at ENGINE 1.290.0. Six line cites in three DS modules had
all rotted:

- ``hybrid.py`` said "hybrid imports rank (line 50)"; its ``from .rank import``
  block now opens on :54. It also cited ``dps.py:34`` twice for "Ability damage
  is not included"; that sentence is now on :45 of the ``dps`` module docstring.
- ``_item_bonus_hp_amp.py`` cited ``engine.py`` ~line 404 for the Tyranny
  ``bonus_ad_pct_bonus_hp`` walk (now :462).
- ``_item_mana_health.py`` cited ``engine.py`` ~line 362 for the Awe-AD
  ``bonus_ad_pct_max_mp`` walk (now :421) and ~line 383 for the Awe-AP
  ``bonus_ap_pct_bonus_mp`` walk (now :442).

All three walks live in ``engine.build_champion``. The tests below pin the cites,
and the facts they restated, by symbol.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import _effects_types, dps, engine

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|``:\d|\blines? \d")

TARGETS = {
    "hybrid.py": (
        "hybrid imports rank at module level (its ``from .rank import`` "
        "block), so rank cannot import hybrid.",
        'ALONE (the ``dps`` module docstring - "Ability damage is not '
        'included").',
        "auto-attack-only by design (the dps module docstring), so AD-axis",
    ),
    "_item_bonus_hp_amp.py": (
        "``bonus_ad_pct_bonus_hp``, in ``engine.build_champion``), but it has "
        "NO bonus-HP -> bonus-HP self-amp walk",
    ),
    "_item_mana_health.py": (
        "``bonus_ad_pct_max_mp``, in ``engine.build_champion``) and bonus mana "
        "-> AP (Archangel's / Seraph's ``bonus_ap_pct_bonus_mp``, the same "
        "function), but it has NO mana -> HP walk",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def test_pattern_matches_the_old_shapes():
    for sample in (
        "# hybrid imports rank (line 50), so rank cannot import hybrid.",
        'otherwise scored on auto-attack DPS ALONE (``dps.py:34`` - "Ability',
        "# (dps.py:34), so AD-axis champions never price their ability damage.",
        "``engine.py`` ~line 404), but it has NO bonus-HP -> bonus-HP self-amp",
        "``engine.py`` ~line 362) and bonus mana -> AP (Archangel's / Seraph's",
        "``bonus_ap_pct_bonus_mp``, ~line 383), but it has NO mana -> HP walk",
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


def _module_level_relative_imports(name: str) -> set:
    tree = ast.parse((DS / name).read_text(encoding="utf-8"))
    return {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.level == 1
    }


def test_hybrid_imports_rank_and_rank_does_not_import_hybrid():
    assert "rank" in _module_level_relative_imports("hybrid.py")
    assert "hybrid" not in _module_level_relative_imports("rank.py")


def test_dps_docstring_still_excludes_ability_damage():
    assert "Ability damage is **not** included" in dps.__doc__


def test_build_champion_carries_the_three_cited_walks():
    src = inspect.getsource(engine.build_champion)
    for field in ("bonus_ad_pct_bonus_hp", "bonus_ad_pct_max_mp",
                  "bonus_ap_pct_bonus_mp"):
        assert f"eff.{field}" in src, field


def test_item_effect_has_no_mana_or_bonus_hp_to_hp_field():
    names = [f.name for f in dataclasses.fields(_effects_types.ItemEffect)]
    for field in ("bonus_ad_pct_bonus_hp", "bonus_ad_pct_max_mp",
                  "bonus_ap_pct_bonus_mp"):
        assert field in names, field
    assert not [n for n in names if re.match(r"(bonus_)?hp_pct_", n)]

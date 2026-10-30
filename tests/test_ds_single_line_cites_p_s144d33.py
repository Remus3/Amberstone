"""Guard: the last RM-1053 line cites in the DS package cite by symbol (part p).

Measured 2026-10-30 at ENGINE 1.290.0. Four line cites were left in two files:

- ``_rune_shield_grants.py`` cited ``_champion_spell_shield_overrides.py:111``
  in its docstring and ``line 111`` in the ``_RUNE_GUARDIAN_SHIELD_PROB``
  comment for ``_SPELL_SHIELD_REACTIVE_PROB = 0.2``. Both still landed (the
  constant sits on :111), but a line cite rots on the next edit above it. The
  ``, line 111`` shape is singular, so the earlier guards' pattern missed it.
- ``tests/test_item_resist_grants_terminus_r67.py`` cited
  ``_effects_data.py:633-634`` for the 3302 ``armor_pen_pct=0.30`` field (now
  :641, inside a longer note) and ``_item_resist_grants.py:123`` for the
  ramping 0.5 default (now ``_ITEM_RESIST_STACK_PROB`` on :155). Both had
  rotted.

The tests below pin the cites, and the values they restated, by symbol.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agents.daemon_slayer import (
    _champion_spell_shield_overrides,
    _effects_data,
    _item_resist_grants,
    _item_spell_shield_overrides,
    _rune_shield_grants,
)

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|``:\d|\blines? \d")

TARGETS = {
    "_rune_shield_grants.py": (
        "(``_champion_spell_shield_overrides._SPELL_SHIELD_REACTIVE_PROB`` = "
        "0.2, aliased by ``_item_spell_shield_overrides._ITEM_SPELL_SHIELD_PROB"
        "``)",
        "(_champion_spell_shield_overrides._SPELL_SHIELD_REACTIVE_PROB, the "
        "same value _item_spell_shield_overrides._ITEM_SPELL_SHIELD_PROB "
        "aliases);",
    ),
    "tests/test_item_resist_grants_terminus_r67.py": (
        '(the _effects_data row "3302" armor_pen_pct=0.30 == 10%/stack x 3)',
        "ramping default of 0.5 (_item_resist_grants._ITEM_RESIST_STACK_PROB).",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def test_pattern_matches_the_old_shapes():
    for sample in (
        "declared at ``_champion_spell_shield_overrides.py:111`` and aliased by",
        "# (_champion_spell_shield_overrides._SPELL_SHIELD_REACTIVE_PROB, line 111);",
        "# (_effects_data.py:633-634 armor_pen_pct=0.30 == 10%/stack x 3), so the",
        "# ramping default of 0.5 (_item_resist_grants.py:123).",
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


def test_guardian_restates_the_reactive_spell_shield_price():
    reactive = _champion_spell_shield_overrides._SPELL_SHIELD_REACTIVE_PROB
    assert reactive == 0.2
    assert _item_spell_shield_overrides._ITEM_SPELL_SHIELD_PROB == reactive
    assert _rune_shield_grants._RUNE_GUARDIAN_SHIELD_PROB == reactive


def test_terminus_cites_resolve_to_the_stated_values():
    assert _effects_data.ITEM_EFFECTS["3302"].armor_pen_pct == pytest.approx(0.30)
    assert _item_resist_grants._ITEM_RESIST_STACK_PROB == 0.5
    light = _item_resist_grants._ITEM_RESIST_GRANTS["3302"]
    assert light.conditional_probability == 1.0

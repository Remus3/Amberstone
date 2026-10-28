"""Guard: the RM-97 pet / summon pin cites ability_dps.py by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The module docstring of
``agents/daemon_slayer/tests/test_pet_summon_damage_uncredited_rm97.py``
carried two ``ability_dps.py`` line cites, both true at 69c88f5b2 (RM-97,
2026-07-28):
- ``ability_dps.py:209`` was the ``SPELL_KEYS`` assignment; at HEAD it is
  comment prose above it, and the assignment sits near 211.
- ``ability_dps.py:459`` was the ``damage_blocks`` filter line in
  ``_select_blocks``; at HEAD it is the ``def _select_blocks(`` line, and
  the filter sits several lines lower.

The tests below pin each claim by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from agents.daemon_slayer import ability_dps

REPO = Path(__file__).resolve().parent.parent
TARGET = (
    REPO / "agents" / "daemon_slayer" / "tests"
    / "test_pet_summon_damage_uncredited_rm97.py"
)
_LINE_CITE = re.compile(r"(?<![\w.])ability_dps\.py:\d")


def _target() -> str:
    return TARGET.read_text(encoding="utf-8")


def test_pattern_matches_the_rotted_shape():
    assert _LINE_CITE.search("(``agents/daemon_slayer/ability_dps.py:209``)")
    assert _LINE_CITE.search("* ``ability_dps.py:459`` ``_select_blocks``")
    for sample in (
        "``ability_dps._select_blocks``",
        "a dps.py:12 cite belongs to another guard",
        "an abilities.py:274 cite is not this pattern",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_ability_dps_line_cite_left_in_rm97():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(_target().splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_rm97_names_each_symbol():
    src = _target()
    for symbol in ("``ability_dps.SPELL_KEYS``", "``ability_dps._select_blocks``"):
        assert symbol in src, symbol


def test_spell_keys_still_exclude_the_passive():
    assert ability_dps.SPELL_KEYS == ("Q", "W", "E", "R")
    assert "P" not in ability_dps.SPELL_KEYS


def test_select_blocks_still_filters_and_returns_zero():
    src = inspect.getsource(ability_dps._select_blocks)
    assert 'b.attribute_kind == "damage"' in src
    assert "if not damage_blocks:\n        return 0.0" in src

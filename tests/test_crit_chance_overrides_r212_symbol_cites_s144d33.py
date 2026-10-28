"""Guard: the R212 crit-chance test cites by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The module docstring of
``agents/daemon_slayer/tests/test_crit_chance_overrides_r212.py`` placed the
basic-attack crit product at ``dps.py:893``, and a comment above
``_NOTE_INFINITY_EDGE_CRIT_DAMAGE`` placed Infinity Edge's shipped
``crit_damage_bonus=0.30`` at ``_effects_data.py:33``. Both were written by
367a5e37f (R212). The dps.py cite was already wrong that day (line 893 sat
inside the mode-modifier block); at HEAD it is a comment line and the
``crit_bonus = DEFAULT_CRIT_BONUS + total_crit_damage_bonus(item_effects)``
line sits about a hundred lines lower. The _effects_data.py cite named IE's
``name=`` line, one above the field it meant.

The tests below pin the cites and the claims by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from agents.daemon_slayer import dps
from agents.daemon_slayer._effects_data import ITEM_EFFECTS

REPO = Path(__file__).resolve().parent.parent
TARGET = (
    REPO / "agents" / "daemon_slayer" / "tests"
    / "test_crit_chance_overrides_r212.py"
)
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d")


def _target() -> str:
    return TARGET.read_text(encoding="utf-8")


def test_pattern_matches_the_rotted_shapes():
    assert _LINE_CITE.search("total_crit_damage_bonus(items)`` (``dps.py:893``)")
    assert _LINE_CITE.search("the SHIPPED ``_effects_data.py:33`` IE")
    for sample in (
        "(``dps.compute_dps``)",
        '``_effects_data.ITEM_EFFECTS["3031"]``',
        "no live :8860, no network",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_the_r212_test():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(_target().splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_r212_test_names_both_symbols():
    text = _target()
    assert "``dps.compute_dps``" in text
    assert '``_effects_data.ITEM_EFFECTS["3031"]``' in text


def test_compute_dps_builds_the_cited_crit_bonus():
    src = inspect.getsource(dps.compute_dps)
    assert (
        "crit_bonus = DEFAULT_CRIT_BONUS + total_crit_damage_bonus(item_effects)"
        in src
    )
    assert dps.DEFAULT_CRIT_BONUS == 0.75


def test_infinity_edge_ships_the_cited_crit_damage_bonus():
    ie = ITEM_EFFECTS["3031"]
    assert ie.name == "Infinity Edge"
    assert ie.crit_damage_bonus == 0.30

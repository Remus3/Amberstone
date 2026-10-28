"""Guard: the RM-36 dual-scaling split pin cites ability_dps.py by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The module docstring of
``agents/daemon_slayer/tests/test_ad_axis_dual_scaling_split_rm36.py``
carried one ``ability_dps.py`` line cite, true at 78a72c0e8 (RM-36,
2026-08-04):
- ``ability_dps.py:385`` was the MIXED 50/50 return line of
  ``_mitigation_factor``; at HEAD it is the PHYSICAL return two lines
  above it, after the function's docstring grew.

The tests below pin the claim by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from agents.daemon_slayer import ability_dps

REPO = Path(__file__).resolve().parent.parent
TARGET = (
    REPO / "agents" / "daemon_slayer" / "tests"
    / "test_ad_axis_dual_scaling_split_rm36.py"
)
_LINE_CITE = re.compile(r"(?<![\w.])ability_dps\.py:\d")


def _target() -> str:
    return TARGET.read_text(encoding="utf-8")


def test_pattern_matches_the_rotted_shape():
    assert _LINE_CITE.search("(``ability_dps.py:385``); the difference")
    for sample in (
        "``ability_dps._mitigation_factor``",
        "a dps.py:34 cite belongs to another guard",
        "a _mana_ability_dps.py:12 cite is not this pattern",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_ability_dps_line_cite_left_in_rm36():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(_target().splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_rm36_names_the_symbol():
    assert "``ability_dps._mitigation_factor``" in _target()


def test_mitigation_factor_still_splits_mixed_50_50():
    src = inspect.getsource(ability_dps._mitigation_factor)
    assert 'if dt == "MIXED":' in src
    assert (
        "return 0.5 * _armor_factor(target_armor) + 0.5 * _armor_factor(target_mr)"
        in src
    )
    mixed = ability_dps._mitigation_factor("MIXED", 100.0, 60.0)
    phys = ability_dps._mitigation_factor("PHYSICAL", 100.0, 60.0)
    magic = ability_dps._mitigation_factor("MAGIC", 100.0, 60.0)
    assert abs(mixed - (0.5 * phys + 0.5 * magic)) < 1e-12

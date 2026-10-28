"""Guard: the R69 and R74 DS burst tests cite by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0 (cited -> line before this edit).
test_item_active_magic_burst_r69.py and test_item_physical_burst_r74.py
lean on the same claim: ``defensive_only`` is documentation-only, so
``collect_effects`` hands a defensive_only entry to the burst facades like
any other. Every line cite behind that claim had drifted: the field
``_effects_types.py:687`` -> 746, its bullet ``effects.py:23`` -> 24,
``collect_effects`` ``effects.py:72-83`` -> a def at 245, and the ehp
docstring mention ``ehp.py:71`` -> 77. A cite that resolves today rots on
the next insert above it, so all of them go.

The tests below pin the claim itself, so an engine consumer that starts
filtering on the flag turns this red rather than leaving the prose stale.
"""
from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path

from agents.daemon_slayer import effects, ehp
from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import ItemEffect
from agents.daemon_slayer.effects import (
    collect_effects,
    total_magic_burst_damage,
    total_physical_burst_damage,
)

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGETS = (
    DS / "tests" / "test_item_active_magic_burst_r69.py",
    DS / "tests" / "test_item_physical_burst_r74.py",
)
# ``effects.py:72-83`` and ``_effects_types.py:687``. Not the port shape
# ``:8860``, which is no cite.
_LINE_CITE = re.compile(r"\w\.(?:py|md):\d|\bat line \d")
_FLAG = "defensive_only"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "documentation-only (defined _effects_types.py:687; described",
        "effects.py:23) - no engine consumer in rank/dps/burst/effects filters on",
        "it, and ``collect_effects`` (effects.py:72-83) passes every registered",
        "R69, re-verified R74: only docstring prose in effects.py:23 + ehp.py:71),",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "``ItemEffect.defensive_only`` in ``_effects_types.py``",
        "the module docstrings of ``effects.py`` and ``ehp.py``",
        "DS ``:8860`` serves the main checkout",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_targets():
    hits = [
        f"{path.name}:{n}: {line.strip()}"
        for path in TARGETS
        for n, line in enumerate(_source(path).splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_flag_is_an_item_effect_field_defaulting_false():
    fields = {f.name: f for f in dataclasses.fields(ItemEffect)}
    assert fields[_FLAG].default is False


def test_flag_is_described_in_the_effects_and_ehp_docstrings():
    assert f"``{_FLAG}``" in (effects.__doc__ or "")
    assert _FLAG in (ehp.__doc__ or "")


def test_no_engine_module_reads_the_flag():
    readers = []
    for path in sorted(DS.glob("*.py")):
        for node in ast.walk(ast.parse(_source(path))):
            if isinstance(node, ast.Attribute) and node.attr == _FLAG:
                readers.append(f"{path.name}:{node.lineno}")
            elif (
                isinstance(node, ast.Constant)
                and node.value == _FLAG
            ):
                readers.append(f"{path.name}:{node.lineno}")
    assert not readers, "defensive_only gained a consumer:\n" + "\n".join(readers)


def test_collect_effects_passes_defensive_only_bursts_through():
    for item_id in ("3152", "223152", "446656"):
        eff = ITEM_EFFECTS[item_id]
        assert eff.defensive_only, item_id
        assert collect_effects([item_id]) == [eff], item_id
        assert total_magic_burst_damage(collect_effects([item_id]), 100.0) > 0.0
    gore = ITEM_EFFECTS["226630"]
    assert gore.defensive_only
    assert collect_effects(["226630"]) == [gore]
    assert total_physical_burst_damage(collect_effects(["226630"]), 60.0) > 0.0

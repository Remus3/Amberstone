"""Guard: ehp.py cites dps.py / engine.py by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. ehp.py carried seven line cites on
six lines into dps.py and engine.py, written by c69a575df (R193 slice B) and
4e4c45269 (R194 slice C):
- ``dps.py:1283`` (three times) was the ``raw_attack_dps = ad * eff_as *
  (1 + crit * crit_bonus)`` line at c69a575df, one below the per-hit
  ``avg_attack_dmg`` line the prose describes; at HEAD it is a crit-override
  f-string and ``avg_attack_dmg`` sits about 210 lines lower in
  ``dps.compute_dps``.
- ``dps.py:1083`` (twice) was the ``crit_total = min(raw_crit +
  crit_from_effects, 1.0)`` fold; at HEAD it is an R111 Bloodmail comment.
- ``engine.py:185`` was the "Crit capped at 1.0" docstring line of
  ``engine._combine_items``; at HEAD it is a "Special cases" line.
- ``dps.py:40`` still lands on the module docstring's
  ``CallContext.targets_in_rotation`` line, but it rots on the next insert
  above it, so it goes too.

The tests below pin each claim by symbol instead.
"""
from __future__ import annotations

import dataclasses
import inspect
import re
from pathlib import Path

from agents.daemon_slayer import dps, engine, ehp
from agents.daemon_slayer._effects_types import CallContext

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "agents" / "daemon_slayer" / "ehp.py"
# ``dps.py:1283`` / ``engine.py:185``. Other ehp.py cites are out of scope.
_LINE_CITE = re.compile(r"(?<![\w.])(?:dps|engine)\.py:\d")


def _target() -> str:
    return TARGET.read_text(encoding="utf-8")


def test_pattern_matches_the_rotted_shape():
    assert _LINE_CITE.search("the expression DS already ships at dps.py:1283)")
    assert _LINE_CITE.search("the engine's crit cap at engine.py:185)")
    for sample in (
        "``dps.compute_dps``'s ``avg_attack_dmg``",
        "an ability_dps.py:12 cite belongs to another guard",
        "no live :8860, no network",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_dps_or_engine_line_cite_left_in_ehp():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(_target().splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_ehp_names_each_symbol():
    src = _target()
    for symbol in (
        "``dps.compute_dps``",
        "``avg_attack_dmg``",
        "``crit_total``",
        "``crit_bonus``",
        "``engine._combine_items``",
        "``CallContext.targets_in_rotation``",
    ):
        assert symbol in src, symbol


def test_compute_dps_carries_the_cited_expressions():
    src = inspect.getsource(dps.compute_dps)
    assert "crit_total = min(raw_crit + crit_from_effects, 1.0)" in src
    assert "crit_bonus = DEFAULT_CRIT_BONUS + total_crit_damage_bonus(item_effects)" in src
    assert "avg_attack_dmg = ad * (1 + crit * crit_bonus)" in src


def test_combine_items_caps_crit_at_one():
    src = inspect.getsource(engine._combine_items)
    assert 'if out.get("crit", 0.0) > 1.0:' in src
    assert 'out["crit"] = 1.0' in src


def test_call_context_carries_targets_in_rotation():
    fields = {f.name: f for f in dataclasses.fields(CallContext)}
    assert fields["targets_in_rotation"].default == 1.0
    assert "``CallContext.targets_in_rotation``" in inspect.getdoc(dps)


def test_multiplier_mirrors_the_dps_expressions():
    src = inspect.getsource(ehp._crit_weighted_vamp_multiplier)
    assert "crit_total = min(max(0.0, crit_chance) + max(0.0, crit_from_effects), 1.0)" in src
    assert "crit_bonus = max(0.0, DEFAULT_CRIT_BONUS + total_crit_damage_bonus(effects))" in src
    assert "return 1.0 + crit_total * crit_bonus" in src


def test_multiplier_is_identity_when_off_and_crit_weighted_when_on():
    assert ehp._crit_weighted_vamp_multiplier([], 0.5) == 1.0
    on = ehp._crit_weighted_vamp_multiplier([], 0.5, assume_crit_weighted_vamp=True)
    assert on == 1.0 + 0.5 * dps.DEFAULT_CRIT_BONUS

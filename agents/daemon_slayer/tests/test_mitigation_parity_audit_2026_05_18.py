"""Drift guard: ability_dps._mitigation_factor must stay folded onto the
single source of truth dps._armor_factor.

Audit 2026-05-18 finding #5. Before this, ability_dps carried a local
copy of League's resist->multiplier curve. A one-sided edit would have
silently desynced the DPS / ability-DPS / burst scorers (burst.py
imports from ability_dps). These tests fail loudly the moment the two
implementations diverge again.
"""
from __future__ import annotations

import math

from agents.daemon_slayer.ability_dps import _mitigation_factor
from agents.daemon_slayer.dps import _armor_factor

# Sweep both signs + the >=0 branch boundary + large values.
_RESISTS = [-200.0, -100.0, -50.0, -1.0, 0.0, 1.0, 25.0, 80.0, 100.0, 300.0, 999.0]


def test_physical_routes_to_armor_factor():
    for a in _RESISTS:
        assert _mitigation_factor("PHYSICAL", a, 0.0) == _armor_factor(a)


def test_magic_routes_to_armor_factor_on_mr():
    for mr in _RESISTS:
        assert _mitigation_factor("MAGIC", 0.0, mr) == _armor_factor(mr)


def test_none_and_unknown_default_to_magic():
    for mr in _RESISTS:
        assert _mitigation_factor(None, 12.3, mr) == _armor_factor(mr)
        assert _mitigation_factor("WeirdType", 12.3, mr) == _armor_factor(mr)


def test_true_bypasses_all_resists():
    for a in _RESISTS:
        for mr in _RESISTS:
            assert _mitigation_factor("TRUE", a, mr) == 1.0


def test_mixed_is_half_armor_half_mr():
    for a in _RESISTS:
        for mr in _RESISTS:
            expected = 0.5 * _armor_factor(a) + 0.5 * _armor_factor(mr)
            assert math.isclose(
                _mitigation_factor("MIXED", a, mr), expected, rel_tol=0, abs_tol=0
            )


def test_case_insensitive_damage_type():
    assert _mitigation_factor("physical", 50.0, 0.0) == _armor_factor(50.0)
    assert _mitigation_factor("true", 50.0, 50.0) == 1.0


def test_negative_resist_branch_matches_formula():
    # Pin the actual League negative-resist curve so a future edit to
    # _armor_factor itself (not just drift between the two) is also caught.
    assert _armor_factor(-100.0) == 2.0 - 100.0 / (100.0 - (-100.0))
    assert _mitigation_factor("PHYSICAL", -100.0, 0.0) == 1.5

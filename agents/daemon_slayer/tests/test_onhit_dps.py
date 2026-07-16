"""Slice B Task 1 (2026-07-16) - on-hit AP combined-DPS scorer test.

Exercises ``compute_onhit_dps``: the exact-sum invariant against the two
composed engine primitives (``compute_ability_dps`` + ``compute_dps``) on a
real on-hit AP build (Gwen: Nashor's Tooth + Rabadon's Deathcap). Mirrors
the shape of ``test_only_phase_hot01.py`` / ``test_ability_dps.py`` -
``DataSnapshot.load()`` is the real (non-mocked) snapshot loader idiom used
across the DS test suite; there is no ``load_default_snapshot()`` helper.
"""
from __future__ import annotations

from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.onhit_dps import compute_onhit_dps

# Nashor's Tooth + Rabadon's - an on-hit AP build for Gwen.
_GWEN_BUILD = ("3115", "3089")


def test_onhit_dps_is_exact_sum_of_two_halves():
    snap = DataSnapshot.load()
    res = compute_onhit_dps(
        snap, "Gwen", level=13, item_ids=_GWEN_BUILD, mode="SR",
        target_armor=105.0, target_mr=52.0, target_max_hp=2430.0,
    )
    ability = compute_ability_dps(
        snap, champion_id="Gwen", level=13, item_ids=_GWEN_BUILD, mode="SR",
        target_armor=105.0, target_mr=52.0, target_max_hp=2430.0,
    ).total_ability_dps
    auto = compute_dps(
        snap, champion_id="Gwen", level=13, item_ids=_GWEN_BUILD, mode="SR",
        target_armor=105.0, target_mr=52.0, target_max_hp=2430.0,
    ).weighted_dps
    assert res.ability_dps == ability
    assert res.auto_dps == auto
    assert res.onhit_dps == ability + auto
    # Both halves are material for an on-hit AP champ (the whole point).
    assert res.ability_dps > 0.0
    assert res.auto_dps > 0.0

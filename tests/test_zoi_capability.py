"""Tests for core.zoi_capability - archetype capability weight multiplier
(ZOI district orchestration, spec F, wave 3b).

Pure fail-soft function: capability_weight(champion, level, game_time_s) -> float
in a documented band (~[0.6, 1.6]). Assassin/carry scale UP with game_time;
tank/enchanter frontload/flatten. Unknown champ / None -> 1.0 neutral.

Synthetic fixtures only. Grep-confirmed API surface:
  - core.archetype_picks.get_archetype_for(champion, prefer_aram_win_axis=False)
    -> {"primary": one of carry/bruiser/tank/mage/assassin/enchanter, ...}
    (core/archetype_picks.py:592, return shape core/archetype_picks.py:59).
"""
import math

import pytest

from core.zoi_capability import (
    CAP_MAX,
    CAP_MIN,
    capability_weight,
)


# --- band + fail-soft guards ---------------------------------------------

def test_unknown_champ_neutral():
    assert capability_weight("ThisChampDoesNotExist_xyz") == 1.0


def test_none_champ_neutral():
    assert capability_weight(None) == 1.0


def test_empty_champ_neutral():
    assert capability_weight("") == 1.0


def test_garbage_champ_neutral():
    # non-string junk must not raise, must return neutral 1.0
    assert capability_weight(12345) == 1.0
    assert capability_weight({"x": 1}) == 1.0
    assert capability_weight(["Zed"]) == 1.0


def test_weight_always_in_band():
    # sweep a spread of champs / levels / times - never leaves the band
    champs = ["Zed", "Jinx", "Malphite", "Lulu", "Aatrox", "Lux", None, "junk_x"]
    for champ in champs:
        for lvl in (None, 1, 6, 11, 16, 18):
            for t in (None, 0, 300, 900, 1500, 3000):
                w = capability_weight(champ, level=lvl, game_time_s=t)
                assert isinstance(w, float)
                assert math.isfinite(w)
                assert CAP_MIN <= w <= CAP_MAX


def test_bad_numeric_inputs_neutralish():
    # NaN / inf / bool time or level must not raise
    w = capability_weight("Zed", level=float("nan"), game_time_s=float("inf"))
    assert math.isfinite(w)
    assert CAP_MIN <= w <= CAP_MAX


# --- archetype curve shape ------------------------------------------------

def test_assassin_scales_up_with_time():
    # Zed -> assassin. Late game weight must exceed early game.
    early = capability_weight("Zed", game_time_s=0)
    late = capability_weight("Zed", game_time_s=1800)
    assert late > early


def test_carry_scales_up_with_time():
    # Jinx -> carry. Late game weight must exceed early game.
    early = capability_weight("Jinx", game_time_s=0)
    late = capability_weight("Jinx", game_time_s=1800)
    assert late > early


def test_tank_flat_or_frontloaded():
    # Malphite -> tank. Tanks frontload: late must NOT exceed early.
    early = capability_weight("Malphite", game_time_s=0)
    late = capability_weight("Malphite", game_time_s=1800)
    assert late <= early


def test_enchanter_flat_or_frontloaded():
    # Lulu -> enchanter. Frontloaded: late must NOT exceed early.
    early = capability_weight("Lulu", game_time_s=0)
    late = capability_weight("Lulu", game_time_s=1800)
    assert late <= early


def test_assassin_late_beats_tank_late():
    # By late game an assassin's scaling weight tops a tank's flattened weight.
    assassin_late = capability_weight("Zed", game_time_s=1800)
    tank_late = capability_weight("Malphite", game_time_s=1800)
    assert assassin_late > tank_late


def test_level_only_still_scales_assassin():
    # game_time_s absent but level present: assassin still scales up with level.
    lo = capability_weight("Zed", level=1)
    hi = capability_weight("Zed", level=16)
    assert hi > lo


def test_no_signal_is_neutral_ish():
    # Known champ, no level, no time -> a finite in-band base (not a crash).
    w = capability_weight("Zed")
    assert math.isfinite(w)
    assert CAP_MIN <= w <= CAP_MAX

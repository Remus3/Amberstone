"""True-audit s144 cycle 167: coach_integration.enemy_stats on junk input.

``compute_enemy_stats`` runs on every SR / ARAM / Arena / Brawl coach tick
(the DS pre-call) and on four dashboard preview routes. Its contract is "always
non-negative, capped" stats. Each test below is named for one weakness the
audit found; each was RED before the hardening:

- a NaN level, enemy level or game clock produced NaN armor / mr / max_hp /
  bonus_hp and handed it to the DS engine;
- a junk level / clock / mode / enemy entry raised, so the caller's broad
  except dropped the whole DS pick list for that tick;
- a one-shot iterable of enemy champions was consumed by the tank count, so the
  no-comp guard and the AD/AP split saw an empty comp;
- a bare string comp was classified letter by letter;
- the live "?" placeholder (coaches write it for a missing championName), or
  any comp DDragon cannot resolve, read as a known all-squishy comp and earned
  the blind 0.90 discount the guard exists to prevent;
- a junk bonus_hp override (inf, a bool, a string) replaced the heuristic;
- a negative enemy level dragged the average down.
"""
from __future__ import annotations

import math

import pytest

import coach_integration.enemy_stats as es_mod
from coach_integration.enemy_stats import EnemyStats, compute_enemy_stats

_SR_L11 = compute_enemy_stats("sr", level=11)  # armor 95, mr 63, max_hp 2210
_TANKS = ["Malphite", "Ornn", "Sion", "Zac", "Garen"]


def _all_finite(s: EnemyStats) -> bool:
    return all(
        math.isfinite(v)
        for v in (s.armor, s.mr, s.max_hp, s.bonus_hp, s.ad_share,
                  s.ap_share, s.hp_scale)
    )


# ---- NaN never reaches DS -------------------------------------------------

def test_nan_level_falls_back_to_clock_not_nan():
    s = compute_enemy_stats("sr", game_seconds=900, level=float("nan"))
    assert _all_finite(s)
    # 900 s -> level 11 on the clock curve -> armor 95.
    assert s.armor == 95.0


def test_inf_level_is_junk_not_level_18():
    s = compute_enemy_stats("sr", game_seconds=900, level=float("inf"))
    assert s.armor == 95.0


def test_nan_game_seconds_reads_as_level_one():
    s = compute_enemy_stats("sr", game_seconds=float("nan"))
    assert _all_finite(s)
    assert s.armor == 45.0  # SR level 1


def test_nan_enemy_level_entry_is_dropped():
    s = compute_enemy_stats("sr", level=1, enemy_levels=[11, float("nan"), 11])
    assert _all_finite(s)
    assert s.armor == 95.0


def test_all_nan_enemy_levels_fall_back_to_level():
    s = compute_enemy_stats("sr", level=11, enemy_levels=[float("nan")])
    assert s.armor == 95.0


# ---- junk never raises ----------------------------------------------------

@pytest.mark.parametrize("junk", ["abc", {"lvl": 3}, [11], object()])
def test_junk_level_never_raises(junk):
    s = compute_enemy_stats("sr", game_seconds=900, level=junk)
    assert s.armor == 95.0


def test_numeric_string_level_still_accepted():
    # Pre-hardening float("11") worked; keep that.
    assert compute_enemy_stats("sr", level="11").armor == 95.0


@pytest.mark.parametrize("junk", [None, "abc", {"t": 1}])
def test_junk_game_seconds_never_raises(junk):
    s = compute_enemy_stats("sr", game_seconds=junk)
    assert s.armor == 45.0


def test_junk_enemy_level_entries_are_dropped():
    s = compute_enemy_stats(
        "sr", level=1, enemy_levels=[11, "abc", {"x": 1}, None, True, 11],
    )
    assert s.armor == 95.0


def test_non_iterable_enemy_levels_falls_back_to_level():
    assert compute_enemy_stats("sr", level=11, enemy_levels=7).armor == 95.0


def test_string_enemy_levels_is_not_read_as_digits():
    # Pre-hardening "11" iterated as ["1", "1"] -> two level-1 enemies.
    assert compute_enemy_stats("sr", level=11, enemy_levels="11").armor == 95.0


def test_huge_int_enemy_level_never_raises():
    s = compute_enemy_stats("sr", level=11, enemy_levels=[10 ** 400])
    assert _all_finite(s)


def test_negative_enemy_level_does_not_drag_average():
    s = compute_enemy_stats("sr", level=1, enemy_levels=[11, -40, 11])
    assert s.armor == 95.0


@pytest.mark.parametrize("junk", [7, 3.5, b"aram", ["aram"]])
def test_non_str_mode_reads_as_sr(junk):
    assert compute_enemy_stats(junk, level=11).armor == _SR_L11.armor


@pytest.mark.parametrize("bad", [5, {"championName": "Zed"}, ["Zed"]])
def test_non_str_champion_entry_never_raises(bad):
    s = compute_enemy_stats(
        "sr", level=11, enemy_champions=["Malphite", bad, "Ornn"],
        comp_hp_lean=True,
    )
    assert s.tanky_count == 2


# ---- the comp is read once, as names --------------------------------------

def test_generator_comp_is_not_consumed_before_the_guard():
    as_list = compute_enemy_stats(
        "sr", level=11, enemy_champions=list(_TANKS), comp_hp_lean=True,
    )
    as_gen = compute_enemy_stats(
        "sr", level=11, enemy_champions=(c for c in _TANKS), comp_hp_lean=True,
    )
    assert as_list.hp_scale > 1.0
    assert as_gen == as_list


def test_generator_comp_still_feeds_ad_ap_split():
    names = ["Zed", "Jinx", "Tryndamere", "Darius", "Garen"]
    as_list = compute_enemy_stats("sr", level=12, enemy_champions=names)
    as_gen = compute_enemy_stats("sr", level=12, enemy_champions=iter(names))
    assert as_list.ad_share > 0.5
    assert as_gen.ad_share == as_list.ad_share


def test_bare_string_comp_is_one_name_not_letters():
    one = compute_enemy_stats("sr", level=11, enemy_champions="Malphite",
                              comp_hp_lean=True)
    listed = compute_enemy_stats("sr", level=11, enemy_champions=["Malphite"],
                                 comp_hp_lean=True)
    assert one == listed


def test_placeholder_only_comp_is_no_info_neutral():
    # aram_coach / brawl_coach write "?" for an enemy with no championName.
    s = compute_enemy_stats("sr", level=11, enemy_champions=["?"] * 5,
                            comp_hp_lean=True)
    assert s.hp_scale == 1.0
    assert s.max_hp == _SR_L11.max_hp


def test_unresolvable_only_comp_is_no_info_neutral():
    s = compute_enemy_stats("sr", level=11,
                            enemy_champions=["NotAChamp", "Zzz"],
                            comp_hp_lean=True)
    assert s.hp_scale == 1.0
    assert s.max_hp == _SR_L11.max_hp


def test_placeholder_does_not_block_a_known_comp():
    known = compute_enemy_stats("sr", level=11, enemy_champions=list(_TANKS),
                                comp_hp_lean=True)
    mixed = compute_enemy_stats("sr", level=11,
                                enemy_champions=list(_TANKS) + ["?"],
                                comp_hp_lean=True)
    assert mixed.hp_scale == known.hp_scale > 1.0


# ---- bonus_hp override ----------------------------------------------------

@pytest.mark.parametrize("junk", [float("inf"), float("nan"), True, "abc",
                                  {"hp": 1}])
def test_junk_bonus_hp_override_uses_heuristic(junk):
    s = compute_enemy_stats("sr", level=11, bonus_hp_override=junk)
    assert s.bonus_hp == _SR_L11.bonus_hp


def test_numeric_string_bonus_hp_override_is_read_as_a_number():
    # One numeric reader for every input: "500" means 500, like level "11".
    assert compute_enemy_stats("sr", level=11,
                               bonus_hp_override="500").bonus_hp == 500.0


# ---- AD/AP split stays a split --------------------------------------------

def test_negative_factor_counts_never_leave_unit_range(monkeypatch):
    import core.aram_comp_verdict as acv

    monkeypatch.setattr(
        acv, "compute_factors",
        lambda names: {"n": 2, "ad_count": -1, "ap_count": 2,
                       "hybrid_count": 0},
    )
    s = compute_enemy_stats("sr", level=11, enemy_champions=["Zed", "Lux"])
    assert (s.ad_share, s.ap_share) == (0.5, 0.5)


def test_non_dict_factors_read_as_no_comp(monkeypatch):
    import core.aram_comp_verdict as acv

    monkeypatch.setattr(acv, "compute_factors", lambda names: ["n", 5])
    s = compute_enemy_stats("sr", level=11, enemy_champions=list(_TANKS),
                            comp_hp_lean=True)
    assert (s.ad_share, s.ap_share, s.hp_scale) == (0.5, 0.5, 1.0)


def test_raising_factors_read_as_no_comp(monkeypatch):
    import core.aram_comp_verdict as acv

    def _boom(names):
        raise RuntimeError("ddragon cache unreadable")

    monkeypatch.setattr(acv, "compute_factors", _boom)
    s = compute_enemy_stats("sr", level=11, enemy_champions=list(_TANKS),
                            comp_hp_lean=True)
    assert (s.ad_share, s.ap_share, s.hp_scale) == (0.5, 0.5, 1.0)


def test_module_still_exports_the_public_names():
    assert es_mod.compute_enemy_stats is compute_enemy_stats
    assert es_mod.EnemyStats is EnemyStats

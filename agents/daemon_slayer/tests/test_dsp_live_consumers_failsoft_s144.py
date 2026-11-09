"""S144-T-570: dsp_live_consumers keeps its "fail-soft" contract on bad input.

The module promises "Contract: fail-soft (never raises)" and per function
"unknown ids contribute 0.0", but before this slice:

  * a junk id (``"x"``, ``None``) raised ValueError / TypeError out of
    ``summoner_fight_adjustments`` and ``enemy_rune_threat``;
  * a bare string id set was iterated per CHARACTER, so ``"14"`` (Ignite)
    read as Cleanse (1) + Flash (4); a bare int raised TypeError; a ``True``
    element read as Cleanse; a fractional float id was truncated;
  * ``enemy_max_hp=None`` raised TypeError and a non-finite HP leaked
    ``inf`` / ``nan`` into ``poke_sustain_hp``;
  * ``antiheal_present="false"`` armed the 40 percent antiheal;
  * a non-finite / non-number ``level`` gave inconsistent garbage (NaN read
    one way, inf another);
  * a ``granter_resists`` value that was not a list of numbers (``5``,
    ``[None]``) raised TypeError, which ``/ally-protected-ehp`` does not map,
    so the DS :8860 route answered 500; a bool resist read as 1.0;
  * a bare string ``ally_grant_champions`` was iterated per character, so
    ``"Janna"`` granted nothing.

The golden block pins valid-input outputs captured BEFORE the rewrite, so the
hardening is proven byte-identical on well-formed input (no ENGINE bump).
"""
from __future__ import annotations

import math
from dataclasses import asdict

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dsp_live_consumers import (
    ally_protected_ehp,
    enemy_rune_threat,
    summoner_fight_adjustments,
)

_IGNITE, _EXHAUST, _HEAL, _BARRIER, _CLEANSE, _GHOST = 14, 3, 7, 21, 1, 6
_PTA, _CONQ, _GRASP, _SECOND_WIND = 8005, 8010, 8437, 8444
_NAN, _INF = float("nan"), float("inf")


@pytest.fixture(scope="module")
def snap() -> DataSnapshot:
    return DataSnapshot.load()


def _ehp(r):
    return (r.physical_ehp, r.magical_ehp, r.blended_ehp)


# --- golden: valid input is byte-identical to the pre-rewrite module ---------

_SFA_GOLDEN = {
    1: {"self_ehp_bonus": 180.0, "self_cc_discount_pct": 0.75,
        "self_ms_pct": 0.3, "self_incoming_dr_pct": 0.35,
        "enemy_antiheal_pct": 0.4},
    11: {"self_ehp_bonus": 573.1470588235294, "self_cc_discount_pct": 0.75,
         "self_ms_pct": 0.3977647058823529, "self_incoming_dr_pct": 0.35,
         "enemy_antiheal_pct": 0.4},
    18: {"self_ehp_bonus": 848.35, "self_cc_discount_pct": 0.75,
         "self_ms_pct": 0.5082, "self_incoming_dr_pct": 0.35,
         "enemy_antiheal_pct": 0.4},
}
_ERT_RAMP = {1: 21.6, 11: 37.129411764705885, 18: 48.0}


@pytest.mark.parametrize("level", [1, 11, 18])
def test_golden_summoner_valid_input_unchanged(level):
    got = summoner_fight_adjustments(
        [_HEAL, _BARRIER, _GHOST, _CLEANSE, _EXHAUST], [_IGNITE, _EXHAUST], level)
    assert asdict(got) == _SFA_GOLDEN[level]


@pytest.mark.parametrize("level", [1, 11, 18])
def test_golden_enemy_rune_valid_input_unchanged(level):
    got = enemy_rune_threat(
        [_PTA, _CONQ, _GRASP, _SECOND_WIND], level, antiheal_present=True,
        enemy_max_hp=2000.0, enemy_missing_hp=500.0)
    assert asdict(got) == {
        "incoming_amp_pct": 0.08, "damage_ramp": _ERT_RAMP[level],
        "poke_sustain_hp": 51.0, "antiheal_pct": 0.4, "ehp_divisor": 1.08,
    }


def test_golden_ally_protected_valid_input_unchanged(snap):
    got = ally_protected_ehp(
        snap, "Jinx", 11, ally_grant_champions=["Janna", "Orianna", "Taric"],
        granter_resists={"Taric": (120.0, 70.0, 40.0, 32.0)}, mode="SR")
    assert _ehp(got) == (2804.19725625, 2335.888221875, 2570.0427390625)


# --- DSP5 summoner ids -------------------------------------------------------

def test_summoner_junk_ids_drop_instead_of_raising():
    clean = summoner_fight_adjustments([_HEAL], [_IGNITE], 11)
    dirty = summoner_fight_adjustments(
        ["x", None, _HEAL, object()], [None, "junk", _IGNITE], 11)
    assert dirty == clean


def test_summoner_numeric_string_id_is_read():
    assert summoner_fight_adjustments([" 1 "]).self_cc_discount_pct == 0.75


def test_summoner_bare_string_is_one_id_not_characters():
    # "14" is Ignite; per-character iteration read it as Cleanse + Flash.
    assert summoner_fight_adjustments("14").self_cc_discount_pct == 0.0
    assert summoner_fight_adjustments((), "14").enemy_antiheal_pct == 0.40
    assert summoner_fight_adjustments("1").self_cc_discount_pct == 0.75


def test_summoner_bare_int_is_one_id():
    assert summoner_fight_adjustments(_CLEANSE).self_cc_discount_pct == 0.75
    assert summoner_fight_adjustments((), _IGNITE).enemy_antiheal_pct == 0.40


def test_summoner_bool_id_is_not_cleanse():
    assert summoner_fight_adjustments([True]).self_cc_discount_pct == 0.0


def test_summoner_float_ids_integral_kept_fractional_dropped():
    assert summoner_fight_adjustments([1.0]).self_cc_discount_pct == 0.75
    assert summoner_fight_adjustments([1.5]).self_cc_discount_pct == 0.0
    assert summoner_fight_adjustments([_NAN, _INF]).self_cc_discount_pct == 0.0


def test_summoner_non_iterable_object_is_empty():
    assert asdict(summoner_fight_adjustments(object(), 3.5)) == asdict(
        summoner_fight_adjustments())


@pytest.mark.parametrize("bad", [_NAN, _INF, -_INF, None, "x", True, [11]])
def test_summoner_bad_level_reads_as_default_level(bad):
    ids = ([_HEAL, _BARRIER, _GHOST], [_IGNITE])
    assert summoner_fight_adjustments(*ids, bad) == summoner_fight_adjustments(
        *ids, 1.0)


# --- DSP6 enemy runes --------------------------------------------------------

def test_enemy_rune_one_junk_id_keeps_the_others():
    t = enemy_rune_threat(["x", None, _PTA])
    assert t.incoming_amp_pct == 0.08
    assert t.ehp_divisor == 1.08


def test_enemy_rune_bare_int_is_one_id():
    assert enemy_rune_threat(_PTA).incoming_amp_pct == 0.08


def test_enemy_rune_bare_string_is_one_id():
    assert enemy_rune_threat(str(_PTA)).incoming_amp_pct == 0.08


def test_enemy_rune_none_max_hp_does_not_raise():
    t = enemy_rune_threat([_GRASP, _SECOND_WIND], enemy_max_hp=None,
                          enemy_missing_hp=None)
    assert t.poke_sustain_hp == 0.0


@pytest.mark.parametrize("bad", [_NAN, _INF, -_INF, "x", True])
def test_enemy_rune_bad_max_hp_is_zero_hp(bad):
    t = enemy_rune_threat([_GRASP, _SECOND_WIND], enemy_max_hp=bad,
                          enemy_missing_hp=500.0)
    assert t.poke_sustain_hp == 0.0


@pytest.mark.parametrize("bad", [_NAN, _INF, -_INF, None, "x", True])
def test_enemy_rune_bad_missing_hp_is_zero_missing(bad):
    want = enemy_rune_threat([_GRASP, _SECOND_WIND], enemy_max_hp=1000.0,
                             enemy_missing_hp=0.0)
    got = enemy_rune_threat([_GRASP, _SECOND_WIND], enemy_max_hp=1000.0,
                            enemy_missing_hp=bad)
    assert got == want
    assert math.isfinite(got.poke_sustain_hp)


def test_enemy_rune_negative_missing_hp_is_not_an_hp_loss():
    want = enemy_rune_threat([_GRASP, _SECOND_WIND], enemy_max_hp=1000.0,
                             enemy_missing_hp=0.0)
    got = enemy_rune_threat([_GRASP, _SECOND_WIND], enemy_max_hp=1000.0,
                            enemy_missing_hp=-5000.0)
    assert got == want
    assert got.poke_sustain_hp > 0.0


@pytest.mark.parametrize("bad", ["false", "no", "0", "", "x", _NAN, None, [], 0])
def test_enemy_rune_antiheal_garbage_is_off(bad):
    assert enemy_rune_threat([], antiheal_present=bad).antiheal_pct == 0.0


@pytest.mark.parametrize("on", [True, 1, "true", " Yes "])
def test_enemy_rune_antiheal_true_values_arm_it(on):
    assert enemy_rune_threat([], antiheal_present=on).antiheal_pct == 0.40


@pytest.mark.parametrize("bad", [_NAN, _INF, -_INF, None, "x", True])
def test_enemy_rune_bad_level_reads_as_default_level(bad):
    assert enemy_rune_threat([_CONQ], bad) == enemy_rune_threat([_CONQ], 1.0)


def test_enemy_rune_outputs_always_finite():
    t = enemy_rune_threat([_GRASP, _SECOND_WIND, _PTA, _CONQ], _INF,
                          antiheal_present=_NAN, enemy_max_hp=_INF,
                          enemy_missing_hp=_NAN)
    assert all(math.isfinite(v) for v in asdict(t).values())


# --- DSP7 ally grants ---------------------------------------------------------

@pytest.mark.parametrize("bad", [5, "abc", {"x": 1}, [True, True, 0, 0], None,
                                 [None, None], [_NAN, _INF, -_INF, _NAN]])
def test_ally_granter_resists_bad_value_is_absent(snap, bad):
    want = ally_protected_ehp(snap, "Jinx", 11, ally_grant_champions=["Taric"])
    got = ally_protected_ehp(snap, "Jinx", 11, ally_grant_champions=["Taric"],
                             granter_resists={"Taric": bad})
    assert _ehp(got) == _ehp(want)


def test_ally_granter_resists_null_on_flat_granter_does_not_raise(snap):
    want = ally_protected_ehp(snap, "Jinx", 11, ally_grant_champions=["Orianna"])
    got = ally_protected_ehp(snap, "Jinx", 11, ally_grant_champions=["Orianna"],
                             granter_resists={"Orianna": [None]})
    assert _ehp(got) == _ehp(want)


def test_ally_granter_resists_bad_slot_is_zero_good_slots_kept(snap):
    want = ally_protected_ehp(snap, "Jinx", 11, ally_grant_champions=["Taric"],
                              granter_resists={"Taric": (120.0, 0.0, 40.0, 32.0)},
                              mode="SR")
    got = ally_protected_ehp(snap, "Jinx", 11, ally_grant_champions=["Taric"],
                             granter_resists={"Taric": [120, None, 40, "32"]},
                             mode="SR")
    assert _ehp(got) == _ehp(want)
    assert (got.physical_ehp, got.magical_ehp) == (2640.93275625, 2184.544721875)


def test_ally_granter_resists_not_a_mapping_is_absent(snap):
    want = ally_protected_ehp(snap, "Jinx", 11, ally_grant_champions=["Taric"])
    got = ally_protected_ehp(snap, "Jinx", 11, ally_grant_champions=["Taric"],
                             granter_resists=[("Taric", 1)])
    assert _ehp(got) == _ehp(want)


def test_ally_bare_string_granter_is_one_champion(snap):
    want = ally_protected_ehp(snap, "Jinx", 11, ally_grant_champions=["Janna"])
    got = ally_protected_ehp(snap, "Jinx", 11, ally_grant_champions="Janna")
    assert _ehp(got) == _ehp(want)
    base = ally_protected_ehp(snap, "Jinx", 11)
    assert got.blended_ehp > base.blended_ehp


def test_ally_null_and_blank_granters_are_skipped(snap):
    want = ally_protected_ehp(snap, "Jinx", 11, ally_grant_champions=["Janna"])
    got = ally_protected_ehp(snap, "Jinx", 11,
                             ally_grant_champions=[None, "", "  ", "Janna", 7])
    assert _ehp(got) == _ehp(want)


def test_ally_route_bad_granter_value_answers_instead_of_500(snap):
    # Before: TypeError out of the consumer, which the route does not map,
    # so DS :8860 answered 500 to a well-formed JSON object.
    server._CACHE.set(snap)
    base = server._route_ally_protected_ehp(
        {"champion": "Jinx", "level": 11, "ally_grant_champions": ["Taric"]})
    for bad in (5, [None], [None, None, None, None]):
        got = server._route_ally_protected_ehp(
            {"champion": "Jinx", "level": 11, "ally_grant_champions": ["Taric"],
             "granter_resists": {"Taric": bad}})
        assert got == base

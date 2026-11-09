"""S144-D-115..118 - rune_procs and summoners never zero a proc off an infinite
level, never credit NaN / inf stat damage or an HP gate off a non-finite or junk
HP, and never raise from their documented fail-soft public surfaces.

Measured at HEAD before the fix (direct calls; every seam is DEFAULT-OFF):
  * rune_procs._clamp_level(+-inf) and summoners._clamp_level(+-inf) raised
    OverflowError (``int(inf)``), so compute_rune_proc_damage(8112, inf) and
    compute_summoner_value(14, inf) swallowed it and returned 0.0 - the whole
    proc / spell zeroed instead of clamping to level 18 / level 1 (S144-D-115).
  * _f / _adaptive_coeff / _adaptive_grant passed NaN and +-inf through: an
    Electrocute with ap=nan returned nan, ad=inf returned inf, Dark Harvest
    souls=nan, Grasp caster_max_hp=inf, Lethal Tempo bonus_as=-inf (-inf) and
    so on; a NaN bonus AD flipped Absolute Focus to its AP side (S144-D-116).
  * HP gates met off a non-finite or junk HP: Absolute Focus credited its >70%
    grant at caster_hp_pct=nan / +inf; Last Stand returned nan at nan and the
    1.11x max amp at -inf, "x" and None; the gated Cut Down amp fired at
    target_hp_pct=+inf and Coup de Grace at -inf / "x" / None; Gathering Storm
    returned nan / inf at game_time_s=nan / inf (S144-D-117).
  * An unhashable rune / spell id raised TypeError from compute_rune_proc_damage,
    keystone_amp and all six summoners public functions, each documented
    fail-soft; keystone_amp also raised on a base_damage float() overflows or
    whose __float__ raises (S144-D-118).

Finite, well-typed inputs stay byte-identical.
"""

from __future__ import annotations

import math

import pytest

from agents.daemon_slayer import rune_procs as rp
from agents.daemon_slayer import summoners as sm

NAN = float("nan")
INF = float("inf")
NONFINITE = [NAN, INF, -INF]


class _RaisingFloat:
    def __float__(self):
        raise RuntimeError("no float")


# --- S144-D-115: infinite level clamps, never zeroes the proc -----------------


@pytest.mark.parametrize("mod", [rp, sm], ids=["rune_procs", "summoners"])
def test_clamp_level_infinite_clamps(mod):
    assert mod._clamp_level(INF) == 18
    assert mod._clamp_level(-INF) == 1
    assert mod._clamp_level(NAN) == 1


@pytest.mark.parametrize("rid", sorted(rp.RUNE_PROCS))
def test_rune_proc_infinite_level_reads_the_band_ends(rid):
    assert rp.compute_rune_proc_damage(rid, INF) == rp.compute_rune_proc_damage(rid, 18)
    assert rp.compute_rune_proc_damage(rid, -INF) == rp.compute_rune_proc_damage(rid, 1)


@pytest.mark.parametrize("sid", sorted(sm.SUMMONER_SPELLS))
def test_summoner_infinite_level_reads_the_band_ends(sid):
    assert sm.compute_summoner_value(sid, INF) == sm.compute_summoner_value(sid, 18)
    assert sm.compute_summoner_value(sid, -INF) == sm.compute_summoner_value(sid, 1)


def test_summoner_infinite_level_is_not_zero():
    # Ignite's level-18 value, not the 0.0 the swallowed OverflowError gave.
    assert sm.compute_summoner_value(14, INF) == pytest.approx(525.0)


# --- S144-D-116: non-finite stats read 0.0 ------------------------------------

_STAT_KWARGS = ["ad", "ap", "bonus_hp", "souls", "caster_max_hp", "shield_amount", "bonus_as"]


@pytest.mark.parametrize("rid", sorted(rp.RUNE_PROCS))
@pytest.mark.parametrize("stat", _STAT_KWARGS)
@pytest.mark.parametrize("bad", NONFINITE, ids=["nan", "inf", "-inf"])
def test_nonfinite_stat_reads_zero(rid, stat, bad):
    base = {"ad": 40.0, "ap": 60.0, "bonus_hp": 300.0, "souls": 3.0,
            "caster_max_hp": 2000.0, "shield_amount": 150.0, "bonus_as": 0.5}
    zeroed = dict(base, **{stat: 0.0})
    poisoned = dict(base, **{stat: bad})
    got = rp.compute_rune_proc_damage(rid, 11, game_time_s=1200.0, **poisoned)
    assert math.isfinite(got)
    assert got == rp.compute_rune_proc_damage(rid, 11, game_time_s=1200.0, **zeroed)


def test_nan_bonus_ad_does_not_flip_absolute_focus_to_ap():
    assert rp.compute_rune_proc_damage(8233, 10, ad=NAN, ap=0.0) == (
        rp.compute_rune_proc_damage(8233, 10, ad=0.0, ap=0.0)
    )


@pytest.mark.parametrize("bad", NONFINITE, ids=["nan", "inf", "-inf"])
def test_adaptive_helpers_nonfinite(bad):
    assert rp._f(bad) == 0.0
    assert rp._adaptive_coeff(100.0, bad, 0.1, 0.05) == pytest.approx(10.0)
    assert rp._adaptive_coeff(bad, 100.0, 0.1, 0.05) == pytest.approx(5.0)
    assert rp._adaptive_grant(bad, 0.0, 7.0, 9.0) == 7.0


# --- S144-D-117: HP / time gates never met off a non-finite or junk value ------

_BAD_HP = [NAN, INF, -INF, "x", None, _RaisingFloat()]
_BAD_HP_IDS = ["nan", "inf", "-inf", "str", "none", "raising"]


@pytest.mark.parametrize("hp", _BAD_HP, ids=_BAD_HP_IDS)
def test_absolute_focus_bad_hp_never_grants(hp):
    assert rp.compute_rune_proc_damage(8233, 10, caster_hp_pct=hp) == 0.0


@pytest.mark.parametrize("hp", _BAD_HP, ids=_BAD_HP_IDS)
def test_last_stand_bad_hp_never_amps(hp):
    assert rp.keystone_amp(8299, 100.0, caster_hp_pct=hp) == 100.0


@pytest.mark.parametrize("rid", [8017, 8014], ids=["cut_down", "coup_de_grace"])
@pytest.mark.parametrize("hp", _BAD_HP, ids=_BAD_HP_IDS)
def test_target_hp_gate_bad_hp_never_amps(rid, hp):
    assert rp.keystone_amp(rid, 100.0, target_hp_pct=hp, gate_target_hp=True) == 100.0


@pytest.mark.parametrize("t", _BAD_HP, ids=_BAD_HP_IDS)
def test_gathering_storm_bad_time_grants_nothing(t):
    assert rp.compute_rune_proc_damage(8236, 10, game_time_s=t) == 0.0


@pytest.mark.parametrize(
    "rid, kwargs, expected",
    [
        (8299, {"caster_hp_pct": 0.30}, 111.0),
        (8299, {"caster_hp_pct": 0.45}, 108.0),
        (8299, {"caster_hp_pct": 0.60}, 100.0),
        (8299, {"caster_hp_pct": "0.30"}, 111.0),
        (8017, {"target_hp_pct": 0.61, "gate_target_hp": True}, 108.0),
        (8017, {"target_hp_pct": 0.60, "gate_target_hp": True}, 100.0),
        (8014, {"target_hp_pct": 0.39, "gate_target_hp": True}, 108.0),
        (8014, {"target_hp_pct": 0.40, "gate_target_hp": True}, 100.0),
        (8014, {"target_hp_pct": NAN}, 108.0),
    ],
)
def test_finite_gates_unchanged(rid, kwargs, expected):
    assert rp.keystone_amp(rid, 100.0, **kwargs) == pytest.approx(expected)


def test_finite_absolute_focus_and_storm_unchanged():
    assert rp.compute_rune_proc_damage(8233, 1, caster_hp_pct=0.71) == pytest.approx(1.8)
    assert rp.compute_rune_proc_damage(8233, 1, caster_hp_pct=0.70) == 0.0
    assert rp.compute_rune_proc_damage(8236, 1, game_time_s=600.0) == pytest.approx(5.0)
    assert rp.compute_rune_proc_damage(8236, 1, game_time_s=600.0, ap=10.0) == pytest.approx(8.0)


# --- S144-D-118: unhashable ids and junk base_damage never raise --------------


def test_rune_public_surface_unhashable_id():
    assert rp.compute_rune_proc_damage([8112], 10) == 0.0
    assert rp.keystone_amp([8005], 100.0) == 100.0


@pytest.mark.parametrize("bad", [10 ** 400, _RaisingFloat()], ids=["overflow", "raising"])
def test_keystone_amp_unconvertible_base(bad):
    assert rp.keystone_amp(8005, bad) == 0.0


@pytest.mark.parametrize(
    "fn",
    [
        sm.compute_summoner_value,
        sm.summoner_antiheal_pct,
        sm.summoner_incoming_dr_pct,
        sm.summoner_cc_discount_pct,
        sm.compute_summoner_ms_pct,
        sm.compute_summoner_ehp_bonus,
    ],
)
def test_summoner_public_surface_unhashable_id(fn):
    assert fn([14]) == 0.0

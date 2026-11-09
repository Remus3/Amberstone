"""S144-D-123..125 - enemy_runes (documented "fail-soft: never raise") never
zeroes Conqueror off an infinite level, never credits inf / NaN / a negative
HP-scaled Grasp term, and never raises on an infinite rune id.

Rebased onto main: the true-audit lane's 980d7527a landed the code fix for
the same three defects first, under its own contract, and these regression
tests now pin THAT contract: a non-finite level reads as level 1 (the
dsp_live_consumers "bad level is 1" rule; an int of any size still clamps),
and an HP that is not a finite, non-negative number makes the whole Grasp /
poke-sustain result 0.0.

Measured at HEAD before the fix (direct calls):
  * compute_enemy_rune_value(8010, +-inf) and enemy_damage_ramp([8010], +-inf)
    returned 0.0: ``_clamp_level`` did ``int(inf)``, the OverflowError was
    swallowed into a zeroed rune (S144-D-123; the S144-D-115 summoners twin
    whose comment says enemy_runes mirrors it). Level 18 reads 48.0, level 1
    reads 21.6.
  * enemy_grasp_magic_proc and enemy_poke_sustain_hp returned inf / -inf / NaN
    for a non-finite HP and a negative value for a negative HP (S144-D-124).
  * every public id-taking function raised OverflowError on a rune id of
    +-inf: ``_iter_ids`` caught only TypeError / ValueError (S144-D-125).

Every finite non-negative input is byte-identical.
"""

from __future__ import annotations

import math

import pytest

from agents.daemon_slayer import enemy_runes as er

INF = float("inf")
NAN = float("nan")
CONQ = 8010
GRASP = 8437
SECOND_WIND = 8444


# --- S144-D-123: Conqueror at an infinite level --------------------------------


class TestConquerorLevel:
    def test_pos_inf_level_reads_1_not_zero(self):
        ref = er.compute_enemy_rune_value(CONQ, 1)
        assert ref == pytest.approx(21.6)
        assert er.compute_enemy_rune_value(CONQ, INF) == ref
        assert er.enemy_damage_ramp([CONQ], INF) == ref

    def test_huge_int_level_clamps_to_18(self):
        ref = er.compute_enemy_rune_value(CONQ, 18)
        assert ref == pytest.approx(48.0)
        assert er.compute_enemy_rune_value(CONQ, 10**400) == ref

    def test_neg_inf_level_reads_1(self):
        ref = er.compute_enemy_rune_value(CONQ, 1)
        assert ref == pytest.approx(21.6)
        assert er.compute_enemy_rune_value(CONQ, -INF) == ref
        assert er.enemy_damage_ramp([CONQ], -INF) == ref

    @pytest.mark.parametrize("lv", [NAN, "x", None, object()],
                             ids=["nan", "str", "none", "obj"])
    def test_junk_level_still_reads_1(self, lv):
        assert er.compute_enemy_rune_value(CONQ, lv) == pytest.approx(21.6)

    def test_clamp_level_helper(self):
        assert er._clamp_level(INF) == 1
        assert er._clamp_level(-INF) == 1
        assert er._clamp_level(NAN) == 1
        assert er._clamp_level(10**400) == 18
        assert er._clamp_level(-(10**400)) == 1
        assert er._clamp_level(9.7) == 9


# --- S144-D-124: Grasp HP-scaled terms ----------------------------------------


class TestGraspHp:
    @pytest.mark.parametrize("hp", [INF, -INF, NAN], ids=["inf", "-inf", "nan"])
    def test_magic_proc_nonfinite_hp_reads_0(self, hp):
        assert er.enemy_grasp_magic_proc([GRASP], hp) == 0.0
        assert er.enemy_grasp_magic_proc([GRASP], hp, ranged=True) == 0.0

    def test_magic_proc_negative_hp_reads_0(self):
        assert er.enemy_grasp_magic_proc([GRASP], -100.0) == 0.0

    def test_magic_proc_finite_unchanged(self):
        assert er.enemy_grasp_magic_proc([GRASP], 1000.0) == pytest.approx(35.0)
        assert er.enemy_grasp_magic_proc([GRASP], 0.0) == 0.0

    @pytest.mark.parametrize("hp", [INF, -INF, NAN], ids=["inf", "-inf", "nan"])
    def test_poke_sustain_nonfinite_max_hp_reads_0(self, hp):
        assert er.enemy_poke_sustain_hp([GRASP, SECOND_WIND], hp, 100.0) == 0.0

    @pytest.mark.parametrize("hp", [INF, -INF, NAN], ids=["inf", "-inf", "nan"])
    def test_poke_sustain_nonfinite_missing_hp_reads_0(self, hp):
        assert er.enemy_poke_sustain_hp([GRASP, SECOND_WIND], 1000.0, hp) == 0.0

    def test_poke_sustain_negative_hp_reads_0(self):
        assert er.enemy_poke_sustain_hp([GRASP, SECOND_WIND], -100.0, 50.0) == 0.0
        assert er.enemy_poke_sustain_hp([GRASP, SECOND_WIND], 1000.0, -50.0) == 0.0

    def test_poke_sustain_finite_unchanged(self):
        got = er.enemy_poke_sustain_hp([GRASP, SECOND_WIND], 1000.0, 100.0)
        assert got == pytest.approx(0.013 * 1000.0 + 5.0 + 0.04 * 100.0)
        assert math.isfinite(got)


# --- S144-D-125: infinite rune ids --------------------------------------------


class TestInfiniteIds:
    @pytest.mark.parametrize("rid", [INF, -INF], ids=["inf", "-inf"])
    def test_id_funcs_never_raise(self, rid):
        assert er.enemy_incoming_amp_pct([rid]) == 0.0
        assert er.enemy_damage_ramp([rid], 18) == 0.0
        assert er.enemy_poke_sustain_pct([rid]) == 0.0
        assert er.enemy_poke_sustain_hp([rid], 1000.0, 100.0) == 0.0
        assert er.enemy_grasp_magic_proc([rid], 1000.0) == 0.0

    def test_iter_ids_helper(self):
        assert tuple(er._iter_ids([INF])) == ()
        assert tuple(er._iter_ids([NAN])) == ()
        assert tuple(er._iter_ids([CONQ, GRASP])) == (CONQ, GRASP)
        assert tuple(er._iter_ids([8010.0])) == (CONQ,)

"""S144-D-111..114 - Cinderbloom and the rune offense grants never credit a gate,
a top tier or an adaptive side off NaN / inf, and never raise on junk.

Measured at HEAD before the fix (direct calls; every seam is DEFAULT-OFF):
  * item_lowhp_magic_crit_amp(["4645"], nan, True) == 1.2 - NaN < 0.40 is False,
    so ``>= threshold`` is False and the low-HP amp fired; -inf did the same,
    and None / an object raised TypeError (S144-D-111).
  * _clamp_level(nan) returned nan (both comparisons False), so Absolute Focus
    and Conqueror returned (nan, nan) at level=nan; absolute_focus_grant with
    caster_hp_pct=nan credited the >70% gate (S144-D-112).
  * jack_of_all_trades_grant(nan) and (inf) paid the 25 AF top tier; the
    conqueror / legend NaN stack count only matched its default because the
    default is the cap (S144-D-113). Their +-inf counts keep clamping (+inf to
    the cap, -inf to 0), so junk never pays more than HEAD did.
  * rune_offense_grants raised ValueError on game_minute="x", credited Jack's
    top tier at jack_stacks=nan, and a NaN bonus_ad flipped the adaptive side to
    AP (S144-D-114).

Finite, well-typed inputs stay byte-identical; the leaf clamps and the
documented inf-minute 60-row clamp are untouched.
"""

from __future__ import annotations

import math

import pytest

from agents.daemon_slayer import _rune_offense_grants as rog
from agents.daemon_slayer._item_lowhp_magic_crit import item_lowhp_magic_crit_amp

NAN = float("nan")
INF = float("inf")


class _RaisingFloat:
    def __float__(self):
        raise RuntimeError("no float")


class _Junk:
    pass


# --- S144-D-111: Cinderbloom low-HP gate --------------------------------------


@pytest.mark.parametrize("hp", [NAN, INF, -INF, None, _Junk(), "abc"])
def test_lowhp_amp_unusable_hp_never_credits_or_raises(hp):
    assert item_lowhp_magic_crit_amp(["4645"], hp, True) == 1.0


def test_lowhp_amp_raising_float_never_raises():
    assert item_lowhp_magic_crit_amp(["4645"], _RaisingFloat(), True) == 1.0


@pytest.mark.parametrize(
    "hp, expected", [(0.39, 1.2), (0.0, 1.2), (0.40, 1.0), (1.0, 1.0), (1, 1.0)]
)
def test_lowhp_amp_finite_inputs_unchanged(hp, expected):
    assert item_lowhp_magic_crit_amp(["4645"], hp, True) == pytest.approx(expected)


def test_lowhp_amp_numeric_string_is_now_coerced():
    # NEW behaviour, not unchanged: HEAD raised TypeError on a str; the float()
    # coercer now reads "0.1" as 0.1, the same as every sibling coercer here.
    assert item_lowhp_magic_crit_amp(["4645"], "0.1", True) == pytest.approx(1.2)


def test_lowhp_amp_flag_off_is_identity_even_on_junk():
    assert item_lowhp_magic_crit_amp(["4645"], NAN, False) == 1.0


# --- S144-D-112: level clamp + Absolute Focus HP gate ------------------------


def test_clamp_level_nan_fails_soft_to_one():
    assert rog._clamp_level(NAN) == 1.0
    assert rog._clamp_level(INF) == 18.0
    assert rog._clamp_level(-INF) == 1.0
    assert rog._clamp_level(10) == 10.0


@pytest.mark.parametrize("fn_args", [("af", NAN, 1.0), ("conq", NAN, 6.0)])
def test_nan_level_never_returns_nan(fn_args):
    kind, level, other = fn_args
    if kind == "af":
        out = rog.absolute_focus_grant(level, other)
        ref = rog.absolute_focus_grant(1, other)
    else:
        out = rog.conqueror_grant(level, other)
        ref = rog.conqueror_grant(1, other)
    assert all(math.isfinite(v) for v in out)
    assert out == ref


def test_clamp_level_and_storm_never_raise_on_raising_float():
    assert rog._clamp_level(_RaisingFloat()) == 1.0
    assert rog.gathering_storm_step(_RaisingFloat()) == (0.0, 0.0)
    assert rog.gathering_storm_step(NAN) == (0.0, 0.0)


@pytest.mark.parametrize("hp", [NAN, INF, -INF, _RaisingFloat()])
def test_absolute_focus_unusable_hp_never_credits(hp):
    assert rog.absolute_focus_grant(10, hp) == (0.0, 0.0)


def test_absolute_focus_finite_gate_unchanged():
    assert rog.absolute_focus_grant(10, 0.70) == (0.0, 0.0)
    ad, ap = rog.absolute_focus_grant(10, 0.71)
    assert ad > 0.0 and ap > 0.0


# --- S144-D-113: stack coercers -----------------------------------------------


@pytest.mark.parametrize("stacks", [NAN, INF, -INF, _RaisingFloat()])
def test_jack_grant_unusable_stacks_pay_nothing(stacks):
    assert rog.jack_of_all_trades_grant(stacks) == (0.0, 0.0)


def test_jack_grant_finite_tiers_unchanged():
    assert rog.jack_of_all_trades_grant(4) == (0.0, 0.0)
    assert rog.jack_of_all_trades_grant(5) == pytest.approx((6.0, 10.0))
    assert rog.jack_of_all_trades_grant(12) == pytest.approx((15.0, 25.0))


@pytest.mark.parametrize("stacks", [NAN, _RaisingFloat()])
def test_conqueror_unusable_stacks_read_assumed_default(stacks, monkeypatch):
    # Pin the contract, not the coincidence: with a default below the cap a
    # NaN count must read the default, not the cap.
    monkeypatch.setattr(rog, "_ASSUMED_CONQUEROR_STACKS", 4.0)
    assert rog.conqueror_grant(10, stacks) == rog.conqueror_grant(10, 4.0)


@pytest.mark.parametrize("stacks", [NAN, _RaisingFloat()])
def test_legend_unusable_stacks_read_assumed_default(stacks, monkeypatch):
    monkeypatch.setattr(rog, "_ASSUMED_LEGEND_STACKS", 3.0)
    assert rog.legend_alacrity_grant(stacks) == rog.legend_alacrity_grant(3.0)


def test_stack_coercers_infinite_counts_keep_clamping(monkeypatch):
    monkeypatch.setattr(rog, "_ASSUMED_CONQUEROR_STACKS", 4.0)
    monkeypatch.setattr(rog, "_ASSUMED_LEGEND_STACKS", 3.0)
    assert rog.conqueror_grant(10, INF) == rog.conqueror_grant(10, 12)
    assert rog.conqueror_grant(10, -INF) == (0.0, 0.0)
    assert rog.legend_alacrity_grant(INF) == pytest.approx(0.18)
    assert rog.legend_alacrity_grant(-INF) == pytest.approx(0.03)


def test_stack_coercers_finite_clamps_unchanged():
    assert rog.conqueror_grant(10, 99) == rog.conqueror_grant(10, 12)
    assert rog.conqueror_grant(10, -3) == (0.0, 0.0)
    assert rog.legend_alacrity_grant(99) == pytest.approx(0.18)
    assert rog.legend_alacrity_grant(-3) == pytest.approx(0.03)


# --- S144-D-114: rune_offense_grants top-level coercers ----------------------

_IDS = list(rog._RUNE_OFFENSE_GRANTS)


def _grants(**kw):
    base = dict(level=10, bonus_ad=50.0, ap=0.0)
    base.update(kw)
    return rog.rune_offense_grants(_IDS, **base)


def _finite(triple):
    return all(math.isfinite(v) for v in triple)


@pytest.mark.parametrize("minute", ["x", _Junk(), _RaisingFloat(), NAN])
def test_unusable_game_minute_reads_assumed_minute(minute):
    out = _grants(game_minute=minute)
    assert _finite(out)
    assert out == _grants(game_minute=None)


def test_inf_game_minute_keeps_documented_60_row_clamp():
    assert _grants(game_minute=INF) == _grants(game_minute=600.0)


@pytest.mark.parametrize("stacks", [NAN, INF, -INF])
def test_unusable_jack_stacks_read_no_census(stacks):
    assert _grants(jack_stacks=stacks) == _grants(jack_stacks=None)


def test_nan_level_never_returns_nan_grant():
    out = _grants(level=NAN)
    assert _finite(out)
    assert out == _grants(level=1)


@pytest.mark.parametrize("bad", [NAN, INF, -INF])
def test_unusable_bonus_ad_reads_zero(bad):
    assert _grants(bonus_ad=bad) == _grants(bonus_ad=0.0)


@pytest.mark.parametrize("bad", [NAN, INF, -INF])
def test_unusable_ap_reads_zero(bad):
    assert _grants(bonus_ad=0.0, ap=bad) == _grants(bonus_ad=0.0, ap=0.0)


def test_finite_inputs_unchanged_spot_values():
    assert _grants() == pytest.approx((36.722352941176474, 0.0, 0.18))
    assert _grants(jack_stacks=10) == pytest.approx((51.722352941176474, 0.0, 0.18))
    ad_side = _grants(bonus_ad=0.0, ap=80.0)
    assert ad_side[0] == 0.0 and ad_side[1] > 0.0

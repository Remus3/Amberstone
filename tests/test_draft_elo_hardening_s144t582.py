"""S144-T-582 - core/draft_elo.py hardening (true-audit lane, s144 cycle 194).

The module docstring promises numerical guards ("a 1.0 or 0.0 input does not
blow up", "rating_to_winrate is unbounded-input safe - extreme deltas saturate
cleanly"). Measured before this slice:

  - winrate_to_rating(NaN) and winrate_to_rating(True) returned +1199.8, the
    STRONGEST possible rating: min()/max() pass a NaN through to the clamp's
    upper bound, so "no number" read as a near-certain win;
  - winrate_to_rating(10 ** 400) raised OverflowError out of float();
  - rating_to_winrate(-1e6) raised OverflowError (math range error) and
    rating_to_winrate(NaN) returned NaN, which json.dumps writes as a bare
    NaN token no strict parser accepts;
  - scale=0 raised ZeroDivisionError in rating_to_winrate (and returned
    -0.0 for any win rate in winrate_to_rating), scale=-400 silently
    inverted every rating, scale=NaN returned NaN and scale=True ran at
    scale 1;
  - winrate_to_rating(0.5) returned -0.0, so every no-data champion / pair in
    the /api/draft-elo payload serialized as "-0.0";
  - top_contributions with one NaN rating returned the WRONG top-N (Python's
    sort is undefined over NaN keys: the real top row was dropped), int(64.9)
    turned a fractional id into champion 64, a bool count read as n=1 and a
    malformed pair tuple raised out of the whole call.
"""
from __future__ import annotations

import json
import math

import pytest

from core import draft_elo as de

NAN = float("nan")
INF = float("inf")


# ---- winrate_to_rating ----------------------------------------------------

@pytest.mark.parametrize("junk", [NAN, True, False, None, "0.6", b"0.6",
                                  object(), [0.6]])
def test_non_number_win_rate_is_neutral_zero(junk):
    r = de.winrate_to_rating(junk)
    assert r == 0.0
    assert math.copysign(1.0, r) == 1.0


def test_neutral_win_rate_is_positive_zero_not_negative_zero():
    r = de.winrate_to_rating(0.5)
    assert r == 0.0
    assert math.copysign(1.0, r) == 1.0
    assert json.dumps(r) == "0.0"


def test_huge_int_win_rate_clamps_instead_of_overflow():
    hi = de.winrate_to_rating(10 ** 400)
    lo = de.winrate_to_rating(-(10 ** 400))
    assert hi == de.winrate_to_rating(1.0)
    assert lo == de.winrate_to_rating(0.0)


def test_infinite_win_rate_clamps_by_sign():
    assert de.winrate_to_rating(INF) == de.winrate_to_rating(1.0)
    assert de.winrate_to_rating(-INF) == de.winrate_to_rating(0.0)


def test_raising_float_subclass_is_neutral():
    class Bad(float):
        def __float__(self):
            raise RuntimeError("boom")

    assert de.winrate_to_rating(Bad(0.7)) == 0.0


def test_real_win_rates_unchanged():
    # Characterization: the in-range transform is byte-identical.
    for wr in (0.001, 0.1, 0.37, 0.55, 0.9, 0.999):
        expected = -400.0 * math.log10(1.0 / wr - 1.0)
        assert de.winrate_to_rating(wr) == expected


# ---- rating_to_winrate ----------------------------------------------------

@pytest.mark.parametrize("rating", [-1e6, -1e300, -(10 ** 400)])
def test_extreme_negative_rating_saturates_to_zero(rating):
    assert de.rating_to_winrate(rating) == 0.0


@pytest.mark.parametrize("rating", [1e6, 1e300, 10 ** 400, INF])
def test_extreme_positive_rating_saturates_to_one(rating):
    assert de.rating_to_winrate(rating) == 1.0


def test_negative_infinite_rating_is_zero():
    assert de.rating_to_winrate(-INF) == 0.0


@pytest.mark.parametrize("junk", [NAN, True, None, "100", object()])
def test_non_number_rating_is_coin_flip(junk):
    assert de.rating_to_winrate(junk) == 0.5


def test_rating_round_trip_and_symmetry_kept():
    # +/-1100 stays inside the [0.001, 0.999] clamp (+/-1199.8).
    for r in (-1100.0, -400.0, -35.0, 0.0, 35.0, 400.0, 1100.0):
        p = de.rating_to_winrate(r)
        assert 0.0 < p < 1.0
        assert math.isclose(p + de.rating_to_winrate(-r), 1.0, abs_tol=1e-12)
        assert math.isclose(de.winrate_to_rating(p), r, abs_tol=1e-6)


def test_known_points_unchanged():
    assert de.rating_to_winrate(0) == 0.5
    assert math.isclose(de.rating_to_winrate(400), 1.0 / 1.1, rel_tol=1e-12)
    assert math.isclose(de.rating_to_winrate(-400), 1.0 - 1.0 / 1.1,
                        rel_tol=1e-12)


def test_draft_winrate_with_nan_side_is_finite_json():
    ally = de.DraftSide(champ_ratings=(NAN,), pair_ratings=())
    enemy = de.DraftSide(champ_ratings=(INF,), pair_ratings=(-INF,))
    p = de.draft_winrate(ally, enemy)
    assert p == 0.5
    json.dumps(p, allow_nan=False)


# ---- scale ----------------------------------------------------------------

@pytest.mark.parametrize("scale", [0, 0.0, -400, -400.0, NAN, INF, True,
                                   None, "400"])
def test_bad_scale_is_a_value_error_both_directions(scale):
    with pytest.raises(ValueError):
        de.winrate_to_rating(0.6, scale=scale)
    with pytest.raises(ValueError):
        de.rating_to_winrate(100.0, scale=scale)


def test_custom_positive_scale_still_works():
    r = de.winrate_to_rating(0.6, scale=173.7)
    assert r > 0
    assert math.isclose(de.rating_to_winrate(r, scale=173.7), 0.6,
                        rel_tol=1e-12)


# ---- top_contributions ----------------------------------------------------

def _tc(**kw):
    base = dict(ally_pairs=[], enemy_pairs=[], matchup_cross=[],
                ally_pair_ratings=(), enemy_pair_ratings=(),
                matchup_ratings=(), ally_pair_counts=[],
                enemy_pair_counts=[], matchup_counts=[])
    base.update(kw)
    return de.top_contributions(**base)


def test_nan_rating_row_dropped_and_real_top_kept():
    out = _tc(ally_pairs=[(1, 2), (3, 4), (5, 6)],
              ally_pair_ratings=(5.0, NAN, 100.0),
              ally_pair_counts=[1, 2, 3], limit=1)
    assert [(c.a, c.b, c.delta) for c in out] == [(5, 6, 100.0)]


def test_infinite_rating_row_dropped():
    out = _tc(matchup_cross=[(1, 2), (3, 4)],
              matchup_ratings=(INF, 10.0),
              matchup_counts=[1, 1], limit=5)
    assert [(c.a, c.b) for c in out] == [(3, 4)]


@pytest.mark.parametrize("bad_pair", [(64.9, 2), (True, 2), ("64", 2),
                                      (None, 2), (1,), 7, (1, 2, 3)])
def test_bad_id_row_dropped_alone(bad_pair):
    out = _tc(ally_pairs=[bad_pair, (10, 11)],
              ally_pair_ratings=(50.0, 5.0),
              ally_pair_counts=[4, 4], limit=5)
    assert [(c.a, c.b, c.delta) for c in out] == [(10, 11, 5.0)]


def test_integral_float_id_is_not_silently_truncated():
    out = _tc(ally_pairs=[(64.0, 2)], ally_pair_ratings=(5.0,),
              ally_pair_counts=[1])
    assert out == []


@pytest.mark.parametrize("bad_n", [True, -3, 2.5, NAN, None, "7"])
def test_bad_count_reads_zero_not_one(bad_n):
    out = _tc(ally_pairs=[(1, 2)], ally_pair_ratings=(5.0,),
              ally_pair_counts=[bad_n])
    assert len(out) == 1
    assert out[0].n == 0
    assert type(out[0].n) is int


def test_bad_rating_types_dropped():
    out = _tc(ally_pairs=[(1, 2), (3, 4), (5, 6)],
              ally_pair_ratings=(True, "9", 1.0),
              ally_pair_counts=[1, 1, 1], limit=5)
    assert [(c.a, c.b) for c in out] == [(5, 6)]


def test_neutral_contributions_carry_positive_zero():
    zero = de.winrate_to_rating(0.5)
    out = _tc(ally_pairs=[(1, 2)], enemy_pairs=[(3, 4)],
              ally_pair_ratings=(zero,), enemy_pair_ratings=(0.0,),
              ally_pair_counts=[0], enemy_pair_counts=[0], limit=5)
    assert len(out) == 2
    for c in out:
        assert math.copysign(1.0, c.delta) == 1.0
    assert "-0.0" not in json.dumps([c.delta for c in out])


def test_fields_are_exact_types():
    import numpy as np

    out = _tc(ally_pairs=[(np.int64(7), np.int64(9))],
              ally_pair_ratings=(np.float64(12.5),),
              ally_pair_counts=[np.int64(4)])
    c = out[0]
    assert (type(c.a), type(c.b), type(c.delta), type(c.n)) == (
        int, int, float, int)
    assert (c.a, c.b, c.delta, c.n) == (7, 9, 12.5, 4)


def test_enemy_sign_flip_kept():
    out = _tc(enemy_pairs=[(3, 4)], enemy_pair_ratings=(40.0,),
              enemy_pair_counts=[9])
    assert out[0].delta == -40.0
    assert out[0].kind == "enemy-pair"

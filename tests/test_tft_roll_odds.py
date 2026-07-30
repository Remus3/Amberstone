"""Property tests for tft/tft_roll_odds.py.

Deliberately NOT single-value pins. The constants the module reads are known
to be stale (see tests/test_tft_constants_staleness.py), so an exact-float pin
would encode a number nobody has verified and would go red the moment the
operator corrects the tables in client. What must hold regardless of the
numbers is the SHAPE of the math, so that is what is pinned here.
"""
from __future__ import annotations

import itertools

import pytest

from tft import tft_data, tft_roll_odds as ro

CONSTS = ro.load_constants(tft_data)
LEVELS = sorted(CONSTS.tier_odds)
COSTS = sorted(CONSTS.pool_sizes)
# (target copies removed, total copies of that cost removed) - the second is
# always >= the first, because a target copy IS a copy of that cost.
POOL_STATES = [(0, 0), (0, 20), (1, 1), (2, 9), (4, 30), (6, 60)]
LEVEL_COST = list(itertools.product(LEVELS, COSTS))
LEVEL_COST_STATE = list(itertools.product(LEVELS, COSTS, POOL_STATES))


def _p(level, cost, taken=(0, 0), **kw):
    return ro.shop_hit_probability(
        level, cost,
        target_copies_taken=taken[0], cost_copies_taken=taken[1], **kw
    )


# -- bounds -------------------------------------------------------------------

@pytest.mark.parametrize("level,cost,taken", LEVEL_COST_STATE)
def test_probability_is_a_probability(level, cost, taken):
    assert 0.0 <= _p(level, cost, taken) <= 1.0


@pytest.mark.parametrize("level,cost,taken", LEVEL_COST_STATE)
def test_slot_probability_is_a_probability(level, cost, taken):
    p = ro.slot_probability(
        level, cost,
        target_copies_taken=taken[0], cost_copies_taken=taken[1],
    )
    assert 0.0 <= p <= 1.0


@pytest.mark.parametrize("level,cost,taken", LEVEL_COST_STATE)
def test_shop_probability_at_least_slot_probability(level, cost, taken):
    """Five chances are never worse than one."""
    slot = ro.slot_probability(
        level, cost,
        target_copies_taken=taken[0], cost_copies_taken=taken[1],
    )
    assert _p(level, cost, taken) >= slot - 1e-12


# -- monotone in pool depletion ----------------------------------------------

@pytest.mark.parametrize("level,cost", LEVEL_COST)
def test_monotone_decreasing_as_target_copies_are_removed(level, cost):
    """Each copy of the target taken by someone else can only hurt."""
    per_unit = CONSTS.pool_sizes[cost]
    prev = 1.1
    for k in range(per_unit + 2):
        cur = _p(level, cost, (k, k))
        assert cur <= prev + 1e-12, f"rose at k={k} ({cur} > {prev})"
        prev = cur


@pytest.mark.parametrize("level,cost", LEVEL_COST)
def test_monotone_decreasing_as_cost_pool_is_contested(level, cost):
    """Holding target copies fixed, a shallower cost pool is never better...

    ...for the OTHER units. For the target, other players taking non-target
    copies of the same cost RAISES the target's share. So the correct
    invariant on this axis is the mirror: it is non-DECREASING.
    """
    total = CONSTS.pool_sizes[cost] * CONSTS.units_per_cost[cost]
    prev = -1.0
    for taken in range(0, total, max(1, total // 12)):
        cur = _p(level, cost, (0, taken))
        assert cur >= prev - 1e-12, f"fell at taken={taken} ({cur} < {prev})"
        prev = cur


@pytest.mark.parametrize("level,cost", LEVEL_COST)
def test_empty_pool_is_exactly_zero(level, cost):
    per_unit = CONSTS.pool_sizes[cost]
    total = per_unit * CONSTS.units_per_cost[cost]
    assert _p(level, cost, (per_unit, total)) == 0.0
    # all target copies gone, cost pool still deep
    assert _p(level, cost, (per_unit, per_unit)) == 0.0
    # over-reported removals clamp, they do not go negative
    assert _p(level, cost, (per_unit + 5, total + 50)) == 0.0


@pytest.mark.parametrize("level,cost", LEVEL_COST)
def test_remaining_pool_never_negative(level, cost):
    t, c = ro.remaining_pool(
        cost, target_copies_taken=9999, cost_copies_taken=9999, consts=CONSTS
    )
    assert t == 0 and c == 0


# -- monotone in tier odds ----------------------------------------------------

@pytest.mark.parametrize("level,cost,taken", LEVEL_COST_STATE)
def test_monotone_increasing_in_tier_odds(level, cost, taken):
    """Doubling the target cost's tier odds never lowers the hit chance."""
    base = CONSTS.tier_odds[level].get(cost, 0.0)
    bumped = dict(CONSTS.tier_odds)
    bumped[level] = {**CONSTS.tier_odds[level], cost: min(1.0, base * 2 or 0.01)}
    alt = ro.SetConstants(
        source="bumped", set_number=CONSTS.set_number,
        verified_in_client=False, tier_odds=bumped,
        pool_sizes=CONSTS.pool_sizes, units_per_cost=CONSTS.units_per_cost,
    )
    assert _p(level, cost, taken, consts=alt) >= _p(level, cost, taken) - 1e-12


@pytest.mark.parametrize("level,cost,taken", LEVEL_COST_STATE)
def test_zero_tier_odds_is_exactly_zero(level, cost, taken):
    zeroed = dict(CONSTS.tier_odds)
    zeroed[level] = {**CONSTS.tier_odds[level], cost: 0.0}
    alt = ro.SetConstants(
        source="zeroed", set_number=CONSTS.set_number,
        verified_in_client=False, tier_odds=zeroed,
        pool_sizes=CONSTS.pool_sizes, units_per_cost=CONSTS.units_per_cost,
    )
    assert _p(level, cost, taken, consts=alt) == 0.0


# -- monotone in level --------------------------------------------------------

@pytest.mark.parametrize(
    "level,cost,taken",
    [
        (lv, c, st)
        for lv, c, st in LEVEL_COST_STATE
        if lv + 1 in CONSTS.tier_odds
        and CONSTS.tier_odds[lv + 1].get(c, 0.0) >= CONSTS.tier_odds[lv].get(c, 0.0)
    ],
)
def test_higher_level_never_lowers_odds_when_tier_odds_do_not_fall(
    level, cost, taken
):
    assert _p(level + 1, cost, taken) >= _p(level, cost, taken) - 1e-12


# -- slots --------------------------------------------------------------------

@pytest.mark.parametrize("level,cost,taken", LEVEL_COST_STATE)
def test_more_slots_never_lowers_odds(level, cost, taken):
    prev = -1.0
    for slots in range(0, 8):
        cur = _p(level, cost, taken, slots=slots)
        assert cur >= prev - 1e-12
        prev = cur


@pytest.mark.parametrize("level,cost,taken", LEVEL_COST_STATE)
def test_zero_slots_is_zero(level, cost, taken):
    assert _p(level, cost, taken, slots=0) == 0.0


@pytest.mark.parametrize("level,cost,taken", LEVEL_COST_STATE)
def test_expected_copies_bounds_and_relation(level, cost, taken):
    exp = ro.expected_copies_per_shop(
        level, cost,
        target_copies_taken=taken[0], cost_copies_taken=taken[1],
    )
    assert 0.0 <= exp <= ro.SHOP_SLOTS
    # E[copies] >= P(at least one), always (Markov / union bound direction).
    assert exp >= _p(level, cost, taken) - 1e-12


# -- rolls for confidence -----------------------------------------------------

@pytest.mark.parametrize("level,cost,taken", LEVEL_COST_STATE)
def test_rolls_for_confidence_is_consistent(level, cost, taken):
    p = _p(level, cost, taken)
    n = ro.rolls_for_confidence(
        level, cost,
        target_copies_taken=taken[0], cost_copies_taken=taken[1],
    )
    if p <= 0.0:
        assert n is None
        return
    assert n >= 1
    assert 1.0 - (1.0 - p) ** n >= 0.5 - 1e-12
    if n > 1:
        assert 1.0 - (1.0 - p) ** (n - 1) < 0.5


@pytest.mark.parametrize("level,cost", LEVEL_COST)
def test_rolls_for_confidence_monotone_in_confidence(level, cost):
    prev = 0
    for conf in (0.1, 0.25, 0.5, 0.75, 0.9, 0.99):
        n = ro.rolls_for_confidence(level, cost, confidence=conf)
        if n is None:
            continue
        assert n >= prev
        prev = n


# -- input validation ---------------------------------------------------------

def test_unknown_level_and_cost_raise():
    with pytest.raises(ValueError):
        ro.shop_hit_probability(99, COSTS[0])
    with pytest.raises(ValueError):
        ro.shop_hit_probability(LEVELS[0], 99)


def test_negative_inputs_raise():
    with pytest.raises(ValueError):
        ro.shop_hit_probability(LEVELS[0], COSTS[0], target_copies_taken=-1)
    with pytest.raises(ValueError):
        ro.shop_hit_probability(LEVELS[0], COSTS[0], slots=-1)
    with pytest.raises(ValueError):
        ro.rolls_for_confidence(LEVELS[0], COSTS[0], confidence=1.0)


def test_incomplete_constants_raise_rather_than_guess():
    """A module with no UNITS_PER_COST must fail loudly, not invent one."""
    from tft import tft_pbe_data

    incomplete = ro.load_constants(tft_pbe_data)
    assert incomplete.units_per_cost is None
    assert not incomplete.complete
    with pytest.raises(ValueError, match="UNITS_PER_COST"):
        ro.shop_hit_probability(LEVELS[0], COSTS[0], consts=incomplete)


def test_default_constants_is_the_complete_bundle():
    d = ro.default_constants()
    assert d.complete
    assert d.source.endswith("tft_data")

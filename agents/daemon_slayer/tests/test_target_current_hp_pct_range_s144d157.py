"""S144-D-157..159: ``target_current_hp_pct`` outside [0, 1] is refused on
every scorer, not only on the burst and ability-DPS ones.

``compute_burst_damage`` and ``compute_ability_dps`` already raise
``ValueError("target_current_hp_pct must be in [0,1], ...")`` (pinned by
``test_engine_robustness_p1l12.py``). ``compute_dps`` did not check the value
at all, and the carry and bruiser rankers forward it straight into it.

Measured at HEAD before the fix (tanky target 100/60/2500/1200, level 11, SR):

* S144-D-157: ``compute_dps`` scales the three %-CURRENT-HP procs (BotRK 3153,
  Hellfire 4017, Fulmination 443055) by the raw fraction, so a negative value
  credits NEGATIVE on-hit damage and a value above 1.0 credits more than the
  target's whole current HP.
* S144-D-158: ``rank_items(target_current_hp_pct=-1.0)`` gave Vayne a BotRK
  delta of -64.87 (105.02 at 1.0) and ``2.0`` gave 189.96, flipping BotRK off
  and on the top row. ``POST /rank`` parses the knob with ``_opt_float``,
  which refuses only non-finite tokens, so both values were reachable over
  HTTP and answered 200.
* S144-D-159: ``rank_items_by_hybrid(target_current_hp_pct=-1.0)`` gave
  Darius a NEGATIVE ``new_dps`` (-13.56) on the BotRK row; ``2.0`` doubled
  the proc. Same transport through ``POST /rank-bruiser``.

Fix: ``compute_dps`` raises the same ValueError the burst and ability-DPS
scorers raise; both rankers call it first, and both routes already map a
ValueError to 422. Every in-range value is byte-identical.
"""

from __future__ import annotations

import math

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.hybrid import rank_items_by_hybrid
from agents.daemon_slayer.rank import rank_items

_TARGET = dict(
    target_armor=100.0, target_mr=60.0,
    target_max_hp=2500.0, target_bonus_hp=1200.0,
)
_BAD = (-1.0, -0.01, 1.01, 2.0, math.nan, math.inf, -math.inf)
_GOOD = (0.0, 0.25, 0.5, 1.0)


@pytest.fixture(scope="module")
def snap():
    return DataSnapshot.load()


def _dps(snap, pct):
    return compute_dps(
        snap, champion_id="Vayne", level=11, item_ids=["3153"], mode="SR",
        target_current_hp_pct=pct, **_TARGET,
    )


def _carry(snap, pct):
    return rank_items(
        snap, champion_id="Vayne", level=11, mode="SR", top_n=200,
        target_current_hp_pct=pct, **_TARGET,
    )


def _bruiser(snap, pct):
    return rank_items_by_hybrid(
        snap, champion_id="Darius", level=11, mode="SR", top_n=200,
        target_current_hp_pct=pct, **_TARGET,
    )


@pytest.mark.parametrize("pct", _BAD)
def test_compute_dps_refuses_out_of_range(snap, pct):
    with pytest.raises(ValueError, match=r"target_current_hp_pct must be in \[0,1\]"):
        _dps(snap, pct)


@pytest.mark.parametrize("pct", _BAD)
def test_carry_ranker_refuses_out_of_range(snap, pct):
    with pytest.raises(ValueError, match=r"target_current_hp_pct must be in \[0,1\]"):
        _carry(snap, pct)


@pytest.mark.parametrize("pct", _BAD)
def test_bruiser_ranker_refuses_out_of_range(snap, pct):
    with pytest.raises(ValueError, match=r"target_current_hp_pct must be in \[0,1\]"):
        _bruiser(snap, pct)


@pytest.mark.parametrize("pct", (-1.0, 2.0))
def test_burst_and_ability_dps_contract_is_unchanged(snap, pct):
    # The sibling scorers that already validated: the shared message is the
    # contract this fix copies, so pin it here beside the new sites.
    with pytest.raises(ValueError, match=r"target_current_hp_pct must be in \[0,1\]"):
        compute_burst_damage(snap, "Zed", 11, target_current_hp_pct=pct)
    with pytest.raises(ValueError, match=r"target_current_hp_pct must be in \[0,1\]"):
        compute_ability_dps(snap, "Ahri", 11, target_current_hp_pct=pct)


@pytest.mark.parametrize("pct", _GOOD)
def test_in_range_values_stay_finite_and_non_negative(snap, pct):
    r = _dps(snap, pct)
    assert math.isfinite(r.weighted_dps) and r.weighted_dps >= 0.0
    rows = _carry(snap, pct).ranked
    assert rows and all(math.isfinite(x.delta_dps) for x in rows)
    botrk = [x for x in _bruiser(snap, pct).ranked if x.item_id == "3153"]
    assert botrk and botrk[0].new_dps >= 0.0


def test_botrk_proc_is_monotone_across_the_valid_range(snap):
    # The %-current-HP proc only ever shrinks as the target loses HP.
    deltas = [
        next(x.delta_dps for x in _carry(snap, p).ranked if x.item_id == "3153")
        for p in _GOOD
    ]
    assert deltas == sorted(deltas)
    assert deltas[0] < deltas[-1]


_ROUTE_BODY = {"level": 11, "mode": "SR", "top": 200, **_TARGET}


@pytest.fixture
def served(snap):
    prior = server._CACHE._snap
    server._CACHE.set(snap)
    yield
    server._CACHE._snap = prior


@pytest.mark.usefixtures("served")
@pytest.mark.parametrize("pct", (-1.0, 2.0))
@pytest.mark.parametrize(
    "route, champion",
    [(server._route_rank, "Vayne"), (server._route_rank_bruiser, "Darius")],
)
def test_routes_answer_422_for_a_finite_out_of_range_value(route, champion, pct):
    body = {**_ROUTE_BODY, "champion": champion, "target_current_hp_pct": pct}
    with pytest.raises(server._ApiError) as exc:
        route(body)
    assert exc.value.status == 422


@pytest.mark.usefixtures("served")
@pytest.mark.parametrize(
    "route, champion",
    [(server._route_rank, "Vayne"), (server._route_rank_bruiser, "Darius")],
)
def test_routes_still_answer_for_an_in_range_value(route, champion):
    body = {**_ROUTE_BODY, "champion": champion, "target_current_hp_pct": 0.5}
    out = route(body)
    assert out["ranked"]

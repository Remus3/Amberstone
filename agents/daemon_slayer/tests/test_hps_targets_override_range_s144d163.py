"""S144-D-163 - ``targets_per_proc_override`` never credits negative or NaN throughput.

Measured at HEAD (lane/ds, 2026-11-08): the override multiplies every item's
per-proc heal and shield in ``compute_hps``. Soraka L11 with Redemption 3107 +
Locket 3190 + Staff of Flowing Water 6616 read item ``direct_throughput`` 7.09
at override 1.0, but -7.09 at -1.0 (a finite value ``_opt_targets_override``
accepts, so ``POST /hps`` and ``POST /rank-enchanter`` both served it), and
NaN at NaN or +inf through the Python API (0 * inf on a zero-proc term).

Contract after the fix (adjudicated against the existing
``test_engine_robustness_p1l12`` pin, which already calls -5.0 legal and says
"zero/negative targets => no positive throughput credit"): a negative override
reads as 0.0 (no targets), a non-finite or unconvertible one raises ValueError
in ``compute_hps`` and ``rank_items_by_hps`` (both routes map it to 422), and
None plus every finite value >= 0 are unchanged.
"""
from __future__ import annotations

import math

import pytest

from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hps import compute_hps, rank_items_by_hps

_ITEMS = ["3107", "3190", "6616"]
_NON_FINITE = (float("nan"), float("inf"), float("-inf"))


@pytest.fixture(scope="module")
def snap():
    return DataSnapshot.load()


def _hps(snap, override):
    return compute_hps(snap, "Soraka", 11, item_ids=_ITEMS,
                       targets_per_proc_override=override)


def test_the_build_really_scales_on_the_override(snap):
    # Anchor: without real heal formulas every assertion below is vacuous.
    one = _hps(snap, 1.0)
    two = _hps(snap, 2)
    assert one.direct_throughput > 0.0
    assert math.isclose(two.direct_throughput, 2.0 * one.direct_throughput)
    assert _hps(snap, None).direct_throughput > 0.0
    assert _hps(snap, None).targets_per_proc_override is None


@pytest.mark.parametrize("neg", [-1.0, -0.5, -5])
def test_negative_reads_as_zero_targets(snap, neg):
    zero = _hps(snap, 0.0)
    got = _hps(snap, neg)
    assert got.direct_throughput == 0.0
    assert got.direct_throughput >= 0.0
    assert got.total_throughput == zero.total_throughput
    assert got.targets_per_proc_override == 0.0
    assert not any(str(neg) in n for n in got.notes)


@pytest.mark.parametrize("bad", _NON_FINITE, ids=repr)
def test_compute_hps_refuses_non_finite(snap, bad):
    with pytest.raises(ValueError, match="targets_per_proc_override"):
        _hps(snap, bad)


@pytest.mark.parametrize("bad", _NON_FINITE, ids=repr)
def test_rank_items_by_hps_refuses_non_finite(snap, bad):
    with pytest.raises(ValueError, match="targets_per_proc_override"):
        rank_items_by_hps(snap, champion_id="Soraka", level=11,
                          current_item_ids=["6617"],
                          targets_per_proc_override=bad)


def test_compute_hps_refuses_unconvertible(snap):
    with pytest.raises(ValueError, match="targets_per_proc_override"):
        _hps(snap, "two")


def test_rank_items_by_hps_negative_never_credits_negative_delta(snap):
    r = rank_items_by_hps(snap, champion_id="Soraka", level=11,
                          current_item_ids=["6617"],
                          targets_per_proc_override=-1.0, top_n=200)
    z = rank_items_by_hps(snap, champion_id="Soraka", level=11,
                          current_item_ids=["6617"],
                          targets_per_proc_override=0.0, top_n=200)
    assert r.ranked
    assert [x.to_dict() for x in r.ranked] == [x.to_dict() for x in z.ranked]


@pytest.fixture
def served(snap):
    prior = server._CACHE._snap
    server._CACHE.set(snap)
    yield
    server._CACHE._snap = prior


_ROUTES = [
    (server._route_hps, {"champion": "Soraka", "level": 11, "items": _ITEMS}),
    (server._route_rank_enchanter,
     {"champion": "Soraka", "level": 11, "items": ["6617"]}),
]


@pytest.mark.usefixtures("served")
@pytest.mark.parametrize("route, body", _ROUTES, ids=["hps", "rank-enchanter"])
def test_routes_answer_a_negative_override_as_zero(route, body):
    neg = route({**body, "targets_per_proc_override": -1})
    zero = route({**body, "targets_per_proc_override": 0})
    assert neg == zero


def test_hps_route_item_throughput_never_negative(snap):
    prior = server._CACHE._snap
    server._CACHE.set(snap)
    try:
        out = server._route_hps({"champion": "Soraka", "level": 11,
                                 "items": _ITEMS,
                                 "targets_per_proc_override": -1})
    finally:
        server._CACHE._snap = prior
    assert out["direct_throughput"] == 0.0

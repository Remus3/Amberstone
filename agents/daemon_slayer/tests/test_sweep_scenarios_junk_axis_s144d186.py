"""S144-D-186..188 - ``sweep_scenarios`` keeps its every-cell-present,
fail-soft contract for a junk item set, a junk level, and a combo / mana walk
that resolved nothing.

Measured at HEAD before the fix (Lux L11, Rabadon's Deathcap 3089, profile
30/30/1900/800, snapshot 16.22.1):

* S144-D-186: an item set that is not iterable (True, 1.5, object()) raised
  TypeError out of ``_coerce_item_set`` and aborted the WHOLE sweep, on every
  metric.
* S144-D-187: a level ``int()`` rejects ("x", None, NaN, +-inf) raised
  ValueError / TypeError / OverflowError and aborted the whole sweep; a bool
  level was read as level 1 (True) or 0 (False).
* S144-D-188: on ``combo`` and ``mana_bounded_dps`` a cell whose walk
  resolved NO action (unknown champion, empty champion, a sequence with no
  readable token, a level outside [1, 18]) gave a FINITE 0.0 with an empty
  note, so it passed invariant 4 and read like a real measurement, while
  ``dps`` / ``burst`` / ``rune_burst`` gave NaN for the same inputs.

Contract pinned here: a bad item set or a bad level fails only its own cells,
each with ``value = NaN`` and one fixed note, without reaching a scorer; the
cell count stays ``levels x item_sets x profiles x modes``; a bad set is
stamped ``item_ids=()`` and a bad level ``level=0`` (not a game level); the
good cells in the same sweep are byte-identical to a sweep without the bad
entry. A falsy set is still the empty set and a numeric level string / float
still reads as before. A combo / mana cell with no resolved action is NaN
with a fixed note; one with resolved actions is unchanged, and so is an
all-locked rotation (a real 0.0: the ult is not learned yet).
"""
from __future__ import annotations

import logging
import math
from dataclasses import astuple

import pytest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.scenario_matrix import (
    VALID_METRICS,
    check_invariants,
    sweep_scenarios,
)

_CHAMP = "Lux"
_SET = ("3089",)
_PROFILE = (30.0, 30.0, 1900.0, 800.0)
_SET_NOTE = "item set not readable"
_LEVEL_NOTE = "level not a whole number"
_NOTHING_NOTE = "walk resolved no action"
_WALKERS = ("combo", "mana_bounded_dps")

_BAD_SETS = [
    pytest.param(True, id="true"),
    pytest.param(1.5, id="float"),
    pytest.param(object(), id="object"),
]
_BAD_LEVELS = [
    pytest.param("x", id="str"),
    pytest.param(None, id="none"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="inf"),
    pytest.param(float("-inf"), id="neg_inf"),
    pytest.param(True, id="true"),
    pytest.param(False, id="false"),
    pytest.param("11.5", id="float_str"),
]


@pytest.fixture(scope="module")
def snap():
    return DataSnapshot.load()


@pytest.fixture(autouse=True)
def _quiet(caplog):
    caplog.set_level(logging.CRITICAL)


def _key(cells):
    return [
        (c.level, c.item_ids, c.target_armor, c.target_mr, c.mode, c.metric,
         "nan" if math.isnan(c.value) else c.value, c.note)
        for c in cells
    ]


@pytest.mark.parametrize("metric", VALID_METRICS)
@pytest.mark.parametrize("bad", _BAD_SETS)
def test_bad_item_set_fails_only_its_own_cells(snap, metric, bad):
    cells = sweep_scenarios(
        _CHAMP, [11], [list(_SET), bad], [_PROFILE], metric=metric,
        snapshot=snap,
    )
    assert len(cells) == 2
    good, junk = cells
    assert junk.item_ids == ()
    assert math.isnan(junk.value)
    assert junk.note == _SET_NOTE
    ref = sweep_scenarios(
        _CHAMP, [11], [list(_SET)], [_PROFILE], metric=metric, snapshot=snap,
    )
    assert _key([good]) == _key(ref)


@pytest.mark.parametrize("falsy", [False, "", None, 0, ()])
def test_falsy_item_set_is_still_the_empty_set(snap, falsy):
    (cell,) = sweep_scenarios(
        _CHAMP, [11], [falsy], [_PROFILE], metric="dps", snapshot=snap,
    )
    assert cell.item_ids == ()
    assert cell.note != _SET_NOTE
    (ref,) = sweep_scenarios(
        _CHAMP, [11], [[]], [_PROFILE], metric="dps", snapshot=snap,
    )
    assert _key([cell]) == _key([ref])


@pytest.mark.parametrize("metric", VALID_METRICS)
@pytest.mark.parametrize("bad", _BAD_LEVELS)
def test_bad_level_fails_only_its_own_cells(snap, metric, bad):
    cells = sweep_scenarios(
        _CHAMP, [11, bad], [list(_SET)], [_PROFILE], metric=metric,
        snapshot=snap,
    )
    assert len(cells) == 2
    good, junk = cells
    assert junk.level == 0
    assert isinstance(junk.level, int) and not isinstance(junk.level, bool)
    assert math.isnan(junk.value)
    assert junk.note == _LEVEL_NOTE
    ref = sweep_scenarios(
        _CHAMP, [11], [list(_SET)], [_PROFILE], metric=metric, snapshot=snap,
    )
    assert _key([good]) == _key(ref)


@pytest.mark.parametrize("level", ["11", 11.0, 11.7])
def test_numeric_level_reads_as_before(snap, level):
    (cell,) = sweep_scenarios(
        _CHAMP, [level], [list(_SET)], [_PROFILE], metric="dps", snapshot=snap,
    )
    (ref,) = sweep_scenarios(
        _CHAMP, [11], [list(_SET)], [_PROFILE], metric="dps", snapshot=snap,
    )
    assert _key([cell]) == _key([ref])


def test_bad_axes_mixed_sweep_keeps_cell_count_and_invariants_run(snap):
    cells = sweep_scenarios(
        _CHAMP, [8, "x", 11], [list(_SET), True], [_PROFILE, (60.0, 60.0)],
        modes=("SR", "ARAM"), metric="dps", snapshot=snap,
    )
    assert len(cells) == 3 * 2 * 2 * 2
    violations = check_invariants(cells)
    assert "no_nan" in {v.invariant for v in violations}
    notes = {c.note for c in cells if math.isnan(c.value)}
    assert notes == {_SET_NOTE, _LEVEL_NOTE}


_NOTHING = [
    pytest.param("NotARealChampion", 11, None, id="unknown_champion"),
    pytest.param("", 11, None, id="empty_champion"),
    pytest.param(_CHAMP, 11, ["ZZ"], id="no_readable_token"),
    pytest.param(_CHAMP, 0, None, id="level_0"),
    pytest.param(_CHAMP, 99, None, id="level_99"),
]


@pytest.mark.parametrize("metric", _WALKERS)
@pytest.mark.parametrize("champ, level, seq", _NOTHING)
def test_walk_with_no_resolved_action_is_nan(snap, metric, champ, level, seq):
    (cell,) = sweep_scenarios(
        champ, [level], [list(_SET)], [_PROFILE], metric=metric,
        snapshot=snap, sequence=seq,
    )
    assert math.isnan(cell.value)
    assert cell.note == _NOTHING_NOTE
    assert "no_nan" in {v.invariant for v in check_invariants([cell])}


@pytest.mark.parametrize("metric", _WALKERS)
@pytest.mark.parametrize("champ", [_CHAMP, "Garen", "Caitlyn"])
@pytest.mark.parametrize("seq", [["R"], ["E", "R"]], ids=["R", "E_R"])
def test_all_locked_rotation_is_a_real_zero(snap, metric, champ, seq):
    # Verifier 1 refutation: mana_sim drops a locked cast without a hit, so an
    # all-locked L1 rotation has no hits yet is a real 0.0, as combo / burst
    # read it.
    (cell,) = sweep_scenarios(
        champ, [1], [[]], [_PROFILE], metric=metric, snapshot=snap,
        sequence=seq,
    )
    assert cell.value == 0.0
    assert cell.note == ""


@pytest.mark.parametrize("metric", _WALKERS)
def test_walk_with_resolved_actions_is_unchanged(snap, metric):
    from agents.daemon_slayer.combo import compute_combo
    from agents.daemon_slayer.mana_sim import compute_mana_bounded_combo

    (cell,) = sweep_scenarios(
        _CHAMP, [11], [list(_SET)], [_PROFILE], metric=metric, snapshot=snap,
    )
    kw = dict(
        item_ids=list(_SET), sequence=["Q", "AA", "W", "R"],
        target_armor=_PROFILE[0], target_mr=_PROFILE[1],
        target_max_hp=_PROFILE[2], target_bonus_hp=_PROFILE[3], mode="SR",
        snapshot=snap,
    )
    if metric == "combo":
        want = float(compute_combo(_CHAMP, 11, **kw).total_mitigated)
    else:
        want = float(compute_mana_bounded_combo(_CHAMP, 11, **kw).bounded_dps)
    assert cell.note == ""
    assert math.isfinite(cell.value) and cell.value > 0.0
    assert cell.value == want


def test_scenario_cell_stays_a_plain_tuple_shape(snap):
    (cell,) = sweep_scenarios(
        _CHAMP, ["x"], [True], [_PROFILE], metric="dps", snapshot=snap,
    )
    assert len(astuple(cell)) == 9
    assert cell.note == _LEVEL_NOTE

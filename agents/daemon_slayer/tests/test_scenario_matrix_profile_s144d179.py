"""S144-D-179..180 - ``sweep_scenarios`` keeps its every-cell-present,
fail-soft contract for a bad target profile entry.

Measured at HEAD before the fix (Caitlyn L11, 3031, profile 100/60/2500/1200):

* S144-D-179: a non-numeric or overflowing profile entry (None, "x", 10**400)
  raised TypeError / ValueError / OverflowError out of ``_coerce_profile`` and
  aborted the WHOLE sweep, while a NaN entry only failed its own cells.
* S144-D-180: a NaN / +-inf profile entry gave a FINITE 0.0 value with an
  empty note on the ``combo`` and ``mana_bounded_dps`` metrics (those scorers
  fail soft to a zero total), so the cell passed invariant 4 and read like a
  real measurement; ``dps`` / ``burst`` / ``rune_burst`` gave NaN with the
  generic "scorer raised" note.

Contract pinned here: a profile entry that is not a finite number never
reaches a scorer; each of its cells carries ``value = NaN`` and the fixed note
"target profile not a finite number" on every metric, the cell count stays
``levels x item_sets x profiles x modes``, and the good profiles in the same
sweep are byte-identical to a sweep without the bad one. A numeric string
still reads as a number.
"""
from __future__ import annotations

import logging
import math

import pytest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.scenario_matrix import (
    VALID_METRICS,
    check_invariants,
    sweep_scenarios,
)

_GOOD = (100.0, 60.0, 2500.0, 1200.0)
_NOTE = "target profile not a finite number"
_BAD = [
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="inf"),
    pytest.param(float("-inf"), id="neg_inf"),
    pytest.param(None, id="none"),
    pytest.param("x", id="str"),
    pytest.param(10 ** 400, id="huge_int"),
]


@pytest.fixture(scope="module")
def snap():
    return DataSnapshot.load()


@pytest.fixture(autouse=True)
def _quiet_logs():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def _sweep(snap, profiles, metric):
    return sweep_scenarios(
        "Caitlyn", [6, 11], [["3031"]], profiles, metric=metric,
        snapshot=snap, runes=[8005],
    )


def _sig(cell):
    return (cell.level, cell.item_ids, cell.target_armor, cell.target_mr,
            cell.mode, cell.metric, cell.value, cell.note)


@pytest.mark.parametrize("bad", _BAD)
@pytest.mark.parametrize("slot", [0, 1, 2, 3])
@pytest.mark.parametrize("metric", VALID_METRICS)
def test_bad_profile_entry_fails_only_its_own_cells(snap, metric, slot, bad):
    bad_profile = list(_GOOD)
    bad_profile[slot] = bad
    cells = _sweep(snap, [_GOOD, tuple(bad_profile)], metric)
    assert len(cells) == 2 * 1 * 2 * 1
    good_cells = cells[0::2]
    bad_cells = cells[1::2]
    for c in bad_cells:
        assert math.isnan(c.value), (metric, c.value)
        assert c.note == _NOTE
    ref = _sweep(snap, [_GOOD], metric)
    assert [_sig(c) for c in good_cells] == [_sig(c) for c in ref]


@pytest.mark.parametrize("metric", ["combo", "mana_bounded_dps"])
def test_nonfinite_profile_is_an_invariant_violation_not_a_zero(snap, metric):
    cells = _sweep(snap, [(float("nan"), 60.0, 2500.0, 1200.0)], metric)
    assert all(c.value != 0.0 for c in cells)
    names = {v.invariant for v in check_invariants(cells)}
    assert "no_nan" in names


@pytest.mark.parametrize("metric", VALID_METRICS)
def test_short_profile_and_numeric_string_still_read(snap, metric):
    two_wide = _sweep(snap, [(100.0, 60.0)], metric)
    padded = _sweep(snap, [(100.0, 60.0, 0.0, 0.0)], metric)
    assert [_sig(c) for c in two_wide] == [_sig(c) for c in padded]
    as_str = _sweep(snap, [("100", "60", "2500", "1200")], metric)
    assert [_sig(c) for c in as_str] == [_sig(c) for c in _sweep(
        snap, [_GOOD], metric)]
    assert all(c.note != _NOTE for c in as_str)

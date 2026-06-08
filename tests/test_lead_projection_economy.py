"""Tests for the HZ-A2 gold-income + power-spike primitives added to
core.lead_projection: minutes_for_level (the band->minute bridge), the gross
income benchmark, the cumulative-gold spike ladder, and spike-ETA. Pure +
deterministic - no engine, no snapshot, no network.
"""

from __future__ import annotations

import pytest

from core import lead_projection as lp


# --- minutes_for_level (inverse of the project_lead level benchmark) -------

@pytest.mark.parametrize(
    "level,minutes", [(2, 2.0), (6, 10.0), (11, 20.0), (16, 30.0)]
)
def test_minutes_for_level_matches_band_levels(level, minutes):
    # The HZ-A1 level bands (L2/L6/L11/L16) map to these representative minutes
    # via the shared level = 1 + 0.5*min benchmark.
    assert lp.minutes_for_level(level) == pytest.approx(minutes)


def test_minutes_for_level_floors_at_zero():
    assert lp.minutes_for_level(1) == pytest.approx(0.0)
    assert lp.minutes_for_level(0) == 0.0


def test_minutes_for_level_strictly_increasing():
    seq = [lp.minutes_for_level(level) for level in (2, 6, 11, 16)]
    assert seq == sorted(seq)
    assert len(set(seq)) == len(seq)


# --- income benchmark ------------------------------------------------------

def test_gold_income_aram_exceeds_sr():
    assert lp.gold_income_per_min("ARAM") > lp.gold_income_per_min("SR")


def test_gold_income_unknown_mode_falls_back_to_sr():
    assert lp.gold_income_per_min("URF") == lp.gold_income_per_min("SR")


def test_expected_gold_earned_linear_in_minutes():
    rate = lp.gold_income_per_min("SR")
    assert lp.expected_gold_earned(10.0, "SR") == pytest.approx(rate * 10.0)
    assert lp.expected_gold_earned(0.0, "SR") == 0.0


def test_expected_gold_earned_clamps_negative_minutes():
    assert lp.expected_gold_earned(-5.0, "SR") == 0.0


# --- spike ladder ----------------------------------------------------------

def test_spike_ladder_is_monotonic_increasing():
    targets = [target for _, target in lp.spike_ladder()]
    assert targets == sorted(targets)
    assert len(targets) == len(set(targets))


def test_next_spike_picks_first_unreached():
    first_label, first_target = lp.spike_ladder()[0]
    label, target = lp.next_spike(0.0)
    assert label == first_label
    assert target == first_target


def test_next_spike_advances_past_a_reached_threshold():
    first_target = lp.spike_ladder()[0][1]
    _, target = lp.next_spike(first_target + 1.0)
    assert target > first_target


def test_next_spike_all_reached_returns_complete():
    huge = lp.spike_ladder()[-1][1] + 10_000.0
    label, _ = lp.next_spike(huge)
    assert label == lp.SPIKE_COMPLETE


def test_spike_threshold_known_and_unknown():
    first_label, first_target = lp.spike_ladder()[0]
    assert lp.spike_threshold(first_label) == first_target
    assert lp.spike_threshold("nope") == 0.0


# --- spike ETA -------------------------------------------------------------

def test_spike_eta_one_minute_of_income():
    rate = lp.gold_income_per_min("SR")
    # target == exactly one minute of income from zero -> 60 seconds.
    assert lp.spike_eta_seconds(0.0, rate, "SR") == pytest.approx(60.0)


def test_spike_eta_already_reached_is_zero():
    assert lp.spike_eta_seconds(5000.0, 3000.0, "SR") == 0.0


def test_spike_eta_aram_faster_than_sr():
    sr = lp.spike_eta_seconds(0.0, 3000.0, "SR")
    aram = lp.spike_eta_seconds(0.0, 3000.0, "ARAM")
    assert aram < sr


# --- composition the precompute relies on (band -> gold -> spike -> eta) ---

def test_band_gold_spike_eta_compose():
    minutes = lp.minutes_for_level(6)  # ~ minute 10
    gold = lp.expected_gold_earned(minutes, "SR")
    assert gold > 0.0
    label, target = lp.next_spike(gold)
    eta = lp.spike_eta_seconds(gold, target, "SR")
    assert eta >= 0.0
    if label != lp.SPIKE_COMPLETE:
        assert target > gold

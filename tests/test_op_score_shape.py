"""Tests for core.op_score_shape - the deterministic arc-shape classifier over
the op_score_curve per-minute series.

Pure synthetic series with hand-built shapes; assertions are on the chosen label
+ the documented bounds (start/end/trend/volatility), never on the gitignored
rewind db. The classifier owns no I/O so these need no fixtures.
"""
from __future__ import annotations

from core import op_score_shape as oss


def _label(series):
    arc = oss.classify_arc(series)
    assert arc is not None
    assert arc["label"] in oss.KNOWN_LABELS
    assert arc["read"]
    return arc


def test_snowball_high_start_rising():
    arc = _label([62, 64, 66, 68, 70, 72])
    assert arc["label"] == "Snowball"
    assert arc["trend"] > 0
    assert arc["start"] >= oss.LEVEL_HIGH


def test_ramping_low_start_rising():
    arc = _label([40, 44, 48, 52, 56, 60])
    assert arc["label"] == "Ramping"
    assert arc["trend"] >= oss.TREND_FLAT
    assert arc["start"] < oss.LEVEL_HIGH


def test_front_loaded_falling():
    arc = _label([70, 66, 62, 58, 54, 50])
    assert arc["label"] == "Front-loaded"
    assert arc["trend"] <= -oss.TREND_FLAT


def test_commanding_flat_high():
    arc = _label([72, 71, 73, 72, 71, 73])
    assert arc["label"] == "Commanding"
    assert abs(arc["trend"]) < oss.TREND_FLAT
    assert arc["volatility"] < oss.VOL_HIGH


def test_behind_flat_low():
    arc = _label([38, 37, 39, 38, 37, 39])
    assert arc["label"] == "Behind"
    assert abs(arc["trend"]) < oss.TREND_FLAT


def test_steady_flat_mid():
    arc = _label([50, 51, 49, 50, 51, 49])
    assert arc["label"] == "Steady"
    assert abs(arc["trend"]) < oss.TREND_FLAT


def test_volatile_swings_dominate_trend():
    # A big up/down swing reads Volatile even if the net endpoints rise.
    arc = _label([30, 70, 30, 70, 30, 72])
    assert arc["label"] == "Volatile"
    assert arc["volatility"] >= oss.VOL_HIGH


def test_too_few_points_is_none():
    assert oss.classify_arc([50, 50, 50]) is None
    assert oss.classify_arc([]) is None
    assert oss.classify_arc(None) is None


def test_none_gaps_are_dropped():
    # Thin-minute None gaps drop out; the remaining real points still classify.
    arc = oss.classify_arc([None, 60, 62, 64, 66, 68, None])
    assert arc is not None
    assert arc["label"] in oss.KNOWN_LABELS


def test_non_numeric_values_ignored():
    arc = oss.classify_arc([60, "x", 62, None, 64, 66])
    assert arc is not None
    assert arc["start"] >= 0.0


def test_bounds_are_rounded_and_in_range():
    arc = _label([55.04, 57.06, 59.08, 61.02, 63.07, 65.09])
    for k in ("start", "end", "trend", "volatility"):
        assert isinstance(arc[k], float)
        # one decimal place of rounding
        assert round(arc[k], 1) == arc[k]
    assert 0.0 <= arc["start"] <= 100.0
    assert 0.0 <= arc["end"] <= 100.0


def test_summarize_curve_splits_win_and_loss():
    payload = {
        "minutes": [
            {"minute": 0, "win_avg": 62, "loss_avg": 40},
            {"minute": 1, "win_avg": 64, "loss_avg": 44},
            {"minute": 2, "win_avg": 66, "loss_avg": 48},
            {"minute": 3, "win_avg": 68, "loss_avg": 52},
            {"minute": 4, "win_avg": 70, "loss_avg": 56},
            {"minute": 5, "win_avg": 72, "loss_avg": 60},
        ]
    }
    out = oss.summarize_curve(payload)
    assert set(out) == {"win", "loss"}
    assert out["win"]["label"] == "Snowball"
    assert out["loss"]["label"] == "Ramping"


def test_summarize_curve_safe_on_empty_and_none():
    assert oss.summarize_curve({"minutes": []}) == {"win": None, "loss": None}
    assert oss.summarize_curve({}) == {"win": None, "loss": None}
    assert oss.summarize_curve(None) == {"win": None, "loss": None}


def test_summarize_curve_handles_thin_null_series():
    # win has >= MIN_POINTS, loss is all None (too thin) -> loss arc is None.
    payload = {
        "minutes": [
            {"minute": m, "win_avg": 50 + m, "loss_avg": None}
            for m in range(6)
        ]
    }
    out = oss.summarize_curve(payload)
    assert out["win"] is not None
    assert out["loss"] is None

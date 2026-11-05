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


# ---------------------------------------------------------------------------
# s144 true-audit cycle 131 (RM-1617..RM-1623). Each test below was RED
# against the pre-hardening module. The classifier's docstring promises
# "Pure - never raises", and its output dict lands in a JSON HTTP response, so
# every number it returns must be finite (json.dumps writes a bare NaN /
# Infinity token that the browser's JSON.parse rejects).
# ---------------------------------------------------------------------------

import json  # noqa: E402
import math  # noqa: E402

import pytest  # noqa: E402

_NUM_KEYS = ("start", "end", "trend", "volatility")


def _strict_json_ok(arc):
    """The arc must serialize as strict JSON (no NaN / Infinity tokens)."""
    json.dumps(arc, allow_nan=False)
    for k in _NUM_KEYS:
        assert math.isfinite(arc[k]), (k, arc[k])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_points_are_dropped_not_propagated(bad):
    # RM-1617: NaN / +-inf passed the float() guard and poisoned every
    # mean - NaN numbers in the payload, and a label decided by NaN
    # comparisons (inf read as Volatile).
    arc = oss.classify_arc([50, bad, 50, 50, 50])
    assert arc is not None
    _strict_json_ok(arc)
    assert arc["label"] == "Steady"
    assert arc["volatility"] == 0.0


def test_only_non_finite_points_is_unreadable():
    nan = float("nan")
    assert oss.classify_arc([nan, nan, nan, nan, nan]) is None


def test_bools_are_not_scores():
    # RM-1618: True read as 1.0 and False as 0.0, inventing a collapse.
    assert oss.classify_arc([True, False, True, False]) is None
    arc = oss.classify_arc([50, False, 50, 50, 50])
    assert arc is not None
    assert arc["label"] == "Steady"
    assert arc["volatility"] == 0.0


@pytest.mark.parametrize("text", ["55", " 60 ", "1e2", b"55", bytearray(b"55")])
def test_text_and_bytes_points_are_not_scores(text):
    # RM-1618: the existing "x" test pinned non-numeric text as ignored,
    # but numeric-looking text (and bytes, which float() also parses) was
    # silently admitted as a score.
    assert oss.classify_arc([text, text, text, text]) is None


def test_huge_int_point_does_not_raise():
    # RM-1619: float(10**400) raised OverflowError, which the
    # (TypeError, ValueError) guard missed - the "never raises" promise broke.
    arc = oss.classify_arc([50, 10 ** 400, 50, 50, 50])
    assert arc is not None
    _strict_json_ok(arc)
    assert arc["label"] == "Steady"


class _FloatNan(float):
    def __float__(self):
        return float("nan")


class _IntInf(int):
    def __float__(self):
        return float("inf")


@pytest.mark.parametrize("sneaky", [_FloatNan(50.0), _IntInf(50)])
def test_subclass_overriding_float_cannot_smuggle_non_finite(sneaky):
    # RM-1617 (verifier follow-up): an int / float subclass passed the
    # range check on its own value, then float() handed back NaN / inf.
    arc = oss.classify_arc([50, sneaky, 50, 50, 50])
    assert arc is not None
    _strict_json_ok(arc)
    assert arc["label"] == "Steady"


@pytest.mark.parametrize("off_scale", [-5, 100.5, 1e308, -1e308])
def test_off_scale_points_are_dropped(off_scale):
    # RM-1620: every threshold lives on the 0-100 composite scale; a value
    # off that scale is not a composite score. Two 1e308 points also
    # overflowed the mean to inf and the trend to NaN.
    arc = oss.classify_arc([50, off_scale, off_scale, 50, 50, 50])
    assert arc is not None
    _strict_json_ok(arc)
    assert arc["label"] == "Steady"


def test_scale_bounds_are_inclusive():
    arc = oss.classify_arc([0, 0, 100, 100])
    assert arc is not None
    assert arc["start"] == 0.0
    assert arc["end"] == 100.0


@pytest.mark.parametrize("series", ["5555", b"\x32\x32\x32\x32", {50: 1, 60: 2, 70: 3, 80: 4}, 5, 5.0, object()])
def test_non_sequence_series_is_unreadable_not_iterated(series):
    # RM-1621: a str was iterated character by character, bytes yielded
    # ints (b"2222" read as four 50s), a dict iterated its keys, and a bare
    # number raised TypeError ("never raises").
    assert oss.classify_arc(series) is None


def test_tuple_and_generator_series_still_classify():
    assert oss.classify_arc((50, 51, 49, 50, 51, 49))["label"] == "Steady"
    assert oss.classify_arc(v for v in (50, 51, 49, 50, 51, 49))["label"] == "Steady"


def test_label_agrees_with_the_reported_trend():
    # RM-1622: the label was decided on the UNROUNDED trend while the
    # payload reports it rounded to 0.1, so a trend of 5.96 was reported as
    # 6.0 (>= TREND_FLAT, the documented rise rule) under the label Steady.
    arc = oss.classify_arc([50, 50, 50, 50, 55.96, 55.96])
    assert arc["trend"] == 6.0
    assert arc["label"] == "Ramping"


def test_label_agrees_with_the_reported_start():
    # RM-1622: start 59.96 was reported 60.0 (>= LEVEL_HIGH) yet labelled
    # Ramping, the not-strong-start branch.
    arc = oss.classify_arc([59.96, 59.96, 63, 63, 70, 70])
    assert arc["start"] == 60.0
    assert arc["trend"] >= oss.TREND_FLAT
    assert arc["label"] == "Snowball"


def test_label_agrees_with_the_reported_volatility():
    # RM-1622: mean jump 10.96 reported as 11.0 (>= VOL_HIGH) but not
    # labelled Volatile.
    arc = oss.classify_arc([50, 60.96, 50, 60.96, 50, 60.96, 50, 60.96, 50, 60.96, 50])
    assert arc["volatility"] == 11.0
    assert arc["label"] == "Volatile"


@pytest.mark.parametrize("payload", [[1, 2], "minutes", 7, {"minutes": "abc"}, {"minutes": {"a": 1}}, {"minutes": 5}])
def test_summarize_curve_malformed_payload_is_safe(payload):
    # RM-1623: a non-dict payload or a non-list "minutes" raised
    # AttributeError / TypeError despite the "Safe" docstring.
    assert oss.summarize_curve(payload) == {"win": None, "loss": None}


def test_summarize_curve_skips_non_dict_rows():
    # RM-1623: one non-dict row (None, a list, a str) raised
    # AttributeError and lost BOTH arcs; it now reads as a gap.
    rows = [{"minute": m, "win_avg": 50 + m, "loss_avg": 40} for m in range(6)]
    rows.insert(2, None)
    rows.insert(4, [1, 2])
    rows.insert(5, "row")
    out = oss.summarize_curve({"minutes": rows})
    assert out["win"] is not None
    assert out["win"]["label"] == "Steady"
    assert out["loss"]["label"] == "Behind"

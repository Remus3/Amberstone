"""aggregator G lane-vs-full WPA totals (R2 lift) on /api/post-game-wpa.

_wpa_totals is a pure sum over the per-event ``wpa`` already in the response:
lane-phase (game_time <= 900s) vs full-game net (+/-) and abs swing, plus the
lane_share fraction. No new data source, no model change. These pin the math.
"""
from __future__ import annotations

import pytest

from dashboard.routes_post_game_wpa import _LANE_END_S, _wpa_totals


def test_empty_events():
    t = _wpa_totals([])
    assert t["lane"]["events"] == 0
    assert t["full"]["events"] == 0
    assert t["lane"]["net_wpa"] == 0.0
    assert t["lane_share"] == 0.0
    assert t["lane_end_s"] == _LANE_END_S


def test_lane_vs_full_split():
    events = [
        {"game_time": 120, "wpa": 0.05},
        {"game_time": 600, "wpa": -0.02},
        {"game_time": 1500, "wpa": 0.10},  # past the lane boundary
    ]
    t = _wpa_totals(events)
    assert t["lane"]["events"] == 2
    assert t["full"]["events"] == 3
    assert t["lane"]["net_wpa"] == round(0.05 - 0.02, 4)
    assert t["lane"]["abs_wpa"] == round(0.05 + 0.02, 4)
    assert t["full"]["net_wpa"] == round(0.05 - 0.02 + 0.10, 4)
    assert t["full"]["abs_wpa"] == round(0.05 + 0.02 + 0.10, 4)
    assert t["lane_share"] == round(0.07 / 0.17, 4)


def test_boundary_is_inclusive():
    # an event exactly at lane_end_s counts as lane
    t = _wpa_totals([{"game_time": _LANE_END_S, "wpa": 0.04}])
    assert t["lane"]["events"] == 1


def test_non_numeric_or_bool_wpa_skipped():
    events = [
        {"game_time": 100, "wpa": None},
        {"game_time": 100, "wpa": "x"},
        {"game_time": 100, "wpa": True},  # bool is not a real wpa
        {"game_time": 100, "wpa": 0.02},
    ]
    t = _wpa_totals(events)
    assert t["full"]["events"] == 1
    assert t["lane"]["events"] == 1
    assert t["full"]["net_wpa"] == 0.02


def test_missing_game_time_counts_as_lane():
    t = _wpa_totals([{"wpa": 0.03}])  # absent game_time -> 0 -> lane
    assert t["lane"]["events"] == 1
    assert t["full"]["events"] == 1


def test_lane_share_zero_when_no_swing():
    t = _wpa_totals([{"game_time": 100, "wpa": 0.0}])
    assert t["full"]["abs_wpa"] == 0.0
    assert t["lane_share"] == 0.0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

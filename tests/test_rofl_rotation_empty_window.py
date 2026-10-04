"""Hand-off residual (2026-10-03): ~104 EMPTY-window observations in the
per-player pull logs (pre-RM-484 throttled listings recorded as []). As the
first or last sample, an empty window reads as "every game dropped" / "all
new" - a fabricated rotation verdict. The log lives OUTSIDE the repo and is
append-only, so the fix is on the READ side: excluded from the comparison,
still counted.
"""
from __future__ import annotations

import core.rofl_archive as ra


def test_trailing_empty_window_does_not_fake_a_full_drop(tmp_path):
    ra.record_pull_observation(tmp_path, "A#1", ["NA1_1", "NA1_2"], now=100.0)
    ra.record_pull_observation(tmp_path, "A#1", ["NA1_1", "NA1_2"], now=200.0)
    ra.record_pull_observation(tmp_path, "A#1", [], now=300.0)
    rep = ra.pull_rotation_report(tmp_path)["A#1"]
    assert rep["rotated"] is False
    assert rep["dropped_ids"] == []
    assert rep["observations"] == 2 and rep["empty_observations"] == 1


def test_leading_empty_window_does_not_fake_all_new(tmp_path):
    ra.record_pull_observation(tmp_path, "A#1", [], now=50.0)
    ra.record_pull_observation(tmp_path, "A#1", ["NA1_1"], now=100.0)
    ra.record_pull_observation(tmp_path, "A#1", ["NA1_1"], now=200.0)
    rep = ra.pull_rotation_report(tmp_path)["A#1"]
    assert rep["rotated"] is False and rep["new_ids"] == []


def test_only_empty_windows_say_nothing(tmp_path):
    ra.record_pull_observation(tmp_path, "A#1", [], now=50.0)
    ra.record_pull_observation(tmp_path, "A#1", [], now=60.0)
    rep = ra.pull_rotation_report(tmp_path)["A#1"]
    assert rep["rotated"] is None and rep["empty_observations"] == 2


def test_real_rotation_survives_interleaved_empties(tmp_path):
    ra.record_pull_observation(tmp_path, "A#1", ["NA1_1"], now=100.0)
    ra.record_pull_observation(tmp_path, "A#1", [], now=150.0)
    ra.record_pull_observation(tmp_path, "A#1", ["NA1_2"], now=200.0)
    rep = ra.pull_rotation_report(tmp_path)["A#1"]
    assert rep["rotated"] is True and rep["new_ids"] == ["NA1_2"]

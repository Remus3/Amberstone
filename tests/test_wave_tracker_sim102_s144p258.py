"""RM-1757 - WaveTracker.update keeps the OLDEST sample inside the 15 s window after the SIM102 merge."""
from __future__ import annotations

from coach_integration._sr_prompt import WaveTracker


def test_first_in_window_sample_is_the_reference():
    wt = WaveTracker()
    # Fills the deque: t=100 is outside the 15 s window of t=120, t=110 is the first inside it.
    wt.update(0, 100.0)
    wt.update(10, 110.0)
    wt.update(20, 115.0)
    # reference is the t=110 sample (cs 10): (40 - 10) / 10 s = 3.0 cs/s -> hard_shove.
    assert wt.update(40, 120.0) == "hard_shove"


def test_newer_in_window_sample_never_replaces_the_reference():
    wt = WaveTracker()
    wt.update(0, 100.0)
    # both samples are in window; the oldest (t=100, cs 0) must win: (30 - 0) / 10 s = 3.0 -> hard_shove.
    # If a newer sample replaced it the reference would be the appended sample itself (dt 0 -> unknown).
    assert wt.update(30, 110.0) == "hard_shove"


def test_no_sample_in_window_is_unknown():
    wt = WaveTracker()
    # the only sample is the one just appended, dt == 0 < 2 -> unknown
    assert wt.update(5, 100.0) == "unknown"

"""s144 true-audit regressions for core/ward_events.py.

Each class pins one weakness the audit found; every test here was RED
against the pre-fix module:

  * a read with a NARROW window evicted entries a wider-window reader
    still needed (the eviction horizon was the caller's own window), so a
    ``/api/ward-heat?window_s=5`` request erased wards from the default
    90 s view;
  * a NaN / inf / bool ``ts`` was stored, and a NaN at the head of the
    deque blocked the lazy GC forever while reporting itself in every
    window;
  * the snapshot returned every buffered entry after a left-only prune,
    so an out-of-order (older) entry behind a newer head, or an entry
    stamped after ``now_s``, was reported as inside the window;
  * a NaN ``now_s`` / ``window_s`` returned the whole buffer and an inf
    ``now_s`` wiped it;
  * ``lane_from_position`` read a NaN coordinate as jungle;
  * a non-str side / lane / ward_type whose truthiness or str() raises
    escaped ``record_ward`` / ``lanes_uncovered``, which promise never to
    raise on bad input.
"""
from __future__ import annotations

import unittest

from core import ward_events

NAN = float("nan")
INF = float("inf")


class _Hostile:
    """A value whose truthiness and str() both raise."""

    def __bool__(self):
        raise RuntimeError("bool")

    def __str__(self):
        raise RuntimeError("str")


class _Base(unittest.TestCase):
    def setUp(self):
        ward_events.reset()

    def tearDown(self):
        ward_events.reset()


class NarrowReadDoesNotEvictWiderTests(_Base):
    def test_narrow_window_read_keeps_entries_for_a_wider_reader(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=1000.0)
        ward_events.record_ward("ally", "top", "control", ts=1040.0)
        narrow = ward_events.recent_wards(now_s=1045.0, window_s=10.0)
        self.assertEqual([e["lane"] for e in narrow], ["top"])
        wide = ward_events.recent_wards(now_s=1045.0, window_s=90.0)
        self.assertEqual([e["lane"] for e in wide], ["mid", "top"])

    def test_narrow_counts_then_wide_uncovered(self):
        ward_events.record_ward("ally", "jg", "yellow", ts=1000.0)
        ward_events.counts_by_lane(now_s=1050.0, window_s=5.0)
        self.assertNotIn(
            "jg",
            ward_events.lanes_uncovered("ally", now_s=1050.0, window_s=60.0),
        )

    def test_retention_horizon_still_evicts(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=1000.0)
        ward_events.recent_wards(
            now_s=1000.0 + ward_events._RETENTION_S + 1.0, window_s=90.0)
        self.assertEqual(ward_events.buffer_size(), 0)

    def test_retention_covers_a_window_wider_than_retention(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=1000.0)
        wide = ward_events._RETENTION_S * 2
        snap = ward_events.recent_wards(now_s=1000.0 + wide - 1.0,
                                        window_s=wide)
        self.assertEqual(len(snap), 1)


class NonFiniteTsDroppedTests(_Base):
    def test_nan_ts_dropped(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=NAN)
        self.assertEqual(ward_events.buffer_size(), 0)

    def test_inf_ts_dropped(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=INF)
        ward_events.record_ward("ally", "mid", "yellow", ts=-INF)
        self.assertEqual(ward_events.buffer_size(), 0)

    def test_bool_ts_dropped(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=True)
        self.assertEqual(ward_events.buffer_size(), 0)

    def test_nan_string_ts_dropped(self):
        ward_events.record_ward("ally", "mid", "yellow", ts="nan")
        self.assertEqual(ward_events.buffer_size(), 0)


class PerEntryWindowFilterTests(_Base):
    def test_out_of_order_old_entry_not_reported(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=1000.0)
        ward_events.record_ward("ally", "top", "yellow", ts=100.0)
        snap = ward_events.recent_wards(now_s=1010.0, window_s=90.0)
        self.assertEqual([e["lane"] for e in snap], ["mid"])
        self.assertNotIn(
            "mid",
            ward_events.lanes_uncovered("ally", now_s=1010.0, window_s=60.0),
        )
        self.assertIn(
            "top",
            ward_events.lanes_uncovered("ally", now_s=1010.0, window_s=60.0),
        )

    def test_out_of_order_entry_past_retention_is_evicted(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=1000.0)
        ward_events.record_ward("ally", "top", "yellow", ts=100.0)
        ward_events.recent_wards(now_s=1010.0, window_s=90.0)
        self.assertEqual(ward_events.buffer_size(), 1)

    def test_entry_after_now_not_reported_but_kept(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=500.0)
        self.assertEqual(
            ward_events.recent_wards(now_s=100.0, window_s=90.0), [])
        self.assertEqual(ward_events.buffer_size(), 1)
        self.assertEqual(
            len(ward_events.recent_wards(now_s=500.0, window_s=90.0)), 1)


class NonFiniteReadArgsTests(_Base):
    def setUp(self):
        super().setUp()
        ward_events.record_ward("ally", "mid", "yellow", ts=1000.0)
        ward_events.record_ward("ally", "top", "yellow", ts=10.0)

    def test_nan_now_returns_empty_and_keeps_buffer(self):
        self.assertEqual(ward_events.recent_wards(now_s=NAN), [])
        self.assertEqual(ward_events.buffer_size(), 2)

    def test_inf_now_returns_empty_and_keeps_buffer(self):
        self.assertEqual(ward_events.recent_wards(now_s=INF), [])
        self.assertEqual(ward_events.buffer_size(), 2)

    def test_bool_now_returns_empty(self):
        self.assertEqual(ward_events.recent_wards(now_s=True), [])
        self.assertEqual(ward_events.buffer_size(), 2)

    def test_nan_window_returns_empty_and_keeps_buffer(self):
        self.assertEqual(
            ward_events.recent_wards(now_s=1000.0, window_s=NAN), [])
        self.assertEqual(ward_events.buffer_size(), 2)

    def test_bool_window_returns_empty(self):
        self.assertEqual(
            ward_events.recent_wards(now_s=1000.0, window_s=True), [])

    def test_inf_window_returns_everything_up_to_now(self):
        snap = ward_events.recent_wards(now_s=1000.0, window_s=INF)
        self.assertEqual(sorted(e["ts"] for e in snap), [10.0, 1000.0])
        self.assertEqual(ward_events.buffer_size(), 2)

    def test_nan_now_counts_are_all_zero(self):
        counts = ward_events.counts_by_lane(now_s=NAN)
        self.assertEqual(sum(counts["ally"].values()), 0)


class LaneFromPositionTests(unittest.TestCase):
    def test_nan_is_unknown(self):
        self.assertEqual(ward_events.lane_from_position(NAN, 5000), "unknown")
        self.assertEqual(ward_events.lane_from_position(5000, NAN), "unknown")
        self.assertEqual(ward_events.lane_from_position("nan", "nan"),
                         "unknown")

    def test_inf_is_unknown(self):
        self.assertEqual(ward_events.lane_from_position(INF, 5000), "unknown")

    def test_bool_is_unknown(self):
        self.assertEqual(ward_events.lane_from_position(True, False),
                         "unknown")

    def test_numeric_string_still_parses(self):
        self.assertEqual(ward_events.lane_from_position("2000", "12000"),
                         "top")


class HostileInputNeverRaisesTests(_Base):
    def test_hostile_side_dropped(self):
        ward_events.record_ward(_Hostile(), "mid", "yellow", ts=100.0)
        self.assertEqual(ward_events.buffer_size(), 0)

    def test_hostile_ward_type_dropped(self):
        ward_events.record_ward("ally", "mid", _Hostile(), ts=100.0)
        self.assertEqual(ward_events.buffer_size(), 0)

    def test_hostile_lane_stored_as_unknown(self):
        ward_events.record_ward("ally", _Hostile(), "yellow", ts=100.0)
        snap = ward_events.recent_wards(now_s=100.0)
        self.assertEqual([e["lane"] for e in snap], ["unknown"])

    def test_non_str_side_dropped(self):
        ward_events.record_ward(b"ally", "mid", "yellow", ts=100.0)
        ward_events.record_ward(["ally"], "mid", "yellow", ts=100.0)
        self.assertEqual(ward_events.buffer_size(), 0)

    def test_hostile_side_uncovered_is_all_lanes(self):
        self.assertEqual(
            ward_events.lanes_uncovered(_Hostile(), now_s=100.0),
            list(ward_events.NAMED_LANES),
        )

    def test_record_from_position_hostile_side_never_raises(self):
        lane = ward_events.record_from_position(
            _Hostile(), 2000, 12000, "yellow", ts=100.0)
        self.assertEqual(lane, "top")
        self.assertEqual(ward_events.buffer_size(), 0)


if __name__ == "__main__":
    unittest.main()

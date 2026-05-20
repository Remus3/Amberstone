"""Tests for core/ward_events.py - the rolling-window ward placement
buffer that backs the UX-3 'Ward-Coverage Heat Strip' panel.

Covers:
  * record_ward shape + sanity-check drops (unknown side / type / lane)
  * Time-window pruning (entries past cutoff drop on read)
  * Lane inference from (x, z) game-unit coords
  * record_from_position end-to-end (infer + record + return resolved)
  * Side-split aggregation
  * counts_by_lane has every lane seeded (no null guards needed
    frontend-side)
  * lanes_uncovered detects all-four-empty + the seed-and-cover case
  * Default window (90s) vs uncovered window (60s) semantics
  * Buffer cap defensive behaviour
  * Reset clears state
  * Buffer is thread-safe (parallel record_ward batches preserve count)
"""
from __future__ import annotations

import threading
import time
import unittest

from core import ward_events


class WardEventsBase(unittest.TestCase):
    def setUp(self):
        # Each test starts on an empty buffer so window-prune assertions
        # are deterministic.
        ward_events.reset()


class RecordTests(WardEventsBase):
    def test_record_basic_round_trip(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=100.0)
        snap = ward_events.recent_wards(now_s=100.0, window_s=90.0)
        self.assertEqual(len(snap), 1)
        ev = snap[0]
        self.assertEqual(ev["side"], "ally")
        self.assertEqual(ev["lane"], "mid")
        self.assertEqual(ev["ward_type"], "yellow")
        self.assertEqual(ev["ts"], 100.0)

    def test_unknown_side_dropped(self):
        ward_events.record_ward("spectator", "mid", "yellow", ts=100.0)
        self.assertEqual(ward_events.buffer_size(), 0)

    def test_unknown_ward_type_dropped(self):
        ward_events.record_ward("ally", "mid", "lasersight", ts=100.0)
        self.assertEqual(ward_events.buffer_size(), 0)

    def test_unknown_lane_kept_as_unknown(self):
        # Unknown LANE is normalised to 'unknown' rather than dropped -
        # OCR producers that can't infer lane should still get to
        # record the placement.
        ward_events.record_ward("ally", "alley", "control", ts=100.0)
        snap = ward_events.recent_wards(now_s=100.0, window_s=90.0)
        self.assertEqual(len(snap), 1)
        self.assertEqual(snap[0]["lane"], "unknown")

    def test_record_normalises_case(self):
        ward_events.record_ward("ALLY", "MID", "Yellow", ts=100.0)
        snap = ward_events.recent_wards(now_s=100.0, window_s=90.0)
        self.assertEqual(snap[0]["side"], "ally")
        self.assertEqual(snap[0]["lane"], "mid")
        self.assertEqual(snap[0]["ward_type"], "yellow")

    def test_record_defaults_ts_to_now(self):
        before = time.time()
        ward_events.record_ward("ally", "mid", "yellow")
        after = time.time()
        snap = ward_events.recent_wards(window_s=90.0)
        self.assertEqual(len(snap), 1)
        self.assertTrue(before <= snap[0]["ts"] <= after)


class WindowPruneTests(WardEventsBase):
    def test_old_entries_evicted_on_read(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=10.0)
        ward_events.record_ward("ally", "top", "control", ts=50.0)
        # At ts=110 the first event is 100s old (outside default 90s).
        snap = ward_events.recent_wards(now_s=110.0, window_s=90.0)
        # Only the second event should remain.
        self.assertEqual(len(snap), 1)
        self.assertEqual(snap[0]["lane"], "top")
        # Lazy GC also drops it from the underlying buffer.
        self.assertEqual(ward_events.buffer_size(), 1)

    def test_window_zero_returns_empty(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=100.0)
        self.assertEqual(ward_events.recent_wards(now_s=100.0, window_s=0.0), [])

    def test_window_negative_returns_empty(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=100.0)
        self.assertEqual(
            ward_events.recent_wards(now_s=100.0, window_s=-5.0), [])

    def test_recent_wards_preserves_insertion_order(self):
        ward_events.record_ward("ally",  "top", "yellow", ts=10.0)
        ward_events.record_ward("enemy", "mid", "control", ts=20.0)
        ward_events.record_ward("ally",  "bot", "blue_trinket", ts=30.0)
        snap = ward_events.recent_wards(now_s=35.0, window_s=90.0)
        self.assertEqual([e["lane"] for e in snap], ["top", "mid", "bot"])


class LaneInferenceTests(WardEventsBase):
    def test_top_lane_top_left_quadrant(self):
        # x low, z high -> top
        self.assertEqual(ward_events.lane_from_position(2000, 12000), "top")

    def test_bot_lane_bottom_right_quadrant(self):
        # x high, z low -> bot
        self.assertEqual(ward_events.lane_from_position(12000, 2000), "bot")

    def test_mid_lane_on_diagonal(self):
        self.assertEqual(ward_events.lane_from_position(7000, 7400), "mid")

    def test_jungle_quadrant(self):
        # 6000, 9500 is in the blue_top_jungle area - neither lane nor
        # diagonal - should be 'jg'.
        self.assertEqual(ward_events.lane_from_position(6000, 9500), "jg")

    def test_out_of_bounds_unknown(self):
        self.assertEqual(ward_events.lane_from_position(-100, 5000), "unknown")
        self.assertEqual(ward_events.lane_from_position(5000, 99999), "unknown")

    def test_non_numeric_unknown(self):
        self.assertEqual(ward_events.lane_from_position("NONE", 0), "unknown")
        self.assertEqual(ward_events.lane_from_position(None, None), "unknown")

    def test_record_from_position_round_trip(self):
        resolved = ward_events.record_from_position(
            "ally", 2000, 12000, "control", ts=100.0)
        self.assertEqual(resolved, "top")
        snap = ward_events.recent_wards(now_s=100.0, window_s=90.0)
        self.assertEqual(len(snap), 1)
        self.assertEqual(snap[0]["lane"], "top")
        self.assertEqual(snap[0]["ward_type"], "control")


class CountsByLaneTests(WardEventsBase):
    def test_counts_seeds_every_lane(self):
        # Empty buffer: every lane bucket is 0 on both sides.
        counts = ward_events.counts_by_lane(now_s=100.0, window_s=90.0)
        self.assertEqual(set(counts.keys()), {"ally", "enemy"})
        for side in ("ally", "enemy"):
            for lane in ("top", "mid", "bot", "jg", "unknown"):
                self.assertEqual(counts[side][lane], 0)

    def test_counts_split_by_side(self):
        ward_events.record_ward("ally",  "mid", "yellow", ts=100.0)
        ward_events.record_ward("ally",  "mid", "yellow", ts=110.0)
        ward_events.record_ward("enemy", "mid", "yellow", ts=120.0)
        counts = ward_events.counts_by_lane(now_s=130.0, window_s=90.0)
        self.assertEqual(counts["ally"]["mid"], 2)
        self.assertEqual(counts["enemy"]["mid"], 1)

    def test_counts_respect_window(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=10.0)
        ward_events.record_ward("ally", "mid", "yellow", ts=90.0)
        # At ts=120 with window=60 only the second event remains.
        counts = ward_events.counts_by_lane(now_s=120.0, window_s=60.0)
        self.assertEqual(counts["ally"]["mid"], 1)


class LanesUncoveredTests(WardEventsBase):
    def test_empty_buffer_all_lanes_uncovered(self):
        self.assertEqual(
            ward_events.lanes_uncovered("ally", now_s=100.0, window_s=60.0),
            ["top", "mid", "bot", "jg"],
        )

    def test_full_coverage_returns_empty(self):
        for lane in ("top", "mid", "bot", "jg"):
            ward_events.record_ward("ally", lane, "yellow", ts=100.0)
        self.assertEqual(
            ward_events.lanes_uncovered("ally", now_s=100.0, window_s=60.0),
            [],
        )

    def test_partial_coverage_lists_gaps(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=100.0)
        ward_events.record_ward("ally", "top", "control", ts=110.0)
        self.assertEqual(
            ward_events.lanes_uncovered("ally", now_s=110.0, window_s=60.0),
            ["bot", "jg"],
        )

    def test_uncovered_ignores_other_side(self):
        # An enemy ward in mid does NOT cover the ally's mid lane.
        ward_events.record_ward("enemy", "mid", "yellow", ts=100.0)
        self.assertEqual(
            ward_events.lanes_uncovered("ally", now_s=100.0, window_s=60.0),
            ["top", "mid", "bot", "jg"],
        )

    def test_uncovered_ignores_unknown(self):
        ward_events.record_ward("ally", "unknown", "yellow", ts=100.0)
        # 'unknown' is not a NAMED lane - it doesn't cover anything,
        # but it also isn't listed as uncovered.
        result = ward_events.lanes_uncovered(
            "ally", now_s=100.0, window_s=60.0)
        self.assertNotIn("unknown", result)
        self.assertEqual(result, ["top", "mid", "bot", "jg"])

    def test_uncovered_respects_window(self):
        # Old ward covers mid 120s ago - default 60s window says mid
        # is uncovered NOW.
        ward_events.record_ward("ally", "mid", "yellow", ts=10.0)
        self.assertIn(
            "mid",
            ward_events.lanes_uncovered("ally", now_s=130.0, window_s=60.0),
        )

    def test_invalid_side_returns_all_lanes(self):
        # Defensive: caller sends garbage side -> treat as fully uncovered
        # rather than raising.
        self.assertEqual(
            ward_events.lanes_uncovered("badside", now_s=100.0),
            ["top", "mid", "bot", "jg"],
        )


class BufferCapTests(WardEventsBase):
    def test_buffer_cap_drops_oldest(self):
        # Defensive cap is 256; insert 300 to confirm the oldest fall off.
        for i in range(300):
            ward_events.record_ward("ally", "mid", "yellow", ts=float(i))
        self.assertLessEqual(ward_events.buffer_size(), 256)
        snap = ward_events.recent_wards(
            now_s=10_000.0, window_s=10_000.0)
        # The first ts in the snap should be (300 - 256) = 44 or higher.
        self.assertGreaterEqual(snap[0]["ts"], 44.0)


class ResetTests(WardEventsBase):
    def test_reset_empties_buffer(self):
        ward_events.record_ward("ally", "mid", "yellow", ts=100.0)
        ward_events.record_ward("enemy", "top", "control", ts=101.0)
        self.assertEqual(ward_events.buffer_size(), 2)
        ward_events.reset()
        self.assertEqual(ward_events.buffer_size(), 0)


class ThreadSafetyTests(WardEventsBase):
    def test_concurrent_record_preserves_count(self):
        # 8 threads x 50 records = 400 attempts. Cap is 256 so we should
        # land at EXACTLY 256.
        def burst():
            for i in range(50):
                ward_events.record_ward("ally", "mid", "yellow",
                                        ts=float(i))
        threads = [threading.Thread(target=burst) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertLessEqual(ward_events.buffer_size(), 256)
        # And there's nothing about the lock that could LOSE entries
        # below the cap - we know 8*50=400 > 256, so we must hit cap.
        self.assertEqual(ward_events.buffer_size(), 256)


if __name__ == "__main__":
    unittest.main()

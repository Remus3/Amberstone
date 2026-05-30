"""Tests for agents/daemon_slayer/spike_markers.py - live power-spike
markers (competitor lift #4, docs/COMPETITOR_LIFT_2026-05-30.md).

The module is a read-only classifier over RC's own DS curves: given the
operator's live champion + level + finished-item count, it returns which
discrete spikes (level 6/11/16 + item-completion 1/2/3) are CROSSED and
which single one is NEXT. NO ENGINE math, NO schema lift.

Covers:
  * LevelThresholdTests - the 6/11/16 (+ optional 9/13/18) breakpoints.
  * CrossedTests - crossed = at-or-past for level + item families.
  * NextTests - exactly one "next" across both families; the nearest gap.
  * ItemCountTests - item-completion markers track item_count_done +
    the len(item_ids) proxy default.
  * FailSoftTests - blank champion yields empty result; unknown champion
    still returns markers (dps_at fail-softs to absent).
  * AsciiHygieneTests - no em-dashes / smart quotes in module + test file.

Marker math tests pass annotate_dps=False to avoid the DS snapshot load
(the dps_at annotation is exercised separately + fail-softs).
"""
from __future__ import annotations

import pathlib
import unittest

from agents.daemon_slayer.spike_markers import (
    SpikeMarker,
    SpikeMarkersResult,
    compute_spike_markers,
)


def _by(markers, kind):
    return [m for m in markers if m.kind == kind]


def _thresholds(markers, kind):
    return [m.threshold for m in markers if m.kind == kind]


def _next(result):
    nxt = [m for m in result.markers if m.next]
    return nxt


class LevelThresholdTests(unittest.TestCase):
    def test_default_level_thresholds_are_6_11_16(self) -> None:
        r = compute_spike_markers("Jinx", 1, annotate_dps=False)
        self.assertEqual(_thresholds(r.markers, "level"), [6, 11, 16])

    def test_minor_adds_9_13_18(self) -> None:
        r = compute_spike_markers("Jinx", 1, include_minor=True,
                                  annotate_dps=False)
        self.assertEqual(_thresholds(r.markers, "level"),
                         [6, 9, 11, 13, 16, 18])

    def test_level_labels_present(self) -> None:
        r = compute_spike_markers("Jinx", 1, annotate_dps=False)
        labels = {m.threshold: m.label for m in _by(r.markers, "level")}
        self.assertEqual(labels[6], "R unlock")
        self.assertEqual(labels[11], "R rank 2")
        self.assertEqual(labels[16], "R rank 3")

    def test_item_thresholds_are_1_2_3(self) -> None:
        r = compute_spike_markers("Jinx", 1, annotate_dps=False)
        self.assertEqual(_thresholds(r.markers, "item"), [1, 2, 3])

    def test_markers_ordered_level_then_item(self) -> None:
        r = compute_spike_markers("Jinx", 1, annotate_dps=False)
        kinds = [m.kind for m in r.markers]
        # All level markers come before all item markers.
        self.assertEqual(kinds, ["level"] * 3 + ["item"] * 3)

    def test_result_is_dataclasses(self) -> None:
        r = compute_spike_markers("Jinx", 1, annotate_dps=False)
        self.assertIsInstance(r, SpikeMarkersResult)
        self.assertTrue(all(isinstance(m, SpikeMarker) for m in r.markers))


class CrossedTests(unittest.TestCase):
    def test_level_8_crosses_6_not_11(self) -> None:
        r = compute_spike_markers("Aatrox", 8, annotate_dps=False)
        lv = {m.threshold: m.crossed for m in _by(r.markers, "level")}
        self.assertTrue(lv[6])      # level 8 >= 6 crossed
        self.assertFalse(lv[11])    # level 8 < 11 not crossed
        self.assertFalse(lv[16])

    def test_level_exactly_at_threshold_is_crossed(self) -> None:
        r = compute_spike_markers("Aatrox", 11, annotate_dps=False)
        lv = {m.threshold: m.crossed for m in _by(r.markers, "level")}
        self.assertTrue(lv[6])
        self.assertTrue(lv[11])     # AT 11 == crossed (at-or-past)
        self.assertFalse(lv[16])

    def test_level_18_crosses_all_level(self) -> None:
        r = compute_spike_markers("Aatrox", 18, annotate_dps=False)
        self.assertTrue(all(m.crossed for m in _by(r.markers, "level")))

    def test_level_1_crosses_no_level(self) -> None:
        r = compute_spike_markers("Aatrox", 1, annotate_dps=False)
        self.assertFalse(any(m.crossed for m in _by(r.markers, "level")))

    def test_level_clamped_above_18(self) -> None:
        r = compute_spike_markers("Aatrox", 25, annotate_dps=False)
        self.assertEqual(r.level, 18)
        self.assertTrue(all(m.crossed for m in _by(r.markers, "level")))

    def test_level_clamped_below_1(self) -> None:
        r = compute_spike_markers("Aatrox", 0, annotate_dps=False)
        self.assertEqual(r.level, 1)


class NextTests(unittest.TestCase):
    def test_exactly_one_next(self) -> None:
        r = compute_spike_markers("Jinx", 8, item_count_done=1,
                                  annotate_dps=False)
        self.assertEqual(len(_next(r)), 1)

    def test_next_marker_field_matches(self) -> None:
        r = compute_spike_markers("Jinx", 8, item_count_done=1,
                                  annotate_dps=False)
        self.assertIsNotNone(r.next_marker)
        flagged = _next(r)[0]
        self.assertEqual(r.next_marker.threshold, flagged.threshold)
        self.assertEqual(r.next_marker.kind, flagged.kind)

    def test_at_level_8_one_item_next_is_two_items(self) -> None:
        # gaps: level 11 -> 3, level 16 -> 8; item 2 -> 1, item 3 -> 2.
        # Nearest gap = item threshold 2 (gap 1). So next is the 2-item
        # spike, NOT the level-11 spike (gap 3).
        r = compute_spike_markers("Jinx", 8, item_count_done=1,
                                  annotate_dps=False)
        nxt = r.next_marker
        self.assertEqual(nxt.kind, "item")
        self.assertEqual(nxt.threshold, 2)

    def test_level_tie_breaks_before_item(self) -> None:
        # level 5, 0 items: level 6 gap 1; item 1 gap 1. Tie on gap 1 ->
        # level wins the tiebreak (ult/scaling is the headline spike).
        r = compute_spike_markers("Jinx", 5, item_count_done=0,
                                  annotate_dps=False)
        nxt = r.next_marker
        self.assertEqual(nxt.kind, "level")
        self.assertEqual(nxt.threshold, 6)

    def test_next_is_a_level_spike_when_nearest(self) -> None:
        # level 10, 3 items (all item spikes crossed): only level 11/16
        # remain. Nearest = level 11 (gap 1).
        r = compute_spike_markers("Jinx", 10, item_count_done=3,
                                  annotate_dps=False)
        nxt = r.next_marker
        self.assertEqual(nxt.kind, "level")
        self.assertEqual(nxt.threshold, 11)

    def test_no_next_when_all_crossed(self) -> None:
        r = compute_spike_markers("Jinx", 18, item_count_done=3,
                                  annotate_dps=False)
        self.assertIsNone(r.next_marker)
        self.assertEqual(len(_next(r)), 0)
        self.assertTrue(all(m.crossed for m in r.markers))

    def test_next_not_crossed(self) -> None:
        r = compute_spike_markers("Jinx", 8, item_count_done=1,
                                  annotate_dps=False)
        self.assertFalse(r.next_marker.crossed)


class ItemCountTests(unittest.TestCase):
    def test_item_count_done_drives_crossed(self) -> None:
        r = compute_spike_markers("Jinx", 8, item_count_done=2,
                                  annotate_dps=False)
        it = {m.threshold: m.crossed for m in _by(r.markers, "item")}
        self.assertTrue(it[1])
        self.assertTrue(it[2])
        self.assertFalse(it[3])

    def test_zero_items_crosses_none(self) -> None:
        r = compute_spike_markers("Jinx", 8, item_count_done=0,
                                  annotate_dps=False)
        self.assertFalse(any(m.crossed for m in _by(r.markers, "item")))

    def test_three_items_crosses_all(self) -> None:
        r = compute_spike_markers("Jinx", 8, item_count_done=3,
                                  annotate_dps=False)
        self.assertTrue(all(m.crossed for m in _by(r.markers, "item")))

    def test_item_count_proxy_from_item_ids(self) -> None:
        # No explicit item_count_done -> defaults to min(len(items), 3).
        r = compute_spike_markers("Jinx", 8, item_ids=["3094", "3031"],
                                  annotate_dps=False)
        self.assertEqual(r.item_count_done, 2)
        it = {m.threshold: m.crossed for m in _by(r.markers, "item")}
        self.assertTrue(it[1])
        self.assertTrue(it[2])
        self.assertFalse(it[3])

    def test_item_id_proxy_capped_at_3(self) -> None:
        # 6 owned ids but only 3 item thresholds.
        r = compute_spike_markers(
            "Jinx", 8,
            item_ids=["3094", "3031", "3072", "3036", "3046", "3026"],
            annotate_dps=False,
        )
        self.assertEqual(r.item_count_done, 3)

    def test_explicit_count_overrides_proxy(self) -> None:
        r = compute_spike_markers("Jinx", 8, item_ids=["3094", "3031"],
                                  item_count_done=1, annotate_dps=False)
        self.assertEqual(r.item_count_done, 1)

    def test_negative_count_clamps_to_zero(self) -> None:
        r = compute_spike_markers("Jinx", 8, item_count_done=-2,
                                  annotate_dps=False)
        self.assertEqual(r.item_count_done, 0)


class FailSoftTests(unittest.TestCase):
    def test_blank_champion_empty_result(self) -> None:
        r = compute_spike_markers("", 8, annotate_dps=False)
        self.assertEqual(r.markers, tuple())
        self.assertIsNone(r.next_marker)

    def test_whitespace_champion_empty_result(self) -> None:
        r = compute_spike_markers("   ", 8, annotate_dps=False)
        self.assertEqual(r.markers, tuple())

    def test_none_champion_empty_result(self) -> None:
        r = compute_spike_markers(None, 8, annotate_dps=False)  # type: ignore[arg-type]
        self.assertEqual(r.markers, tuple())

    def test_unknown_champion_still_returns_markers(self) -> None:
        # An unknown champion is NOT blank - the level/item thresholds are
        # champion-invariant facts. The dps_at annotation fail-softs to
        # absent (annotate_dps=True hits the DS curve which fails on an
        # unknown slug + returns {}).
        r = compute_spike_markers("NotAChampion", 8, annotate_dps=True)
        self.assertEqual(len(r.markers), 6)
        self.assertEqual(_thresholds(r.markers, "level"), [6, 11, 16])
        # dps_at absent for every level marker (curve failed silently).
        self.assertTrue(all(m.dps_at is None for m in _by(r.markers, "level")))

    def test_to_dict_shape(self) -> None:
        r = compute_spike_markers("Jinx", 8, item_count_done=1,
                                  annotate_dps=False)
        d = r.to_dict()
        self.assertEqual(d["champion"], "Jinx")
        self.assertEqual(d["level"], 8)
        self.assertEqual(d["item_count_done"], 1)
        self.assertEqual(len(d["markers"]), 6)
        self.assertIsNotNone(d["next"])
        m0 = d["markers"][0]
        self.assertIn("kind", m0)
        self.assertIn("threshold", m0)
        self.assertIn("label", m0)
        self.assertIn("crossed", m0)
        self.assertIn("next", m0)

    def test_item_marker_has_no_dps_at_key(self) -> None:
        r = compute_spike_markers("Jinx", 8, annotate_dps=False)
        item_dicts = [m.to_dict() for m in _by(r.markers, "item")]
        self.assertTrue(all("dps_at" not in d for d in item_dicts))


class DpsAnnotationTests(unittest.TestCase):
    def test_annotate_false_no_dps(self) -> None:
        r = compute_spike_markers("Jinx", 8, annotate_dps=False)
        self.assertTrue(all(m.dps_at is None for m in _by(r.markers, "level")))

    def test_annotate_dps_failsoft_does_not_raise(self) -> None:
        # Even if the DS snapshot can't resolve, the call must return.
        r = compute_spike_markers("NotAChampion", 8, annotate_dps=True)
        self.assertIsInstance(r, SpikeMarkersResult)


class AsciiHygieneTests(unittest.TestCase):
    _BAD = (chr(0x2013), chr(0x2014), chr(0x2018), chr(0x2019),
            chr(0x201C), chr(0x201D))

    def _scan(self, path: pathlib.Path) -> list[int]:
        text = path.read_text(encoding="utf-8")
        return [i for i, c in enumerate(text) if c in self._BAD]

    def test_module_is_ascii(self) -> None:
        import agents.daemon_slayer.spike_markers as mod
        self.assertEqual(self._scan(pathlib.Path(mod.__file__)), [])

    def test_this_test_file_is_ascii(self) -> None:
        self.assertEqual(self._scan(pathlib.Path(__file__)), [])


if __name__ == "__main__":
    unittest.main()

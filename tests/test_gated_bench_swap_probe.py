"""Tests for tools/gated_bench_swap_probe.py - the G3-01 bench-swap latency
probe. Pure-function coverage of the log parser and the predicate; the relay
watch() path is fail-soft and is exercised live by the lane, not mocked here.
"""
from __future__ import annotations

import time
import unittest

from tools import gated_bench_swap_probe as p


def _cap(ts, champ, phase="ChampSelect"):
    return {"ts": ts, "phase": phase, "my_champion": champ, "bench": [], "queue_id": 2400}


def _natural(start, n, champ, gap=1.05):
    return [_cap(start + i * gap, champ) for i in range(n)]


class TestParse(unittest.TestCase):
    def test_parses_ok_failed_and_exc_lines_only_for_bench_swap(self):
        text = "\n".join([
            "2026-10-25 03:00:00,250 INFO   [cmd] bench_swap -> {'ok': True, 'err': None}",
            "2026-10-25 03:00:05,000 INFO   [cmd] reroll -> {'ok': True, 'err': None}",
            "2026-10-25 03:00:06,500 INFO   [cmd] bench_swap -> {'ok': False, 'err': 'HTTP 400'}",
            "2026-10-25 03:00:07,125 WARNING   [cmd-exc] bench_swap -> {'ok': False, 'err': 'X'}",
            "2026-10-25 03:00:08,000 ERROR   [cmd-poll err] refused",
        ])
        ev = p.parse_bench_swap_events(text)
        self.assertEqual([e["ok"] for e in ev], [True, False, False])
        base = time.mktime(time.strptime("2026-10-25 03:00:00", "%Y-%m-%d %H:%M:%S"))
        self.assertAlmostEqual(ev[0]["t"], base + 0.25, places=3)
        self.assertAlmostEqual(ev[2]["t"] - ev[0]["t"], 6.875, places=3)

    def test_crlf_and_empty(self):
        self.assertEqual(p.parse_bench_swap_events(""), [])
        ev = p.parse_bench_swap_events(
            "2026-10-25 03:00:00,000 INFO   [cmd] bench_swap -> {'ok': True}\r\n")
        self.assertEqual(len(ev), 1)


class TestCaptureRows(unittest.TestCase):
    def test_capture_row_and_dedupe(self):
        d = {"ts": 5.0, "phase": "ChampSelect",
             "champ_select": {"my_champion": 67, "bench": [22], "queue_id": 2400}}
        r = p.capture_row(d)
        self.assertEqual((r["my_champion"], r["bench"], r["queue_id"]), (67, [22], 2400))
        self.assertIsNone(p.capture_row({"phase": "None"}))
        caps = p.dedupe_captures([r, dict(r), None, p.capture_row({"ts": 4.0})])
        self.assertEqual([c["ts"] for c in caps], [4.0, 5.0])
        self.assertIsNone(caps[0]["my_champion"])


DENSE = [90.0 + i * 0.05 for i in range(400)]     # 90.0 .. 109.95


class TestPredicate(unittest.TestCase):
    T = 100.0

    def _ev(self, caps, ok=True, polls=DENSE):
        return p.evaluate_swap(caps, {"t": self.T, "ok": ok}, polls)

    def test_pass_wake_capture(self):
        caps = _natural(self.T - 9.0, 9, 67)            # last natural at 99.4
        caps.append(_cap(self.T + 0.08, 22))            # gap 0.68 < 0.95, L 0.08
        r = self._ev(caps)
        self.assertEqual(r["verdict"], "PASS", r)
        self.assertTrue(r["wake"])
        self.assertEqual(r["champion_after"], 22)
        self.assertEqual(r["bench_after"], [])

    def test_fail_rides_natural_tick_only_with_dense_polls(self):
        caps = _natural(self.T - 9.0, 9, 67)            # last natural at 99.4
        caps.append(_cap(99.4 + 1.05, 22))              # natural gap, L 0.45 > 0.35
        self.assertEqual(self._ev(caps)["verdict"], "FAIL")
        r = self._ev(caps, polls=None)
        self.assertEqual(r["verdict"], "NO_RESULT", r)
        self.assertIn("sparse", r["reason"])

    def test_coincidence_is_no_result(self):
        caps = _natural(self.T - 9.4, 9, 67)            # last natural at 99.0
        caps.append(_cap(99.0 + 1.05, 22))              # natural gap, L 0.05
        r = self._ev(caps)
        self.assertEqual(r["verdict"], "NO_RESULT", r)
        self.assertIn("coincidence", r["reason"])

    def test_missed_baseline_polls_cannot_fake_a_wake(self):
        # gaps 2.1 x3 (missed polls) then 1.05 x3; a relative test against the
        # inflated median would have called the natural 1.03 gap off-cadence.
        # The old relative test put the median at 1.575 and the margin at 1.375.
        ts = [90.0, 92.1, 94.2, 96.3, 97.35, 98.4, 99.45]
        caps = [_cap(t, 67) for t in ts]
        caps.append(_cap(99.45 + 1.03, 22))             # natural, L 0.48
        r = self._ev(caps)
        self.assertNotEqual(r["verdict"], "PASS", r)
        self.assertFalse(r["wake"])
        self.assertAlmostEqual(r["g_nat"], 1.05, places=3)

    def test_second_writer_in_baseline_is_no_result(self):
        caps = _natural(self.T - 9.0, 9, 67)
        caps.insert(5, _cap(caps[4]["ts"] + 0.4, 67))   # an off-cadence capture
        caps.append(_cap(self.T + 0.08, 22))
        r = self._ev(caps)
        self.assertEqual(r["verdict"], "NO_RESULT", r)
        self.assertIn("second writer", r["reason"])

    def test_wake_before_lcu_applied_is_no_result(self):
        caps = _natural(self.T - 9.0, 9, 67)            # last natural at 99.4
        caps.append(_cap(self.T + 0.05, 67))            # wake, old champ still
        caps.append(_cap(self.T + 0.05 + 1.05, 22))     # next natural shows it
        r = self._ev(caps)
        self.assertEqual(r["verdict"], "NO_RESULT", r)
        self.assertIn("before the LCU", r["reason"])

    def test_unchanged_champion(self):
        caps = _natural(self.T - 9.0, 14, 67)           # runs to ~104.65
        self.assertEqual(self._ev(caps)["verdict"], "FAIL")
        self.assertEqual(self._ev(caps, polls=None)["verdict"], "NO_RESULT")
        woke = sorted(caps + [_cap(self.T + 0.05, 67)], key=lambda c: c["ts"])
        r = self._ev(woke)
        self.assertEqual(r["verdict"], "NO_RESULT", r)
        self.assertIn("LCU side", r["reason"])

    def test_wake_boundary_is_pinned_at_095(self):
        base = _natural(self.T - 9.0, 9, 67)            # last natural at 99.4
        r = self._ev(base + [_cap(99.4 + 0.90, 22)])    # L 0.30, gap 0.90
        self.assertEqual(r["verdict"], "PASS", r)
        r = self._ev(base + [_cap(99.4 + 0.97, 22)])    # L 0.37, gap 0.97
        self.assertFalse(r["wake"])
        self.assertEqual(r["verdict"], "FAIL", r)

    def test_hidden_wake_is_no_result_not_fail(self):
        # Click mid-capture: the capture at 100.03 shows the old pick, the woken
        # capture right after it was never polled, the next natural one shows it.
        caps = _natural(self.T - 9.42, 9, 67)           # last natural at 98.98
        caps.append(_cap(self.T + 0.03, 67))            # natural, old pick, L 0.03
        caps.append(_cap(self.T + 0.06 + 1.05, 22))     # gap 1.08 to the seen one
        r = self._ev(caps)
        self.assertEqual(r["verdict"], "NO_RESULT", r)
        self.assertIn("hidden", r["reason"])

    def test_watch_too_short_is_no_result(self):
        caps = _natural(self.T - 9.0, 10, 67)           # ends at 100.45
        self.assertEqual(self._ev(caps)["verdict"], "NO_RESULT")

    def test_failed_post_and_no_baseline_are_no_result(self):
        caps = _natural(self.T - 9.0, 9, 67) + [_cap(self.T + 0.08, 22)]
        self.assertEqual(self._ev(caps, ok=False)["verdict"], "NO_RESULT")
        short = _natural(self.T - 2.0, 2, 67) + [_cap(self.T + 0.08, 22)]
        r = self._ev(short)
        self.assertEqual(r["verdict"], "NO_RESULT")
        self.assertIn("baseline", r["reason"])

    def test_zero_champion_is_not_the_new_pick(self):
        caps = _natural(self.T - 9.0, 9, 67)
        caps.append(_cap(self.T + 0.05, 0))             # transient empty pick
        caps.append(_cap(self.T + 0.12, 22))            # gap 0.07, L 0.12
        r = self._ev(caps)
        self.assertEqual(r["verdict"], "PASS", r)
        self.assertEqual(r["champion_after"], 22)


class TestPollsDense(unittest.TestCase):
    def test_dense_sparse_and_unbounded(self):
        self.assertTrue(p._polls_dense(DENSE, 100.0, 101.0))
        holed = [t for t in DENSE if not 100.2 < t < 100.6]
        self.assertFalse(p._polls_dense(holed, 100.0, 101.0))
        self.assertFalse(p._polls_dense(None, 100.0, 101.0))
        self.assertFalse(p._polls_dense(DENSE, 100.0, 120.0))   # no poll after hi


class TestRowVerdict(unittest.TestCase):
    def test_aggregation(self):
        v = lambda *xs: [{"verdict": x} for x in xs]  # noqa: E731
        self.assertEqual(p.row_verdict(v("PASS", "NO_RESULT")), "PASS")
        self.assertEqual(p.row_verdict(v("PASS", "FAIL")), "FAIL")
        self.assertEqual(p.row_verdict(v("NO_RESULT")), "NO_RESULT")
        self.assertEqual(p.row_verdict([]), "NO_RESULT")


if __name__ == "__main__":
    unittest.main()

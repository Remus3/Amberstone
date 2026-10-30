"""s144 true-audit (cycle 64) of dashboard/_cs_retention.py.

apply_cs_retention runs on every /api/state build (dashboard/_state_builder.py
build_state, straight after the LCU snapshot read, with no try around it), so
anything it raises is a failed state build, and anything it gets wrong is a
champ-select view that is blank, or held past its window. Each class below
pins one finding:

F1  a non-str ``phase`` (the relay JSON can carry any type) raised TypeError
    out of the frozenset membership test (``["Lobby"] in frozenset``).
F2  a deeply nested but valid champ_select (json.loads accepts 600 levels,
    copy.deepcopy does not) raised RecursionError out of the deep copy.
F3  a NaN ``now`` was stored as the cache stamp, so the entry never expired;
    a str ``now`` raised TypeError.
F4  the default clock was the wall clock, so a backward clock step held a
    stale champ-select past its 120 s window.
F5  a ``now`` earlier than the cache stamp (negative elapsed) was read as
    "inside the window" and retained.
F6  the cache was two keys read and written without a lock while
    ThreadingHTTPServer runs several build_state calls at once, so one build
    could pair a new champ_select with an old stamp and clear it.
"""
from __future__ import annotations

import logging
import math
import threading
import time
import unittest

from dashboard import _cs_retention
from dashboard._cs_retention import apply_cs_retention, reset_cs_retention


def _cs(**extra):
    base = {"queue_id": 2400, "is_aram": True, "bench": [1, 2, 3]}
    base.update(extra)
    return base


def _seed(now=1000.0):
    apply_cs_retention({"phase": "ChampSelect", "champ_select": _cs()},
                       now=now)


def _deep(depth):
    root = {}
    node = root
    for _ in range(depth):
        nxt = {}
        node["a"] = nxt
        node = nxt
    node["leaf"] = 1
    return root


class _Base(unittest.TestCase):
    def setUp(self):
        reset_cs_retention()
        self._clock = _cs_retention._clock

    def tearDown(self):
        _cs_retention._clock = self._clock
        reset_cs_retention()


class F1NonStrPhaseTests(_Base):
    def test_list_phase_never_raises_and_holds(self):
        _seed()
        out = apply_cs_retention({"phase": ["Lobby"]}, now=1001.0)
        self.assertTrue(out["champ_select"]["_retained"])

    def test_dict_phase_never_raises_and_holds(self):
        _seed()
        out = apply_cs_retention({"phase": {"p": "Lobby"}}, now=1001.0)
        self.assertTrue(out["champ_select"]["_retained"])

    def test_string_clear_phase_still_clears(self):
        _seed()
        out = apply_cs_retention({"phase": "Lobby"}, now=1001.0)
        self.assertNotIn("champ_select", out)
        self.assertIsNone(_cs_retention._STATE["cs"])


class F2UncopyableChampSelectTests(_Base):
    def test_deep_fresh_cs_never_raises_and_passes_through(self):
        snap = {"phase": "ChampSelect", "champ_select": _deep(5000)}
        out = apply_cs_retention(snap, now=1000.0)
        self.assertIs(out, snap)

    def test_deep_fresh_cs_drops_the_older_cache(self):
        # The newest truth could not be cached, so the older entry is stale
        # and must not be spliced into the next lost-cs snapshot.
        _seed()
        apply_cs_retention({"phase": "ChampSelect",
                            "champ_select": _deep(5000)}, now=1001.0)
        out = apply_cs_retention({"phase": "GameStart"}, now=1002.0)
        self.assertNotIn("champ_select", out)
        self.assertIsNone(_cs_retention._STATE["cs"])

    def test_copy_failure_warns_once_per_streak_with_type_name_only(self):
        snap = {"phase": "ChampSelect",
                "champ_select": _deep(5000)}
        with self.assertLogs("dashboard._cs_retention",
                             level=logging.WARNING) as cm:
            apply_cs_retention(snap, now=1000.0)
            apply_cs_retention(snap, now=1001.0)
            _seed(now=1002.0)
            apply_cs_retention(snap, now=1003.0)
        self.assertEqual(len(cm.records), 2)
        for rec in cm.records:
            self.assertIn("RecursionError", rec.getMessage())
            self.assertNotIn("leaf", rec.getMessage())


class F3JunkNowTests(_Base):
    def test_non_finite_or_non_number_now_uses_the_clock(self):
        for junk in (math.nan, math.inf, -math.inf, "5", True, [1], 10**400):
            with self.subTest(now=junk):
                reset_cs_retention()
                _cs_retention._clock = lambda: 500.0
                apply_cs_retention(
                    {"phase": "ChampSelect", "champ_select": _cs()}, now=junk)
                self.assertEqual(_cs_retention._STATE["ts"], 500.0)

    def test_nan_seeded_entry_still_expires(self):
        _cs_retention._clock = lambda: 500.0
        apply_cs_retention({"phase": "ChampSelect", "champ_select": _cs()},
                           now=math.nan)
        out = apply_cs_retention({"phase": "GameStart"}, now=500.0 + 121.0)
        self.assertNotIn("champ_select", out)

    def test_str_now_on_lost_cs_path_never_raises(self):
        _cs_retention._clock = lambda: 1001.0
        _seed()
        out = apply_cs_retention({"phase": "GameStart"}, now="1001")
        self.assertTrue(out["champ_select"]["_retained"])


class F4MonotonicClockTests(_Base):
    def test_default_clock_is_monotonic(self):
        self.assertIs(_cs_retention._clock, time.monotonic)

    def test_default_now_reads_the_module_clock(self):
        ticks = iter([100.0, 100.0 + 121.0])
        _cs_retention._clock = lambda: next(ticks)
        apply_cs_retention({"phase": "ChampSelect", "champ_select": _cs()})
        out = apply_cs_retention({"phase": "GameStart"})
        self.assertNotIn("champ_select", out)


class F5NegativeElapsedTests(_Base):
    def test_now_before_the_stamp_expires_the_entry(self):
        _seed(now=1000.0)
        out = apply_cs_retention({"phase": "GameStart"}, now=900.0)
        self.assertNotIn("champ_select", out)
        self.assertIsNone(_cs_retention._STATE["cs"])

    def test_boundary_inside_window_still_retains(self):
        _seed(now=1000.0)
        out = apply_cs_retention({"phase": "GameStart"}, now=1000.0)
        self.assertTrue(out["champ_select"]["_retained"])
        out = apply_cs_retention({"phase": "GameStart"}, now=1120.0)
        self.assertTrue(out["champ_select"]["_retained"])


class F6LockTests(_Base):
    def test_a_second_build_waits_for_the_first(self):
        entered = threading.Event()
        release = threading.Event()
        real_copy = _cs_retention._copy

        def slow_copy(obj):
            entered.set()
            release.wait(5.0)
            return real_copy(obj)

        _cs_retention._copy = slow_copy
        done = threading.Event()
        try:
            a = threading.Thread(target=_seed, kwargs={"now": 1000.0},
                                 name="cs-retention-test-a", daemon=True)
            a.start()
            self.assertTrue(entered.wait(5.0))
            _cs_retention._copy = real_copy

            def second():
                apply_cs_retention({"phase": "GameStart"}, now=1001.0)
                done.set()

            b = threading.Thread(target=second, name="cs-retention-test-b",
                                 daemon=True)
            b.start()
            self.assertFalse(done.wait(0.3))
        finally:
            _cs_retention._copy = real_copy
            release.set()
        a.join(5.0)
        b.join(5.0)
        self.assertTrue(done.is_set())

    def test_reset_is_one_consistent_state(self):
        _seed()
        reset_cs_retention()
        self.assertEqual(_cs_retention._STATE, {"cs": None, "ts": 0.0})


if __name__ == "__main__":
    unittest.main()

"""Tests for the R221 pure wave-SPAWN-CLOCK in ``dashboard/_wave_timing.py``.

Slice 1 landed the ``minion_spawn_events`` extract in ``dashboard/_liveclient.py``
(``{"spawn_at_s": float, "event_id": int | None}`` rows, stream order). This
module consumes that list plus a game clock and returns the TIMING subset only.

The heavy pins here are the two that a later slice is most likely to break:

* The ANTI-FABRICATION pin. RM-124 declares the 3-lane wave STATE readout
  (``wave_top`` / ``wave_mid`` / ``wave_bot``, FREEZE / TRADE / CRASH /
  DISENGAGE) data-blocked three ways - ``:2999`` exposes no minion entities.
  A spawn clock cannot know where a wave sits in a lane, so the returned key set
  is asserted EXACTLY; adding a lane key fails here rather than shipping a
  fabricated push percentage.
* The OBSERVED-INTERVAL pin. Three prose sources disagree on first-wave time
  (0:30 / 1:05 / 1:30), so a hardcoded anchor is not trustworthy. A non-default
  spacing is fed in and asserted honored, proving no spawn constant is
  load-bearing whenever the stream carries >= 2 events.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from dashboard import _wave_timing
from dashboard._wave_timing import wave_timing

# Every key the readout is allowed to emit. Kept as a literal (not derived from
# the module) so a new key in the module is a test FAILURE, not a silent pass -
# deriving the expected set from the thing under test would make this pin
# circular and let a lane-state key ride in unchallenged.
_KEYS = {
    "wave_number",
    "last_spawn_s",
    "next_spawn_s",
    "next_spawn_in_s",
    "next_is_cannon",
    "cannon_every_n_waves",
}

_ALL_NONE = dict.fromkeys(_KEYS)


def _ev(t: float, eid: int | None = None) -> dict:
    """One upstream row in the exact shape ``_liveclient.py:398`` emits."""
    return {"spawn_at_s": float(t), "event_id": eid}


def _evs(*times: float) -> list:
    return [_ev(t, eid=i + 1) for i, t in enumerate(times)]


class KnownReadoutTests(unittest.TestCase):
    def test_exact_readout_at_known_event_set(self) -> None:
        # Five waves spaced 30s, clock 15s after the last one. Wave 6 is next
        # and 6 % 3 == 0, so the next wave carries the cannon.
        out = wave_timing(_evs(65.0, 95.0, 125.0, 155.0, 185.0), 200.0)
        self.assertEqual(out, {
            "wave_number": 5,
            "last_spawn_s": 185.0,
            "next_spawn_s": 215.0,
            "next_spawn_in_s": 15.0,
            "next_is_cannon": True,
            "cannon_every_n_waves": 3,
        })

    def test_exact_readout_when_next_wave_is_not_cannon(self) -> None:
        # Same clock shape one wave earlier: wave 5 is next, 5 % 3 != 0.
        out = wave_timing(_evs(65.0, 95.0, 125.0, 155.0), 170.0)
        self.assertEqual(out, {
            "wave_number": 4,
            "last_spawn_s": 155.0,
            "next_spawn_s": 185.0,
            "next_spawn_in_s": 15.0,
            "next_is_cannon": False,
            "cannon_every_n_waves": 3,
        })

    def test_clock_exactly_on_a_spawn_counts_that_wave(self) -> None:
        # An event whose time equals the clock has already fired.
        out = wave_timing(_evs(65.0, 95.0), 95.0)
        self.assertEqual(out["wave_number"], 2)
        self.assertEqual(out["last_spawn_s"], 95.0)
        self.assertEqual(out["next_spawn_s"], 125.0)
        self.assertEqual(out["next_spawn_in_s"], 30.0)

    def test_future_only_events_have_no_spawned_wave(self) -> None:
        # Defensive: the live stream is cumulative-past, but if a row somehow
        # sits ahead of the clock, nothing has spawned yet - the ordinal and
        # the last-spawn must stay None rather than counting an unfired wave.
        out = wave_timing(_evs(65.0, 95.0), 10.0)
        self.assertIsNone(out["wave_number"])
        self.assertIsNone(out["last_spawn_s"])
        self.assertEqual(out["next_spawn_s"], 65.0)
        self.assertEqual(out["next_spawn_in_s"], 55.0)


class NoDataSentinelTests(unittest.TestCase):
    def test_empty_event_list_is_all_none(self) -> None:
        self.assertEqual(wave_timing([], 200.0), _ALL_NONE)

    def test_game_time_none_is_all_none(self) -> None:
        self.assertEqual(wave_timing(_evs(65.0, 95.0), None), _ALL_NONE)

    def test_both_absent_is_all_none(self) -> None:
        self.assertEqual(wave_timing([], None), _ALL_NONE)

    def test_none_event_list_is_all_none(self) -> None:
        self.assertEqual(wave_timing(None, 200.0), _ALL_NONE)

    def test_non_list_event_arg_is_all_none(self) -> None:
        for junk in ("65", 65, {"spawn_at_s": 65.0}, object()):
            with self.subTest(junk=repr(junk)):
                self.assertEqual(wave_timing(junk, 200.0), _ALL_NONE)

    def test_non_numeric_game_time_is_all_none(self) -> None:
        for junk in ("200", [200.0], {}, object()):
            with self.subTest(junk=repr(junk)):
                self.assertEqual(wave_timing(_evs(65.0, 95.0), junk), _ALL_NONE)

    def test_bool_game_time_is_all_none(self) -> None:
        # bool is an int subclass; True must not read as game time 1.0.
        self.assertEqual(wave_timing(_evs(65.0, 95.0), True), _ALL_NONE)
        self.assertEqual(wave_timing(_evs(65.0, 95.0), False), _ALL_NONE)

    def test_all_rows_malformed_is_all_none(self) -> None:
        rows = ["bad", 7, None, [], {}, {"event_id": 1},
                {"spawn_at_s": None}, {"spawn_at_s": "soon"},
                {"spawn_at_s": True}]
        self.assertEqual(wave_timing(rows, 200.0), _ALL_NONE)

    def test_sentinel_is_a_fresh_dict_each_call(self) -> None:
        # A shared module-level sentinel would let one caller's mutation leak
        # into every later no-data readout.
        first = wave_timing([], None)
        first["wave_number"] = 99
        self.assertEqual(wave_timing([], None), _ALL_NONE)


class CannonCadenceBoundaryTests(unittest.TestCase):
    """The cadence table is the ONLY place the source disagreement lives.

    These pin the literal breakpoints so a table edit is a deliberate,
    test-visible act rather than a silent retune.
    """

    def _cadence_at(self, game_time_s: float) -> int | None:
        # Two events ending 10s before the clock: enough to anchor, and the
        # cadence lookup is what is under test, not the projection.
        evs = _evs(game_time_s - 40.0, game_time_s - 10.0)
        return wave_timing(evs, game_time_s)["cannon_every_n_waves"]

    def test_every_third_wave_just_below_first_breakpoint(self) -> None:
        self.assertEqual(self._cadence_at(839.9), 3)

    def test_every_second_wave_at_first_breakpoint(self) -> None:
        self.assertEqual(self._cadence_at(840.0), 2)

    def test_every_second_wave_just_below_second_breakpoint(self) -> None:
        self.assertEqual(self._cadence_at(1499.9), 2)

    def test_every_wave_at_second_breakpoint(self) -> None:
        self.assertEqual(self._cadence_at(1500.0), 1)

    def test_every_wave_well_past_second_breakpoint(self) -> None:
        self.assertEqual(self._cadence_at(2400.0), 1)

    def test_cadence_of_one_makes_every_next_wave_cannon(self) -> None:
        out = wave_timing(_evs(1520.0, 1545.0), 1550.0)
        self.assertEqual(out["cannon_every_n_waves"], 1)
        self.assertIs(out["next_is_cannon"], True)

    def test_table_is_ordered_and_starts_at_zero(self) -> None:
        table = _wave_timing._CANNON_CADENCE
        self.assertEqual(table[0][0], 0.0)
        times = [row[0] for row in table]
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(set(times)), len(times))
        for _t, every_n in table:
            self.assertIsInstance(every_n, int)
            self.assertGreaterEqual(every_n, 1)


class ForwardProjectionTests(unittest.TestCase):
    def test_clock_far_past_last_event_projects_forward(self) -> None:
        # Stale stream: 3 observed waves, clock 375s past the last one.
        # 375 / 30 = 12.5, so 12 unobserved waves have since spawned.
        out = wave_timing(_evs(65.0, 95.0, 125.0), 500.0)
        self.assertEqual(out["wave_number"], 15)
        self.assertEqual(out["last_spawn_s"], 125.0)
        self.assertEqual(out["next_spawn_s"], 515.0)
        self.assertEqual(out["next_spawn_in_s"], 15.0)

    def test_clock_on_an_exact_interval_multiple_stays_forward(self) -> None:
        # The float hazard: 125 - 95 == 30 exactly. The wave that just landed
        # must be counted and the countdown must still point at the NEXT one.
        out = wave_timing(_evs(65.0, 95.0), 125.0)
        self.assertEqual(out["wave_number"], 3)
        self.assertEqual(out["next_spawn_s"], 155.0)
        self.assertEqual(out["next_spawn_in_s"], 30.0)

    def test_countdown_is_never_negative_across_a_long_sweep(self) -> None:
        evs = _evs(65.0, 95.0, 125.0)
        t = 60.0
        while t <= 2400.0:
            with self.subTest(game_time=repr(t)):
                out = wave_timing(evs, t)
                self.assertIsNotNone(out["next_spawn_in_s"])
                self.assertGreaterEqual(out["next_spawn_in_s"], 0.0)
                self.assertGreater(out["next_spawn_s"], t - 1e-6)
            t += 7.5

    def test_countdown_never_exceeds_the_interval(self) -> None:
        evs = _evs(65.0, 95.0, 125.0)
        t = 130.0
        while t <= 900.0:
            with self.subTest(game_time=repr(t)):
                self.assertLessEqual(wave_timing(evs, t)["next_spawn_in_s"], 30.0)
            t += 3.25

    def test_wave_number_is_monotonic_as_the_clock_advances(self) -> None:
        evs = _evs(65.0, 95.0, 125.0)
        prev = 0
        t = 125.0
        while t <= 1200.0:
            n = wave_timing(evs, t)["wave_number"]
            with self.subTest(game_time=repr(t)):
                self.assertGreaterEqual(n, prev)
            prev = n
            t += 5.0


class ObservedIntervalTests(unittest.TestCase):
    def test_non_default_spacing_is_honored(self) -> None:
        # 25s spacing is the documented post-14:00 interval and deliberately
        # NOT the module default - if a constant were load-bearing this reads
        # 135.0 -> 140.0 and the countdown goes wrong.
        out = wave_timing(_evs(60.0, 85.0, 110.0), 115.0)
        self.assertEqual(out["next_spawn_s"], 135.0)
        self.assertEqual(out["next_spawn_in_s"], 20.0)

    def test_second_non_default_spacing_is_honored(self) -> None:
        # A spacing no source proposes: only observation can produce this.
        out = wave_timing(_evs(100.0, 118.0, 136.0), 140.0)
        self.assertEqual(out["next_spawn_s"], 154.0)
        self.assertEqual(out["next_spawn_in_s"], 14.0)

    def test_single_event_falls_back_to_the_documented_default(self) -> None:
        out = wave_timing(_evs(65.0), 70.0)
        self.assertEqual(out["wave_number"], 1)
        self.assertEqual(out["next_spawn_s"],
                         65.0 + _wave_timing._DEFAULT_WAVE_INTERVAL_S)

    def test_median_spacing_survives_one_dropped_event(self) -> None:
        # 65 -> 95 -> (gap) -> 155 -> 185: diffs 30, 60, 30. A last-diff rule
        # would take 30 here too, but a mean would take 40 - the median is what
        # makes a dropped event harmless.
        out = wave_timing(_evs(65.0, 95.0, 155.0, 185.0), 190.0)
        self.assertEqual(out["next_spawn_s"], 215.0)

    def test_out_of_order_stream_does_not_corrupt_the_clock(self) -> None:
        shuffled = _evs(125.0, 65.0, 185.0, 95.0, 155.0)
        ordered = _evs(65.0, 95.0, 125.0, 155.0, 185.0)
        self.assertEqual(wave_timing(shuffled, 200.0),
                         wave_timing(ordered, 200.0))

    def test_degenerate_zero_spacing_falls_back_to_the_default(self) -> None:
        # Duplicate times yield a zero interval; dividing by it would raise.
        out = wave_timing(_evs(65.0, 65.0), 70.0)
        self.assertEqual(out["next_spawn_s"],
                         65.0 + _wave_timing._DEFAULT_WAVE_INTERVAL_S)


class MalformedRowTests(unittest.TestCase):
    def test_malformed_rows_are_skipped_without_crashing(self) -> None:
        rows = [
            "bad", 7, None, [], (),
            {},                          # no spawn_at_s
            {"event_id": 4},             # ordinal without a time
            {"spawn_at_s": None},
            {"spawn_at_s": "soon"},
            {"spawn_at_s": True},        # bool is not a time
            {"spawn_at_s": False},
            _ev(65.0, eid=1),
            _ev(95.0, eid=2),
        ]
        out = wave_timing(rows, 100.0)
        self.assertEqual(out["wave_number"], 2)
        self.assertEqual(out["last_spawn_s"], 95.0)
        self.assertEqual(out["next_spawn_s"], 125.0)

    def test_int_spawn_time_is_accepted_and_floated(self) -> None:
        out = wave_timing([{"spawn_at_s": 65, "event_id": 1},
                           {"spawn_at_s": 95, "event_id": 2}], 100.0)
        self.assertIsInstance(out["last_spawn_s"], float)
        self.assertEqual(out["last_spawn_s"], 95.0)

    def test_int_game_time_is_accepted(self) -> None:
        out = wave_timing(_evs(65.0, 95.0), 100)
        self.assertEqual(out["next_spawn_in_s"], 25.0)

    def test_caller_rows_are_not_mutated(self) -> None:
        rows = _evs(65.0, 95.0)
        before = [dict(r) for r in rows]
        wave_timing(rows, 100.0)
        self.assertEqual(rows, before)


class AntiFabricationPinTests(unittest.TestCase):
    """RM-124: a spawn clock cannot know where a wave sits in a lane.

    ``:2999`` exposes no minion entities, the Overlay Platform M GEP contract gives
    ``minionKills`` counts only, and Match-V5 has no minion event type. Any lane
    push percentage or wave-state verb derived from spawn timing would be
    fabrication, and a wrong precompute is worse than no precompute.
    """

    _FORBIDDEN_KEYS = ("wave_top", "wave_mid", "wave_bot")
    _FORBIDDEN_VERBS = ("freeze", "trade", "crash", "disengage",
                        "slow_push", "fast_push")

    def _readouts(self) -> list:
        return [
            wave_timing(_evs(65.0, 95.0, 125.0), 140.0),
            wave_timing(_evs(1520.0, 1545.0), 1550.0),
            wave_timing(_evs(65.0), 70.0),
            wave_timing([], 200.0),
            wave_timing(_evs(65.0, 95.0), None),
        ]

    def test_no_lane_wave_state_keys(self) -> None:
        for out in self._readouts():
            for key in self._FORBIDDEN_KEYS:
                with self.subTest(key=key):
                    self.assertNotIn(key, out)

    def test_key_set_is_exactly_the_timing_subset(self) -> None:
        for i, out in enumerate(self._readouts()):
            with self.subTest(readout=i):
                self.assertEqual(set(out), _KEYS)

    def test_no_wave_state_verb_is_emitted_as_a_value(self) -> None:
        for out in self._readouts():
            for key, value in out.items():
                if not isinstance(value, str):
                    continue
                for verb in self._FORBIDDEN_VERBS:
                    with self.subTest(key=key, verb=verb):
                        self.assertNotIn(verb, value.lower())

    def test_readout_carries_no_percentage_shaped_value(self) -> None:
        # A push percentage would ride in as a 0-100 or 0-1 float on some new
        # key; the exact-key-set pin above is the real gate, this documents the
        # shape that must never appear.
        out = wave_timing(_evs(65.0, 95.0, 125.0), 140.0)
        self.assertIsInstance(out["wave_number"], int)
        self.assertIsInstance(out["next_is_cannon"], bool)
        self.assertIsInstance(out["cannon_every_n_waves"], int)


class PurityTests(unittest.TestCase):
    def test_repeated_calls_are_identical(self) -> None:
        evs = _evs(65.0, 95.0, 125.0)
        first = wave_timing(evs, 140.0)
        for _ in range(5):
            self.assertEqual(wave_timing(evs, 140.0), first)

    def test_module_imports_no_io_or_clock(self) -> None:
        # A pure compute must not reach for wall-clock time, the network, or
        # dashboard state - any of those makes the readout untestable and
        # couples a Tier-1 module to live runtime.
        text = Path(_wave_timing.__file__).read_text(encoding="utf-8")
        for banned in ("datetime.now", "time.time", "urlopen", "requests",
                       "open(", "import os", "liveclient_cache"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, text)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self) -> None:
        for path in (Path(_wave_timing.__file__), Path(__file__)):
            text = path.read_text(encoding="utf-8")
            for cp in (0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D):
                self.assertNotIn(chr(cp), text)
            text.encode("ascii")


if __name__ == "__main__":
    unittest.main()

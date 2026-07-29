# arch: RM-124 deterministic wave/cannon clock callout | section=tests | frozen=no
"""RED-first tests for the RM-124 deterministic wave / cannon clock.

The wave clock is a PURE function of game_time + the live MinionsSpawning
anchor (its EventTime), never a hardcoded spawn time. It returns a single
"next cannon wave" callout dict {tag, line, eta_s, kind} shaped exactly like
recall_callout so the generic callouts.js sink renders it with zero JS change.

Cadence arithmetic (interval brackets + cannon indexing) is locked here; the
LIVE flip stays gated OFF (enable_wave default False) pending one real-game
validation - so next_callouts emits NO wave kind by default.
"""
from __future__ import annotations

import unittest

from core.event_callouts import next_callouts, wave_callout


# Anchor = first MinionsSpawning EventTime, 1:05 (65s). With a 30s pre-14:00
# interval the wave spawn times are 65, 95, 125, 155, 185, 215 ... and cannon
# lands on every 3rd wave (index 3, 6, ...), i.e. absolute 125s (2:05), 215s.
_ANCHOR = 65.0


class WaveCalloutPureTests(unittest.TestCase):
    def test_returns_next_cannon_eta_from_anchor(self):
        # game_time 100s: next cannon is wave 3 @ 125s -> eta 25s.
        c = wave_callout(100.0, [{"at_s": _ANCHOR}])
        self.assertIsNotNone(c, "cannon callout must fire with a valid anchor")
        self.assertEqual(c["kind"], "wave")
        self.assertAlmostEqual(c["eta_s"], 25.0, delta=0.01)

    def test_advances_past_a_consumed_cannon(self):
        # game_time 130s is just past wave-3 cannon (125s); next cannon is
        # wave 6 @ 65 + 30*5 = 215s -> eta 85s.
        c = wave_callout(130.0, [{"at_s": _ANCHOR}])
        self.assertIsNotNone(c)
        self.assertAlmostEqual(c["eta_s"], 85.0, delta=0.01)

    def test_no_anchor_event_returns_none(self):
        # The whole point of RM-124: NEVER synthesize a spawn time. No anchor
        # event -> no callout.
        self.assertIsNone(wave_callout(100.0, []))
        self.assertIsNone(wave_callout(100.0, None))

    def test_failsoft_on_garbage(self):
        self.assertIsNone(wave_callout("x", [{"at_s": _ANCHOR}]))
        self.assertIsNone(wave_callout(100.0, [{"at_s": None}]))
        self.assertIsNone(wave_callout(100.0, ["not-a-dict"]))
        self.assertIsNone(wave_callout(100.0, [{"at_s": True}]))  # bool guard

    def test_line_is_ascii_and_short(self):
        c = wave_callout(100.0, [{"at_s": _ANCHOR}])
        line = c["line"]
        self.assertTrue(line.isascii(), "callout line must be 7-bit ASCII")
        self.assertLessEqual(len(line.split()), 10, "line <= 10 words")
        # en/em dash + smart quotes, built from escapes so this test file
        # itself stays 7-bit ASCII (the repo hard rule).
        for cp in (0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D):
            self.assertNotIn(chr(cp), line)


class NextCalloutsWaveGateTests(unittest.TestCase):
    def test_wave_gated_off_by_default(self):
        # Do-not-flip-blind: default next_callouts must emit NO wave kind even
        # with a live anchor present.
        cs = next_callouts("sr", 100.0, 1, 0, max_n=99,
                           minion_events=[{"at_s": _ANCHOR}])
        self.assertFalse(any(c.get("kind") == "wave" for c in cs),
                         "wave kind must stay gated OFF by default")

    def test_wave_emitted_when_enabled(self):
        cs = next_callouts("sr", 100.0, 1, 0, max_n=99,
                           minion_events=[{"at_s": _ANCHOR}],
                           enable_wave=True)
        wave = [c for c in cs if c.get("kind") == "wave"]
        self.assertEqual(len(wave), 1, "exactly one wave callout when enabled")
        self.assertAlmostEqual(wave[0]["eta_s"], 25.0, delta=0.01)

    def test_wave_sr_only_even_when_enabled(self):
        for mode in ("aram", "arena"):
            cs = next_callouts(mode, 100.0, 1, 0, max_n=99,
                               minion_events=[{"at_s": _ANCHOR}],
                               enable_wave=True)
            self.assertFalse(any(c.get("kind") == "wave" for c in cs),
                             f"{mode} must never emit a wave callout")


if __name__ == "__main__":
    unittest.main()

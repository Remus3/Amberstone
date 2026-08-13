"""B4-c (RM-189): voice output must be silent while a game is live.

`coaches/voice_coach.py` speaks the Right Now headline through Windows SAPI.
It is the single most reviewer-visible form of "a notification that dictates
player action based on the current game state" - a reviewer does not have to
read a panel, they hear it. Riot's third-party rules ban it in-game; the
operator decision (docs/OVERLAY_COMPLIANCE_PLAN.md section 6c) moves coaching
to pre-game and post-game.

The gate sits inside speak() rather than on its one current caller
(dashboard/routes_coach.py:137, the /api/speak route) so that any future
caller inherits it. is_available() is a capability probe, not a gate, and is
deliberately left alone.

Spy shape matters here. The design forbids a raise-based spy: speak() wraps
its subprocess launch in `except Exception`, so an AssertionError raised from
inside a patched Popen would be swallowed and the test would pass whether or
not the gate worked (memory: reference_raise_based_spy_is_vacuous_under_fail_soft).
These tests use a RECORDING spy plus the return value instead.
"""
from __future__ import annotations

import unittest
from unittest import mock

from coaches import voice_coach
from core import live_game_gate


class _PopenSpy:
    """Recording stand-in for subprocess.Popen. Never raises."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return mock.MagicMock()


class VoiceCoachLiveGateTests(unittest.TestCase):
    def setUp(self):
        # speak() carries module-level dedup + rate-limit state; a previous
        # test's utterance would otherwise rate-limit this one and produce a
        # False that looks like the gate firing.
        voice_coach._LAST_TS = 0.0
        voice_coach._LAST_TEXT = ""
        self.spy = _PopenSpy()
        p = mock.patch.object(voice_coach.subprocess, "Popen", self.spy)
        p.start()
        self.addCleanup(p.stop)

    def _set_live(self, live: bool):
        p = mock.patch.object(live_game_gate, "live_game_now", return_value=live)
        p.start()
        self.addCleanup(p.stop)

    def test_silent_while_live(self):
        self._set_live(True)
        spoke = voice_coach.speak("All in now, their flash is down.")
        self.assertFalse(spoke)
        self.assertEqual(self.spy.calls, [],
                         "a subprocess was launched during a live game")

    def test_negative_control_speaks_when_not_live(self):
        """Without this the live assertion is vacuous - a speak() that is
        broken for every input would pass it."""
        self._set_live(False)
        spoke = voice_coach.speak("Ban Yasuo, he is first-picked here.")
        self.assertTrue(spoke)
        self.assertEqual(len(self.spy.calls), 1)

    def test_gate_precedes_the_dedup_and_rate_limit_bookkeeping(self):
        """A live utterance must not consume the dedup slot. If it did, the
        first legitimate post-game line with the same text would be silently
        swallowed as a duplicate."""
        self._set_live(True)
        voice_coach.speak("Reset now.")
        self.assertEqual(voice_coach._LAST_TEXT, "")
        self.assertEqual(voice_coach._LAST_TS, 0.0)

    def test_is_available_is_not_the_gate(self):
        """is_available() is a capability probe. It must keep answering the
        capability question during a game, so it is NOT gated - the guard
        exists so nobody 'fixes' compliance by stubbing it to False."""
        self._set_live(True)
        with mock.patch.object(voice_coach.subprocess, "run") as run:
            run.return_value = mock.MagicMock(stdout="3")
            self.assertTrue(voice_coach.is_available())


class LiveGameGateTests(unittest.TestCase):
    """core/live_game_gate.py is the single home for the predicate. It must
    not be re-implemented in _state_builder - a private copy is exactly how a
    resolver fix stops reaching its consumers."""

    def test_state_builder_reexports_the_same_object(self):
        from dashboard import _state_builder
        self.assertIs(_state_builder.is_live_game, live_game_gate.is_live_game)

    def test_live_game_now_reads_health(self):
        with mock.patch.object(live_game_gate, "_read_health",
                               return_value={"has_game": True}):
            self.assertTrue(live_game_gate.live_game_now())
        with mock.patch.object(live_game_gate, "_read_health",
                               return_value={"mode": "client"}):
            self.assertFalse(live_game_gate.live_game_now())

    def test_live_game_now_is_fail_safe_on_a_missing_health_file(self):
        """Fail-safe, matching the client gate: an unreadable health.json is
        not evidence of a game. Failing closed would silence pre-game and
        post-game voice for good the first time the file went missing."""
        with mock.patch.object(live_game_gate, "_read_health",
                               return_value=None):
            self.assertFalse(live_game_gate.live_game_now())

    def test_live_game_now_never_raises(self):
        with mock.patch.object(live_game_gate, "_read_health",
                               side_effect=OSError("boom")):
            self.assertFalse(live_game_gate.live_game_now())


if __name__ == "__main__":
    unittest.main()

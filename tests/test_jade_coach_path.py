"""
tests/test_jade_coach_path.py - RM-141 S4: JADE reuses the SR coach path.

WHY this file exists: a JADE game today produces WRONG output, not absent
output. Two independent gates each fail closed on a JADE tick, and the
dashboard keeps serving the last SR game's advice:

  1. core/sr_aram_worker.py - is_sr_mode membership never matches "JADE",
     so no coach ever fires.
  2. app/_game_lifecycle.py - the RiftSnapshot payload branch and its
     emergency fallback both gate on (MODE_SR, MODE_ARENA, MODE_BRAWL),
     so a MODE_JADE envelope yields payload None twice over.

The KIWI_JADE assertions are the load-bearing half of this file: KIWI_JADE is
the ARAM-Mayhem-Jade crossover played on the Howling Abyss and belongs to the
ARAM coach's tick, never the SR coach's. They fail against the natural wrong
implementation - a substring or startswith test on "JADE".
"""
from __future__ import annotations

import queue
import unittest

from core.game_snapshot import (
    MODE_ARAM,
    MODE_ARENA,
    MODE_BRAWL,
    MODE_JADE,
    MODE_SR,
    RiftSnapshot,
)
from core.sr_aram_worker import SrAramWorker


# --------------------------------------------------------------------------
# Gate 1: core/sr_aram_worker.py - does a tick reach _submit_coaching?
# --------------------------------------------------------------------------

class _OneShotReader:
    """read_game() yields the state once, then halts the worker loop."""

    def __init__(self, state, stop_event):
        self._state = state
        self._stop_event = stop_event
        self.calls = 0

    def read_game(self):
        self.calls += 1
        self._stop_event.set()
        return self._state


def _submits_for(game_mode: str) -> bool:
    """Run exactly one SrAramWorker tick and report whether the SR coach fired."""
    worker = SrAramWorker(result_queue=queue.Queue(), coach=object())
    state = {"game_mode": game_mode, "champion": "Ahri"}
    worker._reader = _OneShotReader(state, worker._stop_event)

    fired = []
    worker._submit_coaching = lambda s: fired.append(s)  # type: ignore[method-assign]

    worker._run(worker._generation)

    assert worker._reader.calls == 1, "harness never drove a tick"
    return bool(fired)


class TestSrCoachGateOnGameMode(unittest.TestCase):

    def test_jade_fires_sr_coach_and_kiwi_jade_does_not(self):
        """The differential that pins both directions of the fix at once.

        JADE firing is the revert-detector. KIWI_JADE staying silent is the
        wrong-implementation detector: a substring or startswith test on
        "JADE" would capture KIWI_JADE and steal the ARAM coach's tick.
        """
        self.assertTrue(
            _submits_for("JADE"),
            "JADE is the throwback Rift and must fire the SR coach",
        )
        self.assertFalse(
            _submits_for("KIWI_JADE"),
            "KIWI_JADE is the ARAM coach's tick, not the SR coach's",
        )

    def test_kiwi_jade_lowercase_also_does_not_fire(self):
        """gm_upper normalises case, so the exclusion must survive casing."""
        self.assertFalse(_submits_for("kiwi_jade"))

    def test_jade_lowercase_fires(self):
        self.assertTrue(_submits_for("jade"))

    def test_existing_sr_modes_still_fire(self):
        for gm in ("CLASSIC", "RANKED", "PRACTICETOOL"):
            with self.subTest(game_mode=gm):
                self.assertTrue(_submits_for(gm))

    def test_non_sr_modes_still_do_not_fire(self):
        for gm in ("ARAM", "KIWI", "CHERRY", "TFT"):
            with self.subTest(game_mode=gm):
                self.assertFalse(_submits_for(gm))


# --------------------------------------------------------------------------
# Gate 2: app/_game_lifecycle.py - is a RiftSnapshot payload built?
# --------------------------------------------------------------------------

class _AramSentinel:
    """Distinct from RiftSnapshot so the two payload branches cannot be confused."""
    raw_state = None


class _FakeReader:
    """to_rift_snapshot returns `payload`; the ARAM branch returns its own marker."""

    def __init__(self, payload):
        self._payload = payload
        self.aram_marker = _AramSentinel()

    def to_rift_snapshot(self, state):
        return self._payload

    def to_aram_snapshot(self, state):
        return self.aram_marker


class _FakeStateAuthority:
    def __init__(self, mode):
        self.envelope = type("_Env", (), {"mode": mode})()
        self.set_calls = []

    def set_envelope(self, mode, payload):
        self.set_calls.append((mode, payload))


class _FakeApp:
    def __init__(self, mode, reader):
        self.state = _FakeStateAuthority(mode)
        self.reader = reader
        self._none_streak = 0
        self._was_in_game = True   # skip the on_game_start branch
        self._tft_mode = False
        self._auto_mode = False
        self.mode = "game"
        self._game_state = None


# A state whose every has-data probe reads false, so _apply_auto_fields is
# never reached and the test stays scoped to payload selection.
_INERT_STATE = {"game_mode": "JADE", "champion": "Unknown",
                "game_seconds": 0, "hp_max": 1}


def _payload_for(env_mode, reader_payload):
    from app._game_lifecycle import GameLifecycleManager

    app = _FakeApp(env_mode, _FakeReader(reader_payload))
    GameLifecycleManager(app)._process_game_state(dict(_INERT_STATE))
    if not app.state.set_calls:
        return None
    mode, payload = app.state.set_calls[-1]
    assert mode == env_mode, "envelope mode was rewritten"
    return payload


class TestLifecyclePayloadSelection(unittest.TestCase):

    def test_jade_takes_the_normal_rift_branch(self):
        sentinel = RiftSnapshot()
        self.assertIs(_payload_for(MODE_JADE, sentinel), sentinel)

    def test_jade_takes_the_emergency_rift_fallback(self):
        """Reader returns None, so only the :389 fallback tuple can save it."""
        payload = _payload_for(MODE_JADE, None)
        self.assertIsNotNone(payload)
        self.assertIsInstance(payload, RiftSnapshot)

    def test_existing_rift_modes_unregressed_on_both_branches(self):
        for mode in (MODE_SR, MODE_ARENA, MODE_BRAWL):
            with self.subTest(mode=mode, branch="normal"):
                sentinel = RiftSnapshot()
                self.assertIs(_payload_for(mode, sentinel), sentinel)
            with self.subTest(mode=mode, branch="emergency"):
                self.assertIsInstance(_payload_for(mode, None), RiftSnapshot)

    def test_aram_is_not_swept_into_the_rift_tuples(self):
        """ARAM must still take its own branch, never the widened rift tuple."""
        payload = _payload_for(MODE_ARAM, RiftSnapshot())
        self.assertIsInstance(payload, _AramSentinel)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

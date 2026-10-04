"""P2-4: SrAramWorker.is_first is an EDGE, not "first read this run".

Before P2-4, core/sr_aram_worker.py computed ``is_first = not was_in_game``
with ``was_in_game = False`` at the top of every ``_run``. Starting RC (or a
remediation ``restart()``) mid-game therefore stamped the very first read of an
already-running game as a game start, and a read error followed by a good read
had no way to say "that was a reconnect". These tests drive ``_run``
synchronously against a scripted reader and pin the edge semantics.
"""
from __future__ import annotations

import queue

import pytest

import core.sr_aram_worker as srw
from core.game_snapshot import mode_from_game_mode_string
from core.sr_aram_worker import SrAramWorker
from tests.fixtures.state_dicts import ARAM_STATE, SR_STATE

_S = dict(SR_STATE, game_mode="CLASSIC")


class _ScriptReader:
    """read_game() replays a script; dict -> state, None -> no game,
    exception instance -> raised. Stops the worker when exhausted."""

    def __init__(self, worker, script):
        self._w = worker
        self._script = list(script)

    def read_game(self):
        if not self._script:
            self._w._stop_event.set()
            return None
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    monkeypatch.setattr(srw, "BACKOFF_MIN_S", 0.0)
    monkeypatch.setattr(srw, "BACKOFF_MAX_S", 0.0)


def _drive(script):
    rq = queue.Queue(maxsize=256)
    w = SrAramWorker(result_queue=rq, coach=None)
    w._reader = _ScriptReader(w, script)
    w._run(w._generation)
    out = []
    while True:
        try:
            out.append(rq.get_nowait())
        except queue.Empty:
            return out


def _firsts(results):
    return [r.is_first for r in results if r.state is not None]


def test_startup_mid_game_is_not_a_game_start():
    assert _firsts(_drive([_S, _S, _S])) == [False, False, False]


def test_absent_then_present_is_a_game_start():
    assert _firsts(_drive([None, _S, _S])) == [True, False]


def test_unreachable_then_present_is_not_a_game_start():
    assert _firsts(_drive([RuntimeError("relay down"), _S, _S])) == [False, False]


def test_read_error_between_lobby_and_game_is_not_a_game_start():
    # primed absent in the lobby, then a read error, then a game: reconnect
    assert _firsts(_drive([None, RuntimeError("relay down"), _S])) == [False]


def test_single_none_blip_mid_game_does_not_refire():
    assert _firsts(_drive([None, _S, None, _S])) == [True, False]


def test_game_end_then_new_game_fires_again():
    end = [None] * srw.NONE_STREAK_END
    results = _drive([None, _S] + end + [_S])
    assert _firsts(results) == [True, True]
    assert any(r.end_signal for r in results)


def test_startup_mid_game_then_new_game_fires_for_the_new_game():
    end = [None] * srw.NONE_STREAK_END
    assert _firsts(_drive([_S] + end + [_S])) == [False, True]


def test_canon_mode_still_resolved_on_startup_mid_game():
    results = _drive([ARAM_STATE])
    assert results[0].is_first is False
    assert results[0].canon_mode == mode_from_game_mode_string("ARAM")

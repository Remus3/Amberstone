"""RM-461 round 2 - an unreadable creep score must stay UNCOUNTABLE for the
once-per-game adaptation latch.

``dashboard/_adaptation_latch.compute`` skips a frame whose ``cs`` is None /
not int()-able, and ``_find_opponent_cs`` returns None for an unreadable
opponent ``creep_score``. It latches ``cs_at_10`` from the FIRST frame at
>= 600s and ``csd_at_15`` from the FIRST at >= 900s, for the rest of the game.

Round 1 of RM-461 degraded a bad active ``cs`` to 0, and RM-456 had already
degraded a bad ``players[].creep_score`` to 0. A 0 is int()-able, so one bad
frame at t=901 latched ``cs_at_10 = 0`` / ``csd_at_15 = -60`` (or a
``csd_at_15`` of the full own cs against a phantom 0) permanently. The latch
then reaches the coach via ``_state_builder``.

Rule adopted: an unreadable OR MISSING creep score is None in the summary,
for both ``cs`` and ``players[].creep_score``, so missing and bad agree and the
latch waits for the next readable frame. Valid values are unchanged.
Consumers: stats_panel.js renders ``lc.cs == null`` as "-";
coach_choices.js ``coach.cs || lc.cs || 0``; ``_deterministic_coaching._first``
skips None; ``players[].creep_score`` has no JS reader (grepped).
"""
from __future__ import annotations

import math
import time
from unittest import mock

import pytest

from dashboard import _adaptation_latch as latch
from dashboard import _liveclient

_BAD = [None, "nan", float("nan"), "abc", math.inf, [1], {"v": 1}]
_BAD_IDS = ["None", "strnan", "floatnan", "abc", "inf", "list", "dict"]
_MISSING = object()


def _pl(name, team, creep):
    scores = {"kills": 1, "deaths": 0, "assists": 1}
    if creep is not _MISSING:
        scores["creepScore"] = creep
    return {"summonerName": name, "championName": name, "team": team,
            "position": "MIDDLE", "level": 9, "items": [], "scores": scores}


def _frame(t, creep, opp=60):
    return {"activePlayer": {"summonerName": "Me", "level": 9, "currentGold": 1,
                             "championStats": {}},
            "allPlayers": [_pl("Me", "ORDER", creep), _pl("Zed", "CHAOS", opp)],
            "gameData": {"gameTime": t, "gameMode": "CLASSIC"}}


def _latch(frame):
    from core.liveclient_cache import Snapshot
    snap = Snapshot(data=frame, ts=time.time())
    with mock.patch("core.liveclient_cache.get", return_value=snap):
        summary = _liveclient.liveclient_summary()
    summary["game_id"] = "g"
    return latch.compute(summary)


@pytest.fixture(autouse=True)
def _fresh_latch():
    latch.reset()
    yield
    latch.reset()


@pytest.mark.parametrize("bad", [*_BAD, _MISSING], ids=[*_BAD_IDS, "missing"])
def test_bad_active_cs_frame_does_not_latch(bad):
    assert _latch(_frame(901.0, bad)) == {}
    assert _latch(_frame(905.0, 90)) == {"cs_at_10": 90, "csd_at_15": 30}


@pytest.mark.parametrize("bad", [*_BAD, _MISSING], ids=[*_BAD_IDS, "missing"])
def test_bad_opponent_cs_frame_does_not_latch_csd(bad):
    # cs_at_10 is readable on the bad-opponent frame and may latch; csd must
    # wait for a readable opponent, not diff against a phantom 0.
    assert _latch(_frame(901.0, 90, opp=bad)) == {"cs_at_10": 90}
    assert _latch(_frame(905.0, 95, opp=60)) == {"cs_at_10": 90, "csd_at_15": 35}


def test_valid_frames_latch_unchanged():
    assert _latch(_frame(901.0, 90)) == {"cs_at_10": 90, "csd_at_15": 30}
    assert _latch(_frame(950.0, 120, opp=70)) == {"cs_at_10": 90, "csd_at_15": 30}


def test_valid_zero_cs_is_still_countable():
    assert _latch(_frame(901.0, 0, opp=0)) == {"cs_at_10": 0, "csd_at_15": 0}

"""RM-603: liveclient_summary carries ``ability_ranks`` so a consumer of
consecutive /api/state snapshots (the RM-604 deriver) can run the skill-point
tracker. Additive descriptive state (a rank count, not a directive). Synthetic,
name-scrubbed payloads.
"""
from __future__ import annotations

import time
from unittest import mock

from core import skill_point_tracker as spt
from dashboard import _liveclient


def _agd(abilities):
    ap = {"summonerName": "P1", "level": 3, "currentGold": 0,
          "championStats": {}}
    if abilities is not None:
        ap["abilities"] = abilities
    return {"activePlayer": ap, "allPlayers": [],
            "gameData": {"gameTime": 200.0, "gameMode": "CLASSIC"}}


def _summary(agd):
    from core.liveclient_cache import Snapshot
    snap = Snapshot(data=agd, ts=time.time())
    with mock.patch("core.liveclient_cache.get", return_value=snap):
        return _liveclient.liveclient_summary()


_AB = {"Passive": {"displayName": "P"},
       "Q": {"abilityLevel": 2}, "W": {"abilityLevel": 0},
       "E": {"abilityLevel": 0}, "R": {"abilityLevel": 0}}


def test_ranks_present_and_zero_kept():
    out = _summary(_agd(_AB))
    assert out["ability_ranks"] == {"q": 2, "w": 0, "e": 0, "r": 0}
    rd = spt.read_skill_snapshot(out)
    assert rd is not None and spt.spendable(rd, "") == 1


def test_missing_abilities_is_none_not_zeros():
    out = _summary(_agd(None))
    assert out["ability_ranks"] is None
    assert spt.read_skill_snapshot(out) is None


def test_partial_abilities_is_none():
    out = _summary(_agd({"Q": {"abilityLevel": 1}}))
    assert out["ability_ranks"] is None
    # The rest of the summary survives.
    assert out["level"] == 3

"""RM-415 - dashboard/_liveclient.py ``liveclient_summary`` envelope readers.

``liveclient_summary`` read ``d.get("activePlayer") or {}``,
``d.get("gameData") or {}``, ``ap.get("championStats") or {}``,
``d.get("allPlayers") or []`` and the per-player ``scores`` / ``items`` the
same way. A retyped inner field raised at the next ``.get()`` / ``for``.

Caller severity (measured): the whole body sits in one outer
``except Exception: return {}``, so a single retyped inner field did not
crash - it BLANKED THE ENTIRE SUMMARY (game time, gold, HP, rosters, event
callouts, build path) for every consumer of /api/state. The ``events``
readers already had their own inner ``try`` and degraded to ``[]``; they are
routed through the seam for uniformity, not because they were raising.

Acceptance: a retyped inner field degrades THAT field only; the well-formed
remainder of the frame still reaches the summary.
"""
from __future__ import annotations

import time
from unittest import mock

import pytest

from dashboard import _liveclient

_HOSTILE = [None, "", "nan", "12", True, 5, 1.5]
_HOSTILE_IDS = ["None", "empty", "nan", "strnum", "bool", "int", "float"]


_DEFAULT = object()


def _player(name, team, kills=0, assists=0, items=_DEFAULT):
    return {"summonerName": name, "championName": name, "team": team,
            "position": "MIDDLE",
            "items": ([{"itemID": 3047, "displayName": "Boots"}]
                      if items is _DEFAULT else items),
            "scores": {"kills": kills, "deaths": 0, "assists": assists, "creepScore": 50}}


def _frame(**over):
    d = {
        "activePlayer": {"summonerName": "Me", "level": 9, "currentGold": 1200,
                         "championStats": {"currentHealth": 800, "maxHealth": 1000}},
        "allPlayers": [_player("Me", "ORDER", kills=2, assists=2),
                       _player("Zed", "CHAOS", kills=1)],
        "gameData": {"gameTime": 600.0, "gameMode": "CLASSIC"},
        "events": {"Events": [{"EventName": "MinionsSpawning", "EventTime": 65.0}]},
    }
    d.update(over)
    return d


def _summary(frame):
    from core.liveclient_cache import Snapshot
    snap = Snapshot(data=frame, ts=time.time())
    with mock.patch("core.liveclient_cache.get", return_value=snap):
        return _liveclient.liveclient_summary()


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_active_player_retyped_keeps_the_rest_of_the_summary(bad):
    out = _summary(_frame(activePlayer=bad))
    assert out.get("game_time_s") == 600
    assert out.get("game_mode") == "CLASSIC"
    assert out.get("gold") == 0
    assert [p["championName"] for p in out.get("allPlayers", [])] == ["Me", "Zed"]


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_game_data_retyped_keeps_the_rest_of_the_summary(bad):
    out = _summary(_frame(gameData=bad))
    assert out.get("game_time_s") == 0
    assert out.get("gold") == 1200
    assert out.get("enemy_team") == ["Zed"]


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_champion_stats_retyped_keeps_the_rest_of_the_summary(bad):
    ap = {"summonerName": "Me", "level": 9, "currentGold": 1200, "championStats": bad}
    out = _summary(_frame(activePlayer=ap))
    assert out.get("hp") == 0
    assert out.get("gold") == 1200
    assert out.get("game_time_s") == 600


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_all_players_retyped_keeps_the_rest_of_the_summary(bad):
    out = _summary(_frame(allPlayers=bad))
    assert out.get("game_time_s") == 600
    assert out.get("allPlayers") == []
    assert out.get("enemy_team") == []


def test_non_dict_roster_entries_are_skipped():
    frame = _frame()
    frame["allPlayers"] = ["junk", 5, None] + frame["allPlayers"]
    out = _summary(frame)
    assert out.get("champion") == "Me"
    assert out.get("enemy_team") == ["Zed"]
    assert out.get("kill_participation_pct") == "200%"


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_my_scores_retyped_keeps_the_rest_of_the_summary(bad):
    me = _player("Me", "ORDER")
    me["scores"] = bad
    out = _summary(_frame(allPlayers=[me, _player("Zed", "CHAOS")]))
    assert out.get("kda") == "0/0/0"
    assert out.get("champion") == "Me"
    assert out.get("game_time_s") == 600


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_player_items_retyped_keeps_the_rest_of_the_summary(bad):
    me = _player("Me", "ORDER", items=bad)
    zed = _player("Zed", "CHAOS", items=bad)
    out = _summary(_frame(allPlayers=[me, zed]))
    assert out.get("owned_items") == []
    assert out.get("owned_item_ids") == []
    assert out.get("enemy_item_ids") == []
    assert out.get("champion") == "Me"


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_other_player_scores_retyped_keeps_the_rest_of_the_summary(bad):
    zed = _player("Zed", "CHAOS")
    zed["scores"] = bad
    out = _summary(_frame(allPlayers=[_player("Me", "ORDER", kills=1), zed]))
    assert out.get("champion") == "Me"
    assert [p["creep_score"] for p in out.get("players", [])] == [50, 0]


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_events_retyped_degrades_every_event_list(bad):
    out = _summary(_frame(events=bad))
    for key in ("inhib_events", "minion_events", "turret_events",
                "objective_events", "minion_spawn_events"):
        assert out.get(key) == []
    assert out.get("game_time_s") == 600


def test_well_formed_frame_unchanged():
    out = _summary(_frame())
    assert out["game_time_s"] == 600
    assert out["gold"] == 1200
    assert out["hp"] == 800
    assert out["kda"] == "2/0/2"
    assert out["enemy_team"] == ["Zed"]
    assert out["ally_team"] == ["Me"]
    assert out["owned_item_ids"] == ["3047"]
    assert out["minion_events"] == [{"at_s": 65.0}]
    assert [p["championName"] for p in out["allPlayers"]] == ["Me", "Zed"]

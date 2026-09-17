"""RM-456 (1) - ``liveclient_summary`` numeric fields that are None / "nan".

RM-415 routed the ENVELOPE readers (``activePlayer``, ``championStats``,
``scores``...) through a coercion seam, but the numeric LEAVES under them
were still read with a bare ``int(...)``. ``int(None)`` raises TypeError,
``int("nan")`` and ``int(float("nan"))`` raise ValueError and
``int(float("inf"))`` raises OverflowError; the whole body sits in one outer
``except Exception: return {}``, so ONE bad leaf blanked the ENTIRE summary.

Sites (all in ``dashboard/_liveclient.py``): ``gameData.gameTime``,
``activePlayer.currentGold``, the four ``championStats`` HP / resource
leaves, the six ``stats`` leaves, and ``allPlayers[].scores.creepScore``
(the ``players`` slice). The roster ``_as_int`` caught TypeError/ValueError
but not OverflowError, so an infinite ``level`` / ``kills`` blanked it too.

DEGRADE VALUE is 0, the same default a MISSING leaf already produced.
JS consumer census (web/js), grepped before the change:
  * ``game_time_s``: main.js / map_state.js gate on ``typeof === "number"``;
    next_buy_model.js / objective_gauges.js read ``Number(...)``;
    coach_choices.js ``lc.game_time_s || ...`` - 0 is a number, safe.
  * ``hp_max``: stats_panel.js ``!Number(lc.hp_max)`` HIDES the panel on 0,
    which is the honest render for an unreadable max HP.
  * ``players[].creep_score``: Python-only (``_adaptation_latch``).
No consumer distinguishes 0 from a real zero in a way a None would improve,
and None would fail the ``@property {number}`` contract in state_schema.js.

Valid payloads are unchanged: the seam is ``int()`` with a wider except, so
every value ``int()`` accepted before still maps to the same int.
"""
from __future__ import annotations

import math
import time
from unittest import mock

import pytest

from dashboard import _liveclient

_BAD = [None, "nan", float("nan"), float("inf"), "abc", [1], {"v": 1}]
_BAD_IDS = ["None", "strnan", "floatnan", "inf", "abc", "list", "dict"]


def _player(name, team, creep=50):
    return {"summonerName": name, "championName": name, "team": team,
            "position": "MIDDLE", "level": 9,
            "items": [{"itemID": 3047, "displayName": "Boots"}],
            "scores": {"kills": 1, "deaths": 0, "assists": 1, "creepScore": creep}}


def _frame():
    return {
        "activePlayer": {
            "summonerName": "Me", "level": 9, "currentGold": 1200,
            "championStats": {
                "currentHealth": 800, "maxHealth": 1000,
                "resourceValue": 300, "resourceMax": 400,
                "abilityHaste": 10, "moveSpeed": 345, "armor": 50,
                "magicResist": 40, "attackDamage": 99, "abilityPower": 7,
            },
        },
        "allPlayers": [_player("Me", "ORDER"), _player("Zed", "CHAOS")],
        "gameData": {"gameTime": 600.0, "gameMode": "CLASSIC"},
    }


def _summary(frame):
    from core.liveclient_cache import Snapshot
    snap = Snapshot(data=frame, ts=time.time())
    with mock.patch("core.liveclient_cache.get", return_value=snap):
        return _liveclient.liveclient_summary()


def _assert_rest_intact(out):
    assert out, "one bad numeric leaf blanked the whole summary"
    assert out.get("champion") == "Me"
    assert out.get("enemy_team") == ["Zed"]
    assert out.get("game_mode") == "CLASSIC"


@pytest.mark.parametrize("bad", _BAD, ids=_BAD_IDS)
def test_game_time_bad_degrades_that_field_only(bad):
    f = _frame()
    f["gameData"]["gameTime"] = bad
    out = _summary(f)
    _assert_rest_intact(out)
    assert out["game_time_s"] == 0
    assert out["game_time"] == "0:00"
    assert out["gold"] == 1200


@pytest.mark.parametrize("bad", _BAD, ids=_BAD_IDS)
def test_current_gold_bad_degrades_that_field_only(bad):
    f = _frame()
    f["activePlayer"]["currentGold"] = bad
    out = _summary(f)
    _assert_rest_intact(out)
    assert out["gold"] == 0
    assert out["game_time_s"] == 600


_CS_FIELDS = [("currentHealth", "hp"), ("maxHealth", "hp_max"),
              ("resourceValue", "mana"), ("resourceMax", "mana_max")]


@pytest.mark.parametrize("src,dst", _CS_FIELDS, ids=[d for _, d in _CS_FIELDS])
@pytest.mark.parametrize("bad", _BAD, ids=_BAD_IDS)
def test_champion_stat_bad_degrades_that_field_only(bad, src, dst):
    f = _frame()
    f["activePlayer"]["championStats"][src] = bad
    out = _summary(f)
    _assert_rest_intact(out)
    assert out[dst] == 0
    others = {"hp": 800, "hp_max": 1000, "mana": 300, "mana_max": 400}
    del others[dst]
    assert {k: out[k] for k in others} == others


_STAT_FIELDS = [("abilityHaste", "ability_haste"), ("moveSpeed", "move_speed"),
                ("armor", "armor"), ("magicResist", "magic_resist"),
                ("attackDamage", "attack_damage"), ("abilityPower", "ability_power")]


@pytest.mark.parametrize("src,dst", _STAT_FIELDS, ids=[d for _, d in _STAT_FIELDS])
@pytest.mark.parametrize("bad", _BAD, ids=_BAD_IDS)
def test_stats_leaf_bad_degrades_that_field_only(bad, src, dst):
    f = _frame()
    f["activePlayer"]["championStats"][src] = bad
    out = _summary(f)
    _assert_rest_intact(out)
    assert out["stats"][dst] == 0
    assert out["hp"] == 800


@pytest.mark.parametrize("bad", _BAD, ids=_BAD_IDS)
def test_creep_score_bad_degrades_that_player_row_only(bad):
    f = _frame()
    f["allPlayers"][1]["scores"]["creepScore"] = bad
    out = _summary(f)
    _assert_rest_intact(out)
    assert [p["creep_score"] for p in out["players"]] == [50, 0]


@pytest.mark.parametrize("field", ["level", "kills"])
def test_roster_infinite_value_does_not_blank_the_summary(field):
    f = _frame()
    if field == "level":
        f["allPlayers"][1]["level"] = float("inf")
    else:
        f["allPlayers"][1]["scores"]["kills"] = float("inf")
    out = _summary(f)
    _assert_rest_intact(out)
    zed = out["allPlayers"][1]
    assert (zed["level"] if field == "level" else zed["scores"]["kills"]) == 0


@pytest.mark.parametrize("v", [0, 7, 600.9, -3.5, "12", True, False, 1e6])
def test_seam_matches_int_for_every_value_int_accepted(v):
    assert _liveclient._int_or_zero(v) == int(v)


@pytest.mark.parametrize("v", [None, "nan", "12.5", float("nan"), float("inf"),
                               -math.inf, [1], {}])
def test_seam_degrades_to_zero_where_int_raised(v):
    assert _liveclient._int_or_zero(v) == 0


def test_well_formed_frame_unchanged():
    out = _summary(_frame())
    assert (out["game_time_s"], out["game_time"], out["gold"]) == (600, "10:00", 1200)
    assert (out["hp"], out["hp_max"], out["mana"], out["mana_max"]) == (800, 1000, 300, 400)
    assert out["stats"] == {"ability_haste": 10, "move_speed": 345, "armor": 50,
                            "magic_resist": 40, "attack_damage": 99,
                            "ability_power": 7, "resource_type": ""}
    assert [p["creep_score"] for p in out["players"]] == [50, 50]

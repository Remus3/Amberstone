"""RM-456 (2) - ``_resolve_my_champion`` name fields that are not strings.

``core.enemy_aware_stats.active_player_team`` (which this helper says it
MIRRORS) routes both name reads through ``_as_str`` and skips an empty
roster name. ``_resolve_my_champion`` did neither, so an int
``riotIdGameName`` / ``summonerName`` raised AttributeError at
``me_name.startswith`` or TypeError at ``rid + "#"``. Its caller
``_capgap_shadow_eval`` catches and logs at DEBUG, so the fault DEGRADED
rather than crashed - the tests assert the answer is reached without the
raise (called directly, no except in the path).

Also mirrored: an empty roster name is skipped. Without it an active player
named "#tag" matched the first nameless roster row (``"" == "#tag".split``).

JS consumers: none. ``_resolve_my_champion`` feeds only the default-OFF
capability-gap shadow log; it is not emitted in /api/state.
"""
from __future__ import annotations

import pytest

from dashboard import routes_state as rs

_NON_STR = [5, 1.5, True, ["Me"], {"n": "Me"}]
_NON_STR_IDS = ["int", "float", "bool", "list", "dict"]


def _data(ap, players):
    return {"activePlayer": ap, "allPlayers": players}


@pytest.mark.parametrize("bad", _NON_STR, ids=_NON_STR_IDS)
def test_non_string_active_name_returns_empty_without_raising(bad):
    data = _data({"riotIdGameName": bad},
                 [{"riotIdGameName": "Me", "championName": "Ashe"}])
    assert rs._resolve_my_champion(data) == ""


@pytest.mark.parametrize("bad", _NON_STR, ids=_NON_STR_IDS)
def test_non_string_roster_name_is_skipped_not_raised(bad):
    data = _data({"summonerName": "Me"},
                 [{"riotIdGameName": bad, "championName": "Zed"},
                  {"riotIdGameName": "Me", "championName": "Ashe"}])
    assert rs._resolve_my_champion(data) == "Ashe"


@pytest.mark.parametrize("bad", _NON_STR, ids=_NON_STR_IDS)
def test_non_string_champion_name_returns_empty(bad):
    data = _data({"summonerName": "Me"},
                 [{"summonerName": "Me", "championName": bad}])
    assert rs._resolve_my_champion(data) == ""


def test_empty_roster_name_does_not_match_a_tag_only_active_name():
    data = _data({"summonerName": "#NA1"},
                 [{"riotIdGameName": "", "championName": "Zed"}])
    assert rs._resolve_my_champion(data) == ""


def test_agrees_with_active_player_team_on_the_same_name_rules():
    from core.enemy_aware_stats import active_player_team
    data = _data({"summonerName": 5, "riotIdGameName": "Me"},
                 [{"riotIdGameName": "Me", "championName": "Ashe", "team": "ORDER"}])
    # active_player_team reads ``summonerName or riotIdGameName`` THEN coerces,
    # so a truthy non-string summonerName yields no name at all; mirror it.
    assert active_player_team(data) is None
    assert rs._resolve_my_champion(data) == ""


def test_well_formed_matches_unchanged():
    assert rs._resolve_my_champion(_data(
        {"summonerName": "Me#NA1"},
        [{"riotIdGameName": "Zed", "championName": "Zed"},
         {"riotIdGameName": "Me", "championName": "Ashe"}])) == "Ashe"
    assert rs._resolve_my_champion(_data(
        {"riotIdGameName": "Me"},
        [{"summonerName": "Me", "championName": "Lux"}])) == "Lux"
    assert rs._resolve_my_champion(_data(
        {"summonerName": "Me"},
        [{"summonerName": "Me#EUW", "championName": "Ahri"}])) == ""

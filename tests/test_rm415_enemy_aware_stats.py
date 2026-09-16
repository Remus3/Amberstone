"""RM-415 - core/enemy_aware_stats.py live-client envelope readers.

The unguarded ``envelope.get(k) or {}`` / ``or []`` idiom defends against a
MISSING key and not against a RETYPED one: a truthy non-container (``True``,
``5``, a string) is forwarded unchanged, and the next ``.get()`` or ``for``
raises. ``core/liveclient_cache.py`` validates only the top-level envelope, so
every inner field reaches these readers untouched.

Caller severity (measured, not assumed): both public readers are called from
``dashboard/routes_state.py`` inside a ``try`` that logs at DEBUG and falls
back to the mode/level curve, so a raise here was never a crash - it silently
DISCARDED the live enemy items for that request. The acceptance is therefore
"degraded, not raised": a retyped inner field yields the empty / None result
for that field and leaves the well-formed rest of the frame usable.
"""
from __future__ import annotations

import pytest

from core import enemy_aware_stats as eas

_HOSTILE = [None, "", "nan", "12", True, 5, 1.5]
_HOSTILE_IDS = ["None", "empty", "nan", "strnum", "bool", "int", "float"]


def _me(team: str = "ORDER", **kw) -> dict:
    base = {"summonerName": "Me", "riotIdGameName": "Me", "team": team,
            "items": [{"itemID": 3047, "slot": 0}]}
    base.update(kw)
    return base


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_enemy_items_all_players_retyped_degrades_to_empty(bad):
    assert eas.enemy_items_from_liveclient({"allPlayers": bad}) == []


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_enemy_items_player_items_retyped_degrades_to_empty_list(bad):
    data = {"allPlayers": [{"team": "CHAOS", "items": bad},
                           {"team": "CHAOS", "items": [{"itemID": 3075, "slot": 1}]}]}
    assert eas.enemy_items_from_liveclient(data) == [[], [3075]]


@pytest.mark.parametrize("bad", ["", "nan", "abc", True, [6], {"x": 1}],
                         ids=["empty", "nan", "abc", "bool", "list", "dict"])
def test_enemy_items_non_numeric_slot_is_treated_as_unknown(bad):
    # An unparseable slot is "slot unknown", which the reader already treats
    # as a real item (slot None) - never a TypeError from ``bad >= 6``.
    data = {"allPlayers": [{"team": "CHAOS",
                            "items": [{"itemID": 3047, "slot": bad}]}]}
    assert eas.enemy_items_from_liveclient(data) == [[3047]]


def test_enemy_items_string_numeric_slot_still_filters_the_trinket():
    data = {"allPlayers": [{"team": "CHAOS",
                            "items": [{"itemID": 3340, "slot": "6"},
                                      {"itemID": 3047, "slot": "0"}]}]}
    assert eas.enemy_items_from_liveclient(data) == [[3047]]


def test_enemy_items_well_formed_frame_unchanged():
    data = {"allPlayers": [
        _me(),
        {"team": "CHAOS", "items": [{"itemID": 3047, "slot": 0},
                                    {"itemID": 3340, "slot": 6},
                                    {"itemID": "3075", "slot": 2}]},
    ]}
    assert eas.enemy_items_from_liveclient(data, exclude_team="ORDER") == [[3047, 3075]]


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_active_player_team_active_player_retyped_returns_none(bad):
    assert eas.active_player_team({"activePlayer": bad,
                                   "allPlayers": [_me()]}) is None


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_active_player_team_all_players_retyped_returns_none(bad):
    assert eas.active_player_team({"activePlayer": {"summonerName": "Me"},
                                   "allPlayers": bad}) is None


@pytest.mark.parametrize("bad", [True, 5, 1.5, ["Me"], {"n": "Me"}],
                         ids=["bool", "int", "float", "list", "dict"])
def test_active_player_team_name_retyped_returns_none(bad):
    assert eas.active_player_team({"activePlayer": {"summonerName": bad},
                                   "allPlayers": [_me()]}) is None


@pytest.mark.parametrize("bad", [True, 5, ["Me"]], ids=["bool", "int", "list"])
def test_active_player_team_roster_name_retyped_is_skipped(bad):
    data = {"activePlayer": {"summonerName": "Me"},
            "allPlayers": [{"riotIdGameName": bad, "team": "CHAOS"}, _me()]}
    assert eas.active_player_team(data) == "ORDER"


def test_active_player_team_well_formed_frame_unchanged():
    data = {"activePlayer": {"summonerName": "Me#EUW"},
            "allPlayers": [{"riotIdGameName": "Other", "team": "ORDER"},
                           _me(team="CHAOS")]}
    assert eas.active_player_team(data) == "CHAOS"

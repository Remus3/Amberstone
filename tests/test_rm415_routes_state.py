"""RM-415 - dashboard/routes_state.py ``allPlayers or []`` readers.

Four readers iterate ``liveclient_data.get("allPlayers") or []`` and then
``isinstance``-filter each entry. The per-entry filter tolerates a retyped
STRING (it iterates characters, all filtered) but a retyped non-iterable
(``True``, ``5``, ``1.5``) raised ``TypeError`` at the ``for``.

Caller severity (measured per site):
  * ``_resolve_my_champion`` and ``_enemy_champions_for_target`` have no
    ``try`` of their own - they raise to their callers;
  * those callers (``_capgap_shadow_eval``, ``_resolve_ds_target_stats``) and
    ``_resolve_enemy_champions`` all catch and log at DEBUG, so the raise
    never 500'd a route - it silently threw away the live answer and took the
    fallback path. The tests below assert the degraded answer is produced
    WITHOUT passing through that except (no DEBUG fault line).
"""
from __future__ import annotations

import logging
import time
from unittest import mock

import pytest

from dashboard import routes_state as rs

_HOSTILE = [None, "", "nan", "12", True, 5, 1.5]
_HOSTILE_IDS = ["None", "empty", "nan", "strnum", "bool", "int", "float"]


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_resolve_my_champion_all_players_retyped_returns_empty(bad):
    data = {"activePlayer": {"summonerName": "Me"}, "allPlayers": bad}
    assert rs._resolve_my_champion(data) == ""


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_enemy_champions_for_target_all_players_retyped_returns_empty(bad):
    assert rs._enemy_champions_for_target({"allPlayers": bad}, "ORDER") == []


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_resolve_enemy_champions_degrades_without_hitting_the_except(bad, caplog):
    from core.liveclient_cache import Snapshot
    snap = Snapshot(data={"allPlayers": bad}, ts=time.time())
    caplog.set_level(logging.DEBUG, logger=rs.log.name)
    with mock.patch("core.liveclient_cache.get", return_value=snap), \
         mock.patch("core.enemy_aware_stats.active_player_team", return_value="ORDER"):
        assert rs._resolve_enemy_champions({}) == []
    assert not [r for r in caplog.records
                if "_resolve_enemy_champions" in r.getMessage()]


@pytest.mark.parametrize("bad", _HOSTILE, ids=_HOSTILE_IDS)
def test_capgap_shadow_eval_degrades_without_hitting_the_except(bad, caplog):
    caplog.set_level(logging.DEBUG, logger=rs.log.name)
    with mock.patch.object(rs, "_resolve_my_champion", return_value="Ashe"), \
         mock.patch("core.enemy_aware_stats.active_player_team", return_value="ORDER"), \
         mock.patch("core.ds_capability_gap.build_capability_gap",
                    return_value={"applies": False}) as gap:
        assert rs._capgap_shadow_eval({"allPlayers": bad}) is None
    assert gap.call_args.args[1] == []
    assert not [r for r in caplog.records if "capgap-shadow" in r.getMessage()]


def test_well_formed_rosters_unchanged():
    data = {"activePlayer": {"summonerName": "Me"},
            "allPlayers": [
                {"summonerName": "Me", "championName": "Ashe", "team": "ORDER"},
                "junk",
                {"summonerName": "E1", "championName": "Zed", "team": "CHAOS"},
                {"summonerName": "E2", "team": "CHAOS"},
            ]}
    assert rs._resolve_my_champion(data) == "Ashe"
    assert rs._enemy_champions_for_target(data, "ORDER") == ["Zed", ""]

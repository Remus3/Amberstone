"""RC2 RM-03 E12 lever L3 - byte-identity between the agent's capture_state
and the extracted lcu/snapshot_shape.shape_snapshot.

The whole LCU snapshot assembly moved out of tools/lcu_agent.capture_state()
into lcu/snapshot_shape.shape_snapshot so the dashboard can build the same
payload from an in-process LcuClient (DEFAULT-OFF, RC_LCU_INPROCESS). This
suite pins that the agent path and the module path produce an IDENTICAL
snapshot (modulo the caller-owned config / lcu_port and the volatile ts
fields) across every phase the operator hits: Offline, Lobby, ChampSelect
SR-draft, ChampSelect ARAM-Mayhem (queue 2400 / KIWI), and InProgress. If the
extraction ever drifts, the champ_select the dashboard renders would drift
with it - this is the guard.

All authored content here is 7-bit ASCII.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

import lcu_agent as agent  # noqa: E402
from lcu.snapshot_shape import (  # noqa: E402
    _reset_mastery_cache_for_tests,
    _reset_summoner_lookup_cache_for_tests,
    shape_snapshot,
)

_PHASE_PATH = "/lol-gameflow/v1/gameflow-phase"
_SESSION_PATH = "/lol-champ-select/v1/session"
_GAMEFLOW_PATH = "/lol-gameflow/v1/session"


def _fake_request(routes: dict):
    """Agent transport contract: (method, path, body=None) -> (payload, err).

    Unknown paths answer (None, "404") exactly like LCU does for a resource
    that is not live in the current phase.
    """
    def _req(method, path, body=None):
        if path in routes:
            return routes[path], None
        return None, "404"
    return _req


def _reset_caches() -> None:
    _reset_mastery_cache_for_tests()
    _reset_summoner_lookup_cache_for_tests()


def _drive_agent(routes: dict, *, connected: bool = True) -> dict:
    """Run tools/lcu_agent.capture_state() against a fake transport."""
    _reset_caches()
    fake = _fake_request(routes)
    with mock.patch.object(agent, "ensure_lcu_conn", return_value=connected), \
            mock.patch.object(agent, "lcu_request", new=fake):
        agent._lcu["port"] = 1234
        try:
            return agent.capture_state()
        finally:
            agent._lcu["port"] = 0


def _drive_module(routes: dict) -> dict:
    """Run lcu/snapshot_shape.shape_snapshot against the same fake transport."""
    _reset_caches()
    return shape_snapshot(_fake_request(routes), dict(agent.CONFIG))


def _comparable(state: dict) -> dict:
    """Strip the caller-owned (config / lcu_port) + volatile (ts) fields so two
    snapshots can be compared for structural byte-identity."""
    out = {k: v for k, v in state.items()
           if k not in ("config", "lcu_port", "ts")}
    if isinstance(out.get("cs_debug"), dict):
        out["cs_debug"] = {k: v for k, v in out["cs_debug"].items()
                           if k != "ts"}
    return out


def _sr_draft_session() -> dict:
    return {
        "localPlayerCellId": 2,
        "benchChampions": [],
        "timer": {"phase": "BAN_PICK", "adjustedTimeLeftInPhase": 26000},
        "gameData": {"queue": {"id": 420, "mapId": 11, "gameMode": "CLASSIC",
                               "type": "CLASSIC", "category": "PvP"}},
        "myTeam": [
            {"cellId": 2, "championId": 67, "championPickIntent": 0,
             "summonerId": 55, "summonerInternalName": "moonbeam",
             "puuid": "puuid-me", "assignedPosition": "bottom",
             "spell1Id": 4, "spell2Id": 7},
            {"cellId": 3, "championId": 0, "championPickIntent": 412,
             "summonerId": 56, "displayName": "Ally Two",
             "puuid": "puuid-ally", "assignedPosition": "utility",
             "spell1Id": 4, "spell2Id": 14},
        ],
        "theirTeam": [
            {"cellId": 7, "championId": 122, "summonerId": 90,
             "puuid": "", "assignedPosition": "top",
             "spell1Id": 4, "spell2Id": 12},
        ],
        "trades": [{"id": 1, "cellId": 3, "state": "AVAILABLE"}],
        "positionSwaps": [{"id": 9, "cellId": 3, "state": "AVAILABLE"}],
        "pickOrderSwaps": [{"id": 11, "cellId": 4, "state": "SENT"}],
        "actions": [
            [{"actorCellId": 2, "type": "ban", "championId": 84,
              "completed": True, "isInProgress": False}],
            [{"actorCellId": 2, "type": "pick", "championId": 67,
              "completed": True, "isInProgress": False},
             {"actorCellId": 3, "type": "pick", "championId": 0,
              "completed": False, "isInProgress": True}],
        ],
    }


def _aram_mayhem_session() -> dict:
    return {
        "localPlayerCellId": 0,
        "benchChampions": [{"championId": 21}, {"championId": 76},
                           "junk", {"championId": 143}],
        "timer": {"phase": "GAME_STARTING"},
        "gameData": {"queue": {"id": 2400, "mapId": 12, "gameMode": "KIWI",
                               "type": "ARAM", "category": "PvP"}},
        "myTeam": [{"cellId": 0, "championId": 43, "summonerId": 55,
                    "summonerInternalName": "moonbeam", "puuid": "puuid-me",
                    "spell1Id": 4, "spell2Id": 32}],
        "theirTeam": [],
        "trades": [],
        "positionSwaps": [],
        "pickOrderSwaps": [],
        "actions": [],
    }


def _lobby_payload() -> dict:
    return {
        "gameConfig": {"queueId": 420, "gameMode": "CLASSIC", "mapId": 11,
                       "isCustom": False, "maxLobbySize": 5},
        "partyId": "party-xyz",
        "partyType": "open",
        "canStartActivity": True,
        "members": [
            {"puuid": "self-puuid", "summonerId": 1, "gameName": "SamplePlayer",
             "tagLine": "Trist", "isLeader": True, "summonerLevel": 487,
             "firstPositionPreference": "BOTTOM",
             "secondPositionPreference": "MIDDLE"},
            {"puuid": "fren-puuid", "summonerId": 2, "gameName": "Fren",
             "tagLine": "NA1", "isLeader": False, "summonerLevel": 200,
             "firstPositionPreference": "JUNGLE",
             "secondPositionPreference": "FILL"},
        ],
    }


class TestOfflineAgentPathPreserved(unittest.TestCase):
    """The Offline early-return is agent-owned (transport bit) and must NOT
    delegate - capture_state short-circuits before shape_snapshot."""

    def test_offline_shape_unchanged(self):
        _reset_caches()
        with mock.patch.object(agent, "ensure_lcu_conn", return_value=False):
            st = agent.capture_state()
        self.assertEqual(st["phase"], "Offline")
        self.assertIn("config", st)
        self.assertIn("ts", st)
        self.assertNotIn("champ_select", st)
        self.assertNotIn("lcu_port", st)
        self.assertNotIn("cs_debug", st)


class TestChampSelectParity(unittest.TestCase):
    def _assert_cs_parity(self, session):
        routes = {_PHASE_PATH: '"ChampSelect"', _SESSION_PATH: session}
        a = _drive_agent(routes)
        m = _drive_module(routes)
        # The champ_select the dashboard renders must be byte-identical.
        self.assertEqual(a["champ_select"], m["champ_select"])
        self.assertEqual(list(a["champ_select"]), list(m["champ_select"]))
        # ... and so must the entire snapshot modulo caller-owned + volatile.
        self.assertEqual(_comparable(a), _comparable(m))

    def test_sr_draft_parity(self):
        self._assert_cs_parity(_sr_draft_session())

    def test_aram_mayhem_parity(self):
        self._assert_cs_parity(_aram_mayhem_session())

    def test_aram_mayhem_is_aram_true(self):
        # Pins the pre-refactor shape: queue 2400 (KIWI) reads is_aram True,
        # bench forwarded, so the dashboard bench / quick-swap UI renders.
        routes = {_PHASE_PATH: '"ChampSelect"',
                  _SESSION_PATH: _aram_mayhem_session()}
        cs = _drive_module(routes)["champ_select"]
        self.assertTrue(cs["is_aram"])
        self.assertEqual(cs["queue_id"], 2400)
        self.assertEqual(cs["bench"], [21, 76, 143])
        self.assertEqual(cs["my_champion"], 43)


class TestLobbyParity(unittest.TestCase):
    def test_lobby_snapshot_parity(self):
        routes = {
            _PHASE_PATH: '"Lobby"',
            "/lol-matchmaking/v1/ready-check": {"state": "Invalid",
                                                "playerResponse": "None",
                                                "timer": 0},
            "/lol-lobby/v2/lobby": _lobby_payload(),
            "/lol-matchmaking/v1/search": {"searchState": "Invalid"},
            "/lol-summoner/v1/current-summoner": {"summonerId": 1},
        }
        a = _drive_agent(routes)
        m = _drive_module(routes)
        self.assertEqual(a["phase"], "Lobby")
        self.assertEqual(a.get("lobby"), m.get("lobby"))
        self.assertEqual(a.get("ready_check"), m.get("ready_check"))
        self.assertEqual(_comparable(a), _comparable(m))
        # The forwarded member shape survived the move (riot_id composed).
        self.assertEqual(m["lobby"]["members"][0]["riot_id"], "SamplePlayer#Trist")
        self.assertTrue(m["lobby"]["local_member"]["is_self"])


class TestInProgressParity(unittest.TestCase):
    def test_in_progress_game_id_and_augment_parity(self):
        routes = {
            _PHASE_PATH: '"InProgress"',
            _GAMEFLOW_PATH: {"gameData": {"gameId": 123456,
                                          "queue": {"id": 2400}}},
        }
        a = _drive_agent(routes)
        m = _drive_module(routes)
        self.assertEqual(a["phase"], "InProgress")
        self.assertEqual(a.get("game_id"), m.get("game_id"))
        self.assertEqual(a["game_id"], "123456")
        # Non-Arena queue -> the cherry-augment probe stays False in both.
        self.assertFalse(a["cherry_augment_open"])
        self.assertEqual(a["cherry_augment_open"], m["cherry_augment_open"])
        self.assertNotIn("champ_select", a)
        self.assertEqual(_comparable(a), _comparable(m))


if __name__ == "__main__":
    unittest.main()

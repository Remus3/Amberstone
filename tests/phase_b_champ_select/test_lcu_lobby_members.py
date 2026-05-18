"""s170 (2026-05-11) — LCU lobby members forwarder + lobby field expansion.

Validates the new gamepc_lcu_agent path that forwards:
  /lol-lobby/v2/lobby → state["lobby"].members[], local_member, is_leader,
                       party_type, queue_name
  /lol-matchmaking/v1/search → state["lobby"].search_state

The dashboard's view-lobby panel (_lobbyViewRefresh + _renderTop8 in
web/js/main.js) consumes these fields; before s170 they ran on placeholders.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

import gamepc_lcu_agent as agent  # noqa: E402


def _patch_lcu(responses):
    """Map (method, path) → response. Same helper pattern as
    test_lcu_mastery.py — unknown paths return (None, "unmocked").
    """
    def side(method, path, body=None):
        key = (method, path)
        if key not in responses:
            return (None, "unmocked")
        v = responses[key]
        if isinstance(v, BaseException):
            raise v
        if isinstance(v, tuple) and len(v) == 2:
            return v
        return (v, None)
    return side


class TestLocalSummonerIdMatching(unittest.TestCase):
    """s170.1 — is_self via summoner-id match (LCU isLocalMember unreliable
    on current builds).
    """

    def test_id_match_sets_is_self(self):
        raw = {"summonerId": 12345, "gameName": "Me", "tagLine": "NA1"}
        m = agent._slim_lobby_member(raw, local_summoner_id=12345)
        self.assertTrue(m["is_self"])

    def test_id_mismatch_clears_is_self(self):
        raw = {"summonerId": 12345, "isLocalMember": True,
               "gameName": "Other", "tagLine": "NA1"}
        # Even though LCU said isLocalMember=True, the id mismatch wins.
        m = agent._slim_lobby_member(raw, local_summoner_id=99999)
        self.assertFalse(m["is_self"])

    def test_no_local_id_falls_back_to_islocalmember(self):
        raw = {"summonerId": 12345, "isLocalMember": True,
               "gameName": "Me", "tagLine": "NA1"}
        # local_summoner_id=None → use LCU field.
        m = agent._slim_lobby_member(raw, local_summoner_id=None)
        self.assertTrue(m["is_self"])

    def test_zero_sid_doesnt_match_anything(self):
        raw = {"summonerId": 0, "isLocalMember": False}
        m = agent._slim_lobby_member(raw, local_summoner_id=12345)
        self.assertFalse(m["is_self"])


class TestNameEnrichment(unittest.TestCase):
    """s170.1 — current LCU builds frequently emit empty gameName/tagLine
    on /lol-lobby/v2/lobby members. Enrich by per-summoner lookup.
    """

    def setUp(self):
        agent._reset_summoner_lookup_cache_for_tests()

    def tearDown(self):
        agent._reset_summoner_lookup_cache_for_tests()

    def test_enrich_fills_missing_names(self):
        responses = {
            ("GET", "/lol-summoner/v1/summoners/12345"): {
                "gameName": "SamplePlayer", "tagLine": "Vayne",
                "displayName": "SamplePlayer", "summonerLevel": 487,
            },
        }
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(responses)):
            raw = {"summonerId": 12345, "puuid": "p1"}
            m = agent._slim_lobby_member(raw, enrich=True)
        self.assertEqual(m["game_name"], "SamplePlayer")
        self.assertEqual(m["tag_line"], "Vayne")
        self.assertEqual(m["riot_id"], "SamplePlayer#Vayne")
        self.assertEqual(m["summoner_level"], 487)

    def test_enrich_no_op_when_names_already_present(self):
        # If LCU already emits names on the lobby member, don't fetch.
        responses = {
            ("GET", "/lol-summoner/v1/summoners/12345"): {
                "gameName": "WRONG", "tagLine": "WRONG",
            },
        }
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(responses)) as m_lcu:
            raw = {"summonerId": 12345, "gameName": "Real",
                   "tagLine": "NA1", "summonerLevel": 100}
            m = agent._slim_lobby_member(raw, enrich=True)
        # No lookup made.
        self.assertEqual(m_lcu.call_count, 0)
        self.assertEqual(m["game_name"], "Real")
        self.assertEqual(m["tag_line"], "NA1")

    def test_enrich_off_by_default(self):
        # Backwards-compat: enrich defaults to False so pure unit tests
        # of _slim_lobby_member don't accidentally fire LCU calls.
        with mock.patch.object(agent, "lcu_request",
                               side_effect=AssertionError("should not call")):
            raw = {"summonerId": 12345}
            m = agent._slim_lobby_member(raw)  # no enrich kwarg
        self.assertEqual(m["game_name"], "")

    def test_enrich_silent_on_lookup_failure(self):
        responses = {
            ("GET", "/lol-summoner/v1/summoners/12345"): (None, "http 500"),
        }
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(responses)):
            raw = {"summonerId": 12345, "puuid": "p1"}
            m = agent._slim_lobby_member(raw, enrich=True)
        # No crash; names stay empty.
        self.assertEqual(m["game_name"], "")
        self.assertEqual(m["tag_line"], "")

    def test_enrich_caches_lookup(self):
        responses = {
            ("GET", "/lol-summoner/v1/summoners/12345"): {
                "gameName": "Cached", "tagLine": "X",
            },
        }
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(responses)) as m_lcu:
            raw = {"summonerId": 12345}
            agent._slim_lobby_member(raw, enrich=True)
            agent._slim_lobby_member(raw, enrich=True)
        # Second call hits cache.
        self.assertEqual(m_lcu.call_count, 1)


class TestSlimLobbyMember(unittest.TestCase):
    def test_full_member_shape(self):
        raw = {
            "puuid": "abc123",
            "summonerId": 12345,
            "summonerName": "Moonbeam",
            "gameName": "SamplePlayer",
            "tagLine": "Vayne",
            "isLeader": True,
            "isLocalMember": True,
            "isOwner": True,
            "summonerLevel": 487,
            "ready": False,
            "firstPositionPreference": "BOTTOM",
            "secondPositionPreference": "MIDDLE",
        }
        m = agent._slim_lobby_member(raw)
        self.assertEqual(m["puuid"], "abc123")
        self.assertEqual(m["summoner_id"], 12345)
        self.assertEqual(m["riot_id"], "SamplePlayer#Vayne")
        self.assertEqual(m["game_name"], "SamplePlayer")
        self.assertEqual(m["tag_line"], "Vayne")
        self.assertTrue(m["is_leader"])
        self.assertTrue(m["is_self"])
        self.assertTrue(m["is_owner"])
        self.assertEqual(m["summoner_level"], 487)
        self.assertEqual(m["position_preferences"]["first_preference"], "BOTTOM")
        self.assertEqual(m["position_preferences"]["second_preference"], "MIDDLE")

    def test_falls_back_to_summoner_name_when_riot_id_missing(self):
        # Older LCU builds (or unreached friends) lack gameName/tagLine.
        raw = {"summonerName": "LegacyName", "summonerId": 1}
        m = agent._slim_lobby_member(raw)
        self.assertEqual(m["riot_id"], "LegacyName")
        self.assertEqual(m["game_name"], "")
        self.assertEqual(m["tag_line"], "")

    def test_defaults_when_fields_absent(self):
        m = agent._slim_lobby_member({})
        self.assertEqual(m["puuid"], "")
        self.assertEqual(m["summoner_id"], 0)
        self.assertEqual(m["summoner_level"], 0)
        self.assertFalse(m["is_leader"])
        self.assertFalse(m["is_self"])
        self.assertEqual(m["position_preferences"]["first_preference"], "UNSELECTED")
        self.assertEqual(m["position_preferences"]["second_preference"], "UNSELECTED")

    def test_returns_none_for_non_dict(self):
        self.assertIsNone(agent._slim_lobby_member(None))
        self.assertIsNone(agent._slim_lobby_member("not-a-dict"))
        self.assertIsNone(agent._slim_lobby_member(42))

    def test_position_preference_uppercased(self):
        # LCU sometimes emits lowercase ("top") — view-lobby's _renderLanePref
        # expects upper. Normalize at the agent boundary.
        raw = {"firstPositionPreference": "top", "secondPositionPreference": "jungle"}
        m = agent._slim_lobby_member(raw)
        self.assertEqual(m["position_preferences"]["first_preference"], "TOP")
        self.assertEqual(m["position_preferences"]["second_preference"], "JUNGLE")

    def test_invalid_summoner_id_falls_to_zero(self):
        # Belt and braces — if LCU ever returns a string here, don't crash.
        raw = {"summonerId": "not-an-int"}
        m = agent._slim_lobby_member(raw)
        self.assertEqual(m["summoner_id"], 0)


class TestDeriveSearchState(unittest.TestCase):
    def test_searching_from_payload(self):
        self.assertEqual(
            agent._derive_search_state("Lobby", {"searchState": "Searching"}),
            "Searching",
        )

    def test_awaiting_match_treated_as_searching(self):
        # LCU emits AwaitingMatch in a sub-state right before ready-check pops.
        self.assertEqual(
            agent._derive_search_state("Lobby", {"searchState": "AwaitingMatch"}),
            "Searching",
        )

    def test_found_state(self):
        self.assertEqual(
            agent._derive_search_state("ReadyCheck", {"searchState": "Found"}),
            "MatchFound",
        )

    def test_falls_back_to_phase_mapping(self):
        self.assertEqual(agent._derive_search_state("Matchmaking", None), "Searching")
        self.assertEqual(agent._derive_search_state("ReadyCheck", None), "MatchFound")
        self.assertEqual(agent._derive_search_state("Lobby", None), "Idle")
        self.assertEqual(agent._derive_search_state("ChampSelect", None), "Idle")

    def test_ignores_garbage_payload(self):
        # Non-dict / unexpected shape → fall back to phase mapping.
        self.assertEqual(agent._derive_search_state("Lobby", "garbage"), "Idle")
        self.assertEqual(agent._derive_search_state("Matchmaking", []), "Searching")

    def test_payload_with_unknown_state_falls_to_phase(self):
        self.assertEqual(
            agent._derive_search_state("Lobby", {"searchState": "Unknown"}),
            "Idle",
        )


class TestQueueNameMap(unittest.TestCase):
    def test_known_queues(self):
        self.assertEqual(agent._LOBBY_QUEUE_NAMES[420], "Ranked Solo/Duo")
        self.assertEqual(agent._LOBBY_QUEUE_NAMES[450], "ARAM")
        self.assertEqual(agent._LOBBY_QUEUE_NAMES[1700], "Arena")
        # s234 (#89): ARAM Mayhem is queue 2400 (KIWI gameMode, confirmed
        # s220 / item 87) — NOT 920. 920 is Legend of the Poro King; the
        # old map labelled 920 "ARAM Mayhem", which is why the lobby
        # "change mode" picker couldn't switch into Mayhem.
        self.assertEqual(agent._LOBBY_QUEUE_NAMES[2400], "ARAM Mayhem")
        self.assertEqual(agent._LOBBY_QUEUE_NAMES[920], "Poro King")
        # s234 (#89): Brawl (2300) retired from the live rotation (s214) —
        # the lobby-side name-map residue is removed.
        self.assertNotIn(2300, agent._LOBBY_QUEUE_NAMES)

    def test_unknown_queue_returns_empty(self):
        # Caller uses dict.get(qid, "") — dashboard falls back to "queue N".
        self.assertEqual(agent._LOBBY_QUEUE_NAMES.get(99999, ""), "")


class TestCaptureStateLobby(unittest.TestCase):
    """End-to-end: capture_state() in Lobby phase populates state["lobby"]
    with the full member shape.
    """

    def setUp(self):
        agent._reset_mastery_cache_for_tests()
        self._ensure_patch = mock.patch.object(
            agent, "ensure_lcu_conn", return_value=True,
        )
        self._ensure_patch.start()
        agent._lcu["port"] = 1234

    def tearDown(self):
        self._ensure_patch.stop()
        agent._lcu["port"] = 0
        agent._reset_mastery_cache_for_tests()

    def _stub_lobby(self, members=None, search_state=None,
                   party_type="open", is_custom=False, queue_id=420):
        members = members if members is not None else [
            {
                "puuid": "self-puuid",
                "summonerId": 1, "gameName": "SamplePlayer", "tagLine": "Vayne",
                "isLeader": True, "isLocalMember": True, "summonerLevel": 487,
                "firstPositionPreference": "BOTTOM", "secondPositionPreference": "MIDDLE",
            },
            {
                "puuid": "fren-puuid",
                "summonerId": 2, "gameName": "Fren", "tagLine": "NA1",
                "isLeader": False, "isLocalMember": False, "summonerLevel": 200,
                "firstPositionPreference": "JUNGLE", "secondPositionPreference": "FILL",
            },
        ]
        return {
            ("GET", "/lol-gameflow/v1/gameflow-phase"): ('"Lobby"', None),
            ("GET", "/lol-matchmaking/v1/ready-check"): (None, "http 404"),
            ("GET", "/lol-lobby/v2/lobby"): {
                "gameConfig": {
                    "queueId": queue_id, "gameMode": "CLASSIC",
                    "mapId": 11, "isCustom": is_custom,
                },
                "partyId": "party-xyz",
                "partyType": party_type,
                "canStartActivity": True,
                "members": members,
            },
            ("GET", "/lol-matchmaking/v1/search"):
                ({"searchState": search_state} if search_state else (None, "http 404")),
            ("GET", "/lol-summoner/v1/current-summoner"): {"summonerId": 1},
            ("GET", "/lol-champion-mastery/v1/local-player/champion-mastery"): [],
        }

    def test_full_lobby_state_populated(self):
        rs = self._stub_lobby()
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(rs)):
            state = agent.capture_state()
        lobby = state.get("lobby")
        self.assertIsNotNone(lobby)
        self.assertEqual(lobby["queue_id"], 420)
        self.assertEqual(lobby["queue_name"], "Ranked Solo/Duo")
        self.assertEqual(lobby["party_type"], "open")
        self.assertEqual(lobby["party_id"], "party-xyz")
        self.assertTrue(lobby["is_leader"])  # local member is leader
        self.assertEqual(lobby["search_state"], "Idle")  # phase=Lobby, no search payload
        self.assertEqual(len(lobby["members"]), 2)
        self.assertEqual(lobby["members"][0]["riot_id"], "SamplePlayer#Vayne")
        self.assertEqual(lobby["members"][1]["riot_id"], "Fren#NA1")

    def test_local_member_identified(self):
        rs = self._stub_lobby()
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(rs)):
            state = agent.capture_state()
        lm = state["lobby"]["local_member"]
        self.assertIsNotNone(lm)
        self.assertEqual(lm["riot_id"], "SamplePlayer#Vayne")
        self.assertTrue(lm["is_self"])
        self.assertEqual(lm["position_preferences"]["first_preference"], "BOTTOM")
        self.assertEqual(lm["position_preferences"]["second_preference"], "MIDDLE")

    def test_no_local_member_when_id_mismatch(self):
        # s170.1: local_member identified by summonerId match against
        # /lol-summoner/v1/current-summoner. When no member's id matches,
        # local_member is None.
        rs = self._stub_lobby(members=[
            {"summonerId": 999, "gameName": "Other", "tagLine": "NA1",
             "isLocalMember": False, "isLeader": False},
        ])
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(rs)):
            state = agent.capture_state()
        self.assertIsNone(state["lobby"]["local_member"])
        self.assertFalse(state["lobby"]["is_leader"])

    def test_search_state_from_matchmaking_payload(self):
        rs = self._stub_lobby(search_state="Searching")
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(rs)):
            state = agent.capture_state()
        self.assertEqual(state["lobby"]["search_state"], "Searching")

    def test_empty_members_list_safe(self):
        rs = self._stub_lobby(members=[])
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(rs)):
            state = agent.capture_state()
        self.assertEqual(state["lobby"]["members"], [])
        self.assertIsNone(state["lobby"]["local_member"])
        self.assertFalse(state["lobby"]["is_leader"])

    def test_garbage_member_entries_silently_dropped(self):
        # Mix of valid + invalid member entries — the invalid ones must
        # be filtered without crashing capture_state().
        rs = self._stub_lobby(members=[
            None,
            "not-a-dict",
            {"summonerId": 1, "gameName": "OK", "tagLine": "NA1",
             "isLocalMember": True, "isLeader": True},
            42,
        ])
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(rs)):
            state = agent.capture_state()
        self.assertEqual(len(state["lobby"]["members"]), 1)
        self.assertEqual(state["lobby"]["members"][0]["riot_id"], "OK#NA1")

    def test_arena_queue_name(self):
        rs = self._stub_lobby(queue_id=1700)
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(rs)):
            state = agent.capture_state()
        self.assertEqual(state["lobby"]["queue_name"], "Arena")

    def test_unknown_queue_id_empty_name(self):
        # Dashboard falls back to "queue 99999" when queue_name is empty.
        rs = self._stub_lobby(queue_id=99999)
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(rs)):
            state = agent.capture_state()
        self.assertEqual(state["lobby"]["queue_name"], "")
        self.assertEqual(state["lobby"]["queue_id"], 99999)


if __name__ == "__main__":
    unittest.main()

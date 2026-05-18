"""Priority 8 (2026-05-10) - LCU mastery cache + capture_state plumbing.

Validates the new gamepc_lcu_agent path:
  /lol-summoner/v1/current-summoner → summonerId (cached once, surfaced for downstream)
  /lol-champion-mastery/v1/local-player/champion-mastery → mastery map

The transformed payload lives at ``state["lcu"]["mastery"]`` once the agent
sees a session-relevant phase (Lobby / ChampSelect / GameStart / InProgress
/ ReadyCheck / Matchmaking / WaitingForStats). TTL-cached at MASTERY_TTL_S
to avoid hammering LCU during the lobby loop.
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

import gamepc_lcu_agent as agent  # noqa: E402


def _patch_lcu(responses: dict[tuple[str, str], object]):
    """Return a side-effect that maps (method, path) → response.

    ``responses[(method, path)]`` is either:
      * a (payload, err) tuple - returned directly
      * any other object - returned as (obj, None)
      * Exception instance - raised
    Unknown paths return (None, "unmocked").
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


class TestSummonerIdResolver(unittest.TestCase):
    def setUp(self) -> None:
        agent._reset_mastery_cache_for_tests()

    def test_resolves_and_caches(self) -> None:
        responses = {
            ("GET", "/lol-summoner/v1/current-summoner"):
                {"summonerId": 12345, "displayName": "SamplePlayer"},
        }
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(responses)) as m:
            sid1 = agent._resolve_local_summoner_id()
            sid2 = agent._resolve_local_summoner_id()
        self.assertEqual(sid1, 12345)
        self.assertEqual(sid2, 12345)
        # Second call must hit cache - only one LCU GET.
        self.assertEqual(m.call_count, 1)

    def test_returns_none_when_lcu_unreachable(self) -> None:
        responses = {("GET", "/lol-summoner/v1/current-summoner"): (None, "no_lcu")}
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(responses)):
            self.assertIsNone(agent._resolve_local_summoner_id())

    def test_returns_none_when_payload_missing_summoner_id(self) -> None:
        responses = {("GET", "/lol-summoner/v1/current-summoner"):
                     {"displayName": "Anon"}}
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(responses)):
            self.assertIsNone(agent._resolve_local_summoner_id())


class TestMasteryFetch(unittest.TestCase):
    def setUp(self) -> None:
        agent._reset_mastery_cache_for_tests()

    def test_fetch_transforms_payload_to_per_champ_dict(self) -> None:
        sample = [
            {
                "championId": 67,
                "championLevel": 7,
                "championPoints": 250000,
                "championPointsSinceLastLevel": 0,
                "championPointsUntilNextLevel": 0,
                "lastPlayTime": 1735689600000,
                "chestGranted": True,
                "tokensEarned": 0,
            },
            {
                "championId": 222,
                "championLevel": 5,
                "championPoints": 84000,
                "lastPlayTime": 1735000000000,
            },
        ]
        responses = {
            ("GET", "/lol-summoner/v1/current-summoner"): {"summonerId": 42},
            ("GET", "/lol-champion-mastery/v1/local-player/champion-mastery"): sample,
        }
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(responses)):
            out = agent._maybe_refresh_mastery()
        self.assertIsInstance(out, dict)
        self.assertIn(67, out)
        self.assertEqual(out[67]["level"], 7)
        self.assertEqual(out[67]["points"], 250000)
        self.assertEqual(out[67]["last_play_time"], 1735689600000)
        self.assertTrue(out[67]["chest_granted"])
        # Defaulted-zero fields for the trimmed second entry.
        self.assertEqual(out[222]["level"], 5)
        self.assertEqual(out[222]["chest_granted"], False)
        self.assertEqual(out[222]["tokens_earned"], 0)

    def test_ttl_cache_skips_second_lcu_hit(self) -> None:
        responses = {
            ("GET", "/lol-summoner/v1/current-summoner"): {"summonerId": 7},
            ("GET", "/lol-champion-mastery/v1/local-player/champion-mastery"): [
                {"championId": 1, "championLevel": 3, "championPoints": 1000},
            ],
        }
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(responses)) as m:
            agent._maybe_refresh_mastery()
            agent._maybe_refresh_mastery()
        # 1 summoner + 1 mastery - second _maybe_refresh hits cache for both.
        self.assertEqual(m.call_count, 2)

    def test_ttl_expiry_triggers_re_fetch(self) -> None:
        responses = {
            ("GET", "/lol-summoner/v1/current-summoner"): {"summonerId": 7},
            ("GET", "/lol-champion-mastery/v1/local-player/champion-mastery"): [
                {"championId": 1, "championLevel": 3, "championPoints": 1000},
            ],
        }
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(responses)) as m:
            agent._maybe_refresh_mastery()
            agent._mastery_cache["fetched_at"] -= (agent.MASTERY_TTL_S + 1)
            agent._maybe_refresh_mastery()
        # summoner cached → 1 call; mastery refetched → 2 calls. Total 3.
        self.assertEqual(m.call_count, 3)

    def test_returns_none_on_unexpected_payload_shape(self) -> None:
        responses = {
            ("GET", "/lol-summoner/v1/current-summoner"): {"summonerId": 42},
            ("GET", "/lol-champion-mastery/v1/local-player/champion-mastery"):
                {"error": "not a list"},
        }
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(responses)):
            self.assertIsNone(agent._maybe_refresh_mastery())


class TestCaptureStatePlumbing(unittest.TestCase):
    """Smoke-test the mastery hook inside capture_state without driving the
    full ChampSelect plumbing - we only verify that the lcu.mastery key
    appears for session-relevant phases.
    """

    def setUp(self) -> None:
        agent._reset_mastery_cache_for_tests()
        # capture_state() short-circuits on ensure_lcu_conn → True, then
        # walks the phase branches. We stub both with mock.
        self._ensure_patch = mock.patch.object(
            agent, "ensure_lcu_conn", return_value=True,
        )
        self._ensure_patch.start()
        # Pretend the agent connected on port 1234.
        agent._lcu["port"] = 1234

    def tearDown(self) -> None:
        self._ensure_patch.stop()
        agent._lcu["port"] = 0
        agent._reset_mastery_cache_for_tests()

    def _stub_capture_for_phase(self, phase: str, extra: dict | None = None):
        """Build a minimal responses table for capture_state() at ``phase``."""
        rs: dict = {
            ("GET", "/lol-gameflow/v1/gameflow-phase"): (f'"{phase}"', None),
            ("GET", "/lol-summoner/v1/current-summoner"): {"summonerId": 99},
            ("GET", "/lol-champion-mastery/v1/local-player/champion-mastery"): [
                {"championId": 51, "championLevel": 7, "championPoints": 999999,
                 "lastPlayTime": 1700000000000, "chestGranted": True},
            ],
        }
        if extra:
            rs.update(extra)
        return rs

    def test_lobby_phase_publishes_mastery(self) -> None:
        rs = self._stub_capture_for_phase("Lobby", {
            ("GET", "/lol-matchmaking/v1/ready-check"): (None, "http 404"),
            ("GET", "/lol-lobby/v2/lobby"): {"gameConfig": {"queueId": 420}},
        })
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(rs)):
            state = agent.capture_state()
        # 2026-05-11 live-fix: mastery + summoner_id live at the TOP level of
        # the agent's state (Legion's bridge wraps the whole agent state as
        # ``legion_state["lcu"]`` on the dashboard side).
        self.assertEqual(state["phase"], "Lobby")
        self.assertIn("mastery", state)
        self.assertEqual(state["summoner_id"], 99)
        self.assertEqual(state["mastery"][51]["level"], 7)

    def test_champ_select_phase_publishes_mastery(self) -> None:
        rs = self._stub_capture_for_phase("ChampSelect", {
            ("GET", "/lol-champ-select/v1/session"): {
                "localPlayerCellId": 0,
                "myTeam": [], "theirTeam": [],
                "actions": [],
                "timer": {},
                "benchChampions": [],
                "trades": [],
                "gameData": {"queue": {"id": 420}},
            },
        })
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(rs)):
            state = agent.capture_state()
        self.assertEqual(state["phase"], "ChampSelect")
        self.assertEqual(state["mastery"][51]["points"], 999999)

    def test_idle_phase_does_not_call_mastery(self) -> None:
        rs = self._stub_capture_for_phase("None")
        # "None" / "Unknown" should not trigger mastery fetch.
        with mock.patch.object(agent, "lcu_request",
                               side_effect=_patch_lcu(rs)) as m:
            state = agent.capture_state()
        self.assertNotIn("mastery", state)
        self.assertNotIn("summoner_id", state)
        # The phase GET fires; mastery GET does not.
        # Tolerate however many lookups gameflow does, as long as no mastery call.
        paths = [c.args[1] for c in m.call_args_list if len(c.args) >= 2]
        self.assertNotIn("/lol-champion-mastery/v1/local-player/champion-mastery",
                         paths)


if __name__ == "__main__":
    unittest.main()

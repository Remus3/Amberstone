"""FU02 last-mile - Legion-local LCU agent -> /api/team-context/refresh wiring.

Pins the contract for the new helpers added to `tools/lcu_agent.py`:
  - _picks_signature edge-detection
  - _build_team_context_body wire-shape translation
  - _champion_name_for fallback behavior
  - _maybe_refresh_team_context edge-trigger + rate-limit + leave-CS reset
  - post_team_context_refresh no-auth POST (route is local-only since the
    cross-Claude bridge was decommissioned, ADR-012)

The agent runs standalone (Legion-local) and is stdlib-only; tests import via
`sys.path.insert("tools")` since tools/ has no __init__.py.
"""
from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

import lcu_agent as agent  # noqa: E402


def _reset_module_state():
    """Reset the agent's shared mutable state between cases so order
    can't leak."""
    agent._team_context_state.update({
        "last_phase":           None,
        "last_picks_signature": None,
        "last_post_at":         0.0,
    })
    agent._CHAMP_NAME_CACHE.clear()
    agent._CHAMP_NAME_CACHE_LOADED = False


class TestPicksSignature(unittest.TestCase):
    def test_signature_stable_under_reorder(self):
        cs_a = {
            "my_team":    [{"cellId": 0, "championId": 1},
                           {"cellId": 1, "championId": 2}],
            "their_team": [{"cellId": 5, "championId": 7}],
        }
        cs_b = {
            "my_team":    [{"cellId": 1, "championId": 2},
                           {"cellId": 0, "championId": 1}],   # reordered
            "their_team": [{"cellId": 5, "championId": 7}],
        }
        self.assertEqual(agent._picks_signature(cs_a),
                         agent._picks_signature(cs_b))

    def test_signature_changes_on_lock(self):
        cs0 = {"my_team": [{"cellId": 0, "championId": 0}],
               "their_team": []}
        cs1 = {"my_team": [{"cellId": 0, "championId": 99}],  # locked
               "their_team": []}
        self.assertNotEqual(agent._picks_signature(cs0),
                            agent._picks_signature(cs1))

    def test_signature_handles_missing_arrays(self):
        # Both teams missing - must not raise; signature is empty tuples.
        sig = agent._picks_signature({})
        self.assertEqual(sig, ((), ()))


class TestChampionNameFor(unittest.TestCase):
    def setUp(self):
        _reset_module_state()

    def tearDown(self):
        _reset_module_state()

    def test_known_id_returns_name(self):
        agent._CHAMP_NAME_CACHE[164] = "Camille"
        self.assertEqual(agent._champion_name_for(164), "Camille")

    def test_unknown_id_returns_blank(self):
        agent._CHAMP_NAME_CACHE[164] = "Camille"
        self.assertEqual(agent._champion_name_for(999), "")

    def test_zero_id_returns_blank(self):
        # championId 0 = unlocked; must not be looked up.
        self.assertEqual(agent._champion_name_for(0), "")

    def test_none_id_returns_blank(self):
        self.assertEqual(agent._champion_name_for(None), "")

    def test_string_id_coerces(self):
        agent._CHAMP_NAME_CACHE[164] = "Camille"
        self.assertEqual(agent._champion_name_for("164"), "Camille")


class TestBuildTeamContextBody(unittest.TestCase):
    def setUp(self):
        _reset_module_state()
        agent._CHAMP_NAME_CACHE.update({164: "Camille",
                                        24: "Jax",
                                        157: "Yasuo"})

    def tearDown(self):
        _reset_module_state()

    def test_full_roster_translation(self):
        cs = {
            "queue_id": 420,
            "my_team": [
                {"puuid": "ally1", "summonerName": "AllyOne",
                 "championId": 164},
                {"puuid": "ally2", "summonerName": "AllyTwo",
                 "championId": 24},
            ],
            "their_team": [
                {"puuid": "enemy1", "summonerName": "EnemyOne",
                 "championId": 157},
            ],
        }
        body = agent._build_team_context_body(cs)
        self.assertEqual(body["queue_id"], 420)
        self.assertEqual(len(body["roster"]), 3)
        # Allies first, stamped team_id=100
        self.assertEqual(body["roster"][0]["team_id"], 100)
        self.assertEqual(body["roster"][0]["puuid"], "ally1")
        self.assertEqual(body["roster"][0]["locked_champion"], "Camille")
        self.assertEqual(body["roster"][1]["locked_champion"], "Jax")
        # Enemy stamped team_id=200
        self.assertEqual(body["roster"][2]["team_id"], 200)
        self.assertEqual(body["roster"][2]["puuid"], "enemy1")
        self.assertEqual(body["roster"][2]["locked_champion"], "Yasuo")

    def test_unlocked_champion_translates_to_empty(self):
        cs = {
            "queue_id": 0,
            "my_team": [{"puuid": "ally1", "summonerName": "X",
                         "championId": 0}],   # not yet locked
            "their_team": [],
        }
        body = agent._build_team_context_body(cs)
        self.assertEqual(body["roster"][0]["locked_champion"], "")

    def test_unknown_champion_translates_to_empty_not_id_string(self):
        # Cache miss must NOT leak a numeric-id-as-string into the route;
        # the dashboard renders empty on "" but a numeric string would
        # show up as garbage.
        cs = {
            "queue_id": 0,
            "my_team": [{"puuid": "ally1", "summonerName": "X",
                         "championId": 99999}],
            "their_team": [],
        }
        body = agent._build_team_context_body(cs)
        self.assertEqual(body["roster"][0]["locked_champion"], "")

    def test_empty_teams_safe(self):
        body = agent._build_team_context_body({})
        self.assertEqual(body["queue_id"], 0)
        self.assertEqual(body["roster"], [])

    def test_non_dict_slots_skipped(self):
        cs = {"queue_id": 420,
              "my_team": [{"puuid": "ok", "championId": 164},
                          "garbage", None],
              "their_team": []}
        body = agent._build_team_context_body(cs)
        self.assertEqual(len(body["roster"]), 1)
        self.assertEqual(body["roster"][0]["puuid"], "ok")


class TestPostTeamContextRefresh(unittest.TestCase):
    def setUp(self):
        _reset_module_state()

    def tearDown(self):
        _reset_module_state()

    def test_posts_no_auth_header(self):
        # Post-ADR-012 the route is local-only + unauthenticated, so the
        # client always posts and sends NO Authorization header.
        captured = {}

        class _FakeResp:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return b""

        def _fake_urlopen(req, *_, **__):
            captured["url"]    = req.full_url
            captured["body"]   = req.data
            captured["method"] = req.get_method()
            captured["auth"]   = req.get_header("Authorization")
            captured["ctype"]  = req.get_header("Content-type")
            return _FakeResp()

        body = {"queue_id": 420,
                "roster": [{"puuid": "p1", "summoner_name": "S",
                            "team_id": 100, "locked_champion": "Camille"}]}
        with mock.patch.object(agent.urllib.request, "urlopen",
                               side_effect=_fake_urlopen):
            ok, detail = agent.post_team_context_refresh(body)
        self.assertTrue(ok)
        self.assertEqual(detail, "ok")
        self.assertEqual(captured["url"],
                         "https://192.168.8.230:8888/api/team-context/refresh")
        self.assertEqual(captured["method"], "POST")
        self.assertIsNone(captured["auth"])   # no bearer post-decommission
        self.assertEqual(captured["ctype"], "application/json")
        sent = json.loads(captured["body"])
        self.assertEqual(sent["queue_id"], 420)
        self.assertEqual(sent["roster"][0]["puuid"], "p1")

    def test_handles_http_error(self):
        import urllib.error

        def _fake_urlopen(*_, **__):
            raise urllib.error.HTTPError(
                "u", 401, "unauth", hdrs=None, fp=None)
        with mock.patch.object(agent.urllib.request, "urlopen",
                               side_effect=_fake_urlopen):
            ok, detail = agent.post_team_context_refresh(
                {"queue_id": 0, "roster": []})
        self.assertFalse(ok)
        self.assertEqual(detail, "http_401")

    def test_handles_network_error(self):
        import urllib.error

        def _fake_urlopen(*_, **__):
            raise urllib.error.URLError("connection refused")
        with mock.patch.object(agent.urllib.request, "urlopen",
                               side_effect=_fake_urlopen):
            ok, detail = agent.post_team_context_refresh(
                {"queue_id": 0, "roster": []})
        self.assertFalse(ok)
        self.assertTrue(detail.startswith("network: "), detail)


class TestMaybeRefreshTeamContext(unittest.TestCase):
    """Edge-trigger semantics - POST exactly when entering CS or when
    pick set changes; rate-limited otherwise; reset on leave."""

    def setUp(self):
        _reset_module_state()

    def tearDown(self):
        _reset_module_state()

    def _state(self, phase, picks=None, queue_id=420):
        cs = None
        if picks is not None:
            cs = {"queue_id": queue_id,
                  "my_team": picks.get("my", []),
                  "their_team": picks.get("their", [])}
        return {"phase": phase, "champ_select": cs or {}}

    def test_no_post_outside_champselect(self):
        with mock.patch.object(agent, "post_team_context_refresh",
                               return_value=(True, "ok")) as m:
            agent._maybe_refresh_team_context(self._state("Lobby"))
        self.assertEqual(m.call_count, 0)

    def test_posts_on_champselect_entry(self):
        cs = self._state("ChampSelect",
                          picks={"my": [{"cellId": 0, "championId": 1,
                                         "puuid": "p"}],
                                 "their": []})
        with mock.patch.object(agent, "_maybe_load_champion_names"), \
             mock.patch.object(agent, "post_team_context_refresh",
                               return_value=(True, "ok")) as m:
            agent._maybe_refresh_team_context(cs)
        self.assertEqual(m.call_count, 1)
        self.assertEqual(agent._team_context_state["last_phase"],
                         "ChampSelect")

    def test_no_double_post_on_unchanged_picks(self):
        cs = self._state("ChampSelect",
                          picks={"my": [{"cellId": 0, "championId": 1,
                                         "puuid": "p"}],
                                 "their": []})
        with mock.patch.object(agent, "_maybe_load_champion_names"), \
             mock.patch.object(agent, "post_team_context_refresh",
                               return_value=(True, "ok")) as m:
            agent._maybe_refresh_team_context(cs)   # entry -> POST
            agent._maybe_refresh_team_context(cs)   # same cycle -> no POST
            agent._maybe_refresh_team_context(cs)   # again -> no POST
        self.assertEqual(m.call_count, 1)

    def test_reposts_when_pick_set_changes(self):
        cs1 = self._state("ChampSelect",
                           picks={"my": [{"cellId": 0, "championId": 0,
                                          "puuid": "p"}],
                                  "their": []})
        cs2 = self._state("ChampSelect",
                           picks={"my": [{"cellId": 0, "championId": 99,
                                          "puuid": "p"}],
                                  "their": []})
        with mock.patch.object(agent, "_maybe_load_champion_names"), \
             mock.patch.object(agent, "post_team_context_refresh",
                               return_value=(True, "ok")) as m, \
             mock.patch.object(agent, "TEAM_CONTEXT_REPOST_S", 0.0):
            agent._maybe_refresh_team_context(cs1)   # entry
            agent._maybe_refresh_team_context(cs2)   # pick changed
        self.assertEqual(m.call_count, 2)

    def test_rate_limit_blocks_repost(self):
        cs1 = self._state("ChampSelect",
                           picks={"my": [{"cellId": 0, "championId": 0,
                                          "puuid": "p"}],
                                  "their": []})
        cs2 = self._state("ChampSelect",
                           picks={"my": [{"cellId": 0, "championId": 1,
                                          "puuid": "p"}],
                                  "their": []})
        with mock.patch.object(agent, "_maybe_load_champion_names"), \
             mock.patch.object(agent, "post_team_context_refresh",
                               return_value=(True, "ok")) as m, \
             mock.patch.object(agent, "TEAM_CONTEXT_REPOST_S", 999.0):
            agent._maybe_refresh_team_context(cs1)   # entry - POST
            agent._maybe_refresh_team_context(cs2)   # picks changed but
                                                      # rate-limited -> no POST
        self.assertEqual(m.call_count, 1)

    def test_leave_champselect_resets_state(self):
        cs = self._state("ChampSelect",
                          picks={"my": [{"cellId": 0, "championId": 1,
                                         "puuid": "p"}],
                                 "their": []})
        with mock.patch.object(agent, "_maybe_load_champion_names"), \
             mock.patch.object(agent, "post_team_context_refresh",
                               return_value=(True, "ok")) as m:
            agent._maybe_refresh_team_context(cs)
            self.assertEqual(m.call_count, 1)
            agent._maybe_refresh_team_context(self._state("InProgress"))
            # After a leave, the next entry should re-fire even if picks
            # match the old signature.
            agent._maybe_refresh_team_context(cs)
        self.assertEqual(m.call_count, 2)
        # And state was reset on leave.
        self.assertEqual(agent._team_context_state["last_phase"],
                         "ChampSelect")

    def test_failed_post_does_not_latch_signature(self):
        cs = self._state("ChampSelect",
                          picks={"my": [{"cellId": 0, "championId": 1,
                                         "puuid": "p"}],
                                 "their": []})
        with mock.patch.object(agent, "_maybe_load_champion_names"), \
             mock.patch.object(agent, "post_team_context_refresh",
                               return_value=(False, "http_500")) as m:
            agent._maybe_refresh_team_context(cs)
            agent._maybe_refresh_team_context(cs)   # retries
        self.assertEqual(m.call_count, 2)
        self.assertIsNone(
            agent._team_context_state["last_picks_signature"])


if __name__ == "__main__":
    unittest.main()

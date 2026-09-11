"""RC2 L3 prerequisite - characterization of ``lcu/champ_select_shape.py``.

The dashboard's ``build_state`` cannot source champ-select from an
in-process ``LcuClient`` while the only implementation of the agent's
payload shape lives inline in ``tools/lcu_agent.capture_state()``. These
tests pin that shape against a fake request callable so the shaping can be
driven by ANY LCU transport (relay-posted agent, in-process client) and so
the extraction is provably behavior-identical to what the agent posted
before it.

The fixtures below are shaped from real ``/lol-champ-select/v1/session``
payloads: SR draft (actions + bans + swaps), no-draft ARAM (bench, no
actions), and Arena/Cherry (additionalSubteamData).
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lcu.champ_select_shape import (  # noqa: E402
    CHAMP_SELECT_PHASES,
    shape_champ_select,
)


def _fake_request(routes: dict):
    """Build a stand-in for ``tools/lcu_agent.lcu_request``.

    Same contract: ``(method, path, body=None) -> (payload, err)``. Unknown
    paths answer ``(None, "404")`` the way LCU does for a resource that is
    not live in the current phase.
    """
    calls: list[tuple[str, str]] = []

    def _request(method, path, body=None):
        calls.append((method, path))
        if path in routes:
            return routes[path], None
        return None, "404"

    _request.calls = calls
    return _request


_SESSION_PATH = "/lol-champ-select/v1/session"
_GAMEFLOW_PATH = "/lol-gameflow/v1/session"


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
        "positionSwaps": [{"id": 9, "cellId": 3, "state": "AVAILABLE",
                           "extra": "dropped"}],
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


def _aram_session() -> dict:
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


def _arena_session() -> dict:
    return {
        "localPlayerCellId": 1,
        "benchChampions": [],
        "timer": {"phase": "FINALIZATION"},
        "gameData": {"queue": {"id": 1750, "mapId": 30, "gameMode": "CHERRY",
                               "type": "CHERRY", "category": "PvP"}},
        "myTeam": [{"cellId": 1, "championId": 67, "summonerId": 55,
                    "puuid": "puuid-me", "spell1Id": 4, "spell2Id": 32}],
        "theirTeam": [],
        "trades": [],
        "positionSwaps": [],
        "pickOrderSwaps": [],
        "actions": [],
        "additionalSubteamData": [
            {"subteamId": 1, "name": "Poros",
             "members": [{"cellId": 0, "championId": 12},
                         {"cellId": 1, "championId": 67}]},
            {"subteamId": 2, "name": "Minotaurs",
             "members": [{"cellId": 2, "championId": 122}]},
        ],
    }


class TestPhaseGate(unittest.TestCase):
    def test_non_champ_select_phase_returns_empty(self):
        req = _fake_request({_SESSION_PATH: _sr_draft_session()})
        for phase in ("Lobby", "Matchmaking", "None", "ReadyCheck", ""):
            self.assertEqual(shape_champ_select(req, phase), {})
        # No LCU call at all for an irrelevant phase - the caller must not
        # pay a round-trip it will discard.
        self.assertEqual(req.calls, [])

    def test_all_three_live_phases_shape(self):
        self.assertEqual(
            tuple(CHAMP_SELECT_PHASES),
            ("ChampSelect", "GameStart", "InProgress"))
        for phase in CHAMP_SELECT_PHASES:
            req = _fake_request({_SESSION_PATH: _sr_draft_session()})
            out = shape_champ_select(req, phase)
            self.assertIn("champ_select", out)


class TestSrDraftShape(unittest.TestCase):
    def setUp(self):
        self.req = _fake_request({_SESSION_PATH: _sr_draft_session()})
        self.out = shape_champ_select(self.req, "ChampSelect")
        self.cs = self.out["champ_select"]

    def test_cs_debug_keys_and_order(self):
        dbg = self.out["cs_debug"]
        self.assertEqual(list(dbg), ["cs_session_is_dict", "queue_obj",
                                     "bench_len"])
        self.assertTrue(dbg["cs_session_is_dict"])
        self.assertEqual(dbg["queue_obj"], {
            "id": 420, "mapId": 11, "gameMode": "CLASSIC",
            "type": "CLASSIC", "category": "PvP"})
        self.assertEqual(dbg["bench_len"], 0)

    def test_scalar_fields(self):
        self.assertEqual(self.cs["queue_id"], 420)
        self.assertFalse(self.cs["is_aram"])
        self.assertEqual(self.cs["local_cell"], 2)
        self.assertEqual(self.cs["my_champion"], 67)
        self.assertEqual(self.cs["my_champion_locked"], 67)
        self.assertEqual(self.cs["my_champion_intent"], 0)
        self.assertTrue(self.cs["my_completed"])
        self.assertEqual(self.cs["my_summoners"], [4, 7])
        self.assertEqual(self.cs["bench"], [])
        self.assertEqual(self.cs["phase"], "BAN_PICK")

    def test_team_picks_full_field_set(self):
        self.assertEqual(self.cs["my_team"][0], {
            "cellId": 2,
            "championId": 67,
            "champion_pick_intent": 0,
            "champion_locked": 67,
            "summonerId": 55,
            "summonerName": "You",
            "puuid": "puuid-me",
            "completed": False,
            "assignedPosition": "bottom",
            "summoners": [4, 7],
        })

    def test_hover_falls_back_to_pick_intent(self):
        ally = self.cs["my_team"][1]
        self.assertEqual(ally["championId"], 412)
        self.assertEqual(ally["champion_locked"], 0)
        self.assertEqual(ally["champion_pick_intent"], 412)
        # Riot compliance 2026-08-11: the producer emits a positional
        # "Ally N" label, never the LCU name. See
        # lcu/champ_select_shape._obfuscated_name.
        self.assertEqual(ally["summonerName"], "Ally 2")

    def test_their_team_shaped(self):
        self.assertEqual(len(self.cs["their_team"]), 1)
        self.assertEqual(self.cs["their_team"][0]["championId"], 122)
        self.assertEqual(self.cs["their_team"][0]["puuid"], "")

    def test_trades_and_swaps_slimmed(self):
        self.assertEqual(self.cs["trades"],
                         [{"id": 1, "cellId": 3, "state": "AVAILABLE"}])
        self.assertEqual(self.cs["position_swaps"],
                         [{"id": 9, "cellId": 3, "state": "AVAILABLE"}])
        self.assertEqual(self.cs["pick_order_swaps"],
                         [{"id": 11, "cellId": 4, "state": "SENT"}])

    def test_active_round(self):
        self.assertEqual(self.cs["active_round"],
                         {"type": "pick", "cell_ids": [3]})

    def test_no_arena_keys_off_arena_queue(self):
        self.assertNotIn("arena_teams", self.cs)
        self.assertNotIn("augments", self.cs)

    def test_key_order_is_the_agent_payload_order(self):
        self.assertEqual(list(self.cs), [
            "queue_id", "is_aram", "local_cell", "my_champion",
            "my_champion_locked", "my_champion_intent", "my_completed",
            "my_summoners", "bench", "phase", "my_team", "their_team",
            "trades", "position_swaps", "pick_order_swaps", "active_round",
        ])

    def test_only_the_session_route_is_called(self):
        self.assertEqual(self.req.calls, [("GET", _SESSION_PATH)])


class TestAramShape(unittest.TestCase):
    def setUp(self):
        self.out = shape_champ_select(
            _fake_request({_SESSION_PATH: _aram_session()}), "ChampSelect")
        self.cs = self.out["champ_select"]

    def test_mayhem_queue_is_aram(self):
        self.assertEqual(self.cs["queue_id"], 2400)
        self.assertTrue(self.cs["is_aram"])

    def test_bench_ids_skip_non_dicts(self):
        self.assertEqual(self.cs["bench"], [21, 76, 143])
        self.assertEqual(self.out["cs_debug"]["bench_len"], 4)

    def test_no_actions_means_no_active_round_and_not_completed(self):
        self.assertIsNone(self.cs["active_round"])
        self.assertFalse(self.cs["my_completed"])


class TestArenaShape(unittest.TestCase):
    def setUp(self):
        self.cs = shape_champ_select(
            _fake_request({_SESSION_PATH: _arena_session()}),
            "ChampSelect")["champ_select"]

    def test_arena_teams_appended_after_active_round(self):
        self.assertEqual(list(self.cs)[-2:], ["arena_teams", "augments"])

    def test_arena_teams_is_me_detection(self):
        self.assertEqual(self.cs["arena_teams"], [
            {"id": 1, "name": "Poros", "is_me": True,
             "cells": [{"cellId": 0, "championId": 12},
                       {"cellId": 1, "championId": 67}]},
            {"id": 2, "name": "Minotaurs", "is_me": False,
             "cells": [{"cellId": 2, "championId": 122}]},
        ])

    def test_augments_scaffold(self):
        self.assertEqual(self.cs["augments"], {
            "my_slots": ["", "", ""], "options": [], "current_round": 0})

    def test_legacy_arena_queue_aliases_also_shape(self):
        for qid in (1700, 1710):
            sess = _arena_session()
            sess["gameData"]["queue"]["id"] = qid
            cs = shape_champ_select(
                _fake_request({_SESSION_PATH: sess}),
                "ChampSelect")["champ_select"]
            self.assertIn("arena_teams", cs)


class TestQueueIdFallback(unittest.TestCase):
    def test_missing_gamedata_falls_back_to_gameflow(self):
        sess = _sr_draft_session()
        del sess["gameData"]
        req = _fake_request({
            _SESSION_PATH: sess,
            _GAMEFLOW_PATH: {"gameData": {"queue": {"id": 420}}},
        })
        cs = shape_champ_select(req, "ChampSelect")["champ_select"]
        self.assertEqual(cs["queue_id"], 420)
        self.assertIn(("GET", _GAMEFLOW_PATH), req.calls)

    def test_gameflow_miss_leaves_queue_id_zero(self):
        sess = _sr_draft_session()
        del sess["gameData"]
        cs = shape_champ_select(
            _fake_request({_SESSION_PATH: sess}),
            "ChampSelect")["champ_select"]
        self.assertEqual(cs["queue_id"], 0)
        self.assertFalse(cs["is_aram"])

    def test_queue_obj_empty_when_gamedata_absent(self):
        sess = _sr_draft_session()
        del sess["gameData"]
        dbg = shape_champ_select(
            _fake_request({_SESSION_PATH: sess}), "ChampSelect")["cs_debug"]
        self.assertEqual(dbg["queue_obj"], {
            "id": None, "mapId": None, "gameMode": None,
            "type": None, "category": None})


class TestDegenerateSessions(unittest.TestCase):
    def test_none_session_reports_debug_only(self):
        out = shape_champ_select(_fake_request({}), "ChampSelect")
        self.assertEqual(out, {"cs_debug": {"cs_session_is_dict": False}})
        self.assertNotIn("champ_select", out)

    def test_non_dict_session_reports_debug_only(self):
        out = shape_champ_select(
            _fake_request({_SESSION_PATH: ["not", "a", "dict"]}),
            "InProgress")
        self.assertEqual(out, {"cs_debug": {"cs_session_is_dict": False}})

    def test_empty_dict_session(self):
        cs = shape_champ_select(
            _fake_request({_SESSION_PATH: {}}),
            "ChampSelect")["champ_select"]
        self.assertEqual(cs["queue_id"], 0)
        self.assertEqual(cs["local_cell"], -1)
        self.assertEqual(cs["my_champion"], 0)
        self.assertEqual(cs["my_team"], [])
        self.assertEqual(cs["their_team"], [])
        self.assertIsNone(cs["phase"])
        self.assertIsNone(cs["active_round"])

    def test_malformed_members_are_dropped_not_raised(self):
        sess = _sr_draft_session()
        sess["theirTeam"] = [None, "x", 7]
        sess["trades"] = [None, {"id": 3, "cellId": 1, "state": "BUSY"}]
        sess["positionSwaps"] = "garbage"
        sess["actions"] = ["not-a-group", [None, "x"]]
        cs = shape_champ_select(
            _fake_request({_SESSION_PATH: sess}),
            "ChampSelect")["champ_select"]
        self.assertEqual(cs["their_team"], [])
        self.assertEqual(cs["trades"], [{"id": 3, "cellId": 1,
                                         "state": "BUSY"}])
        self.assertEqual(cs["position_swaps"], [])
        self.assertIsNone(cs["active_round"])
        self.assertFalse(cs["my_completed"])

    def test_non_dict_my_team_entry_is_dropped_not_raised(self):
        # SUPERSEDED 2026-08-31 (lane 8 cycle 46). This pinned an
        # AttributeError as intended behaviour, on the stated grounds that
        # "hardening it here would be a behavior change on an extraction
        # slice that must stay byte-identical". That reason went stale when
        # the extraction landed: the RC2 L3 slice completed 2026-07-20 and
        # tools/lcu_agent.py retains NO inline copy of the shaping (it
        # delegates at :344), so there is no second implementation left for
        # this one to be byte-identical WITH.
        #
        # The pin was also internally inconsistent with the test directly
        # above it, which requires malformed theirTeam / trades /
        # positionSwaps / actions entries to be DROPPED, not raised - the
        # same function, the same class of input, the opposite policy. And
        # the raise was never observable: both callers swallow it
        # (dashboard/_lcu_inprocess.py:255-257 returns None - silently until
        # RM-312 added a throttled WARN there on 2026-09-11;
        # tools/lcu_agent.py:1612 loses the snapshot for the tick and is
        # still silent), so it deleted the whole champ-select payload
        # rather than surfacing anything useful.
        sess = _sr_draft_session()
        sess["myTeam"] = [None]
        cs = shape_champ_select(_fake_request({_SESSION_PATH: sess}),
                                "ChampSelect")["champ_select"]
        self.assertEqual(cs["my_team"], [])
        self.assertEqual(cs["my_champion"], 0)

    def test_non_int_local_cell_normalises_to_minus_one(self):
        sess = _sr_draft_session()
        sess["localPlayerCellId"] = None
        cs = shape_champ_select(
            _fake_request({_SESSION_PATH: sess}),
            "ChampSelect")["champ_select"]
        self.assertEqual(cs["local_cell"], -1)

    def test_missing_bench_key(self):
        sess = _aram_session()
        del sess["benchChampions"]
        out = shape_champ_select(
            _fake_request({_SESSION_PATH: sess}), "ChampSelect")
        self.assertEqual(out["champ_select"]["bench"], [])
        self.assertEqual(out["cs_debug"]["bench_len"], 0)


class TestAgentParity(unittest.TestCase):
    """The agent must post exactly what the extracted module produces."""

    def _capture(self, sess, phase="ChampSelect"):
        sys.path.insert(0, str(_PROJECT_ROOT / "tools"))
        import lcu_agent as agent

        req = _fake_request({
            _SESSION_PATH: sess,
            "/lol-gameflow/v1/gameflow-phase": phase,
        })
        real_request = agent.lcu_request
        real_conn = agent.ensure_lcu_conn
        real_mastery = agent._maybe_refresh_mastery
        agent.lcu_request = req
        agent.ensure_lcu_conn = lambda: True
        agent._maybe_refresh_mastery = lambda: None
        try:
            return agent.capture_state()
        finally:
            agent.lcu_request = real_request
            agent.ensure_lcu_conn = real_conn
            agent._maybe_refresh_mastery = real_mastery

    def test_agent_champ_select_matches_module(self):
        for sess in (_sr_draft_session(), _aram_session(), _arena_session()):
            with self.subTest(queue=sess["gameData"]["queue"]["id"]):
                state = self._capture(sess)
                expected = shape_champ_select(
                    _fake_request({_SESSION_PATH: sess}), "ChampSelect")
                self.assertEqual(state["champ_select"],
                                 expected["champ_select"])
                self.assertEqual(list(state["champ_select"]),
                                 list(expected["champ_select"]))

    def test_agent_cs_debug_still_carries_enrichment(self):
        state = self._capture(_aram_session())
        self.assertEqual(list(state["cs_debug"]),
                         ["raw_phase", "ts", "cs_session_is_dict",
                          "queue_obj", "bench_len"])
        self.assertEqual(state["cs_debug"]["bench_len"], 4)

    def test_agent_omits_champ_select_when_session_absent(self):
        state = self._capture(None)
        self.assertNotIn("champ_select", state)
        self.assertFalse(state["cs_debug"]["cs_session_is_dict"])


class TestConnectionAgnostic(unittest.TestCase):
    """L3 needs this module usable from the dashboard process, where
    ``tools/lcu_agent`` (lockfile scan, push loops, command queue) must
    never be imported."""

    def test_imports_without_agent_or_network(self):
        probe = (
            "import sys; import lcu.champ_select_shape as m;"
            "assert 'lcu_agent' not in sys.modules;"
            "assert 'socket' not in sys.modules;"
            "assert 'urllib.request' not in sys.modules;"
            "print(m.shape_champ_select(lambda *a, **k: (None, 'x'),"
            " 'ChampSelect'))"
        )
        res = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=str(_PROJECT_ROOT), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("cs_session_is_dict", res.stdout)

    def test_no_module_global_connection_state(self):
        import lcu.champ_select_shape as m

        leaked = [n for n in vars(m)
                  if n.startswith("_lcu") or n in ("CONFIG", "TOKEN",
                                                   "LEGION")]
        self.assertEqual(leaked, [])


if __name__ == "__main__":
    unittest.main()

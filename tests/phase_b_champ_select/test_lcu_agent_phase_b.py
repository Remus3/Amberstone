"""Phase B — Champ Select LCU agent handlers + state population.

Pins the contracts added to `tools/gamepc_lcu_agent.py` for the
Champ Select view's command flow:

  - _active_round  → derive {type, cell_ids} from session.actions[]
  - _swap_entries  → slim positionSwaps / pickOrderSwaps for the push
  - _arena_teams   → distil additionalSubteamData with is_me detection
  - _local_in_progress_action → walk actions for the local cell's
                                in-progress ban|pick

  - set_ban_intent / set_pick_intent — PATCH local action, completed=false
  - request_position_swap / request_pick_order_swap — cell_id → swap id
  - set_augment_intent — stub returns explicit "unsupported" error

The agent runs on Game-PC and is stdlib-only; tests import via
`sys.path.insert(..., "tools")` because tools/ has no __init__.py.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

import gamepc_lcu_agent as agent  # noqa: E402


# ---------------------------------------------------------------------------
# Pure helpers — no LCU contact, just shape transforms.
# ---------------------------------------------------------------------------


class TestActiveRound(unittest.TestCase):
    def test_returns_none_when_no_actions(self):
        self.assertIsNone(agent._active_round({}))
        self.assertIsNone(agent._active_round({"actions": []}))

    def test_returns_none_when_nothing_in_progress(self):
        sess = {
            "actions": [[
                {"id": 1, "actorCellId": 0, "type": "ban",
                 "completed": True, "isInProgress": False},
            ]]
        }
        self.assertIsNone(agent._active_round(sess))

    def test_picks_in_progress_returns_pick_with_cells(self):
        sess = {
            "actions": [
                [{"id": 1, "actorCellId": 0, "type": "ban",
                  "completed": True, "isInProgress": False}],
                [{"id": 10, "actorCellId": 3, "type": "pick",
                  "completed": False, "isInProgress": True},
                 {"id": 11, "actorCellId": 6, "type": "pick",
                  "completed": False, "isInProgress": True}],
            ]
        }
        out = agent._active_round(sess)
        self.assertEqual(out["type"], "pick")
        self.assertEqual(sorted(out["cell_ids"]), [3, 6])

    def test_bans_in_progress_returns_ban(self):
        sess = {"actions": [[
            {"id": 1, "actorCellId": 0, "type": "ban",
             "completed": False, "isInProgress": True},
        ]]}
        self.assertEqual(agent._active_round(sess)["type"], "ban")

    def test_skips_malformed_inner_arrays(self):
        sess = {"actions": ["not a list",
                            [{"actorCellId": 2, "type": "pick",
                              "isInProgress": True}]]}
        out = agent._active_round(sess)
        self.assertEqual(out["type"], "pick")
        self.assertEqual(out["cell_ids"], [2])


class TestSwapEntries(unittest.TestCase):
    def test_slims_fields(self):
        raw = [
            {"id": 0, "cellId": 5, "state": "AVAILABLE", "other": "ignored"},
            {"id": 1, "cellId": 6, "state": "SENT"},
        ]
        out = agent._swap_entries(raw)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0],
                         {"id": 0, "cellId": 5, "state": "AVAILABLE"})
        self.assertEqual(out[1],
                         {"id": 1, "cellId": 6, "state": "SENT"})

    def test_handles_none_and_empty(self):
        self.assertEqual(agent._swap_entries(None), [])
        self.assertEqual(agent._swap_entries([]), [])

    def test_skips_non_dict_entries(self):
        self.assertEqual(agent._swap_entries([None, "x", 7]), [])


class TestArenaTeams(unittest.TestCase):
    def test_empty_when_no_subteam_data(self):
        self.assertEqual(agent._arena_teams({}), [])
        self.assertEqual(agent._arena_teams({"additionalSubteamData": []}), [])

    def test_full_4_subteam_distil_with_is_me(self):
        sess = {
            "localPlayerCellId": 2,
            "additionalSubteamData": [
                {"subteamId": 1, "name": "TEAM 1",
                 "members": [{"cellId": 0, "championId": 67},
                             {"cellId": 1, "championId": 412}]},
                {"subteamId": 2, "name": "TEAM 2",
                 "members": [{"cellId": 2, "championId": 67},
                             {"cellId": 3, "championId": 99}]},
                {"subteamId": 3, "name": "TEAM 3",
                 "members": [{"cellId": 4, "championId": 86}]},
            ],
        }
        out = agent._arena_teams(sess)
        self.assertEqual(len(out), 3)
        # Local cell is 2 → subteam 2 is mine
        me = next(t for t in out if t["is_me"])
        self.assertEqual(me["id"], 2)
        self.assertEqual(len(me["cells"]), 2)
        # Others marked not-me
        others = [t for t in out if not t["is_me"]]
        self.assertEqual(len(others), 2)

    def test_no_is_me_when_local_cell_missing(self):
        sess = {
            "additionalSubteamData": [
                {"subteamId": 1, "name": "TEAM 1",
                 "members": [{"cellId": 0, "championId": 67}]},
            ],
        }
        out = agent._arena_teams(sess)
        self.assertFalse(out[0]["is_me"])

    def test_name_fallback_when_missing(self):
        sess = {
            "localPlayerCellId": 0,
            "additionalSubteamData": [
                {"id": 5, "members": [{"cellId": 0, "championId": 1}]},
            ],
        }
        out = agent._arena_teams(sess)
        self.assertEqual(out[0]["name"], "Team 5")


class TestLocalInProgressAction(unittest.TestCase):
    def test_returns_none_when_no_local_cell(self):
        self.assertIsNone(agent._local_in_progress_action({}, "pick"))

    def test_finds_in_progress_pick_for_local_cell(self):
        sess = {
            "localPlayerCellId": 3,
            "actions": [[
                {"id": 50, "actorCellId": 3, "type": "pick",
                 "completed": False, "isInProgress": True,
                 "championId": 0},
            ]],
        }
        out = agent._local_in_progress_action(sess, "pick")
        self.assertIsNotNone(out)
        self.assertEqual(out["id"], 50)

    def test_skips_completed_actions(self):
        sess = {
            "localPlayerCellId": 3,
            "actions": [[
                {"id": 50, "actorCellId": 3, "type": "pick",
                 "completed": True, "isInProgress": False,
                 "championId": 99},
            ]],
        }
        self.assertIsNone(agent._local_in_progress_action(sess, "pick"))

    def test_skips_other_cell_actions(self):
        sess = {
            "localPlayerCellId": 3,
            "actions": [[
                {"id": 50, "actorCellId": 4, "type": "pick",
                 "completed": False, "isInProgress": True},
            ]],
        }
        self.assertIsNone(agent._local_in_progress_action(sess, "pick"))

    def test_type_filter_distinguishes_ban_and_pick(self):
        sess = {
            "localPlayerCellId": 3,
            "actions": [[
                {"id": 1, "actorCellId": 3, "type": "ban",
                 "completed": False, "isInProgress": True},
                {"id": 2, "actorCellId": 3, "type": "pick",
                 "completed": False, "isInProgress": True},
            ]],
        }
        ban = agent._local_in_progress_action(sess, "ban")
        pick = agent._local_in_progress_action(sess, "pick")
        self.assertEqual(ban["id"], 1)
        self.assertEqual(pick["id"], 2)


# ---------------------------------------------------------------------------
# Command handlers — mock lcu_request to avoid touching a real LCU.
# ---------------------------------------------------------------------------


def _mock_lcu_request_for(responses):
    """Build a side_effect that returns ``responses[i]`` per call.

    Each entry is ``(payload, err)`` — same tuple shape as the real
    ``lcu_request``. If exhausted, returns (None, "exhausted") so the
    test fails loudly rather than mysteriously timing out.
    """
    calls = []
    iterator = iter(responses)

    def _side(method, path, body=None):
        calls.append((method, path, body))
        try:
            return next(iterator)
        except StopIteration:
            return (None, "exhausted")

    return _side, calls


class TestSetBanPickIntent(unittest.TestCase):
    def setUp(self):
        self._patch = mock.patch.object(agent, "lcu_request")
        self.mock_req = self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_set_ban_intent_patches_action(self):
        sess = {
            "localPlayerCellId": 3,
            "actions": [[
                {"id": 42, "actorCellId": 3, "type": "ban",
                 "completed": False, "isInProgress": True},
            ]],
        }
        side, calls = _mock_lcu_request_for([
            (sess, None),       # initial GET session
            ({}, None),         # PATCH action
        ])
        self.mock_req.side_effect = side
        out = agent.execute_command(
            {"cmd": "set_ban_intent", "championId": 99})
        self.assertTrue(out["ok"])
        self.assertEqual(out["action_id"], 42)
        # Second call should be the PATCH with championId + completed=False
        method, path, body = calls[1]
        self.assertEqual(method, "PATCH")
        self.assertIn("/actions/42", path)
        self.assertEqual(body, {"championId": 99, "completed": False})

    def test_set_pick_intent_patches_pick_action(self):
        sess = {
            "localPlayerCellId": 3,
            "actions": [[
                {"id": 7, "actorCellId": 3, "type": "pick",
                 "completed": False, "isInProgress": True},
            ]],
        }
        side, _calls = _mock_lcu_request_for([(sess, None), ({}, None)])
        self.mock_req.side_effect = side
        out = agent.execute_command(
            {"cmd": "set_pick_intent", "championId": 164})
        self.assertTrue(out["ok"])
        self.assertEqual(out["action_id"], 7)

    def test_no_championId_rejected(self):
        out = agent.execute_command({"cmd": "set_ban_intent"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["err"], "no championId")
        # No LCU GET should have fired
        self.mock_req.assert_not_called()

    def test_no_in_progress_action_surfaced(self):
        sess = {
            "localPlayerCellId": 3,
            "actions": [[
                {"id": 42, "actorCellId": 3, "type": "ban",
                 "completed": True, "isInProgress": False},
            ]],
        }
        self.mock_req.return_value = (sess, None)
        out = agent.execute_command(
            {"cmd": "set_ban_intent", "championId": 99})
        self.assertFalse(out["ok"])
        self.assertIn("no in-progress ban", out["err"])

    def test_session_fetch_failure(self):
        self.mock_req.return_value = (None, "http 404")
        out = agent.execute_command(
            {"cmd": "set_pick_intent", "championId": 99})
        self.assertFalse(out["ok"])
        self.assertEqual(out["err"], "no session")


class TestPositionAndPickOrderSwap(unittest.TestCase):
    def setUp(self):
        self._patch = mock.patch.object(agent, "lcu_request")
        self.mock_req = self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_position_swap_request_posts(self):
        sess = {
            "positionSwaps": [
                {"id": 11, "cellId": 4, "state": "AVAILABLE"},
            ],
        }
        side, calls = _mock_lcu_request_for([(sess, None), ({}, None)])
        self.mock_req.side_effect = side
        out = agent.execute_command(
            {"cmd": "request_position_swap", "cell_id": 4})
        self.assertTrue(out["ok"])
        self.assertEqual(out["swap_id"], 11)
        method, path, _ = calls[1]
        self.assertEqual(method, "POST")
        self.assertEqual(
            path, "/lol-champ-select/v1/session/position-swaps/11/request")

    def test_pick_order_swap_request_posts(self):
        sess = {
            "pickOrderSwaps": [
                {"id": 22, "cellId": 7, "state": "AVAILABLE"},
            ],
        }
        side, calls = _mock_lcu_request_for([(sess, None), ({}, None)])
        self.mock_req.side_effect = side
        out = agent.execute_command(
            {"cmd": "request_pick_order_swap", "cell_id": 7})
        self.assertTrue(out["ok"])
        self.assertEqual(out["swap_id"], 22)
        method, path, _ = calls[1]
        self.assertEqual(method, "POST")
        self.assertEqual(
            path, "/lol-champ-select/v1/session/pick-order-swaps/22/request")

    def test_no_swap_slot_for_cell(self):
        self.mock_req.return_value = ({"positionSwaps": []}, None)
        out = agent.execute_command(
            {"cmd": "request_position_swap", "cell_id": 4})
        self.assertFalse(out["ok"])
        self.assertIn("no position-swap slot", out["err"])

    def test_busy_state_rejected(self):
        sess = {"positionSwaps": [
            {"id": 11, "cellId": 4, "state": "BUSY"},
        ]}
        self.mock_req.return_value = (sess, None)
        out = agent.execute_command(
            {"cmd": "request_position_swap", "cell_id": 4})
        self.assertFalse(out["ok"])
        self.assertEqual(out["err"], "swap busy")

    def test_invalid_state_rejected(self):
        sess = {"pickOrderSwaps": [
            {"id": 9, "cellId": 4, "state": "INVALID"},
        ]}
        self.mock_req.return_value = (sess, None)
        out = agent.execute_command(
            {"cmd": "request_pick_order_swap", "cell_id": 4})
        self.assertFalse(out["ok"])
        self.assertEqual(out["err"], "swap invalid")

    def test_missing_cell_id(self):
        out = agent.execute_command({"cmd": "request_position_swap"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["err"], "no cell_id")


class TestSetAugmentIntentStub(unittest.TestCase):
    def setUp(self):
        # Even though the handler shouldn't hit LCU, patch to be safe.
        self._patch = mock.patch.object(agent, "lcu_request")
        self.mock_req = self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_returns_unsupported_with_id(self):
        out = agent.execute_command(
            {"cmd": "set_augment_intent", "augment_id": 7042})
        self.assertFalse(out["ok"])
        self.assertEqual(out["err"], "augment_intent_unsupported")
        self.assertEqual(out["augment_id"], 7042)
        self.assertIn("note", out)
        self.mock_req.assert_not_called()

    def test_missing_id_rejected(self):
        out = agent.execute_command({"cmd": "set_augment_intent"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["err"], "no augment_id")


class TestAramQueueIdsAntiDrift(unittest.TestCase):
    """Pin the KNOWN-BUG fix + the agent↔core mirror.

    is_aram was ``queue_id in (450, 920)`` — missing 2400 (ARAM
    Mayhem / KIWI) — so the dashboard's _csvDetectMode fell through to
    "sr" and the bench / quick-swap UI never rendered for Mayhem. The
    agent runs standalone on Game-PC and can't import core.*, so
    ``_ARAM_QUEUE_IDS`` is a hand-kept mirror of the aram keys in
    core.queue_modes — this guards it from silently drifting again."""

    def test_mayhem_2400_in_aram_set(self):
        self.assertIn(2400, agent._ARAM_QUEUE_IDS)
        self.assertIn(450, agent._ARAM_QUEUE_IDS)

    def test_mirror_matches_core_queue_modes_aram_keys(self):
        from core.queue_modes import QUEUE_ID_TO_MODE_KEY
        core_aram = {qid for qid, m in QUEUE_ID_TO_MODE_KEY.items()
                     if m == "aram"}
        self.assertEqual(
            set(agent._ARAM_QUEUE_IDS), core_aram,
            "tools/gamepc_lcu_agent._ARAM_QUEUE_IDS drifted from "
            "core.queue_modes aram keys — keep the mirror in sync")


if __name__ == "__main__":
    unittest.main()

"""Lane 8 cycle 46 - fail-soft guards for ``lcu/champ_select_shape.py``.

WHY THIS FILE EXISTS
--------------------
``lcu/snapshot_shape.py:509-517`` carries an in-code note recording exactly
this defect class, found and fixed there by lane 8 cycle 35 (LEDGER 1294)::

    ``.get("gameData", {})`` hands back the DEFAULT only when the key is
    ABSENT. LCU routinely emits a present-and-NULL sub-object, and
    ``None.get(...)`` then raised AttributeError straight out of
    shape_snapshot, costing the whole snapshot for the tick.

The call into ``shape_champ_select`` sits ELEVEN LINES EARLIER in that same
function (``lcu/snapshot_shape.py:498``) and went into three unfixed copies
of the same double-chain, plus a spread of sibling reads: 19 of 20 probed
inputs raise against the pre-fix module and 0 of 20 against the fixed one,
and 19 unguarded reads were routed through the new helpers. The sibling was
missed - the same shape as lane 8 cycle 45, where a fix landed in
``core/rofl_archive.py`` and its twin never got it.

WHY A RAISE IS EXPENSIVE HERE, AND WHY IT IS INVISIBLE
------------------------------------------------------
Neither caller lets the exception surface:

* ``dashboard/_lcu_inprocess.py:255-257`` catches ``Exception`` and returns
  ``None``, so the in-process L3 path falls back to the ``:8889`` relay hop
  that L3 exists to remove. RM-312 (2026-09-11) added a throttled WARNING on
  that degrade, so this half is no longer SILENT - but the payload for that
  build is still lost.
* ``tools/lcu_agent.py:1612`` calls ``capture_state()`` inside the state
  push loop, so the whole snapshot for that tick is lost - and that half is
  still silent.

Both still degrade, so a malformed field costs the entire champ-select
payload - bench, swaps, active round, Arena rosters.

THE MODULE HAD ALREADY DECIDED TO FAIL SOFT. These sites were the ones the
decision was not applied to: ``trades`` is isinstance-guarded two lines
above an unguarded ``benchChampions`` read, and ``arena_teams`` wraps one
``int()`` in try/except while its sibling ``int()`` nine lines later is
bare. Every case below was MEASURED to raise against the pre-fix module.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lcu.champ_select_shape import (  # noqa: E402
    arena_teams,
    shape_champ_select,
    swap_entries,
)


def _request_for(session, gameflow=None):
    """A transport honouring the agent contract ``(payload, err)``.

    ``/lol-champ-select/v1/session`` answers ``session``; the gameflow
    fallback answers ``gameflow`` (an empty dict unless a case overrides
    it, which is what a live client returns when it has no session).
    """
    def request(method, path, body=None):
        if "champ-select" in path:
            return session, None
        return ({} if gameflow is None else gameflow), None
    return request


def _shape(session, gameflow=None):
    return shape_champ_select(_request_for(session, gameflow), "ChampSelect")


class MalformedGameDataIsNotFatal(unittest.TestCase):
    """The three unguarded copies of the cycle-35 ``gameData`` double-chain.

    ``sess.get("gameData", {})`` returns the default only for an ABSENT
    key. A present-and-null value hands back ``None`` and the chained
    ``.get`` raises.
    """

    def test_game_data_present_and_null(self):
        out = _shape({"gameData": None})
        self.assertEqual(out["champ_select"]["queue_id"], 0)
        self.assertIsNone(out["cs_debug"]["queue_obj"]["id"])

    def test_game_data_queue_present_and_null(self):
        out = _shape({"gameData": {"queue": None}})
        self.assertEqual(out["champ_select"]["queue_id"], 0)
        self.assertIsNone(out["cs_debug"]["queue_obj"]["mapId"])

    def test_game_data_wrong_type_is_treated_as_absent(self):
        for junk in ([], "x", 5, True):
            with self.subTest(junk=junk):
                out = _shape({"gameData": junk})
                self.assertEqual(out["champ_select"]["queue_id"], 0)

    def test_queue_wrong_type_is_treated_as_absent(self):
        for junk in ([], "x", 5):
            with self.subTest(junk=junk):
                out = _shape({"gameData": {"queue": junk}})
                self.assertEqual(out["champ_select"]["queue_id"], 0)

    def test_a_real_queue_id_still_reads_through(self):
        """The guard must not cost the value it is guarding."""
        out = _shape({"gameData": {"queue": {"id": 450, "mapId": 12}}})
        self.assertEqual(out["champ_select"]["queue_id"], 450)
        self.assertTrue(out["champ_select"]["is_aram"])
        self.assertEqual(out["cs_debug"]["queue_obj"]["mapId"], 12)


class MalformedGameflowFallbackIsNotFatal(unittest.TestCase):
    """The fallback exists BECAUSE gameData is unreliable.

    ``lcu/champ_select_shape.py`` documents at its own queue-id fallback
    that the champ-select session "frequently omits gameData during
    BAN_PICK". The fallback read of ``/lol-gameflow/v1/session`` was then
    written assuming that same sub-object is well formed.
    """

    def test_gameflow_game_data_present_and_null(self):
        out = _shape({}, gameflow={"gameData": None})
        self.assertEqual(out["champ_select"]["queue_id"], 0)

    def test_gameflow_queue_present_and_null(self):
        out = _shape({}, gameflow={"gameData": {"queue": None}})
        self.assertEqual(out["champ_select"]["queue_id"], 0)

    def test_gameflow_still_supplies_the_queue_id_when_well_formed(self):
        """Pins the s154 fallback the guard sits on top of."""
        out = _shape({}, gameflow={"gameData": {"queue": {"id": 420}}})
        self.assertEqual(out["champ_select"]["queue_id"], 420)


class MalformedRosterFieldsAreNotFatal(unittest.TestCase):
    """``myTeam`` / ``theirTeam`` / ``benchChampions`` on the shaping path."""

    def test_my_team_present_and_null(self):
        out = _shape({"myTeam": None})
        self.assertEqual(out["champ_select"]["my_team"], [])
        self.assertEqual(out["champ_select"]["my_champion"], 0)

    def test_my_team_carries_a_non_dict_entry(self):
        """``_team_picks`` skipped non-dicts; the local-pick lookup did not."""
        out = _shape({"myTeam": [None, {"cellId": 0, "championId": 67}],
                      "localPlayerCellId": 0})
        self.assertEqual(out["champ_select"]["my_champion"], 67)

    def test_my_team_is_a_dict(self):
        """Iterating a dict yields its string keys, then ``str.get`` raised."""
        out = _shape({"myTeam": {"cellId": 0}})
        self.assertEqual(out["champ_select"]["my_team"], [])

    def test_their_team_wrong_type(self):
        for junk in (None, 5, {"a": 1}, "xy"):
            with self.subTest(junk=junk):
                out = _shape({"theirTeam": junk})
                self.assertEqual(out["champ_select"]["their_team"], [])

    def test_bench_champions_present_and_null(self):
        """``bench_len`` had ``or []``; the ``bench`` read two lines on did not."""
        out = _shape({"benchChampions": None})
        self.assertEqual(out["champ_select"]["bench"], [])
        self.assertEqual(out["cs_debug"]["bench_len"], 0)

    def test_bench_champions_wrong_type(self):
        for junk in (5, {"a": 1}, "ab"):
            with self.subTest(junk=junk):
                out = _shape({"benchChampions": junk})
                self.assertEqual(out["champ_select"]["bench"], [])
                self.assertEqual(out["cs_debug"]["bench_len"], 0)

    def test_a_real_bench_still_reads_through(self):
        out = _shape({"benchChampions": [{"championId": 1}, {"championId": 2}]})
        self.assertEqual(out["champ_select"]["bench"], [1, 2])
        self.assertEqual(out["cs_debug"]["bench_len"], 2)


class MalformedRoundAndSwapFieldsAreNotFatal(unittest.TestCase):
    """``actions`` / ``trades`` / the two swap lists / ``timer``."""

    def test_actions_wrong_type(self):
        for junk in (5, "xy", {"a": 1}):
            with self.subTest(junk=junk):
                out = _shape({"actions": junk})
                self.assertIsNone(out["champ_select"]["active_round"])
                self.assertFalse(out["champ_select"]["my_completed"])

    def test_trades_wrong_type(self):
        for junk in (5, {"a": 1}):
            with self.subTest(junk=junk):
                out = _shape({"trades": junk})
                self.assertEqual(out["champ_select"]["trades"], [])

    def test_swap_lists_wrong_type(self):
        for junk in (5, {"a": 1}):
            with self.subTest(junk=junk):
                out = _shape({"positionSwaps": junk, "pickOrderSwaps": junk})
                self.assertEqual(out["champ_select"]["position_swaps"], [])
                self.assertEqual(out["champ_select"]["pick_order_swaps"], [])

    def test_swap_entries_rejects_a_non_list_directly(self):
        """The helper is public; guard it at its own boundary too."""
        for junk in (5, {"a": 1}, True):
            with self.subTest(junk=junk):
                self.assertEqual(swap_entries(junk), [])

    def test_timer_wrong_type(self):
        """``(sess.get("timer") or {})`` passes a truthy STRING straight on."""
        for junk in ("BAN_PICK", 5):
            with self.subTest(junk=junk):
                out = _shape({"timer": junk})
                self.assertIsNone(out["champ_select"]["phase"])

    def test_a_real_timer_phase_still_reads_through(self):
        out = _shape({"timer": {"phase": "BAN_PICK"}})
        self.assertEqual(out["champ_select"]["phase"], "BAN_PICK")


class ArenaSubteamShapingIsNotFatal(unittest.TestCase):
    """``arena_teams`` guards one ``int()`` and left its sibling bare.

    ``int(sess.get("localPlayerCellId", -1))`` sits in try/except at
    ``lcu/champ_select_shape.py:122-125``; the member comparison nine lines
    later called ``int(m.get("cellId", -2))`` with no guard. A default only
    fires for an ABSENT key, so a present-and-null cellId reached ``int()``.
    """

    def test_member_cell_id_present_and_null(self):
        teams = arena_teams({"localPlayerCellId": 0,
                             "additionalSubteamData": [
                                 {"id": 1, "members": [{"cellId": None}]}]})
        self.assertEqual(len(teams), 1)
        self.assertFalse(teams[0]["is_me"])

    def test_member_cell_id_not_a_number(self):
        teams = arena_teams({"localPlayerCellId": 0,
                             "additionalSubteamData": [
                                 {"id": 1, "members": [{"cellId": "abc"}]}]})
        self.assertEqual(len(teams), 1)
        self.assertFalse(teams[0]["is_me"])

    def test_members_wrong_type(self):
        teams = arena_teams({"localPlayerCellId": 0,
                             "additionalSubteamData": [{"id": 1, "members": 5}]})
        self.assertEqual(teams[0]["cells"], [])

    def test_local_cell_wrong_type_does_not_break_the_member_scan(self):
        """Found by mutation testing, not by reading.

        ``arena_teams`` guarded this ``int()`` from the start, but nothing
        exercised the guard: every arena test passed a well-formed
        ``localPlayerCellId``, so deleting the try/except stayed GREEN.
        The classic shape of an untested guard on a non-default path.
        """
        for junk in (None, "abc", {}, []):
            with self.subTest(junk=junk):
                teams = arena_teams({"localPlayerCellId": junk,
                                     "additionalSubteamData": [
                                         {"id": 1, "members": [{"cellId": 0}]}]})
                self.assertEqual(len(teams), 1)
                self.assertFalse(teams[0]["is_me"])

    def test_subteam_data_wrong_type(self):
        for junk in (5, {"a": 1}, "xy"):
            with self.subTest(junk=junk):
                self.assertEqual(arena_teams({"additionalSubteamData": junk}), [])

    def test_is_me_still_resolves_on_a_well_formed_roster(self):
        """The guard must not cost the match it is guarding."""
        teams = arena_teams({"localPlayerCellId": 3,
                             "additionalSubteamData": [
                                 {"id": 1, "members": [{"cellId": 0}]},
                                 {"id": 2, "members": [{"cellId": 3}]}]})
        self.assertFalse(teams[0]["is_me"])
        self.assertTrue(teams[1]["is_me"])

    def test_arena_shaping_survives_a_malformed_roster_end_to_end(self):
        out = _shape({"gameData": {"queue": {"id": 1750}},
                      "additionalSubteamData": [
                          {"id": 1, "members": [{"cellId": None}]}]})
        self.assertIn("arena_teams", out["champ_select"])


class RiotNameObfuscationHoldsUnderMalformedInput(unittest.TestCase):
    """Riot compliance 2026-08-11 is a PRODUCER-side property.

    ``lcu/champ_select_shape.py:206-210`` states the obfuscation happens
    here so no downstream renderer can leak a name by forgetting to mask.
    That property must survive every malformed shape above, not just the
    happy path - a guard that fails open on a wrong-typed cell id would
    reinstate the leak silently.
    """

    _NAMES = ("RealSummonerName", "AnotherPlayer", "InternalName")

    def _payload_with_names(self, local_cell):
        return {
            "localPlayerCellId": local_cell,
            "myTeam": [
                {"cellId": 0, "summonerName": self._NAMES[0],
                 "displayName": self._NAMES[0], "gameName": self._NAMES[0]},
                {"cellId": 1, "summonerName": self._NAMES[1],
                 "summonerInternalName": self._NAMES[2]},
            ],
            "theirTeam": [{"cellId": 5, "summonerName": self._NAMES[1]}],
        }

    def _assert_no_names(self, out):
        blob = repr(out)
        for name in self._NAMES:
            self.assertNotIn(name, blob)

    def test_no_real_name_survives_shaping(self):
        self._assert_no_names(_shape(self._payload_with_names(0)))

    def test_no_real_name_survives_a_wrong_typed_local_cell(self):
        for local_cell in (None, "abc", {}, [], -1, True):
            with self.subTest(local_cell=local_cell):
                self._assert_no_names(_shape(self._payload_with_names(local_cell)))

    def test_labels_are_positional_and_the_local_slot_says_you(self):
        out = _shape(self._payload_with_names(1))
        names = [p["summonerName"] for p in out["champ_select"]["my_team"]]
        self.assertEqual(names, ["Ally 1", "You"])

    def test_enemy_slots_are_obfuscated_even_though_no_cell_matches(self):
        out = _shape(self._payload_with_names(0))
        self.assertEqual(
            [p["summonerName"] for p in out["champ_select"]["their_team"]],
            ["Ally 1"],
        )


class StringCellIdsResolveTheLocalPlayer(unittest.TestCase):
    """The s155 sibling: the resolver was fixed, the shaper was not.

    ``tools/lcu_agent.py:919-921`` records the measurement (2026-05-09,
    s155)::

        cast to int explicitly - some LCU builds emit actorCellId /
        localPlayerCellId as JSON strings depending on the patch, which
        made the equality check silently miss.

    That cast went into the agent's lock_pick COMMAND handler only. The
    shaping path kept a bare ``==``. MEASURED across all four type
    pairings against the pre-fix module:

        localPlayerCellId / cellId    my_champion   local_cell
        int  / int                    67            1
        str  / str                    67            -1
        str  / int                    0             -1
        int  / str                    0             1

    So the two halves fail INDEPENDENTLY and neither raises:
    ``my_champion`` reads 0 - the dashboard lock button never activates -
    whenever the two types are MIXED, and ``local_cell`` is emitted as -1
    whenever ``localPlayerCellId`` is a string, which is what
    ``_csvResolveRole`` needs to read ``assignedPosition``. Silent
    degradation, which is why it outlived the resolver fix by 15 months.

    ``_obfuscated_name`` already coerced both sides, so the Riot name
    obfuscation held in all four pairings - asserted below so the
    coercion work cannot regress it.
    """

    @staticmethod
    def _session(local_cell, cell_id):
        return {
            "localPlayerCellId": local_cell,
            "myTeam": [{"cellId": cell_id, "championId": 67, "spell1Id": 4,
                        "spell2Id": 14, "assignedPosition": "bottom"}],
        }

    def test_mixed_cell_id_types_still_find_my_pick(self):
        """The silent miss: "1" == 1 is False, so the local cell vanished."""
        for local_cell, cell_id in (("1", 1), (1, "1"), ("1", "1"), (1, 1)):
            with self.subTest(local_cell=local_cell, cell_id=cell_id):
                cs = _shape(self._session(local_cell, cell_id))["champ_select"]
                self.assertEqual(cs["my_champion"], 67)
                self.assertEqual(cs["my_champion_locked"], 67)
                self.assertEqual(cs["my_summoners"], [4, 14])

    def test_string_local_cell_is_emitted_as_an_int(self):
        """-1 made the dashboard role resolver miss every slot."""
        for local_cell in ("1", 1):
            with self.subTest(local_cell=local_cell):
                cs = _shape(self._session(local_cell, 1))["champ_select"]
                self.assertEqual(cs["local_cell"], 1)

    def test_obfuscation_holds_across_every_cell_id_type_pairing(self):
        for local_cell, cell_id in (("1", 1), (1, "1"), ("1", "1"), (1, 1)):
            with self.subTest(local_cell=local_cell, cell_id=cell_id):
                cs = _shape(self._session(local_cell, cell_id))["champ_select"]
                self.assertEqual([p["summonerName"] for p in cs["my_team"]],
                                 ["You"])

    def test_uncoercible_local_cell_still_normalises_to_minus_one(self):
        """Pins the existing contract the coercion must not widen past."""
        for junk in (None, "abc", {}, []):
            with self.subTest(junk=junk):
                out = _shape({"localPlayerCellId": junk, "myTeam": []})
                self.assertEqual(out["champ_select"]["local_cell"], -1)


class HappyPathCharacterization(unittest.TestCase):
    """Pins the shape the rewrite must not move.

    ``tests/phase_b_champ_select/test_champ_select_shape_rc2.py`` already
    characterizes the extraction against real payloads; these assertions
    exist so the guard work above is provably value-preserving on the
    fields it touches.
    """

    _SESSION = {
        "gameData": {"queue": {"id": 420, "mapId": 11, "gameMode": "CLASSIC",
                               "type": "RANKED_SOLO_5x5", "category": "PvP"}},
        "localPlayerCellId": 1,
        "myTeam": [
            {"cellId": 0, "championId": 0, "championPickIntent": 22,
             "spell1Id": 4, "spell2Id": 7, "puuid": "p0"},
            {"cellId": 1, "championId": 67, "spell1Id": 4, "spell2Id": 14,
             "puuid": "p1", "assignedPosition": "bottom"},
        ],
        "theirTeam": [{"cellId": 5, "championId": 103}],
        "benchChampions": [{"championId": 1}],
        "timer": {"phase": "BAN_PICK"},
        "trades": [{"id": 9, "cellId": 5, "state": "AVAILABLE"}],
        "positionSwaps": [{"id": 1, "cellId": 0, "state": "SENT"}],
        "pickOrderSwaps": [{"id": 2, "cellId": 5, "state": "RECEIVED"}],
        "actions": [[{"actorCellId": 1, "type": "pick", "championId": 67,
                      "completed": True, "isInProgress": False},
                     {"actorCellId": 5, "type": "pick", "championId": 103,
                      "completed": False, "isInProgress": True}]],
    }

    def test_full_session_shape_is_unchanged(self):
        cs = _shape(self._SESSION)["champ_select"]
        self.assertEqual(cs["queue_id"], 420)
        self.assertFalse(cs["is_aram"])
        self.assertEqual(cs["local_cell"], 1)
        self.assertEqual(cs["my_champion"], 67)
        self.assertEqual(cs["my_champion_locked"], 67)
        self.assertEqual(cs["my_champion_intent"], 0)
        self.assertTrue(cs["my_completed"])
        self.assertEqual(cs["my_summoners"], [4, 14])
        self.assertEqual(cs["bench"], [1])
        self.assertEqual(cs["phase"], "BAN_PICK")
        self.assertEqual(cs["active_round"], {"type": "pick", "cell_ids": [5]})
        self.assertEqual(cs["trades"],
                         [{"id": 9, "cellId": 5, "state": "AVAILABLE"}])
        self.assertEqual(cs["position_swaps"],
                         [{"id": 1, "cellId": 0, "state": "SENT"}])
        self.assertEqual(cs["pick_order_swaps"],
                         [{"id": 2, "cellId": 5, "state": "RECEIVED"}])
        self.assertNotIn("arena_teams", cs)

    def test_hover_still_falls_back_to_the_pick_intent(self):
        """s171 hover fix - championId is 0 until lock."""
        cs = _shape(self._SESSION)["champ_select"]
        self.assertEqual(cs["my_team"][0]["championId"], 22)
        self.assertEqual(cs["my_team"][0]["champion_pick_intent"], 22)
        self.assertEqual(cs["my_team"][0]["champion_locked"], 0)

    def test_non_champ_select_phase_spends_no_round_trip(self):
        calls = []

        def request(method, path, body=None):
            calls.append(path)
            return {}, None

        self.assertEqual(shape_champ_select(request, "Lobby"), {})
        self.assertEqual(calls, [])

    def test_a_non_dict_session_yields_cs_debug_only(self):
        out = _shape(None)
        self.assertEqual(out, {"cs_debug": {"cs_session_is_dict": False}})
        self.assertNotIn("champ_select", out)


if __name__ == "__main__":
    unittest.main()

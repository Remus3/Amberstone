"""lcu/snapshot_shape.py - malformed-LCU-payload hardening (lane 8 cycle 35).

``shape_snapshot`` shapes a payload RC does not author: the League client
publishes it and Riot changes its field types between builds. The module's
own contract is QUIET DEGRADATION - ``_lookup_summoner_by_id`` documents
"Quiet failure - callers must tolerate missing data", ``_slim_lobby_member``
documents "Returns None when ``m`` isn't a dict so the caller can drop
garbage without a try/except", and ``_maybe_refresh_mastery`` documents
"or None when LCU isn't reachable or the response shape is unexpected".

Three paths broke that contract by RAISING instead, and each one costs the
WHOLE snapshot rather than the one bad field:

  * ``_resolve_local_summoner_id`` int-cast ``summonerId`` unguarded, while
    ``_slim_lobby_member`` guards the SAME field with try/except.
  * ``_maybe_refresh_mastery`` guarded ``championId`` with try/except and
    left its six sibling int-casts bare.
  * the InProgress block read ``gflow.get("gameData", {}).get(...)``, and a
    ``{}`` default does not apply when the key is PRESENT AND NULL - which
    is how LCU routinely emits an absent sub-object.

Blast radius, measured at both call sites and corrected by an adversarial
review that found the first wording both overstated and understated:

  * LIVE path. ``tools/lcu_agent._state_push_loop`` wraps at :1611 and
    catches at :1641, so the ENTIRE ``/upload-lcu`` post at :1614 is skipped
    for that tick, and so are all three edge-fires below it - team-context
    (:1624), last-match ingest (:1631) and the Arena augment force-scan
    (:1638). It does log ``[state loop err]`` at :1642, but it does NOT bump
    ``consecutive_fail``, so the loop never backs off. At ``INTERVAL = 1.0s``
    a persistently mistyped field freezes the dashboard's LCU panel while
    re-failing once a second.
  * DORMANT path. ``dashboard/_lcu_inprocess.lcu_summary_inprocess`` calls
    ``shape_snapshot`` at :258 and catches at :260, returning None so the
    caller falls back to the :8889 relay. The SILENCE half of this bullet is
    HISTORY as of 2026-09-11 and is kept only so the original radius reads
    straight: RM-312 added a throttled WARN inside the module
    (``_log_degrade``, ``dashboard/_lcu_inprocess.py:132``) and RM-405 added a
    deliberately DISTINCT one at the caller seam one frame up
    (``dashboard/_state_builder.py:177``), so the degrade is now traced at
    both layers. The RETURN contract is unchanged. This half is gated on
    ``RC_LCU_INPROCESS == "1"`` (``_state_builder.py:173``) and landed DARK,
    so it is a latent radius, not a live one.

All authored content here is 7-bit ASCII.
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from lcu.snapshot_shape import (  # noqa: E402
    _SUMMONER_LOOKUP_CACHE_MAX,
    _lookup_summoner_by_id,
    _reset_mastery_cache_for_tests,
    _reset_summoner_lookup_cache_for_tests,
    _slim_lobby_member,
    _summoner_lookup_cache,
    shape_snapshot,
)

_PHASE = "/lol-gameflow/v1/gameflow-phase"
_LOBBY = "/lol-lobby/v2/lobby"
_CURRENT = "/lol-summoner/v1/current-summoner"
_MASTERY = "/lol-champion-mastery/v1/local-player/champion-mastery"
_GAMEFLOW = "/lol-gameflow/v1/session"


def _fake_request(routes: dict):
    """Agent transport contract: (method, path, body=None) -> (payload, err).

    Unknown paths answer (None, "404") exactly like LCU does for a resource
    that is not live in the current phase.
    """
    def request(method, path, body=None):
        if path in routes:
            return routes[path], None
        return None, "404"
    return request


class SnapshotShapeMalformedTest(unittest.TestCase):
    """One wrong-shape LCU field must not cost the whole snapshot."""

    def setUp(self):
        _reset_mastery_cache_for_tests()
        _reset_summoner_lookup_cache_for_tests()

    def tearDown(self):
        _reset_mastery_cache_for_tests()
        _reset_summoner_lookup_cache_for_tests()

    # -- W1: non-numeric summonerId ------------------------------------

    def test_non_numeric_summoner_id_does_not_destroy_snapshot(self):
        """A summonerId LCU emits as a non-numeric string degrades to None.

        Before the fix this raised ValueError out of shape_snapshot, so the
        agent skipped the whole /upload-lcu post for the tick.
        """
        request = _fake_request({
            _PHASE: "Lobby",
            _LOBBY: {"gameConfig": {"queueId": 450}, "members": []},
            _CURRENT: {"summonerId": "abc"},
        })
        snap = shape_snapshot(request, {})
        self.assertEqual(snap["phase"], "Lobby")
        # The lobby block still shapes; only the id-derived enrichment is lost.
        self.assertEqual(snap["lobby"]["queue_id"], 450)
        self.assertEqual(snap["lobby"]["queue_name"], "ARAM")
        # A summoner_id that could not be parsed is never published.
        self.assertNotIn("summoner_id", snap)

    def test_dict_valued_summoner_id_does_not_destroy_snapshot(self):
        """TypeError arm of the same guard (LCU emitting an object)."""
        request = _fake_request({
            _PHASE: "Lobby",
            _LOBBY: {"gameConfig": {"queueId": 450}, "members": []},
            _CURRENT: {"summonerId": {"id": 5}},
        })
        snap = shape_snapshot(request, {})
        self.assertEqual(snap["phase"], "Lobby")
        self.assertNotIn("summoner_id", snap)

    # -- W2: malformed mastery entry -----------------------------------

    def test_malformed_mastery_field_keeps_the_sibling_champions(self):
        """One bad championLevel must not delete every other champion.

        Before the fix the bare int() raised and the caller lost the whole
        snapshot - phase, lobby, champ_select and all.
        """
        request = _fake_request({
            _PHASE: "ChampSelect",
            _CURRENT: {"summonerId": 7},
            _MASTERY: [
                {"championId": 1, "championLevel": 7, "championPoints": 100},
                {"championId": 2, "championLevel": "unranked"},
                {"championId": 3, "championLevel": 4, "championPoints": 50},
            ],
        })
        snap = shape_snapshot(request, {})
        mastery = snap["mastery"]
        self.assertEqual(sorted(mastery), [1, 2, 3])
        # The good rows keep their real numbers.
        self.assertEqual(mastery[1]["level"], 7)
        self.assertEqual(mastery[1]["points"], 100)
        self.assertEqual(mastery[3]["level"], 4)
        # The unparseable field coerces to the same 0 an ABSENT field gets,
        # which is the meaning the existing `or 0` already assigned to it.
        self.assertEqual(mastery[2]["level"], 0)

    def test_malformed_mastery_points_field_is_coerced(self):
        """Every int-cast field is guarded, not just championLevel."""
        request = _fake_request({
            _PHASE: "ChampSelect",
            _CURRENT: {"summonerId": 7},
            # Every value here must be TRUTHY as well as unparseable. A
            # falsy one ({}, [], None, 0) is absorbed by the pre-existing
            # `or 0` and would pass identically against the UNFIXED module,
            # proving nothing - three of these were falsy on the first pass
            # and the adversarial review caught it.
            _MASTERY: [{
                "championId": 9,
                "championLevel": 5,
                "championPoints": "lots",
                "lastPlayTime": {"at": 1},
                "championPointsSinceLastLevel": [1],
                "championPointsUntilNextLevel": "x",
                "tokensEarned": "two",
            }],
        })
        snap = shape_snapshot(request, {})
        row = snap["mastery"][9]
        self.assertEqual(row["level"], 5)
        self.assertEqual(row["points"], 0)
        self.assertEqual(row["last_play_time"], 0)
        self.assertEqual(row["points_since_last_level"], 0)
        self.assertEqual(row["points_until_next_level"], 0)
        self.assertEqual(row["tokens_earned"], 0)

    # -- W8: null gameData ---------------------------------------------

    def test_null_game_data_does_not_destroy_snapshot(self):
        """`{"gameData": null}` is how LCU emits an absent sub-object.

        `.get("gameData", {})` returns the DEFAULT only when the key is
        missing, so a present-and-null value reached `.get` on None and
        raised AttributeError.
        """
        request = _fake_request({
            _PHASE: "InProgress",
            _GAMEFLOW: {"gameData": None},
            _CURRENT: {"summonerId": 7},
            _MASTERY: [],
        })
        snap = shape_snapshot(request, {})
        self.assertEqual(snap["phase"], "InProgress")
        self.assertNotIn("game_id", snap)
        self.assertFalse(snap["cherry_augment_open"])

    def test_non_dict_game_data_does_not_destroy_snapshot(self):
        """Same guard, non-null wrong type."""
        request = _fake_request({
            _PHASE: "GameStart",
            _GAMEFLOW: {"gameData": "pending"},
            _CURRENT: {"summonerId": 7},
            _MASTERY: [],
        })
        snap = shape_snapshot(request, {})
        self.assertEqual(snap["phase"], "GameStart")
        self.assertNotIn("game_id", snap)

    def test_valid_game_data_still_yields_game_id_and_arena_probe(self):
        """Characterization: the happy path is unchanged by the guard.

        Pins that hardening the null case did not cost the Arena augment
        probe, which is gated on the queue id read from the SAME sub-dict.
        """
        request = _fake_request({
            _PHASE: "InProgress",
            _GAMEFLOW: {"gameData": {"gameId": 12345, "queue": {"id": 1750}}},
            "/lol-cherry-game-intra-event/v1/augments": {
                "available": [{"id": 1}],
            },
            _CURRENT: {"summonerId": 7},
            _MASTERY: [],
        })
        snap = shape_snapshot(request, {})
        self.assertEqual(snap["game_id"], "12345")
        self.assertTrue(snap["cherry_augment_open"])

    def test_zero_game_id_is_still_suppressed(self):
        """Characterization: gameId "0" means no game and is not published."""
        request = _fake_request({
            _PHASE: "InProgress",
            _GAMEFLOW: {"gameData": {"gameId": 0}},
            _CURRENT: {"summonerId": 7},
            _MASTERY: [],
        })
        snap = shape_snapshot(request, {})
        self.assertNotIn("game_id", snap)

    # -- W3: non-numeric local_summoner_id on the re-exported helper ----

    def test_slim_lobby_member_tolerates_bad_local_summoner_id(self):
        """`_slim_lobby_member` is re-exported through tools/lcu_agent.

        Its docstring promises totality over garbage ("Returns None when m
        isn't a dict"), so the is_self comparison must not raise either.
        """
        request = _fake_request({})
        row = _slim_lobby_member(
            request,
            {"summonerId": 11, "gameName": "Moon", "tagLine": "NA1"},
            local_summoner_id="not-an-id",
        )
        self.assertIsNotNone(row)
        self.assertFalse(row["is_self"])
        self.assertEqual(row["riot_id"], "Moon#NA1")

    def test_slim_lobby_member_still_matches_self_by_id(self):
        """Characterization: the real is_self match is unchanged."""
        request = _fake_request({})
        row = _slim_lobby_member(
            request,
            {"summonerId": 11, "gameName": "Moon", "tagLine": "NA1"},
            local_summoner_id=11,
        )
        self.assertTrue(row["is_self"])

    # -- W4: unbounded per-process lookup cache -------------------------

    def test_summoner_lookup_cache_is_bounded(self):
        """The cache had a TTL but no eviction, so it grew for process life.

        The dashboard process runs for days across many lobbies.
        """
        for sid in range(_SUMMONER_LOOKUP_CACHE_MAX + 25):
            _summoner_lookup_cache[sid] = {"data": {}, "fetched_at": 1.0}
        # Drive one real insert through the guarded path.
        routes = {"/lol-summoner/v1/summoners/99999": {"gameName": "X"}}
        _slim_lobby_member(
            _fake_request(routes),
            {"summonerId": 99999},
            local_summoner_id=1,
            enrich=True,
        )
        self.assertLessEqual(len(_summoner_lookup_cache),
                             _SUMMONER_LOOKUP_CACHE_MAX)

    def test_cache_bound_holds_when_nothing_has_expired_yet(self):
        """Covers the LRU arm, not just the expired-entry arm.

        The first prune loop drops TTL-expired rows; if a burst fills the
        cache faster than the 10-minute TTL, only the second (oldest-first)
        loop can hold the bound. A test that pre-ages every row exercises
        the first loop only and would pass with the second one deleted.
        """
        now = time.time()
        for sid in range(_SUMMONER_LOOKUP_CACHE_MAX + 10):
            # Fresh rows: nothing is eligible for TTL eviction.
            _summoner_lookup_cache[sid] = {"data": {}, "fetched_at": now}
        routes = {"/lol-summoner/v1/summoners/77777": {"gameName": "Y"}}
        _slim_lobby_member(
            _fake_request(routes),
            {"summonerId": 77777},
            local_summoner_id=1,
            enrich=True,
        )
        self.assertLessEqual(len(_summoner_lookup_cache),
                             _SUMMONER_LOOKUP_CACHE_MAX)
        # The row just fetched survived the prune that made room for it.
        self.assertIn(77777, _summoner_lookup_cache)

    # -- adversarial-review findings ------------------------------------

    def test_infinity_does_not_escape_the_coercion_guard(self):
        """`int(float("inf"))` raises OverflowError, not ValueError.

        OverflowError is an ArithmeticError, so a guard catching only
        (TypeError, ValueError) does not stop it. This is reachable, not
        theoretical: json.loads accepts the non-standard `Infinity` literal
        unless parse_constant is supplied, and neither transport supplies
        one (tools/lcu_agent.py:222, lcu/lcu_client.py:197).
        """
        request = _fake_request({
            _PHASE: "Lobby",
            _LOBBY: {"gameConfig": {"queueId": 450}, "members": []},
            _CURRENT: {"summonerId": float("inf")},
        })
        snap = shape_snapshot(request, {})
        self.assertEqual(snap["phase"], "Lobby")
        self.assertNotIn("summoner_id", snap)

    def test_infinite_mastery_field_does_not_escape(self):
        """Same OverflowError arm, reached through the mastery loop."""
        request = _fake_request({
            _PHASE: "ChampSelect",
            _CURRENT: {"summonerId": 7},
            _MASTERY: [{"championId": 4, "championPoints": float("inf")}],
        })
        snap = shape_snapshot(request, {})
        self.assertEqual(snap["mastery"][4]["points"], 0)

    def test_lookup_by_id_coerces_before_building_the_request_path(self):
        """The traversal containment must be intrinsic, not accidental.

        `_lookup_summoner_by_id` interpolates sid into a request path, and
        `tools/lcu_agent.py:254` re-exports it with an UNENFORCED `sid: int`
        annotation and no coercion. That re-export has no non-test callers
        today, so the old containment held only by luck. Assert the helper
        refuses a traversal string on its own.
        """
        seen = []

        def spy(method, path, body=None):
            seen.append(path)
            return None, "404"

        result = _lookup_summoner_by_id(spy, "../../../lol-rso-auth/v1/session")
        self.assertIsNone(result)
        # Rejected before any request was issued at all.
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()

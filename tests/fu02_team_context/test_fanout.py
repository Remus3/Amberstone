"""Champ-select hook + fan-out tests for FU02.

Covers (RC_TICKET_FU02 acceptance #5 + #6 + #9):

  - POST /api/team-context/refresh dispatches priority-1 + priority-2
    work in correct order via the in-process fan-out worker.
  - Each riot_api response mutates the cache atomically; dashboard
    sees fields populate progressively.
  - Worker flips partial=False once both priority tiers complete.
  - Ranked queue (420/440) gate: summoner_name is blanked at the
    storage layer regardless of what LCU posted.
  - Soft-fail: a Riot API None response must not break other entries
    or the partial→complete transition.
  - Default dispatcher refuses to spawn when API key isn't configured
    (skeleton-only mode).
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import riot_api as RA            # noqa: E402
from core import riot_api_cache as RIC     # noqa: E402
from dashboard import routes_team_context as RTC   # noqa: E402


def _h(headers=None):
    """Minimal _send-capturing handler stub."""
    class _Stub:
        def __init__(self, hdrs):
            self.headers = hdrs or {}
            self.client_address = ("127.0.0.1", 0)
            self.captured = {}
        def _send(self, code, body, ctype):
            self.captured = {"code": code, "body": body, "ctype": ctype}
    return _Stub(headers)


class _BaseFanoutCase(unittest.TestCase):
    """Shared setup: bridge auth mocked, riot_api configured, fresh cache."""

    def setUp(self):
        RTC._clear()
        # Bridge auth → 200 path.
        self._is_cfg = mock.patch.object(
            RTC._bridge, "is_configured", return_value=True)
        self._secret = mock.patch.object(
            RTC._bridge, "shared_secret", return_value="test-secret")
        self._is_cfg.start()
        self._secret.start()
        # Reset rate limiter + cache singleton + key cache so cases are isolated.
        RA._reset_bucket_for_tests()
        self._tmp = tempfile.TemporaryDirectory()
        RIC._reset_for_tests(db_path=Path(self._tmp.name) / "riot_cache.db")
        # Force riot_api.is_configured() → True without touching the
        # real key file. The fan-out helpers themselves are mocked, so
        # this is just the gate in _default_dispatch_fanout.
        self._orig_key_cache = RA._KEY_CACHE
        RA._KEY_CACHE = "RGAPI-test-key-aaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    def tearDown(self):
        self._is_cfg.stop()
        self._secret.stop()
        RA._KEY_CACHE = self._orig_key_cache
        RA._reset_bucket_for_tests()
        RIC._reset_for_tests(db_path=None)
        RTC._clear()
        self._tmp.cleanup()

    def _post(self, body):
        h = _h({"Authorization": "Bearer test-secret"})
        RTC._serve_refresh_post(h, body)
        return h


class TestDispatcherWiring(_BaseFanoutCase):
    """The POST handler must call _FANOUT_DISPATCHER with the segmented
    rosters + queue ID, after the skeleton has been stored."""

    def test_dispatcher_called_with_segmented_rosters(self):
        calls = []
        def recorder(allies, enemies, queue_id):
            calls.append((list(allies), list(enemies), queue_id))
        with mock.patch.object(RTC, "_FANOUT_DISPATCHER", recorder):
            self._post({
                "queue_id": 400,
                "roster": [
                    {"puuid": "P1", "summoner_name": "A1",
                     "team_id": 100, "locked_champion": "Camille"},
                    {"puuid": "P2", "summoner_name": "B1",
                     "team_id": 200, "locked_champion": "Yasuo"},
                ],
            })
        self.assertEqual(len(calls), 1)
        allies, enemies, qid = calls[0]
        self.assertEqual(qid, 400)
        self.assertEqual(len(allies), 1)
        self.assertEqual(len(enemies), 1)
        self.assertEqual(allies[0]["puuid"], "P1")
        self.assertEqual(enemies[0]["puuid"], "P2")

    def test_dispatcher_failure_does_not_break_post(self):
        def boom(*_a, **_k):
            raise RuntimeError("simulated dispatcher crash")
        with mock.patch.object(RTC, "_FANOUT_DISPATCHER", boom):
            with self.assertLogs("rc.routes_team_context", level="WARNING"):
                h = self._post({
                    "queue_id": 400,
                    "roster": [{"puuid": "P1", "team_id": 100,
                                "locked_champion": "Camille"}],
                })
        self.assertEqual(h.captured["code"], 200)
        # The skeleton is still cached even though dispatch crashed.
        cache = RTC.get_team_context()
        self.assertIsNotNone(cache)
        assert cache is not None
        self.assertEqual(cache["allies"][0]["puuid"], "P1")


class TestRankedNameBlanking(_BaseFanoutCase):
    """Acceptance #5: queue_id 420/440 → summoner_name blanked at storage."""

    def test_solo_queue_blanks_names(self):
        with mock.patch.object(RTC, "_FANOUT_DISPATCHER", lambda *_a: None):
            self._post({
                "queue_id": 420,
                "roster": [
                    {"puuid": "P1", "summoner_name": "Hidden#NA1",
                     "team_id": 100, "locked_champion": "Camille"},
                ],
            })
        cache = RTC.get_team_context()
        assert cache is not None
        self.assertEqual(cache["allies"][0]["summoner_name"], "")
        # PUUID still flows - only the name is suppressed.
        self.assertEqual(cache["allies"][0]["puuid"], "P1")
        # Champion + team_id still present so the dashboard can render.
        self.assertEqual(cache["allies"][0]["locked_champion"], "Camille")

    def test_flex_queue_blanks_names(self):
        with mock.patch.object(RTC, "_FANOUT_DISPATCHER", lambda *_a: None):
            self._post({
                "queue_id": 440,
                "roster": [
                    {"puuid": "P1", "summoner_name": "Hidden#NA1",
                     "team_id": 100, "locked_champion": "Camille"},
                ],
            })
        cache = RTC.get_team_context()
        assert cache is not None
        self.assertEqual(cache["allies"][0]["summoner_name"], "")

    def test_normal_queue_keeps_names(self):
        with mock.patch.object(RTC, "_FANOUT_DISPATCHER", lambda *_a: None):
            self._post({
                "queue_id": 400,   # normal draft
                "roster": [
                    {"puuid": "P1", "summoner_name": "Visible#NA1",
                     "team_id": 100, "locked_champion": "Camille"},
                ],
            })
        cache = RTC.get_team_context()
        assert cache is not None
        self.assertEqual(cache["allies"][0]["summoner_name"], "Visible#NA1")


class TestFanoutWorker(_BaseFanoutCase):
    """Drive the worker directly so we can assert progressive cache
    mutation. The default dispatcher is bypassed; we hand the worker
    a deterministic roster + mock the riot_api endpoints."""

    def _seed_skeleton(self, queue_id: int = 400) -> tuple[list, list]:
        roster = [
            {"puuid": "P-ALLY1", "team_id": 100, "locked_champion": "Camille"},
            {"puuid": "P-ALLY2", "team_id": 100, "locked_champion": "Jax"},
            {"puuid": "P-ENEMY", "team_id": 200, "locked_champion": "Yasuo"},
        ]
        with mock.patch.object(RTC, "_FANOUT_DISPATCHER", lambda *_a: None):
            self._post({"queue_id": queue_id, "roster": roster})
        cache = RTC.get_team_context()
        assert cache is not None
        return list(cache["allies"]), list(cache["enemies"])

    def test_priority_1_populates_rank_and_mastery(self):
        allies, enemies = self._seed_skeleton()
        rank_payload = [{"queueType": "RANKED_SOLO_5x5", "tier": "GOLD",
                         "rank": "II", "leaguePoints": 12}]
        mastery_payload = {"championPoints": 41_500}

        # All endpoints stubbed to deterministic responses.
        with mock.patch.object(RA, "get_summoner_rank",
                               return_value=rank_payload), \
             mock.patch.object(RA, "get_champion_mastery",
                               return_value=mastery_payload), \
             mock.patch.object(RA, "get_recent_matches",
                               return_value=[]), \
             mock.patch.object(RTC, "_champ_name_to_id",
                               return_value=60):
            RTC._fanout_worker(allies, enemies, queue_id=400)

        cache = RTC.get_team_context()
        assert cache is not None
        for entry in cache["allies"] + cache["enemies"]:
            self.assertEqual(entry["rank"], "GOLD II 12 LP")
            self.assertEqual(entry["mastery_on_locked"], 41_500)
        # Worker drained → partial flips False.
        self.assertFalse(cache["partial"])

    def test_priority_2_populates_mains_winrate_streak(self):
        allies, enemies = self._seed_skeleton()
        # Skip priority-1 by returning empty/None there, focus on priority-2.
        with mock.patch.object(RA, "get_summoner_rank",
                               return_value=[]), \
             mock.patch.object(RA, "get_champion_mastery",
                               return_value=None), \
             mock.patch.object(RA, "get_recent_matches",
                               return_value=["NA1_001", "NA1_002"]), \
             mock.patch.object(RA, "summarize_recent",
                               return_value={
                                   "mains": ["Camille", "Jax", "Fiora"],
                                   "win_rate_recent": 0.62,
                                   "w_l_streak_7": [5, 2],
                               }), \
             mock.patch.object(RTC, "_champ_name_to_id",
                               return_value=60):
            RTC._fanout_worker(allies, enemies, queue_id=400)

        cache = RTC.get_team_context()
        assert cache is not None
        for entry in cache["allies"] + cache["enemies"]:
            self.assertEqual(entry["mains"], ["Camille", "Jax", "Fiora"])
            self.assertAlmostEqual(entry["win_rate_recent"], 0.62, places=2)
            self.assertEqual(entry["w_l_streak_7"], [5, 2])
        self.assertFalse(cache["partial"])

    def test_per_entry_failure_does_not_kill_worker(self):
        allies, enemies = self._seed_skeleton()
        # Make P-ALLY1's mastery call raise; other entries must still complete.
        def mastery_side_effect(puuid, *_a, **_k):
            if puuid == "P-ALLY1":
                raise RuntimeError("simulated fault")
            return {"championPoints": 100}
        with mock.patch.object(RA, "get_summoner_rank",
                               return_value=[]), \
             mock.patch.object(RA, "get_champion_mastery",
                               side_effect=mastery_side_effect), \
             mock.patch.object(RA, "get_recent_matches",
                               return_value=[]), \
             mock.patch.object(RTC, "_champ_name_to_id",
                               return_value=60):
            with self.assertLogs("rc.routes_team_context", level="WARNING"):
                RTC._fanout_worker(allies, enemies, queue_id=400)

        cache = RTC.get_team_context()
        assert cache is not None
        # P-ALLY1 has no mastery (call failed); others got 100.
        ally1 = next(e for e in cache["allies"] if e["puuid"] == "P-ALLY1")
        ally2 = next(e for e in cache["allies"] if e["puuid"] == "P-ALLY2")
        enemy = cache["enemies"][0]
        self.assertEqual(ally1["mastery_on_locked"], 0)
        self.assertEqual(ally2["mastery_on_locked"], 100)
        self.assertEqual(enemy["mastery_on_locked"], 100)
        # partial still flips False - the worker drained both priorities.
        self.assertFalse(cache["partial"])

    def test_unranked_player_keeps_rank_blank(self):
        allies, enemies = self._seed_skeleton()
        with mock.patch.object(RA, "get_summoner_rank", return_value=[]), \
             mock.patch.object(RA, "get_champion_mastery", return_value=None), \
             mock.patch.object(RA, "get_recent_matches", return_value=[]), \
             mock.patch.object(RTC, "_champ_name_to_id", return_value=60):
            RTC._fanout_worker(allies, enemies, queue_id=400)
        cache = RTC.get_team_context()
        assert cache is not None
        # Unranked → rank stays "" (skeleton); pick_solo_rank returns None.
        for entry in cache["allies"]:
            self.assertEqual(entry["rank"], "")


class TestDefaultDispatchGate(_BaseFanoutCase):
    """`_default_dispatch_fanout` must skip when the API key is missing."""

    def test_no_key_skips_thread_spawn(self):
        # Override is_configured() → False; thread must not spawn.
        with mock.patch.object(RA, "is_configured", return_value=False):
            with mock.patch.object(threading, "Thread") as TStub:
                RTC._default_dispatch_fanout([], [], 400)
        self.assertFalse(TStub.called)

    def test_configured_spawns_daemon_thread(self):
        # _http_get is mocked so the thread won't actually hit the network
        # even if the worker runs to completion. We let it spawn, join
        # briefly, and assert the daemon flag.
        with mock.patch.object(RA, "is_configured", return_value=True), \
             mock.patch.object(RA, "_http_get",
                               return_value=RA._HttpResp(200, b"[]", {})):
            RTC._default_dispatch_fanout([], [], 400)
            # Snapshot the worker, then wait briefly for it to drain
            # (empty roster → loop body skipped → _mark_complete →
            # exit). 1s is generous.
            t = RTC._WORKER
        self.assertIsNotNone(t)
        assert t is not None
        self.assertTrue(t.daemon)
        t.join(timeout=2.0)
        self.assertFalse(t.is_alive())


class TestUpdateEntryAtomicity(_BaseFanoutCase):
    """`_update_entry` is the cache-mutation seam used by the worker;
    verify it preserves untouched fields and only mutates the matching
    puuid/team."""

    def setUp(self):
        super().setUp()
        # Seed a skeleton directly via _store so we don't depend on
        # the POST handler.
        RTC._store({
            "allies":  [
                {"puuid": "P1", "summoner_name": "A", "team_id": 100,
                 "locked_champion": "Camille", "rank": "",
                 "mastery_on_locked": 0, "w_l_streak_7": [0, 0],
                 "mains": [], "win_rate_recent": 0.0},
                {"puuid": "P2", "summoner_name": "B", "team_id": 100,
                 "locked_champion": "Jax", "rank": "",
                 "mastery_on_locked": 0, "w_l_streak_7": [0, 0],
                 "mains": [], "win_rate_recent": 0.0},
            ],
            "enemies": [],
            "refreshed_at": "2026-05-09T00:00:00Z",
            "partial": True,
            "queue_id": 400,
        })

    def test_update_only_matching_entry(self):
        RTC._update_entry("allies", "P1", rank="GOLD I 0 LP")
        cache = RTC.get_team_context()
        assert cache is not None
        p1 = next(e for e in cache["allies"] if e["puuid"] == "P1")
        p2 = next(e for e in cache["allies"] if e["puuid"] == "P2")
        self.assertEqual(p1["rank"], "GOLD I 0 LP")
        self.assertEqual(p2["rank"], "")     # untouched

    def test_update_unknown_puuid_silent(self):
        # Unknown PUUID → no-op, no exception, cache unchanged shape.
        RTC._update_entry("allies", "P-NOPE", rank="X")
        cache = RTC.get_team_context()
        assert cache is not None
        self.assertEqual(cache["allies"][0]["rank"], "")

    def test_update_unknown_team_silent(self):
        RTC._update_entry("aliens", "P1", rank="X")
        cache = RTC.get_team_context()
        assert cache is not None
        self.assertEqual(cache["allies"][0]["rank"], "")

    def test_update_bumps_refreshed_at(self):
        cache_before = RTC.get_team_context()
        assert cache_before is not None
        before_ts = cache_before["refreshed_at"]
        # Sleep one second so the second-resolution ISO stamp differs.
        time.sleep(1.05)
        RTC._update_entry("allies", "P1", rank="GOLD I 0 LP")
        cache_after = RTC.get_team_context()
        assert cache_after is not None
        self.assertNotEqual(cache_after["refreshed_at"], before_ts)


class TestStateBuilderProgressiveReveal(_BaseFanoutCase):
    """Once the worker mutates entries, build_state() picks up each
    revision on its next call - that's the dashboard's progressive
    reveal contract."""

    def test_state_carries_partial_then_complete(self):
        from dashboard._state_builder import build_state
        roster = [{"puuid": "P1", "team_id": 100,
                   "locked_champion": "Camille",
                   "summoner_name": "T#1"}]
        with mock.patch.object(RTC, "_FANOUT_DISPATCHER", lambda *_a: None):
            self._post({"queue_id": 400, "roster": roster})

        st1 = build_state()
        tc1 = st1["coach"]["team_context"]
        self.assertIsNotNone(tc1)
        self.assertTrue(tc1["partial"])
        self.assertEqual(tc1["allies"][0]["rank"], "")

        # Worker writes one field, then completes.
        RTC._update_entry("allies", "P1", rank="DIAMOND IV 5 LP")
        RTC._mark_complete()

        st2 = build_state()
        tc2 = st2["coach"]["team_context"]
        self.assertEqual(tc2["allies"][0]["rank"], "DIAMOND IV 5 LP")
        self.assertFalse(tc2["partial"])


if __name__ == "__main__":
    unittest.main()

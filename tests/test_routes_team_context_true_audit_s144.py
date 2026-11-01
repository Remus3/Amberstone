"""s144 lane 8 (true-audit) cycle 6: dashboard/routes_team_context.py.

Findings pinned here, each red before the fix:

  1. `_champ_name_to_id` globbed `data/ddragon/*/data/en_US/champion.json`,
     a path that does not exist in the tree (the tracked DDragon bundles live
     at `data/meta_build/ddragon/<ver>/champion.json`). Every lookup returned
     None, so the live fan-out never fetched mastery and `mastery_on_locked`
     was always 0. Every existing test mocked the resolver, so nothing saw it.
     It also cached a failed load as {} forever, picked `candidates[-1]` of an
     unsorted glob, and let a non-dict champion def raise AttributeError.
  2. The LCU agent re-POSTs on every lock / swap (tools/lcu_agent.py
     `_picks_signature`), and each POST replaced the cache with a fresh
     skeleton: rank, mains, win rate and streak already fetched were wiped.
  3. While a worker was alive a re-POST spawned nothing, and the live worker
     only walked the roster it started with, so a champion locked after the
     first POST never got mastery, a new lobby (dodge + requeue) was never
     enriched, and the old worker then flipped partial=False on it.
  4. A worker mid-pass wrote the mastery of a player's OLD champion into the
     re-POSTed entry that carries the NEW champion.
  5. A worker that had finished its work but not yet exited still blocked the
     next dispatch.
  6. `_as_int` let OverflowError (float inf) escape the handler.
  7. `get_team_context` handed out the live cache the worker mutates.
"""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from core import riot_api as RA
from core import riot_api_cache as RIC
from dashboard import routes_team_context as RTC
from tests._timing_budget import fleet_test_guard

_CHAMP_IDS = {"camille": 164, "jax": 24, "yasuo": 157, "fiora": 114,
              "annie": 1}


def _h():
    class _Stub:
        def __init__(self):
            self.headers = {}
            self.client_address = ("127.0.0.1", 0)
            self.captured = {}

        def _send(self, code, body, ctype):
            self.captured = {"code": code, "body": body, "ctype": ctype}
    return _Stub()


def _post(body):
    h = _h()
    with mock.patch.object(RTC, "_FANOUT_DISPATCHER", lambda *_a: None):
        RTC._serve_refresh_post(h, body)
    return h


def _roster(ally2_champ="Jax", enemy_puuid="P-ENEMY"):
    return [
        {"puuid": "P-ALLY1", "summoner_name": "Ally One", "team_id": 100,
         "locked_champion": "Camille"},
        {"puuid": "P-ALLY2", "summoner_name": "Ally Two", "team_id": 100,
         "locked_champion": ally2_champ},
        {"puuid": enemy_puuid, "summoner_name": "Foe", "team_id": 200,
         "locked_champion": "Yasuo"},
    ]


def _entry(puuid):
    cache = RTC.get_team_context()
    assert cache is not None
    for e in cache["allies"] + cache["enemies"]:
        if e["puuid"] == puuid:
            return e
    raise AssertionError(f"{puuid} not in cache")


def _mastery(_puuid, cid, *_a, **_k):
    return {"championPoints": int(cid) * 1000}


_RANK = [{"queueType": "RANKED_SOLO_5x5", "tier": "GOLD", "rank": "II",
          "leaguePoints": 12}]
_SUMMARY = {"mains": ["Camille"], "win_rate_recent": 0.5,
            "w_l_streak_7": [4, 3]}


class _Base(unittest.TestCase):
    def setUp(self):
        RTC._clear()
        RA._reset_bucket_for_tests()
        self._tmp = tempfile.TemporaryDirectory()
        RIC._reset_for_tests(db_path=Path(self._tmp.name) / "riot_cache.db")
        self._orig_key = RA._KEY_CACHE
        RA._KEY_CACHE = "RGAPI-test-key-aaaaaaaaaaaaaaaaaaaaaaaaaaaaa"  # rc-credential-scan: allow-fixture
        self._orig_names = RTC._CHAMP_NAME_TO_ID_CACHE

    def tearDown(self):
        RA._KEY_CACHE = self._orig_key
        RA._reset_bucket_for_tests()
        RIC._reset_for_tests(db_path=None)
        RTC._clear()
        RTC._CHAMP_NAME_TO_ID_CACHE = self._orig_names
        self._tmp.cleanup()

    def _riot(self, rank=None, summarize=None, mastery=None, matches=None):
        """Patch the four riot_api endpoints the worker calls."""
        return [
            mock.patch.object(RA, "get_summoner_rank",
                              side_effect=rank or (lambda *_a, **_k: _RANK)),
            mock.patch.object(RA, "get_champion_mastery",
                              side_effect=mastery or _mastery),
            mock.patch.object(RA, "get_recent_matches",
                              side_effect=matches
                              or (lambda *_a, **_k: ["NA1_1"])),
            mock.patch.object(RA, "summarize_recent",
                              side_effect=summarize
                              or (lambda *_a, **_k: dict(_SUMMARY))),
            mock.patch.object(RTC, "_champ_name_to_id",
                              side_effect=lambda n: _CHAMP_IDS.get(
                                  (n or "").lower())),
        ]

    def _run_worker(self, patches):
        for p in patches:
            p.start()
        try:
            cache = RTC.get_team_context()
            assert cache is not None
            RTC._fanout_worker(list(cache["allies"]), list(cache["enemies"]),
                               queue_id=int(cache["queue_id"]))
        finally:
            for p in reversed(patches):
                p.stop()


# -- 1. champion name -> id resolver --------------------------------------

def _write_bundle(root: Path, ver: str, champs: dict) -> None:
    d = root / ver
    d.mkdir(parents=True, exist_ok=True)
    data = {cid: ({"id": cid, "key": str(key), "name": name}
                  if key is not None else name)
            for cid, (key, name) in champs.items()}
    (d / "champion.json").write_text(json.dumps({"data": data}),
                                     encoding="utf-8")


class TestChampNameResolver(_Base):
    def test_resolves_from_the_tracked_ddragon_bundle(self):
        # No mock: the real tracked bundle under data/meta_build/ddragon.
        RTC._CHAMP_NAME_TO_ID_CACHE = None
        self.assertEqual(RTC._champ_name_to_id("Wukong"), 62)
        self.assertEqual(RTC._champ_name_to_id("Kai'Sa"), 145)
        self.assertEqual(RTC._champ_name_to_id("camille"), 164)

    def test_resolves_the_ddragon_id_spelling_too(self):
        RTC._CHAMP_NAME_TO_ID_CACHE = None
        self.assertEqual(RTC._champ_name_to_id("MonkeyKing"), 62)

    def test_prefers_latest_pulled_bundle(self):
        # 16.11.1 is the highest directory but not the pulled bundle (a
        # half-written pull, say); _index.json latest_pulled wins.
        root = Path(self._tmp.name) / "dd"
        _write_bundle(root, "16.11.1", {"Annie": (1, "Annie")})
        _write_bundle(root, "16.10.1", {"Annie": (1, "Annie"),
                                        "Newchamp": (999, "Newchamp")})
        (root / "_index.json").write_text(
            json.dumps({"latest_pulled": "16.10.1"}), encoding="utf-8")
        RTC._CHAMP_NAME_TO_ID_CACHE = None
        with mock.patch.object(RTC, "_DDRAGON_DIR", root, create=True):
            self.assertEqual(RTC._champ_name_to_id("Newchamp"), 999)

    def test_without_index_picks_highest_version_numerically(self):
        # Lexically "16.9.1" > "16.10.1"; the newest patch is 16.10.1.
        root = Path(self._tmp.name) / "dd"
        _write_bundle(root, "16.9.1", {"Annie": (1, "Annie")})
        _write_bundle(root, "16.10.1", {"Annie": (1, "Annie"),
                                        "Newchamp": (999, "Newchamp")})
        RTC._CHAMP_NAME_TO_ID_CACHE = None
        with mock.patch.object(RTC, "_DDRAGON_DIR", root, create=True):
            self.assertEqual(RTC._champ_name_to_id("Newchamp"), 999)

    def test_failed_load_is_retried_not_cached_forever(self):
        root = Path(self._tmp.name) / "dd"
        root.mkdir()
        RTC._CHAMP_NAME_TO_ID_CACHE = None
        with mock.patch.object(RTC, "_DDRAGON_DIR", root, create=True):
            self.assertIsNone(RTC._champ_name_to_id("Annie"))
            # A bundle caught mid-write (truncated JSON) loads as nothing...
            (root / "16.10.1").mkdir()
            (root / "16.10.1" / "champion.json").write_text(
                '{"data": {', encoding="utf-8")
            self.assertIsNone(RTC._champ_name_to_id("Annie"))
            # ...and the same path is re-read once it is whole.
            _write_bundle(root, "16.10.1", {"Annie": (1, "Annie")})
            self.assertEqual(RTC._champ_name_to_id("Annie"), 1)

    def test_malformed_champion_def_is_skipped(self):
        root = Path(self._tmp.name) / "dd"
        _write_bundle(root, "16.10.1", {"Annie": (1, "Annie"),
                                        "Broken": (None, "not-a-dict")})
        RTC._CHAMP_NAME_TO_ID_CACHE = None
        with mock.patch.object(RTC, "_DDRAGON_DIR", root, create=True):
            self.assertEqual(RTC._champ_name_to_id("Annie"), 1)

    def test_live_worker_fetches_mastery_by_resolved_id(self):
        RTC._CHAMP_NAME_TO_ID_CACHE = None
        _post({"queue_id": 400, "roster": [
            {"puuid": "P-W", "team_id": 100, "locked_champion": "Wukong"}]})
        seen = []

        def mastery(puuid, cid, *_a, **_k):
            seen.append(cid)
            return {"championPoints": 7}
        patches = self._riot(mastery=mastery)[:4]   # real resolver
        self._run_worker(patches)
        self.assertEqual(seen, [62])
        self.assertEqual(_entry("P-W")["mastery_on_locked"], 7)


# -- 2. re-POST keeps enrichment --------------------------------------------

class TestRepostCarry(_Base):
    def test_repost_keeps_enrichment_for_the_same_player(self):
        _post({"queue_id": 400, "roster": _roster()})
        self._run_worker(self._riot())
        self.assertEqual(_entry("P-ALLY1")["rank"], "GOLD II 12 LP")

        # Ally 2 swaps Jax -> Fiora; the agent re-POSTs the whole roster.
        _post({"queue_id": 400, "roster": _roster(ally2_champ="Fiora")})
        for puuid in ("P-ALLY1", "P-ALLY2", "P-ENEMY"):
            e = _entry(puuid)
            self.assertEqual(e["rank"], "GOLD II 12 LP", puuid)
            self.assertEqual(e["mains"], ["Camille"], puuid)
            self.assertEqual(e["w_l_streak_7"], [4, 3], puuid)
            self.assertAlmostEqual(e["win_rate_recent"], 0.5)
        self.assertEqual(_entry("P-ALLY1")["mastery_on_locked"], 164000)
        # Mastery belongs to the champion: a new lock starts from 0.
        self.assertEqual(_entry("P-ALLY2")["mastery_on_locked"], 0)
        self.assertTrue(RTC.get_team_context()["partial"])

    def test_carried_rate_limit_mark_clears_on_a_clean_fetch(self):
        # Verifier probe D (s144t006): retries exhausted -> marked; a later
        # re-POST carries the mark; the next worker's clean first pass must
        # clear it, or the panel says "rate limited" over complete data.
        _post({"queue_id": 400, "roster": _roster()})
        self._run_worker(self._riot())
        RTC._update_entry("allies", "P-ALLY2", riot_status="rate_limited")
        _post({"queue_id": 400, "roster": _roster()})
        self.assertEqual(_entry("P-ALLY2")["riot_status"], "rate_limited")
        self._run_worker(self._riot())
        self.assertEqual(_entry("P-ALLY2")["riot_status"], "")
        self.assertFalse(RTC.get_team_context()["partial"])

    def test_carried_mark_clears_after_a_relock_round(self):
        # Verifier probe C: marked, then re-locked mid-worker; the follow-up
        # round fetches cleanly and must clear the carried mark.
        _post({"queue_id": 400, "roster": _roster()})
        fired = []

        def matches(puuid, *_a, **_k):
            if not fired:
                fired.append(1)
                RTC._update_entry("allies", "P-ALLY2",
                                  riot_status="rate_limited")
                _post({"queue_id": 400,
                       "roster": _roster(ally2_champ="Fiora")})
            return ["NA1_1"]
        self._run_worker(self._riot(matches=matches))
        self.assertEqual(_entry("P-ALLY2")["mastery_on_locked"], 114000)
        self.assertEqual(_entry("P-ALLY2")["riot_status"], "")

    def test_clean_entry_without_a_mark_does_not_move_refreshed_at(self):
        _post({"queue_id": 400, "roster": _roster()})
        self._run_worker(self._riot())
        before = RTC.get_team_context()["refreshed_at"]
        with mock.patch.object(RTC, "_now_iso", return_value="MOVED"):
            RTC._clear_rate_limited("allies", "P-ALLY1")
        self.assertEqual(RTC.get_team_context()["refreshed_at"], before)

    def test_carry_never_carries_names_past_the_ranked_blank(self):
        _post({"queue_id": 400, "roster": _roster()})
        _post({"queue_id": 420, "roster": _roster()})
        self.assertEqual(_entry("P-ALLY1")["summoner_name"], "")

    def test_new_player_gets_a_fresh_skeleton(self):
        _post({"queue_id": 400, "roster": _roster()})
        self._run_worker(self._riot())
        _post({"queue_id": 400, "roster": _roster(enemy_puuid="P-NEW")})
        self.assertEqual(_entry("P-NEW")["rank"], "")


# -- 3 + 4. a re-POST while the worker runs -------------------------------

class TestRepostDuringWorker(_Base):
    def test_lock_after_first_post_gets_mastery(self):
        _post({"queue_id": 400, "roster": _roster()})
        fired = []

        def matches(puuid, *_a, **_k):
            # First priority-2 call: priority-1 is done for everyone; ally 2
            # now swaps to Fiora and the agent re-POSTs.
            if not fired:
                fired.append(1)
                _post({"queue_id": 400,
                       "roster": _roster(ally2_champ="Fiora")})
            return ["NA1_1"]
        self._run_worker(self._riot(matches=matches))
        self.assertEqual(_entry("P-ALLY2")["locked_champion"], "Fiora")
        self.assertEqual(_entry("P-ALLY2")["mastery_on_locked"], 114000)
        for puuid in ("P-ALLY1", "P-ALLY2", "P-ENEMY"):
            self.assertEqual(_entry(puuid)["rank"], "GOLD II 12 LP", puuid)
        self.assertFalse(RTC.get_team_context()["partial"])

    def test_old_champion_mastery_never_lands_on_the_new_lock(self):
        _post({"queue_id": 400, "roster": _roster()})
        fired = []
        seen_before_refetch = []

        def rank(puuid, *_a, **_k):
            # Re-POST before the worker reaches ally 2 in priority-1.
            if puuid == "P-ALLY1" and not fired:
                fired.append(1)
                _post({"queue_id": 400,
                       "roster": _roster(ally2_champ="Fiora")})
            return _RANK

        def mastery(puuid, cid, *_a, **_k):
            if cid == 114:
                # What the panel showed for ally 2 until the re-fetch.
                seen_before_refetch.append(
                    _entry("P-ALLY2")["mastery_on_locked"])
            return _mastery(puuid, cid)
        self._run_worker(self._riot(rank=rank, mastery=mastery))
        self.assertEqual(seen_before_refetch, [0])
        self.assertEqual(_entry("P-ALLY2")["mastery_on_locked"], 114000)

    def test_swap_and_swap_back_keeps_mastery(self):
        # Verifier probe (s144t006): Jax -> Fiora during round 1, then back
        # to Jax during round 2. (P-ALLY2, Jax) was enriched in round 1, so
        # the worker must not need to re-fetch it - the points it already
        # has must come back with the lock.
        _post({"queue_id": 400, "roster": _roster()})
        fired = []

        def rank(puuid, *_a, **_k):
            if puuid == "P-ALLY1" and not fired:
                fired.append("fiora")
                _post({"queue_id": 400,
                       "roster": _roster(ally2_champ="Fiora")})
            return _RANK

        def mastery(puuid, cid, *_a, **_k):
            if cid == 114 and "jax" not in fired:
                fired.append("jax")
                _post({"queue_id": 400, "roster": _roster()})
            return _mastery(puuid, cid)
        self._run_worker(self._riot(rank=rank, mastery=mastery))
        self.assertEqual(fired, ["fiora", "jax"])
        self.assertEqual(_entry("P-ALLY2")["locked_champion"], "Jax")
        self.assertEqual(_entry("P-ALLY2")["mastery_on_locked"], 24000)
        self.assertFalse(RTC.get_team_context()["partial"])

    def test_update_entry_refuses_a_mastery_for_another_champion(self):
        _post({"queue_id": 400, "roster": _roster(ally2_champ="Fiora")})
        RTC._update_entry("allies", "P-ALLY2", only_if_champion="Jax",
                          mastery_on_locked=5)
        self.assertEqual(_entry("P-ALLY2")["mastery_on_locked"], 0)
        RTC._update_entry("allies", "P-ALLY2", only_if_champion="Fiora",
                          mastery_on_locked=6)
        self.assertEqual(_entry("P-ALLY2")["mastery_on_locked"], 6)

    def test_repost_into_a_tft_queue_gets_no_league_calls(self):
        _post({"queue_id": 400, "roster": _roster()})
        fired = []
        asked = []

        def matches(puuid, *_a, **_k):
            asked.append(puuid)
            if not fired:
                fired.append(1)
                _post({"queue_id": 1090, "roster": [
                    {"puuid": "P-TFT", "team_id": 100,
                     "locked_champion": ""}]})
            return ["NA1_1"]

        def rank(puuid, *_a, **_k):
            asked.append(puuid)
            return _RANK
        self._run_worker(self._riot(rank=rank, matches=matches))
        self.assertNotIn("P-TFT", asked)
        self.assertTrue(RTC.get_team_context()["partial"])

    def test_new_lobby_mid_worker_is_enriched_before_complete(self):
        _post({"queue_id": 400, "roster": _roster()})
        fired = []

        def matches(puuid, *_a, **_k):
            if not fired:
                fired.append(1)
                _post({"queue_id": 400, "roster": [
                    {"puuid": "P-N1", "team_id": 100,
                     "locked_champion": "Annie"},
                    {"puuid": "P-N2", "team_id": 200,
                     "locked_champion": "Fiora"}]})
            return ["NA1_1"]
        self._run_worker(self._riot(matches=matches))
        cache = RTC.get_team_context()
        self.assertFalse(cache["partial"])
        self.assertEqual(_entry("P-N1")["rank"], "GOLD II 12 LP")
        self.assertEqual(_entry("P-N1")["mastery_on_locked"], 1000)
        self.assertEqual(_entry("P-N2")["mains"], ["Camille"])
        self.assertEqual(_entry("P-N2")["mastery_on_locked"], 114000)


# -- 5. a settled worker does not block the next dispatch ----------------

class TestSettledWorkerDoesNotBlock(_Base):
    def test_dispatch_after_settle_spawns_a_worker(self):
        release = threading.Event()
        settled = threading.Event()
        real_info = RTC.log.info

        def info(msg, *args, **kw):
            if str(msg).startswith("team-context fan-out done"):
                settled.set()
                release.wait(5.0)
            return real_info(msg, *args, **kw)

        spawned = threading.Event()
        with mock.patch.object(RA, "is_configured", return_value=True), \
                mock.patch.object(RTC.log, "info", side_effect=info):
            RTC._default_dispatch_fanout([], [], 400)
            first = RTC._WORKER
            try:
                self.assertTrue(settled.wait(fleet_test_guard.budget(5.0)))
                with mock.patch.object(RTC, "_fanout_worker",
                                       lambda *_a, **_k: spawned.set()):
                    RTC._default_dispatch_fanout([], [], 400)
                    self.assertTrue(spawned.wait(fleet_test_guard.budget(5.0)))
            finally:
                release.set()
                if first is not None:
                    first.join(5.0)


# -- 6. _as_int overflow ---------------------------------------------------

class TestAsIntOverflow(_Base):
    def test_infinite_queue_and_team_ids_soft_fail(self):
        h = _post({"queue_id": float("inf"), "roster": [
            {"puuid": "P-X", "team_id": float("-inf"),
             "locked_champion": "Annie"}]})
        self.assertEqual(h.captured["code"], 200)
        cache = RTC.get_team_context()
        self.assertEqual(cache["queue_id"], 0)
        self.assertEqual(_entry("P-X")["team_id"], 0)


# -- 7. readers get a snapshot ---------------------------------------------

class TestSnapshot(_Base):
    def test_get_team_context_returns_a_copy(self):
        _post({"queue_id": 400, "roster": _roster()})
        snap = RTC.get_team_context()
        snap["allies"][0]["rank"] = "MUTATED"
        snap["allies"].append({"puuid": "P-FAKE"})
        snap["partial"] = False
        again = RTC.get_team_context()
        self.assertEqual(again["allies"][0]["rank"], "")
        self.assertEqual(len(again["allies"]), 2)
        self.assertTrue(again["partial"])

    def test_get_route_encodes_a_snapshot_taken_under_the_lock(self):
        # A worker write that lands while the body is being encoded (after
        # the lock is released) must not leak into this response.
        _post({"queue_id": 400, "roster": _roster()})
        real_dumps = json.dumps

        def dumps(obj, *a, **kw):
            RTC._update_entry("allies", "P-ALLY1", rank="LATE WRITE")
            return real_dumps(obj, *a, **kw)
        h = _h()
        with mock.patch.object(RTC.json, "dumps", side_effect=dumps):
            RTC._serve_get(h)
        body = json.loads(h.captured["body"])
        self.assertEqual(body["team_context"]["allies"][0]["rank"], "")
        self.assertEqual(_entry("P-ALLY1")["rank"], "LATE WRITE")

    def test_get_route_body_is_strict_json(self):
        _post({"queue_id": 400, "roster": _roster()})
        h = _h()
        RTC._serve_get(h)
        self.assertEqual(h.captured["code"], 200)
        body = json.loads(h.captured["body"])
        self.assertEqual(len(body["team_context"]["allies"]), 2)


if __name__ == "__main__":
    unittest.main()

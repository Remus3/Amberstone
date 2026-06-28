"""Riot API client tests for `core/riot_api.py` - FU02 fan-out main.

Covers (from RC_TICKET_FU02 acceptance #2 + #4 + #10):

  Rate limiter (DualBucket):
    - Dual-window math: short bucket fills before long.
    - acquire blocks up to timeout, returns False on exhaustion.
    - 429 cooldown imposes a minimum-wait floor on the next acquire.
    - snapshot() returns the currently-tracked counts.

  Endpoint wrappers - all six, with mocked _http_get:
    - get_account_by_riot_id: 200 -> returns parsed dict + caches immutable.
    - get_account_by_riot_id: cache hit short-circuits HTTP.
    - get_recent_matches: 200 list response.
    - get_recent_matches: empty puuid -> None without firing.
    - get_match: immutable cache.
    - get_match_timeline: separate cache key from get_match.
    - get_summoner_rank: 200 list, TTL-cached.
    - get_summoner_rank: empty list (unranked) round-trips via cache.
    - get_champion_mastery: 200 dict, TTL-cached.
    - get_champion_mastery: missing puuid OR champion_id -> None.

  Failure modes:
    - 401 / 403 logs WARNING, returns None.
    - 429 logs WARNING, sets bucket cooldown, returns None.
    - 5xx returns None.
    - URLError / TimeoutError returns None without crashing.
    - Missing API key file: every fn returns None, single warning logged.

  Helper renderers:
    - format_rank_entry shapes "TIER DIVISION LP LP".
    - pick_solo_rank prefers RANKED_SOLO_5x5; falls back to highest tier.
    - summarize_recent walks match details, picks top-3 mains, computes
      winrate + 7-game W/L streak.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import riot_api as RA                     # noqa: E402
from core import riot_api_cache as RIC              # noqa: E402
from core.riot_api import DualBucket                # noqa: E402


def _resp(status: int, body=None, headers: dict | None = None):
    """Build a fake _HttpResp (the lightweight namespace returned by
    riot_api._http_get)."""
    if body is None:
        payload = b""
    elif isinstance(body, (dict, list)):
        payload = json.dumps(body).encode("utf-8")
    else:
        payload = bytes(body)
    return RA._HttpResp(status, payload, dict(headers or {}))


class _ApiKeyTestCase(unittest.TestCase):
    """Mixin: patch _get_api_key to return a fake RGAPI- key + reset
    rate-limit bucket between tests so case ordering doesn't matter."""

    def setUp(self):
        self._orig_key_cache = RA._KEY_CACHE
        RA._KEY_CACHE = "RGAPI-test-key-aaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        RA._reset_bucket_for_tests()
        self._tmp = tempfile.TemporaryDirectory()
        RIC._reset_for_tests(db_path=Path(self._tmp.name) / "cache.db")

    def tearDown(self):
        RA._KEY_CACHE = self._orig_key_cache
        RA._reset_bucket_for_tests()
        RIC._reset_for_tests(db_path=None)
        self._tmp.cleanup()


class TestDualBucket(unittest.TestCase):
    def test_short_window_full_blocks(self):
        # Tight bucket: 3 reqs / 10s, 100 / 1000s. Fill the short side
        # first, then a 4th acquire with timeout=0 must return False.
        b = DualBucket(short_n=3, short_window_s=10.0,
                       long_n=100, long_window_s=1000.0)
        for _ in range(3):
            self.assertTrue(b.acquire(timeout_s=0.0))
        self.assertFalse(b.acquire(timeout_s=0.0))

    def test_long_window_full_blocks(self):
        b = DualBucket(short_n=100, short_window_s=1.0,
                       long_n=2, long_window_s=120.0)
        self.assertTrue(b.acquire(timeout_s=0.0))
        self.assertTrue(b.acquire(timeout_s=0.0))
        self.assertFalse(b.acquire(timeout_s=0.0))

    def test_429_cooldown_blocks_acquire(self):
        b = DualBucket(short_n=20, short_window_s=1.0,
                       long_n=100, long_window_s=120.0)
        b.note_429(retry_after_s=2.0)
        # Even with empty buckets, acquire must fail until cooldown clears.
        self.assertFalse(b.acquire(timeout_s=0.0))

    def test_snapshot_shape(self):
        b = DualBucket()
        b.acquire(timeout_s=0.0)
        snap = b.snapshot()
        self.assertEqual(snap["short_used"], 1)
        self.assertEqual(snap["short_cap"], 20)
        self.assertEqual(snap["long_used"], 1)
        self.assertEqual(snap["long_cap"], 100)
        self.assertGreaterEqual(snap["cooldown_remaining_s"], 0.0)


class TestKeyResolver(unittest.TestCase):
    def setUp(self):
        # Reset cache + warned-once flag so first-call WARNING fires
        # exactly once per case.
        RA._KEY_CACHE = None
        RA._KEY_WARNED_MISSING = False
        # Point the file path at a temp dir so we can flip presence.
        self._tmp = tempfile.TemporaryDirectory()
        self._stash_path = RA._API_KEY_FILE
        RA._API_KEY_FILE = Path(self._tmp.name) / "API-Key-Riot.txt"

    def tearDown(self):
        RA._API_KEY_FILE = self._stash_path
        RA._KEY_CACHE = None
        RA._KEY_WARNED_MISSING = False
        self._tmp.cleanup()

    def test_missing_file_returns_none_and_warns_once(self):
        with self.assertLogs("rc.riot_api", level="WARNING") as logs:
            self.assertIsNone(RA._get_api_key())
            # Second call - already warned, no new record.
            self.assertIsNone(RA._get_api_key())
        # Only one WARNING about the missing file; subsequent silent.
        self.assertEqual(
            sum(1 for r in logs.output if "not found" in r),
            1,
        )

    def test_invalid_format_returns_none(self):
        RA._API_KEY_FILE.write_text("not-a-real-key", encoding="utf-8")
        with self.assertLogs("rc.riot_api", level="WARNING"):
            self.assertIsNone(RA._get_api_key())

    def test_valid_key_round_trip_strips_quotes(self):
        RA._API_KEY_FILE.write_text(
            '"RGAPI-aaaa-bbbb-cccc-dddd-eeeeeeeeeeee"',
            encoding="utf-8",
        )
        out = RA._get_api_key()
        self.assertIsNotNone(out)
        self.assertTrue(out.startswith("RGAPI-"))
        self.assertNotIn('"', out)

    def test_reload_clears_cache(self):
        RA._API_KEY_FILE.write_text(
            "RGAPI-aaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            encoding="utf-8",
        )
        first = RA._get_api_key()
        RA._API_KEY_FILE.write_text(
            "RGAPI-zzzz-yyyy-xxxx-wwww-vvvvvvvvvvvv",
            encoding="utf-8",
        )
        # Without reload, still returns the cached value.
        self.assertEqual(RA._get_api_key(), first)
        RA.reload_api_key()
        self.assertNotEqual(RA._get_api_key(), first)


class TestEndpointsHappyPath(_ApiKeyTestCase):
    def test_get_account_by_riot_id_caches(self):
        fake = {"puuid": "PUUID1", "gameName": "Test", "tagLine": "NA1"}
        with mock.patch.object(RA, "_http_get",
                               return_value=_resp(200, fake)) as m:
            out = RA.get_account_by_riot_id("Test", "NA1")
            self.assertEqual(out, fake)
            # Second call -> cache hit, no HTTP.
            out2 = RA.get_account_by_riot_id("Test", "NA1")
        self.assertEqual(out2, fake)
        self.assertEqual(m.call_count, 1)

    def test_get_recent_matches_returns_list(self):
        fake = ["NA1_111", "NA1_222", "NA1_333"]
        with mock.patch.object(RA, "_http_get",
                               return_value=_resp(200, fake)):
            out = RA.get_recent_matches("PUUID1", count=3)
        self.assertEqual(out, fake)

    def test_get_recent_matches_empty_puuid_skips_http(self):
        with mock.patch.object(RA, "_http_get") as m:
            self.assertIsNone(RA.get_recent_matches(""))
        self.assertFalse(m.called)

    def test_get_match_caches_immutable(self):
        match = {"metadata": {"matchId": "NA1_111"},
                 "info": {"gameMode": "CLASSIC", "participants": []}}
        with mock.patch.object(RA, "_http_get",
                               return_value=_resp(200, match)) as m:
            RA.get_match("NA1_111")
            RA.get_match("NA1_111")
        self.assertEqual(m.call_count, 1)

    def test_get_match_timeline_separate_cache(self):
        # Match detail and timeline must NOT share cache keys.
        detail = {"info": {"gameMode": "CLASSIC", "participants": []}}
        timeline = {"info": {"frames": []}}
        with mock.patch.object(RA, "_http_get") as m:
            m.side_effect = [_resp(200, detail), _resp(200, timeline)]
            d = RA.get_match("NA1_555")
            t = RA.get_match_timeline("NA1_555")
        self.assertEqual(d, detail)
        self.assertEqual(t, timeline)
        self.assertEqual(m.call_count, 2)

    def test_get_summoner_rank_returns_list_and_caches(self):
        ranked = [{"queueType": "RANKED_SOLO_5x5", "tier": "PLATINUM",
                   "rank": "IV", "leaguePoints": 47}]
        with mock.patch.object(RA, "_http_get",
                               return_value=_resp(200, ranked)) as m:
            r1 = RA.get_summoner_rank("PUUID1")
            r2 = RA.get_summoner_rank("PUUID1")
        self.assertEqual(r1, ranked)
        self.assertEqual(r2, ranked)
        self.assertEqual(m.call_count, 1)

    def test_get_summoner_rank_unranked_empty_list(self):
        # Unranked players return [] from Riot - must round-trip cleanly.
        with mock.patch.object(RA, "_http_get",
                               return_value=_resp(200, [])):
            out = RA.get_summoner_rank("PUUID-UNRANKED")
        self.assertEqual(out, [])

    def test_get_champion_mastery_caches(self):
        mastery = {"championId": 60, "championPoints": 287_000,
                   "championLevel": 7}
        with mock.patch.object(RA, "_http_get",
                               return_value=_resp(200, mastery)) as m:
            m1 = RA.get_champion_mastery("PUUID1", 60)
            m2 = RA.get_champion_mastery("PUUID1", 60)
        self.assertEqual(m1, mastery)
        self.assertEqual(m2, mastery)
        self.assertEqual(m.call_count, 1)

    def test_get_champion_mastery_missing_args_short_circuits(self):
        with mock.patch.object(RA, "_http_get") as m:
            self.assertIsNone(RA.get_champion_mastery("", 60))
            self.assertIsNone(RA.get_champion_mastery("PUUID1", 0))
        self.assertFalse(m.called)

    def test_get_top_champion_masteries_caches_list(self):
        top = [
            {"championId": 222, "championLevel": 7, "championPoints": 43_989},
            {"championId": 145, "championLevel": 6, "championPoints": 32_727},
        ]
        with mock.patch.object(RA, "_http_get",
                               return_value=_resp(200, top)) as m:
            r1 = RA.get_top_champion_masteries("PUUID1", count=2)
            r2 = RA.get_top_champion_masteries("PUUID1", count=2)
        self.assertEqual(r1, top)
        self.assertEqual(r2, top)
        self.assertEqual(m.call_count, 1)  # second call served from TTL cache
        # The request must hit the /top endpoint with the count query.
        called_url = m.call_args[0][0]
        self.assertIn("/champion-masteries/by-puuid/PUUID1/top?count=2", called_url)

    def test_get_top_champion_masteries_missing_puuid_short_circuits(self):
        with mock.patch.object(RA, "_http_get") as m:
            self.assertIsNone(RA.get_top_champion_masteries("", count=1))
        self.assertFalse(m.called)

    def test_get_top_champion_masteries_non_list_returns_none(self):
        # A dict body (unexpected shape) is rejected, not cached as truth.
        with mock.patch.object(RA, "_http_get",
                               return_value=_resp(200, {"oops": True})):
            self.assertIsNone(RA.get_top_champion_masteries("PUUID1", count=1))


class TestEndpointFailureModes(_ApiKeyTestCase):
    def test_401_returns_none(self):
        with mock.patch.object(RA, "_http_get",
                               return_value=_resp(401, b"unauthorized")):
            with self.assertLogs("rc.riot_api", level="WARNING"):
                self.assertIsNone(RA.get_summoner_rank("PUUID1"))

    def test_403_returns_none(self):
        with mock.patch.object(RA, "_http_get",
                               return_value=_resp(403, b"forbidden")):
            with self.assertLogs("rc.riot_api", level="WARNING"):
                self.assertIsNone(RA.get_summoner_rank("PUUID1"))

    def test_429_returns_none_and_imposes_cooldown(self):
        with mock.patch.object(RA, "_http_get",
                               return_value=_resp(429, b"slow down",
                                                  {"Retry-After": "5"})):
            with self.assertLogs("rc.riot_api", level="WARNING"):
                self.assertIsNone(RA.get_summoner_rank("PUUID1"))
        snap = RA.bucket_snapshot()
        self.assertGreater(snap["cooldown_remaining_s"], 0.0)

    def test_500_returns_none(self):
        with mock.patch.object(RA, "_http_get",
                               return_value=_resp(500, b"oops")):
            with self.assertLogs("rc.riot_api", level="WARNING"):
                self.assertIsNone(RA.get_match("NA1_xxx"))

    def test_urlerror_returns_none(self):
        with mock.patch.object(RA, "_http_get",
                               side_effect=urllib.error.URLError("conn refused")):
            with self.assertLogs("rc.riot_api", level="WARNING"):
                self.assertIsNone(RA.get_match("NA1_xxx"))

    def test_no_key_returns_none_silently_after_first_warn(self):
        # Override key cache + file path to a non-existent location so
        # the resolver can't recover from a real API-Key-Riot.txt file
        # that may exist on this test host.
        RA._KEY_CACHE = None
        RA._KEY_WARNED_MISSING = True   # squelch the warning for this case
        ghost_path = Path(self._tmp.name) / "does-not-exist.txt"
        with mock.patch.object(RA, "_API_KEY_FILE", ghost_path):
            with mock.patch.object(RA, "_http_get") as m:
                self.assertIsNone(RA.get_match("NA1_xxx"))
                self.assertIsNone(RA.get_summoner_rank("PUUID1"))
        self.assertFalse(m.called)


class TestRateLimiterIntegration(_ApiKeyTestCase):
    def test_bucket_exhaustion_returns_none(self):
        # Saturate the bucket then try one more - must be skipped.
        # Direct injection by replacing the limiter is cleaner than
        # waiting for real time.
        b = DualBucket(short_n=2, short_window_s=10.0,
                       long_n=2, long_window_s=10.0)
        with mock.patch.object(RA, "_BUCKET", b):
            with mock.patch.object(RA, "_http_get",
                                   return_value=_resp(200, [])):
                # First two calls succeed, third gets bucket-blocked.
                self.assertIsNotNone(RA.get_summoner_rank("PUUID-A"))
                self.assertIsNotNone(RA.get_summoner_rank("PUUID-B"))
                with self.assertLogs("rc.riot_api", level="WARNING"):
                    self.assertIsNone(RA.get_summoner_rank("PUUID-C"))


class TestRenderHelpers(unittest.TestCase):
    def test_format_rank_entry_full_shape(self):
        out = RA.format_rank_entry({
            "tier": "PLATINUM", "rank": "IV", "leaguePoints": 47,
            "queueType": "RANKED_SOLO_5x5",
        })
        self.assertEqual(out, "PLATINUM IV 47 LP")

    def test_format_rank_entry_partial(self):
        # Missing LP -> omit; missing division -> omit.
        self.assertEqual(
            RA.format_rank_entry({"tier": "DIAMOND"}),
            "DIAMOND",
        )
        self.assertEqual(RA.format_rank_entry({}), "")
        self.assertEqual(RA.format_rank_entry(None), "")  # type: ignore[arg-type]

    def test_pick_solo_rank_prefers_solo(self):
        entries = [
            {"queueType": "RANKED_FLEX_SR", "tier": "GOLD"},
            {"queueType": "RANKED_SOLO_5x5", "tier": "PLATINUM"},
        ]
        out = RA.pick_solo_rank(entries)
        self.assertEqual(out["tier"], "PLATINUM")

    def test_pick_solo_rank_fallback_to_highest_tier(self):
        # No solo entry - pick the highest tier of what's there.
        entries = [
            {"queueType": "RANKED_FLEX_SR", "tier": "GOLD"},
            {"queueType": "RANKED_TFT", "tier": "DIAMOND"},
        ]
        out = RA.pick_solo_rank(entries)
        self.assertEqual(out["tier"], "DIAMOND")

    def test_pick_solo_rank_empty_returns_none(self):
        self.assertIsNone(RA.pick_solo_rank([]))
        self.assertIsNone(RA.pick_solo_rank(None))   # type: ignore[arg-type]


def _match(puuid: str, champ: str, win: bool) -> dict:
    return {"info": {"participants": [
        {"puuid": puuid, "championName": champ, "win": win},
        {"puuid": "OTHER", "championName": "Other", "win": not win},
    ]}}


class TestSummarizeRecent(_ApiKeyTestCase):
    def test_walks_matches_and_computes_summary(self):
        # 12 matches: 7 wins, 5 losses; champion distribution 5/4/3.
        ids = [f"NA1_{i:03d}" for i in range(12)]
        match_map = {}
        for i, mid in enumerate(ids):
            if i < 5:    champ = "Camille"
            elif i < 9:  champ = "Jax"
            else:        champ = "Fiora"
            win = (i % 2 == 0)
            match_map[mid] = _match("PUUID1", champ, win)

        def fake_http_get(url, *_args, **_kwargs):
            for mid, body in match_map.items():
                if mid in url:
                    return _resp(200, body)
            return _resp(404, b"not found")

        with mock.patch.object(RA, "_http_get", side_effect=fake_http_get):
            out = RA.summarize_recent("PUUID1", ids)

        self.assertIn("Camille", out["mains"])
        self.assertIn("Jax", out["mains"])
        # Top-3 cap.
        self.assertLessEqual(len(out["mains"]), 3)
        # Wins=indices {0,2,4,6,8,10}=6; losses=6 -> wr 0.5
        self.assertAlmostEqual(out["win_rate_recent"], 0.5, places=2)
        # First 7 matches: win at 0,2,4,6 -> 4W, loss at 1,3,5 -> 3L
        self.assertEqual(out["w_l_streak_7"], [4, 3])

    def test_empty_inputs_return_skeleton(self):
        out = RA.summarize_recent("", [])
        self.assertEqual(out["mains"], [])
        self.assertEqual(out["win_rate_recent"], 0.0)
        self.assertEqual(out["w_l_streak_7"], [0, 0])

    def test_missing_participant_skipped(self):
        # A match where our PUUID isn't in participants - soft-skip.
        ids = ["NA1_zzz"]
        match = {"info": {"participants": [
            {"puuid": "OTHER", "championName": "Foo", "win": True},
        ]}}
        with mock.patch.object(RA, "_http_get",
                               return_value=_resp(200, match)):
            out = RA.summarize_recent("PUUID1", ids)
        self.assertEqual(out["mains"], [])
        self.assertEqual(out["win_rate_recent"], 0.0)


if __name__ == "__main__":
    unittest.main()

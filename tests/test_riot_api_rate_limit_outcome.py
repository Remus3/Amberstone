"""A Riot 429 must stay distinguishable from "genuinely not found".

THE DEFECT. `core/riot_api._call_ex` knows exactly why a call came back
empty - it returns `(None, "429")`, `(None, "rate_limited")` or
`(None, "not_found")` - but every public helper projects that down to a bare
None (`_call` at riot_api.py:449, `_cached_or_fetch` at :589). So a consumer
cannot tell "Riot is throttling us, try again" from "this player has no
data", and the champ-select TEAM CONTEXT panel painted a rate limit as an
empty skeleton, while `/api/scouting` shaped it as "Unranked" AND cached that
fabricated answer for 5 minutes.

THE SHAPE OF THE FIX. The None return contract is unchanged (every existing
caller keeps working). The reason is carried out-of-band by a thread-scoped
recorder, `riot_api.track_outcomes()`: a caller that cares wraps its calls
and reads `scope.rate_limited`. A caller that does not care pays nothing.

This file pins both directions: a 429 / local-bucket exhaustion reads as
rate limited, and a 404 does NOT.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import riot_api as RA                     # noqa: E402
from core import riot_api_cache as RIC              # noqa: E402
from dashboard import _party_mains as PM            # noqa: E402
from dashboard import routes_scouting as RS         # noqa: E402
from dashboard import routes_team_context as RTC    # noqa: E402

_PUUID = "puuid-rate-limit-test"


def _resp(status: int, body: bytes = b"[]", headers: dict | None = None):
    return RA._HttpResp(status, body, dict(headers or {}))


def _seq(*responses):
    """`_http_get` stand-in returning `responses` in order (last repeats)."""
    state = {"i": 0}

    def _fake(url, api_key, timeout_s=None):
        i = min(state["i"], len(responses) - 1)
        state["i"] += 1
        return responses[i]
    return _fake


class _Base(unittest.TestCase):
    def setUp(self):
        self._orig_key_cache = RA._KEY_CACHE
        RA._KEY_CACHE = "RGAPI-test-key-aaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        RA._reset_bucket_for_tests()
        self._tmp = tempfile.TemporaryDirectory()
        RIC._reset_for_tests(db_path=Path(self._tmp.name) / "cache.db")
        RTC._clear()
        RS._reset_cache_for_tests()
        PM._reset_cache_for_tests()

    def tearDown(self):
        RA._KEY_CACHE = self._orig_key_cache
        RA._reset_bucket_for_tests()
        RIC._reset_for_tests(db_path=None)
        RTC._clear()
        RS._reset_cache_for_tests()
        PM._reset_cache_for_tests()
        self._tmp.cleanup()


class TestOutcomeScope(_Base):
    """The core seam: the reason survives the public helpers."""

    def test_429_on_uncached_helper_reads_rate_limited(self):
        with mock.patch.object(RA, "_http_get",
                               _seq(_resp(429, b"", {"Retry-After": "1"}))):
            with RA.track_outcomes() as scope:
                got = RA.get_summoner_rank(_PUUID)
        self.assertIsNone(got, "return contract must stay None")
        self.assertTrue(scope.rate_limited)
        self.assertEqual(scope.last, "429")

    def test_404_on_uncached_helper_is_not_rate_limited(self):
        with mock.patch.object(RA, "_http_get", _seq(_resp(404, b"{}"))):
            with RA.track_outcomes() as scope:
                got = RA.get_summoner_rank(_PUUID)
        self.assertIsNone(got)
        self.assertFalse(scope.rate_limited)
        self.assertEqual(scope.last, "not_found")

    def test_429_on_immutable_cached_helper_reads_rate_limited(self):
        with mock.patch.object(RA, "_http_get",
                               _seq(_resp(429, b"", {"Retry-After": "1"}))):
            with RA.track_outcomes() as scope:
                got = RA.get_match("NA1_1")
        self.assertIsNone(got)
        self.assertTrue(scope.rate_limited)

    def test_404_on_immutable_cached_helper_is_not_rate_limited(self):
        with mock.patch.object(RA, "_http_get", _seq(_resp(404, b"{}"))):
            with RA.track_outcomes() as scope:
                got = RA.get_match("NA1_2")
        self.assertIsNone(got)
        self.assertFalse(scope.rate_limited)
        self.assertEqual(scope.last, "not_found")

    def test_local_bucket_exhaustion_reads_rate_limited(self):
        # The 429 cooldown makes the NEXT call fail before anything is sent.
        RA._BUCKET.note_429(60)
        with mock.patch.object(RA, "_http_get", _seq(_resp(200, b"[]"))) as _:
            with mock.patch.object(RA._BUCKET, "acquire", return_value=False):
                with RA.track_outcomes() as scope:
                    got = RA.get_summoner_rank(_PUUID)
        self.assertIsNone(got)
        self.assertTrue(scope.rate_limited)
        self.assertEqual(scope.last, "rate_limited")

    def test_scope_is_fresh_and_nothing_leaks_outside(self):
        with mock.patch.object(RA, "_http_get",
                               _seq(_resp(429, b"", {"Retry-After": "0"}))):
            with RA.track_outcomes() as first:
                RA.get_summoner_rank(_PUUID)
            # A call OUTSIDE any scope records nowhere and does not raise.
            RA._reset_bucket_for_tests()
            RA.get_summoner_rank(_PUUID + "-2")
        with RA.track_outcomes() as second:
            pass
        self.assertTrue(first.rate_limited)
        self.assertEqual(first.outcomes, ["429"])
        self.assertFalse(second.rate_limited)
        self.assertEqual(second.outcomes, [])
        self.assertIsNone(second.last)


class TestTeamContextConsumer(_Base):
    """Champ-select team intel: a 429 is marked, a 404 is not."""

    def _seed(self):
        RTC._store({
            "allies": [RTC._skeleton_entry(
                {"puuid": _PUUID, "team_id": 100, "summoner_name": "A"})],
            "enemies": [], "refreshed_at": "x", "partial": True,
            "queue_id": 450,
        })

    def _entry(self):
        return RTC.get_team_context()["allies"][0]

    def test_skeleton_carries_empty_riot_status(self):
        self._seed()
        self.assertEqual(self._entry()["riot_status"], "")

    def test_priority_1_429_marks_entry_rate_limited(self):
        self._seed()
        with mock.patch.object(RA, "_http_get",
                               _seq(_resp(429, b"", {"Retry-After": "1"}))):
            RTC._enrich_priority_1(dict(self._entry()), None)
        self.assertEqual(self._entry()["riot_status"], "rate_limited")
        self.assertEqual(self._entry()["rank"], "")

    def test_priority_1_404_is_not_marked_rate_limited(self):
        self._seed()
        with mock.patch.object(RA, "_http_get", _seq(_resp(404, b"{}"))):
            RTC._enrich_priority_1(dict(self._entry()), None)
        self.assertEqual(self._entry()["riot_status"], "")

    def test_priority_2_429_marks_entry_rate_limited(self):
        self._seed()
        with mock.patch.object(RA, "_http_get",
                               _seq(_resp(429, b"", {"Retry-After": "1"}))):
            RTC._enrich_priority_2(dict(self._entry()))
        self.assertEqual(self._entry()["riot_status"], "rate_limited")

    def test_worker_retries_a_rate_limited_entry_and_clears_it(self):
        self._seed()
        rank_body = (b'[{"queueType":"RANKED_SOLO_5x5","tier":"GOLD",'
                     b'"rank":"II","leaguePoints":40}]')
        fake = _seq(
            _resp(429, b"", {"Retry-After": "0"}),  # p1 rank -> 429
            _resp(200, b"[]"),                      # p2 match ids -> empty
            _resp(200, rank_body),                  # retry p1 rank -> ok
            _resp(200, b"[]"),                      # retry p2 -> empty
        )
        entry = dict(self._entry())
        with mock.patch.object(RA, "_http_get", fake), \
                mock.patch.object(RTC, "_sleep", lambda s: None):
            RTC._fanout_worker([entry], [], 450)
        got = self._entry()
        self.assertEqual(got["rank"], "GOLD II 40 LP")
        self.assertEqual(got["riot_status"], "")
        self.assertFalse(RTC.get_team_context()["partial"])

    def test_worker_gives_up_after_bounded_retries_and_keeps_the_mark(self):
        self._seed()
        entry = dict(self._entry())
        with mock.patch.object(RA, "_http_get",
                               _seq(_resp(429, b"", {"Retry-After": "0"}))), \
                mock.patch.object(RTC, "_sleep", lambda s: None):
            RTC._fanout_worker([entry], [], 450)
        self.assertEqual(self._entry()["riot_status"], "rate_limited")
        self.assertFalse(RTC.get_team_context()["partial"])


class TestRetryWait(_Base):
    """The wait between retry passes follows the bucket, clamped."""

    def _wait_with(self, snap):
        with mock.patch.object(RA, "bucket_snapshot", lambda: snap):
            return RTC._rate_limit_wait_s()

    def test_zero_cooldown_uses_floor(self):
        self.assertEqual(self._wait_with(
            {"cooldown_remaining_s": 0.0, "long_used": 0, "long_cap": 100}),
            RTC._RATE_LIMIT_WAIT_MIN_S)

    def test_long_retry_after_is_capped(self):
        self.assertEqual(self._wait_with(
            {"cooldown_remaining_s": 500.0, "long_used": 0, "long_cap": 100}),
            RTC._RATE_LIMIT_WAIT_MAX_S)

    def test_full_long_bucket_waits_the_ceiling_not_the_floor(self):
        self.assertEqual(self._wait_with(
            {"cooldown_remaining_s": 0.0, "long_used": 100, "long_cap": 100}),
            RTC._RATE_LIMIT_WAIT_MAX_S)


class TestScoutingConsumer(_Base):
    """`/api/scouting` must not shape a 429 as Unranked, nor cache it."""

    def test_429_is_rate_limited_not_unranked_and_not_cached(self):
        with mock.patch.object(RA, "_http_get",
                               _seq(_resp(429, b"", {"Retry-After": "1"}))):
            got = RS._scout_one(_PUUID, 1000.0)
        self.assertTrue(got.get("rate_limited"))
        self.assertNotEqual(got["display"], "Unranked")
        self.assertNotIn("429", got["display"])
        self.assertIsNone(RS._cache_get(_PUUID, 1000.0),
                          "a rate-limited result must not be cached")

    def test_404_is_unranked_and_cached(self):
        with mock.patch.object(RA, "_http_get", _seq(_resp(404, b"{}"))):
            got = RS._scout_one(_PUUID, 1000.0)
        self.assertFalse(got.get("rate_limited", False))
        self.assertEqual(got["display"], "Unranked")
        self.assertIsNotNone(RS._cache_get(_PUUID, 1000.0))


class TestPartyMainsConsumer(_Base):
    """A rate-limited refresh must retry soon, not sit on a 5-min TTL."""

    def test_rate_limited_refresh_uses_short_retry_ttl(self):
        ok_member = {"game_name": "Ok", "tag_line": "NA1", "riot_id": "Ok#NA1"}
        rl_member = {"game_name": "Rl", "tag_line": "NA1", "riot_id": "Rl#NA1"}

        def _fake_member(member, *, region):
            if member["game_name"] == "Rl":
                with mock.patch.object(
                        RA, "_http_get",
                        _seq(_resp(429, b"", {"Retry-After": "1"}))):
                    RA.get_summoner_rank("x")   # records a 429 in the scope
                return None
            return {"name": "Ahri", "player": "Ok",
                    "mastery_level": 7, "mastery_points": 1}

        with mock.patch.object(PM, "_member_top_main", _fake_member):
            PM._refresh([ok_member, rl_member], ("k",), "na1")
        self.assertEqual(PM._cache["ttl"], PM._EMPTY_RETRY_S)
        self.assertEqual(len(PM._cache["data"]), 1)

    def test_clean_refresh_keeps_long_ttl(self):
        ok_member = {"game_name": "Ok", "tag_line": "NA1", "riot_id": "Ok#NA1"}
        with mock.patch.object(PM, "_member_top_main",
                               lambda m, *, region: {"name": "Ahri"}):
            PM._refresh([ok_member], ("k",), "na1")
        self.assertEqual(PM._cache["ttl"], PM._TTL_S)


if __name__ == "__main__":
    unittest.main()

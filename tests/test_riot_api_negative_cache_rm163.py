"""RM-163: negative caching for core/riot_api.py immutable-cached endpoints.

THE DEFECT (filed 2026-08-06, LEDGER 1204). `get_match_timeline` did:

    data = _call("match_v5_timeline", url)
    if data is not None:
        get_cache().set_immutable(cache_key, data)

A None result was NEVER stored, so a match Riot legitimately has no timeline
for re-fetched on EVERY request forever. cProfile put 289ms of a 291ms
/api/last-match build inside that one urlopen, reached via
dashboard/builders_lcu_enrich.py:428 -> core/riot_api.py:520. A None here is
the NORMAL case, not an error: Match-V5 does not serve event modes (ARAM
Mayhem gameMode KIWI, queue 2400), which is EXPECTED AND PERMANENT.

THE SHARP EDGE is that `_call` collapses six different outcomes into one None.
"Riot has no such resource" is cacheable; "the network blinked" is not. This
file pins BOTH directions:

  CACHEABLE NEGATIVE - the resource does not exist / is not served
    404  not found
    403  forbidden (the measured event-mode Match-V5 response)

  NOT CACHEABLE - transient, or a fault on our side of the wire
    429  rate limited by Riot
    5xx  Riot server error
    401  key invalid / revoked
    URLError / TimeoutError / OSError   transport failure
    local rate-limit bucket exhaustion  (nothing was even sent)
    missing API key                     (nothing was even sent)

Caching any of the second group as a negative would convert a blip into a
self-inflicted outage of bounded-but-real length, which is strictly worse
than the re-fetch cost this row exists to remove.

BOUNDED TTL, NOT IMMUTABLE. The positive rows live in `cache_immutable`,
which never expires - correct, because a finished match is a historical
record. A negative is a statement about Riot's CURRENT inventory, and Riot
does backfill: a timeline can appear minutes after the game ends. So the
negative lands in the TTL table and self-heals. Tests here pin that it is
bounded and that it is NOT written to the immutable table.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import riot_api as RA                     # noqa: E402
from core import riot_api_cache as RIC              # noqa: E402

_MATCH_ID = "NA1_5585328637"
_TIMELINE_KEY = f"match:v5:timeline:{_MATCH_ID}"
_DETAIL_KEY = f"match:v5:{_MATCH_ID}"


def _resp(status: int, body=None, headers: dict | None = None):
    """Build a fake `_HttpResp` - the object `riot_api._http_get` returns."""
    if body is None:
        payload = b""
    elif isinstance(body, (dict, list)):
        payload = json.dumps(body).encode("utf-8")
    else:
        payload = bytes(body)
    return RA._HttpResp(status, payload, dict(headers or {}))


class _Spy:
    """Counting stand-in for `riot_api._http_get`.

    `calls` is the whole point of this file: a negative that is cached shows
    up as a call count that STOPS going up, and nothing else proves it.
    """

    def __init__(self, outcome):
        self.calls = 0
        self._outcome = outcome

    def __call__(self, url, api_key, timeout_s=None):
        self.calls += 1
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        if callable(self._outcome):
            return self._outcome(self.calls)
        return self._outcome


class _NegCacheBase(unittest.TestCase):
    """Fake key + private bucket + throwaway cache DB per test."""

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

    def _call_twice(self, spy, fn=None, **kwargs):
        """Run the endpoint twice, resetting the LOCAL bucket in between.

        Without the reset, a 429 case would be confounded: `note_429` puts the
        bucket into cooldown, so the second call would return None because it
        never fired, and the test would read as "negative cached" when nothing
        of the sort happened.
        """
        fn = fn or (lambda: RA.get_match_timeline(_MATCH_ID))
        with mock.patch.object(RA, "_http_get", spy):
            first = fn()
            RA._reset_bucket_for_tests()
            second = fn()
        return first, second


class TestCacheableNegative(_NegCacheBase):
    """404 / 403 are answers, not failures - store them."""

    def test_timeline_404_is_stored_and_does_not_refire(self):
        spy = _Spy(_resp(404, {"status": {"message": "Data not found"}}))
        first, second = self._call_twice(spy)
        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(
            spy.calls, 1,
            "second call refired the outbound request; the negative was not "
            "cached")

    def test_timeline_403_event_mode_is_stored_and_does_not_refire(self):
        # The measured event-mode response (ARAM Mayhem KIWI / queue 2400).
        spy = _Spy(_resp(403, {"status": {"message": "Forbidden"}}))
        first, second = self._call_twice(spy)
        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(spy.calls, 1)

    def test_match_detail_404_is_stored_and_does_not_refire(self):
        # SIBLING SITE - core/riot_api.py get_match had the identical shape.
        spy = _Spy(_resp(404))
        first, second = self._call_twice(
            spy, fn=lambda: RA.get_match(_MATCH_ID))
        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(spy.calls, 1)

    def test_account_404_is_stored_and_does_not_refire(self):
        # SIBLING SITE - get_account_by_riot_id had the identical shape.
        spy = _Spy(_resp(404))
        first, second = self._call_twice(
            spy, fn=lambda: RA.get_account_by_riot_id("nobody", "0000"))
        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(spy.calls, 1)

    def test_negative_does_not_land_in_the_immutable_table(self):
        """A negative must never reach the never-expiring table.

        If it did, one bad hour would blacklist a match for the life of the
        DB with no way back short of manual SQL - the exact failure mode the
        immutable/TTL split exists to prevent.
        """
        spy = _Spy(_resp(404))
        with mock.patch.object(RA, "_http_get", spy):
            RA.get_match_timeline(_MATCH_ID)
        self.assertIsNone(RIC.get_cache().get_immutable(_TIMELINE_KEY))

    def test_negative_never_masquerades_as_a_positive(self):
        """The cached negative must return None, not a truthy marker dict.

        dashboard/builders_lcu_enrich.py:429 does `isinstance(timeline, dict)`
        - handing it a sentinel dict would feed a marker into the timeline
        parser instead of skipping the panel.
        """
        spy = _Spy(_resp(404))
        with mock.patch.object(RA, "_http_get", spy):
            RA.get_match_timeline(_MATCH_ID)
            RA._reset_bucket_for_tests()
            again = RA.get_match_timeline(_MATCH_ID)
        self.assertIsNone(again)


class TestPositiveStillCaches(_NegCacheBase):
    """The pre-existing positive path is unchanged."""

    def test_200_caches_immutably_and_does_not_refire(self):
        payload = {"metadata": {"matchId": _MATCH_ID}, "info": {"frames": []}}
        spy = _Spy(_resp(200, payload))
        first, second = self._call_twice(spy)
        self.assertEqual(first, payload)
        self.assertEqual(second, payload)
        self.assertEqual(spy.calls, 1)
        self.assertEqual(
            RIC.get_cache().get_immutable(_TIMELINE_KEY), payload,
            "positive result must still land in the immutable table")

    def test_match_detail_200_still_caches_immutably(self):
        payload = {"metadata": {"matchId": _MATCH_ID}}
        spy = _Spy(_resp(200, payload))
        first, second = self._call_twice(
            spy, fn=lambda: RA.get_match(_MATCH_ID))
        self.assertEqual(first, payload)
        self.assertEqual(second, payload)
        self.assertEqual(spy.calls, 1)
        self.assertEqual(RIC.get_cache().get_immutable(_DETAIL_KEY), payload)


class TestNegativeTtlIsBounded(_NegCacheBase):
    """Riot backfills. A negative that never expires is a new bug."""

    def test_ttl_constant_is_bounded_and_nonzero(self):
        ttl = RA._NEGATIVE_TTL_S
        self.assertIsInstance(ttl, int)
        self.assertGreater(
            ttl, 120,
            "must outlast Riot's own 2-minute long rate-limit window or the "
            "negative buys nothing")
        self.assertLessEqual(
            ttl, 86400,
            "a negative older than a day is an assertion about Riot's "
            "inventory that nobody re-checked")

    def test_ttl_constant_is_pinned(self):
        """Pinned deliberately at one hour.

        Long enough that the row's actual cost is gone - /api/last-match
        rebuilds on a seconds-to-minutes cadence, so an hour collapses
        hundreds of 289ms round trips into one. Short enough that the two
        ways a negative can be WRONG both self-heal without cache surgery:
        a timeline Riot backfills minutes after the game ends, and a 403
        that was really a rotated key rather than an event mode.
        """
        self.assertEqual(RA._NEGATIVE_TTL_S, 3600)

    def test_expired_negative_refires(self):
        """With the TTL driven to zero the second call MUST go out again.

        This is what separates "bounded" from "immutable-forever": if the
        entry survived expiry the count would stay at 1 here too.
        """
        spy = _Spy(_resp(404))
        with mock.patch.object(RA, "_NEGATIVE_TTL_S", 0):
            first, second = self._call_twice(spy)
        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(spy.calls, 2)

    def test_backfill_is_served_after_the_negative_expires(self):
        """404 first, then Riot backfills - the caller must see the payload."""
        payload = {"info": {"frames": [{"timestamp": 0}]}}

        def outcome(n):
            return _resp(404) if n == 1 else _resp(200, payload)

        spy = _Spy(outcome)
        with mock.patch.object(RA, "_NEGATIVE_TTL_S", 0):
            first, second = self._call_twice(spy)
        self.assertIsNone(first)
        self.assertEqual(second, payload)
        self.assertEqual(spy.calls, 2)


class TestTransientIsNotCached(_NegCacheBase):
    """The other direction, and the reason this row is not a one-liner."""

    def _assert_refires(self, outcome, label):
        spy = _Spy(outcome)
        first, second = self._call_twice(spy)
        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(
            spy.calls, 2,
            f"{label} was cached as a negative; a transient failure must "
            f"never suppress the next attempt")

    def test_429_is_not_cached(self):
        self._assert_refires(
            _resp(429, {"status": {"message": "Rate limit exceeded"}},
                  {"Retry-After": "1"}),
            "429")

    def test_500_is_not_cached(self):
        self._assert_refires(_resp(500), "500")

    def test_503_is_not_cached(self):
        self._assert_refires(_resp(503), "503")

    def test_401_is_not_cached(self):
        # 401 is OUR fault (key invalid/revoked), not a statement about the
        # match. Caching it would blacklist every match touched during a key
        # rotation.
        self._assert_refires(_resp(401), "401")

    def test_url_error_is_not_cached(self):
        self._assert_refires(urllib.error.URLError("dns"), "URLError")

    def test_timeout_is_not_cached(self):
        self._assert_refires(TimeoutError("read timed out"), "TimeoutError")

    def test_os_error_is_not_cached(self):
        self._assert_refires(OSError("connection reset"), "OSError")

    def test_malformed_body_is_not_cached(self):
        # 200 with a body that will not parse is a broken response, not an
        # absent resource.
        self._assert_refires(_resp(200, b"<html>nope</html>"), "parse error")

    def test_local_bucket_exhaustion_is_not_cached(self):
        """Nothing left the process, so nothing was learned about the match."""
        payload = {"info": {"frames": []}}
        spy = _Spy(_resp(200, payload))
        RA._BUCKET.note_429(retry_after_s=60.0)
        with mock.patch.object(RA, "_http_get", spy):
            blocked = RA.get_match_timeline(_MATCH_ID)
            RA._reset_bucket_for_tests()
            after = RA.get_match_timeline(_MATCH_ID)
        self.assertIsNone(blocked)
        self.assertEqual(spy.calls, 1, "the blocked attempt must not fire")
        self.assertEqual(
            after, payload,
            "bucket exhaustion poisoned the cache with a negative")

    def test_missing_api_key_is_not_cached(self):
        """No key means no request, which means no evidence either way."""
        payload = {"info": {"frames": []}}
        spy = _Spy(_resp(200, payload))
        with mock.patch.object(RA, "_get_api_key", lambda: None):
            with mock.patch.object(RA, "_http_get", spy):
                blocked = RA.get_match_timeline(_MATCH_ID)
        self.assertIsNone(blocked)
        self.assertEqual(spy.calls, 0)
        with mock.patch.object(RA, "_http_get", spy):
            after = RA.get_match_timeline(_MATCH_ID)
        self.assertEqual(
            after, payload,
            "a keyless call poisoned the cache with a negative")


class TestOutcomeClassification(_NegCacheBase):
    """`_call_ex` is the seam that makes the distinction expressible.

    `_call` returns None for six different reasons and therefore cannot
    support this row at all. These pin the classifier directly so a future
    edit that reshuffles the status branches fails here rather than silently
    turning a transient into a cached negative.
    """

    def _classify(self, spy):
        with mock.patch.object(RA, "_http_get", spy):
            _, outcome = RA._call_ex("t", "https://example.invalid/x")
        return outcome

    def test_cacheable_set_is_exactly_not_found_and_forbidden(self):
        self.assertEqual(
            set(RA._CACHEABLE_NEGATIVE_OUTCOMES), {"not_found", "forbidden"})

    def test_404_classifies_not_found(self):
        self.assertEqual(self._classify(_Spy(_resp(404))), "not_found")

    def test_403_classifies_forbidden(self):
        self.assertEqual(self._classify(_Spy(_resp(403))), "forbidden")

    def test_200_classifies_ok(self):
        self.assertEqual(self._classify(_Spy(_resp(200, {"a": 1}))), "ok")

    def test_429_classifies_429(self):
        self.assertEqual(self._classify(_Spy(_resp(429))), "429")

    def test_401_classifies_error(self):
        self.assertEqual(self._classify(_Spy(_resp(401))), "error")

    def test_500_classifies_error(self):
        self.assertEqual(self._classify(_Spy(_resp(500))), "error")

    def test_transport_failure_classifies_error(self):
        self.assertEqual(
            self._classify(_Spy(urllib.error.URLError("dns"))), "error")

    def test_no_key_classifies_no_key(self):
        with mock.patch.object(RA, "_get_api_key", lambda: None):
            _, outcome = RA._call_ex("t", "https://example.invalid/x")
        self.assertEqual(outcome, "no_key")

    def test_bucket_exhaustion_classifies_rate_limited(self):
        RA._BUCKET.note_429(retry_after_s=60.0)
        _, outcome = RA._call_ex("t", "https://example.invalid/x",
                                 rate_limit_timeout_s=0.0)
        self.assertEqual(outcome, "rate_limited")

    def test_no_transient_outcome_is_cacheable(self):
        """Belt and braces: the two sets must not overlap."""
        transient = {"429", "error", "no_key", "rate_limited"}
        self.assertEqual(
            transient & set(RA._CACHEABLE_NEGATIVE_OUTCOMES), set())

    def test_call_still_returns_only_data(self):
        """`_call` keeps its old signature for the uncached endpoints."""
        with mock.patch.object(RA, "_http_get", _Spy(_resp(200, {"a": 1}))):
            self.assertEqual(RA._call("t", "https://example.invalid/x"),
                             {"a": 1})


if __name__ == "__main__":
    unittest.main()

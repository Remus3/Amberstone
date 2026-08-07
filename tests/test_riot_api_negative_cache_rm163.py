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
negative lands in the TTL table and self-heals, at a TTL split by outcome
(not_found 300s, forbidden 900s - see `TestNegativeTtlIsBounded`).

KEY-SCOPED. The negative key embeds the API-key fingerprint. Without that, an
expired key would 403 every match, fan a negative out across every id the
dashboard touches, and then survive the operator installing a working key -
a cache that ignores the fix. See `TestNegativeIsKeyScoped`.
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

    def _immutable_rows(self):
        return RIC.get_cache().stats_fast()["immutable_rows"]


def _zero_ttl():
    """Patch every negative TTL to 0 so the entry is expired on write."""
    return mock.patch.dict(
        RA._NEGATIVE_TTL_S_BY_OUTCOME,
        {k: 0 for k in RA._NEGATIVE_TTL_S_BY_OUTCOME},
    )


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
        """A negative must never reach the never-expiring table - AT ANY KEY.

        If it did, one bad window would blacklist a match for the life of the
        DB with no way back short of manual SQL - the exact failure mode the
        immutable/TTL split exists to prevent.

        Checking only the POSITIVE key here would be too weak: a mutation that
        ALSO wrote the negative into cache_immutable under the `neg:` key
        would sail through. The row COUNT is the assertion that cannot be
        dodged, so it leads.
        """
        spy = _Spy(_resp(404))
        self.assertEqual(self._immutable_rows(), 0, "precondition")
        with mock.patch.object(RA, "_http_get", spy):
            RA.get_match_timeline(_MATCH_ID)
        self.assertEqual(
            self._immutable_rows(), 0,
            "a negative reached cache_immutable - it can never expire there")
        self.assertIsNone(RIC.get_cache().get_immutable(_TIMELINE_KEY))
        self.assertIsNone(
            RIC.get_cache().get_immutable(RA._negative_key(_TIMELINE_KEY)))

    def test_positive_write_is_visible_to_the_row_count(self):
        """Guards the guard above: prove immutable_rows CAN go up.

        Without this, `assertEqual(rows, 0)` would also pass if stats_fast
        were broken or always returned 0, and the strongest assertion in this
        file would be vacuous.
        """
        spy = _Spy(_resp(200, {"info": {"frames": []}}))
        with mock.patch.object(RA, "_http_get", spy):
            RA.get_match_timeline(_MATCH_ID)
        self.assertEqual(self._immutable_rows(), 1)

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

    def test_every_cacheable_outcome_has_a_bounded_nonzero_ttl(self):
        self.assertEqual(
            set(RA._NEGATIVE_TTL_S_BY_OUTCOME),
            set(RA._CACHEABLE_NEGATIVE_OUTCOMES),
            "every cacheable outcome needs an explicit TTL - the fallback is "
            "a safety net, not a design")
        for outcome, ttl in RA._NEGATIVE_TTL_S_BY_OUTCOME.items():
            with self.subTest(outcome=outcome):
                self.assertIsInstance(ttl, int)
                self.assertGreater(
                    ttl, 120,
                    "must outlast Riot's own 2-minute long rate-limit window "
                    "or the negative buys nothing")
                self.assertLessEqual(
                    ttl, 3600,
                    "a negative older than an hour is an assertion about "
                    "Riot's inventory that nobody re-checked")

    def test_ttls_are_pinned_per_outcome(self):
        """Split by how likely Riot is to change its mind.

        not_found (300s) is the VOLATILE one: a match that just ended has its
        detail before its timeline, so a 404 seconds after the game resolves
        minutes later. Capping at 5 minutes keeps post-game review from going
        blind on a real SR timeline Riot has since published.

        forbidden (900s) is the PERMANENT one once the key is ruled out - and
        the key IS ruled out, structurally, by the fingerprint in
        `_negative_key`. What remains is route/mode entitlement (ARAM Mayhem
        KIWI / queue 2400), which never backfills.
        """
        self.assertEqual(RA._NEGATIVE_TTL_S_BY_OUTCOME["not_found"], 300)
        self.assertEqual(RA._NEGATIVE_TTL_S_BY_OUTCOME["forbidden"], 900)

    def test_the_two_outcomes_do_not_share_a_ttl(self):
        """The split is the point; equal values would make it decorative."""
        self.assertNotEqual(
            RA._negative_ttl_for("not_found"),
            RA._negative_ttl_for("forbidden"))

    def test_unknown_outcome_falls_back_to_the_shortest_ttl(self):
        fallback = RA._negative_ttl_for("some_future_outcome")
        self.assertEqual(fallback, RA._NEGATIVE_TTL_FALLBACK_S)
        self.assertLessEqual(
            fallback, min(RA._NEGATIVE_TTL_S_BY_OUTCOME.values()),
            "forgetting the TTL table must cost extra calls, not staleness")

    def test_expired_negative_refires(self):
        """With the TTL driven to zero the second call MUST go out again.

        This is what separates "bounded" from "immutable-forever": if the
        entry survived expiry the count would stay at 1 here too.
        """
        spy = _Spy(_resp(404))
        with _zero_ttl():
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
        with _zero_ttl():
            first, second = self._call_twice(spy)
        self.assertIsNone(first)
        self.assertEqual(second, payload)
        self.assertEqual(spy.calls, 2)


class TestNegativeIsKeyScoped(_NegCacheBase):
    """Installing a fresh key must clear negatives the old key earned.

    THE FAILURE THIS PREVENTS: the operator's Riot key expires, every
    Match-V5 call 403s, and /api/last-match plus
    dashboard/builders_lcu_enrich.py, lib/rewind_live_writer.py and
    dashboard/routes_scouting.py fan that out across many match ids, each
    taking a negative. Un-fingerprinted, installing a VALID key would not
    clear any of them and RC would stay blind after the operator had already
    fixed the problem - a cache actively ignoring the fix.
    """

    _KEY_A = "RGAPI-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    _KEY_B = "RGAPI-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    def test_new_key_invalidates_an_existing_negative(self):
        spy = _Spy(_resp(403))
        RA._KEY_CACHE = self._KEY_A
        with mock.patch.object(RA, "_http_get", spy):
            self.assertIsNone(RA.get_match_timeline(_MATCH_ID))
            RA._reset_bucket_for_tests()
            # Same key - must be served from the negative.
            self.assertIsNone(RA.get_match_timeline(_MATCH_ID))
            self.assertEqual(spy.calls, 1)
            # Key rotated - the old negative must be unreachable.
            RA._KEY_CACHE = self._KEY_B
            RA._reset_bucket_for_tests()
            self.assertIsNone(RA.get_match_timeline(_MATCH_ID))
        self.assertEqual(
            spy.calls, 2,
            "a fresh API key did not clear the negative the old key earned")

    def test_fresh_key_sees_the_payload_the_stale_key_was_denied(self):
        """The whole point: after the fix, RC recovers immediately."""
        payload = {"info": {"frames": []}}

        def outcome(n):
            return _resp(403) if n == 1 else _resp(200, payload)

        spy = _Spy(outcome)
        RA._KEY_CACHE = self._KEY_A
        with mock.patch.object(RA, "_http_get", spy):
            self.assertIsNone(RA.get_match_timeline(_MATCH_ID))
            RA._KEY_CACHE = self._KEY_B
            RA._reset_bucket_for_tests()
            recovered = RA.get_match_timeline(_MATCH_ID)
        self.assertEqual(recovered, payload)

    def test_negative_key_embeds_the_fingerprint(self):
        RA._KEY_CACHE = self._KEY_A
        key_a = RA._negative_key(_TIMELINE_KEY)
        RA._KEY_CACHE = self._KEY_B
        key_b = RA._negative_key(_TIMELINE_KEY)
        self.assertNotEqual(key_a, key_b)
        self.assertIn(RA._key_fingerprint(), key_b)


class TestNegativeKeyNamespace(_NegCacheBase):
    """The prefix and the marker are load-bearing; pin them.

    Nothing collides TODAY - eviction scans cache_immutable only, and no
    production caller writes a positive into the TTL table under one of these
    key shapes. That is a property of the current call graph, not of the
    design, and it is one new TTL-cached endpoint away from being false. These
    pin the two things that keep it true.
    """

    def test_prefix_is_pinned(self):
        self.assertEqual(RA._NEGATIVE_PREFIX, "neg")

    def test_marker_is_pinned(self):
        self.assertEqual(RA._NEGATIVE_MARKER, "__rc_negative__")

    def test_negative_key_starts_with_the_prefix_and_keeps_the_original(self):
        neg = RA._negative_key(_TIMELINE_KEY)
        self.assertTrue(neg.startswith(RA._NEGATIVE_PREFIX + ":"))
        self.assertTrue(neg.endswith(_TIMELINE_KEY))
        self.assertNotEqual(neg, _TIMELINE_KEY)

    def test_negative_key_is_injective_over_cache_keys(self):
        """Timeline and detail negatives must not alias each other."""
        self.assertNotEqual(
            RA._negative_key(_TIMELINE_KEY), RA._negative_key(_DETAIL_KEY))

    def test_negative_key_cannot_collide_with_a_positive_namespace(self):
        for positive in ("account:v1:", "match:v5:", "match:v5:timeline:",
                         "league:v4:", "mastery:v4:", "mastery_top:v4:"):
            with self.subTest(positive=positive):
                self.assertFalse(
                    RA._negative_key(_TIMELINE_KEY).startswith(positive))

    def test_a_ttl_row_without_the_marker_is_not_a_negative(self):
        """An unrelated TTL row at the same key must not read as absent."""
        RIC.get_cache().set_ttl(
            RA._negative_key(_TIMELINE_KEY), {"entries": []}, 300)
        self.assertFalse(RA._negative_cached(_TIMELINE_KEY))

    def test_marker_row_is_what_makes_negative_cached_true(self):
        RIC.get_cache().set_ttl(
            RA._negative_key(_TIMELINE_KEY),
            {RA._NEGATIVE_MARKER: True}, 300)
        self.assertTrue(RA._negative_cached(_TIMELINE_KEY))


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

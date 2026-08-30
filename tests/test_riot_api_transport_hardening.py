"""Lane 8 cycle 11: transport-layer hardening for core/riot_api.py.

Four defects, all found by auditing the module against the lane-8 dimensions
(resource lifetime, input validation, correctness-vs-docstring). The module is
otherwise in good shape - every path segment is `urllib.parse.quote`d, the
key never reaches a log line, the HTTP timeout is set, and the exception
handlers are already narrow. These four are what survived that reading.

W1  RESOURCE LIFETIME - `_http_get` leaked the error response body.
    On a non-2xx, urllib raises `HTTPError`, which is not a plain exception:
    its MRO ends `... OSError -> addinfourl -> addbase -> _TemporaryFileWrapper`,
    so it OWNS an open file object wrapping the socket. `_http_get` called
    `exc.read(4096)` and returned, and `read()` does not close. The object was
    only released when the garbage collector got to it. This sat on a HOT
    path: RM-163 records that a 404/403 on the timeline route fired on every
    single /api/last-match build (289ms of a 291ms build) before negative
    caching landed, so the leak was exercised continuously rather than in
    some rare corner.

W2  INPUT VALIDATION - a single `Retry-After` header could freeze the client
    for 31.7 YEARS. `_call_ex` did `int(resp.headers.get("Retry-After", "60"))`
    and handed the result to `DualBucket.note_429`, which did
    `self._cooldown_until = time.monotonic() + max(0.0, float(retry_after_s))`.
    `max(0.0, ...)` clamps the BOTTOM only. There is no top, so an upstream
    value of 999999999 puts every subsequent `acquire()` into permanent
    refusal - measured before the fix as 999999998.99s of cooldown and
    `acquire() -> False`. Nothing in the module can clear it: `reload_api_key`
    touches only the key cache and `_reset_bucket_for_tests` is test-only, so
    recovery required a process restart. RC's supervisor runs for days.

    The value is upstream-controlled rather than attacker-controlled (RC talks
    to *.api.riotgames.com over TLS), so this is graded as an availability /
    robustness defect, not a remote exploit. The clamp is in `note_429` rather
    than at the header parse on purpose: `note_429` is the single place that
    assigns `_cooldown_until`, so clamping there makes it unreachable for
    EVERY caller, including future ones, instead of for one call site.

W3  CORRECTNESS - `get_champion_mastery` is annotated `-> Optional[dict]` and
    its two siblings (`get_summoner_rank`, `get_top_champion_masteries`)
    return None on an unexpected body shape. This one returned whatever Riot
    sent: it guarded the CACHE WRITE with `isinstance(data, dict)` and then
    `return data` unconditionally, so a list body was refused entry to the
    cache and handed to the caller anyway. The asymmetry is the bug - the
    shape check existed and was applied to the wrong half of the function.

W4  INPUT VALIDATION - `get_top_champion_masteries` clamped `count` at the
    bottom only (`max(1, int(count))`) and interpolated it straight into the
    query string, while its sibling `get_recent_matches` clamps both ends
    (`max(1, min(100, int(count)))`). Champion-Mastery-V4 has a bounded
    result set, so an unbounded count is a request Riot will reject and a
    cache key that can be spammed with unique values.

Every test below was mutation-tested: the production line each one guards was
broken, the test was confirmed RED, and the line restored. Results are
recorded in the LEDGER entry for this cycle.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import riot_api as RA                     # noqa: E402
from core import riot_api_cache as RIC              # noqa: E402


def _resp(status: int, body=None, headers: dict | None = None):
    """Build a fake `_HttpResp` - the object `riot_api._http_get` returns.

    NOTE the `bytes` special-case ordering. The sibling helper in
    `test_riot_api_negative_cache_rm163.py` falls back to `bytes(body)` for
    anything that is not a dict or list, which is wrong for the scalar bodies
    this file needs: `bytes(42)` is FORTY-TWO NUL BYTES, not b"42", so a test
    feeding a bare `42` would exercise the JSON-parse-failure path and pass
    while proving nothing about shape validation. Two tests here did exactly
    that before this was corrected. Everything that is not already bytes is
    JSON-encoded.
    """
    if body is None:
        payload = b""
    elif isinstance(body, (bytes, bytearray)):
        payload = bytes(body)
    else:
        payload = json.dumps(body).encode("utf-8")
    return RA._HttpResp(status, payload, dict(headers or {}))


class _TrackingBody(io.BytesIO):
    """A response body that records whether anyone closed it.

    `io.BytesIO.closed` alone would do, but counting the calls also proves the
    fix does not double-close, which would raise on a real socket wrapper.
    """

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        super().close()


class _RiotApiTestBase(unittest.TestCase):
    """Fake key + private bucket + throwaway cache DB per test.

    Mirrors `tests/test_riot_api_negative_cache_rm163.py::_NegCacheBase`. The
    bucket reset matters here more than anywhere: this file deliberately puts
    the bucket into cooldown, and a leaked cooldown would make every later
    test in the process report `rate_limited` for reasons of its own making.
    """

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


# -- W1: the error response body is closed -------------------------------

class TestHttpErrorBodyIsClosed(_RiotApiTestBase):
    """`_http_get` must release the HTTPError body on every non-2xx."""

    def _get_through_httperror(self, status: int, body: bytes = b"{}"):
        """Drive `_http_get` into its HTTPError branch, return the body obj."""
        fp = _TrackingBody(body)
        err = urllib.error.HTTPError(
            "https://americas.api.riotgames.com/x", status, "err", {}, fp)
        with mock.patch.object(urllib.request, "urlopen", side_effect=err):
            resp = RA._http_get("https://americas.api.riotgames.com/x", "RGAPI-k")
        return fp, resp

    def test_404_body_is_closed(self):
        fp, resp = self._get_through_httperror(404)
        self.assertEqual(resp.status, 404)
        self.assertTrue(
            fp.closed,
            "HTTPError body left open - _http_get read it but never closed it, "
            "so the socket wrapper survives until GC")

    def test_403_body_is_closed(self):
        fp, _ = self._get_through_httperror(403)
        self.assertTrue(fp.closed, "403 error body left open")

    def test_429_body_is_closed(self):
        fp, _ = self._get_through_httperror(429)
        self.assertTrue(fp.closed, "429 error body left open")

    def test_500_body_is_closed(self):
        fp, _ = self._get_through_httperror(500)
        self.assertTrue(fp.closed, "5xx error body left open")

    def test_body_is_closed_exactly_once(self):
        """A double close would raise on a real socket wrapper, not a BytesIO."""
        fp, _ = self._get_through_httperror(404)
        self.assertEqual(fp.close_calls, 1,
                         f"expected exactly one close, got {fp.close_calls}")

    def test_body_is_still_returned_after_being_closed(self):
        """Closing must not cost the caller the payload it reads for logging."""
        fp, resp = self._get_through_httperror(404, body=b'{"status":"nf"}')
        self.assertTrue(fp.closed)
        self.assertEqual(resp.body, b'{"status":"nf"}')

    def test_body_is_closed_even_when_read_raises(self):
        """The close must sit on the exception path too, not only the happy one."""
        fp = _TrackingBody(b"{}")
        fp.read = mock.Mock(side_effect=OSError("connection reset"))
        err = urllib.error.HTTPError(
            "https://americas.api.riotgames.com/x", 404, "err", {}, fp)
        with mock.patch.object(urllib.request, "urlopen", side_effect=err):
            resp = RA._http_get("https://americas.api.riotgames.com/x", "RGAPI-k")
        self.assertEqual(resp.status, 404)
        self.assertEqual(resp.body, b"")
        self.assertTrue(
            fp.closed,
            "body left open when read() raised - the close is not on the "
            "exception path")


# -- W2: the 429 cooldown is bounded -------------------------------------

class TestRetryAfterIsClamped(_RiotApiTestBase):
    """No upstream value may put the bucket into an unrecoverable cooldown."""

    def test_module_declares_a_max_cooldown(self):
        self.assertTrue(
            hasattr(RA, "_MAX_COOLDOWN_S"),
            "core.riot_api must name its cooldown ceiling so it is greppable "
            "and pinnable, not bury a literal in note_429")
        self.assertGreater(RA._MAX_COOLDOWN_S, 0)

    def test_max_cooldown_covers_the_long_bucket_window(self):
        """The ceiling must not be tighter than a legitimate Riot backoff.

        The long bucket is 100 requests per 120s, so any real application-rate
        backoff fits well inside the ceiling. A ceiling below 120s would start
        ignoring backoffs Riot actually means.
        """
        self.assertGreaterEqual(RA._MAX_COOLDOWN_S, 120.0)
        self.assertLessEqual(RA._MAX_COOLDOWN_S, 3600.0)

    def test_note_429_clamps_an_absurd_value(self):
        b = RA.DualBucket()
        b.note_429(999999999)
        remaining = b.snapshot()["cooldown_remaining_s"]
        self.assertLessEqual(
            remaining, RA._MAX_COOLDOWN_S + 1.0,
            f"cooldown of {remaining}s accepted - one upstream header can "
            f"freeze the client for {remaining / 86400 / 365:.1f} years")

    def test_bucket_recovers_after_the_clamped_window(self):
        """The whole point: the freeze must be survivable without a restart."""
        b = RA.DualBucket()
        b.note_429(999999999)
        self.assertFalse(b.acquire(timeout_s=0.0))
        # Rewind the clock past the clamped ceiling rather than sleeping.
        b._cooldown_until -= (RA._MAX_COOLDOWN_S + 1.0)
        self.assertTrue(
            b.acquire(timeout_s=0.0),
            "bucket still refusing after the clamped window elapsed")

    def test_a_legitimate_retry_after_is_preserved(self):
        """Clamping must not flatten every backoff to the ceiling."""
        b = RA.DualBucket()
        b.note_429(30)
        remaining = b.snapshot()["cooldown_remaining_s"]
        self.assertGreater(remaining, 25.0)
        self.assertLessEqual(remaining, 30.0)

    def test_negative_retry_after_still_floors_at_zero(self):
        b = RA.DualBucket()
        b.note_429(-5)
        self.assertEqual(b.snapshot()["cooldown_remaining_s"], 0.0)
        self.assertTrue(b.acquire(timeout_s=0.0))

    def test_nan_retry_after_does_not_poison_the_bucket(self):
        """ROBUSTNESS PIN, not a guard for the W2 clamp - it held BEFORE it too.

        Called out by the verifier gate for this slice, because the honest
        grading matters: every NaN comparison is False, so `max(0.0, nan)`
        already returned 0.0 and the pre-fix code survived this input. The
        test earns its place by pinning that the NEW `min(...)` did not
        introduce a NaN path (a clamp written as a bare comparison would
        have), not by demonstrating the original defect.
        """
        b = RA.DualBucket()
        b.note_429(float("nan"))
        self.assertTrue(
            b.acquire(timeout_s=0.0),
            "a NaN cooldown left the bucket refusing - the clamp introduced a "
            "NaN path that the previous max(0.0, ...) did not have")

    def test_infinite_retry_after_is_clamped(self):
        """The unrecoverable form of W2: `inf` set `_cooldown_until` to `inf`.

        Found by the verifier gate probing the pre-fix code independently.
        `max(0.0, inf)` is `inf`, so the cooldown could never elapse - strictly
        worse than the 31.7-year case, which at least has an end.
        """
        b = RA.DualBucket()
        b.note_429(float("inf"))
        remaining = b.snapshot()["cooldown_remaining_s"]
        self.assertLessEqual(remaining, RA._MAX_COOLDOWN_S + 1.0)
        b._cooldown_until -= (RA._MAX_COOLDOWN_S + 1.0)
        self.assertTrue(b.acquire(timeout_s=0.0))

    def test_hostile_header_through_the_real_call_path(self):
        """End to end: the header value must not reach _cooldown_until raw."""
        spy = mock.Mock(return_value=_resp(429, headers={"Retry-After": "999999999"}))
        with mock.patch.object(RA, "_http_get", spy):
            data, outcome = RA._call_ex("t", "https://americas.api.riotgames.com/x")
        self.assertIsNone(data)
        self.assertEqual(outcome, "429")
        remaining = RA.bucket_snapshot()["cooldown_remaining_s"]
        self.assertLessEqual(
            remaining, RA._MAX_COOLDOWN_S + 1.0,
            f"Retry-After reached the bucket unclamped: {remaining}s")

    def test_non_numeric_header_still_falls_back_to_sixty(self):
        """The existing fallback must survive the new clamp."""
        spy = mock.Mock(return_value=_resp(
            429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}))
        with mock.patch.object(RA, "_http_get", spy):
            RA._call_ex("t", "https://americas.api.riotgames.com/x")
        remaining = RA.bucket_snapshot()["cooldown_remaining_s"]
        self.assertGreater(remaining, 55.0)
        self.assertLessEqual(remaining, 60.0)


# -- W3: mastery shape check applied to the RETURN, not just the cache ----

class TestChampionMasteryShape(_RiotApiTestBase):
    """`get_champion_mastery` is `-> Optional[dict]`; make that true."""

    def _fetch_with_body(self, body):
        spy = mock.Mock(return_value=_resp(200, body))
        with mock.patch.object(RA, "_http_get", spy):
            return RA.get_champion_mastery("puuid-abc", 64)

    def test_list_body_returns_none(self):
        got = self._fetch_with_body([{"championId": 64}])
        self.assertIsNone(
            got,
            "a list body was returned from a function annotated "
            "-> Optional[dict]; the isinstance check guards only the cache write")

    def test_scalar_body_returns_none(self):
        self.assertIsNone(self._fetch_with_body(42))

    def test_string_body_returns_none(self):
        self.assertIsNone(self._fetch_with_body("nope"))

    def test_dict_body_is_still_returned(self):
        got = self._fetch_with_body({"championId": 64, "championLevel": 7})
        self.assertIsInstance(got, dict)
        self.assertEqual(got["championLevel"], 7)

    def test_dict_body_is_still_cached(self):
        """The fix must not cost the endpoint its TTL cache."""
        spy = mock.Mock(return_value=_resp(200, {"championId": 64}))
        with mock.patch.object(RA, "_http_get", spy):
            RA.get_champion_mastery("puuid-abc", 64)
            RA.get_champion_mastery("puuid-abc", 64)
        self.assertEqual(spy.call_count, 1,
                         "second call refetched - the TTL cache write was lost")

    def test_sibling_endpoints_agree_on_the_shape_contract(self):
        """The defect was an ASYMMETRY; pin all three the same way."""
        rank_spy = mock.Mock(return_value=_resp(200, {"not": "a list"}))
        with mock.patch.object(RA, "_http_get", rank_spy):
            self.assertIsNone(RA.get_summoner_rank("puuid-abc"))
        top_spy = mock.Mock(return_value=_resp(200, {"not": "a list"}))
        with mock.patch.object(RA, "_http_get", top_spy):
            self.assertIsNone(RA.get_top_champion_masteries("puuid-abc"))


# -- W4: top-mastery count is clamped at both ends ------------------------

class TestTopMasteryCountClamp(_RiotApiTestBase):
    """`count` reaches the query string; clamp it like its sibling does."""

    _seq = 0

    def _url_for_count(self, count):
        """Fetch once and hand back the URL that reached the transport.

        Each call uses a FRESH puuid. The TTL cache keys on the CLAMPED count,
        so two clamped-equal inputs (0 and -7, both floored to 1) would share a
        cache row and the second would never reach `_http_get` at all -
        `call_args` is then None and the test fails for a reason that has
        nothing to do with clamping. Measured while writing this file.
        """
        type(self)._seq += 1
        spy = mock.Mock(return_value=_resp(200, []))
        with mock.patch.object(RA, "_http_get", spy):
            RA.get_top_champion_masteries(f"puuid-{type(self)._seq}", count=count)
        self.assertIsNotNone(
            spy.call_args,
            "transport never called - the fetch was served from cache, so this "
            "assertion would prove nothing about the URL")
        return spy.call_args[0][0]

    def test_huge_count_is_clamped_in_the_url(self):
        url = self._url_for_count(999999)
        self.assertNotIn(
            "count=999999", url,
            "unbounded count interpolated into the Riot query string")

    def test_clamped_count_is_the_declared_ceiling(self):
        url = self._url_for_count(999999)
        self.assertIn(f"count={RA._MAX_MASTERY_COUNT}", url)

    def test_reasonable_count_is_untouched(self):
        self.assertIn("count=5", self._url_for_count(5))

    def test_zero_and_negative_still_floor_at_one(self):
        self.assertIn("count=1", self._url_for_count(0))
        self.assertIn("count=1", self._url_for_count(-7))

    def test_non_numeric_count_still_falls_back_to_three(self):
        self.assertIn("count=3", self._url_for_count("many"))

    def test_recent_matches_sibling_clamp_is_unchanged(self):
        """Pin the sibling this fix is modelled on, so they cannot drift apart."""
        spy = mock.Mock(return_value=_resp(200, []))
        with mock.patch.object(RA, "_http_get", spy):
            RA.get_recent_matches("puuid-abc", count=999999)
        self.assertIn("count=100", spy.call_args[0][0])


if __name__ == "__main__":
    unittest.main()

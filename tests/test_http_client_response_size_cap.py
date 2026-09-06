# arch: lane 10 queue RM-351 - lib/http/client.py response size cap | section=tests | frozen=no
"""RM-351 - the single outbound chokepoint read every response to EOF.

DEFECT, measured against the pre-fix file:

  `lib/http/client.py:497` was `body = resp.read()` with no argument, and the
  4xx/5xx path at `:508` was `body = e.read() if hasattr(e, "read") else b""`.
  Neither had a `Content-Length` pre-check, and `request`/`get`/`post` carried
  no `max_bytes` parameter, so there was no bound anywhere in the module. The
  `timeout` argument bounds TIME, not BYTES: a slow-drip endpoint that keeps
  handing over data inside the inactivity timeout streams forever, and every
  DDragon bundle, every scraped page and every robots.txt lands on that line.

  This is the same amplification class lane 8 cycle 20 fixed at the `:8889`
  inference boundary (a 5 KB crop read into a 16 MB buffer), one layer lower
  and shared by every outbound fetch in the tree.

WHAT THE FIX SHIPS, and why each half is shaped the way it is:

  - SUCCESS PATH raises. Over the cap, `request` raises `ResponseTooLarge`
    (an `HttpError` subclass) naming the cap, because a truncated 200 body is
    a LIE to the caller - `resp.json()` on half a document raises somewhere
    far away from the real cause.
  - ERROR PATH truncates. A 4xx/5xx body is diagnostic only; the caller reads
    `resp.status`. Raising there would convert a well-formed 404 into a
    network-class exception AND skip the `_on_success` breaker bookkeeping
    that a working-but-refusing remote is supposed to get. So the error body
    is cut at the cap and a warning is logged. That asymmetry is deliberate
    and `ErrorBodyCapTests` below pins it.
  - THE CAP DOES NOT TRIP THE BREAKER. It is a client-side policy rejection,
    exactly like `Blocked`, not evidence that the remote is unhealthy. The
    probe slot is still released (via the existing `finally`), which
    `CapDoesNotWedgeTheBreakerTests` proves.

MUTATION EVIDENCE (run 2026-09-06, each mutant applied to the FIXED file,
suite re-run, mutant reverted):

  1. `_read_bounded` short-circuited to an unbounded `reader.read()`
     -> 7 of 13 red: test_explicit_cap_raises_and_stops_reading,
        test_the_cap_is_enforced_on_post_too,
        test_default_cap_bounds_an_endless_stream,
        test_error_body_is_truncated_at_the_cap,
        test_error_status_survives_a_truncated_body,
        test_over_cap_does_not_count_toward_the_breaker,
        test_over_cap_releases_the_half_open_probe_slot
  2. success path ignoring the over-cap flag (returning the short body
     instead of raising)
     -> 5 of 13 red: test_explicit_cap_raises_and_stops_reading,
        test_the_cap_is_enforced_on_post_too,
        test_default_cap_bounds_an_endless_stream,
        test_over_cap_does_not_count_toward_the_breaker,
        test_over_cap_releases_the_half_open_probe_slot
  3. error path raising instead of truncating
     -> 2 of 13 red: test_error_body_is_truncated_at_the_cap,
        test_error_status_survives_a_truncated_body

No mutant left the file green, and no two mutants have the same kill set - so
each of the three behaviours is separately load-bearing rather than one
assertion standing in for all of them.

STUB FIDELITY NOTE. `_FakeHttpResponse` in the two lane-8 cycle-27 files
defined `read(self)` with no amount parameter, which the real
`http.client.HTTPResponse.read(amt)` and `HTTPError.read(amt)` both accept.
Those stubs were widened to take an optional amount in this same commit; that
is a fidelity fix to the mock, not a production behaviour change.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib import error as urllib_error

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lib.http.client as http_client  # noqa: E402
from lib.http.client import HttpClient, HttpError  # noqa: E402

URL = "https://example.test/resource"


def _write_blocklist(directory: str) -> Path:
    path = Path(directory) / "blocklist.json"
    path.write_text(json.dumps({"hostnames": [], "suffixes": []}), encoding="utf-8")
    return path


class _EndlessResponse:
    """Opener stand-in whose body never ends.

    `read(amt)` hands back exactly `amt` bytes forever and records the running
    total, so a test can assert how much the client actually pulled off the
    wire. `read()` with no amount would never return, which is precisely the
    pre-fix behaviour this row is about - so it raises instead of hanging the
    suite, making an unbounded read a loud failure rather than a timeout.
    """

    def __init__(self, status: int = 200, url: str = URL) -> None:
        self.status = status
        self.url = url
        self.served = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, amt=None):
        if amt is None:
            raise AssertionError(
                "unbounded read() reached the endless stream - the client did "
                "not pass a byte cap down to the response"
            )
        self.served += amt
        return b"\0" * amt

    def getheaders(self):
        return [("Content-Type", "application/octet-stream")]


class _FiniteResponse:
    """Opener stand-in with a real, finite body that honours `read(amt)`."""

    def __init__(self, body: bytes, status: int = 200, url: str = URL) -> None:
        self.status = status
        self.url = url
        self._buf = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, amt=None):
        return self._buf.read() if amt is None else self._buf.read(amt)

    def getheaders(self):
        return [("Content-Type", "application/octet-stream")]


class _CapTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rm351_")
        self.addCleanup(self._tmp.cleanup)
        self.client = HttpClient(blocklist_path=_write_blocklist(self._tmp.name))
        # The rate limiter sleeps up to MIN_INTERVAL_SEC between calls to one
        # host. Nothing here tests the rate gate, so neutralise it.
        patcher = mock.patch.object(self.client, "_rate_gate", lambda host: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _patch_opener(self, **kw):
        return mock.patch.object(self.client._opener, "open", **kw)


class ExplicitCapTests(_CapTestBase):
    def test_explicit_cap_raises_and_stops_reading(self):
        """ACCEPTANCE: max_bytes=1024 against an endless stream raises and
        reads at most ~1024 bytes."""
        endless = _EndlessResponse()
        with self._patch_opener(return_value=endless):
            with self.assertRaises(HttpError) as ctx:
                self.client.get(URL, max_bytes=1024)

        self.assertIsInstance(ctx.exception, http_client.ResponseTooLarge)
        self.assertIn("1024", str(ctx.exception))
        self.assertIn(URL, str(ctx.exception))
        # The contract is "at most the cap plus one chunk" - the client reads
        # one byte past the cap to learn that it was exceeded.
        self.assertLessEqual(
            endless.served,
            1024 + http_client.READ_CHUNK_BYTES,
            f"read {endless.served} bytes for a 1024-byte cap",
        )
        # ...and independently, that it is bounded AT ALL against a stream
        # that would otherwise have run until memory ran out.
        self.assertLess(endless.served, 1_000_000)

    def test_a_body_under_the_cap_is_returned_whole(self):
        """The cap must not truncate or reject a normal response."""
        body = b"x" * 4096
        with self._patch_opener(return_value=_FiniteResponse(body)):
            resp = self.client.get(URL, max_bytes=8192)
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body, body)

    def test_a_body_exactly_at_the_cap_is_allowed(self):
        """The boundary is inclusive - cap bytes is not over the cap."""
        body = b"y" * 2048
        with self._patch_opener(return_value=_FiniteResponse(body)):
            resp = self.client.get(URL, max_bytes=2048)
        self.assertEqual(resp.body, body)

    def test_max_bytes_none_disables_the_cap(self):
        """An explicit opt-out exists for a caller that knows it wants it all."""
        body = b"z" * 4096
        with self._patch_opener(return_value=_FiniteResponse(body)):
            resp = self.client.get(URL, max_bytes=None)
        self.assertEqual(resp.body, body)

    def test_a_negative_cap_is_rejected(self):
        """A nonsense cap fails at the call, not silently as 'unlimited'."""
        with self._patch_opener(return_value=_FiniteResponse(b"ok")):
            with self.assertRaises(ValueError):
                self.client.get(URL, max_bytes=-1)

    def test_the_cap_is_enforced_on_post_too(self):
        """The bound lives in `request`, the chokepoint - not in `get`.

        A cap implemented in `get` alone would leave `post` unbounded, and
        this test is the only thing that would notice.
        """
        endless = _EndlessResponse()
        with self._patch_opener(return_value=endless):
            with self.assertRaises(HttpError):
                self.client.post(URL, data=b"{}", max_bytes=512)
        self.assertLess(endless.served, 1_000_000)


class DefaultCapTests(_CapTestBase):
    def test_a_default_cap_constant_exists_and_is_sane(self):
        cap = http_client.DEFAULT_MAX_RESPONSE_BYTES
        self.assertIsInstance(cap, int)
        # Bigger than the largest artefact any in-tree caller pulls (a DDragon
        # bundle is single-digit MB) and small enough to bound amplification.
        self.assertGreaterEqual(cap, 4 * 1024 * 1024)
        self.assertLessEqual(cap, 64 * 1024 * 1024)

    def test_default_cap_bounds_an_endless_stream(self):
        """ACCEPTANCE (second half): existing callers inherit a cap.

        This deliberately exercises the SHIPPED default rather than a patched
        one - the number that protects real callers is the one under test.
        """
        endless = _EndlessResponse()
        with self._patch_opener(return_value=endless):
            with self.assertRaises(HttpError) as ctx:
                self.client.get(URL)
        self.assertIsInstance(ctx.exception, http_client.ResponseTooLarge)
        self.assertLessEqual(
            endless.served,
            http_client.DEFAULT_MAX_RESPONSE_BYTES + http_client.READ_CHUNK_BYTES,
        )


class ErrorBodyCapTests(_CapTestBase):
    """The 4xx/5xx path truncates rather than raising - see the module note."""

    def _http_error(self, code: int, body: bytes):
        return urllib_error.HTTPError(
            URL, code, f"status {code}", {"Content-Type": "text/plain"}, io.BytesIO(body)
        )

    def test_error_body_is_truncated_at_the_cap(self):
        err = self._http_error(404, b"e" * 5000)
        with self._patch_opener(side_effect=err):
            resp = self.client.get(URL, max_bytes=1024)
        self.assertEqual(len(resp.body), 1024)

    def test_error_status_survives_a_truncated_body(self):
        err = self._http_error(503, b"e" * 5000)
        with self._patch_opener(side_effect=err):
            resp = self.client.get(URL, max_bytes=100)
        self.assertEqual(resp.status, 503)
        self.assertEqual(len(resp.body), 100)

    def test_a_small_error_body_is_untouched(self):
        err = self._http_error(400, b"short")
        with self._patch_opener(side_effect=err):
            resp = self.client.get(URL, max_bytes=1024)
        self.assertEqual(resp.body, b"short")


class CapDoesNotWedgeTheBreakerTests(_CapTestBase):
    """An over-cap response is a POLICY rejection, not a remote failure."""

    def test_over_cap_does_not_count_toward_the_breaker(self):
        host = "example.test"
        for _ in range(http_client.BREAKER_THRESHOLD + 1):
            with self._patch_opener(return_value=_EndlessResponse()):
                with self.assertRaises(HttpError):
                    self.client.get(URL, max_bytes=256)
        st = self.client._host_state(host)
        self.assertEqual(st.failures, 0)
        self.assertIsNone(st.opened_at)

    def test_over_cap_releases_the_half_open_probe_slot(self):
        """Without the existing `finally`, one over-cap read would wedge the
        hostname for the life of the process."""
        host = "example.test"
        with self._patch_opener(return_value=_EndlessResponse()):
            with self.assertRaises(HttpError):
                self.client.get(URL, max_bytes=256)
        self.assertFalse(self.client._host_state(host).probe_in_flight)


if __name__ == "__main__":
    unittest.main()

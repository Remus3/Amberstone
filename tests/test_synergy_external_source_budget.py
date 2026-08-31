"""Regression tests for the three cost/robustness defects in the live
duo-synergy fetch primitive (core.synergy_external_source, lane 8 true-audit).

This module is DEFAULT ON in production (core.smoothed_rates_101qq
`_live_enabled()` reads RC_DUO_SYNERGY_LIVE defaulting to "1") and it talks
to a third-party CN endpoint RC does not control, so all three defects are
live-path exposures:

  1. TOTAL TIME BUDGET. fetch_rows loops over _candidate_dates() and gave
     each attempt the full per-socket _TIMEOUT_S. A socket timeout is not a
     deadline (a slow-drip server resets it on every byte), so the worst
     case was at least _DATE_LOOKBACK_DAYS * _TIMEOUT_S and in principle
     unbounded. A total deadline now bounds the whole loop and shrinks the
     per-attempt timeout to the remaining budget.
  2. NEGATIVE CACHING. Only successes were cached, so every call re-paid the
     entire timeout budget while the endpoint was down. A short negative TTL
     now makes a down endpoint cheap to ask about (force_refresh bypasses it).
  3. RESPONSE SIZE CAP. _http_get_json did an uncapped r.read(), so a hostile
     or malfunctioning endpoint could stream unbounded bytes into memory.

Nothing here touches the network: the _http_get_json seam and
urllib.request.urlopen are both stubbed.
"""
from __future__ import annotations

import json
import math
import sys
import time as _time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import synergy_external_source as S  # noqa: E402

_GOOD_ROW = {
    "championid1": "498", "championid2": "497",
    "doublewinrate": 0.56, "iwinrate1": 0.5, "iwinrate2": 0.5,
    "itemp1": "4.42%", "irank": 1,
    "lane1": "bottom", "lane2": "support",
}


# The GENUINE _http_get_json, captured at import (pytest imports every module
# during collection, before any test body runs). tests/test_synergy_external_
# source.py::FetchRowsTests monkey-patches this seam and its tearDown does NOT
# restore it, so whether the real function is still installed depends on test
# ORDER - which under `-n 8` is not even deterministic. The size-cap and
# non-finite tests below drive the real function through a stubbed urlopen, so
# they must install it themselves rather than inherit whatever leaked.
_REAL_HTTP_GET_JSON = S._http_get_json


class _SeamBase(unittest.TestCase):
    """Deterministic clock + date + a known-genuine HTTP seam, all restored
    on teardown (which also repairs the sibling module's leak)."""

    def setUp(self) -> None:
        S._reset_cache_for_tests()
        S._http_get_json = _REAL_HTTP_GET_JSON
        # Loud, not vacuous: if the capture above ever grabbed a leaked stub,
        # every test here would silently exercise the wrong callable.
        self.assertEqual(getattr(S._http_get_json, "__name__", ""),
                         "_http_get_json",
                         "the real _http_get_json was not installed")
        self._t = [1000.0]
        S._clock = lambda: self._t[0]
        S._utcnow = lambda: datetime(2026, 6, 2, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        S._http_get_json = _REAL_HTTP_GET_JSON
        S._clock = _time.monotonic
        S._utcnow = lambda: datetime.now(timezone.utc)
        S._reset_cache_for_tests()


class TotalTimeBudgetTests(_SeamBase):
    """Defect 1: the date loop must respect a TOTAL wall-clock deadline."""

    def _install_timeout_burner(self) -> list:
        """Each attempt burns exactly the timeout it was handed, then fails -
        the worst realistic case (every date times out)."""
        seen: list = []

        def burner(url, timeout_s=S._TIMEOUT_S):
            seen.append(timeout_s)
            self._t[0] += timeout_s
            raise S.SynergyError("attempt timed out")

        S._http_get_json = burner
        return seen

    def test_budget_constant_actually_bounds_the_loop(self) -> None:
        """A budget >= the naive worst case would bound nothing."""
        self.assertLess(
            S._TOTAL_BUDGET_S, S._DATE_LOOKBACK_DAYS * S._TIMEOUT_S,
            "the total budget must be tighter than the un-deadlined worst case")
        self.assertGreater(S._TOTAL_BUDGET_S, S._TIMEOUT_S,
                           "the budget must still allow more than one attempt")

    def test_total_elapsed_is_bounded_by_the_budget(self) -> None:
        self._install_timeout_burner()
        start = self._t[0]
        self.assertIsNone(S.fetch_rows("bottom", "support"))
        elapsed = self._t[0] - start
        self.assertLessEqual(
            elapsed, S._TOTAL_BUDGET_S + 1e-9,
            "fetch_rows overran its total wall-clock budget")
        self.assertLess(
            elapsed, S._DATE_LOOKBACK_DAYS * S._TIMEOUT_S,
            "elapsed must be well under the un-deadlined worst case")

    def test_no_attempt_is_started_or_sized_past_the_deadline(self) -> None:
        seen = self._install_timeout_burner()
        S.fetch_rows("bottom", "support")
        self.assertGreater(len(seen), 0, "at least one attempt must be made")
        running = 0.0
        for i, t in enumerate(seen):
            self.assertGreater(t, 0.0, "an attempt must get a positive timeout")
            self.assertLessEqual(t, S._TIMEOUT_S,
                                 "an attempt must never exceed the per-attempt timeout")
            running += t
            self.assertLessEqual(
                running, S._TOTAL_BUDGET_S + 1e-9,
                f"attempt {i} was allowed to run past the total deadline")

    def test_a_fast_success_is_unaffected_by_the_deadline(self) -> None:
        calls: list = []

        def ok(url, timeout_s=S._TIMEOUT_S):
            calls.append(url)
            return {"code": 0, "data": [dict(_GOOD_ROW)]}

        S._http_get_json = ok
        rows = S.fetch_rows("bottom", "support")
        self.assertIsNotNone(rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(calls), 1)


class NegativeCacheTests(_SeamBase):
    """Defect 2: a failure must be remembered briefly so a down endpoint is
    cheap to ask about. fetch_rows still returns None - just fast."""

    def _install_failing(self) -> list:
        calls: list = []

        def boom(url, timeout_s=S._TIMEOUT_S):
            calls.append(url)
            raise S.SynergyError("endpoint down")

        S._http_get_json = boom
        return calls

    def _install_ok(self) -> list:
        calls: list = []

        def ok(url, timeout_s=S._TIMEOUT_S):
            calls.append(url)
            return {"code": 0, "data": [dict(_GOOD_ROW)]}

        S._http_get_json = ok
        return calls

    def test_negative_ttl_is_much_shorter_than_the_success_ttl(self) -> None:
        self.assertGreater(S._NEG_TTL_S, 0.0)
        self.assertLess(S._NEG_TTL_S, S._TTL_S / 4.0,
                        "a remembered failure must expire far sooner than a success")

    def test_second_call_after_a_failure_makes_zero_attempts(self) -> None:
        calls = self._install_failing()
        self.assertIsNone(S.fetch_rows("bottom", "support"))
        n = len(calls)
        self.assertEqual(n, S._DATE_LOOKBACK_DAYS,
                         "the first call tries every candidate date")
        self.assertIsNone(S.fetch_rows("bottom", "support"))
        self.assertEqual(
            len(calls), n,
            "a remembered failure must not re-pay the whole timeout budget")

    def test_the_negative_entry_is_never_served_as_data(self) -> None:
        self._install_failing()
        self.assertIsNone(S.fetch_rows("bottom", "support"))
        self.assertIsNone(S.fetch_rows("bottom", "support"))

    def test_force_refresh_bypasses_the_negative_cache(self) -> None:
        calls = self._install_failing()
        self.assertIsNone(S.fetch_rows("bottom", "support"))
        n = len(calls)
        self.assertIsNone(S.fetch_rows("bottom", "support", force_refresh=True))
        self.assertGreater(len(calls), n,
                           "force_refresh must retry a remembered failure")

    def test_the_negative_entry_expires(self) -> None:
        calls = self._install_failing()
        self.assertIsNone(S.fetch_rows("bottom", "support"))
        n = len(calls)
        self._t[0] += S._NEG_TTL_S + 1.0
        self.assertIsNone(S.fetch_rows("bottom", "support"))
        self.assertGreater(len(calls), n,
                           "an expired negative entry must retry")

    def test_the_negative_entry_is_per_lane_pair(self) -> None:
        calls = self._install_failing()
        self.assertIsNone(S.fetch_rows("bottom", "support"))
        n = len(calls)
        self.assertIsNone(S.fetch_rows("top", "jungle"))
        self.assertGreater(len(calls), n,
                           "a different lane pair must not inherit the failure")

    def test_a_success_clears_the_remembered_failure(self) -> None:
        self._install_failing()
        self.assertIsNone(S.fetch_rows("bottom", "support"))
        ok_calls = self._install_ok()
        rows = S.fetch_rows("bottom", "support", force_refresh=True)
        self.assertIsNotNone(rows)
        self.assertEqual(len(ok_calls), 1)
        # The plain (non-forced) call now serves the positive cache, not the
        # stale negative entry.
        rows2 = S.fetch_rows("bottom", "support")
        self.assertIsNotNone(rows2)
        self.assertEqual(len(ok_calls), 1)

    def test_reset_clears_the_negative_cache(self) -> None:
        calls = self._install_failing()
        self.assertIsNone(S.fetch_rows("bottom", "support"))
        n = len(calls)
        S._reset_cache_for_tests()
        self.assertIsNone(S.fetch_rows("bottom", "support"))
        self.assertGreater(len(calls), n,
                           "_reset_cache_for_tests must clear negatives too")


class _FakeResponse:
    """Minimal urlopen stand-in: a context manager with .status and a read()
    that honours a byte count, exactly like a real HTTPResponse."""

    def __init__(self, body: bytes, status: int = 200, seen: Optional[list] = None):
        self._body = body
        self.status = status
        self._seen = seen if seen is not None else []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, amt=-1):
        self._seen.append(amt)
        if amt is None or amt < 0:
            return self._body
        return self._body[:amt]


def _padded_json(pad_bytes: int) -> bytes:
    """A VALID JSON envelope of at least pad_bytes. Valid on purpose: an
    invalid oversized body would raise SynergyError via the JSON path even
    with no size cap, and the test would pass vacuously."""
    return b'{"code": 0, "data": [], "pad": "' + (b"x" * pad_bytes) + b'"}'


class ResponseSizeCapTests(_SeamBase):
    """Defect 3: an untrusted third-party body must not be read unbounded."""

    def test_cap_is_generous_but_still_a_cap(self) -> None:
        """Lower bound: a full 200-row page (well under 100 KB) must never be
        rejected. Upper bound: a cap large enough to OOM the process is not a
        cap - the oversize tests are cap-relative, so this is what catches
        someone simply raising the constant."""
        self.assertGreaterEqual(S._MAX_RESPONSE_BYTES, 1024 * 1024)
        self.assertLessEqual(S._MAX_RESPONSE_BYTES, 16 * 1024 * 1024)

    def test_oversized_body_raises_synergy_error(self) -> None:
        body = _padded_json(S._MAX_RESPONSE_BYTES + 64)
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(body)):
            with self.assertRaisesRegex(S.SynergyError, "too large"):
                S._http_get_json("https://example.invalid/getRankDouble")

    def test_read_is_capped_at_the_limit_plus_one_byte(self) -> None:
        """Overflow must be DETECTED without buffering the whole stream."""
        seen: list = []
        body = _padded_json(S._MAX_RESPONSE_BYTES + 64)
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(body, seen=seen)):
            with self.assertRaises(S.SynergyError):
                S._http_get_json("https://example.invalid/getRankDouble")
        self.assertEqual(
            seen, [S._MAX_RESPONSE_BYTES + 1],
            "read() must ask for at most the cap plus one byte")

    def test_fetch_rows_is_still_fail_soft_on_an_oversized_body(self) -> None:
        body = _padded_json(S._MAX_RESPONSE_BYTES + 64)
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(body)):
            self.assertIsNone(S.fetch_rows("bottom", "support"))

    def test_a_normal_sized_body_still_parses(self) -> None:
        body = b'{"code": 0, "data": [{"championid1": "498",' \
               b' "championid2": "497", "doublewinrate": 0.56}]}'
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(body)):
            data = S._http_get_json("https://example.invalid/getRankDouble")
            self.assertEqual(data["code"], 0)
            rows = S.fetch_rows("bottom", "support")
        self.assertIsNotNone(rows)
        self.assertEqual(len(rows), 1)

    def test_a_body_just_under_the_cap_is_accepted(self) -> None:
        """Guards the boundary against an off-by-one that would break normal
        operation instead of only hostile payloads."""
        pad = S._MAX_RESPONSE_BYTES - 128
        body = _padded_json(pad)
        self.assertLessEqual(len(body), S._MAX_RESPONSE_BYTES)
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(body)):
            data = S._http_get_json("https://example.invalid/getRankDouble")
        self.assertEqual(data["code"], 0)


class NonFiniteRejectionTests(_SeamBase):
    """Defect 4: json.loads accepts the NON-STANDARD literals NaN, Infinity
    and -Infinity by default, and isinstance(float("nan"), float) is True, so
    a NaN doublewinrate used to survive _validate_rows untouched, get sorted
    on by core.smoothed_rates_101qq, and finally be re-emitted by json.dumps
    (allow_nan defaults True) as a bare NaN token. That token is NOT valid
    JSON: a browser JSON.parse rejects it, so ONE poisoned row breaks the
    ENTIRE /api/duo-synergy response, not just its own row.

    Two independent gates, tested separately because either alone would mask
    the other: the parse boundary (whole class killed at the door) and the
    per-row isfinite check (a value that arrived some other way).
    """

    @staticmethod
    def _body(literal: str) -> bytes:
        return (
            b'{"code": 0, "data": [{"championid1": "498",'
            b' "championid2": "497", "doublewinrate": '
            + literal.encode("ascii") + b"}]}"
        )

    # --- gate 1: the parse boundary ---------------------------------------
    def test_parse_boundary_rejects_nan(self) -> None:
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(self._body("NaN"))):
            with self.assertRaisesRegex(S.SynergyError, "non-finite"):
                S._http_get_json("https://example.invalid/getRankDouble")

    def test_parse_boundary_rejects_infinity(self) -> None:
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(self._body("Infinity"))):
            with self.assertRaisesRegex(S.SynergyError, "non-finite"):
                S._http_get_json("https://example.invalid/getRankDouble")

    def test_parse_boundary_rejects_negative_infinity(self) -> None:
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(self._body("-Infinity"))):
            with self.assertRaisesRegex(S.SynergyError, "non-finite"):
                S._http_get_json("https://example.invalid/getRankDouble")

    def test_parse_boundary_rejects_a_non_finite_anywhere_in_the_envelope(self) -> None:
        """Not just doublewinrate - any non-standard literal in the payload."""
        body = (b'{"code": 0, "junk": Infinity, "data": [{"championid1": "1",'
                b' "championid2": "2", "doublewinrate": 0.5}]}')
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(body)):
            with self.assertRaisesRegex(S.SynergyError, "non-finite"):
                S._http_get_json("https://example.invalid/getRankDouble")

    # --- gate 2: the per-row isfinite check --------------------------------
    def test_validate_rows_drops_a_non_finite_rate(self) -> None:
        """Belt and braces: a non-finite value that reached _validate_rows by
        some other route must be dropped, not returned."""
        poisoned = {**_GOOD_ROW, "doublewinrate": float("nan")}
        good = {**_GOOD_ROW, "championid1": "1", "doublewinrate": 0.51}
        out = S._validate_rows({"code": 0, "data": [poisoned, good]})
        self.assertEqual(len(out), 1, "the NaN row must be dropped")
        self.assertEqual(out[0]["championid1"], "1")

    def test_validate_rows_drops_infinite_rates(self) -> None:
        for bad in (float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                good = {**_GOOD_ROW, "championid1": "1", "doublewinrate": 0.51}
                out = S._validate_rows({
                    "code": 0,
                    "data": [{**_GOOD_ROW, "doublewinrate": bad}, good],
                })
                self.assertEqual(len(out), 1)
                self.assertEqual(out[0]["championid1"], "1")

    def test_validate_rows_drops_a_bool_rate(self) -> None:
        """bool is a subclass of int, so `true` used to pass the isinstance
        type check as a win rate."""
        good = {**_GOOD_ROW, "championid1": "1", "doublewinrate": 0.51}
        out = S._validate_rows({
            "code": 0,
            "data": [{**_GOOD_ROW, "doublewinrate": True}, good],
        })
        self.assertEqual(len(out), 1, "a boolean is not a win rate")
        self.assertEqual(out[0]["championid1"], "1")

    def test_an_all_poisoned_payload_is_fail_soft(self) -> None:
        with self.assertRaises(S.SynergyError):
            S._validate_rows({
                "code": 0,
                "data": [{**_GOOD_ROW, "doublewinrate": float("nan")}],
            })

    # --- end to end --------------------------------------------------------
    def test_fetch_rows_returns_none_for_a_nan_payload(self) -> None:
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(self._body("NaN"))):
            self.assertIsNone(S.fetch_rows("bottom", "support"))

    def test_the_happy_path_is_not_over_rejected(self) -> None:
        """A NEGATIVE assertion ("returns None") passes for the wrong reason
        if the gate rejects everything, so assert the finite payload STILL
        returns its rows and that every numeric value in them is finite."""
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(self._body("0.56"))):
            rows = S.fetch_rows("bottom", "support")
        self.assertIsNotNone(rows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["doublewinrate"], 0.56)
        for row in rows:
            for key, value in row.items():
                if isinstance(value, float):
                    self.assertTrue(math.isfinite(value),
                                    f"{key}={value!r} is not finite")

    def test_returned_rows_are_json_serializable_strictly(self) -> None:
        """The exact downstream failure: json.dumps re-emits a bare NaN token
        that a browser JSON.parse rejects. A strict re-parse proves the rows
        this module hands out cannot poison /api/duo-synergy."""
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(self._body("0.56"))):
            rows = S.fetch_rows("bottom", "support")
        blob = json.dumps({"rows": rows})

        def _strict(token):
            raise AssertionError(f"payload carried the invalid token {token}")

        json.loads(blob, parse_constant=_strict)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self) -> None:
        b = (_ROOT / "core" / "synergy_external_source.py").read_bytes()
        self.assertEqual([(i, x) for i, x in enumerate(b) if x > 0x7F], [])

    def test_this_file_is_ascii(self) -> None:
        b = Path(__file__).read_bytes()
        self.assertEqual([(i, x) for i, x in enumerate(b) if x > 0x7F], [])


if __name__ == "__main__":
    unittest.main()

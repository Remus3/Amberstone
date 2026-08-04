"""Envelope-validation guards for core/liveclient_cache.py (lane 8 cycle 7).

`_fetch_once` parses an HTTP envelope RC does not author: the vision relay at
:8889/latest-liveclient is a separate process with its own release cadence.
Three defects were MEASURED on 2026-08-03 by driving `_fetch_once` with
adversarial bodies, and all three fail OPEN - stale or unusable data reads as
LIVE to every consumer:

1. `ts` missing or null with `data` present -> `age_s` was 0.0, i.e. "perfectly
   fresh", forever. Eight production consumers gate on that number
   (`dashboard/routes_state.py:243,906,991`, `dashboard/_liveclient.py:140`,
   `dashboard/_state_cooldowns.py:255`, `coaches/_base_coach.py:689`,
   `modes/shared_vision.py:183`, plus `core/decision_detector.py:830` and
   `core/vision_tracker.py:279` which pass it out), so a timestamp-less
   envelope defeated every freshness gate at once.
2. `ts` in the future -> `max(0.0, ...)` clamped the negative age to 0.0, so a
   skewed or forged timestamp also read as permanently fresh.
3. `ts` non-numeric (a string, a list) -> `float()` raised OUTSIDE the
   try/except in `_fetch_once`, so the exception escaped into the poll loop,
   which logged it at DEBUG and left `_snapshot` frozen at its previous value.

The contract these tests pin is FAIL-CLOSED: an envelope whose age cannot be
established is reported as stale (`_UNKNOWN_AGE_S`), never as fresh, and a
malformed envelope is logged at WARNING so a relay contract change is visible
in `logs/` rather than silent at debug level.
"""
from __future__ import annotations

import json
import logging
import time
import unittest
from unittest import mock

from core.liveclient_cache import _UNKNOWN_AGE_S, Snapshot
import core.liveclient_cache as lc


class _FakeResp:
    def __init__(self, body: str) -> None:
        self._b = body.encode()

    def read(self) -> bytes:
        return self._b

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *a: object) -> bool:
        return False


def _fetch_with(body: str) -> Snapshot:
    """Drive one _fetch_once round-trip against a canned relay body."""
    with mock.patch.object(lc, "urlopen", lambda req, timeout=None: _FakeResp(body)):
        return lc._fetch_once()


class TestAgeIsFailClosed(unittest.TestCase):
    """Defects 1 and 2: an unestablishable age must never read as fresh."""

    # The loosest gate in production is 12.0s (coaches/_base_coach.py:689);
    # the tightest is 5s (dashboard/_liveclient.py:140). A sentinel is only
    # useful if it defeats the loosest one.
    LOOSEST_CONSUMER_GATE_S = 12.0

    def test_missing_ts_with_data_is_not_fresh(self):
        snap = _fetch_with(json.dumps({"data": {"gameData": {}}}))
        self.assertIsNotNone(snap.data, "data should still be delivered")
        self.assertGreater(snap.age_s, self.LOOSEST_CONSUMER_GATE_S)

    def test_null_ts_with_data_is_not_fresh(self):
        snap = _fetch_with(json.dumps({"data": {"gameData": {}}, "ts": None}))
        self.assertIsNotNone(snap.data)
        self.assertGreater(snap.age_s, self.LOOSEST_CONSUMER_GATE_S)

    def test_future_ts_is_not_fresh(self):
        body = json.dumps({"data": {"gameData": {}}, "ts": time.time() + 86400})
        snap = _fetch_with(body)
        self.assertGreater(snap.age_s, self.LOOSEST_CONSUMER_GATE_S)

    def test_small_future_skew_is_tolerated_as_fresh(self):
        """A sub-second future ts is ordinary clock jitter, not a bad envelope."""
        body = json.dumps({"data": {"gameData": {}}, "ts": time.time() + 0.25})
        snap = _fetch_with(body)
        self.assertLess(snap.age_s, 1.0)

    def test_unknown_age_is_json_serializable(self):
        """core/decision_detector.py:830 and core/vision_tracker.py:279 return
        age_s to callers, so the sentinel must not be float('inf') - json.dumps
        emits a bare `Infinity`, which is not valid JSON."""
        self.assertTrue(float("-inf") < _UNKNOWN_AGE_S < float("inf"))
        self.assertEqual(json.loads(json.dumps({"age_s": _UNKNOWN_AGE_S}))["age_s"],
                         _UNKNOWN_AGE_S)


class TestMalformedTsDoesNotEscape(unittest.TestCase):
    """Defect 3: a non-numeric ts must not raise out of _fetch_once."""

    def test_non_numeric_string_ts_does_not_raise(self):
        snap = _fetch_with(json.dumps({"data": {"gameData": {}}, "ts": "abc"}))
        self.assertGreater(snap.age_s, 12.0)

    def test_list_ts_does_not_raise(self):
        snap = _fetch_with(json.dumps({"data": {"gameData": {}}, "ts": [1]}))
        self.assertGreater(snap.age_s, 12.0)

    def test_bool_ts_is_rejected_not_coerced_to_1970(self):
        """`float(True)` is 1.0 - a 1970 timestamp, not a missing one.

        Asserts the UNKNOWN sentinel exactly, not merely "older than the
        loosest gate": a 1970 timestamp is also older than every gate, so a
        `>` assertion here is vacuous and survives deletion of the bool guard
        (measured - this test passed mutation M5 before being tightened).
        """
        snap = _fetch_with(json.dumps({"data": {"gameData": {}}, "ts": True}))
        self.assertEqual(snap.age_s, _UNKNOWN_AGE_S)

    def test_malformed_ts_is_logged_at_warning(self):
        """A relay contract change must be visible in logs/, not debug-only."""
        with self.assertLogs("rc.liveclient_cache", level="WARNING") as cm:
            _fetch_with(json.dumps({"data": {"gameData": {}}, "ts": "abc"}))
        self.assertTrue(any("ts" in line for line in cm.output), cm.output)


class TestExistingContractPreserved(unittest.TestCase):
    """Characterization: what already worked must keep working."""

    def test_valid_envelope_is_fresh(self):
        body = json.dumps({"data": {"gameData": {}}, "ts": time.time()})
        snap = _fetch_with(body)
        self.assertIsNotNone(snap.data)
        self.assertLess(snap.age_s, 5.0)
        self.assertFalse(snap.no_game)

    def test_old_ts_reports_real_age(self):
        body = json.dumps({"data": {"gameData": {}}, "ts": time.time() - 30.0})
        snap = _fetch_with(body)
        self.assertGreater(snap.age_s, 29.0)
        self.assertLess(snap.age_s, _UNKNOWN_AGE_S)

    def test_no_data_still_reports_zero_age(self):
        """Consumers check `snap.data is None` first; the empty snapshot's age
        stays 0.0 so tests/test_liveclient_cache_reuse_hot02.py:89 holds."""
        self.assertEqual(Snapshot(data=None, ts=0.0).age_s, 0.0)
        self.assertEqual(Snapshot().age_s, 0.0)

    def test_age_s_is_total_for_a_directly_built_snapshot(self):
        """`ts: float` is an annotation, not an enforcement. A Snapshot built
        outside _fetch_once can carry any object; age_s is read on every
        consumer's hot path, so it must report stale rather than raise."""
        for bad_ts in ("abc", [1], {"a": 1}, None, object()):
            with self.subTest(ts=repr(bad_ts)):
                snap = Snapshot(data={"gameData": {}}, ts=bad_ts)
                self.assertEqual(snap.age_s, _UNKNOWN_AGE_S)

    def test_non_dict_body_yields_empty_snapshot(self):
        self.assertIsNone(_fetch_with(json.dumps([1, 2, 3])).data)

    def test_unparseable_body_yields_empty_snapshot(self):
        self.assertIsNone(_fetch_with("<html>502</html>").data)

    def test_error_envelope_yields_empty_snapshot(self):
        self.assertIsNone(_fetch_with(json.dumps({"error": "no game"})).data)


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    unittest.main()

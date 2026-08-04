"""Frame-staleness guard for modes/shared_vision._capture_screen (lane 8 cycle 7).

Sibling of the `core/liveclient_cache.Snapshot.age_s` defect fixed in the same
slice, found by the rule-5.3 sibling grep for the shared root cause: clamping a
FUTURE timestamp to zero age, so an envelope RC does not author reads as
perfectly fresh.

`_capture_screen` gates the vision frame on `_FRAME_HARD_AGE_S` (90s) so a
wedged relay cannot feed minutes-old game state into vision. The age was
computed as `max(0.0, time.time() - float(data.get("ts", 0)))`, so a frame
stamped in the future clamped to 0.0 and sailed through both the hard cap and
the `_FRAME_MAX_AGE_S` warning - the exact case the cap exists to stop.

Fail-closed contract: a frame whose age cannot be trusted is SKIPPED, not
served. A missing/zero `ts` already failed closed (age becomes time.time(),
far past the cap) and that behaviour is pinned here too.
"""
from __future__ import annotations

import json
import time
import unittest
from unittest import mock

import modes.shared_vision as sv


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._b = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._b

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *a: object) -> bool:
        return False


def _capture_with(payload: dict):
    sv._fail_streak = 0
    with mock.patch("urllib.request.urlopen",
                    lambda req, timeout=None: _FakeResp(payload)):
        return sv._capture_screen()


class TestFrameAgeFailsClosed(unittest.TestCase):
    def test_fresh_frame_is_served(self):
        self.assertEqual(_capture_with({"b64": "AAAA", "ts": time.time()}), "AAAA")

    def test_recent_frame_within_cap_is_served(self):
        payload = {"b64": "AAAA", "ts": time.time() - 10.0}
        self.assertEqual(_capture_with(payload), "AAAA")

    def test_frame_past_hard_cap_is_skipped(self):
        payload = {"b64": "AAAA", "ts": time.time() - (sv._FRAME_HARD_AGE_S + 30)}
        self.assertIsNone(_capture_with(payload))

    def test_future_stamped_frame_is_skipped_not_treated_as_fresh(self):
        """The defect: a future ts clamped to age 0.0 and defeated the cap."""
        payload = {"b64": "AAAA", "ts": time.time() + 3600}
        self.assertIsNone(_capture_with(payload))

    def test_small_future_skew_is_tolerated(self):
        """Sub-second jitter is not a wedged relay; do not drop good frames."""
        payload = {"b64": "AAAA", "ts": time.time() + 0.25}
        self.assertEqual(_capture_with(payload), "AAAA")

    def test_missing_ts_is_skipped(self):
        self.assertIsNone(_capture_with({"b64": "AAAA"}))

    def test_empty_payload_returns_none(self):
        self.assertIsNone(_capture_with({"b64": ""}))


if __name__ == "__main__":
    unittest.main()

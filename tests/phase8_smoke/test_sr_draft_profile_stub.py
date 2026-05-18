"""Phase 8 step 1 - queue gate + sr_draft state-builder flag + route shape.

Originally shipped as the P8-1 thin-slice tests against an empty-profiles
stub. P8-2 swapped the stub body for live engine /beam calls, so the
build_profile shape tests moved to test_sr_draft_profile_engine.py
(with urlopen mocked). What remains here:

  - `is_sr_draft_queue` matches {400, 420, 430, 440}, rejects others.
  - `dashboard._state_builder.build_state()` injects `sr_draft` into
    `lcu.champ_select` based on `queue_id`.
  - The HTTP route handler returns 200 with the locked envelope shape
    (engine mocked away so the test is fast + deterministic).

Avoids importing the dashboard HTTP server (no port binding in tests);
the route handler itself is exercised by a stubbed `_send` capture so
we don't need a live ThreadingHTTPServer.
"""
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from coaches import sr_draft_profile
from coaches.sr_draft_profile import (
    SR_DRAFT_QUEUE_IDS,
    clear_cache,
    is_sr_draft_queue,
)


class TestQueueGate(unittest.TestCase):
    def test_sr_queues_match(self):
        for qid in (400, 420, 430, 440):
            self.assertTrue(is_sr_draft_queue(qid), f"qid {qid} should match")

    def test_non_sr_queues_reject(self):
        # ARAM (450), Arena (1700), Clash (700), URF (900), TFT ranked (1100).
        for qid in (0, 450, 700, 900, 920, 1100, 1700, 1900):
            self.assertFalse(is_sr_draft_queue(qid), f"qid {qid} should NOT match")

    def test_none_and_garbage(self):
        self.assertFalse(is_sr_draft_queue(None))
        self.assertFalse(is_sr_draft_queue("garbage"))  # type: ignore[arg-type]
        self.assertFalse(is_sr_draft_queue([]))         # type: ignore[arg-type]

    def test_string_int_coerces(self):
        # Some downstream callers pass query-string ints; the gate copes.
        self.assertTrue(is_sr_draft_queue("420"))  # type: ignore[arg-type]

    def test_canonical_set_locked(self):
        self.assertEqual(SR_DRAFT_QUEUE_IDS, frozenset({400, 420, 430, 440}))


class TestStateBuilderFlag(unittest.TestCase):
    """`build_state()` should inject `sr_draft` into lcu.champ_select."""

    def _run_with(self, lcu_snapshot):
        from dashboard import _state_builder
        with mock.patch.object(_state_builder, "lcu_summary", return_value=lcu_snapshot), \
             mock.patch.object(_state_builder, "liveclient_summary", return_value={}), \
             mock.patch.object(_state_builder, "read_json", return_value={"alive": True, "pid": 1}):
            return _state_builder.build_state()

    def test_sr_draft_true_in_ranked_solo(self):
        snap = {"champ_select": {"queue_id": 420, "is_aram": False}}
        out = self._run_with(snap)
        self.assertTrue(out["lcu"]["champ_select"]["sr_draft"])

    def test_sr_draft_false_in_aram(self):
        snap = {"champ_select": {"queue_id": 450, "is_aram": True}}
        out = self._run_with(snap)
        self.assertFalse(out["lcu"]["champ_select"]["sr_draft"])

    def test_sr_draft_false_when_no_champ_select(self):
        # Lobby / not in queue - champ_select absent. Should not crash.
        snap = {}
        out = self._run_with(snap)
        self.assertNotIn("champ_select", out["lcu"])

    def test_sr_draft_false_with_missing_queue_id(self):
        snap = {"champ_select": {"is_aram": False}}  # queue_id absent
        out = self._run_with(snap)
        self.assertFalse(out["lcu"]["champ_select"]["sr_draft"])


class TestRouteHandler(unittest.TestCase):
    """Exercise routes_sr_draft._serve_sr_draft_profile_post via a fake handler.

    Engine is mocked away (URLError) so profiles=[] and the test only
    verifies the route layer's contract - type coercion, 400 path, and
    the locked envelope keys. Engine integration is covered separately
    in test_sr_draft_profile_engine.py."""

    def setUp(self):
        clear_cache()
        # Force engine path to fail so the route returns the empty-profiles
        # envelope deterministically.
        self._patcher = mock.patch.object(
            sr_draft_profile.urllib.request, "urlopen",
            side_effect=urllib.error.URLError("test: engine off"),
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def _handler(self):
        captured = {}
        class _H:
            def _send(self, code, body, ctype):
                captured["code"]  = code
                captured["body"]  = body
                captured["ctype"] = ctype
        return _H(), captured

    def test_happy_path(self):
        from dashboard.routes_sr_draft import _serve_sr_draft_profile_post
        h, captured = self._handler()
        _serve_sr_draft_profile_post(h, {
            "champion": "Tristana", "role": "BOTTOM", "queue_id": 420,
        })
        self.assertEqual(captured["code"], 200)
        body = json.loads(captured["body"])
        self.assertEqual(body["champion"], "Tristana")
        self.assertEqual(body["role"], "BOTTOM")
        self.assertTrue(body["sr_draft"])
        self.assertEqual(body["profiles"], [])  # engine mocked off
        # Locked envelope keys present.
        for k in ("champion", "role", "queue_id", "sr_draft", "engine_version", "profiles"):
            self.assertIn(k, body, f"missing key {k}")

    def test_missing_champion(self):
        from dashboard.routes_sr_draft import _serve_sr_draft_profile_post
        h, captured = self._handler()
        _serve_sr_draft_profile_post(h, {"queue_id": 420})
        self.assertEqual(captured["code"], 400)
        body = json.loads(captured["body"])
        self.assertIn("champion", body["error"])

    def test_garbage_types_dont_crash(self):
        from dashboard.routes_sr_draft import _serve_sr_draft_profile_post
        h, captured = self._handler()
        _serve_sr_draft_profile_post(h, {
            "champion":  "Yuumi",
            "role":      42,            # not a string → coerced to None
            "my_team":   "not a list",  # → None
            "queue_id":  "420",         # not an int → None (sr_draft False)
        })
        self.assertEqual(captured["code"], 200)
        body = json.loads(captured["body"])
        self.assertIsNone(body["role"])
        self.assertIsNone(body["queue_id"])
        self.assertFalse(body["sr_draft"])


if __name__ == "__main__":
    unittest.main()

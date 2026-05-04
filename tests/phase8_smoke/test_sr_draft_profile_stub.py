"""Phase 8 step 1 — SR draft profile stub + sr_draft flag derivation.

Verifies the thin slice that ships before the engine-backed generator
lands in P8-2:
  - `coaches.sr_draft_profile.build_profile()` returns the locked envelope.
  - `is_sr_draft_queue` matches {400, 420, 430, 440} and rejects ARAM/Arena.
  - `dashboard._state_builder.build_state()` injects `sr_draft` into
    `lcu.champ_select` based on `queue_id`.

Avoids importing the dashboard HTTP server (no port binding in tests);
the route handler itself is exercised by a stubbed `_send` capture so
we don't need a live ThreadingHTTPServer.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from coaches.sr_draft_profile import (
    SR_DRAFT_QUEUE_IDS,
    build_profile,
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


class TestBuildProfileStub(unittest.TestCase):
    def test_envelope_shape(self):
        out = build_profile(
            champion="Tristana",
            role="BOTTOM",
            my_team=[{"cellId": 0, "championId": 18}],
            their_team=[{"cellId": 5, "championId": 222}],
            queue_id=420,
        )
        self.assertEqual(out["champion"], "Tristana")
        self.assertEqual(out["role"], "BOTTOM")
        self.assertEqual(out["queue_id"], 420)
        self.assertTrue(out["sr_draft"])
        self.assertIsNone(out["engine_version"])
        self.assertEqual(out["profiles"], [])

    def test_minimal_args(self):
        out = build_profile(champion="Yuumi")
        self.assertEqual(out["champion"], "Yuumi")
        self.assertIsNone(out["role"])
        self.assertIsNone(out["queue_id"])
        self.assertFalse(out["sr_draft"])
        self.assertEqual(out["profiles"], [])

    def test_aram_queue_marks_not_sr_draft(self):
        out = build_profile(champion="Ziggs", queue_id=450)
        self.assertFalse(out["sr_draft"])


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
        # Lobby / not in queue — champ_select absent. Should not crash.
        snap = {}
        out = self._run_with(snap)
        self.assertNotIn("champ_select", out["lcu"])

    def test_sr_draft_false_with_missing_queue_id(self):
        snap = {"champ_select": {"is_aram": False}}  # queue_id absent
        out = self._run_with(snap)
        self.assertFalse(out["lcu"]["champ_select"]["sr_draft"])


class TestRouteHandler(unittest.TestCase):
    """Exercise routes_sr_draft._serve_sr_draft_profile_post via a fake handler."""

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
        self.assertTrue(body["sr_draft"])
        self.assertEqual(body["profiles"], [])

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

"""Phase 8 step 1 - queue gate + sr_draft state-builder flag.

Originally shipped as the P8-1 thin-slice tests against an empty-profiles
stub. P8-2 swapped the stub body for live engine /beam calls, so the
build_profile shape tests moved to test_sr_draft_profile_engine.py
(with urlopen mocked). What remains here:

  - `is_sr_draft_queue` matches {400, 420, 430, 440}, rejects others.
  - `dashboard._state_builder.build_state()` injects `sr_draft` into
    `lcu.champ_select` based on `queue_id`.

The HTTP route handler tests were removed in item 186 along with the
`/api/sr-draft/profile` route (0 live callers; engine still reachable
via `build_profile` direct import in test_sr_draft_profile_engine.py).
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from coaches.sr_draft_profile import (
    SR_DRAFT_QUEUE_IDS,
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



if __name__ == "__main__":
    unittest.main()

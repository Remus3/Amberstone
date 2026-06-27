"""Coach-tick duration instrumentation (base-attack slow-tick investigation).

The mode coaches show a long tick while the player attacks structures
(turret / inhibitor / nexus). This instruments the coaching dispatch + the
slow synchronous phases with a wall-clock timer, stamped with the live
structure/objective-event counts, so the spikes can be correlated to those
events post-game (data/coach_tick_trace.jsonl).

Built via __new__ on a concrete stub so the BaseCoach lifecycle (poll/vision
loops, AppLoop, SDK) is skipped; _run_coach is a no-op stub.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import coaches._base_coach as bc  # noqa: E402
from coaches._base_coach import BaseCoach  # noqa: E402


class _StubCoach(BaseCoach):
    _MODE_NAME = "test"
    _DATA_FILENAME = "test_coaching_data.json"

    def _blank_artifact_data(self) -> dict:
        return {}

    def _parse_raw_state(self, raw: dict) -> dict:
        return {}

    def _run_coach(self, state: dict) -> None:
        self._ran = state

    def _run_vision(self) -> None:
        pass


def _mk() -> "_StubCoach":
    c = _StubCoach.__new__(_StubCoach)
    c._MODE_NAME = "test"
    return c


_RAW = {
    "events": {"Events": [
        {"EventName": "TurretKilled"},
        {"EventName": "TurretKilled"},
        {"EventName": "TurretKilled"},
        {"EventName": "InhibKilled"},
        {"EventName": "ChampionKill"},
        {"EventName": "GameEnd"},
    ]}
}


class TestStructureEventCounts(unittest.TestCase):
    def test_counts_turret_inhib_nexus_total(self):
        out = _mk()._structure_event_counts(_RAW)
        self.assertEqual(out["turret"], 3)
        self.assertEqual(out["inhib"], 1)
        self.assertEqual(out["nexus"], 1)
        self.assertEqual(out["total"], 6)

    def test_empty_raw_is_safe(self):
        out = _mk()._structure_event_counts({})
        self.assertEqual(out, {"turret": 0, "inhib": 0, "nexus": 0, "total": 0})

    def test_malformed_events_skipped(self):
        out = _mk()._structure_event_counts(
            {"events": {"Events": [None, "x", {"EventName": "TurretKilled"}]}}
        )
        self.assertEqual(out["turret"], 1)
        self.assertEqual(out["total"], 3)


class TestDispatchCoachTrace(unittest.TestCase):
    def test_dispatch_runs_coach_and_traces(self):
        c = _mk()
        ran = {}
        c._run_coach = lambda st: ran.update(st)
        struct = {"turret": 3, "inhib": 1, "nexus": 0, "total": 9}
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(bc, "_APP_DIR", Path(td)):
                c._dispatch_coach({"game_time": "25:00"}, struct)
                trace = Path(td) / "data" / "coach_tick_trace.jsonl"
                self.assertTrue(trace.exists(), "trace file not written")
                rec = json.loads(trace.read_text(encoding="utf-8").strip())
        self.assertEqual(ran.get("game_time"), "25:00")  # _run_coach actually ran
        self.assertEqual(rec["mode"], "test")
        self.assertEqual(rec["phase"], "coach")
        self.assertEqual(rec["turret"], 3)
        self.assertEqual(rec["inhib"], 1)
        self.assertEqual(rec["game_time"], "25:00")
        self.assertIn("dur_ms", rec)
        self.assertIsInstance(rec["dur_ms"], (int, float))

    def test_trace_write_failure_never_raises(self):
        c = _mk()
        # Point _APP_DIR at a file so data/ cannot be created -> swallowed.
        with tempfile.NamedTemporaryFile(suffix=".lock") as tf:
            with mock.patch.object(bc, "_APP_DIR", Path(tf.name)):
                c._trace_coach_tick("coach", 12.3, {"turret": 1}, "10:00")


if __name__ == "__main__":
    unittest.main(verbosity=2)

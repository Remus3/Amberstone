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


class TestPollTickTrace(unittest.TestCase):
    """The two untimed synchronous stall suspects: the per-tick artifact I/O
    in _on_state_received, and the whole-poll-tick wall time. _maybe_coach is
    mocked to a no-op so the timing isolates parse + on_state (the Haiku call
    is offloaded to a worker thread and is intentionally NOT in the tick total).
    """

    def _poll_once(self, td: str, slow_ms: float = 0.0) -> list:
        c = _mk()
        c._last_state = {}
        c._fetch_game_data = lambda: _RAW
        c._parse_raw_state = lambda raw: {"game_time": "30:00"}
        c._on_state_received = lambda state: None
        c._maybe_coach = lambda state, prev: None  # isolate synchronous timing
        with mock.patch.object(bc, "_APP_DIR", Path(td)):
            with mock.patch.object(bc, "_SLOW_TICK_MS", slow_ms):
                c._poll_tick()
        trace = Path(td) / "data" / "coach_tick_trace.jsonl"
        if not trace.exists():
            return []
        return [
            json.loads(line)
            for line in trace.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_on_state_phase_traced(self):
        with tempfile.TemporaryDirectory() as td:
            rows = self._poll_once(td)
        phases = {r["phase"] for r in rows}
        self.assertIn("on_state", phases, f"no on_state row; phases={phases}")
        on = next(r for r in rows if r["phase"] == "on_state")
        self.assertEqual(on["mode"], "test")
        self.assertEqual(on["game_time"], "30:00")
        self.assertEqual(on["turret"], 3)   # stamped from _RAW struct counts
        self.assertEqual(on["inhib"], 1)
        self.assertEqual(on["n_events"], 6)
        self.assertIn("dur_ms", on)

    def test_whole_tick_phase_traced(self):
        with tempfile.TemporaryDirectory() as td:
            rows = self._poll_once(td)
        phases = {r["phase"] for r in rows}
        self.assertIn("tick", phases, f"no tick row; phases={phases}")
        tk = next(r for r in rows if r["phase"] == "tick")
        self.assertEqual(tk["game_time"], "30:00")
        self.assertEqual(tk["n_events"], 6)
        self.assertIn("dur_ms", tk)

    def test_fast_tick_emits_no_slow_rows(self):
        with tempfile.TemporaryDirectory() as td:
            rows = self._poll_once(td, slow_ms=1.0e9)
        self.assertEqual(rows, [], "a sub-threshold tick must write no rows")


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

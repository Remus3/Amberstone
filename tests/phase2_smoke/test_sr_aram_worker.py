"""
tests/phase2_smoke/test_sr_aram_worker.py
Smoke tests for core/sr_aram_worker.py worker contract.
No live Riot API, no Tk required.
"""
import queue
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.sr_aram_worker import SrAramWorker, WorkerResult
import core.feature_policy as fp


class FakeReader:
    """Stub GameReader that returns a canned state then None."""
    def __init__(self, states):
        self._states = list(states)
        self._idx = 0
    def read_game(self):
        if self._idx < len(self._states):
            s = self._states[self._idx]
            self._idx += 1
            return s
        return None
    def reset(self): pass


class FakeCoach:
    """Stub CoachIntegration that records submit_state calls."""
    def __init__(self):
        self.submitted = []
    def submit_state(self, state):
        self.submitted.append(state)
    def reset_state(self): pass


class TestSrAramWorkerContract(unittest.TestCase):

    def setUp(self):
        fp._reload()

    def tearDown(self):
        fp._reload()

    def _make_worker(self, states=None, coach=None):
        rq = queue.Queue(maxsize=8)
        w = SrAramWorker(result_queue=rq, coach=coach)
        if states is not None:
            w._reader = FakeReader(states)
        return w, rq

    def test_worker_starts_and_stops_cleanly(self):
        """Worker thread starts, runs, and stops without hanging."""
        w, rq = self._make_worker(states=[])
        w.start()
        self.assertTrue(w.is_alive())
        w.stop()
        w.join(timeout=3.0)
        self.assertFalse(w.is_alive())

    def test_worker_result_is_workerresult(self):
        """Emitted results are WorkerResult instances with correct fields."""
        from tests.fixtures.state_dicts import SR_STATE
        state = dict(SR_STATE, game_mode="CLASSIC")
        w, rq = self._make_worker(states=[state])
        w.start()
        # Wait up to 3s for one result
        result = None
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                result = rq.get_nowait()
                break
            except queue.Empty:
                time.sleep(0.05)
        w.stop(); w.join(timeout=2.0)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, WorkerResult)
        self.assertIsNotNone(result.state)
        self.assertFalse(result.end_signal)

    def test_worker_emits_end_signal_after_none_streak(self):
        """After NONE_STREAK_END Nones, an end_signal result is emitted."""
        import core.sr_aram_worker as _wmod
        from core.sr_aram_worker import NONE_STREAK_END
        from tests.fixtures.state_dicts import SR_STATE
        # Patch backoff to zero so the streak completes in < 1s
        orig_min = _wmod.BACKOFF_MIN_S
        orig_max = _wmod.BACKOFF_MAX_S
        _wmod.BACKOFF_MIN_S = 0.01
        _wmod.BACKOFF_MAX_S = 0.02
        try:
            state = dict(SR_STATE, game_mode="CLASSIC")
            states = [state] + [None] * (NONE_STREAK_END + 2)
            w, rq = self._make_worker(states=states)
            w.start()
            results = []
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    results.append(rq.get(timeout=0.1))
                except queue.Empty:
                    pass
                if any(r.end_signal for r in results):
                    break
            w.stop(); w.join(timeout=2.0)
        finally:
            _wmod.BACKOFF_MIN_S = orig_min
            _wmod.BACKOFF_MAX_S = orig_max
        end_signals = [r for r in results if r.end_signal]
        self.assertTrue(len(end_signals) >= 1, "Expected end_signal result")

    def test_worker_sr_coaching_gate_allow(self):
        """When policy allows, submit_state is called for CLASSIC mode."""
        fp._reload()  # all-allow
        from tests.fixtures.state_dicts import SR_STATE
        state = dict(SR_STATE, game_mode="CLASSIC")
        coach = FakeCoach()
        w, rq = self._make_worker(states=[state], coach=coach)
        w.start()
        time.sleep(0.3)
        w.stop(); w.join(timeout=2.0)
        # Coach should have been called at least once
        self.assertGreaterEqual(len(coach.submitted), 1)

    def test_worker_sr_coaching_gate_disabled(self):
        """When sr.live_coaching is disabled, submit_state is not called."""
        import tempfile, json
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "feature_flags.json"
            cfg.write_text(json.dumps({"sr": {"live_coaching": "disabled"}}))
            fp._reload(cfg)

            from tests.fixtures.state_dicts import SR_STATE
            state = dict(SR_STATE, game_mode="CLASSIC")
            coach = FakeCoach()
            w, rq = self._make_worker(states=[state], coach=coach)
            w.start()
            time.sleep(0.3)
            w.stop(); w.join(timeout=2.0)
        fp._reload()
        self.assertEqual(len(coach.submitted), 0,
                         "No coaching when sr.live_coaching=disabled")

    def test_no_tk_import_in_worker(self):
        """sr_aram_worker.py must not import tkinter."""
        _root = Path(__file__).parent.parent.parent
        src = (_root / "core" / "sr_aram_worker.py").read_text(encoding="utf-8")
        self.assertNotIn("import tkinter", src)
        self.assertNotIn("tk.Tk", src)

    def test_reset_reader_state_non_fatal(self):
        """reset_reader_state() is safe to call before reader is init'd."""
        w, _ = self._make_worker()
        w.reset_reader_state(reason="test")  # no _reader; must not raise

    def test_restart_increments_generation(self):
        w, _ = self._make_worker(states=[])
        w.start()
        gen_before = w._generation
        w.restart()
        self.assertGreater(w._generation, gen_before)
        w.stop(); w.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main()

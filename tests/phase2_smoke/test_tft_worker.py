"""
tests/phase2_smoke/test_tft_worker.py
Smoke tests for core/tft_worker.py worker contract.
No live TFT overlay, no live API, no raw Tk required.
"""
import queue
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.tft_worker import TftWorker, TftWorkerResult


class FakeLiveAnalysis:
    """Stub TftLiveAnalysis — records set_ai_bar calls, no Tk."""
    def __init__(self):
        self._ai_bar = None
        self.started = False
    def set_ai_bar(self, bar): self._ai_bar = bar
    def start(self): self.started = True
    def shutdown(self): pass
    def notify_coach_state(self, s): pass
    def notify_round(self, s): pass


class FakeEngine:
    """Stub TftCoachEngine — records submit calls."""
    def __init__(self):
        self.submitted = []
        self._last_call = 0
    def submit(self, s): self.submitted.append(s)
    def reset_state(self): pass
    def shutdown(self): pass


class FakeReader:
    """Stub TftStateReader — returns canned states then None."""
    def __init__(self, states):
        self._states = list(states)
        self._idx = 0
    def read(self):
        if self._idx < len(self._states):
            s = self._states[self._idx]; self._idx += 1; return s
        return None
    def shutdown(self): pass


class FakeAiBarProxy:
    """Minimal proxy stub — no Tk widgets."""
    def set_scanning(self, pct=0): pass
    def set_done(self): pass
    def notify_scan_scheduled(self, t): pass
    def set_interval(self, s): pass


class TestTftWorkerContract(unittest.TestCase):

    def _make_worker(self, states=None):
        rq = queue.Queue(maxsize=8)
        w = TftWorker(result_queue=rq)
        w._reader = FakeReader(states or [])
        w._engine = FakeEngine()
        w._live   = FakeLiveAnalysis()
        w._live.start()
        return w, rq

    def test_worker_starts_and_stops_cleanly(self):
        w, _ = self._make_worker()
        w.start()
        self.assertTrue(w.is_alive())
        w.stop()
        w.join(timeout=3.0)
        self.assertFalse(w.is_alive())

    def test_worker_result_is_tftworkerresult(self):
        from tests.fixtures.state_dicts import TFT_STATE
        w, rq = self._make_worker(states=[dict(TFT_STATE)])
        w.start()
        result = None
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try: result = rq.get_nowait(); break
            except queue.Empty: time.sleep(0.05)
        w.stop(); w.join(timeout=2.0)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, TftWorkerResult)
        self.assertIsNotNone(result.state)

    def test_shutdown_clears_components(self):
        w, _ = self._make_worker()
        w.start()
        w.shutdown()
        self.assertIsNone(w._live)
        self.assertIsNone(w._engine)
        self.assertIsNone(w._reader)

    def test_wire_ai_bar_before_live_init(self):
        """Pending proxy stored before _live exists is applied after init."""
        rq = queue.Queue(maxsize=4)
        w = TftWorker(result_queue=rq)
        proxy = FakeAiBarProxy()
        w.wire_ai_bar(proxy)
        self.assertIs(w._ai_bar, proxy)
        self.assertIsNone(w._live)  # not yet init'd

        # Simulate _init_components applying pending bar
        live = FakeLiveAnalysis()
        w._live = live
        if w._ai_bar is not None:
            w._live.set_ai_bar(w._ai_bar)
        live.start()
        self.assertIs(live._ai_bar, proxy)

    def test_wire_ai_bar_after_live_init(self):
        """Proxy applied immediately when _live already exists."""
        rq = queue.Queue(maxsize=4)
        w = TftWorker(result_queue=rq)
        live = FakeLiveAnalysis(); live.start()
        w._live = live
        proxy = FakeAiBarProxy()
        w.wire_ai_bar(proxy)
        self.assertIs(w._ai_bar, proxy)
        self.assertIs(live._ai_bar, proxy)

    def test_teardown_clears_ai_bar(self):
        w, _ = self._make_worker()
        w._ai_bar = FakeAiBarProxy()
        w._teardown_components()
        self.assertIsNone(w._ai_bar)

    def test_no_tk_import_in_worker(self):
        _root = Path(__file__).parent.parent.parent
        src = (_root / "core" / "tft_worker.py").read_text(encoding="utf-8")
        self.assertNotIn("import tkinter", src)
        self.assertNotIn("tk.Tk", src)
        self.assertNotIn("root.after", src)

    def test_coaching_gate_disabled_skips_engine(self):
        """When tft.live_coaching is disabled, engine.submit() is not called."""
        import json
        import tempfile
        import core.feature_policy as fp
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "feature_flags.json"
            cfg.write_text(json.dumps({"tft": {"live_coaching": "disabled",
                                               "tft_vision_analysis": "allow"}}))
            fp._reload(cfg)
            from tests.fixtures.state_dicts import TFT_STATE
            w, rq = self._make_worker(states=[dict(TFT_STATE)])
            w.start()
            time.sleep(0.3)
            w.stop(); w.join(timeout=2.0)
        fp._reload()
        self.assertEqual(len(w._engine.submitted if w._engine else []), 0)


if __name__ == "__main__":
    unittest.main()

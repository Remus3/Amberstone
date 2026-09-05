"""
RM-302 - both local-fallback model calls in tft/tft_live_analysis.py must
carry an explicit per-request timeout.

THE DEFECT. `_run_analysis` and `_run_augment_select` each fall back to a
DIRECT `self._client.messages.create(...)` against api.anthropic.com when
moon_proxy declines. Neither passed a `timeout`, so both inherited the SDK
default read timeout of 600 s (anthropic 0.96.0, DEFAULT_TIMEOUT read=600)
inside a loop that ticks every 1.5 s.

THE SYMPTOM IS SILENCE, NOT A THREAD STORM. `_run_cycle` opens with
`self._lock.acquire(blocking=False)` and returns immediately when the lock is
held, so ticks are DROPPED rather than queued. One hung request therefore
stops TFT coaching outright for up to ten minutes.

WHY THE EXISTING DEGRADED GUARD DOES NOT COVER THIS. Cycle 43 added
`_publish_degraded` on the FAILURE path, and
test_tft_live_analysis_lane8_cycle43.test_w5b already proves a RAISED error
publishes the marker. That test passes against the pre-fix module, because
it hands the fake client an exception object. A call that never returns never
raises, so it never reaches that handler at all - which is exactly why the
test below models the HANG rather than an exception. Handing this suite a
pre-built exception would have been vacuous.
"""
import json
import math
import sys
import threading
import types
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tft import tft_live_analysis as tla  # noqa: E402

# The SDK default this row exists to escape. Any bound at or above it is not
# a bound at all.
_SDK_DEFAULT_READ_TIMEOUT_S = 600.0

# Measured p99 of the nearest available population - see the derivation on
# tla._MODEL_TIMEOUT_S. A bound BELOW this would truncate healthy calls and
# trade a ten-minute silence for a permanently degraded panel.
_MEASURED_P99_S = 10.947

# How long a test is willing to wait for a cycle to come back. Real bounded
# calls in this suite raise immediately; this budget only has to be long
# enough that a slow machine is not mistaken for a hang.
_PATIENCE_S = 5.0

_GOOD_RAW = (
    "Comp: Vanguard Jinx\nBuild: Jinx\nBuy: hold gold\nSell: none\n"
    "Keep: Vi\nAugmentPlay: N/A\nLoss: N/A\n"
    "UnitPlacement: Jinx D7\nUnitSwap: none\n"
)

_GOOD_AUGMENT_RAW = "Take: Cybernetic Uplink\nWhy: fits Vanguard\nGameplan: roll at 7\n"

_VS = {
    "board_units": ["Jinx", "Vi"],
    "bench_units": ["Ekko"],
    "shop_units": ["Jinx"],
    "traits_active": ["Vanguard 2"],
    "augments": [],
    "level": 7,
    "hp": 80,
    "gold": 30,
    "augment_choices": [
        {"name": "Cybernetic Uplink", "description": "health and damage"},
        {"name": "Buried Treasures", "description": "loot"},
    ],
}


class _TextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResp:
    def __init__(self, content):
        self.content = content


def _timeout_error():
    """A real anthropic.APITimeoutError, which is what a bounded call raises."""
    import anthropic
    import httpx

    return anthropic.APITimeoutError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


class _HangingMessages:
    """An upstream that has stopped answering.

    Models the SDK's two real behaviours, and NOTHING else:

    * bounded  - a positive finite `timeout` below the SDK default means the
      SDK gives up and raises APITimeoutError. The wait itself is skipped:
      this suite asserts which BRANCH is taken, never how many seconds it
      took, so sleeping the real bound would only make the suite slow and
      clock-sensitive.
    * unbounded - no `timeout` means the SDK waits out its 600 s default,
      which for a loop that ticks every 1.5 s is indistinguishable from
      never returning. Modelled by blocking on an event the test never sets.

    `release()` unblocks any parked worker so a failing run does not leak a
    thread into the rest of the session.
    """

    def __init__(self):
        self.calls = []
        self._release = threading.Event()

    def create(self, **kw):
        self.calls.append(kw)
        t = kw.get("timeout")
        if isinstance(t, (int, float)) and not isinstance(t, bool) \
                and math.isfinite(t) and 0 < t < _SDK_DEFAULT_READ_TIMEOUT_S:
            raise _timeout_error()
        self._release.wait()
        raise AssertionError("unreachable: the hang was released by teardown")

    def release(self):
        self._release.set()


class _RecordingMessages:
    """Answers normally and keeps every kwarg it was called with."""

    def __init__(self, resp):
        self.calls = []
        self._resp = resp

    def create(self, **kw):
        self.calls.append(kw)
        return self._resp

    def release(self):
        pass


class _FakeClient:
    def __init__(self, messages):
        self.messages = messages


class _NoProxy:
    """Stand-in for core.moon_proxy.moon_proxy that always declines.

    Declining is what forces the LOCAL FALLBACK, which is the only path this
    row is about - the primary path is already bounded by
    core/moon_proxy.py TIMEOUT_S = 8.
    """

    @staticmethod
    def get_coaching(prompt, model=""):
        return None


def _mk(tmpdir, messages):
    """Construct TftLiveAnalysis with no network and a scripted model client."""
    obj = tla.TftLiveAnalysis.__new__(tla.TftLiveAnalysis)
    obj._client = _FakeClient(messages)
    obj._model = "claude-haiku-4-5-20251001"
    obj._data_file = Path(tmpdir) / "tft_live_data.json"
    obj._vision = None
    obj._lock = threading.Lock()
    obj._running = False
    obj._thread = None
    obj._last_round = (0, 0)
    obj._last_vision = 0.0
    obj._last_write = {}
    obj._coach_state = {"stage_round": "3-2", "level": 7}
    obj._vision_interval = 15.0
    obj._debug = False
    obj._known_augments = []
    obj._last_placement = ""
    obj._force_flag = False
    obj._round_start_time = 0.0
    obj._scanned_planning = False
    obj._scanned_mid = False
    obj._ai_bar = None
    return obj


class TftLiveAnalysisTimeoutTest(unittest.TestCase):

    def setUp(self):
        import tempfile

        self._td = tempfile.mkdtemp(prefix="rm302_")
        self.tmp = Path(self._td)
        self._parked = []
        # Force the local-fallback model path: the proxy declines.
        import core.moon_proxy as _mp

        self._real_proxy = _mp.moon_proxy
        _mp.moon_proxy = _NoProxy()
        # Neutralize the cost gate so neither entry point short-circuits.
        import core.cost_tracker as _ct

        self._real_gt = _ct.get_tracker
        _ct.get_tracker = lambda: types.SimpleNamespace(
            gate_disabled=lambda _m: False)

    def tearDown(self):
        import shutil

        import core.cost_tracker as _ct
        import core.moon_proxy as _mp

        for m in self._parked:
            m.release()
        for t in getattr(self, "_threads", []):
            t.join(timeout=_PATIENCE_S)
        _mp.moon_proxy = self._real_proxy
        _ct.get_tracker = self._real_gt
        shutil.rmtree(self._td, ignore_errors=True)

    def _run_bounded(self, fn, *args):
        """Run `fn` on a worker and report whether it came back in time."""
        done = threading.Event()

        def _target():
            try:
                fn(*args)
            finally:
                done.set()

        t = threading.Thread(target=_target, daemon=True)
        self._threads = getattr(self, "_threads", [])
        self._threads.append(t)
        t.start()
        return done.wait(timeout=_PATIENCE_S)

    def _read(self, obj):
        return json.loads(obj._data_file.read_text(encoding="utf-8"))

    # ---- the live defect --------------------------------------------------

    def test_rm302a_hung_analysis_call_returns_and_publishes_degraded(self):
        """A hung upstream must become a degraded panel, not ten minutes of
        silence.

        RED pre-fix for the right reason: with no `timeout` the call never
        comes back, so `_run_analysis` never reaches its handler and
        `_publish_degraded` is never called. The panel keeps showing the
        previous round's advice with nothing saying why.
        """
        msgs = _HangingMessages()
        self._parked.append(msgs)
        obj = _mk(self.tmp, msgs)

        came_back = self._run_bounded(obj._run_analysis, dict(_VS))

        self.assertTrue(
            came_back,
            "the fallback call never returned - it is unbounded, so the "
            "degraded marker is unreachable and the panel goes silent")
        self.assertTrue(obj._data_file.exists(),
                        "a timed-out cycle published nothing at all")
        data = self._read(obj)
        self.assertTrue(data.get("degraded"),
                        "a timed-out cycle did not set the degraded marker")
        self.assertEqual(data.get("degraded_message"), tla._DEGRADED_TEXT)
        # The panel must not leak SDK error text (CLAUDE.md Error Handling).
        self.assertNotIn("timed out", json.dumps(data).lower())

    def test_rm302b_hung_augment_select_call_returns(self):
        """The augment-select fallback is the second unbounded site.

        It has no degraded path of its own - it logs and returns - so the
        assertion here is only that it comes back at all. Both sites are
        driven from the same `_run_cycle`, so either one hanging silences
        the coach.
        """
        msgs = _HangingMessages()
        self._parked.append(msgs)
        obj = _mk(self.tmp, msgs)

        came_back = self._run_bounded(obj._run_augment_select, dict(_VS))

        self.assertTrue(
            came_back,
            "the augment-select fallback call never returned - it is "
            "unbounded")

    # ---- the argument itself ---------------------------------------------

    def test_rm302c_both_fallback_sites_pass_a_usable_timeout(self):
        """Pin the kwarg at BOTH sites.

        A bound that is absent, None, non-numeric, non-positive, infinite, or
        at/above the SDK's own 600 s default is not a bound. Asserted against
        the kwargs the module actually handed the SDK, not against source
        text.
        """
        for label, entry, resp in (
            ("_run_analysis", "_run_analysis", _FakeResp([_TextBlock(_GOOD_RAW)])),
            ("_run_augment_select", "_run_augment_select",
             _FakeResp([_TextBlock(_GOOD_AUGMENT_RAW)])),
        ):
            with self.subTest(site=label):
                msgs = _RecordingMessages(resp)
                obj = _mk(self.tmp, msgs)
                getattr(obj, entry)(dict(_VS))

                self.assertEqual(len(msgs.calls), 1,
                                 f"{label} did not reach the fallback once")
                kw = msgs.calls[0]
                self.assertIn("timeout", kw,
                              f"{label} passed no timeout, so it inherits the "
                              f"SDK default of {_SDK_DEFAULT_READ_TIMEOUT_S}s")
                t = kw["timeout"]
                self.assertIsInstance(t, (int, float))
                self.assertNotIsInstance(t, bool)
                self.assertTrue(math.isfinite(t),
                                f"{label} timeout is not a finite number")
                self.assertGreater(t, 0, f"{label} timeout is not positive")
                self.assertLess(
                    t, _SDK_DEFAULT_READ_TIMEOUT_S,
                    f"{label} timeout is no tighter than the SDK default")

    def test_rm302d_the_bound_stays_inside_the_measured_band(self):
        """Guard the VALUE, not just the presence of the kwarg.

        Derived in tla._MODEL_TIMEOUT_S from n=200 direct calls on this same
        model recorded in data/coach_trace.jsonl (p99 10947 ms). Tightening
        below that p99 would start cutting off healthy calls and leave the
        panel permanently degraded - trading one failure mode for a worse
        one. Loosening past 120 s stops bounding anything useful for a loop
        that ticks every 1.5 s.
        """
        t = tla._MODEL_TIMEOUT_S
        self.assertGreater(
            t, _MEASURED_P99_S,
            "the bound is tighter than the measured p99 - healthy calls "
            "would be cut off and published as degraded")
        self.assertLessEqual(
            t, 120.0,
            "the bound is too loose to fix the silence this row is about")


if __name__ == "__main__":
    unittest.main()

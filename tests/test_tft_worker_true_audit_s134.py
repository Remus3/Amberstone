"""Lane 8 (true-audit) session 134 cycle 6 - core/tft_worker.py.

Written before the fix and observed RED against the pre-fix worker, except
two characterization tests that pass on both sides by design
(test_w1_plain_stop_does_not_tear_components_down,
test_poll_interval_stays_at_line_44). The fakes stand in for TftStateReader / TftCoachEngine /
TftLiveAnalysis through sys.modules, so the REAL `_init_components` runs and
no TFT module, LCU, vision relay or model is reached.

  W1  shutdown() while `_init_components` is still running (its join timed
      out) left the vision loop STARTED and never shut down: it kept scanning
      and writing tft_live_data.json after the game had ended.
  W2  a read that returned after shutdown() still published a result.
  W3  a partial init failure kept the built reader, so a retry reported
      success without ever starting the vision loop.
  W4  a re-entrant / concurrent teardown shut a component down twice.
  W5  the worker had eight `except Exception: pass` sites; three went with
      the dead API (W6) and five now log (two policy checks, three teardown
      shutdowns). The debug-only read / submit / live-notify / LCU-set sites
      now go through _log_failure too: the first failure per site at
      WARNING, repeats at DEBUG.
  W6  wire_ai_bar() / force_scan() had no production caller (the facade's
      right-click went in cycle 5; TftAiStatusBar exists nowhere).
  W7  a forced scan (Ctrl+Tab or the dashboard button, both writing
      data/force_scan.json) did nothing in TFT: only coaches/_base_coach.py
      read that file and the TFT coach is not a BaseCoach.
"""
from __future__ import annotations

import logging
import queue
import sys
import threading
import time
import types

from core import tft_worker
from core.tft_worker import TftWorker

_LOGGER = "rc.tft_worker"


class _Live:
    def __init__(self, api_key="", data_file=None, start_exc=None, shutdown_hook=None):
        self.started = 0
        self.shutdowns = 0
        self._start_exc = start_exc
        self._shutdown_hook = shutdown_hook

    def start(self):
        if self._start_exc is not None:
            raise self._start_exc
        self.started += 1

    def shutdown(self):
        self.shutdowns += 1
        if self._shutdown_hook is not None:
            self._shutdown_hook()

    def notify_coach_state(self, state):
        pass

    def notify_round(self, state):
        pass


class _Engine:
    def __init__(self, data_file=None, debug=False):
        self.shutdowns = 0
        self.submitted = []

    def submit(self, state):
        self.submitted.append(state)

    def shutdown(self):
        self.shutdowns += 1


class _Reader:
    def __init__(self):
        self.shutdowns = 0

    def read(self):
        return None

    def shutdown(self):
        self.shutdowns += 1


class _Fakes:
    """Module-level fakes for the three lazy imports in _init_components."""

    def __init__(self, monkeypatch, reader_cls=_Reader, live_kwargs=None):
        self.readers, self.engines, self.lives = [], [], []
        fakes = self
        live_kwargs = dict(live_kwargs or {})

        def _reader():
            r = reader_cls()
            fakes.readers.append(r)
            return r

        def _engine(data_file, debug=False):
            e = _Engine(data_file, debug)
            fakes.engines.append(e)
            return e

        def _live(api_key="", data_file=None):
            lv = _Live(api_key, data_file, **live_kwargs)
            fakes.lives.append(lv)
            return lv

        for name, attr, factory in (
            ("tft.tft_state_reader", "TftStateReader", _reader),
            ("tft.tft_coach_engine", "TftCoachEngine", _engine),
            ("tft.tft_live_analysis", "TftLiveAnalysis", _live),
        ):
            mod = types.ModuleType(name)
            setattr(mod, attr, factory)
            monkeypatch.setitem(sys.modules, name, mod)
        policy = types.ModuleType("core.feature_policy")
        policy.is_allowed = lambda mode, feature: True
        policy.write_disabled_placeholder = lambda mode, feature: None
        monkeypatch.setitem(sys.modules, "core.feature_policy", policy)


def _worker(tmp_path):
    return TftWorker(result_queue=queue.Queue(maxsize=4), data_dir=tmp_path)


def _wait(pred, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


# -- W1: shutdown racing a slow init -----------------------------------------

def test_w1_shutdown_during_slow_init_never_leaves_vision_running(monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()

    class _SlowReader(_Reader):
        def __init__(self):
            super().__init__()
            entered.set()
            release.wait(5.0)

    fakes = _Fakes(monkeypatch, reader_cls=_SlowReader)
    w = _worker(tmp_path)
    w._shutdown_join_timeout_s = 0.05
    w.start()
    assert entered.wait(5.0)
    thread = w._thread
    w.shutdown()  # the join times out: init is still blocked
    release.set()
    thread.join(5.0)
    assert not thread.is_alive()
    assert len(fakes.lives) == 1
    live = fakes.lives[0]
    assert live.started == 0, "a vision loop was started for a finished game"
    assert fakes.readers[0].shutdowns == 1
    assert fakes.engines[0].shutdowns == 1
    assert (w._reader, w._engine, w._live) == (None, None, None)


def test_w1_shutdown_logs_a_thread_that_outlived_its_join(monkeypatch, tmp_path, caplog):
    entered, release = threading.Event(), threading.Event()

    class _SlowReader(_Reader):
        def __init__(self):
            super().__init__()
            entered.set()
            release.wait(5.0)

    _Fakes(monkeypatch, reader_cls=_SlowReader)
    w = _worker(tmp_path)
    w._shutdown_join_timeout_s = 0.05
    w.start()
    assert entered.wait(5.0)
    thread = w._thread
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        w.shutdown()
    release.set()
    thread.join(5.0)
    assert any("did not exit" in r.getMessage() for r in caplog.records
               if r.levelno >= logging.WARNING)


def test_w1_plain_stop_does_not_tear_components_down(monkeypatch, tmp_path):
    # restart() is stop() + start(): the new generation reuses the components,
    # so only shutdown() may tear down from the worker thread.
    _Fakes(monkeypatch)
    w = _worker(tmp_path)
    w.start()
    assert _wait(lambda: w._reader is not None and w._live is not None)
    w.stop()
    w.join(5.0)
    assert w._reader is not None and w._live is not None
    w.shutdown()
    assert (w._reader, w._engine, w._live) == (None, None, None)


def test_w1_shutdown_arriving_during_live_start_stops_the_loop_again(monkeypatch, tmp_path):
    # shutdown() can set its flag after init's pre-start check; the check
    # after start() catches it (its teardown may already have run).
    fakes = _Fakes(monkeypatch)
    w = _worker(tmp_path)

    def _start_then_shutdown_arrives(self=None):
        live = fakes.lives[0]
        live.started += 1
        w._shutdown_requested = True

    monkeypatch.setattr(_Live, "start", lambda self: _start_then_shutdown_arrives())
    w._init_components()
    assert fakes.lives[0].started == 1
    assert fakes.lives[0].shutdowns == 1


# -- W2: a read that returns after shutdown publishes nothing -----------------

def test_w2_read_returning_after_shutdown_publishes_nothing(tmp_path):
    w = _worker(tmp_path)
    w._shutdown_join_timeout_s = 0.05
    in_read, release = threading.Event(), threading.Event()

    class _BlockingReader(_Reader):
        def read(self):
            in_read.set()
            release.wait(5.0)
            return {"stage": 3, "round": 2, "hp": 60}

    w._reader, w._engine, w._live = _BlockingReader(), None, None
    w.start()
    assert in_read.wait(5.0)
    thread = w._thread
    w.shutdown()
    release.set()
    thread.join(5.0)
    assert w._result_queue.empty(), "a stopped worker published a stale board"


# -- W3: partial init failure is rolled back ---------------------------------

def test_w3_partial_init_failure_rolls_back_so_a_retry_rebuilds(monkeypatch, tmp_path):
    fakes = _Fakes(monkeypatch, live_kwargs={"start_exc": RuntimeError("boom")})
    w = _worker(tmp_path)
    assert w._init_components() is False
    assert (w._reader, w._engine, w._live) == (None, None, None)
    assert fakes.readers[0].shutdowns == 1
    assert fakes.engines[0].shutdowns == 1

    fakes2 = _Fakes(monkeypatch)
    assert w._init_components() is True
    assert fakes2.lives and fakes2.lives[0].started == 1
    w._teardown_components()


def test_w3_init_failure_is_logged_with_its_type(monkeypatch, tmp_path, caplog):
    _Fakes(monkeypatch, live_kwargs={"start_exc": RuntimeError("boom")})
    w = _worker(tmp_path)
    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        assert w._init_components() is False
    assert any("RuntimeError" in r.getMessage() for r in caplog.records)


# -- W4: teardown shuts each component down exactly once ---------------------

def test_w4_reentrant_teardown_shuts_each_component_once(tmp_path):
    w = _worker(tmp_path)
    live = _Live(shutdown_hook=lambda: w._teardown_components())
    engine, reader = _Engine(), _Reader()
    w._reader, w._engine, w._live = reader, engine, live
    w._teardown_components()
    assert (live.shutdowns, engine.shutdowns, reader.shutdowns) == (1, 1, 1)


# -- W5: no silent swallow ---------------------------------------------------

def test_w5_teardown_failure_is_logged_and_the_rest_still_torn_down(tmp_path, caplog):
    w = _worker(tmp_path)

    def _boom():
        raise RuntimeError("live shutdown failed")

    live, engine, reader = _Live(shutdown_hook=_boom), _Engine(), _Reader()
    w._reader, w._engine, w._live = reader, engine, live
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        w._teardown_components()
    assert (engine.shutdowns, reader.shutdowns) == (1, 1)
    assert any("live" in r.getMessage().lower() and r.levelno == logging.WARNING
               for r in caplog.records)


def test_w5_policy_failure_at_init_is_logged_and_vision_still_allowed(monkeypatch, tmp_path, caplog):
    fakes = _Fakes(monkeypatch)
    policy = sys.modules["core.feature_policy"]

    def _broken(mode, feature):
        raise OSError("flags file unreadable")

    policy.is_allowed = _broken
    w = _worker(tmp_path)
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert w._init_components() is True
    assert fakes.lives[0].started == 1
    assert any("policy" in r.getMessage().lower() for r in caplog.records
               if r.levelno == logging.WARNING)
    w._teardown_components()


def test_w5_repeated_read_error_warns_once_then_debug(tmp_path, caplog):
    w = _worker(tmp_path)
    calls = {"n": 0}

    class _BadReader(_Reader):
        def read(self):
            calls["n"] += 1
            if calls["n"] >= 3:
                w.stop()
            raise KeyError("stage")

    w._reader, w._engine, w._live = _BadReader(), None, None
    monkeypatch_wait = w._stop_event.wait
    w._stop_event.wait = lambda timeout=None: monkeypatch_wait(0)
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        w._run(w._generation)
    read_recs = [r for r in caplog.records if "read error" in r.getMessage()]
    assert calls["n"] == 3
    assert [r.levelno for r in read_recs] == [logging.WARNING, logging.DEBUG, logging.DEBUG]


def test_w5_engine_submit_error_warns_once(monkeypatch, tmp_path, caplog):
    _Fakes(monkeypatch)
    w = _worker(tmp_path)
    calls = {"n": 0}

    class _OneStateReader(_Reader):
        def read(self):
            calls["n"] += 1
            if calls["n"] >= 3:  # the third read lands after stop: not submitted
                w.stop()
            return {"stage": 2, "round": calls["n"]}

    class _BadEngine(_Engine):
        def submit(self, state):
            raise ValueError("bad state")

    w._reader, w._engine, w._live = _OneStateReader(), _BadEngine(), None
    orig_wait = w._stop_event.wait
    w._stop_event.wait = lambda timeout=None: orig_wait(0)
    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        w._run(w._generation)
    recs = [r for r in caplog.records if "submit" in r.getMessage().lower()]
    assert [r.levelno for r in recs] == [logging.WARNING, logging.DEBUG]


# -- W6: dead API removed ----------------------------------------------------

def test_w6_dead_ai_bar_and_force_scan_api_is_gone(tmp_path):
    w = _worker(tmp_path)
    assert not hasattr(TftWorker, "wire_ai_bar")
    assert not hasattr(TftWorker, "force_scan")
    assert not hasattr(w, "_ai_bar")


def test_poll_interval_stays_at_line_44():
    # core/tft_stage_gate.py cites core/tft_worker.py:44 for the cadence.
    import inspect
    lines = inspect.getsource(tft_worker).splitlines()
    assert lines[43].startswith("POLL_INTERVAL_S: float = 1.5")


def test_shutdown_flag_is_set_before_the_join(tmp_path):
    # The worker thread decides whether to tear down on exit from this flag,
    # so it must already be set when shutdown() starts waiting.
    w = _worker(tmp_path)
    seen = {}

    class _T:
        def join(self, timeout=None):
            seen["flag"] = w._shutdown_requested

        def is_alive(self):
            return False

    w._thread = _T()
    w.shutdown()
    assert seen["flag"] is True


# -- W7: data/force_scan.json reaches the TFT vision loop ---------------------

class _ScanLive(_Live):
    def __init__(self):
        super().__init__()
        self.forced = 0

    def force_scan(self):
        self.forced += 1


def _press(tmp_path, value):
    import json
    (tmp_path / "force_scan.json").write_text(json.dumps({"force": value}), encoding="utf-8")


def test_w7_a_press_after_worker_start_forces_one_scan(tmp_path):
    w = _worker(tmp_path)
    live = _ScanLive()
    w._live = live
    assert w._maybe_force_scan() is False  # no file yet
    _press(tmp_path, time.time() + 1.0)
    assert w._maybe_force_scan() is True
    assert w._maybe_force_scan() is False  # the same press is acted on once
    assert live.forced == 1


def test_w7_a_press_from_before_the_worker_is_ignored(tmp_path):
    _press(tmp_path, time.time() - 600.0)
    w = _worker(tmp_path)
    live = _ScanLive()
    w._live = live
    assert w._maybe_force_scan() is False
    assert live.forced == 0


def test_w7_malformed_press_file_never_raises(tmp_path):
    w = _worker(tmp_path)
    live = _ScanLive()
    w._live = live
    for body in ("{", "[]", '{"force": "soon"}', '{"force": null}', '{"force": NaN}'):
        (tmp_path / "force_scan.json").write_text(body, encoding="utf-8")
        assert w._maybe_force_scan() is False
    assert live.forced == 0


def test_w7_vision_disabled_ignores_a_press(tmp_path):
    w = _worker(tmp_path)
    _press(tmp_path, time.time() + 1.0)
    assert w._live is None
    assert w._maybe_force_scan() is False


def test_w7_the_poll_loop_forwards_a_press_in_game(tmp_path):
    w = _worker(tmp_path)
    live = _ScanLive()
    calls = {"n": 0}

    class _InGame(_Reader):
        def read(self):
            calls["n"] += 1
            if calls["n"] == 2:
                _press(tmp_path, time.time() + 1.0)
            if calls["n"] >= 3:
                w.stop()
            return {"stage": 2, "round": 1}

    w._reader, w._engine, w._live = _InGame(), None, live
    orig_wait = w._stop_event.wait
    w._stop_event.wait = lambda timeout=None: orig_wait(0)
    w._run(w._generation)
    assert live.forced == 1

"""
core/tft_worker.py
Phase 1 Step 5 - TFT runtime poll worker.

Owns TftStateReader, TftCoachEngine, and TftLiveAnalysis.  Runs the TFT
poll loop on a background thread and hands TftWorkerResult objects to
app.py via a thread-safe queue.  app.py applies the results to the
authoritative GameEnvelope (sole writer of _current_envelope).

Ownership boundaries:
  WORKER owns:
    - TftStateReader lifecycle
    - TftCoachEngine lifecycle and coaching submission
    - TftLiveAnalysis lifecycle and vision analysis
    - poll cadence (1.5 s interval)
    - generation-safety (supersession detection)
    - health / liveness pulse timestamps
  APP.PY owns:
    - GameEnvelope authority (sole writer of _current_envelope)
    - TftSnapshot runtime payload construction
    - derived compatibility surfaces (_game_state, legacy mode flags)
    - Tk / UI lifecycle
    - coaches/tft_coach.py facade (overlay attach/detach)
    - consuming TftWorkerResult from the result_queue

No Tk calls may appear in this module.  All GameEnvelope mutations happen
in app.py after consuming results from the queue.

Python 3.9 compatible: no X|Y unions, no walrus, no match.
"""
from __future__ import annotations

import logging
import queue
import time
from pathlib import Path
from typing import Any, Dict, Optional

from core.base_worker import BaseCoachWorker

_log = logging.getLogger("rc.tft_worker")

# Poll cadence (matches coaches/tft_coach.py historical interval)
POLL_INTERVAL_S: float = 1.5


# -- TftWorkerResult -----------------------------------------------------------

class TftWorkerResult:
    """
    Structured result from a single TFT poll iteration.

    Fields:
      state        - dict from TftStateReader.read(), or None
      end_signal   - True when the worker declares the game has ended
                     (state is None and was previously in-game)
      pulse_ts     - worker liveness timestamp (monotonic)
      last_success - monotonic timestamp of most recent successful read
    """
    __slots__ = ("state", "end_signal", "pulse_ts", "last_success")

    def __init__(
        self,
        state: Optional[Dict[str, Any]],
        end_signal: bool = False,
        pulse_ts: float = 0.0,
        last_success: float = 0.0,
    ) -> None:
        self.state        = state
        self.end_signal   = end_signal
        self.pulse_ts     = pulse_ts
        self.last_success = last_success


# -- TftWorker -----------------------------------------------------------------

class TftWorker(BaseCoachWorker):
    """
    Background worker for TFT runtime polling and coaching orchestration.

    Lifecycle:
      w = TftWorker(result_queue, data_dir=..., api_key=..., debug=False)
      w.start()           # launches background daemon thread
      ...                 # app drains result_queue via _drain_tft_q
      w.stop()            # signals stop; thread exits at next boundary
      w.join(timeout=3.0) # optional clean wait
      w.shutdown()        # full teardown including engine/live shutdown

    start() is NOT idempotent: always increments generation and spawns a
    new thread.  Old threads exit when my_gen != self._generation.
    restart() calls stop(), bounded join, then start().

    Thread safety:
      - result_queue is a thread-safe queue.Queue.
      - pulse_ts / last_success_ts are floats; GIL-atomic on CPython.
      - All other state is private, accessed only from the worker thread.

    No Tk calls in this module.
    """

    # AUDIT 2026-04-28 (proposal 1.4): lifecycle (start/stop/join/restart/
    # is_alive + pulse timestamps) lives on BaseCoachWorker. Subclass keeps
    # `shutdown()` for component teardown and the _run loop body only.
    _thread_name_prefix = "TftWorker"
    _restart_join_timeout_s = POLL_INTERVAL_S * 2

    def __init__(
        self,
        result_queue: "queue.Queue[TftWorkerResult]",
        data_dir: Optional[Path] = None,
        api_key: str = "",
        debug: bool = False,
    ) -> None:
        super().__init__()
        self._result_queue = result_queue
        self._data_dir     = data_dir or (Path(__file__).parent.parent / "data")
        self._api_key      = api_key
        self._debug        = debug

        # TFT runtime components - lazily initialised in _init_components()
        self._reader: Any = None   # TftStateReader
        self._engine: Any = None   # TftCoachEngine
        self._live:   Any = None   # TftLiveAnalysis

        # AI status bar reference - stored here so it survives the race between
        # wire_ai_bar() (called from Tk thread on overlay attach) and
        # _init_components() (called from worker thread on first poll).
        # Invariant: _ai_bar is always applied to _live whenever both exist.
        self._ai_bar: Any = None

    # -- Public lifecycle API (start/stop/join/restart/is_alive on base) --

    def shutdown(self) -> None:
        """
        Full teardown: stop the poll thread and shut down TFT components.
        Called by app.py on TFT game end.
        """
        self.stop()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self._teardown_components()

    # -- Internal -------------------------------------------------------------

    def _init_components(self) -> bool:
        """
        Lazily initialise TftStateReader, TftCoachEngine, TftLiveAnalysis.
        Returns True on success.  Idempotent - safe to call multiple times.
        """
        if self._reader is not None:
            return True
        try:
            from tft.tft_state_reader  import TftStateReader
            from tft.tft_coach_engine  import TftCoachEngine
            from tft.tft_live_analysis import TftLiveAnalysis

            tft_data_file = self._data_dir / "tft_coaching_data.json"
            live_data_file = self._data_dir / "tft_live_data.json"

            self._reader = TftStateReader()
            self._engine = TftCoachEngine(tft_data_file, debug=self._debug)
            self._live   = TftLiveAnalysis(
                api_key=self._api_key,
                data_file=live_data_file,
            )
            # Apply any pending AI bar reference stored before _live existed.
            # This closes the race between wire_ai_bar() (Tk thread, called on
            # overlay attach) and _init_components() (worker thread, called on
            # first poll).  If wire_ai_bar() ran first, _ai_bar is already set.
            if self._ai_bar is not None:
                try:
                    self._live.set_ai_bar(self._ai_bar)
                except Exception:
                    pass

            # Phase 1 Step 7: policy gate for tft_vision_analysis.
            # If disabled, skip starting the live-analysis loop.
            # TftStateReader still runs for non-vision runtime state.
            _vision_allowed = True
            try:
                from core.feature_policy import is_allowed, write_disabled_placeholder
                if not is_allowed("tft", "tft_vision_analysis"):
                    _vision_allowed = False
                    write_disabled_placeholder("tft", "tft_vision_analysis")
                    _log.info("TftWorker: tft_vision_analysis disabled by policy")
            except Exception:
                pass  # policy unavailable - allow

            if _vision_allowed:
                self._live.start()
            else:
                self._live = None  # don't hold reference when not started

            _log.info("TftWorker: TFT components initialised (vision=%s)", _vision_allowed)
            return True
        except Exception as exc:
            _log.error("TftWorker: component init failed: %s", exc)
            return False

    def _teardown_components(self) -> None:
        """Shut down TFT runtime components if they were initialised."""
        if self._live is not None:
            try:
                self._live.shutdown()
            except Exception:
                pass
            self._live = None
        self._ai_bar = None  # clear stored reference on teardown
        if self._engine is not None:
            try:
                self._engine.shutdown()
            except Exception:
                pass
            self._engine = None
        if self._reader is not None:
            try:
                self._reader.shutdown()
            except Exception:
                pass
            self._reader = None

    def wire_ai_bar(self, ai_bar: Any) -> None:
        """
        Wire a TftAiStatusBar into TftLiveAnalysis.

        Durable across startup order (Step 5.3):
          - Always stores the reference in self._ai_bar.
          - If _live already exists (worker initialised first), applies immediately.
          - If _live does not exist yet, the stored reference is applied by
            _init_components() when TftLiveAnalysis is created.
          - Safe to call multiple times (reattach) - always updates both the
            stored reference and the live object if present.

        Thread-safe: TftLiveAnalysis.set_ai_bar() is a simple object assignment
        guarded by the GIL on CPython.  No Tk calls are made here.
        """
        self._ai_bar = ai_bar
        if self._live is not None:
            try:
                self._live.set_ai_bar(ai_bar)
            except Exception:
                pass

    def force_scan(self) -> None:
        """Trigger an immediate vision scan (right-click force refresh)."""
        if self._live is not None:
            try:
                self._live.force_scan()
            except Exception:
                pass

    def _run(self, my_gen: int) -> None:
        """
        Worker main loop - background thread only.

        Polls TftStateReader every POLL_INTERVAL_S.  Forwards state to
        TftCoachEngine and TftLiveAnalysis.  Emits TftWorkerResult objects.
        Exits when stopped or superseded by a new generation.
        """
        if not self._init_components():
            _log.error("TftWorker gen=%d: component init failed - exiting", my_gen)
            return

        was_in_game  = False
        _last_sr     = (0, 0)

        while not self._stop_event.is_set():
            # -- Pre-read generation check ----------------------------------
            if my_gen != self._generation:
                _log.debug("TftWorker gen=%d superseded - exiting", my_gen)
                return

            self.pulse_ts = time.monotonic()

            try:
                state = self._reader.read()

                # -- Post-read generation check -----------------------------
                if my_gen != self._generation:
                    _log.debug("TftWorker gen=%d superseded post-read", my_gen)
                    return

                if state:
                    self.last_success_ts = time.monotonic()
                    was_in_game = True

                    # -- Coaching orchestration -----------------------------
                    # Submit to TftCoachEngine (text coaching)
                    # Phase 1 Step 7: gated by feature_policy tft.live_coaching.
                    if self._engine is not None:
                        _submit_ok = True
                        try:
                            from core.feature_policy import is_allowed as _fp_ok, write_disabled_placeholder as _fp_wr
                            if not _fp_ok("tft", "live_coaching"):
                                _fp_wr("tft", "live_coaching")
                                _submit_ok = False
                        except Exception:
                            pass
                        if _submit_ok:
                            try:
                                self._engine.submit(state)
                            except Exception:
                                _log.debug("TftWorker: engine submit error", exc_info=True)

                    # Notify TftLiveAnalysis of round transitions
                    if self._live is not None:
                        try:
                            self._live.notify_coach_state(state)
                            sr = (state.get("stage", 0), state.get("round", 0))
                            if sr != _last_sr:
                                _last_sr = sr
                                self._live.notify_round(state)
                        except Exception:
                            _log.debug("TftWorker: live notify error", exc_info=True)

                    self._enqueue(TftWorkerResult(
                        state=state,
                        pulse_ts=self.pulse_ts,
                        last_success=self.last_success_ts,
                    ))

                else:
                    if was_in_game:
                        # Still poll; game end is declared by app.py via SrAramWorker
                        # end_signal or via absence of TFT mode - not by this worker.
                        # Emit None result so app.py can observe the gap.
                        self._enqueue(TftWorkerResult(
                            state=None,
                            pulse_ts=self.pulse_ts,
                            last_success=self.last_success_ts,
                        ))

            except Exception:
                _log.debug("TftWorker: read error", exc_info=True)

            self._stop_event.wait(POLL_INTERVAL_S)

        _log.info("TftWorker gen=%d exited cleanly", my_gen)

    def _enqueue(self, result: TftWorkerResult) -> None:
        """Drop oldest if full, then enqueue."""
        try:
            self._result_queue.put_nowait(result)
        except queue.Full:
            try:    self._result_queue.get_nowait()
            except queue.Empty: pass
            try:    self._result_queue.put_nowait(result)
            except queue.Full: pass

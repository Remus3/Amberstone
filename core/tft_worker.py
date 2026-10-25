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
from typing import Any, Callable, Dict, Optional

from core.base_worker import BaseCoachWorker

_log = logging.getLogger("rc.tft_worker")

# Poll cadence (matches coaches/tft_coach.py historical interval)
POLL_INTERVAL_S: float = 1.5

# S134: how often the poll loop re-notes the running set from the LCU
# (tft/tft_set.py read_lcu_set_facts). Must stay below tft_set.LIVE_TTL_S
# (180 s) or the noted set lapses between refreshes.
LCU_SET_REFRESH_S: float = 60.0


def make_lcu_request() -> Callable:
    """An LCU ``request(method, path, body=None) -> (payload, None)`` over a
    worker-owned, lazily built ``LcuClient`` (the frozen client is only READ,
    as dashboard/_lcu_inprocess.py does). Nothing connects until the first
    call; each call connects when not yet connected, else re-checks the
    lockfile so a League restart is followed. A None payload means no data.

    For the TFT game-start site that builds the worker:
    ``TftWorker(..., lcu_request=make_lcu_request())``.
    """
    holder: Dict[str, Any] = {}

    def _request(method, path, body=None):
        client = holder.get("client")
        if client is None:
            from lcu.lcu_client import LcuClient
            client = holder["client"] = LcuClient()
        if not client._port:
            client.connect()
        else:
            client._refresh_conn_if_changed()
        return client._request(method, path, data=body), None

    return _request


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
      - The three components are built on the worker thread and torn down
        by shutdown() on the caller's thread, so that can overlap a worker
        thread that outlived its join (an LCU call or a slow init).
        _teardown_components() detaches each one BEFORE shutting it down,
        so two teardowns never shut one component down twice, and an init
        that is still running when shutdown() arrives tears down what it
        built instead of starting the vision loop (lane 8 s134, W1/W4).

    No Tk calls in this module.
    """

    # AUDIT 2026-04-28 (proposal 1.4): lifecycle (start/stop/join/restart/
    # is_alive + pulse timestamps) lives on BaseCoachWorker. Subclass keeps
    # `shutdown()` for component teardown and the _run loop body only.
    _thread_name_prefix = "TftWorker"
    _restart_join_timeout_s = POLL_INTERVAL_S * 2
    # shutdown()'s bounded wait for the poll thread (see shutdown()).
    _shutdown_join_timeout_s: float = 3.0

    def __init__(
        self,
        result_queue: "queue.Queue[TftWorkerResult]",
        data_dir: Optional[Path] = None,
        api_key: str = "",
        debug: bool = False,
        lcu_request: Optional[Callable] = None,
    ) -> None:
        super().__init__()
        self._result_queue = result_queue
        self._data_dir     = data_dir or (Path(__file__).parent.parent / "data")
        self._api_key      = api_key
        self._debug        = debug

        # S134: LCU source of the running TFT set (make_lcu_request). None =
        # the queue id from the relayed LCU agent snapshot only (no
        # mDefaultSet; see _maybe_note_lcu_set).
        self._lcu_request     = lcu_request
        self._lcu_default_set: Optional[str] = None
        self._lcu_set_at: Optional[float] = None
        self._lcu_clock       = time.monotonic

        # TFT runtime components - lazily initialised in _init_components()
        self._reader: Any = None   # TftStateReader
        self._engine: Any = None   # TftCoachEngine
        self._live:   Any = None   # TftLiveAnalysis

        # Set by shutdown() BEFORE it stops and joins the poll thread. An
        # init still in progress reads it and tears down instead of starting
        # the vision loop; plain stop() (restart) leaves the components alone.
        self._shutdown_requested = False
        # Failure sites already logged at WARNING (see _log_failure).
        self._failed_sites: set = set()
        # Newest data/force_scan.json press acted on (wall clock, the
        # writers' own time.time()). Starts at construction so a press left
        # over from an earlier game never fires a paid scan at game start.
        self._force_seen: float = time.time()

        # wire_ai_bar(), force_scan() and the stored _ai_bar were removed in
        # the lane 8 s134 audit: no production caller (TftAiStatusBar is
        # defined nowhere; the facade's right-click went in cycle 5). Forced
        # scans now arrive through data/force_scan.json (_maybe_force_scan).

    # -- Public lifecycle API (start/stop/join/restart/is_alive on base) --

    def shutdown(self) -> None:
        """
        Full teardown: stop the poll thread and shut down TFT components.
        Called by app.py on TFT game end.

        The join is bounded. A poll thread still inside an LCU call, a
        Live Client read or a slow first init when it expires keeps
        running; the components are torn down here anyway. The flag is set
        first: an init still in progress sees it and tears down what it
        built instead of starting the vision loop (_init_components), and a
        read that returns late publishes nothing (_run), so no vision loop
        and no board outlive the game.
        """
        self._shutdown_requested = True
        self.stop()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self._shutdown_join_timeout_s)
            if thread.is_alive():
                _log.warning(
                    "TftWorker: poll thread did not exit within %.1fs of "
                    "shutdown; it publishes nothing more",
                    self._shutdown_join_timeout_s,
                )
        self._teardown_components()

    # -- Internal -------------------------------------------------------------

    def _log_failure(self, site: str, what: str) -> None:
        """Log the exception being handled: the first at each site at WARNING
        with its traceback, repeats at DEBUG. One worker lives for one game,
        so a failure that repeats every 1.5 s tick costs one WARNING per game
        instead of being invisible at the default level."""
        level = logging.DEBUG if site in self._failed_sites else logging.WARNING
        self._failed_sites.add(site)
        _log.log(level, "TftWorker: %s", what, exc_info=True)

    def _init_components(self) -> bool:
        """
        Lazily initialise TftStateReader, TftCoachEngine, TftLiveAnalysis.
        Returns True on success.  Idempotent - safe to call multiple times.

        All or nothing: a failure part-way tears down what was built, so a
        retry rebuilds every component instead of finding `_reader` set and
        reporting success with the vision loop never started. Returns False
        without starting the vision loop when shutdown() has been requested.
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
            except Exception:  # noqa: BLE001
                self._log_failure(
                    "vision_policy",
                    "tft_vision_analysis policy check failed - vision allowed")

            if self._shutdown_requested:
                # shutdown() arrived while this was building (its join timed
                # out): never start a vision loop for a finished game.
                self._teardown_components()
                return False

            live = self._live
            if _vision_allowed and live is not None:
                live.start()
                if self._shutdown_requested:
                    # shutdown() set the flag before tearing down, so a
                    # teardown that shut `live` down before this start() is
                    # caught here and the loop is stopped again.
                    live.shutdown()
            else:
                self._live = None  # don't hold reference when not started

            _log.info("TftWorker: TFT components initialised (vision=%s)", _vision_allowed)
            return True
        except Exception as exc:  # noqa: BLE001
            _log.error("TftWorker: component init failed: %s: %s",
                       type(exc).__name__, exc)
            self._teardown_components()
            return False

    def _teardown_components(self) -> None:
        """Shut down TFT runtime components if they were initialised.

        Each component is detached BEFORE its shutdown() runs, so a second
        teardown (the caller's and the exiting poll thread's can overlap, or
        a shutdown hook can re-enter) finds None and never shuts one down
        twice. A failing shutdown is logged and the rest still run.
        """
        for attr, name in (("_live", "TftLiveAnalysis"),
                           ("_engine", "TftCoachEngine"),
                           ("_reader", "TftStateReader")):
            component = getattr(self, attr)
            setattr(self, attr, None)
            if component is None:
                continue
            try:
                component.shutdown()
            except Exception:  # noqa: BLE001
                _log.warning("TftWorker: %s shutdown failed", name, exc_info=True)

    def _maybe_note_lcu_set(self) -> Optional[int]:
        """Note the running set from the LCU (mDefaultSet + queue id) at most
        once per LCU_SET_REFRESH_S; returns the set noted, else None.

        With an lcu_request: tftsets.json is read once per worker (the default
        set does not change within a game), the queue id every refresh.
        Without one: the queue id from the LCU agent snapshot the vision relay
        already carries (tft/tft_standalone.py relay_lcu_snapshot); it has no
        mDefaultSet, so only a queue that names its own set (QUEUE_SETS, the
        Set 17 revival) is noted and a normal queue keeps resolve_set's
        default - and clears a set an earlier (revival) game noted, so it
        cannot ride into this game for LIVE_TTL_S. Never raises.
        """
        try:
            now = getattr(self, "_lcu_clock", time.monotonic)()
            last = getattr(self, "_lcu_set_at", None)
            if last is not None and now - last < LCU_SET_REFRESH_S:
                return None
            self._lcu_set_at = now
            from tft import tft_set
            request = getattr(self, "_lcu_request", None)
            default_set = getattr(self, "_lcu_default_set", None)
            if request is not None:
                default_set, queue_id = tft_set.read_lcu_set_facts(request, default_set)
            else:
                from tft import tft_standalone
                queue_id = tft_set.snapshot_tft_queue_id(
                    tft_standalone.relay_lcu_snapshot())
            if default_set:
                self._lcu_default_set = default_set
            if queue_id is None:
                return None
            noted = tft_set.note_live_set_from_lcu(default_set, queue_id)
            if noted is None:
                tft_set.clear_live_set()  # a TFT queue that names no set
            return noted
        except Exception:  # noqa: BLE001
            self._log_failure("lcu_set", "LCU set read failed")
            return None

    def _maybe_force_scan(self) -> bool:
        """Run a forced vision scan when data/force_scan.json carries a press
        newer than the last one acted on; returns True when one fired.

        Ctrl+Tab (core/hotkeys.py _trigger_force_scan) and the dashboard
        button (dashboard/_writers.py force_vision_scan) both write
        {"force": time.time()}. Before the lane 8 s134 audit only
        coaches/_base_coach.py read that file, and the TFT coach is not a
        BaseCoach, so a forced scan did nothing in TFT. A missing or
        unreadable file means no press this tick.
        """
        live = self._live
        if live is None:
            return False
        import json  # lazy: an import line above would move POLL_INTERVAL_S off line 44
        try:
            doc = json.loads((self._data_dir / "force_scan.json").read_text(encoding="utf-8"))
            pressed = float(doc.get("force", 0))
        except FileNotFoundError:
            return False
        except (OSError, ValueError, AttributeError, TypeError):
            _log.debug("TftWorker: force_scan.json unreadable", exc_info=True)
            return False
        if not pressed > self._force_seen:  # also rejects NaN
            return False
        self._force_seen = pressed
        try:
            live.force_scan()
        except Exception:  # noqa: BLE001
            self._log_failure("force_scan", "forced scan failed")
            return False
        return True

    def _run(self, my_gen: int) -> None:
        """
        Worker main loop - background thread only.

        Polls TftStateReader every POLL_INTERVAL_S.  Forwards state to
        TftCoachEngine and TftLiveAnalysis.  Emits TftWorkerResult objects.
        Exits when stopped or superseded by a new generation.
        """
        if not self._init_components():
            if self._shutdown_requested:
                _log.info("TftWorker gen=%d: shut down during init", my_gen)
            else:
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

            # S134: keep the running set noted (it routes the round schedule,
            # roll odds and XP table); throttled, never raises.
            self._maybe_note_lcu_set()

            reader = self._reader
            if reader is None:  # torn down by shutdown() mid-iteration
                return
            try:
                state = reader.read()

                # -- Post-read generation / stop check -----------------------
                # A read that returns after shutdown() (its join may have
                # timed out) must not publish the finished game's board.
                if my_gen != self._generation or self._stop_event.is_set():
                    _log.debug("TftWorker gen=%d superseded or stopped post-read", my_gen)
                    return

                if state:
                    self.last_success_ts = time.monotonic()
                    was_in_game = True

                    # -- Coaching orchestration -----------------------------
                    # Submit to TftCoachEngine (text coaching)
                    # Phase 1 Step 7: gated by feature_policy tft.live_coaching.
                    engine = self._engine
                    if engine is not None:
                        _submit_ok = True
                        try:
                            from core.feature_policy import is_allowed as _fp_ok, write_disabled_placeholder as _fp_wr
                            if not _fp_ok("tft", "live_coaching"):
                                _fp_wr("tft", "live_coaching")
                                _submit_ok = False
                        except Exception:  # noqa: BLE001
                            self._log_failure(
                                "coaching_policy",
                                "live_coaching policy check failed - submitting")
                        if _submit_ok:
                            try:
                                engine.submit(state)
                            except Exception:  # noqa: BLE001
                                self._log_failure("submit", "engine submit error")

                    # Notify TftLiveAnalysis of round transitions
                    live = self._live
                    if live is not None:
                        try:
                            live.notify_coach_state(state)
                            sr = (state.get("stage", 0), state.get("round", 0))
                            if sr != _last_sr:
                                _last_sr = sr
                                live.notify_round(state)
                        except Exception:  # noqa: BLE001
                            self._log_failure("live_notify", "live notify error")
                        self._maybe_force_scan()

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

            except Exception:  # noqa: BLE001
                self._log_failure("read", "read error")

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

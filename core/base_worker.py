"""
core/base_worker.py - shared lifecycle for SR/ARAM and TFT poll workers.

AUDIT 2026-04-28 (proposal 1.4): SrAramWorker and TftWorker independently
re-implement the same start/stop/restart/join/is_alive shape plus pulse
timestamps. Pulling that into one base homogenises lifecycle calls from
app.py, makes HealthMonitor's view consistent across mode workers, and
removes a recurring source of subtle drift between the two.

The base class is intentionally minimal: it owns thread spawn/teardown,
generation counters, stop event, and pulse timestamps. Subclasses
implement `_run(my_gen)` (the long-running poll loop) and may override
`shutdown()` for component teardown after stop+join.

Compatibility note: existing call sites use `start`, `stop`, `restart`,
`join`, `is_alive`, `pulse_ts`, `last_success_ts`. The base preserves
all of these. TftWorker adds `shutdown()` - kept on the subclass.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional

_log = logging.getLogger("rc.base_worker")

# A pulse read fractionally before ours can never be ahead of ours by more than
# scheduling noise, so anything further in the "future" than this did not come
# from this process's monotonic clock.
_PULSE_FUTURE_SLACK_S: float = 1.0


def _sanitise_pulse(value: Any) -> float:
    """Coerce a pulse timestamp, degrading anything not from `time.monotonic()`
    to 0.0 - which every consumer already reads as "never pulsed".

    RM-357: this class's contract used to instruct `time.time()` while
    HealthMonitor differences pulse_ts against `time.monotonic()`. A subclass
    written to that contract produced a worker_age near -1.7e9, which passes
    the `worker_age < 12.0` liveness gate forever - a dead worker reported
    alive, the exact inversion of what the pulse exists to detect. Failing to
    0.0 inverts that the safe way: a wrongly-clocked worker reads NOT alive.
    """
    try:
        stamp = float(value)
    except (TypeError, ValueError):
        stamp = math.nan
    if not math.isfinite(stamp) or stamp < 0.0:
        _log.warning("discarding non-monotonic pulse timestamp %r", value)
        return 0.0
    if stamp > time.monotonic() + _PULSE_FUTURE_SLACK_S:
        _log.warning(
            "discarding pulse timestamp %r - not from time.monotonic() "
            "(wall-clock epoch?); see RM-357",
            value,
        )
        return 0.0
    return stamp


class BaseCoachWorker:
    """Lifecycle base for poll-based coach workers.

    Subclass contract:
      * implement `_run(self, my_gen: int) -> None` - the poll loop. Read
        `self._stop_event.is_set()` to exit cleanly. Set
        `self.pulse_ts = time.monotonic()` on each iteration so HealthMonitor
        sees liveness; set `self.last_success_ts = time.monotonic()` on a
        successful read. Both are MONOTONIC, not wall-clock: HealthMonitor
        differences pulse_ts against `time.monotonic()`, so a wall-clock
        stamp would make the age negative and pin the liveness gate open
        (RM-357). A stamp that cannot have come from that clock is discarded
        and read as "never pulsed".
      * generation safety: receive `my_gen` and exit when
        `my_gen != self._generation` (a newer start() has superseded you).
    """

    # Subclasses can override for a clearer thread name in logs.
    _thread_name_prefix: str = "CoachWorker"
    # join() default timeout when restart()ing.
    _restart_join_timeout_s: float = 3.0

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        # Serialises start(): the generation bump, its re-read and the
        # self._thread swap are one step, so two starters (restart() included,
        # which ends in start()) can never share a generation (s144 true-audit
        # F2). Never held across restart()'s join, so a slow join cannot block
        # another start().
        self._lifecycle_lock = threading.Lock()
        self._generation: int = 0
        self._thread: Optional[threading.Thread] = None
        # Single-slot float writes stay GIL-atomic on CPython - no lock needed.
        # pulse_ts and last_success_ts go through properties (see below) whose
        # setters are still a single store, so a reader cannot observe a torn
        # value.
        self._pulse_ts: float = 0.0
        self._last_success_ts: float = 0.0
        # RM-198: lifecycle failures that used to be invisible. A restart()
        # whose bounded join timed out leaves the old thread running; it is
        # kept here (gen -> thread) until it finally exits, and reported by
        # health_pulse(). _run_safe records crashes into the three fields.
        self._stranded: Dict[int, threading.Thread] = {}
        self.crash_count: int = 0
        self.last_error: Optional[str] = None
        self.died_ts: float = 0.0

    @property
    def pulse_ts(self) -> float:
        """Monotonic liveness stamp, read by HealthMonitor."""
        return self._pulse_ts

    @pulse_ts.setter
    def pulse_ts(self, value: Any) -> None:
        self._pulse_ts = _sanitise_pulse(value)

    @property
    def last_success_ts(self) -> float:
        """Monotonic stamp of the last successful read (same clock contract
        as pulse_ts; the RM-357 guard used to cover pulse_ts only)."""
        return self._last_success_ts

    @last_success_ts.setter
    def last_success_ts(self, value: Any) -> None:
        self._last_success_ts = _sanitise_pulse(value)

    # -- Public lifecycle --------------------------------------------------

    def start(self) -> None:
        """Spawn a fresh worker thread. Always increments generation; an
        already-running thread is left to exit on its own via the
        generation mismatch check inside `_run`, and is reported by
        stranded_generations() until it does (a wedged one would otherwise be
        invisible once self._thread is rebound - the RM-198 class)."""
        with self._lifecycle_lock:
            prev, prev_gen = self._thread, self._generation
            if prev is not None and prev.is_alive():
                self._stranded[prev_gen] = prev
            self._stop_event.clear()
            gen = self._generation + 1
            self._generation = gen
            self._thread = threading.Thread(
                target=self._run_safe,
                args=(gen,),
                name=f"{self._thread_name_prefix}-{gen}",
                daemon=True,
            )
            self._thread.start()
        _log.info("%s gen=%d started", self._thread_name_prefix, gen)

    def stop(self) -> None:
        """Signal the worker to exit at the next iteration boundary."""
        self._stop_event.set()
        _log.info("%s stop signalled", self._thread_name_prefix)

    def join(self, timeout: float = 3.0) -> None:
        """Wait for the worker thread (optional - daemon threads exit with proc)."""
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def restart(self) -> None:
        """stop() + bounded join + start() with a fresh generation.

        Safe to call from inside the worker's own thread: that thread cannot
        join itself, so the join is skipped and it exits on the generation
        mismatch once its _run returns."""
        self.stop()
        old = self._thread
        old_gen = self._generation
        if old is not None and old is not threading.current_thread():
            old.join(timeout=self._restart_join_timeout_s)
            # Thread.join returns None either way; is_alive() is the only
            # truth. restart() exists for a wedged worker, which is exactly
            # when this join times out (RM-198). start() records the
            # still-running generation as stranded.
            if old.is_alive():
                _log.warning(
                    "%s gen=%d did not exit within %.1fs of restart; "
                    "left running (stranded)",
                    self._thread_name_prefix, old_gen,
                    self._restart_join_timeout_s,
                )
        self.start()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- HealthMonitor-facing pulse view ----------------------------------

    def health_pulse(self) -> Dict[str, Any]:
        """A consistent shape for HealthMonitor consumption across mode
        workers. Pure read of GIL-atomic floats + thread liveness."""
        return {
            "alive":            self.is_alive(),
            "generation":       self._generation,
            "pulse_ts":         self.pulse_ts,
            "last_success_ts":  self.last_success_ts,
            "stranded_generations": self.stranded_generations(),
            "crash_count":      self.crash_count,
            "last_error":       self.last_error,
            "died_ts":          self.died_ts,
        }

    def stranded_generations(self) -> List[int]:
        """Generations a restart() left running, pruned once they exit."""
        for gen, thread in list(self._stranded.items()):
            if not thread.is_alive():
                self._stranded.pop(gen, None)
        return sorted(self._stranded)

    # -- Subclass hook ----------------------------------------------------

    def _run(self, my_gen: int) -> None:  # pragma: no cover - abstract
        raise NotImplementedError("BaseCoachWorker subclasses must implement _run")

    def _run_safe(self, my_gen: int) -> None:
        """Wrap _run to guarantee a log line on unhandled exceptions -
        otherwise a poll thread can die silently and HealthMonitor only
        notices via the stale pulse_ts."""
        try:
            self._run(my_gen)
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            # RM-198: record the crash where health_pulse() can see it.
            # SystemExit is caught too: threading.excepthook drops it
            # silently, so a worker that called sys.exit() left no trace.
            self.crash_count += 1
            self.last_error = _describe_crash(my_gen, exc)
            self.died_ts = time.monotonic()
            _log.exception("%s gen=%d crashed", self._thread_name_prefix, my_gen)


def _describe_crash(my_gen: int, exc: BaseException) -> str:
    """One capped line for health_pulse()["last_error"]. Never raises: an
    exception whose __str__ raises used to escape the crash handler before
    last_error, died_ts or the log line were written."""
    try:
        text = str(exc)
    except Exception:  # noqa: BLE001 - any __str__ failure degrades the text only
        text = "<unprintable>"
    return f"gen={my_gen} {type(exc).__name__}: {text}"[:300]

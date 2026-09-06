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
from typing import Any, Dict, Optional

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
        self._generation: int = 0
        self._thread: Optional[threading.Thread] = None
        # Single-slot float writes stay GIL-atomic on CPython - no lock needed.
        # pulse_ts goes through a property (see below) whose setter is still a
        # single store to _pulse_ts, so the reader cannot observe a torn value.
        self._pulse_ts: float = 0.0
        self.last_success_ts: float = 0.0

    @property
    def pulse_ts(self) -> float:
        """Monotonic liveness stamp, read by HealthMonitor."""
        return self._pulse_ts

    @pulse_ts.setter
    def pulse_ts(self, value: Any) -> None:
        self._pulse_ts = _sanitise_pulse(value)

    # -- Public lifecycle --------------------------------------------------

    def start(self) -> None:
        """Spawn a fresh worker thread. Always increments generation; an
        already-running thread is left to exit on its own via the
        generation mismatch check inside `_run`."""
        self._stop_event.clear()
        self._generation += 1
        gen = self._generation
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
        """stop() + bounded join + start() with a fresh generation."""
        self.stop()
        if self._thread is not None:
            self._thread.join(timeout=self._restart_join_timeout_s)
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
        }

    # -- Subclass hook ----------------------------------------------------

    def _run(self, my_gen: int) -> None:  # pragma: no cover - abstract
        raise NotImplementedError("BaseCoachWorker subclasses must implement _run")

    def _run_safe(self, my_gen: int) -> None:
        """Wrap _run to guarantee a log line on unhandled exceptions -
        otherwise a poll thread can die silently and HealthMonitor only
        notices via the stale pulse_ts."""
        try:
            self._run(my_gen)
        except Exception:  # noqa: BLE001
            _log.exception("%s gen=%d crashed", self._thread_name_prefix, my_gen)

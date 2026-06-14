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
import threading
from typing import Any, Dict, Optional

_log = logging.getLogger("rc.base_worker")


class BaseCoachWorker:
    """Lifecycle base for poll-based coach workers.

    Subclass contract:
      * implement `_run(self, my_gen: int) -> None` - the poll loop. Read
        `self._stop_event.is_set()` to exit cleanly. Set
        `self.pulse_ts = time.time()` on each iteration so HealthMonitor
        sees liveness; set `self.last_success_ts` on a successful read.
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
        # Float writes are GIL-atomic on CPython - no lock needed.
        self.pulse_ts: float = 0.0
        self.last_success_ts: float = 0.0

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
        except Exception:
            _log.exception("%s gen=%d crashed", self._thread_name_prefix, my_gen)

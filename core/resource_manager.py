"""
core/resource_manager.py
Resource lifecycle management for Amberstone.

Responsibilities:
- Register cleanup callbacks that fire on exit (atexit + signal)
- Memory watchdog (warn at 700 MB, force gc.collect() above 1200 MB - the
  RM-146 ceilings, see _WARN_MB / _LIMIT_MB; on a SUSTAINED breach it also
  drives the same remediation the system uses for an unhealthy coach, via
  an injected hook - see set_remediation_hook()). A single spike over the
  limit does NOT remediate: the breach must hold for
  _MEM_SUSTAINED_SAMPLES consecutive checks, and a
  _MEM_REMEDIATION_COOLDOWN_S cooldown then prevents a flapping process
  from restart-looping. Every triggered remediation emits a structured
  "MEM-REMEDIATION" log line - it is never silent (mirrors the
  tools/cost_health_watchdog.py "never silently restart without logging"
  contract). main.py wires the hook to the coach-restart path; with no
  hook the watchdog logs + gc.collect()s only.
- A sample the watchdog could NOT measure (probe error, non-finite or
  negative value) is UNKNOWN, never "0 MB, healthy": it neither arms nor
  resets the sustained streak, and the outage is logged at WARNING once
  (plus one INFO line when measurement comes back).
- Provide a single shutdown() entry point that drains all threads cleanly,
  wakes and stops the watchdog, and disarms remediation. It is safe to
  re-enter from the SIGINT / SIGTERM handler while the interrupted main
  thread holds the registry lock (the lock is reentrant).
- Keep a weak-reference registry of all daemon threads for join-on-exit

Usage:
    from core.resource_manager import ResourceManager
    rm = ResourceManager(app_dir)
    rm.register(my_object)          # object must have a shutdown() method
    rm.start_memory_watchdog()      # optional - monitors RSS
    # ... at exit ...
    rm.shutdown()
"""

from __future__ import annotations
import atexit
import gc
import logging
import math
import os
import sys
import threading
import time
import weakref
from pathlib import Path
from typing import Callable

_log = logging.getLogger("rc.resources")

_MB = 1024 * 1024
# RM-146 (raised 2026-08-02 from 300 / 500 on a measured basis; do NOT walk
# these back without re-measuring). One clean from-boot run plus two full
# back-to-back ARAM matches on the SAME process measured RC's normal in-game
# working set at 530-548 MB RSS (both matches agreed on the roof within
# 0.3 MB) against ~1.03 GB committed. At the old 500 MB limit, simply PLAYING
# was a permanent breach: the watchdog logged at ERROR every 60s for the whole
# of every match and the restart-loop guard correctly declined to act on it
# forever, so the guard protected a bad steady state instead of fixing it.
# Nothing leaks - the +392 MB taken at the first game start is a ONE-TIME lazy
# warm-up that is REUSED (the second match's start cost only +55 MB RSS and
# +24 MB committed, not another +392/+835). _WARN_MB clears the measured
# working set so normal play is quiet; _LIMIT_MB additionally clears the
# highest RSS ever observed on this box (810 MB, on the aged pre-restart
# process - cause not explained by either measured match), so remediation
# fires only on a genuine runaway. Pinned by
# tests/test_resource_manager_ceiling_rm146.py. Full record: LEDGER 1170.
_WARN_MB  = 700
_LIMIT_MB = 1200

# Sustained-breach gate: how many CONSECUTIVE watchdog checks must report
# RSS > _LIMIT_MB before a remediation is triggered. A single transient
# spike (e.g. a one-off large allocation that gc reclaims) must NOT restart
# the live RC. At the default 60s watchdog interval, 3 samples == a breach
# that held for ~2-3 minutes.
_MEM_SUSTAINED_SAMPLES = 3


def _is_measurement(rss_mb: object) -> bool:
    """True iff rss_mb is a real RSS reading: a finite, non-negative number
    (bool excluded). Anything else is UNKNOWN, never a healthy sample."""
    if isinstance(rss_mb, bool) or not isinstance(rss_mb, (int, float)):
        return False
    return math.isfinite(rss_mb) and rss_mb >= 0.0


class ResourceManager:
    def __init__(self, app_dir: Path) -> None:
        self._app_dir      = app_dir
        self._shutdown_done = False
        # REENTRANT on purpose: _signal_handler runs shutdown() on the main
        # thread, between two bytecodes of whatever the main thread was
        # doing. If that was register() / set_remediation_hook() (both run
        # on the main thread in main.py) it already holds this lock, and a
        # plain Lock deadlocks Ctrl+C / console close forever.
        self._lock         = threading.RLock()
        self._registry: list = []           # objects with .shutdown()
        self._threads:  list[weakref.ref] = []   # tracked daemon threads
        self._watchdog: threading.Thread | None = None
        # Set by shutdown(); the watchdog waits on it instead of sleeping, so
        # teardown wakes it at once rather than after a whole interval.
        self._stop = threading.Event()
        # True while the RSS probe is failing (one WARNING per outage).
        self._probe_down = False

        # High-memory remediation wiring. _remediation_hook is an injected
        # zero-arg callable that performs the SAME remediation the system
        # uses for an unhealthy coach (main.py wires
        # app._remediation.RemediationService.restart_game_poll). When None
        # the watchdog degrades to log + gc.collect().
        self._remediation_hook = None
        # Consecutive-breach counter for the sustained-N debounce.
        self._mem_breach_streak = 0
        # monotonic() of the last triggered memory remediation (-inf = never),
        # used for the restart-loop cooldown.
        self._mem_last_remediation_mono = float("-inf")

        atexit.register(self.shutdown)

        # Windows: trap CTRL+C / console close. signal.signal raises
        # ValueError off the main thread (and OSError / ValueError for a
        # signal the platform lacks); the manager still works without the
        # handler - atexit remains the shutdown path.
        try:
            import signal
            signal.signal(signal.SIGINT,  self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except (ValueError, OSError, AttributeError) as exc:
            _log.debug("signal handlers not installed: %s", exc)

    # --- Registration -------------------------------------------------------

    def register(self, obj: object) -> None:
        """Register any object that has a shutdown() method."""
        with self._lock:
            self._registry.append(obj)

    def register_thread(self, t: threading.Thread) -> None:
        """Track a daemon thread so we can wait for it on exit."""
        with self._lock:
            self._threads.append(weakref.ref(t))

    # --- High-memory remediation wiring ---------------------------------------

    # Cooldown between two memory-triggered remediations. A flapping process
    # that climbs back over the limit immediately after a restart must NOT
    # restart-loop; 600s is comfortably longer than a clean RC restart +
    # warm-up so a genuinely-recovered process never re-trips on residual RSS.
    _MEM_REMEDIATION_COOLDOWN_S: float = 600.0

    def set_remediation_hook(self, hook: Callable[[], object] | None) -> None:
        """
        Wire the high-memory watchdog to a remediation entrypoint.

        `hook` is a zero-arg callable that performs the SAME remediation the
        system already uses for an unhealthy coach. The intended wiring is
        `app._remediation.RemediationService.restart_game_poll` (the same
        entrypoint ops/rc_self_monitor's `thread_restart` ladder step drives).
        It should return a dict like {"ok": bool, ...} but any return value
        (or exception) is tolerated - the watchdog never crashes on it.

        Passing None disables remediation (back to log + gc.collect() only).
        """
        with self._lock:
            self._remediation_hook = hook

    def _mem_remediation_step(self, rss_mb: float) -> bool:
        """
        Drive the sustained-breach gate for a single watchdog sample.

        Returns True iff this sample TRIGGERED a remediation (the Nth
        consecutive breach, outside the cooldown). All of the debounce,
        cooldown and logging live here so the policy is unit-testable
        without a real restart or a running watchdog thread.

        Restart-loop safety:
          - a single spike never fires (needs _MEM_SUSTAINED_SAMPLES in a row)
          - any sub-threshold sample resets the streak (must be *sustained*)
          - after a trigger the streak is reset AND a _MEM_REMEDIATION_-
            COOLDOWN_S window must elapse before another trigger is possible
          - a missing/raising hook is logged and swallowed (loop survives)
          - after shutdown() nothing fires: restarting the game poll in the
            middle of teardown would spawn threads the exit never joins
          - an UNKNOWN sample (None, NaN, +-inf, negative) is ignored: it
            neither arms nor resets the streak. NaN in particular must not
            reach the comparison below, where `nan <= limit` is False and
            would count garbage as a breach.
        """
        if self._shutdown_done:
            return False
        if not _is_measurement(rss_mb):
            return False
        if rss_mb <= _LIMIT_MB:
            # Below the line: a sustained breach must be UNBROKEN, so any
            # healthy sample wipes the streak.
            self._mem_breach_streak = 0
            return False

        self._mem_breach_streak += 1
        if self._mem_breach_streak < _MEM_SUSTAINED_SAMPLES:
            # Breaching but not yet sustained - arm, do not act.
            _log.warning(
                "Memory breach %d/%d: %.0f MB > %d MB (arming; not yet "
                "sustained - no remediation)",
                self._mem_breach_streak, _MEM_SUSTAINED_SAMPLES,
                rss_mb, _LIMIT_MB,
            )
            return False

        # Sustained breach reached. Reset the streak now so that, whatever
        # happens below, we re-arm from zero (no double-count) and the
        # cooldown is the sole gate on the next trigger.
        self._mem_breach_streak = 0

        now = time.monotonic()
        since = now - self._mem_last_remediation_mono
        if since < self._MEM_REMEDIATION_COOLDOWN_S:
            _log.error(
                "MEM-REMEDIATION suppressed: rss=%.0f MB sustained "
                "(>= %d MB x %d samples) but within cooldown "
                "(%.0fs / %.0fs elapsed) - NOT restarting (restart-loop "
                "guard)",
                rss_mb, _LIMIT_MB, _MEM_SUSTAINED_SAMPLES,
                since, self._MEM_REMEDIATION_COOLDOWN_S,
            )
            return False

        # Latch the cooldown BEFORE invoking the hook: even if the hook
        # raises or hangs briefly, we must not re-enter on the next sample.
        self._mem_last_remediation_mono = now

        with self._lock:
            # Re-read under the lock shutdown() sets the flag under: a
            # sample that passed the entry check just before teardown
            # began must not restart the game poll now. (A shutdown that
            # starts after this read can still overlap the hook; shutdown
            # bounds that with its 2 s watchdog join.)
            if self._shutdown_done:
                return False
            hook = self._remediation_hook

        if hook is None:
            _log.error(
                "MEM-REMEDIATION TRIGGERED but no remediation hook wired: "
                "rss=%.0f MB sustained (>= %d MB x %d samples). "
                "Logging only (set_remediation_hook not called); "
                "cooldown latched %.0fs.",
                rss_mb, _LIMIT_MB, _MEM_SUSTAINED_SAMPLES,
                self._MEM_REMEDIATION_COOLDOWN_S,
            )
            return True

        _log.error(
            "MEM-REMEDIATION TRIGGERED: rss=%.0f MB sustained "
            "(>= %d MB x %d consecutive samples) - invoking remediation "
            "hook (same path as unhealthy-coach restart); next eligible "
            "in %.0fs.",
            rss_mb, _LIMIT_MB, _MEM_SUSTAINED_SAMPLES,
            self._MEM_REMEDIATION_COOLDOWN_S,
        )
        try:
            result = hook()
            _log.error("MEM-REMEDIATION result: %r", result)
        except Exception as exc:  # noqa: BLE001
            _log.error(
                "MEM-REMEDIATION hook error (swallowed; watchdog "
                "continues, cooldown still latched): %s", exc,
            )
        return True

    # --- Memory watchdog ----------------------------------------------------

    def start_memory_watchdog(self, interval_s: float = 30.0) -> None:
        """Start background thread that monitors process RSS every interval_s."""
        with self._lock:
            if self._shutdown_done:
                return
            if self._watchdog and self._watchdog.is_alive():
                return
            t = threading.Thread(
                target=self._watchdog_loop,
                args=(interval_s,),
                daemon=True,
                name="MemoryWatchdog",
            )
            t.start()
            self._watchdog = t
        _log.debug("Memory watchdog started (check every %.0fs)", interval_s)

    def _watchdog_loop(self, interval_s: float):
        # Event.wait, not time.sleep: shutdown() sets _stop and the loop
        # leaves at once instead of sleeping out the interval (60 s live).
        while not self._shutdown_done and not self._stop.is_set():
            self._watchdog_tick()
            if self._stop.wait(interval_s):
                break

    def _watchdog_tick(self) -> None:
        """One watchdog sample. Never raises; an unmeasurable sample is
        logged (once per outage) and kept away from the remediation gate."""
        try:
            rss_mb = self._rss_mb()
            if not _is_measurement(rss_mb):
                self._probe_failed(f"probe returned {rss_mb!r}")
                return
            self._probe_ok()
            if rss_mb > _LIMIT_MB:
                _log.error(
                    "Memory limit exceeded: %.0f MB > %d MB - "
                    "forcing garbage collection",
                    rss_mb, _LIMIT_MB,
                )
                gc.collect()
                rss_after = self._rss_mb()
                if not _is_measurement(rss_after):
                    self._probe_failed(f"post-GC probe returned {rss_after!r}")
                    return
                _log.info("After GC: %.0f MB", rss_after)
                # gc alone may not reclaim a real leak. Feed the post-GC
                # RSS to the sustained-breach gate; it owns the debounce +
                # cooldown + structured logging and only restarts the coach
                # on a genuine sustained breach (see _mem_remediation_step).
                self._mem_remediation_step(rss_after)
            elif rss_mb > _WARN_MB:
                _log.warning("Memory high: %.0f MB (warn at %d MB)",
                             rss_mb, _WARN_MB)
                # A sub-limit sample must reset the sustained streak.
                self._mem_remediation_step(rss_mb)
            else:
                _log.debug("Memory: %.0f MB", rss_mb)
                self._mem_remediation_step(rss_mb)
        except Exception as exc:  # noqa: BLE001 - a watchdog thread must outlive any probe or hook failure
            self._probe_failed(f"{type(exc).__name__}: {exc}")

    def _probe_failed(self, why: str) -> None:
        # WARNING on the first failure of an outage, DEBUG after: the live
        # process logs at INFO, so a DEBUG-only failure made a blind
        # watchdog invisible, and a WARNING every 60 s would be spam.
        if not self._probe_down:
            self._probe_down = True
            _log.warning(
                "Memory watchdog: RSS unmeasurable (%s) - sample skipped; "
                "remediation streak left unchanged until it recovers", why,
            )
        else:
            _log.debug("Memory watchdog: still unmeasurable (%s)", why)

    def _probe_ok(self) -> None:
        if self._probe_down:
            self._probe_down = False
            _log.info("Memory watchdog: RSS measurable again")

    @staticmethod
    def _rss_mb() -> float | None:
        """Return current process RSS in MB, or None when the psapi fallback
        cannot measure. Never 0.0 for "unknown": the gate would read that as
        a healthy sample. psutil (pinned in requirements.txt) first - a
        psutil.Error from it propagates, and _watchdog_tick logs it as an
        outage - then a Windows psapi fallback; other platforms without
        psutil -> None."""
        try:
            import psutil
        except ImportError:
            psutil = None
        if psutil is not None:
            return psutil.Process(os.getpid()).memory_info().rss / _MB
        if sys.platform != "win32":
            return None
        # Imported OUTSIDE the measuring try: its except clause names
        # ctypes.ArgumentError, which must be bound when that tuple is built.
        try:
            import ctypes
            import ctypes.wintypes as wt
        except ImportError:
            return None
        try:
            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [("cb", wt.DWORD),
                            ("PageFaultCount", wt.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]

            pmc = PROCESS_MEMORY_COUNTERS()
            pmc.cb = ctypes.sizeof(pmc)
            # The pseudo-handle is (HANDLE)-1. Untyped, ctypes returns and
            # passes it as a 32-bit int, the upper half is lost on x64 and
            # the call fails with ERROR_INVALID_HANDLE (measured 2026-11-08:
            # the old untyped call returned 0 and the fallback read 0.0 MB on
            # every 64-bit run). Pass it typed instead.
            current_process = wt.HANDLE(-1)
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                current_process, ctypes.byref(pmc), ctypes.sizeof(pmc))
            if not ok:
                return None
            return pmc.WorkingSetSize / _MB
        except (OSError, AttributeError, ValueError, TypeError,
                ctypes.ArgumentError):
            return None

    # --- Shutdown -----------------------------------------------------------

    def _signal_handler(self, signum, frame):
        _log.info("Signal %d received - shutting down", signum)
        self.shutdown()
        sys.exit(0)

    def shutdown(self) -> None:
        """Drain all registered resources in reverse-registration order."""
        with self._lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True
            # Snapshot under the lock: a register() racing teardown must not
            # mutate the list this loop walks.
            registry = list(self._registry)
            threads = list(self._threads)
            watchdog = self._watchdog
        # Wake the watchdog out of its interval wait; it exits at once.
        self._stop.set()

        # atexit can invoke this after log handler streams are already closed
        # (pytest/logging teardown); a failed emit then sprays
        # "--- Logging error ---" tracebacks via Handler.handleError. Suppress
        # logging-internal errors for the duration and restore on the way out.
        _prev_raise = logging.raiseExceptions
        logging.raiseExceptions = False
        try:
            _log.info("ResourceManager.shutdown() - cleaning up %d objects",
                      len(registry))

            # Shut down in reverse order (last registered = first to close)
            for obj in reversed(registry):
                try:
                    if hasattr(obj, "shutdown"):
                        obj.shutdown()
                except Exception as exc:  # noqa: BLE001 - one bad resource must not stop the drain of the rest
                    _log.warning("Error shutting down %s: %s", obj, exc)

            # Join tracked daemon threads (give each 2s), and the watchdog,
            # which _stop has already woken. Joining the CURRENT thread
            # raises RuntimeError (shutdown called from a tracked thread or
            # from the watchdog's own hook), so skip it rather than swallow.
            current = threading.current_thread()
            joinable = [ref() for ref in threads]
            if watchdog is not None:
                joinable.append(watchdog)
            for t in joinable:
                if t is None or t is current or not t.is_alive():
                    continue
                try:
                    t.join(timeout=2.0)
                except RuntimeError as exc:
                    _log.debug("Thread %s not joinable: %s", t.name, exc)
                    continue
                if t.is_alive():
                    _log.warning("Thread %s did not stop cleanly", t.name)

            # Final GC
            gc.collect()
            _log.info("ResourceManager.shutdown() complete")
        finally:
            logging.raiseExceptions = _prev_raise

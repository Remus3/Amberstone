"""
core/resource_manager.py
Resource lifecycle management for Riot Commander.

Responsibilities:
- Register cleanup callbacks that fire on exit (atexit + signal)
- Memory watchdog (warn at 300 MB, force gc.collect() at 500 MB; on a
  SUSTAINED breach also drives the same remediation the system uses for
  an unhealthy coach, via an injected hook - see set_remediation_hook()).
  A single 500 MB spike does NOT remediate: the breach must hold for
  _MEM_SUSTAINED_SAMPLES consecutive checks, and a
  _MEM_REMEDIATION_COOLDOWN_S cooldown then prevents a flapping process
  from restart-looping. Every triggered remediation emits a structured
  "MEM-REMEDIATION" log line - it is never silent (mirrors the
  tools/cost_health_watchdog.py "never silently restart without logging"
  contract). The hook stays None until something wires it (main.py is
  frozen; wiring it is an operator-gated follow-up), so the default
  behavior is unchanged: log + gc.collect() only.
- Provide a single shutdown() entry point that drains all threads cleanly
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
import os
import sys
import threading
import time
import weakref
from pathlib import Path

_log = logging.getLogger("rc.resources")

_MB = 1024 * 1024
_WARN_MB  = 300
_LIMIT_MB = 500

# Sustained-breach gate: how many CONSECUTIVE watchdog checks must report
# RSS > _LIMIT_MB before a remediation is triggered. A single transient
# spike (e.g. a one-off large allocation that gc reclaims) must NOT restart
# the live RC. At the default 60s watchdog interval, 3 samples == a breach
# that held for ~2-3 minutes.
_MEM_SUSTAINED_SAMPLES = 3


class ResourceManager:
    def __init__(self, app_dir: Path):
        self._app_dir      = app_dir
        self._shutdown_done = False
        self._lock         = threading.Lock()
        self._registry: list = []           # objects with .shutdown()
        self._threads:  list[weakref.ref] = []   # tracked daemon threads
        self._watchdog: threading.Thread | None = None

        # High-memory remediation wiring (default OFF - logs only).
        # _remediation_hook is an injected zero-arg callable that performs the
        # SAME remediation the system uses for an unhealthy coach (in practice
        # app._remediation.RemediationService.restart_game_poll). It is left
        # None unless an owner calls set_remediation_hook(); when None the
        # watchdog degrades to today's behavior (log + gc.collect()).
        self._remediation_hook = None
        # Consecutive-breach counter for the sustained-N debounce.
        self._mem_breach_streak = 0
        # monotonic() of the last triggered memory remediation (-inf = never),
        # used for the restart-loop cooldown.
        self._mem_last_remediation_mono = float("-inf")

        atexit.register(self.shutdown)

        # Windows: trap CTRL+C / console close
        try:
            import signal
            signal.signal(signal.SIGINT,  self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except Exception:
            pass

    # --- Registration -------------------------------------------------------

    def register(self, obj):
        """Register any object that has a shutdown() method."""
        with self._lock:
            self._registry.append(obj)

    def register_thread(self, t: threading.Thread):
        """Track a daemon thread so we can wait for it on exit."""
        with self._lock:
            self._threads.append(weakref.ref(t))

    # --- High-memory remediation wiring ---------------------------------------

    # Cooldown between two memory-triggered remediations. A flapping process
    # that climbs back over the limit immediately after a restart must NOT
    # restart-loop; 600s is comfortably longer than a clean RC restart +
    # warm-up so a genuinely-recovered process never re-trips on residual RSS.
    _MEM_REMEDIATION_COOLDOWN_S: float = 600.0

    def set_remediation_hook(self, hook) -> None:
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
        """
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
        except Exception as exc:
            _log.error(
                "MEM-REMEDIATION hook error (swallowed; watchdog "
                "continues, cooldown still latched): %s", exc,
            )
        return True

    # --- Memory watchdog ----------------------------------------------------

    def start_memory_watchdog(self, interval_s: float = 30.0):
        """Start background thread that monitors process RSS every interval_s."""
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
        while not self._shutdown_done:
            try:
                rss_mb = self._rss_mb()
                if rss_mb > _LIMIT_MB:
                    _log.error(
                        "Memory limit exceeded: %.0f MB > %d MB - "
                        "forcing garbage collection",
                        rss_mb, _LIMIT_MB,
                    )
                    gc.collect()
                    rss_after = self._rss_mb()
                    _log.info("After GC: %.0f MB", rss_after)
                    # gc alone may not reclaim a real leak. Feed the
                    # post-GC RSS to the sustained-breach gate; it owns
                    # the debounce + cooldown + structured logging and
                    # only restarts the coach on a genuine sustained
                    # breach (see _mem_remediation_step).
                    self._mem_remediation_step(rss_after)
                elif rss_mb > _WARN_MB:
                    _log.warning("Memory high: %.0f MB (warn at %d MB)",
                                 rss_mb, _WARN_MB)
                    # A sub-limit sample must reset the sustained streak.
                    self._mem_remediation_step(rss_mb)
                else:
                    _log.debug("Memory: %.0f MB", rss_mb)
                    self._mem_remediation_step(rss_mb)
            except Exception as exc:
                _log.debug("Watchdog error: %s", exc)
            time.sleep(interval_s)

    @staticmethod
    def _rss_mb() -> float:
        """Return current process RSS in MB.  Works on Windows and Linux."""
        try:
            import psutil
            return psutil.Process(os.getpid()).memory_info().rss / _MB
        except ImportError:
            pass
        try:
            # Windows fallback via ctypes
            import ctypes
            import ctypes.wintypes
            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [("cb", ctypes.wintypes.DWORD),
                             ("PageFaultCount", ctypes.wintypes.DWORD),
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
            ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(),
                ctypes.byref(pmc), ctypes.sizeof(pmc))
            return pmc.WorkingSetSize / _MB
        except Exception:
            return 0.0

    # --- Shutdown -----------------------------------------------------------

    def _signal_handler(self, signum, frame):
        _log.info("Signal %d received - shutting down", signum)
        self.shutdown()
        sys.exit(0)

    def shutdown(self):
        """Drain all registered resources in reverse-registration order."""
        with self._lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True

        _log.info("ResourceManager.shutdown() - cleaning up %d objects",
                  len(self._registry))

        # Shut down in reverse order (last registered = first to close)
        for obj in reversed(self._registry):
            try:
                if hasattr(obj, "shutdown"):
                    obj.shutdown()
            except Exception as exc:
                _log.warning("Error shutting down %s: %s", obj, exc)

        # Join tracked daemon threads (give each 2s)
        for ref in self._threads:
            t = ref()
            if t and t.is_alive():
                try:
                    t.join(timeout=2.0)
                    if t.is_alive():
                        _log.warning("Thread %s did not stop cleanly", t.name)
                except Exception:
                    pass

        # Final GC
        gc.collect()
        _log.info("ResourceManager.shutdown() complete")

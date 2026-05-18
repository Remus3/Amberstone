"""
core/resource_manager.py
Resource lifecycle management for Riot Commander.

Responsibilities:
- Register cleanup callbacks that fire on exit (atexit + signal)
- Memory watchdog (warn at 300 MB, force gc.collect() at 500 MB).
  NOTE: an earlier docstring promised "restart coach at 500 MB" but the
  watchdog only logs + gc.collect()s - it never invokes a remediation
  hook. Wiring an actual coach restart would need to call into the
  frozen `app/_remediation.py`; a future refactor could do that.
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


class ResourceManager:
    def __init__(self, app_dir: Path):
        self._app_dir      = app_dir
        self._shutdown_done = False
        self._lock         = threading.Lock()
        self._registry: list = []           # objects with .shutdown()
        self._threads:  list[weakref.ref] = []   # tracked daemon threads
        self._watchdog: threading.Thread | None = None

        atexit.register(self.shutdown)

        # Windows: trap CTRL+C / console close
        try:
            import signal
            signal.signal(signal.SIGINT,  self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except Exception:
            pass

    # ── Registration ─────────────────────────────────────────────────────────

    def register(self, obj):
        """Register any object that has a shutdown() method."""
        with self._lock:
            self._registry.append(obj)

    def register_thread(self, t: threading.Thread):
        """Track a daemon thread so we can wait for it on exit."""
        with self._lock:
            self._threads.append(weakref.ref(t))

    # ── Memory watchdog ──────────────────────────────────────────────────────

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
                elif rss_mb > _WARN_MB:
                    _log.warning("Memory high: %.0f MB (warn at %d MB)",
                                 rss_mb, _WARN_MB)
                else:
                    _log.debug("Memory: %.0f MB", rss_mb)
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

    # ── Shutdown ─────────────────────────────────────────────────────────────

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

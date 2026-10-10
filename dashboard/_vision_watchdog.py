# arch: periodic liveness self-heal for the :8889 vision server (RM-735) | section=dashboard | frozen=no
"""Keep a LIVE vision server on :8889, not just a bound port (RM-735).

Before RM-735, ``start_dashboard`` ran one ``connect_ex`` against :8889 at
dashboard start and spawned ``moon_vision_server.py`` if nothing answered.
That checked port ownership once: a server that wedged while holding the
port (the session 106 wedge, twice within ~2 h - accept loop parked in
``Thread.start``) or one that died later was never replaced until RC itself
restarted.

This watchdog probes ``GET /health`` with a short timeout every
``interval_s`` seconds from a daemon thread in the RC process:

* ok   - reset the failure count and the spawn back-off;
* down - connection refused and nothing listens: spawn now. Refused while a
  process DOES listen (a full accept backlog - Windows resets the SYN) is
  hung, not down;
* hung - timeout, reset or a non-200 from a listener: count it. At
  ``fail_threshold`` consecutive hung probes, dump the holder's stacks with
  py-spy when it is installed (evidence for the next wedge, written under
  ``logs/``), ``taskkill /F`` the holder - only if its command line is a
  vision server; a foreign holder is logged and left alone - then spawn a
  fresh server. The fresh process reaps any other vision instance before it
  binds (``vision_server/_reap.py``).

After every spawn a grace window (``grace_s``, doubling up to
``max_grace_s`` while nothing comes back ok) keeps a slow boot on a loaded
box from being reaped by the next spawn. Every side effect is injectable for
tests; the defaults pass ``CREATE_NO_WINDOW`` on every child.
"""
from __future__ import annotations

import http.client
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from core.polled_json import atomic_write_bytes
from core.ports import VISION

_log = logging.getLogger("rc.web_dashboard")

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
# Command-line markers of a vision-server process (same set as
# vision_server/_reap.py): the file-path spawn and the module form.
_MARKERS = ("moon_vision_server", "-m vision_server")

OK, DOWN, HUNG = "ok", "down", "hung"

INTERVAL_S = 15.0
TIMEOUT_S = 3.0
FAIL_THRESHOLD = 3
GRACE_S = 90.0
MAX_GRACE_S = 1800.0


# -- default side effects ------------------------------------------------------
def probe_health(port: int, timeout_s: float) -> str:
    """``GET /health`` on loopback -> OK / DOWN / HUNG. Never raises."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout_s)
    try:
        conn.request("GET", "/health")
        resp = conn.getresponse()
        resp.read(65536)
        return OK if resp.status == 200 else HUNG
    except ConnectionRefusedError:
        return DOWN
    except (OSError, http.client.HTTPException, ValueError):
        return HUNG
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def find_listener_pid(port: int) -> Optional[int]:
    """PID listening on ``port`` (any local address), or None."""
    try:
        import psutil
        for c in psutil.net_connections(kind="tcp"):
            if (c.status == psutil.CONN_LISTEN and c.laddr
                    and c.laddr.port == port and c.pid):
                return int(c.pid)
    except Exception as exc:  # noqa: BLE001
        _log.debug("vision watchdog: listener lookup failed: %s", exc)
    return None


def is_vision_pid(pid: int) -> bool:
    try:
        import psutil
        cmdline = " ".join(psutil.Process(pid).cmdline() or [])
    except Exception:  # noqa: BLE001
        return False
    return any(m in cmdline for m in _MARKERS)


def kill_pid(pid: int) -> bool:
    """``taskkill /F /PID`` (repo rule: never Stop-Process)."""
    try:
        r = subprocess.run(["taskkill", "/F", "/PID", str(int(pid))],
                           capture_output=True, timeout=15,
                           creationflags=_NO_WINDOW)
        return r.returncode == 0
    except Exception as exc:  # noqa: BLE001
        _log.warning("vision watchdog: taskkill %s failed: %s", pid, exc)
        return False


def capture_stack(pid: int, app_dir: Path) -> Optional[Path]:
    """Best-effort ``py-spy dump`` of a hung holder into ``logs/``."""
    exe = shutil.which("py-spy")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "dump", "--pid", str(int(pid))],
                           capture_output=True, timeout=30,
                           creationflags=_NO_WINDOW)
        out = Path(app_dir) / "logs" / (
            f"vision_wedge_{time.strftime('%Y%m%d-%H%M%S')}_{int(pid)}.txt")
        # Shared helper: creates logs/, per-writer scratch name, fsync and the
        # WinError 5 retry (atomic-write guard RM-258 / RM-261).
        atomic_write_bytes(out, (r.stdout or b"") + (r.stderr or b""))
        return out
    except Exception as exc:  # noqa: BLE001
        _log.warning("vision watchdog: py-spy dump of %s failed: %s", pid, exc)
        return None


def spawn_vision(app_dir: Path) -> int:
    """Start ``moon_vision_server.py`` windowless and detached from RC stdio."""
    app_dir = Path(app_dir)
    proc = subprocess.Popen(
        [sys.executable, str(app_dir / "moon_vision_server.py")],
        cwd=str(app_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=_NO_WINDOW,
    )
    return proc.pid


# -- the watchdog ----------------------------------------------------------------
class VisionWatchdog:
    def __init__(self, app_dir: Path, *, port: int = VISION,
                 interval_s: float = INTERVAL_S, timeout_s: float = TIMEOUT_S,
                 fail_threshold: int = FAIL_THRESHOLD, grace_s: float = GRACE_S,
                 max_grace_s: float = MAX_GRACE_S,
                 probe: Callable[[int, float], str] = probe_health,
                 find_holder: Callable[[int], Optional[int]] = find_listener_pid,
                 is_vision: Callable[[int], bool] = is_vision_pid,
                 kill: Callable[[int], bool] = kill_pid,
                 spawn: Callable[[Path], int] = spawn_vision,
                 capture: Callable[[int, Path], Optional[Path]] = capture_stack,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.app_dir = Path(app_dir)
        self.port = port
        self.interval_s = interval_s
        self.timeout_s = timeout_s
        self.fail_threshold = max(1, int(fail_threshold))
        self.grace_s = grace_s
        self.max_grace_s = max(grace_s, max_grace_s)
        self._probe = probe
        self._find_holder = find_holder
        self._is_vision = is_vision
        self._kill = kill
        self._spawn = spawn
        self._capture = capture
        self._clock = clock
        self.failures = 0
        self.grace_until = 0.0
        self.current_grace_s = grace_s

    def tick(self) -> str:
        """One probe and at most one action. Returns what it did."""
        state = self._probe(self.port, self.timeout_s)
        now = self._clock()
        if state == OK:
            if self.failures:
                _log.info("vision server answering again after %d failed "
                          "probe(s)", self.failures)
            self.failures = 0
            self.grace_until = 0.0
            self.current_grace_s = self.grace_s
            return "ok"
        if now < self.grace_until:
            return "grace"
        if state == DOWN:
            if self._find_holder(self.port) is None:
                self._respawn(now)
                _log.info("vision server not running - spawned "
                          "moon_vision_server.py")
                return "spawned"
            # Something LISTENS but refuses: Windows answers a SYN with a reset
            # once the accept backlog is full, i.e. the holder stopped
            # accepting (measured live 2026-10-10 with a suspended holder).
            # Same verdict as a timeout.
            state = HUNG
        self.failures += 1
        if self.failures < self.fail_threshold:
            if self.failures == 1:
                _log.warning("vision server /health did not answer within "
                             "%.1fs (1/%d)", self.timeout_s, self.fail_threshold)
            return "suspect"
        holder = self._find_holder(self.port)
        if holder is not None and not self._is_vision(holder):
            _log.warning("vision port %d is held by pid %d, which is not a "
                         "vision server - left alone", self.port, holder)
            self.failures = 0
            self._start_grace(now)
            return "foreign"
        killed = None
        if holder is not None:
            dump = self._capture(holder, self.app_dir)
            killed = self._kill(holder)
            if not killed:
                _log.warning("vision watchdog could not kill hung pid %d", holder)
            elif dump is not None:
                _log.info("vision watchdog: stack dump of pid %d at %s",
                          holder, dump)
        self._respawn(now)
        _log.warning("vision server hung (%d consecutive /health failures) - "
                     "killed pid %s (%s), spawned moon_vision_server.py",
                     self.fail_threshold, holder,
                     "ok" if killed else "not killed" if holder else "gone")
        return "replaced"

    def _respawn(self, now: float) -> None:
        self.failures = 0
        try:
            self._spawn(self.app_dir)
        finally:
            self._start_grace(now)

    def _start_grace(self, now: float) -> None:
        self.grace_until = now + self.current_grace_s
        self.current_grace_s = min(self.current_grace_s * 2, self.max_grace_s)

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - the loop must outlive a tick
                _log.warning("vision watchdog tick failed: %s", exc)
            stop.wait(self.interval_s)


_RUNNING: Optional[VisionWatchdog] = None
_START_LOCK = threading.Lock()


def start_vision_watchdog(app_dir: Path) -> VisionWatchdog:
    """Start the watchdog thread once per process; the first tick is now."""
    global _RUNNING
    with _START_LOCK:
        if _RUNNING is not None:
            return _RUNNING
        wd = VisionWatchdog(app_dir)
        t = threading.Thread(target=wd.run, args=(threading.Event(),),
                             daemon=True, name="VisionWatchdog")
        t.start()
        _RUNNING = wd
        return wd

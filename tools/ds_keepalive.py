"""RC-independent restarter for the Daemon Slayer engine on :8860 (RM-750).

Why: RC's ``DsWatchdog`` (``core/daemon_slayer_client.py``) was DS's only
relauncher. Task Scheduler RestartOnFailure on RC-DaemonSlayer is inert for a
crash exit - the kill's exit 1 was logged as "successfully completed" and no
relaunch came within 161 s (measured 2026-10-16, LEDGER 1731) - so while RC
was down (crash loop, tripped circuit breaker, operator stop) a crashed or
wedged DS stayed down.

What: this long-lived loop runs the SAME ``DsWatchdog`` RC runs, so liveness
is a real ``GET /health`` round trip and a holder that listens but does not
answer is replaced (DS has wedged with the task Running, the port in LISTEN
and a live pid; only the request found it). Three differences from RC's copy:

* it acts only while RC's watchdog is NOT live - RC's loop leaves
  ``ops/runtime/ds_watchdog_rc.json`` on every pass; while that is fresh and
  its pid alive, the keepalive probes nothing and drops its own state, so a
  later takeover starts counting from zero;
* it relaunches ONLY through the RC-DaemonSlayer task
  (``spawn_ds_task_only``), never as a child, so the task stays the single
  owner of DS (RM-740 (e)) and IgnoreNew de-duplicates any overlap with RC;
* it idles while ``ops/runtime/DS_KEEPALIVE_STOP`` exists (legion_off.ps1
  writes it so "off" stays off; legion_on.ps1 removes it).

It also takes over only while that relaunch route EXISTS: every step asks
``schtasks /Query`` for RC-DaemonSlayer and, while it is absent, stands down
as ``no-task`` (S144-T-708). The watchdog kills a verified DS that is hung or
slow to bind and then relaunches it; with no task the relaunch raises, so a
watchdog there could only take DS down, never bring it back.

Status (2026-10-31 launcher cutover): RC-DaemonSlayer is unregistered and
RC-DSKeepalive was never registered (docs/OPERATIONS.md, "Moved to the app"),
so on this host the keepalive stands down as ``no-task`` and watches
nothing; it only acts on a host that still registers both.

Host: the RC-DSKeepalive scheduled task (``tools/install_ds_keepalive_task.ps1``:
SYSTEM, at startup plus a 1-minute indefinite repeat with IgnoreNew, so Task
Scheduler restarts the keepalive itself if it dies). Log:
``logs/ds_keepalive.log`` (ProgramData fallback when SYSTEM cannot write it).

Usage::

    pythonw tools/ds_keepalive.py            # the task's action (runs forever)
    python  tools/ds_keepalive.py --status   # read-only view; acts on nothing
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import core.daemon_slayer_client as dsc  # noqa: E402
from core.log_rotation import LFRotatingFileHandler  # noqa: E402

logger = logging.getLogger("rc.tools.ds_keepalive")

STOP_FLAG = _PROJECT_ROOT / "ops" / "runtime" / "DS_KEEPALIVE_STOP"
_LOG_FILE = _PROJECT_ROOT / "logs" / "ds_keepalive.log"
_FALLBACK_LOG_FILE = (
    Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData")
    / "Amberstone" / "ds_keepalive.log"
)


def stop_flag_present(path: Path = STOP_FLAG) -> bool:
    try:
        return Path(path).exists()
    except OSError:
        return False


def ds_task_registered() -> bool:
    """Is the RC-DaemonSlayer task registered? Read-only; never raises.

    ``schtasks /Query`` only - never ``/Run`` or ``/End``. No schtasks, a
    timeout or any other refusal reads as "not registered", which makes the
    keepalive stand down: without the task it has no way to relaunch DS.
    """
    try:
        return dsc._schtasks("/Query", "/TN", dsc.DS_TASK_NAME) == 0
    except (OSError, subprocess.SubprocessError):
        return False


def make_keepalive_watchdog() -> dsc.DsWatchdog:
    """RC's watchdog with every default, but relaunching only via the task."""
    return dsc.DsWatchdog(spawn=dsc.spawn_ds_task_only)


class DsKeepalive:
    """One ``step`` per interval: stopped / deferred / no-task, or one tick."""

    def __init__(self, *,
                 rc_live: Callable[[], bool] = dsc.rc_watchdog_live,
                 stopped: Callable[[], bool] = stop_flag_present,
                 make_watchdog: Callable[[], dsc.DsWatchdog] = make_keepalive_watchdog,
                 task_registered: Callable[[], bool] = ds_task_registered,
                 ) -> None:
        self._rc_live = rc_live
        self._stopped = stopped
        self._make_watchdog = make_watchdog
        self._task_registered = task_registered
        self._wd: Optional[dsc.DsWatchdog] = None
        self._idle: Optional[str] = None
        # run(): the (type, message) of the failure last logged with its
        # traceback, and how many steps in a row have failed.
        self._fail_sig: Optional[tuple] = None
        self._fail_count = 0

    def step(self) -> str:
        if self._stopped():
            return self._stand_down("stopped", f"{STOP_FLAG.name} is present")
        if self._rc_live():
            return self._stand_down("deferred", "RC's DsWatchdog is live")
        if not self._route_exists():
            # Checked every step, not only at takeover: the next tick may be
            # the one that kills, and a kill with no relaunch is an outage.
            return self._stand_down(
                "no-task", f"no {dsc.DS_TASK_NAME} task to relaunch DS through")
        if self._wd is None:
            logger.warning("RC's DsWatchdog is not live - the keepalive is "
                           "watching DS :%d", dsc.DEFAULT_PORT)
            self._wd = self._make_watchdog()
            self._idle = None
        return self._wd.tick()

    def _route_exists(self) -> bool:
        try:
            return bool(self._task_registered())
        except Exception as exc:  # noqa: BLE001 - unknown reads as absent
            logger.debug("ds_keepalive route check failed: %r", exc)
            return False

    def _stand_down(self, mode: str, why: str) -> str:
        if self._idle != mode:
            logger.info("%s - the keepalive is not watching DS (%s)", why, mode)
            self._idle = mode
        self._wd = None
        return mode

    def run(self, stop: threading.Event,
            interval_s: float = dsc.WATCHDOG_INTERVAL_S) -> None:
        while not stop.is_set():
            try:
                self.step()
            except Exception as exc:  # noqa: BLE001 - the loop must outlive a step
                self._step_failed(exc)
            else:
                self._step_ok()
            stop.wait(interval_s)

    def _step_failed(self, exc: Exception) -> None:
        """Log a failing step: the traceback once per kind, repeats at DEBUG.

        A deterministic bug fails every interval; logging each one at WARNING
        without its type buried the cause under one identical line per 30 s
        (and ``KeyError()`` logged an empty message).
        """
        self._fail_count += 1
        sig = (type(exc).__name__, str(exc))
        if sig != self._fail_sig:
            self._fail_sig = sig
            logger.warning("ds_keepalive step failed: %s: %s", sig[0], sig[1],
                           exc_info=(type(exc), exc, exc.__traceback__))
        else:
            logger.debug("ds_keepalive step failed again (%d in a row): %s: %s",
                         self._fail_count, sig[0], sig[1])

    def _step_ok(self) -> None:
        if self._fail_count:
            logger.info("ds_keepalive recovered after %d failed step(s)",
                        self._fail_count)
        self._fail_count = 0
        self._fail_sig = None


def status() -> dict:
    """What the keepalive would see now. Probes /health; changes nothing."""
    return {
        "health": dsc.probe_ds_health(dsc.DEFAULT_PORT, dsc.WATCHDOG_TIMEOUT_S),
        "rc_watchdog_live": dsc.rc_watchdog_live(),
        "stop_flag": stop_flag_present(),
    }


def _attach_log() -> None:
    """Add one rotating file handler to the root logger (the first that opens).

    Idempotent: a second call while a handler for either log file is attached
    adds nothing (a duplicate would double every line and hold a second open
    file handle for the life of the process).
    """
    root = logging.getLogger()
    wanted = {os.path.abspath(str(t)) for t in (_LOG_FILE, _FALLBACK_LOG_FILE)}
    if any(os.path.abspath(str(getattr(h, "baseFilename", ""))) in wanted
           for h in root.handlers):
        return
    for target in (_LOG_FILE, _FALLBACK_LOG_FILE):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            handler = LFRotatingFileHandler(
                target, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        except OSError:
            continue
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        return


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true",
                    help="print the keepalive's view as JSON and exit; acts on nothing")
    args = ap.parse_args(argv)
    if args.status:
        print(json.dumps(status(), sort_keys=True))
        return 0
    _attach_log()
    logger.info("ds_keepalive started (pid %d)", os.getpid())
    DsKeepalive().run(threading.Event())
    return 0


if __name__ == "__main__":
    sys.exit(main())

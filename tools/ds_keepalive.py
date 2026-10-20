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
import logging.handlers
import os
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import core.daemon_slayer_client as dsc  # noqa: E402

logger = logging.getLogger("rc.tools.ds_keepalive")

STOP_FLAG = _PROJECT_ROOT / "ops" / "runtime" / "DS_KEEPALIVE_STOP"
_LOG_FILE = _PROJECT_ROOT / "logs" / "ds_keepalive.log"
_FALLBACK_LOG_FILE = (
    Path(os.environ.get("ProgramData") or r"C:\ProgramData")
    / "Amberstone" / "ds_keepalive.log"
)


def stop_flag_present(path: Path = STOP_FLAG) -> bool:
    try:
        return Path(path).exists()
    except OSError:
        return False


def make_keepalive_watchdog() -> dsc.DsWatchdog:
    """RC's watchdog with every default, but relaunching only via the task."""
    return dsc.DsWatchdog(spawn=dsc.spawn_ds_task_only)


class DsKeepalive:
    """One ``step`` per interval: stopped / deferred, or one watchdog tick."""

    def __init__(self, *,
                 rc_live: Callable[[], bool] = dsc.rc_watchdog_live,
                 stopped: Callable[[], bool] = stop_flag_present,
                 make_watchdog: Callable[[], dsc.DsWatchdog] = make_keepalive_watchdog,
                 ) -> None:
        self._rc_live = rc_live
        self._stopped = stopped
        self._make_watchdog = make_watchdog
        self._wd: Optional[dsc.DsWatchdog] = None
        self._idle: Optional[str] = None

    def step(self) -> str:
        if self._stopped():
            return self._stand_down("stopped", f"{STOP_FLAG.name} is present")
        if self._rc_live():
            return self._stand_down("deferred", "RC's DsWatchdog is live")
        if self._wd is None:
            logger.warning("RC's DsWatchdog is not live - the keepalive is "
                           "watching DS :%d", dsc.DEFAULT_PORT)
            self._wd = self._make_watchdog()
            self._idle = None
        return self._wd.tick()

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
                logger.warning("ds_keepalive step failed: %s", exc)
            stop.wait(interval_s)


def status() -> dict:
    """What the keepalive would see now. Probes /health; changes nothing."""
    return {
        "health": dsc.probe_ds_health(dsc.DEFAULT_PORT, dsc.WATCHDOG_TIMEOUT_S),
        "rc_watchdog_live": dsc.rc_watchdog_live(),
        "stop_flag": stop_flag_present(),
    }


def _attach_log() -> None:
    for target in (_LOG_FILE, _FALLBACK_LOG_FILE):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                target, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        except OSError:
            continue
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger()
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

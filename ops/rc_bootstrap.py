"""
ops/rc_bootstrap.py

One-shot bootstrap: when hot-reloaded into the running app, starts any
ops components (bridge, supervisor, watchdog) that are not currently running.
Safe to reload repeatedly — checks before spawning.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
_CONFIG       = str(_PROJECT_ROOT / "ops" / "rc_config.json")
_BRIDGE       = str(_PROJECT_ROOT / "ops" / "rc_file_bridge.py")
_SUPERVISOR   = str(_PROJECT_ROOT / "ops" / "rc_supervisor.py")
_WATCHDOG     = str(_PROJECT_ROOT / "ops" / "run_self_healing_watchdog.ps1")
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

import logging
_log = logging.getLogger("rc.bootstrap")


def _is_running(script_fragment: str) -> bool:
    """Check if a pythonw process with the given script is running."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NonInteractive", "-NoProfile", "-Command",
             f"(Get-CimInstance Win32_Process | Where-Object {{$_.CommandLine -like '*{script_fragment}*'}}).Count"],
            capture_output=True, text=True, timeout=8,
            creationflags=_CREATE_NO_WINDOW
        )
        count = int(result.stdout.strip() or "0")
        return count > 0
    except Exception:
        return False


def _start(exe: str, args: list[str], tag: str) -> int | None:
    try:
        proc = subprocess.Popen(
            [exe] + args,
            cwd=str(_PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
        )
        _log.info("rc_bootstrap: started %s pid=%d", tag, proc.pid)
        return proc.pid
    except Exception as exc:
        _log.error("rc_bootstrap: failed to start %s: %s", tag, exc)
        return None


# ── Run on import/reload ──────────────────────────────────────────────────

_results = {}

# Bridge
if not _is_running("rc_file_bridge"):
    pid = _start("pythonw.exe", [_BRIDGE, "--config", _CONFIG], "file_bridge")
    _results["bridge"] = f"started pid={pid}"
    _log.info("rc_bootstrap: bridge was down — started pid=%s", pid)
else:
    _results["bridge"] = "already_running"
    _log.info("rc_bootstrap: bridge already running")

# Supervisor
if not _is_running("rc_supervisor"):
    pid = _start("pythonw.exe", [_SUPERVISOR, "--config", _CONFIG], "supervisor")
    _results["supervisor"] = f"started pid={pid}"
    _log.info("rc_bootstrap: supervisor was down — started pid=%s", pid)
else:
    _results["supervisor"] = "already_running"
    _log.info("rc_bootstrap: supervisor already running")

# Watchdog
if not _is_running("run_self_healing_watchdog"):
    pid = _start(
        "powershell.exe",
        ["-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass",
         "-File", _WATCHDOG, "-ConfigPath", _CONFIG],
        "watchdog"
    )
    _results["watchdog"] = f"started pid={pid}"
    _log.info("rc_bootstrap: watchdog was down — started pid=%s", pid)
else:
    _results["watchdog"] = "already_running"
    _log.info("rc_bootstrap: watchdog already running")

_log.info("rc_bootstrap complete: %s", _results)

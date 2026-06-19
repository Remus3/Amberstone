"""gamepc_bridge_daemon.py - zero-cost bridge task sentinel for Game-PC.

Polls Legion's /api/bridge for unhandled tasks targeted at 'gamepc'.
Invokes `claude --print "/process-bridge-tasks"` ONLY when count > 0.
Zero API cost when the queue is empty.

State files (C:\\RC-Agent\\):
    bridge_daemon_health.json  - last poll status, invocation count
    bridge_daemon.lock         - held while claude --print is running

Scheduled task: RC-BridgeDaemon  (at logon, restart-on-failure 3x/1min)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

# -- Config ----------------------------------------------------------------
POLL_IDLE_S  = 30    # seconds between polls when empty
POLL_WORK_S  = 10    # seconds after a batch completes before re-checking
LOCK_STALE_S = 300   # seconds before a held lock is declared stale
TARGET       = "gamepc"

SCRIPT_DIR   = Path(__file__).resolve().parent   # C:\RC-Agent\
PULL_SCRIPT  = SCRIPT_DIR / "bridge_pull_tasks.py"
HEALTH_FILE  = SCRIPT_DIR / "bridge_daemon_health.json"
LOCK_FILE    = SCRIPT_DIR / "bridge_daemon.lock"

# -- Logging ---------------------------------------------------------------
# Console handler (useful when running foreground; no-op under pythonw.exe)
_fmt = logging.Formatter("%(asctime)s [bridge-daemon] %(levelname)s %(message)s",
                          datefmt="%H:%M:%S")
_root = logging.getLogger()
_root.setLevel(logging.INFO)
_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
_root.addHandler(_ch)
# File handler - always active; rotate at ~1 MB to keep it bounded
from logging.handlers import RotatingFileHandler as _RFH
_fh = _RFH(SCRIPT_DIR / "bridge_daemon.log", maxBytes=1_000_000, backupCount=2,
            encoding="utf-8")
_fh.setFormatter(_fmt)
_root.addHandler(_fh)
_log = logging.getLogger("bridge_daemon")


# -- Helpers ---------------------------------------------------------------

def _resolve_claude() -> str:
    """Find claude CLI binary (Windows .cmd shim or bare executable)."""
    override = os.environ.get("ANTHROPIC_CLAUDE_PATH")
    if override and os.path.exists(override):
        return override
    appdata = os.environ.get("APPDATA", "")
    candidates = [
        os.path.join(appdata, "npm", "claude.cmd") if appdata else None,
        os.path.join(appdata, "npm", "claude.exe") if appdata else None,
        "claude.cmd", "claude.exe", "claude",
    ]
    for c in (c for c in candidates if c):
        if os.path.isabs(c) and os.path.exists(c):
            return c
        found = shutil.which(c)
        if found:
            return found
    return "claude"


def _pid_alive(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    r = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
        capture_output=True, text=True, timeout=5,
    )
    return str(pid) in r.stdout


def _lock_held() -> bool:
    if not LOCK_FILE.exists():
        return False
    try:
        info = json.loads(LOCK_FILE.read_text())
        age  = time.time() - float(info.get("ts", 0))
        pid  = int(info.get("pid", 0))
        if age > LOCK_STALE_S or not _pid_alive(pid):
            _log.warning("clearing stale lock (age=%.0fs pid=%d)", age, pid)
            LOCK_FILE.unlink(missing_ok=True)
            return False
        return True
    except Exception:  # noqa: BLE001
        LOCK_FILE.unlink(missing_ok=True)
        return False


def _set_lock(held: bool) -> None:
    if held:
        tmp = LOCK_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"pid": os.getpid(), "ts": time.time()}))
        tmp.replace(LOCK_FILE)
    else:
        LOCK_FILE.unlink(missing_ok=True)


def _write_health(status: str, count: int, last_task_ts: float,
                  invocations: int) -> None:
    data = {
        "status": status,            # "idle" | "invoking" | "locked"
        "pid": os.getpid(),
        "target": TARGET,
        "pending_count": count,
        "last_check_ts": time.time(),
        "last_task_ts": last_task_ts or None,
        "invocations_since_boot": invocations,
        "poll_idle_s": POLL_IDLE_S,
    }
    tmp = HEALTH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(HEALTH_FILE)


def _check_count() -> int:
    """Return count of pending unhandled tasks for TARGET. 0 on error."""
    if not PULL_SCRIPT.exists():
        _log.error("bridge_pull_tasks.py not found at %s", PULL_SCRIPT)
        return 0
    try:
        r = subprocess.run(
            [sys.executable, str(PULL_SCRIPT), "--target", TARGET],
            capture_output=True, text=True, timeout=15,
        )
        data = json.loads(r.stdout)
        return int(data.get("count", 0))
    except Exception as e:  # noqa: BLE001
        _log.debug("check failed: %s", e)
        return 0


# -- Main loop -------------------------------------------------------------

def main() -> None:
    _log.info("starting  pid=%d  target=%s  poll_idle=%ds",
              os.getpid(), TARGET, POLL_IDLE_S)
    claude = _resolve_claude()
    _log.info("claude binary: %s", claude)

    invocations  = 0
    last_task_ts = 0.0
    stopping     = [False]

    def _on_signal(*_):
        stopping[0] = True

    signal.signal(signal.SIGTERM, _on_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _on_signal)

    sleep_s = POLL_IDLE_S

    while not stopping[0]:
        count = _check_count()

        if count > 0:
            _log.info("%d task(s) pending for %s", count, TARGET)
            if _lock_held():
                _log.info("claude already running (lock held) - will recheck in %ds",
                          POLL_WORK_S)
                _write_health("locked", count, last_task_ts, invocations)
                sleep_s = POLL_WORK_S
            else:
                _set_lock(True)
                last_task_ts = time.time()
                invocations += 1
                _write_health("invoking", count, last_task_ts, invocations)
                _log.info("invoking claude --print /process-bridge-tasks  "
                          "(invocation #%d)", invocations)
                try:
                    # CREATE_NO_WINDOW prevents a conhost window from flashing
                    # on each cadence: claude is a .cmd npm shim on Windows
                    # and a pythonw parent cannot suppress the conhost spawn
                    # via STARTUPINFO alone. Cross-platform safe via the
                    # win32 guard.
                    _flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                    # Force OAuth: strip any raw sk-ant-api03 env var so the
                    # claude CLI falls through to ~/.claude/.credentials.json.
                    # Defense-in-depth - the registry should already be clean
                    # post fleet OAuth migration 2026-05-20.
                    _env = os.environ.copy()
                    _env.pop("ANTHROPIC_API_KEY", None)
                    subprocess.run(
                        [claude, "--dangerously-skip-permissions",
                         "-p", "/process-bridge-tasks"],
                        timeout=180,
                        creationflags=_flags,
                        env=_env,
                    )
                except subprocess.TimeoutExpired:
                    _log.warning("claude --print timed out after 180s")
                except Exception as e:  # noqa: BLE001
                    _log.error("claude invocation error: %s", e)
                finally:
                    _set_lock(False)
                # Re-check quickly - the batch may have had multiple tasks and
                # bridge_pull_tasks dedupes by processed IDs, so a fresh check
                # confirms everything was handled.
                sleep_s = POLL_WORK_S
        else:
            _write_health("idle", 0, last_task_ts, invocations)
            sleep_s = POLL_IDLE_S

        # Interruptible sleep: wakes every 1s to respect stopping flag
        deadline = time.monotonic() + sleep_s
        while not stopping[0] and time.monotonic() < deadline:
            time.sleep(1)

    _log.info("stopping cleanly")
    _set_lock(False)


if __name__ == "__main__":
    main()

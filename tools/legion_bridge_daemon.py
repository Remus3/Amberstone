"""legion_bridge_daemon.py - zero-cost bridge task sentinel for Legion.

Polls Legion's own /api/bridge for unhandled tasks targeted at 'legion'.
Invokes `claude --print "/process-bridge-tasks"` ONLY when count > 0.
Zero API cost when the queue is empty.

Mirrors tools/gamepc_bridge_daemon.py + tools/peer_bridge_daemon.py to close
the fleet symmetry gap surfaced 2026-05-20 (verify-bridge-roundtrip self-test
exited 0xC000013A without verdict update because no Legion daemon was firing
/process-bridge-tasks on incoming kind=task envelopes; the bridge_watcher
classifier escalates most kind=task envelopes since the auto_read_patterns /
auto_ops_verbs whitelist is intentionally narrow, and the push-notif spawn
in the frozen watcher uses bare argv[0]='claude' which subprocess.run cannot
resolve to claude.cmd on Windows).

State files (under ops/runtime/ to match Legion conventions):
    legion_bridge_daemon_health.json  - last poll status, invocation count
    legion_bridge_daemon.lock         - held while claude --print is running

Log: logs/legion_bridge_daemon.log (rotating, 1 MB x 2).

Scheduled task: RC-BridgeDaemon (AtLogOn Highest, restart 3/1min, ETL=0).
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
from logging.handlers import RotatingFileHandler as _RFH
from pathlib import Path

# Config
POLL_IDLE_S  = 30
POLL_WORK_S  = 10
LOCK_STALE_S = 300
TARGET       = "legion"

SCRIPT_DIR   = Path(__file__).resolve().parent              # tools/
PROJECT_ROOT = SCRIPT_DIR.parent                            # C:\Riot Commander\
PULL_SCRIPT  = SCRIPT_DIR / "bridge_pull_tasks.py"
RUNTIME_DIR  = PROJECT_ROOT / "ops" / "runtime"
HEALTH_FILE  = RUNTIME_DIR / "legion_bridge_daemon_health.json"
LOCK_FILE    = RUNTIME_DIR / "legion_bridge_daemon.lock"
LOG_DIR      = PROJECT_ROOT / "logs"
LOG_FILE     = LOG_DIR / "legion_bridge_daemon.log"

# Logging
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
_fmt = logging.Formatter(
    "%(asctime)s [legion-bridge-daemon] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
_root = logging.getLogger()
_root.setLevel(logging.INFO)
_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
_root.addHandler(_ch)
_fh = _RFH(LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
_fh.setFormatter(_fmt)
_root.addHandler(_fh)
_log = logging.getLogger("legion_bridge_daemon")


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
    except Exception:
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
        "status": status,
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
    except Exception as e:
        _log.debug("check failed: %s", e)
        return 0


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
                _log.info("claude already running (lock held) - recheck in %ds",
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
                # Mirror gamepc/peer: inherit env, no manual env.pop here;
                # OAuth login on this machine is what authenticates the CLI.
                # Run from project root so /process-bridge-tasks finds
                # tools/bridge_*.py and CLAUDE.md.
                try:
                    subprocess.run(
                        [claude, "--dangerously-skip-permissions",
                         "-p", "/process-bridge-tasks"],
                        cwd=str(PROJECT_ROOT),
                        timeout=180,
                    )
                except subprocess.TimeoutExpired:
                    _log.warning("claude --print timed out after 180s")
                except Exception as e:
                    _log.error("claude invocation error: %s", e)
                finally:
                    _set_lock(False)
                sleep_s = POLL_WORK_S
        else:
            _write_health("idle", 0, last_task_ts, invocations)
            sleep_s = POLL_IDLE_S

        deadline = time.monotonic() + sleep_s
        while not stopping[0] and time.monotonic() < deadline:
            time.sleep(1)

    _log.info("stopping cleanly")
    _set_lock(False)


if __name__ == "__main__":
    main()

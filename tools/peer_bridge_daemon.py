"""peer_bridge_daemon.py - zero-cost bridge task sentinel for Peer.

Polls Peer's local /api/bridge/messages for unhandled tasks targeted at 'peer'.
Invokes `claude --print "/process-bridge-tasks"` ONLY when count > 0.
Zero API cost when the queue is empty.

Self-contained: no dependency on bridge_pull_tasks.py (uses inline HTTP fetch
compatible with Peer's bare-list response format as well as the RC dict format).

State files (alongside this script, default: <repo>/tools/):
    peer_bridge_daemon_health.json  - last poll status, invocation count
    peer_bridge_daemon.lock         - held while claude --print is running
    peer_bridge_daemon.log          - rotating log (1 MB × 2)

Scheduled / boot setup:
    python3 tools/peer_bridge_daemon.py   # foreground, ctrl-c to stop
    nohup python3 tools/peer_bridge_daemon.py &   # background

    Or add to whatever startup mechanism Peer uses (launchd, systemd, cron @reboot).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import ssl
import subprocess
import sys
import time
import urllib.request
from logging.handlers import RotatingFileHandler as _RFH
from pathlib import Path

# -- Config ----------------------------------------------------------------
POLL_IDLE_S  = 30    # seconds between polls when empty
POLL_WORK_S  = 10    # seconds after a batch completes before re-checking
LOCK_STALE_S = 300   # seconds before a held lock is declared stale
LOOKBACK_S   = 86400 # 24h task horizon
TARGET       = "peer"
# Peer's bridge endpoint (bare-list format, also accepts RC dict format)
BRIDGE_URL   = "https://127.0.0.1:8888/api/bridge/messages"

SCRIPT_DIR    = Path(__file__).resolve().parent
HEALTH_FILE   = SCRIPT_DIR / "peer_bridge_daemon_health.json"
LOCK_FILE     = SCRIPT_DIR / "peer_bridge_daemon.lock"
# Processed-IDs file: mirrors bridge_pull_tasks.py location logic
_local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
PROCESSED_FILE = Path(_local) / "rc-bridge-tasks-processed.txt"

# -- SSL context (skip cert verify - mirrors bridge_pull_tasks.py) ---------
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

# -- Logging ---------------------------------------------------------------
_fmt  = logging.Formatter("%(asctime)s [peer-bridge-daemon] %(levelname)s %(message)s",
                           datefmt="%H:%M:%S")
_root = logging.getLogger()
_root.setLevel(logging.INFO)
_ch   = logging.StreamHandler()
_ch.setFormatter(_fmt)
_root.addHandler(_ch)
_fh   = _RFH(SCRIPT_DIR / "peer_bridge_daemon.log",
              maxBytes=1_000_000, backupCount=2, encoding="utf-8")
_fh.setFormatter(_fmt)
_root.addHandler(_fh)
_log  = logging.getLogger("peer_bridge_daemon")


# -- Helpers ---------------------------------------------------------------

def _resolve_claude() -> str:
    """Find claude CLI binary - checks env override, npm shim, then PATH."""
    override = os.environ.get("ANTHROPIC_CLAUDE_PATH")
    if override and os.path.exists(override):
        return override
    # Windows npm shim
    appdata = os.environ.get("APPDATA", "")
    win_candidates = [
        os.path.join(appdata, "npm", "claude.cmd") if appdata else None,
        os.path.join(appdata, "npm", "claude.exe") if appdata else None,
    ]
    for c in (c for c in win_candidates if c):
        if os.path.isabs(c) and os.path.exists(c):
            return c
    # POSIX / PATH lookup
    for name in ("claude",):
        found = shutil.which(name)
        if found:
            return found
    return "claude"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


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


def _read_processed() -> set:
    try:
        return set(line.strip() for line in PROCESSED_FILE.read_text().splitlines() if line.strip())
    except Exception:
        return set()


def _fetch_messages() -> list:
    """Return all bridge messages from the last LOOKBACK_S seconds."""
    since = time.time() - LOOKBACK_S
    url   = f"{BRIDGE_URL}?since={since:.0f}&limit=200"
    try:
        with urllib.request.urlopen(url, timeout=8, context=_SSL) as resp:
            raw = json.loads(resp.read())
        # Peer returns bare list; RC returns {"messages": [...]} or {"items": [...]}
        if isinstance(raw, list):
            return raw
        return (raw.get("messages") or raw.get("items") or [])
    except Exception as e:
        _log.debug("fetch failed: %s", e)
        return []


def _check_count() -> int:
    """Return count of pending unhandled tasks for TARGET."""
    msgs = _fetch_messages()
    if not msgs:
        return 0
    answered  = {m["in_reply_to"] for m in msgs
                 if m.get("kind") == "result" and m.get("in_reply_to")}
    processed = _read_processed()
    tasks = [
        m for m in msgs
        if m.get("kind") == "task"
        and m.get("target") in {TARGET, "rc"}  # "rc" = Legion label used in some envelopes
        and m.get("id") not in answered
        and m.get("id") not in processed
    ]
    return len(tasks)


# -- Main loop -------------------------------------------------------------

def main() -> None:
    _log.info("starting  pid=%d  target=%s  poll_idle=%ds  bridge=%s",
              os.getpid(), TARGET, POLL_IDLE_S, BRIDGE_URL)
    claude = _resolve_claude()
    _log.info("claude binary: %s", claude)

    invocations  = 0
    last_task_ts = 0.0
    stopping     = [False]

    def _on_signal(*_):
        stopping[0] = True

    signal.signal(signal.SIGTERM, _on_signal)
    if hasattr(signal, "SIGBREAK"):   # Windows only
        signal.signal(signal.SIGBREAK, _on_signal)
    try:
        signal.signal(signal.SIGINT, _on_signal)
    except Exception:
        pass

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
                _log.info("invoking claude --print /process-bridge-tasks  (#%d)",
                          invocations)
                try:
                    # CREATE_NO_WINDOW prevents a conhost window from flashing
                    # on each cadence: claude is a .cmd npm shim on Windows
                    # and a pythonw parent cannot suppress the conhost spawn
                    # via STARTUPINFO alone. Cross-platform safe via the
                    # win32 guard.
                    _flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                    subprocess.run(
                        [claude, "--dangerously-skip-permissions",
                         "-p", "/process-bridge-tasks"],
                        timeout=180,
                        creationflags=_flags,
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

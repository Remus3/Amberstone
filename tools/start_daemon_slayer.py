"""Boot launcher for the Daemon Slayer engine on :8893.

Wrapper around ``agents.daemon_slayer.cli serve`` that pins ``cwd`` to the
project root before importing — scheduled tasks invoke us with whatever
working directory the scheduler hands over (``C:\\Windows\\System32`` for
SYSTEM-context tasks), and ``data_loader`` resolves snapshots relative to
``cwd`` if no ``--data-root`` is given.

Used by the ``RC-DaemonSlayer`` scheduled task. Manual invocation works
too — ``py tools/start_daemon_slayer.py``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import datetime
import logging
import socket
import traceback

from agents.daemon_slayer.server import serve_forever  # noqa: E402

_LOG_FILE = _PROJECT_ROOT / "logs" / "daemon_slayer_startup.log"


def _log_startup(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{ts}  {msg}\n")
    except OSError:
        pass


if __name__ == "__main__":
    # If port is already bound (e.g. task re-triggered while still running),
    # exit 0 so the scheduled task doesn't record a failure.
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 8893))
        s.close()
    except OSError:
        s.close()
        _log_startup("port 8893 already bound — skipping (exit 0)")
        sys.exit(0)

    _log_startup("starting serve_forever()")
    try:
        code = serve_forever()
    except Exception:
        tb = traceback.format_exc()
        _log_startup(f"UNHANDLED EXCEPTION (exit 1):\n{tb}")
        sys.exit(1)
    _log_startup(f"serve_forever() returned {code}")
    sys.exit(code)

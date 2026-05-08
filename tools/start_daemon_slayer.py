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

from agents.daemon_slayer.server import serve_forever  # noqa: E402


if __name__ == "__main__":
    import socket
    # If port is already bound (e.g. task re-triggered while still running),
    # exit 0 so the scheduled task doesn't record a failure.
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 8893))
        s.close()
    except OSError:
        s.close()
        sys.exit(0)
    sys.exit(serve_forever())

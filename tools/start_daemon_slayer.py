"""Boot launcher for the Daemon Slayer engine on :8860.

Wrapper around ``agents.daemon_slayer.cli serve`` that pins ``cwd`` to the
project root before importing - scheduled tasks invoke us with whatever
working directory the scheduler hands over (``C:\\Windows\\System32`` for
SYSTEM-context tasks), and ``data_loader`` resolves snapshots relative to
``cwd`` if no ``--data-root`` is given.

Used by the ``RC-DaemonSlayer`` scheduled task. Manual invocation works
too - ``$env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/start_daemon_slayer.py``.
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
# The RC-DaemonSlayer scheduled task runs as SYSTEM; appends under
# _PROJECT_ROOT can fail there, and the launcher is invoked via pythonw.exe
# (no console) so sys.stderr may be unusable too. ProgramData is always
# SYSTEM-writable - fall back to it so a boot-time failure still leaves a
# trace instead of vanishing into a swallowed OSError.
_FALLBACK_LOG_FILE = (
    Path(os.environ.get("ProgramData") or r"C:\ProgramData")
    / "Amberstone" / "daemon_slayer_startup.log"
)


def _write_log_line(target: Path, line: str) -> bool:
    """Append one line to ``target``. True on success, False on OSError."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(line)
        return True
    except OSError:
        return False


def _log_startup(msg: str) -> Path | None:
    """Append a timestamped startup line; return the Path written, or None.

    Tries the canonical logs/ file, then the SYSTEM-writable ProgramData
    fallback, and always echoes to stderr (best-effort). Never raises:
    boot-time traceability must not itself crash the launcher.
    """
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}  {msg}\n"
    written: Path | None = None
    for target in (_LOG_FILE, _FALLBACK_LOG_FILE):
        if _write_log_line(target, line):
            written = target
            break
    try:
        sys.stderr.write(line)
        sys.stderr.flush()
    except Exception:
        pass
    return written


if __name__ == "__main__":
    # If port is already bound (e.g. task re-triggered while still running),
    # exit 0 so the scheduled task doesn't record a failure.
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 8860))
        s.close()
    except OSError:
        s.close()
        _log_startup("port 8860 already bound - skipping (exit 0)")
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

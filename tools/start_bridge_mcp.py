"""Boot launcher for the local cross-Claude bridge MCP server on :8895.

Wrapper around ``tools.bridge_mcp_server.serve_forever`` that pins
``cwd`` to the project root before importing - scheduled tasks invoke us
with whatever working directory the scheduler hands over
(``C:\\Windows\\System32`` for SYSTEM-context tasks), and the server's
ops/runtime/bridge_inbox_pending.json lookup resolves relative to the
project root.

Used by the ``RC-Bridge-MCP`` scheduled task. Manual invocation works
too - ``C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/start_bridge_mcp.py``. Mirrors
tools/start_ds_matchdb_mcp.py (same logging + port-preflight contract).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

os.chdir(_PROJECT_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import datetime  # noqa: E402
import socket  # noqa: E402
import traceback  # noqa: E402

from tools.bridge_mcp_server import serve_forever  # noqa: E402

_LOG_FILE = _PROJECT_ROOT / "logs" / "bridge_mcp_startup.log"
_FALLBACK_LOG_FILE = (
    Path(os.environ.get("ProgramData") or r"C:\ProgramData")
    / "RiotCommander" / "bridge_mcp_startup.log"
)


def _write_log_line(target: Path, line: str) -> bool:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(line)
        return True
    except OSError:
        return False


def _log_startup(msg: str) -> Path | None:
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
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 8895))
        s.close()
    except OSError:
        s.close()
        _log_startup("port 8895 already bound - skipping (exit 0)")
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

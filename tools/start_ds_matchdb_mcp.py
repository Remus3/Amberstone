"""Boot launcher for the local DS + match-DB MCP server on :8861.

Wrapper around ``tools.ds_matchdb_mcp_server.serve_forever`` that pins
``cwd`` to the project root before importing - scheduled tasks invoke us
with whatever working directory the scheduler hands over
(``C:\\Windows\\System32`` for SYSTEM-context tasks), and the server's
core.* imports + match_history.db lookup resolve relative to the project
root.

Used by the ``RC-DS-MatchDB-MCP`` scheduled task. Manual invocation works
too - ``$env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/start_ds_matchdb_mcp.py``. Mirrors
tools/start_daemon_slayer.py (same logging + port-preflight contract).

Port preflight (session 129): a start that finds :8861 bound WAITS for the
holder to let go (``core/port_handoff.py``) and exits 0 only when a live
ds-matchdb-mcp instance still holds it after the window. Measured: after
``schtasks /End`` the old process lingered, the immediate ``/Run`` skipped
on "already bound", then the old pid died and nothing listened on :8861.
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
import traceback  # noqa: E402
from typing import Callable, Optional  # noqa: E402

from core.port_handoff import (  # noqa: E402
    LIVE,
    POLL_S,
    STUCK,
    WINDOW_S,
    await_port,
)
from tools.ds_matchdb_mcp_server import (  # noqa: E402
    HOST,
    PORT,
    holder_is_matchdb,
    serve_forever,
)

_LOG_FILE = _PROJECT_ROOT / "logs" / "ds_matchdb_mcp_startup.log"
# The scheduled task may run as SYSTEM; appends under _PROJECT_ROOT can
# fail there, and pythonw.exe (no console) makes sys.stderr unusable too.
# ProgramData is always SYSTEM-writable - fall back to it so a boot-time
# failure still leaves a trace instead of vanishing into a swallowed OSError.
_FALLBACK_LOG_FILE = (
    Path(os.environ.get("ProgramData") or r"C:\ProgramData")
    / "Amberstone" / "ds_matchdb_mcp_startup.log"
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
    except Exception:  # noqa: BLE001
        pass
    return written


def main(*, host: str = HOST, port: int = PORT,
         serve: Callable[..., int] = serve_forever,
         log: Optional[Callable[[str], object]] = None,
         window_s: float = WINDOW_S, poll_s: float = POLL_S,
         holder_live: Optional[Callable[[], bool]] = None) -> int:
    """Start the server unless a LIVE instance already serves ``port``.

    A held port is waited out (up to ``window_s``), never skipped on sight:
    exit 0 only when a live ds-matchdb-mcp instance still holds it after the
    window, exit 1 when something else holds it (nothing was started).
    """
    log = log or _log_startup
    live = holder_live or (lambda: holder_is_matchdb(host, port))
    h = await_port(host, port, holder_live=live, window_s=window_s, poll_s=poll_s)
    if h.state == LIVE:
        log(f"port {port} already bound by a live ds-matchdb-mcp instance "
            f"(checked after {h.waited_s:.0f}s) - skipping (exit 0)")
        return 0
    if h.state == STUCK:
        log(f"port {port} still bound after {h.waited_s:.0f}s and the holder "
            f"does not answer as ds-matchdb-mcp - not started (exit 1)")
        return 1
    if h.waited_s >= poll_s:
        log(f"port {port} was bound; its holder released it after "
            f"{h.waited_s:.1f}s")
    log("starting serve_forever()")
    try:
        code = serve(host=host, port=port)
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        log(f"UNHANDLED EXCEPTION (exit 1):\n{tb}")
        return 1
    log(f"serve_forever() returned {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())

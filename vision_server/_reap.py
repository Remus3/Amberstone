# arch: reap stale/orphaned :8889 vision-server instances before bind | section=vision | frozen=no
"""Reap orphaned vision-server processes before a fresh instance binds :8889.

Root cause (2026-07-05, project_liveclient_loopback_regression): dashboard/
server.py self-heals the vision server by spawning moon_vision_server.py
whenever :8889 does not answer a connect() probe, and vision_server.main binds
a ThreadingHTTPServer with allow_reuse_address=True (SO_REUSEADDR). On Windows
SO_REUSEADDR lets a fresh instance CO-BIND :8889 alongside a still-running
predecessor instead of failing, and across RC restarts the old child is never
killed (the parent exits, the child keeps running + keeps the bind). Orphaned
instances accumulate; with several sockets co-bound to 0.0.0.0:8889 the OS
delivers connections ambiguously and every connect() is REFUSED (~2s), which
blanks /api/state.lcu, the overlay 10-player roster + the vision frames.

Fix: before a fresh instance binds, kill any OTHER vision-server processes.
They are stale by construction - main() only reaches this path because :8889
was not answering, so no functioning server is being served by them. The sweep
is dependency-injectable for tests and a safe no-op when psutil is unavailable;
it must never raise (it is protecting the server it runs inside of).

Note: the sibling Daemon Slayer launcher (tools/start_daemon_slayer.py) is NOT
affected - it guards with a real bind() probe (no SO_REUSEADDR), so a held
:8860 makes the fresh bind fail and it exits cleanly instead of co-binding.
"""
from __future__ import annotations

import os

from ._config import PORT, log

# Command-line substrings that identify a vision-server process: the file-path
# launch dashboard/server.py uses, and the `python -m vision_server` module form.
_MARKERS = ("moon_vision_server", "-m vision_server")


def _enumerate_processes():
    """Yield ``(pid, cmdline_str)`` for every process. psutil-backed; yields
    nothing when psutil is unavailable so the reap degrades to a safe no-op."""
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            yield proc.info["pid"], " ".join(proc.info.get("cmdline") or [])
        except Exception:  # noqa: BLE001
            continue


def _default_kill(pid: int) -> None:
    import psutil

    psutil.Process(pid).kill()


def find_stale_vision_pids(exclude_pid, procs=None):
    """Return the PIDs of OTHER vision-server processes, excluding
    ``exclude_pid``. ``procs`` is an iterable of ``(pid, cmdline_str)`` and is
    enumerated live (via psutil) when None."""
    if procs is None:
        procs = _enumerate_processes()
    stale = []
    for pid, cmdline in procs:
        if pid == exclude_pid:
            continue
        if any(marker in cmdline for marker in _MARKERS):
            stale.append(pid)
    return stale


def reap_stale_vision_instances(exclude_pid=None, procs=None, killer=None):
    """Kill stale/orphaned vision-server processes so a fresh instance can bind
    :8889 cleanly. Returns the list of PIDs actually reaped. Best-effort: a
    kill that raises is logged and skipped, never aborting the sweep, and the
    whole call is a no-op when no other instances exist."""
    if exclude_pid is None:
        exclude_pid = os.getpid()
    if killer is None:
        killer = _default_kill
    reaped = []
    for pid in find_stale_vision_pids(exclude_pid, procs):
        try:
            killer(pid)
            reaped.append(pid)
            log.warning("reaped stale vision-server pid %d (was co-binding :%d)", pid, PORT)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not reap vision-server pid %d: %s", pid, exc)
    return reaped

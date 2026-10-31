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
was not answering, so no functioning server is being served by them.

What counts as a vision server (s144 true-audit cycle 75). The test used to be
a substring match over the space-joined command line, which killed anything
that merely MENTIONED the name - an editor with the file open, a grep for it,
a tool handed the path as an argument, a shell running a launch string, and
every `python -m vision_server_<x>`. It is now structural, over the argv list
(`is_vision_server_argv`): argv[0] is a Python interpreter, and its first
non-option argument is a script named moon_vision_server.py / .pyw, or its
module option is exactly `-m vision_server`. The file form is the real launch
(dashboard/_vision_watchdog.spawn_vision runs [sys.executable, <app>/
moon_vision_server.py]). The module form is matched for safety only: the
package has no __main__.py today, so `-m vision_server` cannot start a server.
The `py.exe` launcher is deliberately NOT matched: it only waits on a real
interpreter child, which is matched and reaped itself. The predicate lives in
core/vision_server_argv.py (s144 true-audit cycle 76), shared with the RC
watchdog's taskkill check, so the two killers cannot drift apart again.

Three more guards. The new server's own ANCESTORS are never reaped: a venv
redirector re-executes the interpreter with the same command line, and the
Windows launchers hold their child in a kill-on-close job, so killing the
parent would take this server down with it. The kill goes through the psutil
handle that did the enumerating, never a fresh Process(pid), so psutil's
pid-reuse check can refuse a pid recycled between the scan and the kill. And
the sweep never raises - not for a failed kill, a malformed entry, a failed
ancestor lookup or a process table that errors mid-iteration - because an
exception here kills main() before the bind, under pythonw with the traceback
going nowhere. A missing psutil disables the reap with a WARNING, not
silently.

Everything is dependency-injectable for tests: `procs` entries are
``(pid, argv)`` or ``(pid, argv, handle)`` where `handle` has ``.kill()``.

Note: the sibling Daemon Slayer launcher (tools/start_daemon_slayer.py) is NOT
affected - it guards with a real bind() probe (no SO_REUSEADDR), so it never
co-binds a held :8860: it waits for the holder to release the port
(core/port_handoff.await_port, session 129), exits 0 if a live DS still holds
it after the window and exits 1 for any other holder.
"""
from __future__ import annotations

import os

from core.vision_server_argv import is_vision_server_argv

from ._config import PORT, log


def _enumerate_processes():
    """Yield ``(pid, argv_list, handle)`` for every process. psutil-backed;
    yields nothing (with a WARNING) when psutil is unavailable, so the reap
    degrades to a visible no-op."""
    try:
        import psutil
    except ImportError:
        log.warning("psutil unavailable - stale vision-server reap skipped")
        return
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            yield proc.info["pid"], list(proc.info.get("cmdline") or []), proc
        except Exception:  # noqa: BLE001 - one unreadable row never ends the scan
            continue


def _ancestor_pids(pid: int) -> set:
    """PIDs of every ancestor of `pid` (empty set if unknown). Never raises."""
    try:
        import psutil
        return {p.pid for p in psutil.Process(pid).parents()}
    except Exception:  # noqa: BLE001 - psutil missing, pid gone, access denied
        return set()


def _default_kill(pid: int) -> None:
    """Kill by pid. Only for an injected `procs` entry that carries no handle;
    the live path always kills through the enumerating handle instead."""
    import psutil

    psutil.Process(pid).kill()


def _scan(exclude_pid, procs, ancestors):
    """Return ``[(pid, handle_or_None)]`` for stale vision servers. Never raises."""
    if procs is None:
        procs = _enumerate_processes()
    if ancestors is None:
        try:
            ancestors = _ancestor_pids(exclude_pid)
        except Exception as exc:  # noqa: BLE001 - an injected/broken lookup
            log.warning("vision-server reap: ancestor lookup failed: %s", exc)
            ancestors = ()
    try:
        skip = {p for p in ancestors if isinstance(p, int)}
    except Exception as exc:  # noqa: BLE001 - an injected non-iterable / raising ancestors
        log.warning("vision-server reap: bad ancestors ignored: %s", exc)
        skip = set()
    stale = []
    try:
        for entry in procs:
            try:
                pid, argv = entry[0], entry[1]
                handle = entry[2] if len(entry) > 2 else None
            except Exception:  # noqa: BLE001 - one malformed entry never ends the scan
                continue
            if not isinstance(pid, int) or pid == exclude_pid or pid in skip:
                continue
            if is_vision_server_argv(argv):
                stale.append((pid, handle))
    except Exception as exc:  # noqa: BLE001 - must never raise (module contract)
        log.warning("vision-server reap: process enumeration failed after %d "
                    "match(es): %s", len(stale), exc)
    return stale


def find_stale_vision_pids(exclude_pid, procs=None, ancestors=None):
    """Return the PIDs of OTHER vision-server processes, excluding
    ``exclude_pid`` and its ancestors. ``procs`` is an iterable of
    ``(pid, argv)`` / ``(pid, argv, handle)`` and is enumerated live (via
    psutil) when None; ``ancestors`` is looked up live when None."""
    return [pid for pid, _h in _scan(exclude_pid, procs, ancestors)]


def reap_stale_vision_instances(exclude_pid=None, procs=None, killer=None,
                                ancestors=None):
    """Kill stale/orphaned vision-server processes so a fresh instance can bind
    :8889 cleanly. Returns the list of PIDs actually reaped. Best-effort: a
    kill that raises is logged and skipped, never aborting the sweep, and the
    whole call is a no-op when no other instances exist. An injected `killer`
    receives the pid; otherwise the enumerated handle's ``.kill()`` is used."""
    if exclude_pid is None:
        exclude_pid = os.getpid()
    reaped = []
    for pid, handle in _scan(exclude_pid, procs, ancestors):
        try:
            if killer is not None:
                killer(pid)
            elif handle is not None:
                handle.kill()
            else:
                _default_kill(pid)
            reaped.append(pid)
            log.warning("reaped stale vision-server pid %d (was co-binding :%d)", pid, PORT)
        except Exception as exc:  # noqa: BLE001 - best-effort, never abort the sweep
            log.warning("could not reap vision-server pid %d: %s", pid, exc)
    return reaped

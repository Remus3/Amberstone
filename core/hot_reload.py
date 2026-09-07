"""Hot-reload watchdog: watch non-frozen .py files and auto-trigger restart.

Runs a background thread that polls file mtimes. On change to a non-frozen
.py file, validates with py_compile then writes restart_trigger.txt so the
supervisor triggers a reload (~5s). Eliminates the manual "write restart_trigger"
step from 74% of sessions.

Frozen files (per CLAUDE.md) are never watched: main.py, core/log_setup.py,
core/moon_proxy.py, lcu/lcu_client.py, core/game_snapshot.py,
ops/rc_dev_runtime.py, ops/rc_supervisor.py, app/__init__.py, app/_loop.py,
app/_health_monitor.py, app/_remediation.py, app/_state_authority.py,
app/_overlay_manager.py, app/_game_lifecycle.py, tools/diagnose.md,
tools/caveman.md.

Usage (in app bootstrap)::

    from core.hot_reload import start_watcher
    start_watcher(project_root=Path("C:/Riot Commander"))

Signals:
  - HALT: write anything to ops/runtime/hot_reload_halt.txt to stop the watcher.
  - Status: ops/runtime/hot_reload.json has {watching, last_change, last_compile}.

Caveats:
  - Polling interval is 2s (not inotify - cross-platform).
  - The watcher writes restart_trigger.txt; the supervisor handles the actual
    process restart. The ~5s latency of process restart is inherent to
    pythonw.exe + supervisor cycle.
  - py_compile errors are logged but do NOT block the restart trigger - the
    model sees py_compile failures via pytest_guard.py already. If py_compile
    fails, restart_trigger is NOT written (avoid silent crash).
"""

from __future__ import annotations

import json
import os
import py_compile
import threading
import time
from pathlib import Path

# Frozen files (CLAUDE.md hard rule) - absolute repo-relative paths.
_FROZEN_PATHS: set[str] = {
    # Use as_posix() so paths are always forward-slash on every platform.
    # _is_frozen() normalizes its input the same way.
    Path("main.py").as_posix(),
    Path("core/log_setup.py").as_posix(),
    Path("core/moon_proxy.py").as_posix(),
    Path("lcu/lcu_client.py").as_posix(),
    Path("core/game_snapshot.py").as_posix(),
    Path("ops/rc_dev_runtime.py").as_posix(),
    Path("ops/rc_supervisor.py").as_posix(),
    Path("app/__init__.py").as_posix(),
    Path("app/_loop.py").as_posix(),
    Path("app/_health_monitor.py").as_posix(),
    Path("app/_remediation.py").as_posix(),
    Path("app/_state_authority.py").as_posix(),
    Path("app/_overlay_manager.py").as_posix(),
    Path("app/_game_lifecycle.py").as_posix(),
}

# Directories excluded from watching.
_SKIP_DIRS: tuple[str, ...] = (
    ".git",
    "__pycache__",
    "logs",
    "docs/_archive",
    "data",  # JSON data, not code
    "web",  # JS/CSS hot-reloaded separately by Electron
    "node_modules",
)

# Derived from _SKIP_DIRS (which stays the single source of truth) so the
# segment test below is a cheap membership check for the common single-segment
# case and an explicit run-match for the multi-segment ones.
_SKIP_SEGMENTS: frozenset[str] = frozenset(
    s for s in _SKIP_DIRS if "/" not in s
)
_SKIP_RUNS: tuple[tuple[str, ...], ...] = tuple(
    tuple(s.split("/")) for s in _SKIP_DIRS if "/" in s
)

# Directories we DO watch (only these subtrees contain editable .py).
_WATCH_DIRS: tuple[str, ...] = (
    "agents",
    "core",
    "dashboard",
    "ops",
    "tests",
    "tools",
    "",
)


def _is_frozen(rel: str) -> bool:
    """True if the path is a frozen file (CLAUDE.md hard rule)."""
    return rel.replace("\\", "/") in _FROZEN_PATHS


def _is_skipped(rel: str) -> bool:
    """True if any _SKIP_DIRS entry matches a DIRECTORY segment of the path.

    Matching is anchored to path-segment boundaries, never a raw substring of
    the whole path. An unanchored `entry in rel` test also drops any file
    whose path merely CONTAINS a token - measured on this tree, that silently
    excluded 23 live non-frozen .py files (core/data_retention.py,
    core/coaching_data_lock.py, tools/web_ascii_sweep.py, and web_dashboard.py
    itself, the module that starts this watcher), which defeats the whole
    point of the watchdog.

    Two rules follow from a skip entry naming a DIRECTORY:
      - The basename is not part of the comparison window, so a file called
        web_dashboard.py is not "in a web directory".
      - A partial segment does not count: "data" must not match "database".

    Multi-segment entries (e.g. "docs/_archive") match a consecutive run of
    directory segments at any depth.
    """
    dirs = rel.replace("\\", "/").split("/")[:-1]  # drop the basename
    if _SKIP_SEGMENTS.intersection(dirs):
        return True
    for run in _SKIP_RUNS:
        n = len(run)
        for i in range(len(dirs) - n + 1):
            if tuple(dirs[i:i + n]) == run:
                return True
    return False


def _should_watch(rel: str) -> bool:
    """True if this .py file should be watched for changes."""
    r = rel.replace("\\", "/")
    if _is_skipped(r):
        return False
    if _is_frozen(r):
        return False
    if not r.endswith(".py"):
        return False
    # Only watch files in the approved subtrees.
    for wd in _WATCH_DIRS:
        if r == wd or r.startswith(wd + "/") or (wd == "" and "/" not in r):
            return True
    return False


def _scan_py_files(root: Path) -> dict[str, float]:
    """Walk watch dirs and return {rel_path: mtime} for all .py files."""
    files: dict[str, float] = {}
    for wd in _WATCH_DIRS:
        d = root / wd if wd else root
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
            rel = p.relative_to(root).as_posix()
            if _should_watch(rel):
                try:
                    files[rel] = p.stat().st_mtime
                except OSError:
                    pass
    return files


def _write_json(path: Path, data: dict) -> None:
    """Atomic write a JSON status file."""
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def _watch_loop(root: Path, halt_path: Path, status_path: Path) -> None:
    """Background thread: poll mtimes, trigger restart on change."""
    trigger = root / "restart_trigger.txt"
    # Initial scan - do NOT trigger on first pass.
    try:
        known = _scan_py_files(root)
    except OSError:
        known = {}

    _write_json(status_path, {
        "watching": True,
        "last_change": None,
        "last_compile": None,
        "file_count": len(known),
    })

    while True:
        time.sleep(2.0)

        # HALT check.
        if halt_path.exists():
            _write_json(status_path, {
                "watching": False,
                "reason": "halt file detected",
            })
            return

        try:
            current = _scan_py_files(root)
        except OSError:
            continue

        changed: list[str] = []
        for rel, mtime in current.items():
            prev = known.get(rel, 0)
            if mtime > prev + 0.5:  # 0.5s buffer for write latency
                changed.append(rel)

        if not changed:
            known = current
            continue

        # Compile-check changed files first.
        compile_ok = True
        for rel in changed:
            path = root / rel
            try:
                py_compile.compile(str(path), doraise=True)
            except (py_compile.PyCompileError, OSError) as exc:
                compile_ok = False
                msg = str(exc).splitlines()[0][:160]
                _write_json(status_path, {
                    "watching": True,
                    "last_change": rel,
                    "last_compile": f"FAILED: {msg}",
                    "file_count": len(known),
                })
                break

        if not compile_ok:
            # py_compile failed - do NOT write restart_trigger
            # (silent crash risk under pythonw.exe, CLAUDE.md hard rule).
            known = current
            continue

        # All changed files compile clean -> trigger restart.
        try:
            ttmp = trigger.with_suffix(".tmp")
            ttmp.write_text("auto-hot-reload", encoding="utf-8")
            os.replace(ttmp, trigger)
        except OSError:
            pass

        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        _write_json(status_path, {
            "watching": True,
            "last_change": ts,
            "last_compile": f"OK ({len(changed)} file(s))",
            "changed": changed,
            "file_count": len(current),
        })

        known = current


def start_watcher(project_root: Path) -> threading.Thread:
    """Start the hot-reload watchdog in a background daemon thread.

    Returns the thread (already started). The caller does not need to join -
    it's a daemon thread that dies with the process.
    """
    halt = project_root / "ops" / "runtime" / "hot_reload_halt.txt"
    status = project_root / "ops" / "runtime" / "hot_reload.json"
    status.parent.mkdir(parents=True, exist_ok=True)

    t = threading.Thread(
        target=_watch_loop,
        args=(project_root, halt, status),
        daemon=True,
        name="hot-reload-watcher",
    )
    t.start()
    return t

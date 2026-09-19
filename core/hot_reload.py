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
  - Polling interval is 2s (not inotify - cross-platform). Each poll is a
    PRUNING os.scandir walk of the watch dirs - a skipped directory is never
    entered, the repo root is listed non-recursively, and the mtime comes
    from the DirEntry so no per-file stat is issued. The pre-2026-09-19 scan
    used pathlib.rglob from the root, which enumerates EVERY directory before
    the filter runs: measured live, that descended .claude/worktrees (~197k
    files) and ops/runtime/responder_export (~14k files) every 2s and drove
    ~37,000 filesystem metadata ops/sec from the idle RC process. The first
    fix (os.walk, same day) pruned the descent but still re-statted every
    accepted file after the listing - ~5,858 ops/sec at idle.
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

# Directories excluded from watching. The scanner PRUNES these - it never
# descends into them - so an entry here is also a promise about I/O cost.
# `git ls-files .claude ops/runtime moon_sync_inbox` returned zero tracked
# files on 2026-09-19, so the three gitignored entries cannot hide a real
# module.
_SKIP_DIRS: tuple[str, ...] = (
    ".git",
    "__pycache__",
    "logs",
    "docs/_archive",
    "data",  # JSON data, not code
    "web",  # JS/CSS hot-reloaded separately by Electron
    "node_modules",
    # Gitignored runtime state, including responder_export/<sha12>/ which
    # are full copies of the repo - their .py must never trigger a restart.
    "ops/runtime",
    # Harness scratch: .claude/worktrees/agent-* checkouts are not runtime.
    ".claude",
    # Gitignored cross-repo inbox (see CLAUDE.md, cross-repo channel).
    "moon_sync_inbox",
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

# Directories we DO watch (only these subtrees contain editable .py). The
# "" entry is the repo root and means ROOT-LEVEL FILES ONLY (e.g.
# web_dashboard.py): it is listed non-recursively, never walked.
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
    return _dirs_match_skip(dirs)


def _is_skipped_dir(rel_dir: str) -> bool:
    """True if a DIRECTORY path (repo-relative) is excluded by _SKIP_DIRS.

    Same segment-anchored semantics as _is_skipped, but every segment is a
    directory segment (there is no basename to drop). This is the prune
    predicate: _scan_py_files never descends into a directory for which it
    returns True.
    """
    return _dirs_match_skip(rel_dir.replace("\\", "/").split("/"))


def _dirs_match_skip(dirs: list[str]) -> bool:
    """Shared segment test behind _is_skipped and _is_skipped_dir."""
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
    """Walk watch dirs and return {rel_path: mtime} for all .py files.

    Scoping AND cost, not filtering. Two properties, each pinned by a test:

      - The walk PRUNES. A directory matching _SKIP_DIRS is never pushed,
        so it is never entered, and the root ("") is a single non-recursive
        listing that accepts root-level files only. Every allowed directory
        is enumerated exactly once per scan (one os.scandir each).
      - The walk issues NO per-file stat. os.scandir already returns a
        DirEntry per name, and entry.stat(follow_symlinks=False) reads the
        mtime that the directory listing carried (Windows: free; POSIX: one
        C-level lstat, never the Python-level os.stat). The round-1 walker
        used os.walk, which threw the DirEntry away, and then re-statted
        every accepted file - 2,331 extra stats per 2s poll on the live
        tree, ~5,858 metadata ops/sec at idle.

    Which top-level watch dirs exist is read off the root listing rather
    than probed with is_dir(): a missing watch dir then costs nothing, and
    on Linux os.path.isdir would itself be an os.stat call.

    _should_watch / _is_frozen remain the acceptance filter for FILES;
    _is_skipped_dir is the prune predicate for DIRECTORIES.
    """
    files: dict[str, float] = {}
    subtrees = frozenset(wd for wd in _WATCH_DIRS if wd)
    # Stack of (absolute path, repo-relative posix path) still to list.
    stack: list[tuple[str, str]] = []

    # Root: accept root-level *.py, and seed the stack with the watch
    # subtrees that actually exist. Never recurse from the repo root.
    try:
        with os.scandir(root) as it:
            for entry in it:
                name = entry.name
                if entry.is_dir(follow_symlinks=False):
                    if name in subtrees and not _is_skipped_dir(name):
                        stack.append((entry.path, name))
                elif (
                    name.endswith(".py")
                    and entry.is_file(follow_symlinks=False)
                    and _should_watch(name)
                ):
                    try:
                        files[name] = entry.stat(follow_symlinks=False).st_mtime
                    except OSError:
                        pass
    except OSError:
        return files

    while stack:
        dirpath, rel_dir = stack.pop()
        try:
            with os.scandir(dirpath) as it:
                for entry in it:
                    rel = f"{rel_dir}/{entry.name}"
                    if entry.is_dir(follow_symlinks=False):
                        # Prune: a skipped directory is never pushed.
                        if not _is_skipped_dir(rel):
                            stack.append((entry.path, rel))
                    elif (
                        rel.endswith(".py")
                        and entry.is_file(follow_symlinks=False)
                        and _should_watch(rel)
                    ):
                        try:
                            files[rel] = entry.stat(
                                follow_symlinks=False
                            ).st_mtime
                        except OSError:
                            pass
        except OSError:
            # A directory that vanished between push and list, or one we
            # cannot read: skip it, same as os.walk's default onerror.
            continue
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

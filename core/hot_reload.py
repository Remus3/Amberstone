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
    start_watcher(project_root=Path(__file__).resolve().parent)

Signals:
  - HALT: write anything to ops/runtime/hot_reload_halt.txt to stop the watcher.
  - Status: ops/runtime/hot_reload.json has {watching, last_change, last_compile,
    pending, deferred_reason, deferred_since}.
  - Trail: every trigger, every deferral and every compile refusal is ONE
    INFO/WARNING line on logger "rc.hot_reload" (logs/YYYY-MM-DD.log) naming
    the changed files. hot_reload.json is rewritten at startup, so the log is
    the only record that survives the restart a trigger causes.

Scope (s134). Session 134 measured 18 RC restarts during ONE TFT match
(ops/runtime/tft_qa/RESTART_DIAG.md); each restart drops live TFT state.
Every one came from an edit to a file the RC process never imports: tests/*,
agents/agent1_lead/*, agents/agent3_testing/* and the gitignored lane driver
files under ops/loop/control/. Two rules close it:
  - WATCH ONLY WHAT RC LOADED. A changed file restarts RC only when its path
    is the __file__ of a module in this process's sys.modules (the watcher
    runs inside the RC process: main.py imports web_dashboard, which starts
    it). A module RC has not loaded cannot be stale in RC, so a new file, a
    test, a Phase-3 agent module or a Daemon Slayer module that only the
    separate :8860 process loads never restarts RC. tests/ (at any depth) and
    ops/loop/control/ are also excluded by PATH, so even a process that did
    load them (pytest) never treats them as candidates. Tracked ops/loop
    modules stay candidates: dashboard/routes_loop_status.py and
    routes_loop_control.py importlib-load ops.loop.lanes / lane_launcher /
    steer / interrupt at call time, so RC can hold them.
  - DEFER WHILE A GAME IS LIVE. When a loaded file changes while a League or
    TFT game is running (a game process - League of Legends.exe or
    TFTClient-Win64-Shipping.exe - is alive, checked at most every
    PROCESS_CACHE_S; or the RC-LCUAgent snapshot reports a gameflow phase in
    IN_GAME_PHASES), the restart is held as PENDING and fired once, when
    both signals say the game is over. The game check runs only while a
    restart is pending, never on an idle tick.
  - Daemon Slayer :8860 is unchanged: it is its own scheduled-task process
    (RC-DaemonSlayer) and this watcher never restarted it; an RC restart
    never touched it either (core/daemon_slayer_client.ensure_running is a
    no-op while :8860 answers). DS modules RC imports in-process still
    restart RC when edited, exactly as before.

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
import logging
import os
import py_compile
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from core.polled_json import atomic_write_text

_log = logging.getLogger("rc.hot_reload")

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
    # s134: test trees at ANY depth (tests/, agents/daemon_slayer/tests/,
    # tools/tests/). The RC process never imports one; 9 of the 18 in-match
    # restarts in RESTART_DIAG.md were edits under tests/.
    "tests",
    # s134: gitignored lane prompts, lane drivers and loop control state.
    # Never imported by RC; 9 of the 18 in-match restarts were edits to
    # ops/loop/control/lane_prompts/s134_lane_*.py.
    "ops/loop/control",
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

# Directories we DO scan for candidates (a SUPERSET of what can restart RC:
# a candidate restarts RC only if RC has loaded it, see _loaded_repo_files).
# The "" entry is the repo root and means ROOT-LEVEL FILES ONLY (e.g.
# web_dashboard.py): it is listed non-recursively, never walked. "tests" left
# this list in s134 - RC never imports a test module.
_WATCH_DIRS: tuple[str, ...] = (
    "agents",
    "core",
    "dashboard",
    "ops",
    "tools",
    "",
)

# s134 game deferral. Lower-case process image names of a running League or
# TFT game (NOT the League client, LeagueClientUx.exe, which is up between
# games too).
GAME_PROCESS_NAMES: frozenset[str] = frozenset({
    "league of legends.exe",
    "tftclient-win64-shipping.exe",
})
# LCU gameflow phases during which a game is loading or running. GameStart
# (loading screen) and Reconnect (game up, client reconnecting) drop live
# state on a restart exactly like InProgress does.
IN_GAME_PHASES: frozenset[str] = frozenset({
    "GameStart",
    "InProgress",
    "Reconnect",
})
# The process scan is the expensive signal (one psutil.process_iter); its
# answer is reused for this many seconds.
PROCESS_CACHE_S = 10.0
# Paths named per log line before the rest are summarised as "(+N more)".
_LOG_PATH_CAP = 40

# Windows paths compare case-insensitively; the scan keys keep on-disk case
# and a module __file__ may not, so membership is tested on a folded key.
if os.name == "nt":
    def _fold(rel: str) -> str:
        return rel.lower()
else:
    def _fold(rel: str) -> str:
        return rel


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
    try:
        atomic_write_text(path, json.dumps(data, indent=2))
    except OSError:
        pass


def _loaded_repo_files(
    root: Path, modules: Optional[Mapping[str, object]] = None,
) -> frozenset[str]:
    """Repo-relative posix paths of the .py files behind loaded modules.

    ``modules`` defaults to this process's ``sys.modules``. A module counts
    when its ``__file__`` is a ``.py`` path inside ``root`` (anchored on a
    path-separator boundary, so a sibling directory whose name merely starts
    with the root's name does not match). Namespace packages, built-ins,
    extension modules and sourceless ``.pyc`` loads carry no ``.py`` file and
    are skipped.

    ``dict(sys.modules)`` is one C-level copy under the GIL; an importing
    thread that resizes the dict mid-copy (free-threaded builds) is retried.
    Raises RuntimeError only if three copies in a row fail - the watcher then
    keeps its last good answer.
    """
    src = sys.modules if modules is None else modules
    values: Optional[list] = None
    for _ in range(3):
        try:
            values = list(dict(src).values())
            break
        except RuntimeError:
            continue
    if values is None:
        raise RuntimeError("sys.modules changed size during three copies")
    base = os.path.abspath(str(root))
    prefix = os.path.normcase(os.path.join(base, ""))
    cut = len(prefix)
    out: set[str] = set()
    for mod in values:
        try:
            f = getattr(mod, "__file__", None)
        except Exception:  # noqa: BLE001 - a lazy module's __getattr__
            continue
        if not isinstance(f, str) or not f.endswith(".py"):
            continue
        p = os.path.abspath(f)
        if os.path.normcase(p).startswith(prefix):
            out.add(p[cut:].replace("\\", "/"))
    return frozenset(out)


def _default_process_names() -> frozenset[str]:
    """Lower-case image names of every running process (psutil, pinned).

    No psutil -> an empty set: the process signal is then silent and the
    LCU phase alone decides.
    """
    try:
        import psutil
    except ImportError:
        return frozenset()
    names: set[str] = set()
    for proc in psutil.process_iter(["name"]):
        try:
            n = proc.info.get("name")
        except Exception:  # noqa: BLE001 - a process that exited mid-scan
            continue
        if isinstance(n, str) and n:
            names.add(n.lower())
    return frozenset(names)


def _default_lcu_phase() -> Optional[str]:
    """Gameflow phase from the RC-LCUAgent snapshot, or None.

    Reads the same agent-posted snapshot /api/state uses
    (``dashboard._liveclient.lcu_summary``: localhost :8889, 1 s timeout,
    ``{}`` when the agent is down or its last push is older than 5 s).
    Imported lazily: this module must stay importable without the dashboard.
    """
    from dashboard._liveclient import lcu_summary

    snap = lcu_summary()
    phase = snap.get("phase") if isinstance(snap, dict) else None
    return phase if isinstance(phase, str) and phase else None


class GameActivity:
    """Is a League or TFT game loading or running right now?

    ``check()`` (also ``__call__``) returns a short reason string when a game
    is live - ``"process league of legends.exe"`` or
    ``"lcu phase InProgress"`` - and None when it is not. The process scan is
    cached for ``cache_s`` seconds whatever it answered; the LCU phase is read
    only when no game process was seen. Never raises: a failing probe counts
    as "no evidence of a game" for that signal.
    """

    def __init__(
        self,
        *,
        process_names: Optional[Callable[[], Iterable[str]]] = None,
        lcu_phase: Optional[Callable[[], Optional[str]]] = None,
        clock: Callable[[], float] = time.monotonic,
        cache_s: float = PROCESS_CACHE_S,
    ) -> None:
        self._process_names = process_names or _default_process_names
        self._lcu_phase = lcu_phase or _default_lcu_phase
        self._clock = clock
        self._cache_s = cache_s
        self._proc_at: Optional[float] = None
        self._proc_hit: Optional[str] = None

    def _game_process(self) -> Optional[str]:
        now = self._clock()
        if self._proc_at is not None and now - self._proc_at < self._cache_s:
            return self._proc_hit
        try:
            hits = sorted(
                n.lower() for n in self._process_names()
                if isinstance(n, str) and n.lower() in GAME_PROCESS_NAMES
            )
        except Exception:  # noqa: BLE001
            hits = []
        self._proc_at = now
        self._proc_hit = hits[0] if hits else None
        return self._proc_hit

    def check(self) -> Optional[str]:
        proc = self._game_process()
        if proc:
            return f"process {proc}"
        try:
            phase = self._lcu_phase()
        except Exception:  # noqa: BLE001
            phase = None
        if isinstance(phase, str) and phase in IN_GAME_PHASES:
            return f"lcu phase {phase}"
        return None

    __call__ = check


def _fmt_paths(paths: list[str]) -> str:
    shown = ", ".join(paths[:_LOG_PATH_CAP])
    rest = len(paths) - _LOG_PATH_CAP
    return f"{shown} (+{rest} more)" if rest > 0 else shown


class HotReloadWatcher:
    """One poll of the watchdog per ``tick()``; the loop lives in _watch_loop.

    ``tick()`` returns what it did, one of:
      "idle"           nothing changed (or nothing is pending)
      "ignored"        files changed, none of them loaded by RC
      "deferred"       a loaded file changed (now or earlier) and a game is
                       live; the restart is pending
      "triggered"      restart_trigger.txt written (pending set fired)
      "compile_failed" a pending file does not compile; no trigger, pending
                       cleared (the fixing edit triggers on its own)
      "trigger_failed" restart_trigger.txt could not be written; pending
                       kept, retried next tick

    Injection seams (tests): ``loaded`` returns the repo-relative files RC
    has loaded (default: _loaded_repo_files over sys.modules), ``game``
    returns a reason string while a game is live (default: GameActivity),
    ``scan`` is the candidate walker.
    """

    def __init__(
        self,
        root: Path,
        *,
        status_path: Path,
        trigger_path: Optional[Path] = None,
        loaded: Optional[Callable[[], Iterable[str]]] = None,
        game: Optional[Callable[[], Optional[str]]] = None,
        scan: Callable[[Path], dict] = _scan_py_files,
    ) -> None:
        self.root = Path(root)
        self.status_path = status_path
        self.trigger = trigger_path or self.root / "restart_trigger.txt"
        self._loaded = loaded or (lambda: _loaded_repo_files(self.root))
        self._game = game if game is not None else GameActivity()
        self._scan = scan
        self._last_loaded: frozenset[str] = frozenset()
        # Initial scan - never triggers.
        try:
            self.known: dict[str, float] = self._scan(self.root)
        except OSError:
            self.known = {}
        # Insertion-ordered set of loaded files whose restart is still owed.
        self.pending: dict[str, None] = {}
        self.deferred_since: Optional[str] = None
        self.deferred_reason: Optional[str] = None

    # -- helpers ---------------------------------------------------------
    def _loaded_set(self) -> frozenset[str]:
        try:
            got = frozenset(_fold(r) for r in self._loaded())
        except Exception as exc:  # noqa: BLE001
            _log.debug("hot-reload: loaded-module census failed (%s); "
                       "reusing the last one", type(exc).__name__)
            return self._last_loaded
        self._last_loaded = got
        return got

    def _in_game(self) -> Optional[str]:
        try:
            return self._game() or None
        except Exception:  # noqa: BLE001
            return None

    def _status(self, **extra) -> None:
        doc = {
            "watching": True,
            "file_count": len(self.known),
            "pending": list(self.pending),
            "deferred_reason": self.deferred_reason,
            "deferred_since": self.deferred_since,
        }
        doc.update(extra)
        _write_json(self.status_path, doc)

    def _clear_pending(self) -> None:
        self.pending = {}
        self.deferred_since = None
        self.deferred_reason = None

    def write_initial_status(self) -> None:
        loaded = self._loaded_set()
        self._status(
            last_change=None,
            last_compile=None,
            loaded_count=sum(1 for r in self.known if _fold(r) in loaded),
        )

    # -- the poll --------------------------------------------------------
    def tick(self) -> str:
        try:
            current = self._scan(self.root)
        except OSError:
            return "idle"
        raw = [
            rel for rel, mtime in current.items()
            # 0.5 s buffer for write latency.
            if mtime > self.known.get(rel, 0) + 0.5
        ]
        self.known = current

        changed: list[str] = []
        if raw:
            loaded = self._loaded_set()
            changed = [r for r in raw if _fold(r) in loaded]
            ignored = [r for r in raw if _fold(r) not in loaded]
            if ignored:
                _log.debug("hot-reload: ignored %d change(s) RC has not "
                           "loaded: %s", len(ignored), _fmt_paths(ignored))
            for rel in changed:
                self.pending[rel] = None

        if not self.pending:
            return "ignored" if raw else "idle"

        reason = self._in_game()
        if reason:
            if self.deferred_since is None:
                self.deferred_since = time.strftime("%Y-%m-%dT%H:%M:%S")
            self.deferred_reason = reason
            if changed:
                _log.info(
                    "hot-reload: restart deferred, game in progress (%s): "
                    "%d changed file(s): %s; %d pending",
                    reason, len(changed), _fmt_paths(changed),
                    len(self.pending))
                self._status(last_change=self.deferred_since,
                             last_compile="DEFERRED (game in progress)")
            return "deferred"
        return self._fire()

    def _fire(self) -> str:
        files = list(self.pending)
        for rel in files:
            try:
                py_compile.compile(str(self.root / rel), doraise=True)
            except (py_compile.PyCompileError, OSError) as exc:
                lines = str(exc).splitlines()
                msg = (lines[0] if lines else type(exc).__name__)[:160]
                # py_compile failed - do NOT write restart_trigger
                # (silent crash risk under pythonw.exe, CLAUDE.md hard rule).
                _log.warning(
                    "hot-reload: restart NOT triggered, py_compile failed "
                    "for %s: %s (pending dropped: %s)",
                    rel, msg, _fmt_paths(files))
                self._clear_pending()
                self._status(last_change=rel, last_compile=f"FAILED: {msg}")
                return "compile_failed"

        try:
            atomic_write_text(self.trigger, "auto-hot-reload")
        except OSError as exc:
            # No restart was requested: say so, keep the pending set and
            # retry on the next tick instead of logging a false "triggered".
            _log.warning("hot-reload: could not write %s (%s); %d file(s) "
                         "stay pending: %s", self.trigger.name,
                         type(exc).__name__, len(files), _fmt_paths(files))
            return "trigger_failed"
        held =(f" (deferred since {self.deferred_since}, game over)"
                if self.deferred_since else "")
        _log.info("hot-reload: restart triggered by %d file(s)%s: %s",
                  len(files), held, _fmt_paths(files))
        self._clear_pending()
        self._status(
            last_change=time.strftime("%Y-%m-%dT%H:%M:%S"),
            last_compile=f"OK ({len(files)} file(s))",
            changed=files,
        )
        return "triggered"


def _watch_loop(root: Path, halt_path: Path, status_path: Path) -> None:
    """Background thread: poll every 2 s, trigger restart on a loaded change."""
    watcher = HotReloadWatcher(root, status_path=status_path)
    watcher.write_initial_status()

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
            watcher.tick()
        except Exception:  # noqa: BLE001 - one bad tick must not end the thread
            _log.warning("hot-reload: tick failed", exc_info=True)


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

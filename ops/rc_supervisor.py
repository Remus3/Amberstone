"""
ops/rc_supervisor.py  --  Phase 0 control plane (FROZEN)

Phase 0 is complete and externally signed off. Do not make semantic changes
to the lifecycle, health-check, or monitor-alignment logic without an explicit
Phase 1+ change request.

Architecture summary:
  - Supervisor is the sole authoritative lifecycle owner.
    It spawns, stops, and restarts the app process; no other component may do so.
  - SelfMonitor is subordinate and process-bound.
    It reads supervisor status.json on every tick and will not return "healthy"
    unless the supervisor has confirmed the process is running and ready.
  - Deprecated scripts (watchdog.ps1, restart.bat, restart_clean.bat) are
    emergency/manual tools only; the supervisor must be running for normal ops.
  - status.json is the single inter-process control channel between supervisor
    and SelfMonitor. Its supervisor_run_id field is the bootstrap identity anchor.

Addendum fixes applied (Phases 0.1 - 0.13a):
  [1]  PidLock stores pid+start_time+run_id (JSON). league_watcher reads pid field.
  [1]  process adoption: supervisor adopts healthy running instance.
  [1]  stop_app() terminates by OWNED PID only.
  [2]  arbitrary shell paths gated behind admin_bridge_enabled flag.
  [3]  bad JSON supervisor requests logged and skipped.
  [3]  main loop wrapped in top-level try/except; writes fatal status before exit.
  [4]  non-blocking deploy thread; one deploy at a time.
  [5-8] heartbeat_valid(): process-alive + pid + mtime-floor + booting + run_id.
  [9-11] SelfMonitor aligned to supervisor state; 3-state return; stale-age fix.
  [12] rollback excludes ops/backups/ and API-Key-Claude.txt.
  [13] Bootstrap guard bounded; write_status() failures logged.
  [13a] Bootstrap guard kind-sentinel: distinguishes missing vs invalid status.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

#  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
# Lifecycle authority:
#   START   -  this supervisor (via start_app or adopt_existing_app)
#   STOP    -  this supervisor (via stop_app, owned PID or adopted PID only)
#   RESTART  -  this supervisor (via restart_app, same rules)
#   ROLLBACK  -  this supervisor (via _do_rollback, triggered by supervisor_requests/)
#   MONITOR  -  SelfMonitor threads (inside this process)
#
# Nothing else may start main.py when supervisor is running.
# watchdog.ps1, restart.bat, restart_clean.bat are deprecated (see .DEPRECATED files).
#  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 


#  -  -  Utilities  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

EXPECTED_DECISIONS_VERSION = "phase3-1.1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _replace_with_retry(src: Path, dst: Path) -> None:
    # Concurrent reader+writer on the same file (e.g. supervisor reads
    # health.json while Main writes it) can transiently raise WinError 5
    # PermissionError on Windows because the open-read holds a share lock.
    # The conflicting reader closes within milliseconds; a short backoff
    # clears it. Peer-VIP smoke 2026-05-02 surfaced this race.
    delays = (0.025, 0.05, 0.2)
    for i in range(len(delays) + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i >= len(delays):
                raise
            time.sleep(delays[i])


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _replace_with_retry(tmp, path)


def _pid_alive(pid: int) -> bool:
    """Check if a Windows process with the given PID is alive."""
    try:
        import ctypes
        SYNCHRONIZE = 0x00100000
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    except Exception:
        try:
            # CREATE_NO_WINDOW: this module runs under a pythonw.exe-hosted
            # scheduled task (RC-Supervisor), which must stay Interactive
            # because it drives the Electron overlay - so unlike the S4U tasks
            # it has a desktop and a console child WOULD flash onscreen.
            # pythonw suppresses its OWN console, never a child's, and
            # capture_output/check_output does not suppress it either
            # (b2b6a4f3, same class). Platform-guarded: passing creationflags
            # on POSIX raises, and CI runs these tests on ubuntu.
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                stderr=subprocess.DEVNULL, text=True, timeout=5,
                creationflags=(0x08000000 if os.name == "nt" else 0),
            )
            return str(pid) in out
        except Exception:
            return False


def _kill_pid(pid: int) -> bool:
    """Terminate a process by PID. Returns True if signal was sent."""
    try:
        import ctypes
        PROCESS_TERMINATE = 0x0001
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if not h:
            return False
        result = ctypes.windll.kernel32.TerminateProcess(h, 1)
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(result)
    except Exception:
        return False


#  -  -  PID Lock  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

class PidLock:
    """
    JSON lock file: {pid, start_time, run_id, locked_at}.
    The 'pid' field is kept as a top-level integer for backward compatibility
    with rc_league_watcher.ps1 which reads it as a plain number.

    AUDIT 2026-04-28 (proposal 1.5): replaced write+sleep+verify with a real
    Win32 byte-range lock via msvcrt.locking(). The fd stays open for the
    lifetime of the supervisor process; the OS releases the lock on crash,
    closing the theoretical race window where two supervisors could both
    pass the verify step.
    """

    def __init__(self, lock_file: Path) -> None:
        self.lock_file = lock_file
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        # Sidecar file holding the OS-level byte-range lock. Kept separate
        # from the readable JSON pid file so msvcrt's exclusive lock doesn't
        # block rc_league_watcher.ps1's plain-text read of the pid field.
        self._os_lock_path = lock_file.parent / (lock_file.name + ".oslock")
        self._run_id = _new_id()
        self._fd: Optional[int] = None

    def acquire(self) -> bool:
        import msvcrt
        my_pid  = os.getpid()
        my_time = time.time()
        try:
            fd = os.open(str(self._os_lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        except OSError:
            return False
        try:
            # Non-blocking exclusive byte-range lock on byte 0. If another
            # supervisor holds the lock the OS returns OSError immediately;
            # if a previous supervisor crashed without releasing, the OS has
            # already cleared the lock so we proceed.
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        # Write the readable JSON payload for league_watcher.ps1 (and any
        # other observers). atomic_write_json gives mid-write safety on the
        # readable file without coupling to the OS-lock fd.
        try:
            atomic_write_json(self.lock_file, {
                "pid":        my_pid,
                "start_time": my_time,
                "run_id":     self._run_id,
                "locked_at":  utc_now(),
            })
        except OSError:
            self.release()
            return False
        return True

    def release(self) -> None:
        if self._fd is not None:
            import msvcrt
            try:
                os.lseek(self._fd, 0, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        # Best-effort cleanup of both files (oslock may still be held by the
        # kernel if the OS hasn't fully released; harmless either way).
        for p in (self.lock_file, self._os_lock_path):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


#  -  -  Circuit Breaker  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

class CircuitBreaker:
    """
    Persisted crash-loop protection.
    State written to ops/runtime/circuit_breaker_state.json on every change.
    Restored on supervisor startup so counters survive supervisor restarts.
    """

    def __init__(
        self,
        state_file:   Path,
        max_restarts: int   = 5,
        window_s:     float = 120.0,
        cooldown_s:   float = 300.0,
    ) -> None:
        self.state_file   = state_file
        self.max_restarts = max_restarts
        self.window_s     = window_s
        self.cooldown_s   = cooldown_s
        self._times: List[float] = []
        self.tripped      = False
        self._trip_time:  Optional[float] = None
        self._total_restarts = 0
        self._restore()

    #  -  -  Public  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

    def allow_restart(self) -> bool:
        now = time.monotonic()
        if self.tripped:
            if self._trip_time and (now - self._trip_time) >= self.cooldown_s:
                self._do_reset()
            else:
                return False

        self._times = [t for t in self._times if now - t < self.window_s]
        if len(self._times) >= self.max_restarts:
            self.tripped    = True
            self._trip_time = now
            self._persist()
            return False

        self._times.append(now)
        self._total_restarts += 1
        self._persist()
        return True

    def on_success(self) -> None:
        if not self.tripped and not self._times:
            return
        self._do_reset()

    def force_reset(self) -> None:
        """Explicit reset  -  triggered by reset_breaker file or command."""
        self._do_reset()

    def seconds_until_reset(self) -> float:
        if not self.tripped or self._trip_time is None:
            return 0.0
        return max(0.0, self.cooldown_s - (time.monotonic() - self._trip_time))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tripped":            self.tripped,
            "count_in_window":    len(self._times),
            "total_restarts":     self._total_restarts,
            "max_restarts":       self.max_restarts,
            "window_s":           self.window_s,
            "cooldown_s":         self.cooldown_s,
            "seconds_until_reset": round(self.seconds_until_reset(), 1),
        }

    #  -  -  Internal  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

    def _do_reset(self) -> None:
        self._times     = []
        self.tripped     = False
        self._trip_time  = None
        self._persist()

    def _persist(self) -> None:
        try:
            atomic_write_json(self.state_file, {
                "updated_at":      utc_now(),
                "tripped":         self.tripped,
                "total_restarts":  self._total_restarts,
                "trip_time_mono":  self._trip_time,   # None if not tripped
                "times_count":     len(self._times),
                "max_restarts":    self.max_restarts,
                "window_s":        self.window_s,
                "cooldown_s":      self.cooldown_s,
            })
        except Exception:
            pass

    def _restore(self) -> None:
        """Restore persisted counters from previous run."""
        try:
            if not self.state_file.exists():
                return
            data = json.loads(self.state_file.read_text(encoding="utf-8-sig"))
            self._total_restarts = int(data.get("total_restarts", 0))
            if data.get("tripped"):
                # Approximate: we can't know exact monotonic time from a previous run.
                # Treat as if tripped just now  -  will auto-clear after cooldown_s.
                self.tripped    = True
                self._trip_time = time.monotonic()
        except Exception:
            pass


#  -  -  Helpers  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

def _new_id() -> str:
    import uuid
    return uuid.uuid4().hex[:16]


# ---- Phase 3 supervisor subordinate watcher (additive sidecar) -------------
#
# Frozen-file note: additive only. Does NOT touch any main-app lifecycle path
# (start_app / stop_app / restart_app / _app_alive / heartbeat_valid /
# heartbeat_stale / status.json main-app schema).
#
# Watches agents/state/lockfile (written by agents.supervisor every 5s, see
# agents/supervisor.py HEARTBEAT_INTERVAL). Restarts the
# RC-Phase3-Supervisor scheduled task via `schtasks /Run` (preserves the
# task's run-as-Admin + HIGHEST run-level context - don't Popen
# `pythonw -m agents.supervisor` directly from here).


class _Phase3Watcher:
    """Detects Phase 3 supervisor death or heartbeat staleness and
    re-launches its scheduled task. Restart events surface via the parent
    Supervisor's _record_incident + status.json.

    Default thresholds:
      - heartbeat staleness: 30s (~6 missed 5s heartbeats - tolerates
        event-loop pauses, GC, startup grace, transient I/O blocks)
      - per-attempt cooldown: 30s (new instance needs ~3-5s to write its
        first heartbeat; cooldown prevents re-fire while booting)
      - CircuitBreaker: max 5 restarts in 120s, then 300s lockout (same
        defaults as main app's breaker but a separate budget - Phase 3
        flapping must not affect main-app restart credit)
    """

    _HEARTBEAT_STALE_S = 30.0
    _RESTART_COOLDOWN_S = 30.0
    _SCHED_TASK_NAME = "RC-Phase3-Supervisor"

    # Stale-code detection (2026-05-18). `python -m agents.supervisor`
    # imports its code once at process start and has no restart_trigger
    # equivalent - a deploy that doesn't stall its heartbeat leaves it
    # running old code indefinitely (2026-05-17 incident: a ~27h process
    # never picked up keystone 3eb2e2d, silently broadcasting un-mirrored
    # WS health). When the process is otherwise healthy but its
    # `started_at` predates the newest mtime in its import chain, restart
    # it via the SAME cooldown + CircuitBreaker + schtasks path. The
    # grace margin absorbs the import->lockfile-write gap + clock skew.
    # Self-limiting: the restarted process's started_at moves past the
    # mtimes (one restart per deploy); the budget bounds any pathology.
    _STALE_CODE_GRACE_S = 5.0
    _WATCHED_CODE_FILES = (
        "dashboard/_state_builder.py",
        "dashboard/_liveclient.py",
        "dashboard/_cs_retention.py",
        "core/queue_modes.py",
    )
    _WATCHED_CODE_DIRS = ("agents",)
    # agents/daemon_slayer is the standalone Daemon Slayer engine - it
    # runs as its own process on :8860 (supervised independently) and is
    # NOT imported by the Phase 3 supervisor. Edits there (the active DS
    # work cadence) must not bounce Phase 3, so prune it from the
    # recursive agents/ scan.
    _EXCLUDED_CODE_DIRS = ("agents/daemon_slayer",)

    def __init__(
        self,
        project_root: Path,
        runtime_dir: Path,
        log_fn,
        *,
        lockfile_path: Optional[Path] = None,
        budget_state_file: Optional[Path] = None,
        restarter=None,
        pid_alive_fn=None,
        clock=None,
    ) -> None:
        self._project_root = project_root
        self._lockfile = lockfile_path or (project_root / "agents" / "state" / "lockfile")
        self._log = log_fn
        self._restarter = restarter or self._default_restarter
        self._pid_alive = pid_alive_fn or _pid_alive
        self._clock = clock or time.monotonic

        self._budget = CircuitBreaker(
            state_file=budget_state_file or (runtime_dir / "phase3_breaker_state.json"),
            max_restarts=5, window_s=120.0, cooldown_s=300.0,
        )

        self._last_restart_mono: Optional[float] = None
        self._last_state: str = "unknown"
        self._last_pid: Optional[int] = None
        self._last_age_s: Optional[float] = None
        self._last_acted_at: Optional[str] = None

    @staticmethod
    def _default_restarter(task_name: str, stale_pid: Optional[int] = None) -> bool:
        """Restart the Phase 3 scheduled task.

        The task is MultipleInstancesPolicy=IgnoreNew, so a bare
        `schtasks /Run` is refused (0x800710E0) while an instance is
        still alive - which is exactly the `stale_code` trigger (the
        process is healthy, it just imported old code) and a hung
        `stale_heartbeat` (process alive but not beating). When the
        recorded pid is still alive, terminate it first so the
        scheduler can launch a fresh instance. taskkill /F is used
        deliberately (never Stop-Process - it hangs the MCP pipe, per
        the project hard rule).
        """
        try:
            if stale_pid and _pid_alive(int(stale_pid)):
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(int(stale_pid))],
                    capture_output=True, timeout=10,
                    creationflags=(0x08000000 if os.name == "nt" else 0),
                )
                # Wait for the process to actually exit so the task slot
                # is released before /Run (else IgnoreNew still refuses).
                # Bounded - if it outlives the wait the next watcher tick
                # retries cleanly (pid now dead -> a plain /Run works).
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    if not _pid_alive(int(stale_pid)):
                        break
                    time.sleep(0.25)
            result = subprocess.run(
                ["schtasks", "/Run", "/TN", task_name],
                capture_output=True, timeout=10,
                creationflags=(0x08000000 if os.name == "nt" else 0),
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError, ValueError):
            return False

    def _read_lockfile(self) -> Optional[Dict[str, Any]]:
        if not self._lockfile.exists():
            return None
        try:
            return json.loads(self._lockfile.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _started_at_epoch(data: Optional[Dict[str, Any]]) -> Optional[float]:
        """Epoch seconds for the lockfile's ``started_at``, or None when
        absent/unparseable. Absent = an old supervisor predating the
        2026-05-18 heartbeat change - the stale-code check then no-ops
        (it will gain the field the first time it restarts for any
        reason), so this is backward-compatible by construction."""
        if not isinstance(data, dict):
            return None
        s = data.get("started_at")
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(str(s))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except (ValueError, TypeError):
            return None

    def _newest_code_mtime(self) -> Optional[float]:
        """Newest mtime across the Phase-3 import chain: every ``*.py``
        under the watched package dirs plus the explicit cross-package
        files. Returns None if nothing is found / all stats fail (caller
        treats None as 'cannot determine' -> skip, never false-restart)."""
        newest: Optional[float] = None
        try:
            for rel in self._WATCHED_CODE_FILES:
                p = self._project_root / rel
                try:
                    m = p.stat().st_mtime
                except OSError:
                    continue
                if newest is None or m > newest:
                    newest = m
            excluded = tuple(
                self._project_root / e for e in self._EXCLUDED_CODE_DIRS
            )
            for rel in self._WATCHED_CODE_DIRS:
                base = self._project_root / rel
                if not base.is_dir():
                    continue
                for p in base.rglob("*.py"):
                    if any(p.is_relative_to(ex) for ex in excluded):
                        continue
                    try:
                        m = p.stat().st_mtime
                    except OSError:
                        continue
                    if newest is None or m > newest:
                        newest = m
        except Exception:  # noqa: BLE001 - scan must never raise
            return None
        return newest

    def check(self) -> Dict[str, Any]:
        """Inspect Phase 3 health; restart if dead/stale + budget allows.

        Result keys:
          state: "healthy" | "stale_heartbeat" | "dead_pid" | "missing_lockfile"
                  | "stale_code" | "restarting" | "restart_invocation_failed"
                  | "cooldown" | "restart_blocked"
          pid, heartbeat_age_s, acted: bool, plus trigger / cooldown detail
        """
        data = self._read_lockfile()
        pid = int(data.get("pid", 0)) if isinstance(data, dict) else 0
        hb_str = data.get("heartbeat_at") if isinstance(data, dict) else None

        age_s: Optional[float] = None
        if hb_str:
            try:
                hb_dt = datetime.fromisoformat(str(hb_str))
                if hb_dt.tzinfo is None:
                    hb_dt = hb_dt.replace(tzinfo=timezone.utc)
                age_s = (datetime.now(timezone.utc) - hb_dt).total_seconds()
            except (ValueError, TypeError):
                age_s = None

        if data is None or age_s is None:
            state = "missing_lockfile"
            unhealthy = True
        elif age_s > self._HEARTBEAT_STALE_S:
            state = "stale_heartbeat"
            unhealthy = True
        elif pid and not self._pid_alive(pid):
            state = "dead_pid"
            unhealthy = True
        else:
            state = "healthy"
            unhealthy = False

        # Stale-code upgrade: an otherwise-healthy process (alive +
        # fresh heartbeat) that imported its code before a later deploy
        # touched its import chain. Reuses the same cooldown + budget +
        # restarter path below. Fully guarded - any failure to determine
        # started_at or scan mtimes SKIPS the check (never false-restart);
        # absent started_at = an old supervisor, also skipped.
        if not unhealthy:
            try:
                started_epoch = self._started_at_epoch(data)
                if started_epoch is not None:
                    newest = self._newest_code_mtime()
                    if (newest is not None
                            and newest > started_epoch + self._STALE_CODE_GRACE_S):
                        state = "stale_code"
                        unhealthy = True
            except Exception:  # noqa: BLE001 - never crash the watcher
                pass

        self._last_pid = pid or None
        self._last_age_s = age_s

        if not unhealthy:
            self._last_state = state
            return {"state": state, "pid": pid or None,
                    "heartbeat_age_s": age_s, "acted": False}

        now_mono = self._clock()
        if self._last_restart_mono is not None:
            since = now_mono - self._last_restart_mono
            if since < self._RESTART_COOLDOWN_S:
                self._last_state = "cooldown"
                return {"state": "cooldown", "pid": pid or None,
                        "heartbeat_age_s": age_s, "acted": False,
                        "trigger": state,
                        "cooldown_remaining_s": round(self._RESTART_COOLDOWN_S - since, 1)}

        if not self._budget.allow_restart():
            self._last_state = "restart_blocked"
            return {"state": "restart_blocked", "pid": pid or None,
                    "heartbeat_age_s": age_s, "acted": False,
                    "trigger": state,
                    "budget_cooldown_s": round(self._budget.seconds_until_reset(), 1)}

        ok = self._restarter(self._SCHED_TASK_NAME, pid or None)
        self._last_restart_mono = now_mono
        self._last_acted_at = utc_now()
        result_state = "restarting" if ok else "restart_invocation_failed"
        self._last_state = result_state
        self._log(
            f"phase3 {state} -- schtasks /Run {self._SCHED_TASK_NAME} "
            f"{'OK' if ok else 'FAILED'} (age={age_s}s pid={pid or None})"
        )
        return {"state": result_state, "pid": pid or None,
                "heartbeat_age_s": age_s, "acted": True, "trigger": state}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_state":           self._last_state,
            "last_pid":             self._last_pid,
            "last_heartbeat_age_s": (round(self._last_age_s, 1)
                                     if self._last_age_s is not None else None),
            "last_acted_at":        self._last_acted_at,
            "stale_threshold_s":    self._HEARTBEAT_STALE_S,
            "stale_code_grace_s":   self._STALE_CODE_GRACE_S,
            "restart_cooldown_s":   self._RESTART_COOLDOWN_S,
            "scheduled_task":       self._SCHED_TASK_NAME,
            "budget":               self._budget.to_dict(),
        }


#  -  -  Supervisor  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

class Supervisor:

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.config      = json.loads(config_path.read_text(encoding="utf-8-sig"))

        self.project_root  = Path(self.config["project_root"]).resolve()
        self.runtime_dir   = Path(
            self.config.get("runtime_dir") or self.project_root / "ops" / "runtime"
        ).resolve()
        self.status_file   = self.runtime_dir / "status.json"
        self.health_file   = Path(
            self.config.get("health_file") or self.runtime_dir / "health.json"
        ).resolve()
        self.log_file      = self.runtime_dir / "logs" / "supervisor.log"
        self.deploy_req_dir  = self.runtime_dir / "deploy_requests"
        self.deploy_res_dir  = self.runtime_dir / "deploy_results"
        self.sup_req_dir     = self.runtime_dir / "supervisor_requests"
        self.cb_state_file   = self.runtime_dir / "circuit_breaker_state.json"

        self.python_exe    = self.config.get("python_exe") or sys.executable
        self.app_cmd       = self.config["app_cmd"]
        self.deploy_script = Path(
            self.config.get("deploy_script")
            or self.project_root / "ops" / "rc_transactional_deploy.py"
        ).resolve()
        self.max_heartbeat_age = float(self.config.get("max_heartbeat_age_seconds", 15.0))
        self.poll_interval     = float(self.config.get("poll_interval_seconds", 1.0))

        # Process tracking (owned + adopted, never by pattern)
        self.process:        Optional[subprocess.Popen] = None
        self._adopted_pid:   Optional[int]  = None
        self._owned_run_id:  Optional[str]  = None   # run_id from health.json
        self._owned_session_id: Optional[str] = None  # session_id from health.json
        self.last_start_at:  Optional[str]  = None
        self.last_restart_reason: Optional[str] = None

        # Startup grace: track when we last started/adopted so heartbeat_stale()
        # does not treat "no health.json yet" as healthy indefinitely.
        # Set by start_app() and _adopt_existing_app(); cleared by stop_app().
        self._awaiting_first_heartbeat: bool          = False
        self._startup_mono_ts:          Optional[float] = None  # monotonic time of last start
        self.startup_heartbeat_timeout_s: float = float(
            self.config.get("startup_heartbeat_timeout_s", 30.0)
        )  # max seconds to wait for first healthy heartbeat after start

        # Launch identity: binds heartbeat acceptance to the specific spawned process.
        # _expected_pid       - the PID Popen returned (or the adopted pid).
        # _launch_mtime_floor - wall-clock time just before Popen; any valid health.json
        #                       for THIS launch must have mtime >= this value.
        # _observed_pid       - the PID the child actually reports in health.json,
        #                       latched on first valid heartbeat. Peer-VIP 2026-05-02
        #                       surfaced that pythonw.exe under a venv is a launcher
        #                       stub: Popen returns the stub pid but the real child
        #                       (pythonw3.13.exe) writes its OWN pid to health.json.
        #                       After first heartbeat we trust _observed_pid for
        #                       liveness, not _expected_pid. Stale-from-previous-run
        #                       protection still comes from the mtime floor.
        # All three cleared by stop_app(); set by start_app() / _adopt_existing_app().
        self._expected_pid:        Optional[int]   = None
        self._launch_mtime_floor:  Optional[float] = None  # time.time() at launch
        self._observed_pid:        Optional[int]   = None

        # Single-instance lock
        self.pid_lock = PidLock(self.runtime_dir / "supervisor.pid")

        # Crash-loop protection (persisted)
        self.circuit_breaker = CircuitBreaker(
            state_file   = self.cb_state_file,
            max_restarts = int(self.config.get("max_restart_attempts", 5)),
            window_s     = float(self.config.get("restart_window_seconds", 120.0)),
            cooldown_s   = float(self.config.get("restart_cooldown_seconds", 300.0)),
        )

        # Non-blocking deploy state
        self._deploy_in_progress: set[str] = set()
        self._deploy_thread: Optional[threading.Thread] = None

        # Self-monitor (started inside loop())
        self._monitor = None

        # Ensure dirs
        for d in [self.deploy_req_dir, self.deploy_res_dir, self.sup_req_dir,
                  self.runtime_dir, self.log_file.parent]:
            d.mkdir(parents=True, exist_ok=True)

        # Subordinate watch for the Phase 3 supervisor (agents.supervisor).
        # Additive sidecar - see _Phase3Watcher docstring. Does not touch
        # any main-app lifecycle path.
        self._phase3_watcher = _Phase3Watcher(
            project_root=self.project_root,
            runtime_dir=self.runtime_dir,
            log_fn=self.log,
        )

    #  -  -  Logging  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

    def log(self, line: str) -> None:
        msg = f"[{utc_now()}] {line}\n"
        try:
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(msg)
        except Exception:
            pass

    #  -  -  Status  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

    def write_status(self, extra: Optional[Dict[str, Any]] = None) -> None:
        # Compute startup deadline info for status visibility
        awaiting = self._awaiting_first_heartbeat
        deadline_remaining: Optional[float] = None
        if awaiting and self._startup_mono_ts is not None:
            elapsed = time.monotonic() - self._startup_mono_ts
            deadline_remaining = max(0.0, self.startup_heartbeat_timeout_s - elapsed)

        data: Dict[str, Any] = {
            "updated_at":               utc_now(),
            "supervisor_state":         self._supervisor_state(),
            "supervisor_run_id":        self.pid_lock._run_id,
            "process_running":          self._app_alive(),
            "pid":                      self._current_pid(),
            "expected_pid":             self._expected_pid,
            "owned_run_id":             self._owned_run_id,
            "owned_session_id":         self._owned_session_id,
            "awaiting_first_heartbeat": awaiting,
            "first_heartbeat_deadline_s": deadline_remaining,
            "last_start_at":            self.last_start_at,
            "last_restart_reason":      self.last_restart_reason,
            "circuit_breaker":          self.circuit_breaker.to_dict(),
            "deploy_in_progress":       bool(self._deploy_in_progress),
            "phase3":                   self._phase3_watcher.to_dict(),
        }
        if extra:
            data.update(extra)
        try:
            atomic_write_json(self.status_file, data)
        except Exception as exc:
            self.log(f"write_status FAILED: {type(exc).__name__}: {exc}")
            self._record_incident("ERROR", "write_status_failed", "none", "error",
                                  detail=str(exc))

    def _current_pid(self) -> Optional[int]:
        if self.process and self.process.poll() is None:
            return self.process.pid
        if self._adopted_pid and _pid_alive(self._adopted_pid):
            return self._adopted_pid
        return None

    #  -  -  App alive check  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

    def _app_alive(self) -> bool:
        if self.process is not None and self.process.poll() is None:
            return True
        if self._adopted_pid is not None:
            if _pid_alive(self._adopted_pid):
                return True
            self._adopted_pid = None  # adopted process died
        return False

    #  -  -  Process adoption  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

    def _adopt_existing_app(self) -> bool:
        """
        Check if a healthy app is already running and adopt it instead of
        blindly spawning a second one.  Returns True if adopted.
        On adoption, propagates full process identity (run_id + session_id)
        to owned-ID tracking and incident log.
        """
        if not self.health_file.exists():
            return False
        try:
            age = time.time() - self.health_file.stat().st_mtime
            if age > self.max_heartbeat_age:
                return False
            health = json.loads(self.health_file.read_text(encoding="utf-8-sig"))
            if not health.get("alive"):
                return False
            pid = int(health.get("pid") or 0)
            if not pid or not _pid_alive(pid):
                return False
            run_id     = str(health.get("run_id")     or "")
            session_id = str(health.get("session_id") or "")
            self._adopted_pid      = pid
            self._owned_run_id     = run_id
            self._owned_session_id = session_id or None
            self.last_start_at     = health.get("started_at")
            self.last_restart_reason = "adopted_existing"
            # Adoption: identity is known immediately from the live health file.
            # _observed_pid is set to the same pid since adoption already validated
            # this is the live process - there's no stub-indirection question,
            # we read pid straight from the freshly-mtimed health.json.
            self._expected_pid         = pid
            self._observed_pid         = pid
            self._launch_mtime_floor   = None  # adoption already validated freshness
            self._awaiting_first_heartbeat = False
            self._startup_mono_ts          = None
            # Propagate identity to incident log immediately
            if hasattr(self, '_incident_log') and self._incident_log is not None:
                try:
                    self._incident_log.set_process_identity(
                        run_id, session_id
                    )
                except Exception:
                    pass
            self.log(f"adopted existing app pid={pid} run_id={run_id}")
            return True
        except Exception as exc:
            self.log(f"adopt_existing_app failed: {exc}")
            return False

    #  -  -  Lifecycle  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

    def start_app(self, reason: str) -> bool:
        """
        Start the overlay.  First tries to adopt an already-running healthy
        instance.  Returns False if circuit breaker blocks the restart.
        """
        if self._app_alive():
            return True  # already managed

        # Try adoption before spawning
        if self._adopt_existing_app():
            return True

        if not self.circuit_breaker.allow_restart():
            wait = self.circuit_breaker.seconds_until_reset()
            self.log(
                f"circuit_breaker TRIPPED  -  refusing restart reason={reason!r} "
                f"({wait:.0f}s until auto-reset)"
            )
            self._record_incident("ERROR", "circuit_breaker_tripped", "app_restart",
                                  "skipped", detail=f"reason={reason}")
            return False

        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        try:
            self.process = subprocess.Popen(
                self.app_cmd,
                cwd=str(self.project_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                creationflags=flags,
            )
        except Exception as exc:
            self.log(f"start_app failed: {exc}")
            return False

        self.last_start_at       = utc_now()
        self.last_restart_reason = reason
        self._owned_run_id       = None   # will be updated on first heartbeat
        self._owned_session_id   = None
        # Bind heartbeat acceptance to the process we just spawned.
        # _launch_mtime_floor is set BEFORE Popen so any health.json written
        # by the new process will have mtime > floor; a stale file from the
        # previous run will have mtime < floor and be rejected.
        self._expected_pid        = self.process.pid
        self._launch_mtime_floor  = time.time()   # set after Popen returns
        # Start the startup grace window
        self._awaiting_first_heartbeat = True
        self._startup_mono_ts          = time.monotonic()
        self.log(f"started app pid={self.process.pid} reason={reason!r}")
        self.write_status()
        return True

    def stop_app(self, reason: str) -> None:
        """
        Stop the managed app.
        ALWAYS by owned PID or adopted PID  -  never by broad pattern matching.
        """
        if self.process is not None:
            pid = self.process.pid
            if self.process.poll() is None:
                self.log(f"stopping owned app pid={pid} reason={reason!r}")
                self.process.terminate()
                try:
                    self.process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    try:
                        self.process.wait(timeout=2.0)
                    except Exception:  # noqa: BLE001
                        # LEFT BROAD DELIBERATELY (2026-07-19 triage). Popen.wait()
                        # on Windows is NOT TimeoutExpired-only: _wait() calls
                        # _winapi.WaitForSingleObject + GetExitCodeProcess, both of
                        # which raise OSError on a bad/closed handle. Could not
                        # rule out OSError here, and an escape would propagate out
                        # of stop_app() into the restart path - a silent crash
                        # under pythonw. Narrow only with a proven raise set.
                        pass
            self.process = None

        elif self._adopted_pid is not None:
            pid = self._adopted_pid
            if _pid_alive(pid):
                self.log(f"stopping adopted app pid={pid} reason={reason!r}")
                if not _kill_pid(pid):
                    self.log(f"kill_pid({pid}) failed  -  process may already be dead")
                # Give it a moment
                for _ in range(10):
                    if not _pid_alive(pid):
                        break
                    time.sleep(0.2)
            self._adopted_pid = None

        self._owned_run_id     = None
        self._owned_session_id = None
        self._awaiting_first_heartbeat = False
        self._startup_mono_ts          = None
        self._expected_pid             = None
        self._launch_mtime_floor       = None
        self._observed_pid             = None
        self.write_status()

    def restart_app(self, reason: str) -> bool:
        self.stop_app(reason=reason)
        time.sleep(1.0)
        return self.start_app(reason=reason)

    #  -  -  Health  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

    def _read_health(self) -> Optional[Dict[str, Any]]:
        """Read health.json safely. Returns None on any error."""
        try:
            if not self.health_file.exists():
                return None
            return json.loads(self.health_file.read_text(encoding="utf-8-sig"))
        except Exception:
            return None

    def _is_current_launch_heartbeat(self, health: dict, mtime: float) -> tuple:
        """
        Return (is_current: bool, reject_reason: str).
        Used during startup grace only - establishes whether a freshly
        appearing health.json belongs to the launch we just kicked off.

        Peer-VIP 2026-05-02 surfaced that pythonw.exe inside a venv is a
        LAUNCHER STUB: subprocess.Popen returns the stub's pid, but the
        real child (pythonw3.13.exe) is a separate process and writes its
        OWN pid to health.json. The two never match. Strict pid matching
        here would treat every legitimate startup as a foreign heartbeat.

        Acceptance rule:
          - mtime >= _launch_mtime_floor (file written after we Popen'd).
        Adoption sets _launch_mtime_floor=None (already-validated freshness),
        so the floor check is skipped in that case.

        We do NOT check pid here - _observed_pid is latched on first valid
        heartbeat in _on_first_heartbeat() and enforced thereafter.
        """
        if self._expected_pid is None:
            return False, "no_expected_pid"
        floor = self._launch_mtime_floor
        if floor is not None and mtime < floor:
            return False, ("startup_rejected_stale_health_file:"
                           " mtime=" + str(round(mtime, 3))
                           + " floor=" + str(round(floor, 3)))
        return True, ""

    def heartbeat_stale(self) -> bool:
        """
        Return True if the app heartbeat is unhealthy.

        All heartbeat acceptance is process-bound:
          - health.json pid must match _expected_pid (the process we spawned/adopted)
          - health.json mtime must be >= _launch_mtime_floor (post-launch write)
        This prevents a stale health.json from a previous run being treated as
        a valid heartbeat for a newly launched process.

        Three phases:
          1. Startup grace (awaiting_first_heartbeat=True):
             - file missing: tolerated within grace window
             - file exists but wrong pid/stale mtime: ignored (keep waiting)
             - file exists with booting=True for current pid: tolerated within grace
             - file exists, alive=True, not booting, current pid: first heartbeat
             - grace expires with no valid heartbeat: stale -> restart
          2. Normal operation:
             - file missing: stale
             - mtime too old: stale
             - wrong pid: stale (foreign/previous-run file)
             - alive=False: stale
             - fresh, correct pid, alive=True: healthy
        """
        now_mono = time.monotonic()

        def _read_with_mtime():
            """Returns (health_dict, mtime) or (None, 0) on error."""
            try:
                mtime = self.health_file.stat().st_mtime
                payload = json.loads(self.health_file.read_text(encoding="utf-8-sig"))
                return payload, mtime
            except Exception:
                return None, 0.0

        # -- Startup grace phase -----------------------------------------------
        if self._awaiting_first_heartbeat and self._startup_mono_ts is not None:
            elapsed      = now_mono - self._startup_mono_ts
            within_grace = elapsed < self.startup_heartbeat_timeout_s

            if not self.health_file.exists():
                if within_grace:
                    return False   # tolerate missing file during startup
                self.log("startup_heartbeat_timeout: no health.json after "
                         + str(round(elapsed, 1)) + "s")
                return True

            health, mtime = _read_with_mtime()
            if health is None:
                return True   # unreadable = stale

            # Check if this file belongs to the process we launched
            is_current, reject_reason = self._is_current_launch_heartbeat(health, mtime)

            if not is_current:
                # File is stale/wrong-pid: keep waiting within grace, restart after
                if within_grace:
                    return False   # waiting for current process to write its file
                self.log("startup_heartbeat_timeout: " + reject_reason
                         + " after " + str(round(elapsed, 1)) + "s")
                return True

            # File is from our process. Now check liveness.
            if health.get("alive") and not health.get("booting"):
                # First healthy heartbeat received - clear grace window
                self._awaiting_first_heartbeat = False
                self._startup_mono_ts          = None
                self._on_first_heartbeat(health)
                return False

            if within_grace:
                return False   # current pid, booting or alive=False but within grace

            # Grace expired with wrong or no valid heartbeat
            self.log("startup_heartbeat_timeout: grace expired after "
                     + str(round(elapsed, 1)) + "s")
            return True

        # -- Normal operation (after first heartbeat or adopted process) -------
        if not self.health_file.exists():
            return True
        health, mtime = None, 0.0
        try:
            mtime  = self.health_file.stat().st_mtime
            health = self._read_health()
        except Exception:
            return True
        if mtime and time.time() - mtime > self.max_heartbeat_age:
            return True
        if not health:
            return True
        if not health.get("alive"):
            return True
        # PID check in normal operation: enforce against _observed_pid (the
        # pid the child actually reports, latched on first valid heartbeat).
        # _expected_pid (the Popen-returned pid) may be a stub indirection on
        # venv pythonw installs and is intentionally NOT compared here.
        # If we somehow reach normal-operation without ever latching an
        # observed pid, fall through and let _on_first_heartbeat capture it.
        if self._observed_pid is not None:
            reported_pid = int(health.get("pid") or 0)
            if reported_pid != self._observed_pid:
                self.log("heartbeat_wrong_pid: observed="
                         + str(self._observed_pid) + " got=" + str(reported_pid))
                return True
        self._on_first_heartbeat(health)
        return False

    def _on_first_heartbeat(self, health: Dict[str, Any]) -> None:
        """Update owned identity from a live heartbeat payload."""
        # Latch the pid the child actually reports - this may differ from
        # _expected_pid (Popen pid) when pythonw.exe is a launcher stub.
        # Only set on the FIRST valid heartbeat; subsequent calls are no-ops
        # so a foreign or stale-runtime heartbeat can't overwrite our anchor.
        if self._observed_pid is None:
            reported_pid = int(health.get("pid") or 0)
            if reported_pid > 0:
                self._observed_pid = reported_pid
                if reported_pid != self._expected_pid:
                    self.log("observed_pid_diverged_from_expected:"
                             " expected=" + str(self._expected_pid)
                             + " observed=" + str(reported_pid)
                             + " (pythonw stub indirection - expected on venvs)")

        reported_run_id     = str(health.get("run_id") or "")
        reported_session_id = str(health.get("session_id") or "")
        if reported_run_id and self._owned_run_id is None:
            self._owned_run_id     = reported_run_id
            self._owned_session_id = reported_session_id or None
            if hasattr(self, "_incident_log") and self._incident_log is not None:
                try:
                    self._incident_log.set_process_identity(
                        self._owned_run_id,
                        self._owned_session_id or "",
                    )
                except Exception:
                    pass

    def heartbeat_valid(self) -> bool:
        """
        Combined live-process + valid-heartbeat check.
        True only when BOTH of these hold simultaneously:
          1. The managed app process is currently alive (_app_alive())
          2. health.json contains a fresh, current, non-booting heartbeat
             for that exact process.

        File requirements (all must hold for condition 2):
          - health.json exists
          - mtime < max_heartbeat_age
          - health["pid"] == _expected_pid
          - mtime >= _launch_mtime_floor  (if floor is set)
          - alive=True
          - booting=False

        Why _app_alive() is required:
          A fresh health.json with alive=True can persist on disk for up to
          max_heartbeat_age seconds after a process crash. Checking only the
          file would grant health credit for a dead process. The process
          liveness check eliminates that false-positive window.

        This is STRICTER than heartbeat_stale()==False:
          - heartbeat_stale() returns False during startup grace even when
            the health file is missing or shows booting=True.
          - heartbeat_valid() returns False in ALL startup-grace cases AND
            when the process is not alive.

        Use this for: deploy guards, stable_ticks, circuit-breaker credit.
        Use heartbeat_stale() for: restart decisions only.
        """
        # Process must be alive - catches dead process before reading stale file
        if not self._app_alive():
            return False
        if not self.health_file.exists():
            return False
        try:
            mtime   = self.health_file.stat().st_mtime
            if time.time() - mtime > self.max_heartbeat_age:
                return False
            health  = json.loads(self.health_file.read_text(encoding="utf-8-sig"))
        except Exception:
            return False
        if not health.get("alive"):
            return False
        if health.get("booting"):
            return False
        # Must be from the process we own
        if self._expected_pid is not None:
            if int(health.get("pid") or 0) != self._expected_pid:
                return False
        if self._launch_mtime_floor is not None:
            if mtime < self._launch_mtime_floor:
                return False
        return True

    def _supervisor_state(self) -> str:
        """
        Return a single string describing the supervisor's current health view.
        Used in write_status() for unambiguous observability.

          healthy_ready            - app is fully healthy, valid heartbeat
          tolerated_startup_wait   - awaiting first heartbeat, within grace
          unhealthy_restart_required - app dead, stale heartbeat, or grace expired
        """
        if not self._app_alive():
            return "unhealthy_restart_required"
        if self.heartbeat_valid():
            return "healthy_ready"
        if self._awaiting_first_heartbeat and self._startup_mono_ts is not None:
            elapsed = time.monotonic() - self._startup_mono_ts
            if elapsed < self.startup_heartbeat_timeout_s:
                return "tolerated_startup_wait"
        return "unhealthy_restart_required"

    def app_is_healthy(self) -> bool:
        """True when the managed process is alive AND has emitted a valid
        current-process heartbeat. Delegates to heartbeat_valid() which
        enforces both the process-liveness and heartbeat-file checks."""
        return self.heartbeat_valid()

    #  -  -  Request handlers  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

    def process_supervisor_requests(self) -> None:
        """
        Process all *.json files in supervisor_requests/.
        Malformed/bad JSON is logged and skipped  -  never crashes the loop.
        """
        for path in sorted(self.sup_req_dir.glob("*.json")):
            try:
                raw = path.read_text(encoding="utf-8-sig")
            except Exception as exc:
                self.log(f"supervisor_request read error {path.name}: {exc}")
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    # unlink() is the only raising call.
                    pass
                continue

            try:
                req  = json.loads(raw)
            except Exception as exc:
                self.log(f"supervisor_request bad JSON {path.name}: {exc}")
                path.unlink(missing_ok=True)
                continue

            try:
                kind = str(req.get("type") or "")
                if kind == "restart":
                    reason = str(req.get("reason") or path.stem)
                    self.log(f"supervisor_request restart reason={reason!r}")
                    self.restart_app(reason=reason)
                elif kind == "rollback":
                    self.log("supervisor_request rollback")
                    self._do_rollback(req)
                elif kind == "shutdown":
                    self.log("supervisor_request shutdown")
                    self.stop_app(reason="shutdown_request")
                    path.unlink(missing_ok=True)
                    self.pid_lock.release()
                    raise SystemExit(0)
                elif kind == "reset_circuit_breaker":
                    self.log("supervisor_request reset_circuit_breaker")
                    self.circuit_breaker.force_reset()
                else:
                    self.log(f"supervisor_request unknown type={kind!r} in {path.name}")
            except SystemExit:
                raise
            except Exception as exc:
                self.log(f"supervisor_request handling error {path.name}: {exc}")
            finally:
                path.unlink(missing_ok=True)

    def _do_rollback(self, req: Dict[str, Any]) -> None:
        """
        Restore the most recent backup.
        Never includes ops/backups/ (prevents recursive backup growth).
        Never includes API-Key-Claude.txt.
        After restore, prunes backups older than backup_retention_count.
        """
        import shutil
        backups_root = self.project_root / "ops" / "backups"
        api_key_name = self.config.get("api_key_file", "API-Key-Claude.txt")

        if not backups_root.exists():
            self.log("rollback: no backups directory found")
            return

        candidates = sorted(
            (d for d in backups_root.iterdir() if d.is_dir()),
            reverse=True,
        )
        if not candidates:
            self.log("rollback: no backup directories found")
            return

        latest = candidates[0]
        self.log(f"rollback: restoring from {latest.name}")
        self.stop_app(reason="rollback")

        restored = skipped = 0
        for src in latest.rglob("*"):
            if not src.is_file():
                continue
            try:
                rel = src.relative_to(latest)
            except ValueError:
                # relative_to() raises only ValueError; src comes from
                # latest.rglob() so this is defence-in-depth.
                continue
            rel_str = str(rel)
            # Exclusions
            if rel_str.startswith("ops\\backups") or rel_str.startswith("ops/backups"):
                skipped += 1
                continue
            if rel_str == api_key_name or rel_str.endswith(f"\\{api_key_name}"):
                skipped += 1
                continue
            dst = self.project_root / rel
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                restored += 1
            except Exception as e:
                self.log(f"rollback copy failed {rel}: {e}")

        self.log(f"rollback: restored={restored} skipped={skipped} from {latest.name}")
        self._record_incident("INFO", "rollback_complete", "rollback", "ok",
                              detail=f"backup={latest.name} files={restored}")
        time.sleep(1.0)
        self.start_app(reason="post_rollback")
        # Prune old backups after successful restore
        self._prune_old_backups(backups_root)

    def _prune_old_backups(self, backups_root: Path) -> None:
        """
        Prune backup directories older than backup_retention_count.
        Never deletes the most recent N backups (configurable, default 10).
        Never includes API-Key-Claude.txt in any backup it touches.
        """
        retention = int(self.config.get("backup_retention_count", 10))
        if not backups_root.exists():
            return
        backups = sorted(
            (d for d in backups_root.iterdir() if d.is_dir()),
            reverse=True,
        )
        to_delete = backups[retention:]   # keep newest N, delete the rest
        for old_dir in to_delete:
            try:
                import shutil as _shutil
                _shutil.rmtree(old_dir, ignore_errors=True)
                self.log(f"pruned old backup: {old_dir.name}")
            except Exception as exc:
                self.log(f"backup prune failed {old_dir.name}: {exc}")

    #  -  -  Non-blocking deploy  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

    def process_deploy_requests(self) -> None:
        """
        Start a deploy in a background thread.
        Supervisor loop stays unblocked and continues health monitoring.
        Exactly one deploy at a time  -  concurrent deploys are rejected.
        """
        # Don't start another while one is running
        if self._deploy_thread and self._deploy_thread.is_alive():
            return
        if not self.app_is_healthy():
            return

        for path in sorted(self.deploy_req_dir.glob("*.json")):
            stem = path.stem
            if stem in self._deploy_in_progress:
                continue

            # Rename to .deploying to prevent re-pickup
            in_progress = path.with_suffix(".deploying")
            try:
                path.rename(in_progress)
            except Exception as exc:
                self.log(f"deploy rename failed {path.name}: {exc}")
                continue

            self._deploy_in_progress.add(stem)
            self._deploy_thread = threading.Thread(
                target=self._run_deploy_thread,
                args=(in_progress, stem),
                name=f"Deploy-{stem[:12]}",
                daemon=True,
            )
            self._deploy_thread.start()
            self.log(f"deploy {stem} started in background thread")
            break  # one at a time

    def _run_deploy_thread(self, path: Path, stem: str) -> None:
        result_path = self.deploy_res_dir / f"{stem}.json"
        cmd = [
            self.python_exe, str(self.deploy_script),
            "--request", str(path),
            "--result",  str(result_path),
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=120.0,
                # Same CREATE_NO_WINDOW rationale as _pid_alive above. This one
                # spawns self.python_exe (console python.exe, not pythonw), so
                # it is the most visible of the four - DEVNULL redirects the
                # streams but does NOT stop Windows allocating the console.
                creationflags=(0x08000000 if os.name == "nt" else 0),
            )
            self.log(f"deploy {stem} finished exit={proc.returncode}")
        except subprocess.TimeoutExpired:
            self.log(f"deploy {stem} TIMEOUT (120s)")
        except Exception as exc:
            self.log(f"deploy {stem} error: {exc}")
        finally:
            path.unlink(missing_ok=True)
            self._deploy_in_progress.discard(stem)

    #  -  -  Self-monitor bootstrap  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

    def _start_self_monitor(self) -> None:
        try:
            # Add ops/ to path so imports work when running as pythonw.exe
            ops_dir = str(self.project_root / "ops")
            if ops_dir not in sys.path:
                sys.path.insert(0, ops_dir)
            proj_dir = str(self.project_root)
            if proj_dir not in sys.path:
                sys.path.insert(0, proj_dir)

            from rc_incident_log     import IncidentLog
            from rc_state_validator import StateValidator
            from rc_self_monitor     import SelfMonitor

            profile_path = self.project_root / "config" / "self_monitor_profile.json"
            profile: Dict[str, Any] = {}
            try:
                if profile_path.exists():
                    profile = json.loads(profile_path.read_text(encoding="utf-8-sig"))
            except Exception:
                pass

            self._incident_log = IncidentLog(
                runtime_dir    = self.runtime_dir,
                retention_days = int(profile.get("incident_log_retention_days", 7)),
            )

            validator = None
            if profile.get("screen_validation_enabled"):
                validator = StateValidator(
                    project_root = self.project_root,
                    incident_log = self._incident_log,
                    interval_s   = float(profile.get("screen_validation_interval_s", 30)),
                )

            self._monitor = SelfMonitor(
                project_root      = self.project_root,
                runtime_dir       = self.runtime_dir,
                incident_log      = self._incident_log,
                state_validator   = validator,
                health_file       = self.health_file,
                max_heartbeat_age = self.max_heartbeat_age,
                supervisor_run_id = self.pid_lock._run_id,
            )

            if profile.get("resume_on_boot") and profile.get("enabled"):
                self._monitor.set_armed(True)

            self._monitor.start()
            self.log("SelfMonitor started")

        except Exception as exc:
            self.log(f"SelfMonitor start failed (non-fatal): {exc}")
            self._monitor = None

    def _record_incident(
        self, severity: str, trigger: str, action: str,
        result: str, detail: str = ""
    ) -> None:
        if self._monitor and hasattr(self._monitor, "incident_log"):
            try:
                self._monitor.incident_log.record(
                    severity=severity, subsystem="supervisor",
                    trigger=trigger, action=action, result=result, detail=detail,
                )
            except Exception:
                pass

    def _check_phase3(self) -> None:
        """Subordinate watch for the Phase 3 supervisor (agents.supervisor).
        Restart events surface via _record_incident + status.json. See the
        _Phase3Watcher class docstring for the frozen-file additive rationale.
        Exceptions are swallowed so a watcher fault never disturbs the main
        app lifecycle.
        """
        try:
            result = self._phase3_watcher.check()
        except Exception as exc:
            self.log(f"phase3_watcher error (non-fatal): {exc}")
            return
        if not result.get("acted"):
            return
        trigger = result.get("trigger", "unknown")
        state = result.get("state", "unknown")
        detail = (
            f"age={result.get('heartbeat_age_s')}s "
            f"pid={result.get('pid')}"
        )
        severity = "WARN" if state == "restarting" else "ERROR"
        self._record_incident(
            severity, f"phase3_{trigger}", "phase3_restart", state, detail=detail
        )

    #  -  -  Main loop  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

    def _verify_decisions_version(self) -> None:
        """Fail-closed check: resolved_decisions.json must match EXPECTED_DECISIONS_VERSION."""
        decisions_path = self.project_root / "agents" / "state" / "resolved_decisions.json"
        if not decisions_path.exists():
            raise RuntimeError(
                f"resolved_decisions.json not found at {decisions_path}; "                f"expected version {EXPECTED_DECISIONS_VERSION}"
            )
        try:
            data = json.loads(decisions_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(
                f"resolved_decisions.json is not valid JSON: {exc}"
            ) from exc
        actual = data.get("version")
        if actual != EXPECTED_DECISIONS_VERSION:
            raise RuntimeError(
                f"resolved_decisions.json version mismatch: "                f"expected {EXPECTED_DECISIONS_VERSION!r}, got {actual!r}"
            )
        self.log(f"decisions version verified: {actual}")


    def loop(self) -> None:
        # Acquire single-instance lock (RC-1 fix)
        if not self.pid_lock.acquire():
            self.log("ABORT: another supervisor is already running (PID lock held)")
            sys.exit(1)
        self.log(f"PID lock acquired pid={os.getpid()}")
        self._verify_decisions_version()

        try:
            # Bootstrap order (Phase 0.12):
            # 1. start_app() first - establishes _expected_pid, _launch_mtime_floor,
            #    awaiting_first_heartbeat, and calls write_status() internally.
            # 2. write_status() explicitly to guarantee status.json is on disk with
            #    the current supervisor_run_id before SelfMonitor reads it.
            # 3. _start_self_monitor() last - SelfMonitor's bootstrap guard will
            #    immediately find matching status.json and proceed normally.
            self.start_app(reason="supervisor_boot")
            self.write_status()   # ensure current-run status is on disk before monitor starts
            self._start_self_monitor()
            stable_ticks = 0

            while True:
                try:
                    #  -  -  Health check  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
                    if not self._app_alive():
                        stable_ticks = 0
                        self.log("app process not alive -- restarting")
                        self._record_incident("WARN", "process_exit",
                                              "app_restart", "pending")
                        self.start_app(reason="process_exit")

                    elif self.heartbeat_stale():
                        stable_ticks = 0
                        self.log("heartbeat stale -- restarting")
                        self._record_incident("WARN", "heartbeat_stale",
                                              "app_restart", "pending")
                        self.restart_app(reason="heartbeat_stale")

                    elif self.heartbeat_valid():
                        # Strictly healthy: valid current-process heartbeat.
                        # Only this branch accumulates stable_ticks and
                        # grants circuit-breaker credit. startup-grace
                        # tolerance (heartbeat_stale()==False but no valid
                        # heartbeat yet) does NOT increment stable_ticks.
                        stable_ticks += 1
                        if stable_ticks >= 30:   # 30s of validated healthy ticks
                            self.circuit_breaker.on_success()
                            stable_ticks = 0

                    # else: startup grace tolerated -- process alive, not restarting,
                    # but not yet validated. stable_ticks stays at 0.


                    #  -  -  Check circuit-breaker reset file  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
                    reset_file = self.runtime_dir / "reset_circuit_breaker.flag"
                    if reset_file.exists():
                        self.circuit_breaker.force_reset()
                        reset_file.unlink(missing_ok=True)
                        self.log("circuit breaker reset via flag file")

                    #  -  -  Process requests and deploys  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
                    # AUDIT-PHASE-2-OPS-001: restart_trigger.txt watcher.
                    # AUDIT 2026-04-28 (deferred-frozen): clear via
                    # tmp+rename so a writer racing the clear can't see
                    # the file mid-truncate. Pairs with the atomic-write
                    # helper used by writers (proposal 4.3).
                    try:
                        _tf = self.project_root / "restart_trigger.txt"
                        if _tf.exists() and _tf.stat().st_size > 0:
                            _tf_tmp = _tf.with_suffix(".clear.tmp")
                            _tf_tmp.write_text("", encoding="utf-8")
                            os.replace(_tf_tmp, _tf)
                            self.log("restart_trigger.txt detected -- restarting")
                            self.restart_app(reason="restart_trigger")
                    except (OSError, ValueError) as exc:
                        self.log(f"restart_trigger watcher: {exc}")
                    self.process_deploy_requests()
                    self.process_supervisor_requests()
                    self._check_phase3()
                    self.write_status()

                except SystemExit:
                    raise
                except Exception as exc:
                    self.log(f"supervisor loop error (non-fatal): {exc}")

                time.sleep(self.poll_interval)

        except SystemExit:
            self.log("supervisor exiting (SystemExit)")
            raise
        except Exception as exc:
            # Top-level containment: write fatal status before exit
            fatal_msg = f"FATAL supervisor crash: {type(exc).__name__}: {exc}"
            self.log(fatal_msg)
            try:
                atomic_write_json(self.status_file, {
                    "updated_at":  utc_now(),
                    "fatal":       True,
                    "fatal_error": fatal_msg,
                })
            except Exception:
                pass
            raise
        finally:
            self.pid_lock.release()
            if self._monitor:
                try:
                    self._monitor.stop()
                except Exception:
                    pass


#  -  -  Entry point  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args   = parser.parse_args()
    sup    = Supervisor(Path(args.config).resolve())
    sup.loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


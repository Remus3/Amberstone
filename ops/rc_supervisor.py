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

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Lifecycle authority:
#   START  â€” this supervisor (via start_app or adopt_existing_app)
#   STOP   â€” this supervisor (via stop_app, owned PID or adopted PID only)
#   RESTART â€” this supervisor (via restart_app, same rules)
#   ROLLBACK â€” this supervisor (via _do_rollback, triggered by supervisor_requests/)
#   MONITOR â€” SelfMonitor threads (inside this process)
#
# Nothing else may start main.py when supervisor is running.
# watchdog.ps1, restart.bat, restart_clean.bat are deprecated (see .DEPRECATED files).
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


# â”€â”€ Utilities â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

EXPECTED_DECISIONS_VERSION = "phase3-1.1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


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
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                stderr=subprocess.DEVNULL, text=True, timeout=5,
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


# â”€â”€ PID Lock â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class PidLock:
    """
    JSON lock file: {pid, start_time, run_id, locked_at}.
    The 'pid' field is kept as a top-level integer for backward compatibility
    with rc_league_watcher.ps1 which reads it as a plain number.
    """

    def __init__(self, lock_file: Path) -> None:
        self.lock_file = lock_file
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self._run_id = _new_id()

    def acquire(self) -> bool:
        my_pid  = os.getpid()
        my_time = time.time()

        if self.lock_file.exists():
            try:
                raw = self.lock_file.read_text(encoding="utf-8").strip()
                # Support both plain-PID (legacy) and JSON formats
                if raw.startswith("{"):
                    rec = json.loads(raw)
                    other_pid = int(rec.get("pid", 0))
                else:
                    other_pid = int(raw)
                if other_pid and other_pid != my_pid and _pid_alive(other_pid):
                    return False
            except Exception:
                pass  # corrupt / stale â€” overwrite

        payload = {
            "pid":        my_pid,
            "start_time": my_time,
            "run_id":     self._run_id,
            "locked_at":  utc_now(),
        }
        self.lock_file.write_text(json.dumps(payload), encoding="utf-8")
        time.sleep(0.05)
        try:
            written = json.loads(self.lock_file.read_text(encoding="utf-8"))
            return int(written.get("pid", 0)) == my_pid
        except Exception:
            return False

    def release(self) -> None:
        try:
            if not self.lock_file.exists():
                return
            raw = self.lock_file.read_text(encoding="utf-8").strip()
            if raw.startswith("{"):
                rec = json.loads(raw)
                if int(rec.get("pid", 0)) == os.getpid():
                    self.lock_file.unlink(missing_ok=True)
            else:
                if int(raw) == os.getpid():
                    self.lock_file.unlink(missing_ok=True)
        except Exception:
            pass


# â”€â”€ Circuit Breaker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    # â”€â”€ Public â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        """Explicit reset â€” triggered by reset_breaker file or command."""
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

    # â”€â”€ Internal â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
                # Treat as if tripped just now â€” will auto-clear after cooldown_s.
                self.tripped    = True
                self._trip_time = time.monotonic()
        except Exception:
            pass


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _new_id() -> str:
    import uuid
    return uuid.uuid4().hex[:16]


# â”€â”€ Supervisor â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        # _expected_pid    — the PID of the process WE launched (from Popen or adoption)
        # _launch_mtime_floor — wall-clock time just before Popen; any valid health.json
        #                       for THIS launch must have mtime >= this value.
        # Both cleared by stop_app(); set by start_app()/adopt.
        self._expected_pid:        Optional[int]   = None
        self._launch_mtime_floor:  Optional[float] = None  # time.time() at launch

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

    # â”€â”€ Logging â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def log(self, line: str) -> None:
        msg = f"[{utc_now()}] {line}\n"
        try:
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(msg)
        except Exception:
            pass

    # â”€â”€ Status â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    # â”€â”€ App alive check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _app_alive(self) -> bool:
        if self.process is not None and self.process.poll() is None:
            return True
        if self._adopted_pid is not None:
            if _pid_alive(self._adopted_pid):
                return True
            self._adopted_pid = None  # adopted process died
        return False

    # â”€â”€ Process adoption â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
            # Adoption: identity is known immediately from the live health file
            self._expected_pid         = pid
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

    # â”€â”€ Lifecycle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
                f"circuit_breaker TRIPPED â€” refusing restart reason={reason!r} "
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
        ALWAYS by owned PID or adopted PID â€” never by broad pattern matching.
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
                    except Exception:
                        pass
            self.process = None

        elif self._adopted_pid is not None:
            pid = self._adopted_pid
            if _pid_alive(pid):
                self.log(f"stopping adopted app pid={pid} reason={reason!r}")
                if not _kill_pid(pid):
                    self.log(f"kill_pid({pid}) failed â€” process may already be dead")
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
        self.write_status()

    def restart_app(self, reason: str) -> bool:
        self.stop_app(reason=reason)
        time.sleep(1.0)
        return self.start_app(reason=reason)

    # â”€â”€ Health â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        A heartbeat belongs to the current launch if:
          1. health["pid"] matches _expected_pid (the process we spawned)
          2. mtime >= _launch_mtime_floor (file was written after we launched)
        For adoption (_launch_mtime_floor is None), only pid is checked.
        """
        expected = self._expected_pid
        if expected is None:
            return False, "no_expected_pid"
        reported_pid = int(health.get("pid") or 0)
        if reported_pid != expected:
            return False, ("startup_rejected_wrong_pid_heartbeat:"
                           " expected=" + str(expected) + " got=" + str(reported_pid))
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

        # ── Startup grace phase ───────────────────────────────────────────────
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
                # First healthy heartbeat received — clear grace window
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

        # ── Normal operation (after first heartbeat or adopted process) ───────
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
        # PID check in normal operation: reject foreign/previous-run files
        if self._expected_pid is not None:
            reported_pid = int(health.get("pid") or 0)
            if reported_pid != self._expected_pid:
                self.log("heartbeat_wrong_pid: expected="
                         + str(self._expected_pid) + " got=" + str(reported_pid))
                return True
        self._on_first_heartbeat(health)
        return False

    def _on_first_heartbeat(self, health: Dict[str, Any]) -> None:
        """Update owned identity from a live heartbeat payload."""
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
        # Process must be alive — catches dead process before reading stale file
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

          healthy_ready            — app is fully healthy, valid heartbeat
          tolerated_startup_wait   — awaiting first heartbeat, within grace
          unhealthy_restart_required — app dead, stale heartbeat, or grace expired
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

    # â”€â”€ Request handlers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def process_supervisor_requests(self) -> None:
        """
        Process all *.json files in supervisor_requests/.
        Malformed/bad JSON is logged and skipped â€” never crashes the loop.
        """
        for path in sorted(self.sup_req_dir.glob("*.json")):
            try:
                raw = path.read_text(encoding="utf-8-sig")
            except Exception as exc:
                self.log(f"supervisor_request read error {path.name}: {exc}")
                try:
                    path.unlink(missing_ok=True)
                except Exception:
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
            except Exception:
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

    # â”€â”€ Non-blocking deploy â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def process_deploy_requests(self) -> None:
        """
        Start a deploy in a background thread.
        Supervisor loop stays unblocked and continues health monitoring.
        Exactly one deploy at a time â€” concurrent deploys are rejected.
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
            )
            self.log(f"deploy {stem} finished exit={proc.returncode}")
        except subprocess.TimeoutExpired:
            self.log(f"deploy {stem} TIMEOUT (120s)")
        except Exception as exc:
            self.log(f"deploy {stem} error: {exc}")
        finally:
            path.unlink(missing_ok=True)
            self._deploy_in_progress.discard(stem)

    # â”€â”€ Self-monitor bootstrap â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    # â”€â”€ Main loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
            # 1. start_app() first — establishes _expected_pid, _launch_mtime_floor,
            #    awaiting_first_heartbeat, and calls write_status() internally.
            # 2. write_status() explicitly to guarantee status.json is on disk with
            #    the current supervisor_run_id before SelfMonitor reads it.
            # 3. _start_self_monitor() last — SelfMonitor's bootstrap guard will
            #    immediately find matching status.json and proceed normally.
            self.start_app(reason="supervisor_boot")
            self.write_status()   # ensure current-run status is on disk before monitor starts
            self._start_self_monitor()
            stable_ticks = 0

            while True:
                try:
                    # â”€â”€ Health check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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


                    # â”€â”€ Check circuit-breaker reset file â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                    reset_file = self.runtime_dir / "reset_circuit_breaker.flag"
                    if reset_file.exists():
                        self.circuit_breaker.force_reset()
                        reset_file.unlink(missing_ok=True)
                        self.log("circuit breaker reset via flag file")

                    # â”€â”€ Process requests and deploys â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                    # AUDIT-PHASE-2-OPS-001: restart_trigger.txt watcher
                    try:
                        _tf = self.project_root / "restart_trigger.txt"
                        if _tf.exists() and _tf.stat().st_size > 0:
                            _tf.write_text("", encoding="utf-8")
                            self.log("restart_trigger.txt detected -- restarting")
                            self.restart_app(reason="restart_trigger")
                    except Exception:
                        pass
                    self.process_deploy_requests()
                    self.process_supervisor_requests()
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


# â”€â”€ Entry point â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args   = parser.parse_args()
    sup    = Supervisor(Path(args.config).resolve())
    sup.loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


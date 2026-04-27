"""
ops/rc_self_monitor.py  â€”  Phase 0.1 corrective rewrite

Changes vs Phase 0:
  [1]  Ladder escalation fixed: health_check no longer resets ladder/consecutive_fails.
       Escalation advances on EACH unhealthy tick regardless of whether the current
       step "succeeded".  Reset happens only after a VERIFIED healthy tick.
  [4]  _check_health() now uses subsystem fields from health.json:
       - ui_loop_alive (from Tk pulse timestamp)
       - game_poll_worker_alive (from worker pulse)
       - alive AND both subsystems must be healthy for a clean pass
       - Plain alive=True alone is no longer sufficient.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_LADDER = [
    "health_check",
    "thread_restart",
    "panel_rebuild",
    "hot_reload",
    "app_restart",
    "rollback",
]

_DEFAULT_PROFILE: Dict[str, Any] = {
    "enabled":                      False,
    "resume_on_boot":               False,
    "auto_retry":                   True,
    "max_restart_attempts":         5,
    "restart_window_seconds":       120,
    "restart_cooldown_seconds":     300,
    "max_hot_reload_attempts":      3,
    "screen_validation_enabled":    False,
    "screen_validation_interval_s": 30,
    "safe_live_patch_only":         True,
    "incident_log_retention_days":  7,
    "remediation_ladder":           _LADDER,
    "allowed_hot_reload_modules": [
        "core.theme",
        "tft.tft_data",
        "tft.tft_pbe_data",
        "champion_profiles",
        "role_profiles",
        "composition_advisor",
        "item_advisor",
    ],
    "allowed_panel_rebuild_keys": [
        "game_bottom",
        "game_rtop",
        "game_rbot",
    ],
}

# How many ticks a subsystem pulse may lag before we treat it as dead
_PULSE_STALE_S = 10.0


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return None


class CircuitBreaker:
    def __init__(
        self,
        max_restarts: int   = 5,
        window_s:     float = 120.0,
        cooldown_s:   float = 300.0,
    ) -> None:
        self.max_restarts  = max_restarts
        self.window_s      = window_s
        self.cooldown_s    = cooldown_s
        self._restart_times: List[float] = []
        self.tripped        = False
        self._trip_time:    Optional[float] = None

    def record_restart(self) -> bool:
        now = time.monotonic()
        if self.tripped and self._trip_time is not None:
            if now - self._trip_time >= self.cooldown_s:
                self.reset()
        if self.tripped:
            return False
        self._restart_times = [t for t in self._restart_times if now - t < self.window_s]
        self._restart_times.append(now)
        if len(self._restart_times) > self.max_restarts:
            self.tripped    = True
            self._trip_time = now
            return False
        return True

    def reset(self) -> None:
        self._restart_times = []
        self.tripped         = False
        self._trip_time      = None

    @property
    def seconds_until_reset(self) -> float:
        if not self.tripped or self._trip_time is None:
            return 0.0
        return max(0.0, self.cooldown_s - (time.monotonic() - self._trip_time))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tripped":             self.tripped,
            "restart_count":       len(self._restart_times),
            "max_restarts":        self.max_restarts,
            "window_s":            self.window_s,
            "cooldown_s":          self.cooldown_s,
            "seconds_until_reset": round(self.seconds_until_reset, 1),
        }


class SelfMonitor:
    """
    Subordinate health monitor for Riot Commander.  Created and started by
    Supervisor after start_app() + write_status() have established current-run
    state.  Call start() to begin monitoring; call stop() to shut down.

    Phase 0 (FROZEN) — do not change health semantics without an explicit request.

    Health classification (_check_health returns one of three states):
      "healthy"   All of the following hold simultaneously:
                    - Bootstrap guard passed (status.json present, readable,
                      supervisor_run_id matches this monitor's binding)
                    - supervisor process_running=True
                    - health.json exists, pid == expected_pid, mtime fresh
                    - alive=True, booting=False
                    - run_id / session_id match supervisor owned values (if known)
                    - supervisor_state == "healthy_ready"
                    - subsystem checks pass (provider, ui_loop, game_poll_worker)
      "tolerated" Within the bootstrap window OR supervisor startup grace:
                    no escalation, no ladder reset, no incident log entry.
      "unhealthy" Genuine failure: escalate ladder, increment consecutive_fails.

    Ladder semantics:
      - "unhealthy" tick: consecutive_fails++, execute ladder[ladder_idx].
      - "healthy" tick:   consecutive_fails=0, ladder_idx=0, CB reset.
      - "tolerated" tick: no counter changes.
      - ladder_idx advances only after a non-health_check step is issued.

    Supervisor binding:
      Pass supervisor_run_id=pid_lock._run_id on construction so the bootstrap
      guard can reject status.json files that belong to a previous supervisor run.
      The guard is disabled (bypassed) when supervisor_run_id is empty.
    """

    TICK_INTERVAL = 5.0
    CMD_INTERVAL  = 1.0

    def __init__(
        self,
        project_root:      Path,
        runtime_dir:       Path,
        incident_log,
        state_validator,
        health_file:       Path,
        max_heartbeat_age: float = 15.0,
        supervisor_run_id: str   = "",
    ) -> None:
        self.project_root      = Path(project_root)
        self.runtime_dir       = Path(runtime_dir)
        self.incident_log      = incident_log
        self.state_validator  = state_validator
        self.health_file       = Path(health_file)
        self.max_heartbeat_age = max_heartbeat_age

        # Bootstrap identity: the supervisor_run_id this monitor was created for.
        # _check_health() rejects status.json that belongs to a different supervisor
        # run (stale from a previous supervisor process) until the current run's
        # status is established. Empty string means no binding (legacy/test mode).
        self._supervisor_run_id: str = supervisor_run_id

        # Phase 0.13: bounded bootstrap window.
        # _seen_current_supervisor_status: flips True the first time _check_health()
        #   reads a status.json whose supervisor_run_id matches self._supervisor_run_id.
        #   After that, missing/invalid/stale status is no longer tolerated.
        # _bootstrap_deadline_mono: monotonic deadline past which missing/stale status
        #   is unhealthy even if _seen_current_supervisor_status is still False.
        #   Set to start() time + _BOOTSTRAP_GRACE_S when start() is called.
        self._seen_current_supervisor_status: bool  = False
        self._bootstrap_deadline_mono:        float = 0.0  # set in start()

        self._profile_path = self.project_root / "config" / "self_monitor_profile.json"
        self._state_path   = self.runtime_dir / "monitor_state.json"
        self._kill_flag    = self.runtime_dir / "self_monitor_off.flag"
        self._pause_flag   = self.runtime_dir / "monitor_paused.flag"
        self._cmd_dir      = self.runtime_dir / "monitor_commands"
        self._sup_req_dir  = self.runtime_dir / "supervisor_requests"
        self._ctrl_cmd_dir = self.runtime_dir / "control" / "commands"
        self._ctrl_res_dir = self.runtime_dir / "control" / "results"

        for d in [self._cmd_dir, self._sup_req_dir,
                  self._ctrl_cmd_dir, self._ctrl_res_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # â”€â”€ Runtime state (persisted each tick) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        self._ladder_idx        = 0
        self._consecutive_fails = 0
        self._last_success_ts   = ""
        self._last_failure_ts   = ""
        self._last_action       = "none"
        self._last_result       = "ok"
        self._hot_reload_count  = 0
        self._armed             = False
        self._paused            = False
        self._safe_mode         = False

        self.circuit_breaker = CircuitBreaker()
        self._stop_event     = threading.Event()
        self._threads:       List[threading.Thread] = []

        # Phase 0.3 fix 3: monotonic timestamp when worker was first seen dead.
        # Used for client-mode grace-period detection in _check_health().
        self._worker_dead_since: Optional[float] = None

        # _startup_grace_s: used ONLY as fallback in the booting=True check (step 5)
        # when supervisor status.json is unavailable and a started_at timestamp is
        # present in the health payload. Primary grace authority is the supervisor
        # status.json field awaiting_first_heartbeat / supervisor_state.
        self._startup_grace_s: float = 30.0  # must match supervisor startup_heartbeat_timeout_s
        # _monitor_start_mono: set in start(); no longer used for grace decisions.
        # Retained for state reporting and external introspection only.
        self._monitor_start_mono: float = 0.0

        self._restore_state()

    # â”€â”€ Public â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def start(self) -> None:
        if self._threads:
            return
        # Record start time for state reporting; no longer drives grace decisions.
        self._monitor_start_mono: float = time.monotonic()
        # Bootstrap deadline: after this monotonic time, missing/stale supervisor
        # status transitions from "tolerated" to "unhealthy" even if
        # _seen_current_supervisor_status has never been set.
        self._bootstrap_deadline_mono = time.monotonic() + self._BOOTSTRAP_GRACE_S
        t1 = threading.Thread(target=self._monitor_loop,
                               name="SelfMonitor-Main", daemon=True)
        t2 = threading.Thread(target=self._command_loop,
                               name="SelfMonitor-Cmd",  daemon=True)
        self._threads.extend([t1, t2])
        for t in self._threads:
            t.start()
        self.incident_log.record(
            severity="INFO", subsystem="monitor", trigger="startup",
            action="monitor_on", result="ok",
            detail=f"SelfMonitor started armed={self._armed}",
        )

    def stop(self) -> None:
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=3.0)
        self._threads.clear()
        self._write_state()

    def set_armed(self, armed: bool) -> None:
        self._armed = armed
        self._write_state()

    # â”€â”€ Monitor loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as exc:
                self.incident_log.record(
                    severity="ERROR", subsystem="monitor",
                    trigger="monitor_loop_crash", action="none", result="failed",
                    detail=str(exc),
                )
            self._stop_event.wait(self.TICK_INTERVAL)

    def _tick(self) -> None:
        profile = self._load_profile()

        # Kill switch â€” checked first every tick
        if self._kill_flag.exists():
            if self._armed:
                self._armed  = False
                self._paused = False
                self.incident_log.record(
                    severity="WARN", subsystem="monitor",
                    trigger="kill_flag_detected", action="monitor_off", result="ok",
                    detail="self_monitor_off.flag found â€” auto-repair disabled",
                )
            self._write_state(profile)
            return

        self._paused = self._pause_flag.exists()

        if not profile.get("enabled", False):
            self._armed = False
            self._write_state(profile)
            return

        self._armed = True

        # State validator (renamed from state_validator)
        if (self.state_validator is not None
                and profile.get("screen_validation_enabled", False)):
            try:
                self.state_validator.interval_s = float(
                    profile.get("screen_validation_interval_s", 30))
                self.state_validator.maybe_run()
            except Exception:
                pass

        self._maybe_write_summary(profile)

        # -- Health check -------------------------------------------------------
        # Phase 0.9: _check_health() returns (state, detail) where state is
        # "healthy", "tolerated", or "unhealthy".
        #   healthy   - verified good, reset ladder
        #   tolerated - startup grace / pid mismatch within grace;
        #               do NOT escalate, do NOT reset ladder
        #   unhealthy - genuine failure, escalate ladder
        health_state, health_detail = self._check_health()

        if health_state == "healthy":
            if self._consecutive_fails > 0:
                self.incident_log.record(
                    severity="INFO", subsystem="monitor",
                    trigger="health_recovered", action="none", result="ok",
                    detail=f"after {self._consecutive_fails} consecutive failures",
                )
            # Reset ONLY after a verified healthy tick
            self._consecutive_fails = 0
            self._ladder_idx        = 0
            self._hot_reload_count  = 0
            self._last_success_ts   = _utc()
            self.circuit_breaker.reset()
            self._write_state(profile)
            return

        if health_state == "tolerated":
            # Startup grace or supervisor-aligned wait.
            # Do not escalate ladder, do not reset ladder.
            # Not logged at WARN to avoid noise during normal startup.
            self._write_state(profile)
            return

        # health_state == "unhealthy" -- fall through to escalation

        # â”€â”€ Health failure â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        self._consecutive_fails += 1
        self._last_failure_ts   = _utc()
        self.incident_log.record(
            severity="WARN", subsystem="monitor",
            trigger="health_check_failed", action="none", result="ok",
            detail=f"consecutive_fails={self._consecutive_fails} {health_detail}",
        )

        if self._paused or self._safe_mode:
            self._write_state(profile)
            return

        if not profile.get("auto_retry", True):
            self._write_state(profile)
            return

        # â”€â”€ Execute current ladder step â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        ladder = profile.get("remediation_ladder", _LADDER)
        idx    = min(self._ladder_idx, len(ladder) - 1)
        step   = ladder[idx]

        t0          = time.monotonic()
        issued      = self._execute_step(step, profile)
        duration_ms = int((time.monotonic() - t0) * 1000)

        self._last_action = step
        self._last_result = "issued" if issued else "failed_to_issue"

        self.incident_log.record(
            severity="INFO" if issued else "ERROR",
            subsystem="monitor",
            trigger=f"health_failed_consecutive_{self._consecutive_fails}",
            action=step,
            result=self._last_result,
            duration_ms=duration_ms,
        )

        # â”€â”€ Advance ladder unconditionally after each unhealthy tick â”€â”€â”€â”€â”€â”€
        # health_check is the only "wait and observe" step â€” it does not
        # advance the ladder on the FIRST failure (we need consecutive_failsâ‰¥2
        # before escalating past it).  All subsequent steps advance regardless
        # of whether the command was successfully issued.
        if step == "health_check":
            # Stay at health_check for the first failure; escalate on the second.
            if self._consecutive_fails >= 2:
                self._ladder_idx = min(idx + 1, len(ladder) - 1)
        else:
            # Always advance â€” issuing the command is the action, not waiting
            # for the app to recover (recovery is detected on the next healthy tick).
            self._ladder_idx = min(idx + 1, len(ladder) - 1)

        self._write_state(profile)

    # â”€â”€ Remediation steps â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _execute_step(self, step: str, profile: Dict[str, Any]) -> bool:
        """Issue one remediation action. Returns True if command was dispatched."""
        if step == "health_check":
            return True  # observe-only

        if step == "thread_restart":
            cmd_id = self._send_devruntime_command({
                "type": "callback", "name": "restart_game_poll", "kwargs": {},
            })
            return self._wait_for_command_result(cmd_id, timeout=8.0)

        if step == "panel_rebuild":
            keys    = profile.get("allowed_panel_rebuild_keys", [])
            any_ok  = False
            for key in keys:
                cmd_id = self._send_devruntime_command({
                    "type": "rebuild_named_ui", "name": key, "kwargs": {},
                })
                if self._wait_for_command_result(cmd_id, timeout=5.0):
                    any_ok = True
            return any_ok

        if step == "hot_reload":
            max_hl = int(profile.get("max_hot_reload_attempts", 3))
            if self._hot_reload_count >= max_hl:
                self.incident_log.record(
                    severity="WARN", subsystem="monitor",
                    trigger="hot_reload_exhausted",
                    action="hot_reload", result="skipped",
                    detail=f"count={self._hot_reload_count} max={max_hl}",
                )
                return False
            modules = profile.get("allowed_hot_reload_modules", [])
            if not modules:
                return False
            cmd_id = self._send_devruntime_command({
                "type": "reload_safe_modules", "modules": modules,
            })
            ok = self._wait_for_command_result(cmd_id, timeout=12.0)
            if ok:
                self._hot_reload_count += 1
            return ok

        if step == "app_restart":
            if not self.circuit_breaker.record_restart():
                self.incident_log.record(
                    severity="WARN", subsystem="monitor",
                    trigger="circuit_breaker_tripped",
                    action="app_restart", result="skipped",
                    detail=f"cooldown={self.circuit_breaker.seconds_until_reset:.0f}s",
                )
                return False
            req_id   = f"monitor-restart-{int(time.time())}"
            req_path = self._sup_req_dir / f"{req_id}.json"
            _atomic_write(req_path, {
                "type": "restart", "reason": "monitor_health_failure", "at": _utc(),
            })
            self._hot_reload_count = 0
            return True

        if step == "rollback":
            req_id   = f"monitor-rollback-{int(time.time())}"
            req_path = self._sup_req_dir / f"{req_id}.json"
            _atomic_write(req_path, {
                "type": "rollback", "reason": "monitor_repeated_failure", "at": _utc(),
            })
            return True

        return False

    # â”€â”€ Health check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    # Grace period: how long a dead poll worker is tolerated in client mode.
    _WORKER_DEAD_CLIENT_GRACE_S: float = 30.0

    # Bootstrap grace: how long to tolerate missing/stale supervisor status before
    # the bootstrap guard escalates to "unhealthy". Must be >= supervisor startup
    # grace (30s default) to avoid false escalation on slow starts.
    _BOOTSTRAP_GRACE_S: float = 60.0

    # ── Supervisor status reader ──────────────────────────────────────────────

    def _read_supervisor_status(self) -> Optional[Dict[str, Any]]:
        """Read ops/runtime/status.json safely. Returns None on any error."""
        status_path = self.runtime_dir / "status.json"
        try:
            if status_path.exists():
                return json.loads(status_path.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
        return None

    def _supervisor_awaiting_first_heartbeat(self) -> bool:
        """[legacy — not called internally; retained for external introspection]
        True if supervisor status.json says awaiting_first_heartbeat=True."""
        status = self._read_supervisor_status()
        if status is None:
            return False
        return bool(status.get("awaiting_first_heartbeat", False))

    def _supervisor_expected_pid(self) -> Optional[int]:
        """[legacy — not called internally; retained for external introspection]
        Return expected_pid from supervisor status.json, or None if unavailable."""
        status = self._read_supervisor_status()
        if status is None:
            return None
        v = status.get("expected_pid")
        return int(v) if v is not None else None

    def _supervisor_state_str(self) -> str:
        """[legacy — not called internally; retained for external introspection]
        Return supervisor_state string from status.json, or '' if unavailable."""
        status = self._read_supervisor_status()
        if status is None:
            return ""
        return str(status.get("supervisor_state") or "")

    # ── Health check ──────────────────────────────────────────────────────────
    #
    # Phase 0.9: _check_health() now returns a 3-value state string rather than
    # a plain bool, so _tick() can distinguish:
    #   "healthy"  — verified healthy; resets ladder
    #   "tolerated" — startup grace / identity mismatch within grace; NO ladder reset
    #   "unhealthy" — genuine failure; escalate ladder
    #
    # The public interface is kept as tuple[str, str] = (state, detail).

    def _check_health(self) -> tuple[str, str]:
        """
        Return (state: str, detail: str) where state is one of:

          "healthy"   — ALL of the following are simultaneously true:
                        - Bootstrap guard passed: supervisor status.json is
                          present, readable, and belongs to this supervisor run
                        - supervisor process_running=True
                        - health.json exists, pid matches expected_pid, mtime fresh
                        - alive=True, booting=False
                        - run_id matches owned_run_id (if both are known)
                        - session_id matches owned_session_id (if both are known)
                        - supervisor_state == "healthy_ready"
                        - subsystem checks pass (provider, ui_loop, game_poll_worker)

          "tolerated" — do NOT escalate, do NOT reset ladder. Returned when:
                        - bootstrap guard: status.json missing, invalid, or stale
                          run_id — but still within the 60-second bootstrap window
                        - startup grace: health.json missing, stale, booting=True,
                          or wrong-pid while supervisor reports tolerated_startup_wait

          "unhealthy" — genuine failure requiring remediation. Returned when:
                        - bootstrap guard fails AFTER bootstrap window closes, OR
                          after current supervisor status has been seen at least once
                        - any health check (0-8) fails outside of startup grace

        Check order (Phase 0.13a final):
          Bootstrap guard (stateful, FIRST):
            - reads status.json; distinguishes missing / invalid / run_id-mismatch
            - tolerated within 60s bootstrap window or before first match
            - unhealthy after window or after first match was seen
            - sets _seen_current_supervisor_status=True on first run_id match
          0.  process_running gate (supervisor status)
          1.  health file existence
          2.  Read file (capture age + payload; NO stale-age rejection yet)
          3.  PID identity check (before stale-age, so wrong-pid stale files
              return "tolerated" within grace rather than "unhealthy")
          2b. Stale-age rejection (after pid; gated by supervisor startup grace)
          4.  alive=True check
          5.  booting=False check (with supervisor-grace and started_at fallback)
          6.  run_id / session_id identity match against supervisor owned values
          7.  supervisor_state must be "healthy_ready"
          8.  Subsystem checks (last_state_provider_ok, ui_loop_alive,
              game_poll_worker_alive with in-game vs client-mode grace)

        Status authority:
          supervisor status.json is the sole authoritative source for process
          identity, startup grace, and readiness state. If status.json is missing
          or belongs to a different supervisor run after the bootstrap window,
          _check_health() returns "unhealthy" regardless of health.json contents.
        """
        # -- Bootstrap guard (Phase 0.13) -----------------------------------------
        # Before any health evaluation, confirm that the supervisor status on disk
        # belongs to THIS supervisor run. The guard has three phases:
        #
        #   A) _seen_current_supervisor_status == False AND within bootstrap deadline:
        #      - status.json missing           -> tolerated, detail: bootstrap_waiting...
        #      - invalid JSON / read error     -> tolerated, detail: bootstrap_invalid...
        #      - supervisor_run_id mismatch    -> tolerated, detail: bootstrap_rejecting...
        #      - run_id matches                -> _seen_current_supervisor_status = True,
        #                                         proceed to normal health checks
        #
        #   B) _seen_current_supervisor_status == True (already saw matching status):
        #      - status.json missing           -> unhealthy (not tolerated any more)
        #      - invalid JSON / read error     -> unhealthy
        #      - supervisor_run_id mismatch    -> unhealthy
        #      - run_id matches                -> proceed normally
        #
        #   C) Bootstrap deadline expired without ever seeing matching status:
        #      - all status failures           -> unhealthy
        #
        # Disabled when self._supervisor_run_id == "" (legacy/test mode).
        if self._supervisor_run_id:
            # Read status.json with explicit distinction between three failure modes:
            #   _bs_kind == "missing"  : file does not exist on disk
            #   _bs_kind == "invalid"  : file exists but could not be parsed
            #   _bs_kind == "ok"       : file read and parsed successfully
            _bs_kind:       str            = "missing"
            _bs_status_raw: Optional[dict] = None
            _status_path = self.runtime_dir / "status.json"
            if _status_path.exists():
                try:
                    _bs_status_raw = json.loads(_status_path.read_text(encoding="utf-8-sig"))
                    _bs_kind = "ok"
                except Exception:
                    _bs_kind = "invalid"   # exists but unreadable / bad JSON
            # else: _bs_kind stays "missing"

            _within_bootstrap = (not self._seen_current_supervisor_status
                                  and time.monotonic() < self._bootstrap_deadline_mono)

            if _bs_kind != "ok":
                # File missing or invalid -- classify by phase and kind
                if _within_bootstrap:
                    _tol_detail = (
                        "bootstrap_waiting_for_current_supervisor_status"
                        if _bs_kind == "missing"
                        else "bootstrap_invalid_supervisor_status"
                    )
                    return "tolerated", _tol_detail
                # Steady-state or deadline-expired: unhealthy
                _unhy_detail = (
                    "unhealthy_supervisor_status_missing"
                    if _bs_kind == "missing"
                    else "unhealthy_supervisor_status_invalid"
                )
                return "unhealthy", _unhy_detail

            # File parsed OK -- check supervisor_run_id
            _bs_run_id = str(_bs_status_raw.get("supervisor_run_id") or "")
            if _bs_run_id != self._supervisor_run_id:
                _mismatch_detail = (
                    "bootstrap_rejecting_stale_supervisor_status:"
                    " expected=" + self._supervisor_run_id
                    + " got=" + (_bs_run_id or "<missing>")
                )
                if _within_bootstrap:
                    return "tolerated", _mismatch_detail
                return "unhealthy", (
                    "unhealthy_supervisor_run_id_mismatch:"
                    " expected=" + self._supervisor_run_id
                    + " got=" + (_bs_run_id or "<missing>")
                )

            # Run ID matches this supervisor: bootstrap is satisfied.
            self._seen_current_supervisor_status = True


        # Read supervisor status once per check (cheap local file read)
        sup_status          = self._read_supervisor_status()
        sup_expected_pid:   Optional[int]  = None
        sup_owned_run_id:   Optional[str]  = None
        sup_owned_session_id: Optional[str] = None
        sup_process_running: Optional[bool] = None  # None = status unavailable
        sup_awaiting:        bool           = False
        sup_state:           str            = ""

        if sup_status is not None:
            v = sup_status.get("expected_pid")
            sup_expected_pid     = int(v) if v is not None else None
            sup_owned_run_id     = str(sup_status.get("owned_run_id") or "") or None
            sup_owned_session_id = str(sup_status.get("owned_session_id") or "") or None
            pr = sup_status.get("process_running")
            sup_process_running  = bool(pr) if pr is not None else None
            sup_awaiting         = bool(sup_status.get("awaiting_first_heartbeat", False))
            sup_state            = str(sup_status.get("supervisor_state") or "")

        within_supervisor_grace = (
            sup_awaiting
            or sup_state == "tolerated_startup_wait"
        )

        # ── 0. Process-running gate ───────────────────────────────────────────────
        # If supervisor reports the managed process is NOT running and we are
        # not in startup grace, the app is dead regardless of what health.json says.
        if sup_process_running is False and not within_supervisor_grace:
            self._worker_dead_since = None
            return "unhealthy", "process_running=False (supervisor reports dead)"

        # ── 1. Health file existence ───────────────────────────────────────────────
        if not self.health_file.exists():
            self._worker_dead_since = None
            if within_supervisor_grace:
                return "tolerated", "startup_grace: health_file_missing"
            return "unhealthy", "health_file_missing"

        # ── 2. Read file (always — we need pid/run_id to classify correctly) ──────────
        # NOTE: The stale-age rejection (age > max_heartbeat_age) is applied AFTER the
        # startup-grace and identity checks below. This ensures a stale previous-run
        # health file during supervisor startup grace returns "tolerated" (not "unhealthy")
        # because the pid/run_id mismatch check fires first.
        # Strict stale rejection without grace context appears at check 2b below.
        try:
            age     = time.time() - self.health_file.stat().st_mtime
            payload = json.loads(self.health_file.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            self._worker_dead_since = None
            return "unhealthy", f"health_read_error: {exc}"

        # ── 3. PID identity check (before stale-age rejection) ───────────────────────
        # If supervisor has a known expected_pid, verify the file belongs to it.
        # A stale previous-run file will be caught here (wrong pid -> tolerated/unhealthy)
        # BEFORE the stale-age check, so startup grace semantics are honoured.
        if sup_expected_pid is not None:
            file_pid = int(payload.get("pid") or 0)
            if file_pid != sup_expected_pid:
                self._worker_dead_since = None
                if within_supervisor_grace:
                    return (
                        "tolerated",
                        "startup_grace: pid_mismatch expected="
                        + str(sup_expected_pid) + " got=" + str(file_pid),
                    )
                return (
                    "unhealthy",
                    "pid_mismatch expected="
                    + str(sup_expected_pid) + " got=" + str(file_pid),
                )

        # ── 2b. Stale-age rejection (after pid check; gated by grace) ────────────────
        # Now that we know the file is from the correct pid (or pid unknown), apply the
        # age-based stale check. During supervisor startup grace, a stale current-process
        # boot marker is tolerated. After grace, stale always means unhealthy.
        if age > self.max_heartbeat_age:
            self._worker_dead_since = None
            if within_supervisor_grace:
                return "tolerated", f"startup_grace: heartbeat_stale age={age:.0f}s (correct pid, within grace)"
            return "unhealthy", f"heartbeat_stale age={age:.0f}s"

        # ── 4. alive check ───────────────────────────────────────────────────────────
        if not payload.get("alive"):
            self._worker_dead_since = None
            return "unhealthy", "alive=False"

        # ── 5. booting check ────────────────────────────────────────────────────────
        if payload.get("booting"):
            self._worker_dead_since = None
            if within_supervisor_grace:
                return "tolerated", "startup_grace: booting=True (supervisor awaiting)"
            started_at_str = str(payload.get("started_at") or "")
            if started_at_str:
                try:
                    from datetime import datetime, timezone as _tz
                    started_dt = datetime.fromisoformat(started_at_str)
                    boot_age_s = (
                        datetime.now(_tz.utc) - started_dt
                    ).total_seconds()
                    if boot_age_s < self._startup_grace_s:
                        return "tolerated", "startup_grace: booting=True (started_at fallback)"
                except Exception:
                    pass
            return "unhealthy", "booting=True (startup grace expired)"

        # ── 6. run_id / session_id identity match ────────────────────────────────────
        # When supervisor has established owned_run_id, the health file must match.
        # Wrong run/session within grace: tolerated (still starting up).
        # Wrong run/session outside grace: unhealthy (orphaned or stale file).
        if sup_owned_run_id is not None:
            file_run_id = str(payload.get("run_id") or "")
            if file_run_id and file_run_id != sup_owned_run_id:
                self._worker_dead_since = None
                if within_supervisor_grace:
                    return (
                        "tolerated",
                        "startup_grace: run_id_mismatch expected="
                        + sup_owned_run_id + " got=" + file_run_id,
                    )
                return (
                    "unhealthy",
                    "run_id_mismatch expected="
                    + sup_owned_run_id + " got=" + file_run_id,
                )

        if sup_owned_session_id is not None:
            file_session_id = str(payload.get("session_id") or "")
            if file_session_id and file_session_id != sup_owned_session_id:
                self._worker_dead_since = None
                if within_supervisor_grace:
                    return (
                        "tolerated",
                        "startup_grace: session_id_mismatch",
                    )
                return "unhealthy", "session_id_mismatch"

        # ── 7. Supervisor readiness gate ─────────────────────────────────────────────
        # Only return "healthy" when supervisor also considers the app ready.
        # If supervisor state is known but NOT healthy_ready, the app may have
        # just been adopted or is still transitioning.
        if sup_state and sup_state != "healthy_ready":
            if within_supervisor_grace:
                return "tolerated", "startup_grace: supervisor_state=" + sup_state
            return "unhealthy", "supervisor_state=" + sup_state

        # ── 8. Subsystem checks (app confirmed running, not booting) ─────────────────

        if "last_state_provider_ok" in payload:
            if not payload["last_state_provider_ok"]:
                self._worker_dead_since = None
                return "unhealthy", "last_state_provider_ok=False"

        if "ui_loop_alive" in payload:
            if not payload["ui_loop_alive"]:
                age_note = (
                    " pulse_age=" + str(payload.get("ui_pulse_age_s")) + "s"
                    if "ui_pulse_age_s" in payload else ""
                )
                self._worker_dead_since = None
                return "unhealthy", "ui_loop_alive=False" + age_note

        if "game_poll_worker_alive" in payload:
            worker_alive = bool(payload["game_poll_worker_alive"])
            has_game     = bool(payload.get("has_game", False))
            if worker_alive:
                self._worker_dead_since = None
            else:
                now = time.monotonic()
                if self._worker_dead_since is None:
                    self._worker_dead_since = now
                dead_for_s = now - self._worker_dead_since
                if has_game:
                    worker_age = payload.get("game_poll_worker_age_s")
                    return "unhealthy", (
                        "game_poll_worker_alive=False (game active age="
                        + str(worker_age) + "s)"
                    )
                else:
                    if dead_for_s >= self._WORKER_DEAD_CLIENT_GRACE_S:
                        return "unhealthy", (
                            f"game_poll_worker_alive=False (client mode "
                            f"dead_for={dead_for_s:.0f}s >= grace={self._WORKER_DEAD_CLIENT_GRACE_S:.0f}s)"
                        )
        else:
            self._worker_dead_since = None

        detail = "last_command_ok=False" if not payload.get("last_command_ok", True) else ""
        return "healthy", detail

    # â”€â”€ Command loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _command_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                for path in sorted(self._cmd_dir.glob("*.json")):
                    self._handle_command_file(path)
            except Exception:
                pass
            self._stop_event.wait(self.CMD_INTERVAL)

    def _handle_command_file(self, path: Path) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            path.unlink(missing_ok=True)
            return

        action  = str(payload.get("action") or "status")
        result: Dict[str, Any] = {"action": action, "handled_at": _utc(), "ok": False}
        profile = self._load_profile()

        try:
            if action == "on":
                profile["enabled"]        = True
                profile["resume_on_boot"] = True
                _atomic_write(self._profile_path, profile)
                self._armed  = True
                self._paused = False
                self._kill_flag.unlink(missing_ok=True)
                self._pause_flag.unlink(missing_ok=True)
                result.update({"ok": True, "enabled": True})
                self.incident_log.record(
                    severity="INFO", subsystem="monitor",
                    trigger="command", action="monitor_on", result="ok",
                )

            elif action == "off":
                profile["enabled"]        = False
                profile["resume_on_boot"] = False
                _atomic_write(self._profile_path, profile)
                self._armed = False
                self.circuit_breaker.reset()
                result.update({"ok": True, "enabled": False})
                self.incident_log.record(
                    severity="INFO", subsystem="monitor",
                    trigger="command", action="monitor_off", result="ok",
                )

            elif action == "pause":
                self._pause_flag.write_text("paused", encoding="utf-8")
                self._paused = True
                result.update({"ok": True, "paused": True})

            elif action == "resume":
                self._pause_flag.unlink(missing_ok=True)
                self._kill_flag.unlink(missing_ok=True)
                self._paused    = False
                self._safe_mode = False
                result.update({"ok": True, "resumed": True})
                self.incident_log.record(
                    severity="INFO", subsystem="monitor",
                    trigger="command", action="monitor_resume", result="ok",
                )

            elif action == "safe_mode":
                self._safe_mode = True
                self._paused    = False
                result.update({"ok": True, "safe_mode": True})

            elif action == "status":
                result.update({
                    "ok": True,
                    "state":   self._build_state_dict(profile),
                    "profile": profile,
                })

            elif action == "reset_ladder":
                self._ladder_idx        = 0
                self._consecutive_fails = 0
                self._hot_reload_count  = 0
                self.circuit_breaker.reset()
                result.update({"ok": True, "ladder_reset": True})

            else:
                result["error"] = f"unknown_action: {action!r}"

        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"

        res_path = self._cmd_dir / (path.stem + ".result.json")
        _atomic_write(res_path, result)
        path.unlink(missing_ok=True)
        self._write_state(profile)

    # â”€â”€ DevRuntime helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _send_devruntime_command(self, payload: Dict[str, Any]) -> str:
        import uuid
        cmd_id       = payload.get("id") or uuid.uuid4().hex
        payload      = dict(payload)
        payload["id"] = cmd_id
        _atomic_write(self._ctrl_cmd_dir / f"{cmd_id}.json", payload)
        return cmd_id

    def _wait_for_command_result(self, cmd_id: str, timeout: float = 8.0) -> bool:
        result_path = self._ctrl_res_dir / f"{cmd_id}.result.json"
        deadline    = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if result_path.exists():
                try:
                    return bool(json.loads(
                        result_path.read_text(encoding="utf-8-sig")
                    ).get("ok"))
                except Exception:
                    return False
            time.sleep(0.2)
        return False

    # â”€â”€ State persistence â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _write_state(self, profile: Optional[Dict[str, Any]] = None) -> None:
        if profile is None:
            profile = self._load_profile()
        try:
            _atomic_write(self._state_path, self._build_state_dict(profile))
        except Exception:
            pass

    def _build_state_dict(self, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if profile is None:
            profile = self._load_profile()
        ladder = profile.get("remediation_ladder", _LADDER)
        idx    = min(self._ladder_idx, len(ladder) - 1)
        return {
            "updated_at":        _utc(),
            "armed":             self._armed,
            "paused":            self._paused,
            "safe_mode":         self._safe_mode,
            "kill_flag_present": self._kill_flag.exists(),
            "enabled":           profile.get("enabled", False),
            "resume_on_boot":    profile.get("resume_on_boot", False),
            "ladder_step":       ladder[idx] if ladder else "none",
            "ladder_index":      self._ladder_idx,
            "consecutive_fails": self._consecutive_fails,
            "hot_reload_count":  self._hot_reload_count,
            "last_action":       self._last_action,
            "last_result":       self._last_result,
            "last_success_ts":   self._last_success_ts,
            "last_failure_ts":   self._last_failure_ts,
            "circuit_breaker":   self.circuit_breaker.to_dict(),
        }

    def _restore_state(self) -> None:
        prev = _read_json(self._state_path)
        if not prev:
            return
        self._ladder_idx        = int(prev.get("ladder_index",       0))
        self._consecutive_fails = int(prev.get("consecutive_fails",  0))
        self._hot_reload_count  = int(prev.get("hot_reload_count",   0))
        self._last_action       = str(prev.get("last_action",        "none"))
        self._last_result       = str(prev.get("last_result",        "ok"))
        self._last_success_ts   = str(prev.get("last_success_ts",    ""))
        self._last_failure_ts   = str(prev.get("last_failure_ts",    ""))
        cb = prev.get("circuit_breaker", {})
        if cb.get("tripped"):
            self.circuit_breaker.tripped    = True
            self.circuit_breaker._trip_time = time.monotonic()

    def _load_profile(self) -> Dict[str, Any]:
        base = dict(_DEFAULT_PROFILE)
        disk = _read_json(self._profile_path)
        if disk:
            base.update(disk)
        return base

    _summary_last_written: float = 0.0
    _SUMMARY_INTERVAL:     float = 60.0

    def _maybe_write_summary(self, profile: Dict[str, Any]) -> None:
        now = time.monotonic()
        if now - self._summary_last_written < self._SUMMARY_INTERVAL:
            return
        self._summary_last_written = now
        try:
            self.incident_log.write_summary(
                monitor_state=self._build_state_dict(profile)
            )
            self.incident_log.purge_old()
        except Exception:
            pass


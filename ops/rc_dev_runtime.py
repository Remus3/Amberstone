"""
ops/rc_dev_runtime.py  -  Phase 0 Addendum compliant rewrite

Lightweight file-based control plane for Riot Commander.

Changes vs Phase 0 initial:
  [2]  shell, start_process disabled by default.
       Only active when config['admin_bridge_enabled'] = true.
       Self-monitor uses only allowlisted actions.
  [5]  run_id and session_id added to every health.json payload.
  [5]  Boot marker written immediately on start(), before first 1s tick.
  [5]  Subsystem health fields: ui_loop_alive, game_poll_worker_alive,
       last_state_provider_ok, last_command_ok.
  [11] Shutdown bug fixed: stop() never tries to join the current thread
       (prevents RuntimeError when command loop triggers shutdown).
  [11] Final shutdown status written before thread exit.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


# -- Safe-reload allowlist (Item 9) --------------------------------------------
#
# SAFE_RELOAD: data/config modules with no live widget instances.
#   Re-importing these is safe because no running object holds a reference
#   to a live tkinter widget or holds per-game mutable state.
#
# RESTART_ONLY: modules that own live instances, threads, or tkinter state.
#   Hot-reloading these corrupts in-process state - must be restart-only.
#
SAFE_RELOAD_MODULES = frozenset({
    "core.theme",
    "tft.tft_data",
    "tft.tft_pbe_data",
    "champion_profiles",
    "role_profiles",
    "composition_advisor",
    "item_advisor",
})

RESTART_ONLY_MODULES = frozenset({
    "app",
    "main",
    "coach_integration",
    "game_reader",
    "performance_tracker",
    "overlay",
    "tft.tft_coach_engine",
    "tft.tft_pbe_engine",
    "tft.tft_live_analysis",
    "tft.tft_state_reader",
    "tft.tft_overlay",
    "ui.base",
    "ui.game_bottom",
    "ui.game_right_top",
    "ui.game_right_bot",
    "ui.client_panel",
})


class DevRuntime:
    """
    Heartbeat writer + file-based command processor, embedded in the overlay process.

    Admin-only commands (shell, start_process) are disabled in normal runtime
    and only active when admin_bridge_enabled=true is set in rc_config.json.
    """

    def __init__(
        self,
        project_root:         str | os.PathLike[str],
        app_name:             str   = "riot-commander",
        runtime_dir:          str   = "ops/runtime",
        heartbeat_interval:   float = 1.0,
        command_poll_interval: float = 0.5,
        admin_bridge_enabled: bool  = False,
    ) -> None:
        self.project_root         = Path(project_root).resolve()
        self.app_name             = app_name
        self.runtime_dir          = (self.project_root / runtime_dir).resolve()
        self.control_commands_dir = self.runtime_dir / "control" / "commands"
        self.control_results_dir  = self.runtime_dir / "control" / "results"
        self.health_file          = self.runtime_dir / "health.json"
        self.last_fatal_file      = self.runtime_dir / "last_fatal.txt"
        self.heartbeat_interval   = heartbeat_interval
        self.command_poll_interval = command_poll_interval
        self.admin_bridge_enabled = admin_bridge_enabled

        self._callbacks:      Dict[str, Callable[..., Any]] = {}
        self._state_provider: Optional[Callable[[], Dict[str, Any]]] = None
        self._stop_event      = threading.Event()
        self._threads:        list[threading.Thread] = []
        self._started_at      = _utc_now()

        # Unique IDs for this run - written to every health.json
        self._run_id     = uuid.uuid4().hex
        self._session_id = uuid.uuid4().hex

        # Health tracking
        self._last_reload_ok    = True
        self._last_reload_error: Optional[str] = None
        self._last_cmd_ok       = True
        self._last_sp_ok        = True   # state_provider last result

        self.control_commands_dir.mkdir(parents=True, exist_ok=True)
        self.control_results_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def set_state_provider(self, provider: Callable[[], Dict[str, Any]]) -> None:
        self._state_provider = provider

    def register_reload_callback(self, name: str, callback: Callable[..., Any]) -> None:
        self._callbacks[name] = callback

    # -- Start / Stop ----------------------------------------------------------

    def start(self) -> None:
        """
        Write a boot marker immediately (before first 1s heartbeat tick),
        then start heartbeat and command threads.
        """
        if self._threads:
            return

        # Boot marker: written immediately so supervisor sees a fresh file
        # even if the first real heartbeat is up to 1s away.
        boot_payload: Dict[str, Any] = {
            "app":        self.app_name,
            "pid":        os.getpid(),
            "run_id":     self._run_id,
            "session_id": self._session_id,
            "started_at": self._started_at,
            "updated_at": _utc_now(),
            "alive":      False,   # not yet alive - set to True on first tick
            "booting":    True,
        }
        try:
            _atomic_write_json(self.health_file, boot_payload)
        except Exception:
            pass

        t1 = threading.Thread(
            target=self._heartbeat_loop,
            name="DevRuntimeHeartbeat",
            daemon=True,
        )
        t2 = threading.Thread(
            target=self._command_loop,
            name="DevRuntimeCommands",
            daemon=True,
        )
        self._threads.extend([t1, t2])
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        """
        Cooperative shutdown.
        NEVER joins the calling thread (prevents RuntimeError when the
        command loop calls stop() on itself via a 'shutdown' command).
        """
        self._stop_event.set()

        # Write final shutdown status
        try:
            shutdown_payload = self._build_health_payload()
            shutdown_payload["alive"]            = False
            shutdown_payload["shutting_down"]    = True
            shutdown_payload["shutdown_at"]      = _utc_now()
            _atomic_write_json(self.health_file, shutdown_payload)
        except Exception:
            pass

        current = threading.current_thread()
        for t in self._threads:
            if t is current:
                continue   # never join ourselves
            t.join(timeout=2.0)
        self._threads.clear()

    def write_fatal(self, text: str) -> None:
        try:
            self.last_fatal_file.parent.mkdir(parents=True, exist_ok=True)
            self.last_fatal_file.write_text(text, encoding="utf-8")
        except Exception:
            pass

    # -- Health payload --------------------------------------------------------

    def _build_health_payload(self) -> Dict[str, Any]:
        """
        Build health.json payload for this tick.

        Fix (Phase 0.3): last_state_provider_ok must reflect the ACTUAL outcome
        of the state_provider call made THIS tick, not the stale value from the
        previous tick stored in self._last_sp_ok.

        Pattern:
          1. Call state_provider (if wired) and capture its this-tick result.
          2. Build payload using that result - never the pre-call stale value.
          3. Update self._last_sp_ok for persistent tracking after payload is set.
        """
        # Step 1 - call the state provider first, capture this-tick outcome
        this_tick_sp_ok: Optional[bool]          = None   # None = no provider
        this_tick_sp_error: Optional[str]        = None
        this_tick_state: Optional[Dict[str, Any]] = None

        if self._state_provider is not None:
            try:
                result = self._state_provider()
                this_tick_state  = result if isinstance(result, dict) else {}
                this_tick_sp_ok  = True
            except Exception as exc:
                this_tick_sp_ok    = False
                this_tick_sp_error = f"{type(exc).__name__}: {exc}"

        # Step 2 - build payload using this-tick result
        payload: Dict[str, Any] = {
            "app":               self.app_name,
            "pid":               os.getpid(),
            "run_id":            self._run_id,
            "session_id":        self._session_id,
            "started_at":        self._started_at,
            "updated_at":        _utc_now(),
            "alive":             True,
            "booting":           False,
            "last_command_ok":   self._last_cmd_ok,
            "last_reload_ok":    self._last_reload_ok,
            "last_reload_error": self._last_reload_error,
        }

        if this_tick_sp_ok is None:
            # No provider registered - omit subsystem fields entirely.
            # SelfMonitor treats absent fields as unknown, not unhealthy.
            pass
        elif this_tick_sp_ok:
            # Provider succeeded this tick - write True for this tick.
            payload["last_state_provider_ok"] = True
            if this_tick_state:
                payload.update(this_tick_state)
        else:
            # Provider failed this tick - write False + error for this tick.
            payload["last_state_provider_ok"] = False
            payload["state_provider_error"]   = this_tick_sp_error

        # Step 3 - update persistent tracking AFTER payload is constructed
        if this_tick_sp_ok is not None:
            self._last_sp_ok = this_tick_sp_ok

        return payload

    # -- Heartbeat loop --------------------------------------------------------

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                payload = self._build_health_payload()
                _atomic_write_json(self.health_file, payload)
            except Exception as exc:
                self.write_fatal(
                    f"heartbeat_error: {type(exc).__name__}: {exc}\n"
                    f"{traceback.format_exc()}"
                )
            self._stop_event.wait(self.heartbeat_interval)

    # -- Command loop ----------------------------------------------------------

    def _command_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                for path in sorted(self.control_commands_dir.glob("*.json")):
                    self._handle_command_file(path)
            except Exception as exc:
                self.write_fatal(
                    f"command_loop_error: {type(exc).__name__}: {exc}\n"
                    f"{traceback.format_exc()}"
                )
            self._stop_event.wait(self.command_poll_interval)

    def _handle_command_file(self, path: Path) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            result = {
                "ok":           False,
                "error":        f"invalid_json: {type(exc).__name__}: {exc}",
                "command_file": str(path),
                "handled_at":   _utc_now(),
            }
            self._write_result_for_path(path, result)
            path.unlink(missing_ok=True)
            return

        command_id = str(payload.get("id") or uuid.uuid4())
        kind       = str(payload.get("type") or "").strip()

        result: Dict[str, Any] = {
            "id":         command_id,
            "type":       kind,
            "ok":         False,
            "handled_at": _utc_now(),
        }

        try:
            if kind == "ping":
                result.update({"ok": True, "reply": "pong"})

            elif kind == "reload_safe_modules":
                # Self-monitor safe path: only SAFE_RELOAD modules
                modules = [
                    m for m in (payload.get("modules") or [])
                    if m in SAFE_RELOAD_MODULES
                ]
                rejected = [
                    m for m in (payload.get("modules") or [])
                    if m not in SAFE_RELOAD_MODULES
                ]
                r = self._reload_modules(modules)
                if rejected:
                    r["rejected_restart_only"] = rejected
                result.update(r)

            elif kind == "reload_modules":
                # Full reload path (requires modules to be in SAFE_RELOAD)
                requested = payload.get("modules") or []
                safe = [m for m in requested if m in SAFE_RELOAD_MODULES]
                unsafe = [m for m in requested if m not in SAFE_RELOAD_MODULES]
                r = self._reload_modules(safe)
                if unsafe:
                    r.setdefault("errors", []).extend([
                        {"module": m, "error": "RESTART_ONLY module - not hot-reloadable"}
                        for m in unsafe
                    ])
                    r["ok"] = r["ok"] and not unsafe
                result.update(r)

            elif kind == "rebuild_named_ui":
                name   = str(payload.get("name") or "")
                kwargs = payload.get("kwargs") or {}
                result.update(self._run_callback(f"rebuild_panel_{name}", kwargs))

            elif kind == "callback":
                name   = str(payload.get("name") or "")
                kwargs = payload.get("kwargs") or {}
                result.update(self._run_callback(name, kwargs))

            elif kind == "dump_state":
                result["ok"]    = True
                result["state"] = self._state_provider() if self._state_provider else {}

            elif kind == "read_health":
                # Safe read-only path
                try:
                    result["ok"]     = True
                    result["health"] = json.loads(
                        self.health_file.read_text(encoding="utf-8-sig")
                    ) if self.health_file.exists() else {}
                except Exception as exc:
                    result["error"] = str(exc)

            elif kind == "monitor_control":
                action = str(payload.get("action") or "status")
                result.update(self._handle_monitor_control(action, payload))

            elif kind == "controlled_restart":
                # Self-monitor restart path: writes a supervisor request
                result.update(self._do_controlled_restart(payload))

            elif kind == "rollback_last_known_good":
                result.update(self._do_rollback_request(payload))

            # -- Admin-only commands (disabled by default) -----------------
            elif kind in ("shell", "start_process"):
                if not self.admin_bridge_enabled:
                    result["error"] = (
                        f"command type '{kind}' is disabled in normal runtime. "
                        "Set admin_bridge_enabled=true in rc_config.json to enable."
                    )
                elif kind == "shell":
                    cmd = str(payload.get("command") or "")
                    timeout = float(payload.get("timeout_seconds") or 15.0)
                    result.update(self._run_shell(cmd, timeout))
                else:
                    exe  = str(payload.get("exe") or "")
                    args = payload.get("args") or []
                    cwd  = str(payload.get("cwd") or str(self.project_root))
                    result.update(self._start_process(exe, args, cwd))

            elif kind == "shutdown":
                result.update({"ok": True, "reply": "shutdown_requested"})
                self._write_result_for_path(path, result)
                path.unlink(missing_ok=True)
                self.stop()  # safe: stop() skips joining current thread
                return

            else:
                result["error"] = f"unknown_command_type: {kind!r}"
                self._last_cmd_ok = False

        except Exception as exc:
            self._last_cmd_ok = False
            self._last_reload_error = f"{type(exc).__name__}: {exc}"
            result["error"]     = self._last_reload_error
            result["traceback"] = traceback.format_exc()
        else:
            self._last_cmd_ok = bool(result.get("ok"))

        self._write_result_for_path(path, result)
        path.unlink(missing_ok=True)

    # -- Monitor control -------------------------------------------------------

    def _handle_monitor_control(
        self, action: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        profile_path = self.project_root / "config" / "self_monitor_profile.json"
        state_path   = self.project_root / "ops" / "runtime" / "monitor_state.json"
        cmd_dir      = self.runtime_dir / "monitor_commands"
        kill_flag    = self.runtime_dir / "self_monitor_off.flag"
        pause_flag   = self.runtime_dir / "monitor_paused.flag"

        cmd_dir.mkdir(parents=True, exist_ok=True)

        def _load(p: Path) -> Dict[str, Any]:
            try:
                return json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
            except Exception:
                return {}

        def _relay(act: str) -> str:
            cid = uuid.uuid4().hex
            _atomic_write_json(cmd_dir / f"{cid}.json", {"action": act, "id": cid})
            return cid

        if action == "status":
            return {"ok": True, "profile": _load(profile_path), "state": _load(state_path)}

        if action in ("on", "off"):
            profile = _load(profile_path)
            profile["enabled"]        = (action == "on")
            profile["resume_on_boot"] = (action == "on")
            _atomic_write_json(profile_path, profile)
            _relay(action)
            if action == "off":
                kill_flag.write_text("off", encoding="utf-8")
            else:
                kill_flag.unlink(missing_ok=True)
                pause_flag.unlink(missing_ok=True)
            return {"ok": True, "enabled": action == "on"}

        if action == "pause":
            pause_flag.write_text("paused", encoding="utf-8")
            _relay("pause")
            return {"ok": True, "paused": True}

        if action == "resume":
            pause_flag.unlink(missing_ok=True)
            kill_flag.unlink(missing_ok=True)
            _relay("resume")
            return {"ok": True, "resumed": True}

        if action in ("safe_mode", "reset_ladder"):
            _relay(action)
            return {"ok": True, action: True}

        return {"ok": False, "error": f"unknown monitor_control action: {action!r}"}

    # -- Controlled restart / rollback (for self-monitor) ----------------------

    def _do_controlled_restart(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        req_id   = f"devruntime-restart-{int(time.time())}"
        sup_dir  = self.runtime_dir / "supervisor_requests"
        req_path = sup_dir / f"{req_id}.json"
        sup_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(req_path, {
            "type":   "restart",
            "reason": str(payload.get("reason") or "devruntime_controlled_restart"),
            "at":     _utc_now(),
        })
        return {"ok": True, "request_id": req_id}

    def _do_rollback_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        req_id   = f"devruntime-rollback-{int(time.time())}"
        sup_dir  = self.runtime_dir / "supervisor_requests"
        req_path = sup_dir / f"{req_id}.json"
        sup_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(req_path, {
            "type":   "rollback",
            "reason": str(payload.get("reason") or "devruntime_rollback"),
            "at":     _utc_now(),
        })
        return {"ok": True, "request_id": req_id}

    # -- Internal helpers ------------------------------------------------------

    def _write_result_for_path(
        self, command_path: Path, result: Dict[str, Any]
    ) -> None:
        result_path = self.control_results_dir / (command_path.stem + ".result.json")
        _atomic_write_json(result_path, result)

    def _reload_modules(self, modules: Iterable[str]) -> Dict[str, Any]:
        modules    = [str(m).strip() for m in modules if str(m).strip()]
        reloaded:  list[str] = []
        imported:  list[str] = []
        errors:    list[Dict[str, str]] = []

        for name in modules:
            try:
                if name in sys.modules:
                    importlib.reload(sys.modules[name])
                    reloaded.append(name)
                else:
                    importlib.import_module(name)
                    imported.append(name)
            except Exception as exc:
                errors.append({
                    "module":    name,
                    "error":     f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                })

        ok = not errors
        self._last_reload_ok    = ok
        self._last_reload_error = None if ok else errors[0]["error"]
        return {"ok": ok, "reloaded": reloaded, "imported": imported, "errors": errors}

    def _run_callback(
        self, name: str, kwargs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Invoke a registered callback and return a result dict.

        Result propagation rules (fix 1):
          - Callback not found            -> ok=False, error set
          - Callback raises exception     -> ok=False, error set
          - Callback returns dict ok=False -> outer ok=False, inner preserved
          - Callback returns dict ok=True  -> outer ok=True
          - Callback returns non-dict      -> wrapped as {ok:True, result:value}
        """
        cb = self._callbacks.get(name)
        if cb is None:
            self._last_reload_ok    = False
            self._last_reload_error = f"callback_not_found: {name}"
            return {"ok": False, "error": self._last_reload_error, "callback": name}
        try:
            value = cb(**kwargs) if kwargs else cb()
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            self._last_reload_ok    = False
            self._last_reload_error = err
            return {"ok": False, "error": err, "callback": name}

        # If the callback returned a dict, propagate its ok/error fields directly.
        if isinstance(value, dict):
            cb_ok = bool(value.get("ok", True))  # default True for dicts without ok
            self._last_reload_ok    = cb_ok
            self._last_reload_error = None if cb_ok else str(value.get("error", ""))
            result: Dict[str, Any] = {"ok": cb_ok, "callback": name}
            result.update(value)        # preserve all inner keys (detail, error, etc.)
            result["callback"] = name   # ensure callback name is always present
            return result

        # Non-dict return value - wrap it.
        self._last_reload_ok    = True
        self._last_reload_error = None
        return {"ok": True, "callback": name, "result": value}

    # -- Admin-only methods (disabled unless admin_bridge_enabled) -------------

    def _run_shell(self, command: str, timeout: float = 15.0) -> Dict[str, Any]:
        if not command:
            return {"ok": False, "error": "empty command"}
        try:
            flags = 0x08000000 if os.name == "nt" else 0
            proc = subprocess.run(
                ["powershell.exe", "-NonInteractive", "-NoProfile",
                 "-ExecutionPolicy", "Bypass", "-Command", command],
                capture_output=True, text=True, timeout=timeout,
                creationflags=flags, cwd=str(self.project_root),
            )
            return {
                "ok":         proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout":     proc.stdout.strip(),
                "stderr":     proc.stderr.strip(),
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"timeout after {timeout}s"}
        # AUDIT 2026-04-28 (deferred-frozen): narrowed from bare Exception.
        except (OSError, FileNotFoundError, ValueError, UnicodeDecodeError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _start_process(
        self, exe: str, args: list, cwd: str,
        verify_alive_s: float = 0.5,
    ) -> Dict[str, Any]:
        """Spawn a fire-and-forget child process. Briefly polls the child
        after launch so an immediate exec failure (e.g. exe missing args)
        surfaces as an error instead of a phantom successful spawn.

        AUDIT 2026-04-28 (deferred-frozen): the prior Popen with no
        post-launch verification let "ok=true, pid=..." return for a process
        that immediately died. The verify window is intentionally short
        (default 500 ms) so this stays a spawner, not a wait()."""
        if not exe:
            return {"ok": False, "error": "empty exe"}
        try:
            flags = 0x08000000 if os.name == "nt" else 0
            proc = subprocess.Popen(
                [exe] + [str(a) for a in args],
                cwd=cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
        except (OSError, FileNotFoundError, ValueError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        # Brief liveness check: if the child died inside verify_alive_s,
        # report exit_code rather than "ok".
        try:
            if verify_alive_s > 0:
                rc = proc.wait(timeout=verify_alive_s)
                return {"ok": False, "pid": proc.pid,
                        "error": f"process exited immediately (rc={rc})"}
        except subprocess.TimeoutExpired:
            # Still alive - fire-and-forget success path.
            return {"ok": True, "pid": proc.pid}
        except OSError as exc:
            return {"ok": False, "pid": proc.pid,
                    "error": f"{type(exc).__name__}: {exc}"}
        return {"ok": True, "pid": proc.pid}

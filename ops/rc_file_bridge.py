"""
ops/rc_file_bridge.py  -  Phase 0 Addendum compliant rewrite

Subprocess bridge: exposes file/log/clipboard/screenshot ops to Claude MCP
via JSON request files in ops/runtime/bridge_requests/.

Changes vs Phase 0 initial:
  [2]  run_powershell gated behind admin_bridge_enabled config flag (default false).
       Normal self-monitor automation never touches this handler.
  [3]  handle_request: invalid JSON produces an error result file and continues.
       One bad request file NEVER kills the bridge process.
  [3]  run() loop has top-level exception containment.
  [12] Clipboard ops use win32clipboard (pywin32) or tkinter clipboard if available,
       falling back to PS subprocess only if both unavailable.
  [12] Retention cleanup: screenshot images, bridge result files, command result files
       pruned on a background schedule.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from PIL import ImageGrab as _ImageGrab  # type: ignore
    _HAS_PIL = True
except Exception:  # noqa: BLE001
    _HAS_PIL = False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _get_clipboard_native() -> Optional[str]:
    """Read clipboard via win32clipboard -> tkinter -> None."""
    try:
        import win32clipboard  # type: ignore
        win32clipboard.OpenClipboard()
        try:
            text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            return text
        finally:
            win32clipboard.CloseClipboard()
    except Exception:  # noqa: BLE001
        pass
    try:
        import tkinter as _tk
        r = _tk.Tk(); r.withdraw()
        t = r.clipboard_get()
        r.destroy()
        return t
    except Exception:  # noqa: BLE001
        return None


def _set_clipboard_native(text: str) -> bool:
    """Write clipboard via win32clipboard -> tkinter -> False."""
    try:
        import win32clipboard  # type: ignore
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            return True
        finally:
            win32clipboard.CloseClipboard()
    except Exception:  # noqa: BLE001
        pass
    try:
        import tkinter as _tk
        r = _tk.Tk(); r.withdraw()
        r.clipboard_clear(); r.clipboard_append(text)
        r.update()   # required to flush to OS clipboard
        r.destroy()
        return True
    except Exception:  # noqa: BLE001
        return False


def _pid_alive(pid: int) -> bool:
    """Return True if a process with the given PID is running."""
    try:
        import ctypes
        SYNCHRONIZE = 0x00100000
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    except Exception:  # noqa: BLE001
        pass
    try:
        import subprocess as _sp
        out = _sp.check_output(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
            stderr=_sp.DEVNULL, text=True, timeout=5,
        )
        return str(pid) in out
    except Exception:  # noqa: BLE001
        return False


class FileBridge:

    # Retention intervals
    _IMAGE_RETENTION_DAYS    = 2
    _RESULT_RETENTION_HOURS  = 24
    _CLEANUP_INTERVAL_S      = 600   # run cleanup every 10 minutes

    def __init__(self, config_path: Path) -> None:
        self.config       = json.loads(config_path.read_text(encoding="utf-8-sig"))
        self.project_root = Path(self.config["project_root"]).resolve()
        self.runtime_dir  = Path(
            self.config.get("runtime_dir") or self.project_root / "ops" / "runtime"
        ).resolve()
        self.request_dir  = self.runtime_dir / "bridge_requests"
        self.result_dir   = self.runtime_dir / "bridge_results"
        self.log_file     = self.runtime_dir / "logs" / "file_bridge.log"
        self.poll_s       = float(self.config.get("bridge_poll_interval_seconds", 0.5))

        # Admin-only flag: gating run_powershell and shell commands
        self.admin_bridge_enabled = bool(
            self.config.get("admin_bridge_enabled", False)
        )

        # Override retention from config
        self._IMAGE_RETENTION_DAYS   = int(
            self.config.get("image_retention_days", self._IMAGE_RETENTION_DAYS)
        )
        self._RESULT_RETENTION_HOURS = int(
            self.config.get("control_file_retention_hours", self._RESULT_RETENTION_HOURS)
        )

        self.request_dir.mkdir(parents=True, exist_ok=True)
        self.result_dir.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        self._last_cleanup = 0.0

        # Single-instance protection: acquire bridge.pid lock before running.
        # Raises RuntimeError if another healthy bridge process already holds it.
        self._acquire_bridge_lock()

    def _acquire_bridge_lock(self) -> None:
        """
        Single-instance protection via bridge.pid file.
        If another process holds the lock and is still alive, raise RuntimeError.
        Otherwise write our own PID and take ownership.
        """
        pid_path = self.runtime_dir / "bridge.pid"
        my_pid   = os.getpid()

        if pid_path.exists():
            try:
                raw = pid_path.read_text(encoding="utf-8").strip()
                other_pid = int(json.loads(raw)["pid"]) if raw.startswith("{") else int(raw)
                if other_pid and other_pid != my_pid and _pid_alive(other_pid):
                    raise RuntimeError(
                        f"Another FileBridge is already running (PID {other_pid}). "
                        "Exiting to avoid duplicate bridge."
                    )
            except RuntimeError:
                raise
            except Exception:  # noqa: BLE001
                pass  # stale / corrupt - overwrite

        # Write our lock
        self._write_bridge_pid()
        # Double-check we won any write race
        import time as _t
        _t.sleep(0.05)
        try:
            raw2 = pid_path.read_text(encoding="utf-8").strip()
            written_pid = int(json.loads(raw2)["pid"]) if raw2.startswith("{") else int(raw2)
            if written_pid != my_pid:
                raise RuntimeError(
                    f"Lost bridge.pid write race to PID {written_pid}. Exiting."
                )
        except RuntimeError:
            raise
        except Exception:  # noqa: BLE001
            pass  # file unreadable - proceed

    def _write_bridge_pid(self) -> None:
        import uuid as _uuid
        pid_data = {
            "pid":       os.getpid(),
            "run_id":    _uuid.uuid4().hex[:16],
            "locked_at": utc_now(),
        }
        try:
            pid_path = self.runtime_dir / "bridge.pid"
            pid_path.write_text(__import__('json').dumps(pid_data), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def _release_bridge_pid(self) -> None:
        try:
            pid_path = self.runtime_dir / "bridge.pid"
            if pid_path.exists():
                raw = pid_path.read_text(encoding="utf-8").strip()
                if raw.startswith('{'):
                    pid = int(__import__('json').loads(raw).get("pid", 0))
                else:
                    pid = int(raw)
                if pid == os.getpid():
                    pid_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

    # -- Logging ---------------------------------------------------------------

    def log(self, line: str) -> None:
        try:
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(f"[{utc_now()}] {line}\n")
        except Exception:  # noqa: BLE001
            pass

    # -- Main loop -------------------------------------------------------------

    def run(self) -> None:
        self.log(f"FileBridge started pid={os.getpid()} "
                 f"admin_bridge_enabled={self.admin_bridge_enabled}")
        while True:
            try:
                for path in sorted(self.request_dir.glob("*.json")):
                    self._safe_handle(path)
                self._maybe_cleanup()
            except Exception as exc:  # noqa: BLE001
                # Top-level containment: bridge never dies from a loop error
                self.log(f"bridge loop error (non-fatal): {type(exc).__name__}: {exc}")
            time.sleep(self.poll_s)

    def _safe_handle(self, path: Path) -> None:
        """Handle one request file.  Malformed JSON -> error result, continue."""
        req_id = path.stem
        kind   = "unknown"

        try:
            raw = path.read_text(encoding="utf-8-sig")
        except Exception as exc:  # noqa: BLE001
            self.log(f"request read error {path.name}: {exc}")
            path.unlink(missing_ok=True)
            return

        try:
            req    = json.loads(raw)
            req_id = str(req.get("id") or path.stem or uuid.uuid4().hex)
            kind   = str(req.get("type") or "")
        except Exception as exc:  # noqa: BLE001
            # Bad JSON: write an error result and move on
            err_result: Dict[str, Any] = {
                "id":           req_id,
                "type":         kind,
                "ok":           False,
                "error":        f"invalid_json: {type(exc).__name__}: {exc}",
                "raw_preview":  raw[:200],
                "handled_at":   utc_now(),
            }
            try:
                atomic_write_json(self.result_dir / f"{path.stem}.json", err_result)
            except Exception:  # noqa: BLE001
                pass
            path.unlink(missing_ok=True)
            self.log(f"bad JSON in {path.name} - error result written")
            return

        result: Dict[str, Any] = {
            "id":         req_id,
            "type":       kind,
            "handled_at": utc_now(),
            "ok":         False,
        }

        try:
            if kind == "ping":
                result.update({"ok": True, "reply": "pong"})

            elif kind == "tail_file":
                result.update(self._tail_file(req))

            elif kind == "grep_file":
                result.update(self._grep_file(req))

            elif kind == "list_processes":
                result.update(self._list_processes())

            elif kind == "get_clipboard":
                result.update(self._get_clipboard())

            elif kind == "set_clipboard":
                result.update(self._set_clipboard(req))

            elif kind == "screenshot_region":
                result.update(self._screenshot_region(req))

            elif kind == "read_log_tail":
                result.update(self._read_log_tail(req))

            elif kind == "read_health":
                result.update(self._read_health_file())

            elif kind == "read_incident_summary":
                result.update(self._read_incident_summary())

            # -- Admin-only (disabled by default) -------------------------
            elif kind == "run_powershell":
                if not self.admin_bridge_enabled:
                    result["error"] = (
                        "run_powershell is disabled in normal runtime. "
                        "Set admin_bridge_enabled=true in rc_config.json to enable."
                    )
                else:
                    result.update(self._run_powershell(req))

            else:
                result["error"] = f"unknown_request_type: {kind!r}"

        except Exception as exc:  # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"

        self.log(f"handled {path.name} kind={kind} ok={result.get('ok')}")
        try:
            atomic_write_json(self.result_dir / f"{path.stem}.json", result)
        except Exception:  # noqa: BLE001
            pass
        path.unlink(missing_ok=True)

    # -- Request handlers ------------------------------------------------------

    def _tail_file(self, req: Dict[str, Any]) -> Dict[str, Any]:
        path  = Path(str(req["path"])).resolve()
        lines = int(req.get("lines", 50))
        text  = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        return {"ok": True, "path": str(path), "lines": text[-lines:]}

    def _grep_file(self, req: Dict[str, Any]) -> Dict[str, Any]:
        path    = Path(str(req["path"])).resolve()
        pattern = re.compile(str(req["pattern"]))
        max_m   = int(req.get("max_matches", 50))
        matches: List[Dict[str, Any]] = []
        for idx, line in enumerate(
            path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1
        ):
            if pattern.search(line):
                matches.append({"line_number": idx, "line": line})
                if len(matches) >= max_m:
                    break
        return {"ok": True, "path": str(path), "matches": matches}

    def _list_processes(self) -> Dict[str, Any]:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV"],
            capture_output=True, text=True, timeout=10.0, startupinfo=si,
        )
        rows = list(csv.DictReader(io.StringIO(completed.stdout)))
        return {"ok": completed.returncode == 0, "processes": rows[:200]}

    def _get_clipboard(self) -> Dict[str, Any]:
        # Try native (win32clipboard -> tkinter) first
        text = _get_clipboard_native()
        if text is not None:
            return {"ok": True, "text": text}
        # Fallback to PowerShell (kept for environments without pywin32/tkinter)
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=5.0, startupinfo=si,
            )
            return {"ok": completed.returncode == 0, "text": completed.stdout}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _set_clipboard(self, req: Dict[str, Any]) -> Dict[str, Any]:
        text = str(req.get("text") or "")
        # Try native first (win32clipboard -> tkinter)
        if _set_clipboard_native(text):
            return {"ok": True}
        # Fallback to PowerShell
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            # Use SetText via .NET - avoids the heredoc quoting issues
            ps_cmd = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                f"[System.Windows.Forms.Clipboard]::SetText({json.dumps(text)})"
            )
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=5.0, startupinfo=si,
            )
            return {"ok": completed.returncode == 0, "stderr": completed.stderr}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _screenshot_region(self, req: Dict[str, Any]) -> Dict[str, Any]:
        if not _HAS_PIL:
            return {"ok": False, "error": "Pillow.ImageGrab unavailable"}
        bbox = req.get("bbox")
        if not bbox or len(bbox) != 4:
            return {"ok": False, "error": "bbox must be [left, top, right, bottom]"}
        image     = _ImageGrab.grab(bbox=tuple(int(v) for v in bbox))
        image_dir = self.result_dir / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        img_path  = image_dir / f"{uuid.uuid4().hex}.png"
        image.save(img_path)
        return {
            "ok":         True,
            "image_path": str(img_path),
            "size":       list(image.size),
            "bbox":       bbox,
        }

    def _read_log_tail(self, req: Dict[str, Any]) -> Dict[str, Any]:
        """Safe log read - self-monitor uses this instead of run_powershell."""
        log_name = str(req.get("log", "supervisor"))  # supervisor|file_bridge|watchdog
        valid    = {"supervisor", "file_bridge", "watchdog", "rc_app"}
        if log_name not in valid:
            return {"ok": False, "error": f"log name must be one of {sorted(valid)}"}
        fname   = {"supervisor": "supervisor.log", "file_bridge": "file_bridge.log",
                   "watchdog": "watchdog.log", "rc_app": "app.log"}.get(log_name, "supervisor.log")
        path    = self.runtime_dir / "logs" / fname
        lines   = int(req.get("lines", 50))
        if not path.exists():
            return {"ok": True, "lines": [], "path": str(path)}
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"ok": True, "lines": content[-lines:], "path": str(path)}

    def _read_health_file(self) -> Dict[str, Any]:
        """Safe read of health.json - self-monitor uses this."""
        hf = self.runtime_dir / "health.json"
        if not hf.exists():
            return {"ok": True, "health": {}}
        try:
            return {"ok": True, "health": json.loads(hf.read_text(encoding="utf-8-sig"))}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _read_incident_summary(self) -> Dict[str, Any]:
        """Safe read of incident_summary.json - self-monitor uses this."""
        sf = self.runtime_dir / "incident_summary.json"
        if not sf.exists():
            return {"ok": True, "summary": {}}
        try:
            return {"ok": True, "summary": json.loads(sf.read_text(encoding="utf-8-sig"))}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    # -- Admin-only ------------------------------------------------------------

    def _run_powershell(self, req: Dict[str, Any]) -> Dict[str, Any]:
        command         = str(req["command"])
        timeout_seconds = float(req.get("timeout_seconds", 10.0))
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", command],
            capture_output=True, text=True,
            timeout=timeout_seconds, startupinfo=si,
        )
        return {
            "ok":         completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout":     completed.stdout[-4000:],
            "stderr":     completed.stderr[-4000:],
        }

    # -- Retention cleanup -----------------------------------------------------

    def _maybe_cleanup(self) -> None:
        now = time.monotonic()
        if now - self._last_cleanup < self._CLEANUP_INTERVAL_S:
            return
        self._last_cleanup = now
        try:
            self._cleanup_images()
            self._cleanup_result_files()
        except Exception as exc:  # noqa: BLE001
            self.log(f"cleanup error (non-fatal): {exc}")

    def _cleanup_images(self) -> None:
        """Delete screenshot PNGs older than image_retention_days."""
        img_dir = self.result_dir / "images"
        if not img_dir.exists():
            return
        cutoff = time.time() - (self._IMAGE_RETENTION_DAYS * 86400)
        removed = 0
        for f in img_dir.glob("*.png"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
                    removed += 1
            except Exception:  # noqa: BLE001
                pass
        if removed:
            self.log(f"cleanup: removed {removed} old screenshot(s)")

    def _cleanup_result_files(self) -> None:
        """Delete bridge result files older than result_retention_hours."""
        cutoff = time.time() - (self._RESULT_RETENTION_HOURS * 3600)
        removed = 0
        for f in self.result_dir.glob("*.json"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
                    removed += 1
            except Exception:  # noqa: BLE001
                pass
        # Also clean control command/result files
        for subdir in [
            self.runtime_dir / "control" / "commands",
            self.runtime_dir / "control" / "results",
        ]:
            if not subdir.exists():
                continue
            for f in subdir.glob("*.json"):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink(missing_ok=True)
                        removed += 1
                except Exception:  # noqa: BLE001
                    pass
        if removed:
            self.log(f"cleanup: removed {removed} stale result/command file(s)")


# -- Entry point ---------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args   = parser.parse_args()
    try:
        bridge = FileBridge(Path(args.config).resolve())
    except RuntimeError as exc:
        # Single-instance check: another bridge is already running.
        # Exit cleanly with code 2 so league_watcher can detect this.
        import sys as _sys
        print(f"[bridge] {exc}", file=_sys.stderr)
        return 2
    bridge.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

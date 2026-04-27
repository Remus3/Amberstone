from __future__ import annotations

import argparse
import json
import os
import py_compile
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def clear_pycache_for(path: Path) -> None:
    folder = path.parent / "__pycache__"
    if folder.exists() and folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


def copy_atomic(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def wait_for_result(result_dir: Path, stem: str, timeout_seconds: float) -> Dict[str, Any] | None:
    target = result_dir / f"{stem}.result.json"
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if target.exists():
            return json.loads(target.read_text(encoding="utf-8-sig"))
        time.sleep(0.2)
    return None


def wait_for_heartbeat(
    health_file:      Path,
    previous_mtime:   float,
    timeout_seconds:  float,
    expected_run_id:  Optional[str] = None,
    allow_new_run:    bool          = False,
) -> bool:
    """
    Wait for a fresh, valid heartbeat after a deploy action.

    Parameters
    ----------
    expected_run_id
        The run_id that was active BEFORE the deploy.  If None, only
        mtime+alive is checked (legacy / no run_id in health.json).
    allow_new_run
        False (default) — only accept the SAME run_id recovering in-place.
            Use for hot-reload deploys: the process should not have restarted.
        True — also accept a DIFFERENT run_id that is alive.
            Use for force-restart deploys: supervisor killed and relaunched the app.

    Acceptance rules
    ----------------
    1. health.json must be newer than previous_mtime (written after deploy started).
    2. alive must be True.
    3. If expected_run_id is None: accept any alive+newer file (legacy path).
    4. If expected_run_id is set:
       - Same run_id  -> always accepted (same process recovered).
       - Diff run_id  -> accepted only if allow_new_run=True.
       - Empty run_id -> fall back to mtime+alive (old format).

    The previous_mtime guard ensures a pre-existing health.json from a prior run
    is never accidentally accepted, regardless of its run_id.
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            if not health_file.exists():
                time.sleep(0.25)
                continue
            mtime = health_file.stat().st_mtime
            if mtime <= previous_mtime:
                time.sleep(0.25)
                continue
            payload = json.loads(health_file.read_text(encoding="utf-8-sig"))
            if not payload.get("alive"):
                time.sleep(0.25)
                continue
            # File is newer and alive=True.  Now check run_id context.
            if expected_run_id is None:
                return True   # no run_id tracking — mtime+alive is sufficient
            current_run_id = str(payload.get("run_id") or "")
            if not current_run_id:
                return True   # health.json has no run_id field (old format)
            if current_run_id == expected_run_id:
                return True   # same process recovered in-place
            if allow_new_run:
                return True   # different run, but caller explicitly permits it
            # Different run_id and allow_new_run=False: keep waiting for the
            # expected process to recover (or for timeout to expire).
        except Exception:
            pass
        time.sleep(0.25)
    return False


def compile_python_files(staged_paths: Sequence[Path]) -> List[Dict[str, str]]:
    errors: List[Dict[str, str]] = []
    for path in staged_paths:
        if path.suffix.lower() == ".py":
            try:
                py_compile.compile(str(path), doraise=True)
            except Exception as exc:
                errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
    return errors


def send_command(command_dir: Path, payload: Dict[str, Any]) -> str:
    command_dir.mkdir(parents=True, exist_ok=True)
    command_id = payload.get("id") or uuid.uuid4().hex
    payload = dict(payload)
    payload["id"] = command_id
    command_file = command_dir / f"{command_id}.json"
    atomic_write_json(command_file, payload)
    return str(command_id)


def restore_backup(backup_root: Path, project_root: Path, deployed_files: Sequence[Dict[str, Any]]) -> None:
    for item in deployed_files:
        live_rel = Path(item["live"])
        backup_path = backup_root / live_rel
        live_path = project_root / live_rel
        if backup_path.exists():
            copy_atomic(backup_path, live_path)
            clear_pycache_for(live_path)


def do_deploy(request_path: Path) -> Dict[str, Any]:
    req = json.loads(request_path.read_text(encoding="utf-8-sig"))
    request_id = str(req.get("request_id") or request_path.stem)
    project_root = Path(req["project_root"]).resolve()
    staging_root = Path(req["staging_root"]).resolve()
    runtime_dir = Path(req.get("runtime_dir") or project_root / "ops" / "runtime").resolve()
    command_dir = runtime_dir / "control" / "commands"
    result_dir = runtime_dir / "control" / "results"
    health_file = Path(req.get("health_file") or runtime_dir / "health.json").resolve()
    backups_root = Path(req.get("backups_root") or project_root / "ops" / "backups").resolve()

    files = req.get("files") or []
    if not files:
        raise ValueError("deploy request contains no files")

    staged_paths = []
    for item in files:
        staged_rel = Path(item["staged"])
        staged_path = staging_root / staged_rel
        if not staged_path.exists():
            raise FileNotFoundError(f"staged file not found: {staged_path}")
        staged_paths.append(staged_path)

    compile_errors = compile_python_files(staged_paths)
    if compile_errors:
        return {
            "request_id": request_id,
            "ok": False,
            "phase": "compile",
            "errors": compile_errors,
            "handled_at": utc_now(),
        }

    backup_root = backups_root / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{request_id}"
    deployed_files: List[Dict[str, Any]] = []
    previous_mtime = health_file.stat().st_mtime if health_file.exists() else 0.0
    # Capture current run_id so wait_for_heartbeat can validate post-deploy
    _pre_run_id: Optional[str] = None
    try:
        if health_file.exists():
            _pre_run_id = str(
                json.loads(health_file.read_text(encoding="utf-8-sig")).get("run_id") or ""
            ) or None
    except Exception:
        pass

    try:
        for item in files:
            live_rel = Path(item["live"])
            staged_rel = Path(item["staged"])
            live_path = project_root / live_rel
            staged_path = staging_root / staged_rel
            backup_path = backup_root / live_rel

            if live_path.exists():
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(live_path, backup_path)

            copy_atomic(staged_path, live_path)
            clear_pycache_for(live_path)
            deployed_files.append(item)

        hot_modules = []
        callbacks = []

        for item in files:
            mode = str(item.get("reload_mode") or "restart").strip().lower()
            if mode == "hot_reload":
                hot_modules.extend(item.get("modules") or [])
            elif mode == "callback":
                callbacks.append(
                    {
                        "name": item.get("callback"),
                        "kwargs": item.get("callback_kwargs") or {},
                    }
                )

        command_results = []

        if hot_modules:
            command_id = send_command(command_dir, {"type": "reload_modules", "modules": hot_modules})
            res = wait_for_result(result_dir, command_id, timeout_seconds=float(req.get("command_timeout_seconds", 8.0)))
            command_results.append({"id": command_id, "result": res})
            if not res or not res.get("ok"):
                restore_backup(backup_root, project_root, deployed_files)
                return {
                    "request_id": request_id,
                    "ok": False,
                    "phase": "hot_reload",
                    "command_results": command_results,
                    "handled_at": utc_now(),
                    "rollback": True,
                }

        for cb in callbacks:
            if not cb.get("name"):
                continue
            command_id = send_command(command_dir, {"type": "callback", "name": cb["name"], "kwargs": cb["kwargs"]})
            res = wait_for_result(result_dir, command_id, timeout_seconds=float(req.get("command_timeout_seconds", 8.0)))
            command_results.append({"id": command_id, "result": res})
            if not res or not res.get("ok"):
                restore_backup(backup_root, project_root, deployed_files)
                return {
                    "request_id": request_id,
                    "ok": False,
                    "phase": "callback",
                    "command_results": command_results,
                    "handled_at": utc_now(),
                    "rollback": True,
                }

        if req.get("force_restart"):
            restart_request = runtime_dir / "supervisor_requests" / f"{request_id}.restart.json"
            restart_request.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(restart_request, {"type": "restart", "reason": f"deploy:{request_id}", "at": utc_now()})

        heartbeat_ok = wait_for_heartbeat(
            health_file,
            previous_mtime   = previous_mtime,
            timeout_seconds  = float(req.get("health_timeout_seconds", 10.0)),
            expected_run_id  = _pre_run_id,
            # force_restart means supervisor killed and relaunched: accept new run_id.
            # Hot-reload (no force_restart): require the same run_id to recover.
            allow_new_run    = bool(req.get("force_restart", False)),
        )
        if not heartbeat_ok:
            restore_backup(backup_root, project_root, deployed_files)
            restart_request = runtime_dir / "supervisor_requests" / f"{request_id}.restart.json"
            restart_request.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(restart_request, {"type": "restart", "reason": f"rollback:{request_id}", "at": utc_now()})
            return {
                "request_id": request_id,
                "ok": False,
                "phase": "health_check",
                "command_results": command_results,
                "handled_at": utc_now(),
                "rollback": True,
            }

        # Prune old backups after successful deploy
        try:
            retention = int(req.get("backup_retention_count", 10))
            api_key   = req.get("api_key_file", "API-Key-Claude.txt")
            all_bkps  = sorted((d for d in backups_root.iterdir() if d.is_dir()), reverse=True)
            for old in all_bkps[retention:]:
                shutil.rmtree(old, ignore_errors=True)
        except Exception:
            pass

        return {
            "request_id": request_id,
            "ok": True,
            "phase": "complete",
            "backup_root": str(backup_root),
            "command_results": command_results,
            "handled_at": utc_now(),
        }
    except Exception as exc:
        restore_backup(backup_root, project_root, deployed_files)
        return {
            "request_id": request_id,
            "ok": False,
            "phase": "exception",
            "error": f"{type(exc).__name__}: {exc}",
            "handled_at": utc_now(),
            "rollback": True,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True, help="Path to deploy request JSON file.")
    parser.add_argument("--result", required=False, help="Optional result JSON path.")
    args = parser.parse_args()

    request_path = Path(args.request).resolve()
    result = do_deploy(request_path)

    if args.result:
        result_path = Path(args.result).resolve()
    else:
        req = json.loads(request_path.read_text(encoding="utf-8-sig"))
        project_root = Path(req["project_root"]).resolve()
        runtime_dir = Path(req.get("runtime_dir") or project_root / "ops" / "runtime").resolve()
        result_path = runtime_dir / "deploy_results" / f"{request_path.stem}.json"

    atomic_write_json(result_path, result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

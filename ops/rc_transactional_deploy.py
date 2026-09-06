"""Transactional deploy worker - copy staged files over live ones, verify the
app survives, roll back if it does not.

Invoked by the supervisor as a SUBPROCESS (`ops/rc_supervisor.py:658`,
configured at `ops/rc_config.json:9`), once per JSON request found in
`ops/runtime/deploy_requests/`. It runs under the supervisor's token and it
overwrites RC's own source files, which makes the request the most powerful
untrusted input in the tree.

TRUST BOUNDARY (audited 2026-08-05, lane 8 cycle 7)
---------------------------------------------------
No in-repo module writes `deploy_requests/` today - the directory is only
created (`bootstrap_riot_commander_dev.ps1:102`,
`ops/rc_league_watcher.ps1:79`). The producer is therefore out-of-band by
construction, so every path in the request is treated as hostile here:

  * `files[].live`   is contained under `project_root`
  * `files[].staged` is contained under `staging_root`
  * `request_id`     is contained under the directories derived from it

`contained_path` is the single primitive that enforces this, modelled on the
`dashboard/routes_static.py:64-67` precedent - resolve both sides and assert
`relative_to`. A prefix check plus a ".." filter was deliberately REPLACED by
that pattern there because both are bypassable; the same reasoning applies.

MEASURED, not assumed: on Windows `Path("C:/Riot Commander") / Path("C:/x")`
is `C:\\x` - an absolute right-hand side discards the root entirely, so
string-prefix reasoning about the joined path is wrong before it starts.

SECRETS. `rc_supervisor.py:29` records that rollback excludes `ops/backups/`
and `API-Key-Claude.txt`. This module named the same file in a local
`api_key` variable it never read - a declared exclusion that was not
implemented. `_is_excluded_name` implements it on BOTH sides of the copy:
the key can neither be deployed over nor lifted out of a staging tree into
the project, where the dashboard static route would then serve it.
"""
from __future__ import annotations

import argparse
import json
import os
import py_compile
import shutil
import time
import uuid
from datetime import datetime, timezone
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Files that may never cross the staged -> live copy in either direction.
# Kept as a default so an old request without `api_key_file` is still guarded.
DEFAULT_EXCLUDED_NAMES = ("API-Key-Claude.txt",)

# os.replace transiently raises PermissionError (WinError 5) on Windows when a
# reader holds the destination open. Deploy writes land on polled paths - the
# control-command drop directory and the deploy result files - so contention is
# routine rather than exceptional. Bounded backoff, ~275 ms worst case, then
# re-raise: an UNBOUNDED retry would convert a visible failure into a hung
# deploy thread. This mirrors core/polled_json.py:40-48 rather than importing
# it: this module is launched by absolute path as a SCRIPT, so sys.path[0] is
# `ops/` and the project root is not importable here.
_REPLACE_RETRY_DELAYS_S = (0.025, 0.05, 0.2)


class DeployPathError(ValueError):
    """A request path component that escapes its declared root, names an
    excluded file, or is not a usable relative path at all."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _replace_with_retry(src: Path, dst: Path) -> None:
    """os.replace with bounded backoff, then re-raise."""
    for i in range(len(_REPLACE_RETRY_DELAYS_S) + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i >= len(_REPLACE_RETRY_DELAYS_S):
                raise
            time.sleep(_REPLACE_RETRY_DELAYS_S[i])


def contained_path(root: Path, rel: Any) -> Path:
    """Resolve `rel` under `root` and prove it stayed inside.

    Raises DeployPathError on anything that is not a plain relative path
    landing under `root`: a non-string, an empty string, an embedded NUL, an
    absolute or drive-qualified or UNC path, or a `..` walk that escapes.
    """
    if isinstance(rel, Path):
        text = str(rel)
    elif isinstance(rel, str):
        text = rel
    else:
        raise DeployPathError(
            f"path component must be a string, got {type(rel).__name__}")
    if not text.strip():
        raise DeployPathError("empty path component")
    if "\x00" in text:
        raise DeployPathError("path component contains a NUL byte")
    candidate = Path(text)
    # A drive ("C:x", "//server/share/x") or a root ("/x") means the join
    # would not be anchored to `root` at all - reject before resolving, so
    # the process cwd never gets a say in where the file lands.
    if candidate.drive or candidate.root:
        raise DeployPathError(f"path component is not relative: {text!r}")
    base = Path(root).resolve()
    resolved = (base / candidate).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        raise DeployPathError(
            f"path component escapes its root: {text!r}") from None
    return resolved


def _is_excluded_name(path_text: str, excluded: Sequence[str]) -> bool:
    """True when the final component matches an excluded filename. Windows
    filenames are case-insensitive, so the comparison is too."""
    name = Path(path_text).name.casefold()
    return any(name == str(e).casefold() for e in excluded)


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    _replace_with_retry(tmp, path)


def clear_pycache_for(path: Path) -> None:
    folder = path.parent / "__pycache__"
    if folder.exists() and folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


def copy_atomic(src: Path, dst: Path) -> None:
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    shutil.copy2(src, tmp)
    _replace_with_retry(tmp, dst)


def wait_for_result(result_dir: Path, stem: str,
                    timeout_seconds: float) -> Dict[str, Any] | None:
    """Poll for a command result file. Monotonic clock: a wall-clock deadline
    can be moved by an NTP step or a DST change mid-deploy."""
    target = result_dir / f"{stem}.result.json"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if target.exists():
            try:
                return json.loads(target.read_text(encoding="utf-8-sig"))
            except (OSError, JSONDecodeError, ValueError):
                # The writer may be mid-write; retry until the deadline
                # rather than failing the deploy on a torn read.
                pass
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
        False (default) - only accept the SAME run_id recovering in-place.
            Use for hot-reload deploys: the process should not have restarted.
        True - also accept a DIFFERENT run_id that is alive.
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

    `previous_mtime` is a FILE mtime, so its comparison stays on the wall
    clock; only the timeout deadline is monotonic.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            if not health_file.exists():
                time.sleep(0.25)
                continue
            mtime = health_file.stat().st_mtime
            if mtime <= previous_mtime:
                time.sleep(0.25)
                continue
            payload = json.loads(health_file.read_text(encoding="utf-8-sig"))
            if not isinstance(payload, dict) or not payload.get("alive"):
                time.sleep(0.25)
                continue
            # File is newer and alive=True.  Now check run_id context.
            if expected_run_id is None:
                return True   # no run_id tracking - mtime+alive is sufficient
            current_run_id = str(payload.get("run_id") or "")
            if not current_run_id:
                return True   # health.json has no run_id field (old format)
            if current_run_id == expected_run_id:
                return True   # same process recovered in-place
            if allow_new_run:
                return True   # different run, but caller explicitly permits it
            # Different run_id and allow_new_run=False: keep waiting for the
            # expected process to recover (or for timeout to expire).
        except (OSError, JSONDecodeError, ValueError):
            # Missing, torn, or non-JSON health file: keep polling. Narrowed
            # from `except Exception` - a genuine programming error in this
            # loop should surface, not spin silently until the timeout.
            pass
        time.sleep(0.25)
    return False


def compile_python_files(staged_paths: Sequence[Path]) -> List[Dict[str, str]]:
    errors: List[Dict[str, str]] = []
    for path in staged_paths:
        if path.suffix.lower() == ".py":
            try:
                py_compile.compile(str(path), doraise=True)
            except Exception as exc:  # noqa: BLE001
                errors.append({"path": str(path),
                               "error": f"{type(exc).__name__}: {exc}"})
    return errors


def send_command(command_dir: Path, payload: Dict[str, Any]) -> str:
    command_dir.mkdir(parents=True, exist_ok=True)
    command_id = payload.get("id") or uuid.uuid4().hex
    payload = dict(payload)
    payload["id"] = command_id
    command_file = command_dir / f"{command_id}.json"
    atomic_write_json(command_file, payload)
    return str(command_id)


def restore_backup(backup_root: Path, project_root: Path,
                   deployed_files: Sequence[Dict[str, Any]]) -> None:
    """Undo a deploy.

    Two cases, and the second one used to be missed: a file that EXISTED
    before the deploy is restored from its backup, and a file the deploy
    CREATED is removed. Leaving a created file behind is not a cosmetic gap -
    a new module can shadow an import for every later run, so a "rolled back"
    deploy would still have changed what the app executes.

    `deployed_files` entries carry `_resolved_live` and `_created`, both set
    by `do_deploy` from already-contained paths.
    """
    for item in deployed_files:
        live_path = item.get("_resolved_live")
        if live_path is None:
            continue
        live_path = Path(live_path)
        if item.get("_created"):
            try:
                live_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                continue
            clear_pycache_for(live_path)
            continue
        backup_path = backup_root / item["_backup_rel"]
        if backup_path.exists():
            copy_atomic(backup_path, live_path)
            clear_pycache_for(live_path)


def prune_backups(backups_root: Path, req: Dict[str, Any],
                  errors: List[str]) -> int:
    """Delete all but the newest `backup_retention_count` backup directories.

    Fail-soft by contract - a prune failure must never fail an otherwise good
    deploy - but the reason is appended to `errors` and surfaced in the result
    instead of vanishing into a bare `except Exception: pass`. Returns the
    number of directories removed.
    """
    backups_root = Path(backups_root)
    try:
        retention = int(req.get("backup_retention_count", 10))
        # RM-363: the bound was `< 0`, which admitted the ONE degenerate
        # value a "keep newest N" slice cannot survive. `all_bkps[0:]` is
        # every backup, and this runs AFTER the health check inside a live
        # deploy, so the in-flight deploy's own rollback snapshot sits under
        # the same root and is rmtree'd with the history.
        if retention < 1:
            raise ValueError(
                f"backup_retention_count must be >= 1, got {retention}")
        if not backups_root.is_dir():
            return 0
        all_bkps = sorted((d for d in backups_root.iterdir() if d.is_dir()),
                          reverse=True)
        removed = 0
        for old in all_bkps[retention:]:
            shutil.rmtree(old, ignore_errors=True)
            removed += 1
        return removed
    except (OSError, TypeError, ValueError) as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        return 0


def _fail(request_id: str, phase: str, **extra: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "request_id": request_id,
        "ok": False,
        "phase": phase,
        "handled_at": utc_now(),
    }
    out.update(extra)
    return out


def _validate_files(
    files: Any,
    project_root: Path,
    staging_root: Path,
    excluded: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[Path]]:
    """Turn the raw `files` list into entries carrying CONTAINED absolute
    paths. Raises DeployPathError on anything hostile or malformed - the
    caller converts that into a `validate` phase failure, so a bad request
    never reaches the copy loop."""
    if not isinstance(files, list):
        raise DeployPathError(
            f"`files` must be a list, got {type(files).__name__}")
    if not files:
        raise DeployPathError("deploy request contains no files")
    entries: List[Dict[str, Any]] = []
    staged_paths: List[Path] = []
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            raise DeployPathError(
                f"files[{index}] must be an object, got "
                f"{type(item).__name__}")
        raw_live = item.get("live")
        raw_staged = item.get("staged")
        if raw_live is None or raw_staged is None:
            raise DeployPathError(
                f"files[{index}] needs both `live` and `staged`")
        for raw in (raw_live, raw_staged):
            if isinstance(raw, (str, Path)) and _is_excluded_name(str(raw),
                                                                  excluded):
                # Never name the value, only the filename: this branch exists
                # precisely because the file holds a secret.
                raise DeployPathError(
                    f"files[{index}] names an excluded file: "
                    f"{Path(str(raw)).name!r}")
        live_path = contained_path(project_root, raw_live)
        staged_path = contained_path(staging_root, raw_staged)
        if not staged_path.is_file():
            raise DeployPathError(f"staged file not found: {staged_path}")
        entry = dict(item)
        entry["_resolved_live"] = str(live_path)
        entry["_resolved_staged"] = str(staged_path)
        entry["_backup_rel"] = str(live_path.relative_to(project_root))
        entries.append(entry)
        staged_paths.append(staged_path)
    return entries, staged_paths


def _public(entry: Dict[str, Any]) -> Dict[str, Any]:
    """The request-authored half of an entry, without the internal keys."""
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def do_deploy(request_path: Path) -> Dict[str, Any]:
    request_path = Path(request_path)
    request_id = request_path.stem
    try:
        req = json.loads(request_path.read_text(encoding="utf-8-sig"))
        if not isinstance(req, dict):
            raise ValueError(
                f"request must be a JSON object, got {type(req).__name__}")
        request_id = str(req.get("request_id") or request_path.stem)
        project_root = Path(req["project_root"]).resolve()
        staging_root = Path(req["staging_root"]).resolve()
        runtime_dir = Path(
            req.get("runtime_dir") or project_root / "ops" / "runtime"
        ).resolve()
        backups_root = Path(
            req.get("backups_root") or project_root / "ops" / "backups"
        ).resolve()
        health_file = Path(
            req.get("health_file") or runtime_dir / "health.json").resolve()
        excluded = list(DEFAULT_EXCLUDED_NAMES)
        if req.get("api_key_file"):
            excluded.append(str(req["api_key_file"]))
        # The request id names files under runtime_dir, so it is a path
        # component like any other and is contained the same way.
        safe_stem = contained_path(runtime_dir, f"{request_id}.probe").name
        entries, staged_paths = _validate_files(
            req.get("files"), project_root, staging_root, excluded)
    except (DeployPathError, KeyError, OSError, JSONDecodeError,
            TypeError, ValueError) as exc:
        return _fail(request_id, "validate",
                     error=f"{type(exc).__name__}: {exc}")

    command_dir = runtime_dir / "control" / "commands"
    result_dir = runtime_dir / "control" / "results"
    safe_id = safe_stem[: -len(".probe")]

    compile_errors = compile_python_files(staged_paths)
    if compile_errors:
        return _fail(request_id, "compile", errors=compile_errors)

    backup_root = (backups_root /
                   f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{safe_id}")
    deployed_files: List[Dict[str, Any]] = []
    previous_mtime = health_file.stat().st_mtime if health_file.exists() else 0.0
    # Capture current run_id so wait_for_heartbeat can validate post-deploy
    _pre_run_id: Optional[str] = None
    try:
        if health_file.exists():
            _pre_run_id = str(
                json.loads(health_file.read_text(encoding="utf-8-sig"))
                .get("run_id") or ""
            ) or None
    except (OSError, JSONDecodeError, ValueError, AttributeError):
        pass

    def _rollback(phase: str, **extra: Any) -> Dict[str, Any]:
        restore_backup(backup_root, project_root, deployed_files)
        return _fail(request_id, phase, rollback=True, **extra)

    try:
        for entry in entries:
            live_path = Path(entry["_resolved_live"])
            staged_path = Path(entry["_resolved_staged"])
            backup_path = backup_root / entry["_backup_rel"]

            existed = live_path.exists()
            entry["_created"] = not existed
            if existed:
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(live_path, backup_path)

            copy_atomic(staged_path, live_path)
            clear_pycache_for(live_path)
            deployed_files.append(entry)

        hot_modules: List[Any] = []
        callbacks: List[Dict[str, Any]] = []

        for entry in entries:
            mode = str(entry.get("reload_mode") or "restart").strip().lower()
            if mode == "hot_reload":
                hot_modules.extend(entry.get("modules") or [])
            elif mode == "callback":
                callbacks.append({
                    "name": entry.get("callback"),
                    "kwargs": entry.get("callback_kwargs") or {},
                })

        command_results: List[Dict[str, Any]] = []
        command_timeout = float(req.get("command_timeout_seconds", 8.0))

        if hot_modules:
            command_id = send_command(
                command_dir, {"type": "reload_modules", "modules": hot_modules})
            res = wait_for_result(result_dir, command_id,
                                  timeout_seconds=command_timeout)
            command_results.append({"id": command_id, "result": res})
            if not res or not res.get("ok"):
                return _rollback("hot_reload", command_results=command_results)

        for cb in callbacks:
            if not cb.get("name"):
                continue
            command_id = send_command(
                command_dir,
                {"type": "callback", "name": cb["name"], "kwargs": cb["kwargs"]})
            res = wait_for_result(result_dir, command_id,
                                  timeout_seconds=command_timeout)
            command_results.append({"id": command_id, "result": res})
            if not res or not res.get("ok"):
                return _rollback("callback", command_results=command_results)

        restart_request = (runtime_dir / "supervisor_requests" /
                           f"{safe_id}.restart.json")
        if req.get("force_restart"):
            atomic_write_json(restart_request, {
                "type": "restart",
                "reason": f"deploy:{safe_id}",
                "at": utc_now(),
            })

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
            atomic_write_json(restart_request, {
                "type": "restart",
                "reason": f"rollback:{safe_id}",
                "at": utc_now(),
            })
            return _rollback("health_check", command_results=command_results)

        prune_errors: List[str] = []
        prune_backups(backups_root, req, prune_errors)

        result: Dict[str, Any] = {
            "request_id": request_id,
            "ok": True,
            "phase": "complete",
            "backup_root": str(backup_root),
            "command_results": command_results,
            "handled_at": utc_now(),
        }
        if prune_errors:
            result["backup_prune_errors"] = prune_errors
        return result
    except Exception as exc:  # noqa: BLE001
        # Last-resort net: whatever went wrong mid-copy, the tree must end up
        # where it started. The exception TYPE and message are reported; the
        # deployed-file list is reduced to its request-authored keys so no
        # resolved absolute path is echoed back beyond what was sent.
        return _rollback("exception",
                         error=f"{type(exc).__name__}: {exc}",
                         files=[_public(e) for e in deployed_files])


def _default_result_path(request_path: Path) -> Path:
    """Where to write the result when `--result` was not given and the request
    is too broken to tell us. Next to the request itself: the supervisor reads
    its own `deploy_results/<stem>.json`, so this only has to be somewhere
    writable and predictable."""
    return request_path.with_suffix(".result.json")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True,
                        help="Path to deploy request JSON file.")
    parser.add_argument("--result", required=False,
                        help="Optional result JSON path.")
    args = parser.parse_args()

    request_path = Path(args.request).resolve()
    result = do_deploy(request_path)

    if args.result:
        result_path = Path(args.result).resolve()
    else:
        # Re-derive the supervisor's conventional location, but never let a
        # malformed request stop the result from being written at all - a
        # silent deploy worker is the worst failure shape here.
        try:
            req = json.loads(request_path.read_text(encoding="utf-8-sig"))
            project_root = Path(req["project_root"]).resolve()
            runtime_dir = Path(
                req.get("runtime_dir") or project_root / "ops" / "runtime"
            ).resolve()
            result_path = (runtime_dir / "deploy_results" /
                           f"{request_path.stem}.json")
        except (OSError, JSONDecodeError, KeyError, TypeError, ValueError):
            result_path = _default_result_path(request_path)

    atomic_write_json(result_path, result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""PKG-6b backend update cycle: the one command the shell runs for an update.

docs/PACKAGING_PLAN.md section 3.4 (release channel) and residual WA11. The
PKG-2 updater (ops/launcher/updater.py) has every step as its own call; this
module sequences them so the shell spawns ONE windowless child and reads ONE
JSON line back, and so the sequencing is tested under pytest with the real
deploy worker rather than in Electron:

    run:  [resume a pending op] -> check -> stage (or reuse a verified
          staging) -> apply (deferred, exit 3, while a game is live) ->
          finish (poll the supervisor's result, bounded) -> verify (main.py
          healthy again; after a supervised restart, a NEW run id) ->
          recover() when it does not come back -> the restart actions.

The supervisor's restart reaches main.py only (updater RESTART CLASSIFIER),
so the result names what is still owed: `host_services` (the service host
restarts them, ops/launcher/service_host.py command channel), `respawn_host`
(the host's own code or the dependency set changed: the shell stops and
respawns the host, which restarts every service), `relaunch_shell`
(rc-shell code; a backend payload never carries it, electron-updater does).
Those restarts are the shell's to time: it holds them until no game is live.

Restart safety (each step is a separate, persisted state):
  - a pending op (the updater's update_state.json) is finished first, so a
    cycle cut short by a quit resumes on the next one;
  - between `finish ok` and `verified` the cycle keeps a `verify` record in
    ops/runtime/launcher/update_cycle.json; the next cycle re-verifies (on
    a fresh window, alive only) and still returns the restart actions;
  - the shell quitting is never mistaken for a broken update: a gone parent
    (--parent-pid) or a halted host (launcher_status.json state halted)
    ends the cycle as `interrupted`, never in recover();
  - one cycle at a time: ops/runtime/launcher/update_cycle.lock (O_EXCL; a
    dead holder's lock is taken over, a live one's never touched).

Statuses and exit codes (stdout is ONE JSON line, `status` + `ok`):
  0  up-to-date | noop | applied | pending | interrupted | busy
  1  refused (`code` = the updater's stable UpdateError code) | failed |
     lost | recovered | error (`code` = the exception type, no message
     beyond a short sanitised line: the shell only logs it)
  3  deferred: a game is live; retry after it (the staging is kept)

Never at boot: nothing here registers anything; the shell runs it while the
app is up. Stdlib only, run under `-I` (no RC module on sys.path): the
sibling updater and service host are loaded from their files.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent.parent


def _sibling(name: str) -> Any:
    """ops/launcher/<name>.py: a package import when this module was imported
    as ops.launcher.update_cycle; under the shell's `-I` launch the folder is
    not on sys.path, so it is loaded from its file (the service host's
    first_run pattern, same module names)."""
    if __package__:
        return importlib.import_module(f"{__package__}.{name}")
    mod_name = f"rc_launcher_{name}"
    mod = sys.modules.get(mod_name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(mod_name, HERE / f"{name}.py")
        if spec is None or spec.loader is None:
            raise ImportError(f"ops/launcher/{name}.py is not loadable")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(mod_name, None)
            raise
    return mod


up = _sibling("updater")
sh = _sibling("service_host")

SCHEMA = 1
FINISH_TIMEOUT_S = 300.0    # the supervisor kills a worker at 120 s
HEALTH_TIMEOUT_S = 180.0    # main.py back after a supervised restart
SETTLE_S = 20.0             # hot_reload fires on the next mtime tick
POLL_S = 2.0
LOCK_STALE_S = 4 * 3600.0   # a lock older than this is stale whatever its pid
LOCK_TORN_S = 60.0          # an unreadable lock this old is debris
OK_EXIT = 0
FAIL_EXIT = 1
DEFER_EXIT = 3
OK_STATUSES = ("up-to-date", "noop", "applied", "pending", "interrupted", "busy")
FAIL_STATUSES = ("refused", "failed", "lost", "recovered", "error")
# Every name the service host acts on (its services.json names plus
# WATCHDOG_PORTS); app / shell are the shell's own acts.
HOST_SERVICES = frozenset(set(up.ALL_SERVICE_NAMES) - {"app", "shell"})
_DETAIL_RE = re.compile(r"[^\x20-\x7e]+")


def utc_now() -> str:
    return up.utc_now()


def cycle_path(root: Path) -> Path:
    return up.launcher_state_dir(root) / "update_cycle.json"


def lock_path(root: Path) -> Path:
    return up.launcher_state_dir(root) / "update_cycle.lock"


def _clean(text: Any, limit: int = 240) -> str:
    return _DETAIL_RE.sub(" ", str(text)).strip()[:limit]


# ------------------------------------------------------------ results


@dataclass
class CycleResult:
    status: str
    version: Optional[str] = None
    current: Optional[str] = None
    detail: Optional[str] = None
    code: Optional[str] = None
    restart: Optional[Dict[str, Any]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        if self.status == "deferred":
            return DEFER_EXIT
        return OK_EXIT if self.status in OK_STATUSES else FAIL_EXIT

    @property
    def ok(self) -> bool:
        return self.exit_code == OK_EXIT

    def to_dict(self) -> Dict[str, Any]:
        doc = {"ok": self.ok, "status": self.status, "version": self.version,
               "current": self.current, "detail": self.detail, "code": self.code,
               "restart": self.restart}
        doc.update(self.extra)
        return doc


def restart_actions(plan: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What is still owed after a deploy, from the updater's RestartPlan dict:
    the host's services, a host respawn (app), a shell relaunch (shell)."""
    plan = plan if isinstance(plan, dict) else {}
    names = [n for n in (plan.get("services") or []) if isinstance(n, str)]
    respawn = "app" in names
    host = sorted({n for n in names if n in HOST_SERVICES})
    return {"level": plan.get("level") or "none", "app": plan.get("app") or "none",
            "services": sorted(set(names)),
            # A host respawn restarts every service: nothing else to send it.
            "host_services": [] if respawn else host,
            "respawn_host": respawn, "relaunch_shell": "shell" in names,
            "stale_check": bool(plan.get("stale_check"))}


# ------------------------------------------------------------ state file


def read_cycle(root: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(cycle_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": SCHEMA, "verify": None, "last": None}
    if not isinstance(doc, dict):
        return {"schema": SCHEMA, "verify": None, "last": None}
    doc.setdefault("verify", None)
    doc.setdefault("last", None)
    return doc


def _write_cycle(root: Path, **changes: Any) -> None:
    doc = read_cycle(root)
    doc.update(changes)
    doc["schema"] = SCHEMA
    doc["updated"] = utc_now()
    up._write_json(cycle_path(root), doc)


# ------------------------------------------------------------------ lock


def _pid_alive(pid: int) -> bool:
    return sh.pid_alive(pid)


class _Lock:
    def __init__(self, root: Path) -> None:
        self.path = lock_path(root)
        self.held = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps({"pid": os.getpid(), "at": time.time()}).encode("ascii")
        for _ in range(2):
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if not self._stale():
                    return False
                try:
                    self.path.unlink()
                except OSError:
                    return False
                continue
            try:
                os.write(fd, body)
            finally:
                os.close(fd)
            self.held = True
            return True
        return False

    def _stale(self) -> bool:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            pid, at = int(doc["pid"]), float(doc.get("at") or 0.0)
        except (OSError, ValueError, KeyError, TypeError):
            # Unreadable: a holder between its O_EXCL create and its write,
            # or debris. Young = a holder; old = debris.
            try:
                return time.time() - self.path.stat().st_mtime > LOCK_TORN_S
            except OSError:
                return False
        if at and time.time() - at > LOCK_STALE_S:
            return True
        return not _pid_alive(pid)

    def release(self) -> None:
        if self.held:
            try:
                self.path.unlink()
            except OSError:
                pass
            self.held = False


# ----------------------------------------------------------------- cycle


class _Interrupted(Exception):
    pass


class _Ctx:
    def __init__(self, root: Path, *, clock, sleep, parent_alive, health, log) -> None:
        self.root = root
        self.clock = clock
        self.sleep = sleep
        self.parent_alive = parent_alive
        self.health = health
        self.log = log

    def check_alive(self, *, host: bool = True) -> None:
        """The shell gone, or (verify only) the host halted, ends the cycle as
        interrupted. The finish wait checks the parent only: a halted host
        there changes nothing on disk, and the next cycle resumes it."""
        if not self.parent_alive():
            raise _Interrupted("the shell is gone")
        if host and _host_halted(self.root):
            raise _Interrupted("the service host is stopping")


def _host_halted(root: Path) -> bool:
    try:
        doc = json.loads((up.runtime_dir(root) / "launcher_status.json")
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(doc, dict) and doc.get("state") == "halted"


def _staged_or_stage(ctx: _Ctx, source: Any, release: Any, channel: str,
                     shell_version: Optional[str]) -> Any:
    final = up.staging_root(ctx.root) / release.version
    if final.is_dir():
        try:
            staged = up.verify_staged(ctx.root, release.version)
            ctx.log(f"reusing the verified staging of {release.version}")
            return staged
        except up.UpdateError as exc:
            ctx.log(f"restaging {release.version}: the staging failed verify ({exc.code})")
    return up.stage(ctx.root, source, release, channel=channel, shell_version=shell_version)


def _wait_finish(ctx: _Ctx, timeout_s: float, poll_s: float) -> Any:
    deadline = ctx.clock() + timeout_s
    while True:
        fin = up.finish(ctx.root)
        if fin.status != "pending":
            return fin
        ctx.check_alive(host=False)
        if ctx.clock() >= deadline:
            return fin
        ctx.sleep(poll_s)


def _verify(ctx: _Ctx, rec: Dict[str, Any], *, resumed: bool, timeout_s: float,
            settle_s: float, poll_s: float) -> bool:
    """main.py healthy after the deploy. A supervised restart (app effect
    `restart`) must show a NEW run id; a hot_reload one first waits out the
    settle window (the watcher fires on its next tick). A resumed verify
    (the app was relaunched since) needs only a live heartbeat."""
    before = rec.get("run_id_before")
    need_new = (not resumed) and rec.get("app") == "restart" and bool(before)
    if not resumed and rec.get("app") == "hot_reload" and settle_s > 0:
        end = ctx.clock() + settle_s
        while ctx.clock() < end:
            ctx.check_alive()
            ctx.sleep(min(poll_s, max(end - ctx.clock(), 0.01)))
    deadline = ctx.clock() + timeout_s
    while True:
        h = ctx.health()
        alive = bool(h.get("alive"))
        if alive and (not need_new or (h.get("run_id") and h.get("run_id") != before)):
            return True
        ctx.check_alive()
        if ctx.clock() >= deadline:
            return False
        ctx.sleep(poll_s)


def _after_finish(ctx: _Ctx, fin: Any, current: Optional[str], *, health_timeout_s: float,
                  settle_s: float, poll_s: float) -> CycleResult:
    if fin.status == "pending":
        return CycleResult("pending", fin.version, current,
                           "the supervisor has not finished the deploy yet")
    if fin.status in ("failed", "lost"):
        res = fin.result or {}
        detail = (f"deploy {fin.status} in phase {res.get('phase')}"
                  if fin.status == "failed" else "the deploy request vanished with no result")
        return CycleResult(fin.status, fin.version, current, detail)
    if fin.status == "none":
        return CycleResult("up-to-date", None, current, "nothing pending")
    plan = fin.restart if isinstance(fin.restart, dict) else {}
    rec = {"version": fin.version, "kind": fin.kind, "app": plan.get("app") or "none",
           "run_id_before": fin.run_id_before, "restart": plan, "at": utc_now()}
    _write_cycle(ctx.root, verify=rec)
    return _verify_and_report(ctx, rec, current, resumed=False,
                              health_timeout_s=health_timeout_s, settle_s=settle_s,
                              poll_s=poll_s)


def _verify_and_report(ctx: _Ctx, rec: Dict[str, Any], current: Optional[str], *,
                       resumed: bool, health_timeout_s: float, settle_s: float,
                       poll_s: float) -> CycleResult:
    version = rec.get("version")
    if _verify(ctx, rec, resumed=resumed, timeout_s=health_timeout_s, settle_s=settle_s,
               poll_s=poll_s):
        _write_cycle(ctx.root, verify=None)
        return CycleResult("applied", version, version, "verified: main.py is healthy",
                           restart=restart_actions(rec.get("restart")))
    ctx.check_alive()   # a quit that raced the last probe is not a broken update
    ctx.log(f"main.py did not come back after {version}; recovering")
    try:
        out = up.recover(ctx.root)
    except up.UpdateError as exc:
        _write_cycle(ctx.root, verify=None)
        return CycleResult("failed", version, current,
                           _clean(f"the app did not come back and recover was refused: {exc}"),
                           code=exc.code)
    _write_cycle(ctx.root, verify=None)
    return CycleResult("recovered", version, (out or {}).get("to_version"),
                       "the app did not come back; the supervisor's rollback was requested",
                       extra={"requests": [Path(p).name for p in (out or {}).get("requests", [])]})


def run_cycle(root: Path, source: Any, *, channel: str = "stable",
              shell_version: Optional[str] = None,
              game_check: Optional[Callable[[], Optional[str]]] = None,
              health: Optional[Callable[[], Dict[str, Any]]] = None,
              parent_alive: Optional[Callable[[], bool]] = None,
              clock: Callable[[], float] = time.monotonic,
              sleep: Callable[[float], None] = time.sleep,
              finish_timeout_s: float = FINISH_TIMEOUT_S,
              health_timeout_s: float = HEALTH_TIMEOUT_S,
              settle_s: float = SETTLE_S, poll_s: float = POLL_S,
              log: Optional[Callable[[str], None]] = None) -> CycleResult:
    """One update cycle. Never raises for an expected outcome: every refusal
    is a CycleResult with its code. Every side effect is injectable."""
    log = log or (lambda _msg: None)
    try:
        root = up._install_root(root)
    except up.UpdateError as exc:
        return CycleResult("refused", detail=_clean(exc), code=exc.code)
    ctx = _Ctx(root, clock=clock, sleep=sleep,
               parent_alive=parent_alive or (lambda: True),
               health=health or (lambda: up.app_health(root)), log=log)
    lock = _Lock(root)
    if not lock.acquire():
        return CycleResult("busy", detail="another update cycle is running")
    current: Optional[str] = None
    try:
        try:
            current = up.installed_version(root)
            res = _cycle(ctx, source, current, channel=channel, shell_version=shell_version,
                         game_check=game_check, finish_timeout_s=finish_timeout_s,
                         health_timeout_s=health_timeout_s, settle_s=settle_s, poll_s=poll_s)
        except _Interrupted as exc:
            res = CycleResult("interrupted", None, current, _clean(exc))
        except up.GameLiveError as exc:
            res = CycleResult("deferred", None, current, _clean(exc), code=exc.code)
        except up.UpdateError as exc:
            res = CycleResult("refused", None, current, _clean(exc), code=exc.code)
        except Exception as exc:   # noqa: BLE001 - reported as one JSON line
            res = CycleResult("error", None, current, _clean(f"{type(exc).__name__}: {exc}"),
                              code=type(exc).__name__)
        # Still under the lock: the cycle file is read-modify-write, so a
        # second cycle must never interleave with this last write.
        try:
            _write_cycle(root, last=dict(res.to_dict(), at=utc_now()))
        except OSError as exc:
            log(f"cycle status not written: {type(exc).__name__}")
    finally:
        lock.release()
    log(f"cycle {res.status}: {res.detail}")
    return res


def _cycle(ctx: _Ctx, source: Any, current: Optional[str], *, channel: str,
           shell_version: Optional[str], game_check, finish_timeout_s: float,
           health_timeout_s: float, settle_s: float, poll_s: float) -> CycleResult:
    timing = {"health_timeout_s": health_timeout_s, "settle_s": settle_s, "poll_s": poll_s}
    # 1. Resume: an op a previous cycle (or a direct CLI call) left pending.
    if up.read_state(ctx.root).get("pending"):
        ctx.log("resuming a pending update operation")
        fin = _wait_finish(ctx, finish_timeout_s, poll_s)
        return _after_finish(ctx, fin, up.installed_version(ctx.root), **timing)
    # 2. Resume: a deploy that finished but was never verified.
    rec = read_cycle(ctx.root).get("verify")
    if isinstance(rec, dict) and rec.get("version"):
        ctx.log(f"re-verifying {rec.get('version')} after an interrupted cycle")
        return _verify_and_report(ctx, rec, current, resumed=True, **timing)
    # 3. A new cycle.
    release = up.check(source, channel=channel, current_version=current)
    if release is None:
        return CycleResult("up-to-date", None, current, "no newer release on this channel")
    ctx.log(f"release {release.version} available (installed {current})")
    staged = _staged_or_stage(ctx, source, release, channel, shell_version)
    _write_cycle(ctx.root, phase="staged", version=staged.version)
    applied = up.apply(ctx.root, staged.version, game_check=game_check)
    if applied.status == "noop":
        return CycleResult("noop", staged.version, staged.version,
                           "every file of the release is already live")
    ctx.log(f"deploy requested: {applied.request_id}")
    fin = _wait_finish(ctx, finish_timeout_s, poll_s)
    return _after_finish(ctx, fin, current, **timing)


# ------------------------------------------------------------------- CLI


def _log_to_file(root: Path) -> Callable[[str], None]:
    log = sh.HostLog(Path(root) / "ops" / "runtime" / "logs" / "update_cycle.log")
    return log.write


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="update_cycle",
                                 description="Amberstone backend update cycle (PKG-6b).")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="backend root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--source", required=True,
                     help="local:<dir>, github or github:<owner>/<repo>")
    run.add_argument("--channel", choices=up.CHANNELS, default="stable")
    run.add_argument("--shell-version", default=None)
    run.add_argument("--parent-pid", type=int, default=None,
                     help="the shell; once it is gone the cycle stops (never recovers)")
    run.add_argument("--finish-timeout", type=float, default=FINISH_TIMEOUT_S)
    run.add_argument("--health-timeout", type=float, default=HEALTH_TIMEOUT_S)
    sub.add_parser("status")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if args.cmd == "status":
        doc = {"ok": True, "status": "status", "cycle": read_cycle(root),
               "installed": up.installed_version(root), "state": up.read_state(root)}
        print(json.dumps(doc, sort_keys=True))
        return OK_EXIT
    parent = None
    try:
        try:
            source = up._source(args.source)
        except up.UpdateError as exc:
            res = CycleResult("refused", detail=_clean(exc), code=exc.code)
        else:
            parent = sh.ParentWatch(args.parent_pid) if args.parent_pid else None
            res = run_cycle(root, source, channel=args.channel,
                            shell_version=args.shell_version,
                            parent_alive=parent.alive if parent else None,
                            finish_timeout_s=max(1.0, args.finish_timeout),
                            health_timeout_s=max(1.0, args.health_timeout),
                            log=_log_to_file(root))
    finally:
        if parent is not None:
            parent.close()
    print(json.dumps(res.to_dict(), sort_keys=True))
    return res.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

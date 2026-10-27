"""PKG-6b backend update cycle: the one command the shell runs for an update.

docs/PACKAGING_PLAN.md section 3.4 (release channel) and residual WA11. The
PKG-2 updater (ops/launcher/updater.py) has every step as its own call; this
module sequences them so the shell spawns ONE windowless child and reads ONE
JSON line back, and so the sequencing is tested under pytest with the real
deploy worker rather than in Electron:

    run:     [resume, below] -> check (never a version that already failed)
             -> stage (or reuse a verified staging) -> apply (deferred, exit
             3, while a game is live) -> finish (bounded) -> verify ->
             recover() when main.py does not come back -> the restarts owed.
    resume:  only what an earlier cycle left: complete an interrupted
             recover, finish a pending deploy (a deploy cut off mid-copy is
             salvaged and recovered), re-verify, and - with --restarts-sent -
             health-check the restarts the shell performed. Never checks or
             applies a release, needs no /api/state: the shell runs it at
             launch and while a record exists even when main.py is down.

READY (review F1 / F7): main.py writes alive=True from DevRuntime before its
imports (main.py:98 -> :171), so a heartbeat proves nothing about new code.
A run is ready when health.json carries `last_state_provider_ok` (written
only after main.py wired its state provider, main.py:208 - after every
import and the app constructor), its pid is alive, the heartbeat is fresh
(<= HEARTBEAT_STALE_S) - all held by ONE run id for STABLE_S - and the
dashboard answers /api/health at the end. After a supervised restart the run
must also be NEW; after a hot_reload the settle window runs first and any run
change restarts the stable window, so the old run's heartbeat cannot pass a
reload that broke the new one.

OWED RESTARTS (F3): the supervisor's restart reaches main.py only (updater
RESTART CLASSIFIER), so a verified deploy names what is still owed:
`host_services` (the host restarts them, service_host.py command channel),
`respawn_host` (launcher or dependency changes: the shell respawns the
host), `relaunch_shell` (rc-shell code; never in a backend payload). They
are recorded (`owed`) until the shell reports them sent and every one came
back on a NEW process and stayed up for STABLE_S; otherwise recover() - or
`deferred` while a game is live, so a working main.py is never rolled back
mid-game.

Fix round 2: a service the host does not own (a port holder outside its job,
e.g. a DS run by the RC-DaemonSlayer task) is NOT ours to restart - skipped and
logged, never a failure and never a bad-version mark; a restart the host
deferred (a game) is owed again; a `halted` status counts only while that
host is alive and the file fresh; hot_reload needs a watcher of the current
run, and when the watcher reports it fired for these files, a NEW run.

BAD VERSIONS (F4): a version that ended recovered / failed / lost is kept in
`bad_versions` and never applied again; a newer release still is.

Restart safety (each step is a separate, persisted state):
  - the updater's `recovering` marker makes recover() re-entrant (F6);
  - a pending op (update_state.json) is finished first;
  - `verify` / `owed` records in ops/runtime/launcher/update_cycle.json
    survive a quit and are resumed;
  - the shell quitting is never mistaken for a broken update: a gone parent
    (--parent-pid) or a halted host ends the cycle as `interrupted`;
  - `phase` in the cycle file says where a cycle is (the shell never kills
    one in `deploying` / `recovering`);
  - one cycle at a time: ops/runtime/launcher/update_cycle.lock.

Recover is offline (the backup copied back here) when no supervisor holds
its lock: nobody would read a supervisor request then (a respawned host that
fails on new code).

Statuses and exit codes (stdout is ONE JSON line, `status` + `ok`):
  0  up-to-date | noop | applied | pending | interrupted | busy | owed |
     skipped (the newest release failed before) | idle (resume: nothing)
  1  refused (`code` = the updater's stable UpdateError code) | failed |
     lost | recovered | error (`code` = the exception type)
  3  deferred: a game is live; retry after it

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
import ssl
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
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
HEALTH_TIMEOUT_S = 180.0    # main.py ready after a supervised restart
SETTLE_S = 20.0             # hot_reload polls every 2 s, restarts in ~5 s
STABLE_S = 30.0             # one ready run (or one restarted process) held this long
HEARTBEAT_STALE_S = 5.0     # DevRuntime beats every 1 s (ops/rc_config.json)
STATUS_FRESH_S = 30.0       # the host rewrites launcher_status.json every 5 s
POLL_S = 2.0
LOCK_STALE_S = 4 * 3600.0   # a lock older than this is stale whatever its pid
LOCK_TORN_S = 60.0          # an unreadable lock this old is debris
DEFAULT_DASHBOARD_PORT = 8888
OK_EXIT = 0
FAIL_EXIT = 1
DEFER_EXIT = 3
OK_STATUSES = ("up-to-date", "noop", "applied", "pending", "interrupted", "busy", "owed",
               "skipped", "idle", "applied-unrestarted")
# Fix round 3: R4 the supervisor takes a rollback request within its loop;
# R7 a recover that cannot complete backs off and, after this many tries,
# asks for attention; R5 the shell's idle LCU phases (rc-shell
# src/backend_update.js IDLE_PHASES; a test pins the mirror).
SUPERVISOR_TAKE_S = 60.0
RECOVER_ATTENTION_AFTER = 3
IDLE_PHASES = ("", "None", "Lobby")
QUIT_SLACK_S = 2.0
# Fix round 4 (M1): the longest a deploy can legitimately run after its
# request was written - the worker honours a request until it expires
# (updater REQUEST_TTL_S) and the supervisor kills a worker at 120 s - so a
# host stop excuses a failed deploy only inside [request, request + this];
# and a release is excused by a quit at most QUIT_EXCUSES_MAX times.
WORKER_KILL_S = 120.0
DEPLOY_MAX_S = up.REQUEST_TTL_S + WORKER_KILL_S + 60.0
QUIT_EXCUSES_MAX = 2
# M2: outcomes that skip a service with nothing old left running (no notice).
QUIET_SKIPS = frozenset({"not-running", "not-configured"})
SERVICE_LABELS = {"ds": "Daemon Slayer", "vision": "the vision server",
                  "lcu_agent": "the LCU agent", "liveclient_relay": "the Live Client relay",
                  "hotkey_listener": "the hotkey listener", "supervisor": "the RC supervisor",
                  "phase3_supervisor": "the Phase 3 supervisor", "app": "the service host"}
FAIL_STATUSES = ("refused", "failed", "lost", "recovered", "error")
BAD_STATUSES = ("recovered", "failed", "lost")
# Every name the service host acts on (its services.json names plus
# WATCHDOG_PORTS); app / shell are the shell's own acts.
HOST_SERVICES = frozenset(set(up.ALL_SERVICE_NAMES) - {"app", "shell"})
# Restart outcomes (service_host.py) that mean "not this host's to restart":
# the service is skipped by the restart check, never a failure.
NOT_OURS = frozenset({"refused:not-in-job", "refused:no-job", "refused:not-owned",
                      "refused:unsupported", "not-configured", "not-running",
                      # R2: a process the host cannot even open is not in its job
                      "refused:open-failed"})
_DETAIL_RE = re.compile(r"[^\x20-\x7e]+")


def utc_now() -> str:
    return up.utc_now()


def cycle_path(root: Path) -> Path:
    return up.launcher_state_dir(root) / "update_cycle.json"


def lock_path(root: Path) -> Path:
    return up.launcher_state_dir(root) / "update_cycle.lock"


def _clean(text: Any, limit: int = 240) -> str:
    return _DETAIL_RE.sub(" ", str(text)).strip()[:limit]


def _epoch(iso: Any) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(iso)).timestamp()
    except (TypeError, ValueError):
        return None


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


def _owes(actions: Dict[str, Any]) -> bool:
    return bool(actions.get("host_services")) or bool(actions.get("respawn_host"))


# ------------------------------------------------------------ state file


def read_cycle(root: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(cycle_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    doc.setdefault("schema", SCHEMA)
    for key in ("verify", "owed", "last", "phase"):
        doc.setdefault(key, None)
    if not isinstance(doc.get("bad_versions"), dict):
        doc["bad_versions"] = {}
    return doc


def _write_cycle(root: Path, **changes: Any) -> None:
    doc = read_cycle(root)
    doc.update(changes)
    doc["schema"] = SCHEMA
    doc["updated"] = utc_now()
    up._write_json(cycle_path(root), doc)


def _mark_bad(root: Path, version: Optional[str], status: str) -> None:
    if not isinstance(version, str) or not up.VERSION_RE.match(version):
        return
    bad = dict(read_cycle(root)["bad_versions"])
    bad[version] = {"status": status, "at": utc_now()}
    _write_cycle(root, bad_versions=bad)


# ------------------------------------------------------------ probes


def readiness(root: Path) -> Dict[str, Any]:
    """One readiness sample of main.py from ops/runtime/health.json: alive,
    ready (the post-import `last_state_provider_ok`), run_id, heartbeat age,
    pid_alive. Never raises."""
    path = up.runtime_dir(root) / "health.json"
    try:
        age = time.time() - path.stat().st_mtime
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"alive": False, "ready": False, "run_id": None, "age_s": None,
                "pid_alive": False}
    doc = doc if isinstance(doc, dict) else {}
    pid = doc.get("pid")
    alive_pid = isinstance(pid, int) and not isinstance(pid, bool) and sh.pid_alive(pid)
    return {"alive": doc.get("alive") is True, "ready": doc.get("last_state_provider_ok") is True,
            "run_id": str(doc.get("run_id") or "") or None, "age_s": round(age, 2),
            "pid_alive": bool(alive_pid)}


def _sample_ok(s: Dict[str, Any]) -> bool:
    age = s.get("age_s")
    return bool(s.get("alive") and s.get("ready") and s.get("pid_alive") and s.get("run_id")
                and isinstance(age, (int, float)) and age <= HEARTBEAT_STALE_S)


def busy_from_state(doc: Any) -> Optional[str]:
    """Why an /api/state document is NOT an idle moment, else None - the
    shell's bu.idleForUpdate: live-game flags (under `health`,
    dashboard/_state_builder.py:1058-1072), a non-empty liveclient, or an
    LCU phase outside IDLE_PHASES (champ select, queue, loading, ...)."""
    if not isinstance(doc, dict):
        return "no /api/state"
    health = doc.get("health") if isinstance(doc.get("health"), dict) else {}
    for flag in up.LIVE_GAME_FLAGS:
        if health.get(flag) is True or doc.get(flag) is True:
            return f"health {flag}"
    lc = doc.get("liveclient")
    if isinstance(lc, dict) and lc:
        return "liveclient active"
    lcu = doc.get("lcu") if isinstance(doc.get("lcu"), dict) else {}
    phase = "" if lcu.get("phase") is None else str(lcu.get("phase"))
    return None if phase in IDLE_PHASES else f"lcu phase {phase}"[:80]


def fetch_api_state(root: Path) -> Optional[Dict[str, Any]]:
    """GET /api/state from the local dashboard (loopback, the origin the
    host's own health probe finds), or None."""
    origin = sh.fetch_health_origin(dashboard_port())
    if not origin:
        return None
    tls = ssl.create_default_context()
    tls.check_hostname = False
    tls.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                         urllib.request.HTTPSHandler(context=tls))
    try:
        with opener.open(f"{origin}/api/state", timeout=3.0) as r:
            doc = json.loads(r.read(4 << 20).decode("utf-8", "replace"))
    except Exception:   # noqa: BLE001 - unreadable = not idle
        return None
    return doc if isinstance(doc, dict) else None


def _apply_gate(root: Path) -> Optional[str]:
    """The default apply-time check: a game process / fresh health flag
    (updater.game_live), else the shell's LCU-phase gate (R5)."""
    return up.game_live(root) or busy_from_state(fetch_api_state(root))


def _quit_overlapped(root: Path, since: Optional[float], until: Optional[float]) -> bool:
    """R1: did the host stop the app (service_host.record_host_stop) inside
    [since, until]? A deploy that failed then is not a bad release."""
    if since is None:
        return False
    # M1: never past the deploy's own longest life, whatever `until` says.
    hi = min(until if until is not None else since + DEPLOY_MAX_S,
             since + DEPLOY_MAX_S) + QUIT_SLACK_S
    try:
        doc = json.loads((up.launcher_state_dir(root) / "host_stops.json")
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    for stop in (doc.get("stops") if isinstance(doc, dict) else None) or []:
        at = stop.get("at") if isinstance(stop, dict) else None
        if isinstance(at, (int, float)) and since - QUIT_SLACK_S <= at <= hi:
            return True
    return False


def dashboard_port() -> int:
    try:
        doc = json.loads(sh.DEFAULT_SERVICES.read_text(encoding="utf-8"))
        port = int(doc.get("dashboard_port"))
        return port if 0 < port < 65536 else DEFAULT_DASHBOARD_PORT
    except (OSError, ValueError, TypeError):
        return DEFAULT_DASHBOARD_PORT


def _host_status(root: Path) -> Dict[str, Any]:
    try:
        doc = json.loads((up.runtime_dir(root) / "launcher_status.json")
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def services_state(root: Path, owed: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """For each owed name: did it come back on a process started after the
    deploy, is it healthy, and which pid holds it. Host services from the
    host's fresh status file; vision / ds from the process listening on
    their port (sh.port_listener_pids + its creation time); `app` (a host
    respawn) from a new host pid in owned mode with every service running."""
    at = float(owed.get("at_epoch") or 0.0)
    status = _host_status(root)
    upd = _epoch(status.get("updated"))
    fresh = upd is not None and time.time() - upd <= STATUS_FRESH_S
    entries = {s.get("name"): s for s in status.get("services") or [] if isinstance(s, dict)}
    # The host's own verdict on the newest restart command naming each
    # service since the deploy (service_host.py `commands`).
    outcome: Dict[str, str] = {}
    for rec in [] if owed.get("ignore_commands") else status.get("commands") or []:
        if not isinstance(rec, dict) or (_epoch(rec.get("at")) or 0.0) < at:
            continue
        for n, o in (rec.get("results") or {}).items():
            if isinstance(o, str):
                outcome[n] = o
    out: Dict[str, Dict[str, Any]] = {}
    for name in owed.get("names") or []:
        o = outcome.get(name, "")
        if o.startswith("deferred:"):
            out[name] = {"restarted": False, "healthy": False, "pid": None, "deferred": o}
            continue
        if o in NOT_OURS:
            out[name] = {"restarted": False, "healthy": False, "pid": None, "skip": o}
            continue
        if name == "app":
            pid = status.get("host_pid")
            running = bool(entries) and all(s.get("state") == "running"
                                            for s in entries.values())
            new = isinstance(pid, int) and pid != owed.get("host_pid_before")
            ok = fresh and status.get("mode") == "owned" and running
            out[name] = {"restarted": bool(fresh and new), "healthy": bool(ok), "pid": pid}
        elif name in sh.WATCHDOG_PORTS:
            pids = sh.port_listener_pids(sh.WATCHDOG_PORTS[name])
            pid = pids[0] if pids else None
            created = sh.process_created(pid) if pid else None
            out[name] = {"restarted": bool(created is not None and created > at),
                         "healthy": pid is not None, "pid": pid}
        else:
            e = entries.get(name) or {}
            started = _epoch(e.get("started"))
            out[name] = {"restarted": bool(fresh and started is not None and started > at),
                         "healthy": bool(fresh and e.get("state") == "running"),
                         "pid": e.get("pid")}
    return out


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


# ----------------------------------------------------------------- context


class _Interrupted(Exception):
    pass


@dataclass
class _Ctx:
    root: Path
    clock: Callable[[], float]
    sleep: Callable[[float], None]
    now: Callable[[], float]
    uptime: Callable[[], float]
    parent_alive: Callable[[], bool]
    health: Callable[[], Dict[str, Any]]
    serving: Callable[[], bool]
    services_probe: Callable[[Dict[str, Any]], Dict[str, Dict[str, Any]]]
    supervisor_alive: Callable[[], bool]
    game_check: Optional[Callable[[], Optional[str]]]
    log: Callable[[str], None]
    finish_timeout_s: float
    health_timeout_s: float
    settle_s: float
    stable_s: float
    poll_s: float

    def check_alive(self, *, host: bool = True) -> None:
        """The shell gone, or (verify only) the host halted, ends the cycle as
        interrupted. The finish wait checks the parent only: a halted host
        there changes nothing on disk, and the next cycle resumes it."""
        if not self.parent_alive():
            raise _Interrupted("the shell is gone")
        if host and _host_halted(self.root):
            raise _Interrupted("the service host is stopping")

    def phase(self, name: str, version: Optional[str] = None) -> None:
        _write_cycle(self.root, phase=name, version=version)

    def game_reason(self) -> Optional[str]:
        probe = self.game_check if self.game_check is not None else \
            (lambda: up.game_live(self.root))
        try:
            return probe()
        except Exception as exc:   # noqa: BLE001 - a failed probe defers
            return f"game check failed: {type(exc).__name__}"


def _host_halted(root: Path) -> bool:
    """A host is stopping RIGHT NOW: its status says halted, the file is
    fresh and its pid is alive. Every stop writes `halted`, so a dead host's
    last status (a respawned host that died on import) is no quit."""
    st = _host_status(root)
    if st.get("state") != "halted":
        return False
    upd = _epoch(st.get("updated"))
    pid = st.get("host_pid")
    return bool(upd is not None and time.time() - upd <= STATUS_FRESH_S
                and isinstance(pid, int) and not isinstance(pid, bool) and sh.pid_alive(pid))


def _make_ctx(root: Path, *, clock, sleep, now, uptime, parent_alive, health, serving,
              services_probe, supervisor_alive, game_check, log, finish_timeout_s,
              health_timeout_s, settle_s, stable_s, poll_s) -> _Ctx:
    port = dashboard_port()
    lock = up.runtime_dir(root) / "supervisor.pid"
    return _Ctx(
        root=root, clock=clock, sleep=sleep, now=now, uptime=uptime or up.boot_uptime_s,
        parent_alive=parent_alive or (lambda: True),
        health=health or (lambda: readiness(root)),
        serving=serving or (lambda: sh.fetch_health_origin(port) is not None),
        services_probe=services_probe or (lambda owed: services_state(root, owed)),
        supervisor_alive=supervisor_alive or (lambda: sh.lock_holder_alive(lock)),
        game_check=game_check, log=log or (lambda _m: None),
        finish_timeout_s=finish_timeout_s, health_timeout_s=health_timeout_s,
        settle_s=settle_s, stable_s=stable_s, poll_s=poll_s)


# ----------------------------------------------------------------- steps


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


def _wait_finish(ctx: _Ctx) -> Any:
    deadline = ctx.clock() + ctx.finish_timeout_s
    while True:
        fin = up.finish(ctx.root, now=ctx.now, uptime=ctx.uptime)
        if fin.status != "pending":
            return fin
        ctx.check_alive(host=False)
        if ctx.clock() >= deadline:
            return fin
        ctx.sleep(ctx.poll_s)


def _wait_ready(ctx: _Ctx, *, before: Optional[str], need_new: bool, settle: bool) -> bool:
    """READY (module docstring): one ready run held for stable_s, then the
    dashboard answering. A run change restarts the window."""
    if settle and ctx.settle_s > 0:
        end = ctx.clock() + ctx.settle_s
        while ctx.clock() < end:
            ctx.check_alive()
            ctx.sleep(min(ctx.poll_s, max(end - ctx.clock(), 0.01)))
    deadline = ctx.clock() + ctx.health_timeout_s
    cand: Optional[str] = None
    since = 0.0
    while True:
        s = ctx.health()
        rid = s.get("run_id")
        if _sample_ok(s) and not (need_new and rid == before):
            if rid != cand:
                cand, since = rid, ctx.clock()
            elif ctx.clock() - since >= ctx.stable_s and ctx.serving():
                return True
        else:
            cand = None
        ctx.check_alive()
        if ctx.clock() >= deadline:
            return False
        ctx.sleep(ctx.poll_s)


def _rolled_back_actions(root: Path, version: Optional[str]) -> Dict[str, Any]:
    """R4: the restarts the ROLLED-BACK files need, classified exactly as
    apply classified the update (a service may have loaded the new code)."""
    rec = up.read_installed(root) or {}
    if rec.get("version") != version:
        return restart_actions(None)
    paths = sorted(set(rec.get("pre_hashes") or {}) | set(rec.get("created") or []))
    if not paths:
        return restart_actions(None)
    return restart_actions(up.classify_paths(paths, hot_reload_active=False).to_dict())


def _merge_actions(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    respawn = bool(a.get("respawn_host") or b.get("respawn_host"))
    out = dict(a)
    out.update(respawn_host=respawn,
               host_services=[] if respawn else sorted(set(a.get("host_services") or [])
                                                     | set(b.get("host_services") or [])),
               relaunch_shell=bool(a.get("relaunch_shell") or b.get("relaunch_shell")))
    return out


def _await_supervisor(ctx: _Ctx, requests: List[str]) -> None:
    """R4: owed restarts must load the RESTORED files, so wait (bounded) for
    the supervisor to take its rollback request (it unlinks each request
    after handling it, ops/rc_supervisor.py:1325)."""
    end = ctx.clock() + SUPERVISOR_TAKE_S
    while any(Path(r).exists() for r in requests) and ctx.clock() < end:
        ctx.check_alive(host=False)
        ctx.sleep(ctx.poll_s)


def _recover(ctx: _Ctx, version: Optional[str], current: Optional[str], why: str, *,
             actions: Optional[Dict[str, Any]] = None, bad: bool = True) -> CycleResult:
    ctx.check_alive()   # a quit that raced the last probe is not a broken update
    offline = not ctx.supervisor_alive()
    ctx.log(f"{why}; recovering {version} ({'offline' if offline else 'via the supervisor'})")
    ctx.phase("recovering", version)
    owed_back = _rolled_back_actions(ctx.root, version)
    try:
        out = up.recover(ctx.root, now=ctx.now, offline=offline)
    except up.UpdateError as exc:
        _write_cycle(ctx.root, verify=None, owed=None, phase="done")
        if bad:
            _mark_bad(ctx.root, version, "failed")
        return CycleResult("failed", version, current,
                           _clean(f"{why} and recover was refused: {exc}"), code=exc.code)
    _write_cycle(ctx.root, verify=None, owed=None, phase="done")
    if bad:
        _mark_bad(ctx.root, version, "recovered")
    if not offline:
        _await_supervisor(ctx, list((out or {}).get("requests") or []))
    act = _merge_actions(dict(actions) if actions else restart_actions(None), owed_back)
    if offline:
        # No supervisor ran the old code back in: the host itself failed, so
        # the shell respawns it on the restored files.
        act.update(respawn_host=True, host_services=[])
    return CycleResult("recovered", version, (out or {}).get("to_version"),
                       _clean(f"{why}; the update was rolled back "
                              f"({'restored here' if offline else 'supervisor rollback'})"),
                       restart=act,
                       extra={"requests": [Path(p).name for p in (out or {}).get("requests", [])]})


def _foreign_notice(version: Optional[str], foreign: Dict[str, str]) -> str:
    """M2: the plain-words state for services the host does not run."""
    who = ", ".join(SERVICE_LABELS.get(n, n) for n in sorted(foreign))
    return _clean(f"Backend update {version or ''} installed, but {who} still runs the old "
                  "code: it runs outside Amberstone (a scheduled task) - restart it or "
                  "reboot the PC to finish the update", 240)


def _notice_check(ctx: _Ctx) -> Dict[str, Any]:
    """M2: a persisted notice stays until every named service is seen on a
    process started after the update (its old refusal is ignored)."""
    rec = read_cycle(ctx.root).get("notice")
    if not isinstance(rec, dict) or not rec.get("names"):
        return {}
    names = sorted(rec["names"])
    st = ctx.services_probe({"names": names, "at_epoch": rec.get("at_epoch") or 0.0,
                             "ignore_commands": True})
    if all((st.get(n) or {}).get("restarted") for n in names):
        _write_cycle(ctx.root, notice=None)
        ctx.log("the services named in the update notice restarted; notice cleared")
        return {}
    return {"notice": rec.get("text")}


def _complete_recover(ctx: _Ctx, current: Optional[str]) -> CycleResult:
    marker = up.read_state(ctx.root).get("recovering") or {}
    version = marker.get("version")
    doc = read_cycle(ctx.root)
    fails = int(doc.get("recover_failures") or 0)
    retry_after = doc.get("retry_after")
    if isinstance(retry_after, (int, float)) and ctx.now() < retry_after:
        return CycleResult("failed", version, current,
                           "an interrupted recover waits before its next try",
                           code="recovery_attention" if fails >= RECOVER_ATTENTION_AFTER
                           else "recover_backoff")
    ctx.log(f"completing an interrupted recover of {version}")
    ctx.phase("recovering", version)
    try:
        out = up.recover(ctx.root, now=ctx.now, offline=bool(marker.get("offline")))
    except (up.UpdateError, OSError) as exc:
        # R7: never a tight retry loop; after RECOVER_ATTENTION_AFTER tries
        # the shell shows "update recovery needs attention".
        fails += 1
        delay = min(60.0 * 2 ** (fails - 1), 3600.0)
        try:   # L3: a full disk must not hide the attention state
            _write_cycle(ctx.root, recover_failures=fails, retry_after=float(ctx.now()) + delay)
        except OSError:
            ctx.log("the recover backoff could not be recorded")
        code = "recovery_attention" if fails >= RECOVER_ATTENTION_AFTER else "recover_failed"
        ctx.log(f"completing the recover failed ({type(exc).__name__}); try {fails}")
        return CycleResult("failed", version, current,
                           _clean(f"completing the recover failed ({type(exc).__name__}); "
                                  f"next try in {int(delay)} s"), code=code)
    _write_cycle(ctx.root, verify=None, owed=None, phase="done", recover_failures=0,
                 retry_after=None)
    _mark_bad(ctx.root, version, "recovered")
    act = restart_actions(None)
    if marker.get("offline"):
        act.update(respawn_host=True)
    return CycleResult("recovered", version, (out or {}).get("to_version"),
                       "an interrupted recover was completed", restart=act)


def _reload_outcome(root: Path, since: Optional[float], changed: List[str]) -> str:
    """What core/hot_reload.py did with this deploy's files, from its status
    file (core/hot_reload.py _fire / tick): `fired` (rewritten since the
    deploy, naming one of them, compile OK), `compile_failed`, or `quiet`
    (not rewritten: none of them was loaded, so the running main.py never
    held their old code - the only case an old run may verify)."""
    path = up.runtime_dir(root) / "hot_reload.json"
    try:
        written = path.stat().st_mtime
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return "quiet"
    if since is None or written + 1.0 < since or not isinstance(doc, dict):
        return "quiet"
    compiled = str(doc.get("last_compile") or "")
    named = set(doc.get("changed") or []) | set(doc.get("pending") or []) | \
        {doc.get("last_change")}
    if not named & set(changed):
        return "quiet"
    if compiled.startswith("DEFERRED"):
        return "deferred"   # held for a game: not yet reloaded (fix round 3)
    return "compile_failed" if compiled.startswith("FAILED") else "fired"


def _verify_and_report(ctx: _Ctx, rec: Dict[str, Any], current: Optional[str], *,
                       resumed: bool) -> CycleResult:
    version = rec.get("version")
    app = rec.get("app") or "none"
    before = rec.get("run_id_before")
    ctx.phase("verifying", version)
    need_new = not resumed and app == "restart" and bool(before)
    if (not resumed or rec.get("reload_deferred")) and app == "hot_reload":
        # The watcher was fresh at apply (updater.hot_reload_watching, else
        # the plan would be `restart`). Settle, then ask what it did.
        end = ctx.clock() + ctx.settle_s
        while ctx.clock() < end:
            ctx.check_alive()
            ctx.sleep(min(ctx.poll_s, max(end - ctx.clock(), 0.01)))
        changed = [r.get("path") for r in (rec.get("restart") or {}).get("reasons") or []
                   if isinstance(r, dict) and r.get("app") == "hot_reload"]
        what = _reload_outcome(ctx.root, rec.get("requested_at"), changed)
        ctx.log(f"hot_reload after the deploy: {what}")
        if what == "compile_failed":
            return _recover(ctx, version, current, "core/hot_reload.py could not compile it")
        if what == "deferred":
            _write_cycle(ctx.root, verify=dict(rec, reload_deferred=True))
            return CycleResult("deferred", version, current,
                               "core/hot_reload.py holds the reload for a game; verify waits",
                               code="game_live")
        need_new = what == "fired" and bool(before)
    ok = _wait_ready(ctx, before=before, need_new=need_new, settle=False)
    if not ok:
        return _recover(ctx, version, current, "main.py did not become ready")
    actions = restart_actions(rec.get("restart"))
    excuses = dict(read_cycle(ctx.root).get("quit_excuses") or {})
    excuses.pop(str(version), None)
    _write_cycle(ctx.root, notice=None, quit_excuses=excuses)   # M2 / M1
    if _owes(actions):
        names = list(actions["host_services"]) + (["app"] if actions["respawn_host"] else [])
        owed = {"version": version, "names": names, "respawn_host": actions["respawn_host"],
                "host_pid_before": _host_status(ctx.root).get("host_pid"),
                "at": utc_now(), "at_epoch": float(ctx.now()), "restart": rec.get("restart")}
        _write_cycle(ctx.root, verify=None, owed=owed, phase="owed")
        detail = "verified: main.py is ready; restarts owed: " + ", ".join(names)
    else:
        _write_cycle(ctx.root, verify=None, phase="done")
        detail = "verified: main.py is ready"
    return CycleResult("applied", version, version, detail, restart=actions)


def _after_finish(ctx: _Ctx, fin: Any, current: Optional[str]) -> CycleResult:
    if fin.status == "pending":
        return CycleResult("pending", fin.version, current,
                           "the supervisor has not finished the deploy yet")
    res = fin.result if isinstance(fin.result, dict) else {}
    quit_hit = fin.status in ("interrupted", "failed", "lost") and _quit_overlapped(
        ctx.root, getattr(fin, "requested_at", None), res.get("result_at"))
    if quit_hit:
        # M1: a user restarting a visibly broken app cannot excuse it forever.
        excuses = dict(read_cycle(ctx.root).get("quit_excuses") or {})
        n = int(excuses.get(str(fin.version)) or 0) + 1
        excuses[str(fin.version)] = n
        _write_cycle(ctx.root, quit_excuses=excuses)
        quit_hit = n <= QUIT_EXCUSES_MAX
    if fin.status == "interrupted":
        if fin.kind == "apply":
            return _recover(ctx, fin.version, current,
                            "the deploy was cut off mid-copy (the supervisor stopped)",
                            bad=not quit_hit)
        return CycleResult("failed", fin.version, current,
                           "a rollback was cut off; run it again", code="interrupted")
    if fin.status in ("failed", "lost") and quit_hit:
        # R1: the app was quit during the deploy (the supervisor stopped
        # main.py, the worker's heartbeat wait failed and it rolled back) -
        # not a bad release; the next idle cycle applies it again.
        _write_cycle(ctx.root, phase="interrupted")   # L5: not a protected phase
        return CycleResult("interrupted", fin.version, current,
                           "the app was stopped during the deploy; it will be retried")
    if fin.status in ("failed", "lost"):
        _mark_bad(ctx.root, fin.version, fin.status)
        detail = (f"deploy failed in phase {res.get('phase')}" if fin.status == "failed"
                  else "the deploy request vanished with no result")
        return CycleResult(fin.status, fin.version, current, detail)
    if fin.status == "none":
        return CycleResult("up-to-date", None, current, "nothing pending")
    plan = fin.restart if isinstance(fin.restart, dict) else {}
    rec = {"version": fin.version, "kind": fin.kind, "app": plan.get("app") or "none",
           "run_id_before": fin.run_id_before, "restart": plan, "at": utc_now(),
           "requested_at": getattr(fin, "requested_at", None)}
    _write_cycle(ctx.root, verify=rec)
    return _verify_and_report(ctx, rec, current, resumed=False)


def _check_restarts(ctx: _Ctx, owed: Dict[str, Any], current: Optional[str]) -> CycleResult:
    """F3: every owed name back on a NEW process, healthy, the same pids held
    for stable_s, and main.py ready throughout; else recover (deferred while
    a game is live)."""
    version = owed.get("version")
    all_names = list(owed.get("names") or [])
    owed = dict(owed, sent_at=utc_now())   # B4: the shell retries a sent check
    _write_cycle(ctx.root, owed=owed)
    ctx.phase("restart-check", version)
    deadline = ctx.clock() + ctx.health_timeout_s
    cand = None
    since = 0.0
    skipped: Dict[str, str] = {}
    while True:
        st = ctx.services_probe(owed)
        deferred = sorted(n for n in all_names if (st.get(n) or {}).get("deferred"))
        if deferred:
            # The host refused to restart them mid-game: owed again (B3).
            _write_cycle(ctx.root, owed=dict(owed, sent_at=None), phase="owed")
            return CycleResult("owed", version, current,
                               "the host deferred the restarts (a game): " + ", ".join(deferred),
                               code="host_deferred",
                               restart=restart_actions(owed.get("restart")))
        skipped = {n: (st.get(n) or {}).get("skip") for n in all_names
                   if (st.get(n) or {}).get("skip")}
        names = [n for n in all_names if n not in skipped]
        main = ctx.health()
        good = _sample_ok(main) and all(
            (st.get(n) or {}).get("restarted") and (st.get(n) or {}).get("healthy")
            and (st.get(n) or {}).get("pid") for n in names)
        if good:
            key = tuple([(st.get(n) or {}).get("pid") for n in names] + [main.get("run_id")])
            if key != cand:
                cand, since = key, ctx.clock()
            elif ctx.clock() - since >= ctx.stable_s and ctx.serving():
                _write_cycle(ctx.root, owed=None, phase="done")
                detail = "verified: the restarted services stayed up: " + \
                    (", ".join(names) or "none")
                foreign = {n: o for n, o in skipped.items() if o not in QUIET_SKIPS}
                if skipped:
                    ctx.log("not ours to restart: " + ", ".join(
                        f"{n} ({o})" for n, o in sorted(skipped.items())))
                if foreign:
                    # R2 / M2: these still run the old code and an app restart
                    # does not reach them: say who they are and how they
                    # restart; the notice persists until they are seen on a
                    # new process (or the next update lands).
                    text = _foreign_notice(version, foreign)
                    _write_cycle(ctx.root, notice={
                        "version": version, "names": foreign, "text": text, "at": utc_now(),
                        "at_epoch": owed.get("at_epoch")})
                    detail = "installed; not restarted (not ours): " + ", ".join(
                        f"{n} ({o})" for n, o in sorted(foreign.items())) + \
                        ("; restarted and verified: " + ", ".join(names) if names else "")
                    return CycleResult("applied-unrestarted", version, version, _clean(detail),
                                       restart=restart_actions(None), extra={"notice": text})
                return CycleResult("applied", version, version, detail,
                                   restart=restart_actions(None))
        else:
            cand = None
        ctx.check_alive(host=False)
        if ctx.clock() >= deadline:
            break
        ctx.sleep(ctx.poll_s)
    names = [n for n in all_names if n not in skipped]
    failing = [n for n in names if not ((st.get(n) or {}).get("restarted")
                                       and (st.get(n) or {}).get("healthy"))]
    if _sample_ok(main):
        reason = ctx.game_reason()
        if reason:
            return CycleResult("deferred", version, current,
                               _clean(f"restarted services not healthy ({', '.join(failing)}); "
                                      f"recover waits for the game to end ({reason})"),
                               code="game_live")
    actions = restart_actions(owed.get("restart"))
    return _recover(ctx, version, current,
                    "restarted services did not stay up: " + (", ".join(failing) or "unstable"),
                    actions=actions)


def _resume(ctx: _Ctx, current: Optional[str], *, restarts_sent: bool) -> Optional[CycleResult]:
    """What an earlier cycle left, in order; None = nothing recorded."""
    if up.read_state(ctx.root).get("recovering"):
        return _complete_recover(ctx, current)
    if up.read_state(ctx.root).get("pending"):
        ctx.log("resuming a pending update operation")
        fin = _wait_finish(ctx)
        return _after_finish(ctx, fin, up.installed_version(ctx.root))
    doc = read_cycle(ctx.root)
    rec = doc.get("verify")
    if isinstance(rec, dict) and rec.get("version"):
        ctx.log(f"re-verifying {rec.get('version')} after an interrupted cycle")
        return _verify_and_report(ctx, rec, current, resumed=True)
    owed = doc.get("owed")
    if isinstance(owed, dict) and owed.get("version"):
        if not restarts_sent:
            return CycleResult("owed", owed.get("version"), current,
                               "restarts owed: " + ", ".join(owed.get("names") or []),
                               restart=restart_actions(owed.get("restart")))
        return _check_restarts(ctx, owed, current)
    return None


def _run(ctx: _Ctx, source: Any, current: Optional[str], *, channel: str,
         shell_version: Optional[str], game_check) -> CycleResult:
    resumed = _resume(ctx, current, restarts_sent=False)
    if resumed is not None:
        return resumed
    bad = read_cycle(ctx.root)["bad_versions"]
    release = up.check(source, channel=channel, current_version=current)
    if release is None:
        return CycleResult("up-to-date", None, current, "no newer release on this channel")
    if release.version in bad:
        alt = up.check(source, channel=channel, current_version=current, exclude=set(bad))
        if alt is None:
            return CycleResult("skipped", release.version, current,
                               f"release {release.version} failed before "
                               f"({bad[release.version].get('status')}); waiting for a newer one")
        release = alt
    ctx.log(f"release {release.version} available (installed {current})")
    staged = _staged_or_stage(ctx, source, release, channel, shell_version)
    ctx.phase("staged", staged.version)
    applied = up.apply(ctx.root, staged.version,
                       game_check=game_check if game_check is not None
                       else (lambda: _apply_gate(ctx.root)))
    if applied.status == "noop":
        _write_cycle(ctx.root, phase="done")
        return CycleResult("noop", staged.version, staged.version,
                           "every file of the release is already live")
    ctx.log(f"deploy requested: {applied.request_id}")
    ctx.phase("deploying", staged.version)
    fin = _wait_finish(ctx)
    return _after_finish(ctx, fin, current)


def _guarded(root: Path, ctx_kw: Dict[str, Any], body: Callable[[_Ctx, Optional[str]], Any],
             log: Callable[[str], None]) -> CycleResult:
    try:
        root = up._install_root(root)
    except up.UpdateError as exc:
        return CycleResult("refused", detail=_clean(exc), code=exc.code)
    ctx = _make_ctx(root, log=log, **ctx_kw)
    lock = _Lock(root)
    if not lock.acquire():
        return CycleResult("busy", detail="another update cycle is running")
    current: Optional[str] = None
    try:
        try:
            ctx.phase("starting")   # L5: never inherit a protected phase
            current = up.installed_version(root)
            res = body(ctx, current)
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
            doc = read_cycle(root)
            phase = doc.get("phase")
            if res.status not in ("interrupted", "pending", "owed", "deferred"):
                phase = "done"
            _write_cycle(root, last=dict(res.to_dict(), at=utc_now()), phase=phase)
        except OSError as exc:
            log(f"cycle status not written: {type(exc).__name__}")
    finally:
        lock.release()
    log(f"cycle {res.status}: {res.detail}")
    return res


def _ctx_kw(*, clock, sleep, now, uptime, parent_alive, health, serving, services_probe,
            supervisor_alive, game_check, finish_timeout_s, health_timeout_s, settle_s,
            stable_s, poll_s) -> Dict[str, Any]:
    return dict(clock=clock, sleep=sleep, now=now, uptime=uptime, parent_alive=parent_alive,
                health=health,
                serving=serving, services_probe=services_probe,
                supervisor_alive=supervisor_alive, game_check=game_check,
                finish_timeout_s=finish_timeout_s, health_timeout_s=health_timeout_s,
                settle_s=settle_s, stable_s=stable_s, poll_s=poll_s)


def run_cycle(root: Path, source: Any, *, channel: str = "stable",
              shell_version: Optional[str] = None,
              game_check: Optional[Callable[[], Optional[str]]] = None,
              health: Optional[Callable[[], Dict[str, Any]]] = None,
              serving: Optional[Callable[[], bool]] = None,
              services_probe: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
              supervisor_alive: Optional[Callable[[], bool]] = None,
              parent_alive: Optional[Callable[[], bool]] = None,
              clock: Callable[[], float] = time.monotonic,
              sleep: Callable[[float], None] = time.sleep,
              now: Callable[[], float] = time.time,
              uptime: Optional[Callable[[], float]] = None,
              finish_timeout_s: float = FINISH_TIMEOUT_S,
              health_timeout_s: float = HEALTH_TIMEOUT_S,
              settle_s: float = SETTLE_S, stable_s: float = STABLE_S, poll_s: float = POLL_S,
              log: Optional[Callable[[str], None]] = None) -> CycleResult:
    """One update cycle. Never raises for an expected outcome: every refusal
    is a CycleResult with its code. Every side effect is injectable."""
    kw = _ctx_kw(clock=clock, sleep=sleep, now=now, uptime=uptime, parent_alive=parent_alive,
                 health=health,
                 serving=serving, services_probe=services_probe,
                 supervisor_alive=supervisor_alive, game_check=game_check,
                 finish_timeout_s=finish_timeout_s, health_timeout_s=health_timeout_s,
                 settle_s=settle_s, stable_s=stable_s, poll_s=poll_s)
    return _guarded(root, kw, lambda ctx, cur: _run(
        ctx, source, cur, channel=channel, shell_version=shell_version,
        game_check=game_check), log or (lambda _m: None))


def resume_cycle(root: Path, *, restarts_sent: bool = False,
                 game_check: Optional[Callable[[], Optional[str]]] = None,
                 health: Optional[Callable[[], Dict[str, Any]]] = None,
                 serving: Optional[Callable[[], bool]] = None,
                 services_probe: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
                 supervisor_alive: Optional[Callable[[], bool]] = None,
                 parent_alive: Optional[Callable[[], bool]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 now: Callable[[], float] = time.time,
                 uptime: Optional[Callable[[], float]] = None,
                 finish_timeout_s: float = FINISH_TIMEOUT_S,
                 health_timeout_s: float = HEALTH_TIMEOUT_S,
                 settle_s: float = SETTLE_S, stable_s: float = STABLE_S,
                 poll_s: float = POLL_S,
                 log: Optional[Callable[[str], None]] = None) -> CycleResult:
    """Only what an earlier cycle left (module docstring); `idle` when
    nothing is recorded. Needs no /api/state and never applies a release."""
    kw = _ctx_kw(clock=clock, sleep=sleep, now=now, uptime=uptime, parent_alive=parent_alive,
                 health=health,
                 serving=serving, services_probe=services_probe,
                 supervisor_alive=supervisor_alive, game_check=game_check,
                 finish_timeout_s=finish_timeout_s, health_timeout_s=health_timeout_s,
                 settle_s=settle_s, stable_s=stable_s, poll_s=poll_s)

    def body(ctx: _Ctx, cur: Optional[str]) -> CycleResult:
        got = _resume(ctx, cur, restarts_sent=restarts_sent)
        if got is not None:
            return got
        return CycleResult("idle", None, cur, "nothing to resume", extra=_notice_check(ctx))
    return _guarded(root, kw, body, log or (lambda _m: None))


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
    res_p = sub.add_parser("resume")
    res_p.add_argument("--restarts-sent", action="store_true",
                       help="the shell performed the owed restarts: health-check them")
    for p in (run, res_p):
        p.add_argument("--parent-pid", type=int, default=None,
                       help="the shell; once it is gone the cycle stops (never recovers)")
        p.add_argument("--finish-timeout", type=float, default=FINISH_TIMEOUT_S)
        p.add_argument("--health-timeout", type=float, default=HEALTH_TIMEOUT_S)
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
        common = dict(finish_timeout_s=max(1.0, args.finish_timeout),
                      health_timeout_s=max(1.0, args.health_timeout), log=_log_to_file(root))
        if args.parent_pid:
            parent = sh.ParentWatch(args.parent_pid)
            common["parent_alive"] = parent.alive
        if args.cmd == "resume":
            res = resume_cycle(root, restarts_sent=args.restarts_sent, **common)
        else:
            try:
                source = up._source(args.source)
            except up.UpdateError as exc:
                res = CycleResult("refused", detail=_clean(exc), code=exc.code)
            else:
                res = run_cycle(root, source, channel=args.channel,
                                shell_version=args.shell_version, **common)
    finally:
        if parent is not None:
            parent.close()
    print(json.dumps(res.to_dict(), sort_keys=True))
    return res.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

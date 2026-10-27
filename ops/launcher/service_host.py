"""PKG-1 service host: owns, starts and stops RC's local services for the app.

docs/PACKAGING_PLAN.md sections 3.1 - 3.3. The Electron shell spawns ONE
windowless child,

    <python> -I ops/launcher/service_host.py --root <backend> --parent-pid <pid>

and this process owns every RC service for the life of the app: the frozen
supervisor (ops/rc_supervisor.py, which owns main.py and through RC's own
watchdogs vision :8889 and DS :8860), the LCU agent, the Live Client relay and
the hotkey listener (plus the Phase 3 supervisor in the dev profile). Services
start when the APP launches and stop when it quits. Nothing here registers a
start at boot: no task, no Run key, no Startup shortcut.

Process hygiene
- Every child is created SUSPENDED with CREATE_NO_WINDOW, assigned to ONE
  Windows job object (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, no breakaway) and
  only then resumed, so a grandchild a service starts is in the job from its
  first instruction. If this host dies, the kernel closes the job handle and
  ends the whole tree. Model: the kit's job object
  (ops/fleet_kit/fleet_headless.py:1762 `_WinJob`); re-implemented, not
  imported, because the kit is dev-only and never ships in a bundle.
- Stops act on OWNED handles and the job only. No taskkill, no kill by image
  name (PACKAGING_PLAN S7).
- The host writes nothing to its own stdout / stderr while running (the shell
  may hold those pipes unread); it logs to ops/runtime/logs/service_host.log.
  Service stdout / stderr go to DEVNULL: each service keeps its own rotating
  log (tools/lcu_agent.py:87, tools/hotkey_listener.py:123,
  tools/liveclient_relay.py:56, ops/rc_supervisor.py:713), and a duplicate
  stream here would grow without bound.

Profiles (services.json `profiles`, chosen by --profile): `packaged` = a
default install, the dashboard bound to loopback (RC_DASH_BIND=127.0.0.1,
read by dashboard/server.py, PACKAGING_PLAN M5); `dev` = the operator's
linked checkout, RC_DASH_BIND removed so :8888 keeps the wildcard bind its
tailnet view needs (PACKAGING_PLAN V3), plus the Phase 3 supervisor.

Lifecycle
- Start: probe first (3.3). A healthy supervisor already holding the
  dashboard port (the pre-cutover scheduled tasks, or a dev run) = ATTACH
  mode: start nothing, only report. A live supervisor lock or a held port
  that is NOT healthy = BLOCKED: start nothing either, never double start.
  Otherwise OWNED: create any missing per-install secret (PKG-1b,
  ops/launcher/first_run.py: vision token, dashboard token, deploy key;
  never overwrites one; RC_DASH_TOKEN reaches the services only when the
  profile sets `dash_token_gate`), generate the per-install supervisor
  config (absolute interpreter, PACKAGING_PLAN S10) and start the services
  in manifest order.
- Run: reap exits and restart with bounded backoff (BackoffPolicy); watch the
  parent pid; rewrite the status file on change and every few seconds.
- Stop (a stdin line `stop`, stdin EOF, a signal, or the parent gone): write
  a `shutdown` request for the supervisor (ops/rc_supervisor.py:1309; it then
  stops main.py by owned pid), stop the agents by owned handle, wait a
  bounded grace, then TERMINATE THE JOB - anything left, grandchildren
  included, dies with it. A request nobody consumed is removed so it cannot
  shut down the next launch's supervisor.

Command channel (PKG-6b, PACKAGING_PLAN WA11). Besides `stop`, the shell
writes one JSON object per stdin line; only the parent holds that pipe, so
no other local process can command the host:
    {"cmd": "restart", "id": "<id>", "services": ["lcu_agent", "vision"]}
    {"cmd": "stop"}
The stdin thread only queues a line (bounded); tick() parses and applies it,
so every service change stays on the supervision thread. Per name:
  - a service this host spawned: running = ended by its OWNED handle (the
    supervisor gracefully, through the same shutdown request a quit writes)
    and respawned at once, killed after stop_grace_s if it hangs; not
    running (backoff, failed, halted) = started now with a fresh backoff
    window. A requested restart is never counted as a crash.
  - vision / ds (WATCHDOG_PORTS): grandchildren RC's own watchdogs own
    (dashboard/_vision_watchdog.py, core/daemon_slayer_client.py DsWatchdog).
    The host ends the process listening on the service port ONLY when that
    process is inside this host's job object (IsProcessInJob on the opened
    handle, so a recycled pid cannot be hit); the watchdog then respawns it
    on fresh code. A listener outside the job (a pre-cutover task) is left
    alone.
  - app / shell (SHELL_ACTIONS): the shell's own acts (respawn this host,
    relaunch the shell); refused here with that reason.
Attach and blocked mode refuse every restart (nothing here is owned). The
outcome of the last COMMAND_HISTORY commands is in the status file under
`commands`: [{"id", "cmd", "at", "results": {name: outcome}, "error"?}].

Status: ops/runtime/launcher_status.json, written atomically and rewritten
at least every STATUS_HEARTBEAT_S while the host lives. Schema 1 is the
contract the shell parses (rc-shell/src/service_status.js header, PKG-3):
    {"schema": 1, "updated": ISO-8601 UTC, "host_pid", "parent_pid",
     "profile", "mode": "owned"|"attach"|"blocked"|null, "state",
     "job": bool, "origin", "healthy", "reason",
     "services": [{"name", "role", "state", "pid", "port", "restarts",
                   "last_error", "owned", "in_job", "started"}]}
The shell reads schema / updated / mode / host_pid / origin and per service
name / state / pid / port / restarts / last_error, and ignores the rest
(`blocked` mode reads as no mode there; its services read `blocked`).
Every `state` is a word of the kit state vocabulary
(ops/fleet_kit/tokens.json "states"): pending, running, failed, halted,
idle, blocked, stale.

Exit codes: 0 stopped, 1 internal error, 2 bad manifest, 3 another host
holds ops/runtime/service_host.pid.

Stdlib only: it runs under `-I`, with no RC module on sys.path.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import queue
import re
import secrets
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, NamedTuple, Optional, Tuple

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent.parent
DEFAULT_SERVICES = HERE / "services.json"

SCHEMA = 1
PROFILES = ("packaged", "dev")
ROLES = ("supervisor", "agent")
RESTART_POLICIES = ("always", "on-failure", "never")
PLACEHOLDERS = ("root", "supervisor_config")

# Platform-guarded: passing a non-zero creationflags on POSIX raises, and CI
# runs the suite on ubuntu (same guard as ops/rc_supervisor.py:930).
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CREATE_SUSPENDED = 0x00000004 if os.name == "nt" else 0
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_EXTENDED_LIMIT_INFORMATION = 9

_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WAIT_TIMEOUT = 0x102
_ERROR_ACCESS_DENIED = 5
_FILETIME_UNIX_EPOCH = 116444736000000000   # 1970-01-01 in 100 ns since 1601

# The shell reads the status file as stale after 30 s and expects a rewrite
# at least every 10 s (rc-shell/src/service_status.js DEFAULT_STALE_AFTER_MS).
STATUS_HEARTBEAT_S = 5.0
MAX_ERROR_CHARS = 240
HEALTH_RETRY_S = 2.0
HEALTH_HEALTHY_S = 10.0
ATTACH_REPROBE_S = 5.0
STOP_POLL_S = 0.1
LOG_MAX_BYTES = 1 << 20

# Inside the shell reader's NAME_RE (rc-shell/src/service_status.js), so no
# service the host reports is dropped by the shell.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SHUTDOWN_REQUEST_PREFIX = "launcher-shutdown-"

# ---- command channel (PKG-6b)
COMMANDS = ("restart", "stop")
STOP_WORDS = ("stop", "quit", "exit")
MAX_COMMAND_CHARS = 4096
MAX_COMMAND_SERVICES = 16
MAX_PENDING_COMMANDS = 32
COMMAND_HISTORY = 8
COMMAND_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
# Services RC's own watchdogs respawn (grandchildren in the job), by the port
# they listen on. Mirrors core/ports.py VISION / DS_ENGINE (a test pins it).
WATCHDOG_PORTS = {"vision": 8889, "ds": 8860}
# Names the updater reports that only the shell can act on.
SHELL_ACTIONS = {"app": "refused:respawn-host", "shell": "refused:relaunch-shell"}
_PROCESS_TERMINATE = 0x0001
_ERROR_INSUFFICIENT_BUFFER = 122
_TCP_TABLE_OWNER_PID_LISTENER = 3
_TERMINATE_WAIT_MS = 5000
# PKG-6b: a stop never ends the job under a running deploy. While a
# deploy_requests/*.deploying file exists the supervisor is inside its
# transactional worker (it kills one at 120 s, ops/rc_supervisor.py:1462) and
# handles the shutdown request only after it, so the grace stretches to this
# bound - past the worker's own kill - and returns to stop_grace_s once the
# file is gone.
DEPLOY_STOP_GRACE_S = 150.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------ atomic write


def _scratch(path: Path) -> Path:
    # Per-writer scratch name ending in .tmp: two writers never share one,
    # and the supervisor's `*.json` request glob (ops/rc_supervisor.py:1281)
    # never picks up a half-written request.
    return path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")


def _replace_with_retry(src: Path, dst: Path) -> None:
    # A reader holding the target open makes os.replace raise WinError 5 on
    # Windows until it closes (ops/rc_supervisor.py:69 measured the same
    # race); a short backoff clears it.
    delays = (0.01, 0.025, 0.05, 0.1, 0.2, 0.4)
    for i in range(len(delays) + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i >= len(delays):
                raise
            time.sleep(delays[i])


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON so a reader sees the old file or the new one, never a torn
    one: scratch file, flush + fsync, then os.replace (CLAUDE.md hard rule)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _scratch(path)
    payload = json.dumps(data, indent=2).encode("ascii")
    try:
        with open(tmp, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        _replace_with_retry(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


# ------------------------------------------------------------ manifest


class ConfigError(ValueError):
    """The service manifest (or the supervisor config base) is unusable."""


@dataclass(frozen=True)
class BackoffPolicy:
    initial_s: float = 1.0
    factor: float = 2.0
    max_s: float = 60.0
    max_restarts: int = 5
    window_s: float = 300.0
    stable_s: float = 60.0

    def delay(self, consecutive: int) -> float:
        """Seconds to wait before restart number `consecutive` (1-based).
        Grows by `factor` and never exceeds `max_s`."""
        d = float(self.initial_s)
        for _ in range(max(int(consecutive), 1) - 1):
            d *= self.factor
            if d >= self.max_s:
                break
        return min(d, float(self.max_s))


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    argv: Tuple[str, ...]
    role: str = "agent"
    port: Optional[int] = None
    restart: str = "always"
    profiles: Tuple[str, ...] = PROFILES


@dataclass(frozen=True)
class HostConfig:
    services: Tuple[ServiceSpec, ...]
    backoff: BackoffPolicy = field(default_factory=BackoffPolicy)
    dashboard_port: int = 8888
    tick_s: float = 0.25
    stop_grace_s: float = 15.0
    # The merged environment overrides for this profile: top-level `env`,
    # then `profiles.<profile>.env`. A None value removes an inherited
    # variable (the dev profile pins RC_DASH_BIND unset this way).
    env: Tuple[Tuple[str, Optional[str]], ...] = ()
    # PKG-1b: `profiles.<profile>.dash_token_gate`. True exports the stored
    # per-install dashboard token as RC_DASH_TOKEN to every service; default
    # off (PACKAGING_PLAN V3: a set token 401s the header-less callers).
    dash_token_gate: bool = False
    # PKG-6b fix round 2: restart commands are deferred while a League / TFT
    # game is live (the updater's own game check). Off only for the packaged
    # smoke's probe host, whose result must not depend on the build box.
    restart_game_guard: bool = True

    def env_map(self) -> Dict[str, Optional[str]]:
        return dict(self.env)


def _num(doc: Dict[str, Any], key: str, default: float, where: str,
         *, minimum: float = 0.0, strict: bool = False) -> float:
    value = doc.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where}: {key} must be a number")
    if value < minimum or (strict and value == minimum):
        raise ConfigError(f"{where}: {key} out of range ({value})")
    return float(value)


def _port(value: Any, where: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 65536:
        raise ConfigError(f"{where}: port must be an integer 1-65535 or null")
    return value


def _parse_backoff(raw: Any) -> BackoffPolicy:
    if raw is None:
        return BackoffPolicy()
    if not isinstance(raw, dict):
        raise ConfigError("backoff must be an object")
    where = "backoff"
    initial = _num(raw, "initial_s", 1.0, where, strict=True)
    factor = _num(raw, "factor", 2.0, where, minimum=1.0)
    max_s = _num(raw, "max_s", 60.0, where, strict=True)
    if max_s < initial:
        raise ConfigError("backoff: max_s must be >= initial_s")
    max_restarts = raw.get("max_restarts", 5)
    if isinstance(max_restarts, bool) or not isinstance(max_restarts, int) or max_restarts < 0:
        raise ConfigError("backoff: max_restarts must be an integer >= 0")
    window = _num(raw, "window_s", 300.0, where, strict=True)
    stable = _num(raw, "stable_s", 60.0, where)
    return BackoffPolicy(initial, factor, max_s, max_restarts, window, stable)


def _parse_service(raw: Any, index: int) -> ServiceSpec:
    if not isinstance(raw, dict):
        raise ConfigError(f"services[{index}] must be an object")
    name = raw.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ConfigError(f"services[{index}]: name must match {_NAME_RE.pattern}")
    where = f"service {name!r}"
    argv = raw.get("argv")
    if not isinstance(argv, list) or not argv or \
            not all(isinstance(a, str) and a for a in argv):
        raise ConfigError(f"{where}: argv must be a non-empty list of strings")
    for arg in argv:
        for ph in _PLACEHOLDER_RE.findall(arg):
            if ph not in PLACEHOLDERS:
                raise ConfigError(f"{where}: unknown placeholder {{{ph}}}")
    role = raw.get("role", "agent")
    if role not in ROLES:
        raise ConfigError(f"{where}: role must be one of {ROLES}")
    restart = raw.get("restart", "always")
    if restart not in RESTART_POLICIES:
        raise ConfigError(f"{where}: restart must be one of {RESTART_POLICIES}")
    profiles = raw.get("profiles", list(PROFILES))
    if not isinstance(profiles, list) or not profiles or \
            any(p not in PROFILES for p in profiles):
        raise ConfigError(f"{where}: unknown profile in {profiles!r}")
    return ServiceSpec(name=name, argv=tuple(argv), role=role,
                       port=_port(raw.get("port"), where), restart=restart,
                       profiles=tuple(profiles))


def parse_config(doc: Any, profile: str) -> HostConfig:
    """Validate a manifest document and keep the services of `profile`.
    Keys starting with `_` are comments."""
    if profile not in PROFILES:
        raise ConfigError(f"unknown profile {profile!r}; expected one of {PROFILES}")
    if not isinstance(doc, dict):
        raise ConfigError("manifest must be a JSON object")
    if doc.get("schema") != SCHEMA:
        raise ConfigError(f"unsupported schema {doc.get('schema')!r}; expected {SCHEMA}")
    env = _parse_env(doc.get("env", {}), "env", allow_unset=False)
    raw_profiles = doc.get("profiles", {})
    if not isinstance(raw_profiles, dict):
        raise ConfigError("profiles must be an object")
    dash_token_gate = False
    for prof, block in raw_profiles.items():
        if prof.startswith("_"):
            continue
        if prof not in PROFILES:
            raise ConfigError(f"unknown profile {prof!r} in profiles")
        if not isinstance(block, dict):
            raise ConfigError(f"profiles.{prof} must be an object")
        prof_env = _parse_env(block.get("env", {}), f"profiles.{prof}.env",
                              allow_unset=True)
        gate = block.get("dash_token_gate", False)
        if not isinstance(gate, bool):
            raise ConfigError(f"profiles.{prof}.dash_token_gate must be true or false")
        if prof == profile:
            env.update(prof_env)
            dash_token_gate = gate
    raw_services = doc.get("services")
    if not isinstance(raw_services, list) or not raw_services:
        raise ConfigError("services must be a non-empty list")
    specs = [_parse_service(raw, i) for i, raw in enumerate(raw_services)]
    seen: set = set()
    for spec in specs:
        if spec.name in seen:
            raise ConfigError(f"duplicate service name {spec.name!r}")
        seen.add(spec.name)
    for prof in PROFILES:
        sups = [s.name for s in specs if s.role == "supervisor" and prof in s.profiles]
        if len(sups) > 1:
            raise ConfigError(f"more than one supervisor role in profile {prof!r}: {sups}")
    chosen = tuple(s for s in specs if profile in s.profiles)
    if not chosen:
        raise ConfigError(f"no services for profile {profile!r}")
    port = _port(doc.get("dashboard_port", 8888), "dashboard_port") or 8888
    guard = doc.get("restart_game_guard", True)
    if not isinstance(guard, bool):
        raise ConfigError("restart_game_guard must be true or false")
    return HostConfig(
        services=chosen,
        backoff=_parse_backoff(doc.get("backoff")),
        dashboard_port=port,
        tick_s=_num(doc, "tick_s", 0.25, "manifest", strict=True),
        stop_grace_s=_num(doc, "stop_grace_s", 15.0, "manifest"),
        env=tuple(sorted(env.items())),
        dash_token_gate=dash_token_gate,
        restart_game_guard=guard,
    )


def _parse_env(raw: Any, where: str, *, allow_unset: bool) -> Dict[str, Optional[str]]:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: env must map strings to strings")
    out: Dict[str, Optional[str]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not _ENV_NAME_RE.match(key):
            raise ConfigError(f"{where}: env name {key!r} is not a variable name")
        if value is None and allow_unset:
            out[key] = None
        elif isinstance(value, str):
            out[key] = value
        else:
            raise ConfigError(f"{where}: env must map strings to strings"
                              + (" or null" if allow_unset else ""))
    return out


def child_environment(overrides: Dict[str, Optional[str]],
                      base: Optional[Dict[str, str]] = None) -> Optional[Dict[str, str]]:
    """The services' environment: `base` (default os.environ) with the
    overrides applied; None (inherit as is) when there are none. A None
    override removes the variable, matched case-insensitively on Windows
    where environment names are."""
    if not overrides:
        return None
    env = dict(os.environ if base is None else base)
    for key, value in overrides.items():
        if os.name == "nt":
            for existing in [k for k in env if k.upper() == key.upper()]:
                del env[existing]
        else:
            env.pop(key, None)
        if value is not None:
            env[key] = value
    return env


def load_config(path: Path, profile: str) -> HostConfig:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read manifest {path}: {exc}") from exc
    return parse_config(doc, profile)


# ------------------------------------------------- interpreter + config


def service_python(executable: Optional[str] = None, *,
                   windows: Optional[bool] = None) -> str:
    """The interpreter for services: the windowless pythonw.exe beside a
    python.exe on Windows (today's tasks run pythonw), else the same one."""
    exe = Path(executable or sys.executable)
    win = (os.name == "nt") if windows is None else windows
    if win and exe.name.lower() == "python.exe":
        windowless = exe.with_name("pythonw.exe")
        if windowless.is_file():
            return str(windowless)
    return str(exe)


def supervisor_config_path(root: Path) -> Path:
    return Path(root) / "ops" / "runtime" / "launcher" / "rc_config.json"


def generate_supervisor_config(root: Path, python_exe: str,
                               out_path: Optional[Path] = None) -> Path:
    """Write the per-install supervisor config (PACKAGING_PLAN S10).

    Starts from the tracked ops/rc_config.json and pins the interpreter and
    the project root as ABSOLUTE values (the frozen supervisor honours an
    absolute value as a per-host override, ops/rc_supervisor.py:680), so the
    supervisor never resolves a bare `pythonw.exe` on PATH. The output lives
    under the gitignored ops/runtime/."""
    root = Path(root)
    base_path = root / "ops" / "rc_config.json"
    try:
        base = json.loads(base_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"supervisor config base {base_path}: {exc}") from exc
    if not isinstance(base, dict):
        raise ConfigError(f"supervisor config base {base_path} is not an object")
    cfg = dict(base)
    cfg["_generated_by"] = ("ops/launcher/service_host.py: per-install supervisor "
                            "config with an absolute interpreter (PACKAGING_PLAN S10); "
                            "regenerated at every app launch, never edit")
    cfg["project_root"] = str(root)
    cfg["python_exe"] = python_exe
    app_cmd = base.get("app_cmd")
    tail = list(app_cmd[1:]) if isinstance(app_cmd, list) and app_cmd else ["main.py"]
    cfg["app_cmd"] = [python_exe] + tail
    out = Path(out_path) if out_path is not None else supervisor_config_path(root)
    atomic_write_json(out, cfg)
    return out


def clear_stale_shutdown_requests(runtime_dir: Path) -> List[Path]:
    """Delete every `launcher-shutdown-*.json` this host family left behind.

    A host killed between writing its request and deleting it (a hard kill,
    a logoff) leaves one; the next supervisor would read it and exit 0, which
    the on-failure policy reads as a deliberate stop - RC would never come
    up. Called ONLY in owned mode, after the probe found no live supervisor
    and before anything spawns. Other request files (restart, rollback, an
    operator's shutdown) are never touched."""
    d = Path(runtime_dir) / "supervisor_requests"
    removed: List[Path] = []
    if not d.is_dir():
        return removed
    for path in sorted(d.glob(f"{SHUTDOWN_REQUEST_PREFIX}*.json")):
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            pass
    return removed


def write_shutdown_request(runtime_dir: Path, reason: str) -> Path:
    """Drop a `shutdown` request where the frozen supervisor polls for one
    (ops/rc_supervisor.py:716 supervisor_requests/, handled at :1309: it
    stops main.py by owned pid, releases its lock and exits 0)."""
    d = Path(runtime_dir) / "supervisor_requests"
    path = d / f"{SHUTDOWN_REQUEST_PREFIX}{int(time.time() * 1000)}-{os.getpid()}.json"
    atomic_write_json(path, {"type": "shutdown", "reason": reason,
                             "requested_by": "ops/launcher/service_host.py",
                             "requested_at": utc_now()})
    return path


# ------------------------------------------------------- command channel


class CommandError(ValueError):
    """A command line the host refuses. `code` is stable; match on it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Command:
    cmd: str
    id: str
    services: Tuple[str, ...] = ()


def parse_command(line: Any) -> Command:
    """One stdin JSON line -> Command, or CommandError. Strict: an object,
    a known `cmd`, an id inside COMMAND_ID_RE (generated when absent), and
    for `restart` 1..MAX_COMMAND_SERVICES service names in _NAME_RE
    (duplicates dropped, order kept)."""
    text = str(line).strip()
    if len(text) > MAX_COMMAND_CHARS:
        raise CommandError("size", f"command longer than {MAX_COMMAND_CHARS} chars")
    try:
        doc = json.loads(text)
    except ValueError:
        raise CommandError("json", "not a JSON command") from None
    if not isinstance(doc, dict):
        raise CommandError("shape", "a command is a JSON object")
    cmd = doc.get("cmd")
    if cmd not in COMMANDS:
        raise CommandError("cmd", f"unknown command {str(cmd)[:32]!r}")
    cid = doc.get("id")
    if cid is None:
        cid = f"host-{int(time.time() * 1000)}-{secrets.token_hex(3)}"
    if not isinstance(cid, str) or not COMMAND_ID_RE.match(cid):
        raise CommandError("id", "command id must match [A-Za-z0-9_.:-]{1,64}")
    if cmd == "stop":
        return Command("stop", cid)
    names = doc.get("services")
    if not isinstance(names, list) or not names or len(names) > MAX_COMMAND_SERVICES:
        raise CommandError("services", f"services must be a list of 1..{MAX_COMMAND_SERVICES}")
    out: List[str] = []
    for name in names:
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise CommandError("services", "a service name must match [a-z][a-z0-9_]*")
        if name not in out:
            out.append(name)
    return Command("restart", cid, tuple(out))


# ------------------------------------------------------------ first run


def _first_run_module() -> Any:
    """ops/launcher/first_run.py (PKG-1b). A package import when this module
    was imported as ops.launcher.service_host; under the shell's `-I` launch
    the launcher folder is not on sys.path, so it is loaded from its file."""
    if __package__:
        from . import first_run
        return first_run
    name = "rc_launcher_first_run"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, HERE / "first_run.py")
        if spec is None or spec.loader is None:
            raise ImportError("ops/launcher/first_run.py is not loadable")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return mod


def _updater_module() -> Any:
    """ops/launcher/updater.py (PKG-2), loaded like first_run: its game check
    is the one the restart guard uses."""
    if __package__:
        from . import updater
        return updater
    name = "rc_launcher_updater"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, HERE / "updater.py")
        if spec is None or spec.loader is None:
            raise ImportError("ops/launcher/updater.py is not loadable")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return mod


def provision_first_run(root: Path, config: HostConfig, environ: Dict[str, str],
                        log: Callable[[str], None]) -> Dict[str, str]:
    """Create the missing per-install secrets (PACKAGING_PLAN 3.2) and return
    the environment overrides for the services: RC_DASH_TOKEN only when the
    profile's dash_token_gate is on. Logs names and paths, never a value."""
    report = _first_run_module().provision(
        root, dash_token_gate=config.dash_token_gate, environ=environ)
    for line in report.lines(Path(root)):
        log(line)
    return dict(report.env)


# ------------------------------------------------------------ Win32


_K32 = None


def _kernel32():
    """A private kernel32 handle with explicit prototypes. Never the shared
    ctypes.windll object: prototypes set there would leak to every module."""
    global _K32
    if _K32 is None:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        k32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.c_void_p,) * 4
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                ctypes.c_void_p, wintypes.DWORD)
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k32.IsProcessInJob.argtypes = (wintypes.HANDLE, wintypes.HANDLE,
                                       ctypes.POINTER(wintypes.BOOL))
        k32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        _K32 = k32
    return _K32


def pid_alive(pid: int) -> bool:
    """True while process `pid` exists (not merely an open handle on it)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        k32 = _kernel32()
        h = k32.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            # Access denied = it exists but belongs to someone else.
            return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
        try:
            return k32.WaitForSingleObject(h, 0) == _WAIT_TIMEOUT
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def process_created(pid: int) -> Optional[float]:
    """Unix creation time of `pid`, or None where it cannot be read."""
    if sys.platform != "win32":
        return None
    import ctypes
    k32 = _kernel32()
    h = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        times = [ctypes.c_ulonglong() for _ in range(4)]
        if not k32.GetProcessTimes(h, *(ctypes.byref(t) for t in times)):
            return None
        return (times[0].value - _FILETIME_UNIX_EPOCH) / 1e7
    finally:
        k32.CloseHandle(h)


def lock_holder_alive(lock_path: Path) -> bool:
    """Read-only check of the frozen supervisor's PidLock file
    (ops/rc_supervisor.py:166; JSON {pid, start_time, ...}). Never takes the
    OS lock itself, so it cannot race a supervisor starting up. A pid that
    was created AFTER the lock was written is a reused pid, not the holder."""
    try:
        doc = json.loads(Path(lock_path).read_text(encoding="utf-8-sig"))
        pid = int(doc["pid"])
        start = float(doc.get("start_time") or 0.0)
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if not pid_alive(pid):
        return False
    created = process_created(pid)
    if created is not None and start and created > start + 2.0:
        return False
    return True


def _lock_pid(lock_path: Path) -> Optional[int]:
    try:
        return int(json.loads(Path(lock_path).read_text(encoding="utf-8-sig"))["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


class JobAssignError(OSError):
    """A child could not be put in the job. It was never resumed: the caller
    terminates it and reports the service failed."""


class WinJob:
    """ONE Windows job object holding every service and its descendants.

    KILL_ON_JOB_CLOSE and no BREAKAWAY_OK: nothing leaves the job, and when
    the last handle closes (this host exits or dies) the kernel ends every
    member. Children are created SUSPENDED and resumed only after they are
    in the job, so no grandchild can start outside it."""

    suspends = True

    def __init__(self, handle) -> None:
        self.handle = handle

    @classmethod
    def create(cls) -> Optional["WinJob"]:
        if sys.platform != "win32":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            class _Basic(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                            ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD),
                            ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t),
                            ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t),
                            ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class _Io(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in (
                    "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class _Ext(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io),
                            ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]

            k32 = _kernel32()
            handle = k32.CreateJobObjectW(None, None)
            if not handle:
                return None
            info = _Ext()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k32.SetInformationJobObject(handle, _JOB_EXTENDED_LIMIT_INFORMATION,
                                               ctypes.byref(info), ctypes.sizeof(info)):
                k32.CloseHandle(handle)
                return None
            return cls(handle)
        except (OSError, AttributeError, ValueError):
            return None

    def adopt(self, proc) -> bool:
        """Assign the SUSPENDED child (by its Popen handle, never a pid) to
        the job, then resume it. Returns True: it is in the job and running.

        A failed assignment raises JobAssignError WITHOUT resuming: the child
        has run no instruction yet, so the caller terminates it and nothing
        ever runs outside the job. A failed resume raises OSError so the
        caller kills the child: one left suspended would read as running
        forever."""
        import ctypes
        ph = getattr(proc, "_handle", None)
        if ph is None or not self.handle:
            raise JobAssignError("no process or job handle to assign")
        if not _kernel32().AssignProcessToJobObject(self.handle, int(ph)):
            raise JobAssignError(
                f"AssignProcessToJobObject failed (winerror {ctypes.get_last_error()})")
        nt = ctypes.WinDLL("ntdll")
        nt.NtResumeProcess.argtypes = (ctypes.c_void_p,)
        if nt.NtResumeProcess(ctypes.c_void_p(int(ph))) != 0:
            raise OSError("NtResumeProcess failed")
        return True

    def terminate(self) -> None:
        if self.handle:
            _kernel32().TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            _kernel32().CloseHandle(self.handle)
            self.handle = None


class ParentWatch:
    """Is the launching shell still alive? Holds a handle on Windows, so a
    recycled pid can never read as the parent."""

    def __init__(self, pid: int, *, kernel32: Any = None) -> None:
        self.pid = int(pid)
        self._handle = None
        self._dead = False
        self._k32 = kernel32 if kernel32 is not None else \
            (_kernel32() if sys.platform == "win32" else None)
        if self._k32 is not None:
            h = self._k32.OpenProcess(_SYNCHRONIZE, False, self.pid)
            if h:
                self._handle = h
            else:
                import ctypes
                if ctypes.get_last_error() != _ERROR_ACCESS_DENIED:
                    self._dead = True

    def alive(self) -> bool:
        if self._dead:
            return False
        if self._handle is not None:
            if self._k32.WaitForSingleObject(self._handle, 0) == _WAIT_TIMEOUT:
                return True
            self._dead = True
            return False
        if not pid_alive(self.pid):
            self._dead = True
        return not self._dead

    def close(self) -> None:
        """Release the parent handle (idempotent). main() calls it in a
        finally, so the handle never outlives the host loop."""
        handle, self._handle = self._handle, None
        if handle is not None and self._k32 is not None:
            try:
                self._k32.CloseHandle(handle)
            except OSError:
                pass


def port_listener_pids(port: int) -> List[int]:
    """Pids of every process LISTENING on TCP `port`, IPv4 and IPv6 (Win32
    GetExtendedTcpTable, TCP_TABLE_OWNER_PID_LISTENER). Elsewhere: []."""
    if sys.platform != "win32" or not isinstance(port, int) or not 0 < port < 65536:
        return []
    import ctypes
    import struct
    from ctypes import wintypes
    ip = ctypes.WinDLL("iphlpapi")
    fn = ip.GetExtendedTcpTable
    fn.restype = wintypes.DWORD
    fn.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
                   wintypes.ULONG, ctypes.c_int, wintypes.ULONG)
    found: List[int] = []
    # (address family, row bytes, dwLocalPort offset, dwOwningPid offset):
    # MIB_TCPROW_OWNER_PID and MIB_TCP6ROW_OWNER_PID.
    for family, row, port_at, pid_at in ((2, 24, 8, 20), (23, 56, 20, 52)):
        size = wintypes.DWORD(0)
        raw = None
        for _ in range(5):
            buf = ctypes.create_string_buffer(max(int(size.value), 4))
            size = wintypes.DWORD(len(buf))
            rc = fn(buf, ctypes.byref(size), False, family,
                    _TCP_TABLE_OWNER_PID_LISTENER, 0)
            if rc == 0:
                raw = buf.raw
                break
            if rc != _ERROR_INSUFFICIENT_BUFFER:
                break
        if raw is None or len(raw) < 4:
            continue
        count = struct.unpack_from("<I", raw, 0)[0]
        for i in range(count):
            off = 4 + i * row
            if off + row > len(raw):
                break
            v = struct.unpack_from("<I", raw, off + port_at)[0]
            if (((v & 0xFF) << 8) | ((v >> 8) & 0xFF)) == port:   # network order
                pid = struct.unpack_from("<I", raw, off + pid_at)[0]
                if pid and pid not in found:
                    found.append(pid)
    return found


def terminate_job_listener(job: Any, port: int, *,
                           listeners: Callable[[int], List[int]] = port_listener_pids) -> str:
    """End the process listening on `port` ONLY if it is inside `job` (this
    host's job object). The check runs on the OPENED handle, so the process
    it proves is the one terminated (a recycled pid cannot be hit). Never by
    image name, never outside the job. Outcome: terminated | not-running |
    refused:no-job | refused:not-in-job | refused:open-failed |
    refused:unsupported."""
    handle = getattr(job, "handle", None) if job is not None else None
    if not handle:
        return "refused:no-job"
    if sys.platform != "win32":
        return "refused:unsupported"
    import ctypes
    from ctypes import wintypes
    pids = listeners(port)
    if not pids:
        return "not-running"
    k32 = _kernel32()
    outcomes = []
    for pid in pids:
        h = k32.OpenProcess(_PROCESS_TERMINATE | _SYNCHRONIZE
                            | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            outcomes.append("refused:open-failed")
            continue
        try:
            inside = wintypes.BOOL(False)
            if not k32.IsProcessInJob(h, handle, ctypes.byref(inside)) or not inside.value:
                outcomes.append("refused:not-in-job")
                continue
            if not k32.TerminateProcess(h, 1):
                outcomes.append("refused:open-failed")
                continue
            k32.WaitForSingleObject(h, _TERMINATE_WAIT_MS)
            outcomes.append("terminated")
        finally:
            k32.CloseHandle(h)
    for want in ("terminated", "refused:not-in-job"):
        if want in outcomes:
            return want
    return outcomes[0]


class HostLock:
    """Single host per backend root: ops/runtime/service_host.pid (3.3).

    Same shape as the frozen supervisor's PidLock (ops/rc_supervisor.py:166):
    an OS byte-range lock on a sidecar `.oslock` the kernel releases if this
    process dies, plus a readable JSON pid file written atomically."""

    def __init__(self, path: Path, info: Optional[Dict[str, Any]] = None) -> None:
        self.path = Path(path)
        self._os_lock = self.path.with_name(self.path.name + ".oslock")
        self._info = dict(info or {})
        self._fd: Optional[int] = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self._os_lock), os.O_RDWR | os.O_CREAT, 0o644)
        except OSError:
            return False
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        try:
            atomic_write_json(self.path, dict(self._info, pid=os.getpid(),
                                              start_time=time.time(),
                                              locked_at=utc_now()))
        except OSError:
            self.release()
            return False
        return True

    def release(self) -> None:
        if self._fd is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    os.lseek(self._fd, 0, os.SEEK_SET)
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
            for p in (self.path, self._os_lock):
                try:
                    p.unlink()
                except OSError:
                    pass


# ------------------------------------------------------------ probes


class Probe(NamedTuple):
    mode: str                      # owned | attach | blocked
    reason: Optional[str]
    origin: Optional[str]
    supervisor_pid: Optional[int]


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def fetch_health_origin(port: int, host: str = "127.0.0.1",
                        timeout: float = 1.0) -> Optional[str]:
    """The origin serving a HEALTHY RC on `port` (GET /api/health answers
    health.json with `alive` true), or None. Loopback only; TLS is tried
    first with verification off (a local mkcert leaf), then plain HTTP. A
    closed port costs one short connect, never two full HTTP timeouts."""
    if not port_open(port, host):
        return None
    tls = ssl.create_default_context()
    tls.check_hostname = False
    tls.verify_mode = ssl.CERT_NONE
    no_proxy = urllib.request.ProxyHandler({})
    for scheme in ("https", "http"):
        handlers: List[Any] = [no_proxy]
        if scheme == "https":
            handlers.append(urllib.request.HTTPSHandler(context=tls))
        opener = urllib.request.build_opener(*handlers)
        try:
            with opener.open(f"{scheme}://{host}:{port}/api/health", timeout=timeout) as r:
                if r.status != 200:
                    continue
                doc = json.loads(r.read(1 << 20).decode("utf-8", "replace"))
        except (OSError, ValueError, urllib.error.URLError):
            continue
        except Exception:   # noqa: BLE001 - http.client raises a wide family
            continue
        if isinstance(doc, dict) and doc.get("alive"):
            return f"{scheme}://{host}:{port}"
    return None


def probe_existing(root: Path, port: int, *,
                   holder_alive: Callable[[Path], bool] = lock_holder_alive,
                   fetch: Callable[[int], Optional[str]] = fetch_health_origin,
                   port_open: Callable[[int], bool] = port_open) -> Probe:
    """Decide owned / attach / blocked before starting anything (3.3).

    attach  = a live supervisor holds its lock AND the port answers healthy:
              start nothing, report it (pre-cutover tasks, a dev run).
    blocked = a live supervisor lock, or a held port, but not that healthy
              pair: start nothing either (never double start; a second
              supervisor would refuse itself anyway).
    owned   = neither: this host starts the services."""
    lock = Path(root) / "ops" / "runtime" / "supervisor.pid"
    sup_alive = bool(holder_alive(lock))
    origin = fetch(port)
    if sup_alive and origin:
        pid = _lock_pid(lock)
        return Probe("attach", f"healthy supervisor pid {pid} holds :{port}", origin, pid)
    if sup_alive:
        return Probe("blocked", f"a supervisor holds its lock but :{port} is not healthy",
                     None, _lock_pid(lock))
    if origin or port_open(port):
        return Probe("blocked", f":{port} is served without a live supervisor", origin, None)
    return Probe("owned", None, None, None)


# ------------------------------------------------------------ host


def _clean_error(text: Optional[str]) -> Optional[str]:
    """One printable-ASCII line, capped like the shell's reader caps it
    (rc-shell/src/service_status.js cleanError), so the file stays small."""
    if text is None:
        return None
    flat = re.sub(r" {2,}", " ", re.sub(r"[^\x20-\x7e]", " ", str(text))).strip()
    return flat[:MAX_ERROR_CHARS]


@dataclass
class _Runtime:
    spec: ServiceSpec
    state: str = "pending"
    proc: Any = None
    pid: Optional[int] = None
    in_job: bool = False
    restarts: int = 0
    attempts: int = 0
    consecutive: int = 0
    last_error: Optional[str] = None
    started_mono: Optional[float] = None
    started_wall: Optional[str] = None
    next_start: Optional[float] = None
    exits: Deque[float] = field(default_factory=deque)
    argv: Optional[List[str]] = None
    # PKG-6b: a requested restart in flight (the exit is not a crash).
    restart_pending: bool = False
    restart_deadline: Optional[float] = None
    restart_request: Optional[Path] = None
    restart_records: List[Dict[str, Any]] = field(default_factory=list)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


class ServiceHost:
    """Owns the services of one backend root. Every side effect is injected
    (popen, job, clock, sleep, parent, probe, health) so the policy is
    testable without a real process."""

    def __init__(self, root: Path, config: HostConfig, *,
                 profile: str = "packaged",
                 popen: Callable[..., Any] = subprocess.Popen,
                 job_factory: Callable[[], Any] = WinJob.create,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 parent_alive: Optional[Callable[[], bool]] = None,
                 parent_pid: Optional[int] = None,
                 probe: Optional[Callable[[], Probe]] = None,
                 health: Optional[Callable[[], Optional[str]]] = None,
                 python_exe: Optional[str] = None,
                 status_path: Optional[Path] = None,
                 log: Optional[Callable[[str], None]] = None,
                 provision: Optional[Callable[..., Dict[str, str]]] = None,
                 port_terminator: Optional[Callable[[Any, int], str]] = None,
                 game_check: Optional[Callable[[], Optional[str]]] = None) -> None:
        self.root = Path(root)
        self.config = config
        self.profile = profile
        self.runtime_dir = self.root / "ops" / "runtime"
        self.status_path = Path(status_path) if status_path else \
            self.runtime_dir / "launcher_status.json"
        self.python_exe = python_exe or service_python()
        self.parent_pid = parent_pid
        self._popen = popen
        self._job_factory = job_factory
        self._clock = clock
        self._sleep = sleep
        self._parent_alive = parent_alive or (lambda: True)
        port = config.dashboard_port
        self._probe = probe or (lambda: probe_existing(self.root, port))
        self._health = health or (lambda: fetch_health_origin(port))
        self._log = log or (lambda msg: None)
        self._provision = provision or provision_first_run
        self._env = child_environment(config.env_map())
        self.mode: Optional[str] = None
        self.job: Any = None
        self.origin: Optional[str] = None
        self.healthy = False
        self.reason: Optional[str] = None
        self.stop_reason: Optional[str] = None
        self.stopped = False
        self._started = False
        self._next_health = 0.0
        self._next_reprobe = 0.0
        self._last_doc: Optional[Dict[str, Any]] = None
        self._last_write = float("-inf")
        self._services = [_Runtime(spec) for spec in config.services]
        # PKG-6b command channel: filled by the stdin thread, drained by tick().
        self._commands_in: "queue.Queue[str]" = queue.Queue(maxsize=MAX_PENDING_COMMANDS)
        self._history: Deque[Dict[str, Any]] = deque(maxlen=COMMAND_HISTORY)
        self._terminate_port_owner = port_terminator or terminate_job_listener
        self._game_check = game_check

    # ---- lifecycle

    def start(self) -> None:
        if self._started or self.stopped:
            return
        self._started = True
        probe = self._probe()
        self.mode = probe.mode
        self.reason = probe.reason
        now = self._clock()
        if probe.mode != "owned":
            self.origin = probe.origin
            self.healthy = probe.mode == "attach"
            # The shell's overall state is its worst service state
            # (rc-shell/src/service_status.js aggregate): attach reads idle
            # (nothing to fix), blocked reads blocked (its error view).
            for rt in self._services:
                rt.state = "idle" if probe.mode == "attach" else "blocked"
            self._next_reprobe = now + ATTACH_REPROBE_S
            self._log(f"{probe.mode} mode, starting nothing: {probe.reason}")
            self._write_status(force=True)
            return
        # Owned = the probe found no live supervisor, so a launcher shutdown
        # request still on disk is stale and would stop our supervisor at once.
        for stale in clear_stale_shutdown_requests(self.runtime_dir):
            self._log(f"removed a stale shutdown request: {stale.name}")
        self._provision_secrets()
        self.job = self._job_factory()
        if self.job is None:
            self._log("no job object: children are stopped by owned handle only")
        sup_cfg: Optional[str] = None
        if any("{supervisor_config}" in a for rt in self._services for a in rt.spec.argv):
            try:
                sup_cfg = str(generate_supervisor_config(self.root, self.python_exe))
            except ConfigError as exc:
                self._log(f"supervisor config: {exc}")
                sup_cfg = None
                for rt in self._services:
                    if any("{supervisor_config}" in a for a in rt.spec.argv):
                        rt.state = "failed"
                        rt.last_error = f"supervisor config: {exc}"
        for rt in self._services:
            if rt.state == "failed":
                continue
            rt.argv = self._resolve_argv(rt.spec, sup_cfg)
            self._spawn(rt, now)
        self._write_status(force=True)

    def tick(self) -> bool:
        """One supervision pass. False once the host has stopped."""
        if self.stopped:
            return False
        if not self._parent_alive():
            self._log("parent process is gone")
            self.stop("parent_exit")
            return False
        now = self._clock()
        self._drain_commands(now)
        if self.stopped:   # a {"cmd": "stop"} line
            return False
        if self.mode == "owned":
            for rt in self._services:
                self._restart_overdue(rt, now)
            for rt in self._services:
                self._reap(rt, now)
            for rt in self._services:
                if rt.state == "pending" and rt.next_start is not None and now >= rt.next_start:
                    self._spawn(rt, now)
            if now >= self._next_health:
                self.origin = self._health()
                self.healthy = bool(self.origin)
                self._next_health = now + (HEALTH_HEALTHY_S if self.healthy else HEALTH_RETRY_S)
        elif self.mode == "attach" and now >= self._next_reprobe:
            probe = self._probe()
            self.healthy = probe.mode == "attach"
            if probe.origin:
                self.origin = probe.origin
            self._next_reprobe = now + ATTACH_REPROBE_S
        self._write_status()
        return True

    def run(self, stop_event: threading.Event) -> None:
        if not self._parent_alive():
            self.stop("parent_exit")
            return
        try:
            self.start()
            while not stop_event.is_set():
                if not self.tick():
                    break
                stop_event.wait(self.config.tick_s)
        finally:
            self.stop(self.stop_reason or "stop_requested")

    def stop(self, reason: str) -> None:
        if self.stopped:
            return
        self.stopped = True
        self.reason = reason
        self._log(f"stopping: {reason}")
        if self.mode == "owned":
            self._stop_owned(reason)
            for rt in self._services:
                rt.state = "halted"
                rt.pid = None
                rt.next_start = None
        self._write_status(force=True)

    # ---- internals

    def _provision_secrets(self) -> None:
        """PKG-1b, owned mode only, before the first spawn. A provisioning
        fault never blocks the launch: it is logged by type (no message, so
        no value can leak) and the services start on what exists."""
        environ = self._env if self._env is not None else dict(os.environ)
        try:
            overrides = self._provision(self.root, self.config, environ, self._log)
        except Exception as exc:   # noqa: BLE001 - logged, launch continues
            self._log(f"first run: provisioning failed ({type(exc).__name__})")
            return
        if overrides:
            merged = self.config.env_map()
            merged.update(overrides)
            self._env = child_environment(merged)

    def _resolve_argv(self, spec: ServiceSpec, sup_cfg: Optional[str]) -> List[str]:
        values = {"root": str(self.root), "supervisor_config": sup_cfg or ""}
        args = [_PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], a) for a in spec.argv]
        if args[0].endswith(".py") and not Path(args[0]).is_absolute():
            args[0] = str(self.root / args[0])
        return [self.python_exe] + args

    def _spawn(self, rt: _Runtime, now: float) -> None:
        if rt.attempts:
            rt.restarts += 1
        rt.attempts += 1
        rt.next_start = None
        job = self.job
        flags = CREATE_NO_WINDOW
        if job is not None and getattr(job, "suspends", False):
            flags |= CREATE_SUSPENDED
        try:
            proc = self._popen(
                rt.argv or [], cwd=str(self.root), env=self._env,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=flags)
        except (OSError, ValueError) as exc:
            self._log(f"{rt.spec.name}: spawn failed: {exc}")
            self._on_exit(rt, now, f"spawn failed: {exc}", clean=False, runtime=0.0)
            return
        in_job = False
        if job is not None:
            try:
                in_job = bool(job.adopt(proc))
                if not in_job:
                    raise JobAssignError("the job refused the child")
            except JobAssignError as exc:
                # Never resumed: terminate the still-suspended child, so no
                # service ever runs outside the job. Not retried - a refused
                # assignment does not heal by itself.
                self._log(f"{rt.spec.name}: job assignment failed, terminating "
                          f"suspended pid {proc.pid}: {exc}")
                self._kill(proc)
                rt.proc = None
                rt.pid = None
                rt.in_job = False
                rt.state = "failed"
                rt.last_error = f"job assignment failed, service not started: {exc}"
                return
            except OSError as exc:
                self._log(f"{rt.spec.name}: job adopt failed, killing it: {exc}")
                self._kill(proc)
                self._on_exit(rt, now, f"spawn failed: job adopt: {exc}",
                              clean=False, runtime=0.0)
                return
        rt.proc = proc
        rt.pid = proc.pid
        rt.in_job = in_job
        rt.state = "running"
        rt.started_mono = now
        rt.started_wall = utc_now()
        self._log(f"{rt.spec.name}: started pid {proc.pid} (in_job={in_job})")

    def _reap(self, rt: _Runtime, now: float) -> None:
        if rt.state != "running" or rt.proc is None:
            return
        code = rt.proc.poll()
        if code is None:
            return
        runtime = now - (rt.started_mono if rt.started_mono is not None else now)
        rt.proc = None
        rt.pid = None
        self._log(f"{rt.spec.name}: exited with code {code} after {runtime:.1f}s")
        if rt.restart_pending:
            self._respawn_requested(rt, now)
            return
        self._on_exit(rt, now, f"exit code {code}", clean=(code == 0), runtime=runtime)

    # ---- PKG-6b command channel

    def submit_command(self, line: str) -> bool:
        """Queue one command line (any thread). Applied by the next tick();
        a full queue drops the line (logged)."""
        try:
            self._commands_in.put_nowait(str(line)[:MAX_COMMAND_CHARS + 1])
            return True
        except queue.Full:
            self._log("command queue full; a command line was dropped")
            return False

    def _drain_commands(self, now: float) -> None:
        changed = False
        while True:
            try:
                line = self._commands_in.get_nowait()
            except queue.Empty:
                break
            changed = True
            try:
                cmd = parse_command(line)
            except CommandError as exc:
                self._history.append({"id": None, "cmd": None, "at": utc_now(),
                                      "results": {}, "error": exc.code})
                self._log(f"command refused ({exc.code})")
                continue
            if cmd.cmd == "stop":
                self._history.append({"id": cmd.id, "cmd": "stop", "at": utc_now(),
                                      "results": {}})
                self.stop_reason = self.stop_reason or "command_stop"
                self.stop(self.stop_reason)
                return
            self._apply_restart(cmd, now)
        if changed:
            self._write_status(force=True)

    def _game_reason(self) -> Optional[str]:
        """Why a restart must wait (a live game), else None. The injected
        check, else the updater's game_live (process scan + fresh health
        flags). A failed probe defers: a restart can wait, a mid-game
        restart cannot be undone."""
        try:
            if self._game_check is not None:
                return self._game_check()
            return _updater_module().game_live(self.root)
        except Exception as exc:   # noqa: BLE001 - fail closed
            return f"game check failed ({type(exc).__name__})"

    def _apply_restart(self, cmd: Command, now: float) -> None:
        record: Dict[str, Any] = {"id": cmd.id, "cmd": cmd.cmd, "at": utc_now(),
                                  "results": {}}
        self._history.append(record)
        by_name = {rt.spec.name: rt for rt in self._services}
        game = None
        if self.mode == "owned" and not self.stopped and self.config.restart_game_guard:
            game = self._game_reason()
            if game:
                self._log(f"command {cmd.id}: restarts deferred, {game}")
        for name in cmd.services:
            if self.mode != "owned" or self.stopped:
                outcome = "refused:not-owned"
            elif game:
                outcome = "deferred:game-live"
            elif name in SHELL_ACTIONS:
                outcome = SHELL_ACTIONS[name]
            elif name in WATCHDOG_PORTS:
                outcome = self._restart_watchdog_service(name)
            elif name in by_name:
                outcome = self._request_restart(by_name[name], record, now)
            else:
                outcome = "not-configured"
            record["results"][name] = outcome
        self._log(f"command {cmd.id}: restart {record['results']}")

    def _restart_watchdog_service(self, name: str) -> str:
        if self.job is None:
            return "refused:no-job"
        try:
            outcome = str(self._terminate_port_owner(self.job, WATCHDOG_PORTS[name]))
        except Exception as exc:   # noqa: BLE001 - reported, never raised
            self._log(f"{name}: restart failed ({type(exc).__name__})")
            return "refused:error"
        return outcome[:40]

    def _request_restart(self, rt: _Runtime, record: Dict[str, Any], now: float) -> str:
        if rt.restart_pending:
            rt.restart_records.append(record)
            return "restarting"
        if rt.alive():
            rt.restart_pending = True
            rt.restart_deadline = now + self.config.stop_grace_s
            rt.restart_records = [record]
            graceful = False
            if rt.spec.role == "supervisor":
                try:
                    rt.restart_request = write_shutdown_request(
                        self.runtime_dir, f"restart:{record['id']}")
                    graceful = True
                except OSError as exc:
                    self._log(f"{rt.spec.name}: restart request failed: {exc}")
            if not graceful:
                try:
                    rt.proc.terminate()
                except OSError as exc:
                    self._log(f"{rt.spec.name}: terminate failed: {exc}")
            self._log(f"{rt.spec.name}: restart requested ({record['id']})")
            return "restarting"
        if rt.argv is None:
            return "refused:not-startable"
        # Not running (backoff, failed, halted): start now, fresh window.
        rt.proc = None
        rt.pid = None
        rt.consecutive = 0
        rt.exits.clear()
        rt.next_start = None
        self._spawn(rt, now)
        return "restarted" if rt.state == "running" else f"failed:{rt.state}"

    def _restart_overdue(self, rt: _Runtime, now: float) -> None:
        if not rt.restart_pending or rt.restart_deadline is None or now < rt.restart_deadline:
            return
        if rt.proc is not None and rt.proc.poll() is None:
            self._log(f"{rt.spec.name}: did not stop for its restart in "
                      f"{self.config.stop_grace_s:g}s; ending it")
            self._kill(rt.proc)
        rt.restart_deadline = None

    def _respawn_requested(self, rt: _Runtime, now: float) -> None:
        if rt.restart_request is not None:
            try:
                rt.restart_request.unlink()
                self._log(f"{rt.spec.name}: removed its unconsumed restart request")
            except FileNotFoundError:
                pass
            except OSError as exc:
                self._log(f"{rt.spec.name}: restart request not removed: {exc}")
        records = rt.restart_records
        rt.restart_pending = False
        rt.restart_deadline = None
        rt.restart_request = None
        rt.restart_records = []
        rt.next_start = None
        self._spawn(rt, now)
        outcome = "restarted" if rt.state == "running" else f"failed:{rt.state}"
        for rec in records:
            rec["results"][rt.spec.name] = outcome
        self._write_status(force=True)

    def _on_exit(self, rt: _Runtime, now: float, error: str, *,
                 clean: bool, runtime: float) -> None:
        policy = rt.spec.restart
        if policy == "never" or (policy == "on-failure" and clean):
            rt.state = "halted"
            rt.last_error = None if clean else error
            return
        bo = self.config.backoff
        if runtime >= bo.stable_s:
            rt.consecutive = 0
        rt.consecutive += 1
        rt.exits.append(now)
        while rt.exits and now - rt.exits[0] > bo.window_s:
            rt.exits.popleft()
        if len(rt.exits) > bo.max_restarts:
            rt.state = "failed"
            rt.last_error = (f"{error}; gave up after {len(rt.exits)} exits "
                             f"in {bo.window_s:g}s")
            self._log(f"{rt.spec.name}: {rt.last_error}")
            return
        rt.state = "pending"
        rt.last_error = error
        rt.next_start = now + bo.delay(rt.consecutive)

    def _kill(self, proc: Any) -> None:
        try:
            if proc.poll() is None:
                proc.kill()
        except OSError:
            pass

    def _stop_owned(self, reason: str) -> None:
        request: Optional[Path] = None
        sup = next((rt for rt in self._services if rt.spec.role == "supervisor"), None)
        if sup is not None and sup.alive():
            try:
                request = write_shutdown_request(self.runtime_dir, reason)
                self._log(f"shutdown request written: {request.name}")
            except OSError as exc:
                self._log(f"shutdown request failed: {exc}")
        for rt in self._services:
            if rt is not sup and rt.alive():
                try:
                    rt.proc.terminate()
                except OSError as exc:
                    self._log(f"{rt.spec.name}: terminate failed: {exc}")
        begun = self._clock()
        deadline = begun + self.config.stop_grace_s
        deploy_deadline = begun + max(self.config.stop_grace_s, DEPLOY_STOP_GRACE_S)
        while True:
            in_flight = self._deploy_in_flight()
            if not in_flight and not any(rt.alive() for rt in self._services):
                break
            if self._clock() >= (deploy_deadline if in_flight else deadline):
                break
            self._sleep(STOP_POLL_S)
            self._write_status()   # keep the heartbeat through a long grace
        if self.job is not None:
            try:
                self.job.terminate()
            except OSError as exc:
                self._log(f"job terminate failed: {exc}")
            try:
                self.job.close()
            except OSError:
                pass
            # The handle is closed: the status must not claim a live job.
            self.job = None
        for rt in self._services:
            rt.in_job = False
            if rt.proc is not None:
                self._kill(rt.proc)
        if request is not None:
            try:
                request.unlink()
                self._log("removed the unconsumed shutdown request")
            except OSError:
                pass
        for rt in self._services:   # PKG-6b: a restart caught by the stop
            if rt.restart_request is not None:
                try:
                    rt.restart_request.unlink()
                except OSError:
                    pass
            rt.restart_pending = False
            rt.restart_deadline = None
            rt.restart_request = None

    def _deploy_in_flight(self) -> bool:
        """A deploy worker may still be copying: a deploy_requests/*.deploying
        with no deploy_results/<stem>.json yet. Fix round 2: the frozen
        supervisor exits on its shutdown request WITHOUT waiting for its
        deploy thread (ops/rc_supervisor.py:1309-1314), so every service can
        be gone while the worker, a grandchild in this job, is mid-copy; the
        worker writes the result itself (--result), which ends the wait.
        A .deploying beside its result is finished (B9)."""
        try:
            results = self.runtime_dir / "deploy_results"
            return any(not (results / f"{p.stem}.json").exists()
                       for p in (self.runtime_dir / "deploy_requests").glob("*.deploying"))
        except OSError:
            return False

    def _top_state(self) -> str:
        if self.stopped:
            return "halted"
        if self.mode == "blocked":
            return "blocked"
        if self.mode == "attach":
            return "idle" if self.healthy else "stale"
        states = [rt.state for rt in self._services]
        if "failed" in states:
            return "failed"
        if "pending" in states:
            return "pending"
        if "running" in states:
            return "running"
        return "halted" if self._started else "pending"

    def status(self) -> Dict[str, Any]:
        owned = self.mode == "owned"
        return {
            "schema": SCHEMA,
            "host_pid": os.getpid(),
            "parent_pid": self.parent_pid,
            "profile": self.profile,
            "mode": self.mode,
            "state": self._top_state(),
            "job": self.job is not None,
            "origin": self.origin,
            "healthy": self.healthy,
            "reason": self.reason,
            "services": [{
                "name": rt.spec.name,
                "role": rt.spec.role,
                "state": rt.state,
                "pid": rt.pid,
                "port": rt.spec.port,
                "restarts": rt.restarts,
                "last_error": _clean_error(rt.last_error),
                "owned": owned,
                "in_job": rt.in_job,
                "started": rt.started_wall,
            } for rt in self._services],
            # PKG-6b: copies, so an in-place outcome update reads as a change.
            "commands": [dict(rec, results=dict(rec["results"])) for rec in self._history],
        }

    def _write_status(self, force: bool = False) -> None:
        doc = self.status()
        now = self._clock()
        if not force and doc == self._last_doc and now - self._last_write < STATUS_HEARTBEAT_S:
            return
        try:
            atomic_write_json(self.status_path, dict(doc, updated=utc_now()))
        except OSError as exc:
            self._log(f"status write failed (retried next tick): {exc}")
            return
        self._last_doc = doc
        self._last_write = now


# ------------------------------------------------------------ CLI


class HostLog:
    """Append-only host log, rolled to `.1` past LOG_MAX_BYTES. Never raises."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, msg: str) -> None:
        line = f"{utc_now()} pid={os.getpid()} {msg}\n"
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size > LOG_MAX_BYTES:
                    os.replace(self.path, self.path.with_name(self.path.name + ".1"))
                with open(self.path, "a", encoding="utf-8", errors="replace") as fh:
                    fh.write(line)
            except OSError:
                pass


def _watch_stdin(host: ServiceHost, event: threading.Event, stream: Any) -> None:
    """The shell's channel: a `stop` line (or EOF when the shell's end of the
    pipe closes: it quit or died) stops the host; any other non-empty line
    is queued as a command (PKG-6b) and applied by the supervision loop."""
    try:
        for line in stream:
            text = line.strip()
            if text.lower() in STOP_WORDS:
                host.stop_reason = host.stop_reason or "stdin_stop"
                event.set()
                return
            if text:
                host.submit_command(text)
    except (OSError, ValueError):
        pass
    host.stop_reason = host.stop_reason or "stdin_eof"
    event.set()


def _install_signals(host: ServiceHost, event: threading.Event) -> None:
    def handler(signum, _frame):
        host.stop_reason = host.stop_reason or f"signal_{signum}"
        event.set()
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="service_host",
        description="Own RC's local services for the life of the app (PKG-1).")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="backend root")
    ap.add_argument("--parent-pid", type=int, default=None,
                    help="the launching shell; its exit stops every service")
    ap.add_argument("--services", default=None, help="manifest (default: services.json here)")
    ap.add_argument("--profile", choices=PROFILES, default="packaged",
                    help="packaged = loopback dashboard; dev = linked checkout, "
                         "wildcard bind kept for the tailnet view")
    ap.add_argument("--python", default=None, help="interpreter for the services")
    ap.add_argument("--no-stdin", action="store_true",
                    help="do not treat stdin as the quit channel")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    log = HostLog(root / "ops" / "runtime" / "logs" / "service_host.log")
    manifest = Path(args.services) if args.services else DEFAULT_SERVICES
    try:
        config = load_config(manifest, args.profile)
    except ConfigError as exc:
        log.write(f"bad manifest: {exc}")
        print(f"service_host: {exc}", file=sys.stderr)
        return 2
    lock = HostLock(root / "ops" / "runtime" / "service_host.pid",
                    {"parent_pid": args.parent_pid, "profile": args.profile})
    if not lock.acquire():
        log.write("another service host holds ops/runtime/service_host.pid")
        print("service_host: another service host is running", file=sys.stderr)
        return 3
    parent: Optional[ParentWatch] = None
    try:
        parent = ParentWatch(args.parent_pid) if args.parent_pid else None
        host = ServiceHost(
            root, config, profile=args.profile,
            parent_alive=parent.alive if parent else None,
            parent_pid=args.parent_pid,
            python_exe=args.python or service_python(),
            log=log.write)
        stop_event = threading.Event()
        if not args.no_stdin and sys.stdin is not None:
            threading.Thread(target=_watch_stdin, args=(host, stop_event, sys.stdin),
                             name="service-host-stdin", daemon=True).start()
        _install_signals(host, stop_event)
        log.write(f"service host up: root={root} profile={args.profile} "
                  f"parent={args.parent_pid}")
        try:
            host.run(stop_event)
        except Exception as exc:   # noqa: BLE001 - logged, then a clean exit code
            log.write(f"internal error: {type(exc).__name__}: {exc}")
            return 1
        log.write(f"service host down: {host.reason}")
        return 0
    finally:
        if parent is not None:
            parent.close()
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())

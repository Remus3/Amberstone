"""PKG-1: the launcher's Python service host (docs/PACKAGING_PLAN.md 3.1-3.3).

Acceptance (slice PKG-1, docs/PACKAGING_PLAN.md section 4), one test group
each:

  A1 fake services start inside ONE job object
  A2 parent death kills all of them
  A3 a graceful stop writes a `shutdown` supervisor request BEFORE the job
     is terminated
  A4 attach mode starts nothing when a healthy supervisor holds :8888
  A5 restart-on-exit backoff is bounded (delay capped, restarts per window
     capped, then the service reads `failed`)
  A6 every child is spawned with CREATE_NO_WINDOW
  A7 no `taskkill /IM` (the host never runs taskkill at all)
  A8 the status file is written atomically, in the kit state vocabulary

The unit tests drive ServiceHost through injected fakes (popen, job, clock,
probe, health) and run on every OS. The `test_real_*` tests start a REAL host
process whose services are tiny sleeper scripts written into tmp_path - never
an RC service - and need a Windows job object, so they skip off Windows.
No test reaches the live tree: every root is tmp_path, and every probe that
could touch the live :8888 is injected.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from ops.launcher import service_host as sh

ROOT = Path(__file__).resolve().parent.parent
HOST_PY = ROOT / "ops" / "launcher" / "service_host.py"
SERVICES_JSON = ROOT / "ops" / "launcher" / "services.json"
TOKENS_JSON = ROOT / "ops" / "fleet_kit" / "tokens.json"
NO_WINDOW = 0x08000000

WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32", reason="needs a Windows job object")


# --------------------------------------------------------------- fakes


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += max(float(seconds), 0.0)


class FakeProc:
    def __init__(self, pid, argv, behaviour=None):
        self.pid = pid
        self.argv = list(argv)
        self.returncode = None
        self.terminated = False
        self.killed = False
        self._behaviour = behaviour

    def poll(self):
        if self.returncode is None and self._behaviour is not None:
            code = self._behaviour(self)
            if code is not None:
                self.returncode = code
        return self.returncode

    def wait(self, timeout=None):
        if self.poll() is None:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        return self.returncode

    def terminate(self):
        self.terminated = True
        if self.returncode is None:
            self.returncode = 1

    def kill(self):
        self.killed = True
        if self.returncode is None:
            self.returncode = 1


class FakePopen:
    """Records every spawn; `behaviour[script]` decides when a child exits."""

    def __init__(self, clock=None, events=None):
        self.calls = []
        self.procs = []
        self.spawn_times = {}
        self.behaviour = {}
        self.fail = set()
        self.fail_message = "fake spawn failure"
        self._pid = 4000
        self._clock = clock
        self._events = events if events is not None else []

    @staticmethod
    def script_of(argv):
        for arg in argv[1:]:
            if arg.endswith(".py"):
                return Path(arg).name
        return argv[-1]

    def __call__(self, argv, **kw):
        script = self.script_of(argv)
        self.calls.append((list(argv), dict(kw)))
        if script in self.fail:
            raise OSError(self.fail_message)
        self._pid += 1
        proc = FakeProc(self._pid, argv, self.behaviour.get(script))
        self.procs.append(proc)
        if self._clock is not None:
            self.spawn_times.setdefault(script, []).append(self._clock())
        self._events.append(("spawn", script, proc.pid))
        return proc

    def by_script(self, script):
        return [p for p in self.procs if self.script_of(p.argv) == script]


class FakeJob:
    suspends = False

    def __init__(self, events, snapshot=None):
        self.adopted = []
        self.terminated = 0
        self.closed = 0
        self.events = events
        self.snapshot = snapshot
        self.seen_at_terminate = None

    def adopt(self, proc):
        self.adopted.append(proc.pid)
        self.events.append(("adopt", proc.pid))
        return True

    def terminate(self):
        self.terminated += 1
        self.events.append(("terminate",))
        if self.snapshot is not None:
            self.seen_at_terminate = self.snapshot()

    def close(self):
        self.closed += 1


def _owned_probe():
    return sh.Probe("owned", None, None, None)


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "backend"
    (root / "ops").mkdir(parents=True)
    shutil.copyfile(ROOT / "ops" / "rc_config.json", root / "ops" / "rc_config.json")
    return root


def make_config(*, services=None, backoff=None, grace=5.0, port=1):
    doc = {
        "schema": 1,
        "dashboard_port": port,
        "tick_s": 0.5,
        "stop_grace_s": grace,
        "backoff": backoff or {"initial_s": 1, "factor": 2, "max_s": 8,
                               "max_restarts": 4, "window_s": 600,
                               "stable_s": 30},
        "services": services or [
            {"name": "supervisor", "role": "supervisor",
             "argv": ["sup.py", "--config", "{supervisor_config}"],
             "port": 8888, "restart": "on-failure"},
            {"name": "agent_a", "argv": ["a.py"], "restart": "always"},
            {"name": "agent_b", "argv": ["b.py"], "restart": "always"},
        ],
    }
    return sh.parse_config(doc, "packaged")


def make_host(root, cfg, *, popen, job=None, clock=None, parent_alive=None,
              probe=None, job_calls=None):
    clock = clock or FakeClock()

    def job_factory():
        if job_calls is not None:
            job_calls.append(1)
        return job

    return sh.ServiceHost(
        root, cfg, popen=popen, job_factory=job_factory, clock=clock,
        sleep=clock.sleep, parent_alive=parent_alive or (lambda: True),
        probe=probe or _owned_probe, health=lambda: None,
        python_exe="PYEXE")


def read_status(root: Path) -> dict:
    return json.loads((root / "ops" / "runtime" / "launcher_status.json")
                      .read_text(encoding="utf-8"))


def svc_status(doc: dict, name: str) -> dict:
    return next(s for s in doc["services"] if s["name"] == name)


# ------------------------------------------------- manifest + config


def test_shipped_manifest_loads_for_both_profiles():
    packaged = sh.load_config(SERVICES_JSON, "packaged")
    dev = sh.load_config(SERVICES_JSON, "dev")
    names = [s.name for s in packaged.services]
    assert names[0] == "supervisor", "the supervisor starts first (3.2)"
    assert {"lcu_agent", "liveclient_relay", "hotkey_listener"} <= set(names)
    assert "phase3_supervisor" not in names, "Phase 3 is dev-profile only"
    assert "phase3_supervisor" in [s.name for s in dev.services]
    assert packaged.dashboard_port == 8888
    sup = packaged.services[0]
    assert sup.role == "supervisor"
    assert "{supervisor_config}" in sup.argv
    assert sum(1 for s in dev.services if s.role == "supervisor") == 1


def test_shipped_manifest_points_at_tracked_entry_points():
    seen = 0
    for profile in ("packaged", "dev"):
        for spec in sh.load_config(SERVICES_JSON, profile).services:
            if spec.argv[0] == "-m":
                target = ROOT / (spec.argv[1].replace(".", "/") + ".py")
            else:
                target = ROOT / spec.argv[0]
            assert target.is_file(), f"{spec.name}: {target} missing"
            seen += 1
    assert seen >= 9, "an empty manifest must not pass"


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d["services"].append(dict(d["services"][1])), "duplicate"),
    (lambda d: d["services"][1].update(argv=[]), "argv"),
    (lambda d: d["services"][1].update(argv=["a.py", 3]), "argv"),
    (lambda d: d["services"][1].update(argv=["a.py", "{nope}"]), "placeholder"),
    (lambda d: d["services"][1].update(profiles=["kiosk"]), "profile"),
    (lambda d: d["services"][1].update(restart="sometimes"), "restart"),
    (lambda d: d["services"][1].update(role="supervisor"), "supervisor"),
    (lambda d: d["backoff"].update(max_s=0.5), "backoff"),
    (lambda d: d["backoff"].update(max_restarts=-1), "backoff"),
    (lambda d: d.update(schema=2), "schema"),
    (lambda d: d.update(env={"X": 1}), "env"),
    (lambda d: d.update(env={"X": None}), "env"),
    (lambda d: d.update(env={"BAD NAME": "1"}), "env"),
    (lambda d: d["profiles"].update(kiosk={"env": {}}), "profile"),
    (lambda d: d["profiles"]["packaged"]["env"].update(RC_DASH_BIND=5), "env"),
    (lambda d: d.update(profiles=[]), "profiles"),
])
def test_parse_config_rejects_bad_manifest(mutate, needle):
    doc = json.loads(SERVICES_JSON.read_text(encoding="utf-8"))
    mutate(doc)
    with pytest.raises(sh.ConfigError) as err:
        sh.parse_config(doc, "packaged")
    assert needle in str(err.value).lower()


# ------------------------------- profile env (PKG-5 dashboard bind)

BIND = "RC_DASH_BIND"   # dashboard/server.py BIND_ENV (PKG-5)


def test_shipped_profiles_pin_the_dashboard_bind():
    packaged = sh.load_config(SERVICES_JSON, "packaged").env_map()
    dev = sh.load_config(SERVICES_JSON, "dev").env_map()
    assert packaged[BIND] == "127.0.0.1", "a default install binds loopback only"
    assert BIND in dev and dev[BIND] is None, "Legion's profile must leave it UNSET"


def test_services_json_names_no_host_or_tailnet_address():
    text = SERVICES_JSON.read_text(encoding="utf-8")
    ips = re.findall(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])", text)
    assert ips and set(ips) == {"127.0.0.1"}, ips
    assert not re.search(r"\.ts\.net|tailnet\.|rc-host", text, re.I)


def _env_has(env: dict, key: str) -> bool:
    return any(k.upper() == key.upper() for k in env)


@pytest.mark.parametrize("profile, expected", [("packaged", "127.0.0.1"), ("dev", None)])
def test_profile_env_reaches_the_dashboard_owner(tmp_path, monkeypatch, profile, expected):
    monkeypatch.setenv(BIND, "192.0.2.7")           # an inherited value (RFC 5737)
    monkeypatch.setenv("RC_PKG1_INHERITED", "kept")
    root = make_root(tmp_path)
    cfg = sh.load_config(SERVICES_JSON, profile)
    fp = FakePopen()
    host = make_host(root, cfg, popen=fp, job=FakeJob([]))
    host.start()
    assert len(fp.calls) == len(cfg.services)
    sup_kw = next(kw for argv, kw in fp.calls if any("rc_supervisor.py" in a for a in argv))
    for env in [sup_kw["env"]] + [kw["env"] for _argv, kw in fp.calls]:
        assert env is not None
        assert env.get("RC_PKG1_INHERITED") == "kept", "the rest is inherited"
        if expected is None:
            assert not _env_has(env, BIND), "dev removes an inherited bind"
        else:
            assert env[BIND] == expected
    assert os.environ[BIND] == "192.0.2.7", "the host's own environment is untouched"


def test_child_environment_inherits_when_there_is_nothing_to_change():
    assert sh.child_environment({}) is None
    env = sh.child_environment({"A_X": "1", "A_Y": None}, base={"A_Y": "2", "B": "3"})
    assert env == {"A_X": "1", "B": "3"}


def test_parse_config_rejects_unknown_profile():
    doc = json.loads(SERVICES_JSON.read_text(encoding="utf-8"))
    with pytest.raises(sh.ConfigError):
        sh.parse_config(doc, "kiosk")


def test_generated_supervisor_config_names_an_absolute_interpreter(tmp_path):
    root = make_root(tmp_path)
    exe = tmp_path / "py" / "pythonw.exe"
    out = sh.generate_supervisor_config(root, str(exe))
    assert out == root / "ops" / "runtime" / "launcher" / "rc_config.json"
    cfg = json.loads(out.read_text(encoding="utf-8"))
    base = json.loads((root / "ops" / "rc_config.json")
                      .read_text(encoding="utf-8-sig"))
    assert cfg["python_exe"] == str(exe)
    assert cfg["app_cmd"] == [str(exe)] + base["app_cmd"][1:]
    assert Path(cfg["project_root"]) == root
    assert cfg["max_restart_attempts"] == base["max_restart_attempts"]
    assert not list(out.parent.glob("*.tmp"))


def test_service_python_prefers_the_windowless_sibling(tmp_path):
    exe = tmp_path / "python.exe"
    exe.write_bytes(b"")
    assert sh.service_python(str(exe), windows=True) == str(exe)
    (tmp_path / "pythonw.exe").write_bytes(b"")
    assert sh.service_python(str(exe), windows=True) == str(tmp_path / "pythonw.exe")
    assert sh.service_python(str(exe), windows=False) == str(exe)


# ------------------------------------------------------- A1 one job


def test_a1_every_service_is_adopted_into_one_job(tmp_path):
    root = make_root(tmp_path)
    events, job_calls = [], []
    job = FakeJob(events)
    fp = FakePopen(events=events)
    host = make_host(root, make_config(), popen=fp, job=job, job_calls=job_calls)
    host.start()
    assert len(job_calls) == 1, "exactly one job per host"
    assert len(fp.procs) == 3
    assert job.adopted == [p.pid for p in fp.procs]
    for i, ev in enumerate(events):
        if ev[0] == "spawn":
            assert events[i + 1] == ("adopt", ev[2]), "adopt right after spawn"
    doc = read_status(root)
    assert doc["mode"] == "owned"
    assert doc["job"] is True
    assert all(s["in_job"] and s["owned"] for s in doc["services"])
    assert all(s["state"] == "running" for s in doc["services"])
    sup_argv = fp.calls[0][0]
    assert sup_argv[0] == "PYEXE"
    cfg_path = sup_argv[sup_argv.index("--config") + 1]
    assert Path(cfg_path) == root / "ops" / "runtime" / "launcher" / "rc_config.json"
    assert Path(cfg_path).is_file()


def test_a1_no_job_still_runs_and_reports_it(tmp_path):
    root = make_root(tmp_path)
    fp = FakePopen()
    host = make_host(root, make_config(), popen=fp, job=None)
    host.start()
    assert len(fp.procs) == 3
    doc = read_status(root)
    assert doc["job"] is False
    assert not any(s["in_job"] for s in doc["services"])
    for _argv, kw in fp.calls:
        assert kw["creationflags"] == sh.CREATE_NO_WINDOW, "never suspended without a job"


# --------------------------------------------- A6 CREATE_NO_WINDOW


def test_a6_constant_matches_the_platform():
    assert sh.CREATE_NO_WINDOW == (NO_WINDOW if os.name == "nt" else 0)


def test_a6_every_spawn_and_respawn_is_windowless(tmp_path):
    root = make_root(tmp_path)
    clock = FakeClock()
    fp = FakePopen(clock=clock)
    fp.behaviour["a.py"] = lambda proc: 3
    host = make_host(root, make_config(), popen=fp, job=FakeJob([]), clock=clock)
    host.start()
    for _ in range(20):
        host.tick()
        clock.sleep(0.5)
    assert len(fp.by_script("a.py")) > 1, "respawns must be covered too"
    for argv, kw in fp.calls:
        assert kw["creationflags"] & sh.CREATE_NO_WINDOW == sh.CREATE_NO_WINDOW
        assert kw["stdin"] is subprocess.DEVNULL
        assert kw["stdout"] is subprocess.DEVNULL
        assert kw["stderr"] is subprocess.DEVNULL
        assert Path(kw["cwd"]) == root
        assert argv[0] == "PYEXE"


_SPAWN_ATTRS = {"Popen", "run", "call", "check_call", "check_output"}
_BANNED_CALLS = {"system", "startfile", "popen", "spawnl", "spawnv",
                 "spawnve", "spawnle", "execv", "execl", "posix_spawn"}


def test_a6_static_every_spawn_site_passes_creationflags():
    tree = ast.parse(HOST_PY.read_text(encoding="utf-8"))
    sites = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        func = node.func
        base = func.value.id if isinstance(func.value, ast.Name) else None
        if base == "os":
            assert func.attr not in _BANNED_CALLS, f"os.{func.attr} line {node.lineno}"
        is_spawn = (base == "subprocess" and func.attr in _SPAWN_ATTRS) or \
            func.attr == "_popen"
        if is_spawn:
            sites += 1
            kws = {k.arg for k in node.keywords}
            assert "creationflags" in kws, f"spawn at line {node.lineno} lacks creationflags"
    assert sites >= 1, "the spawn site must be found, or this guard is empty"


# ------------------------------------------------------ A7 no /IM


def _code_tokens(path: Path) -> list[str]:
    """Every string literal, name, attribute and import of a module, minus
    docstrings: what the code can EXECUTE, not what its prose explains."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                out.append(node.value)
        elif isinstance(node, ast.Name):
            out.append(node.id)
        elif isinstance(node, ast.Attribute):
            out.append(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            out += [a.name for a in node.names] + [getattr(node, "module", None) or ""]
    return out


def test_code_tokens_sees_literals_and_skips_prose():
    tokens = _code_tokens(HOST_PY)
    assert "supervisor_requests" in tokens and "shutdown" in tokens
    assert not any("Process hygiene" in t for t in tokens), "docstrings are prose"


def test_a7_no_taskkill_or_image_kill_anywhere_in_the_host():
    for path in (HOST_PY, HOST_PY.parent / "__init__.py"):
        for tok in _code_tokens(path):
            assert not re.search(r"taskkill", tok, re.I), (path.name, tok)
            assert not re.search(r"/IM\b", tok), (path.name, tok)
            assert "Stop-Process" not in tok, (path.name, tok)
    text = SERVICES_JSON.read_text(encoding="utf-8")
    assert not re.search(r"taskkill|/IM\b|Stop-Process", text, re.I)


def test_never_at_boot_nothing_registers_a_start():
    tokens = [t.lower() for t in _code_tokens(HOST_PY)]
    for needle in ("schtasks", "winreg", "currentversion\\run", "startup",
                   "openatlogin", "register-scheduledtask"):
        assert not any(needle in t for t in tokens), needle


# --------------------------------------------- A3 graceful stop order


def _requests_dir(root: Path) -> Path:
    return root / "ops" / "runtime" / "supervisor_requests"


def _snapshot(root):
    def snap():
        d = _requests_dir(root)
        out = {}
        for p in sorted(d.glob("*.json")) if d.is_dir() else []:
            out[p.name] = json.loads(p.read_text(encoding="utf-8"))
        return out
    return snap


def test_a3_shutdown_request_is_written_before_the_job_is_terminated(tmp_path):
    root = make_root(tmp_path)
    events = []
    job = FakeJob(events, snapshot=_snapshot(root))
    fp = FakePopen(events=events)
    host = make_host(root, make_config(), popen=fp, job=job)
    host.start()
    host.stop("test_quit")
    seen = job.seen_at_terminate
    assert job.terminated == 1 and job.closed == 1
    assert len(seen) == 1, f"one shutdown request at terminate time: {seen}"
    (req,) = seen.values()
    assert req["type"] == "shutdown"
    agents = fp.by_script("a.py") + fp.by_script("b.py")
    assert all(p.terminated for p in agents), "agents stopped by owned handle"
    assert events[-1] == ("terminate",)
    doc = read_status(root)
    assert doc["state"] == "halted"
    assert doc["reason"] == "test_quit"
    assert all(s["state"] == "halted" for s in doc["services"])
    # a request nobody consumed must not shut down the NEXT supervisor
    assert not list(_requests_dir(root).glob("*.json"))


def test_a3_supervisor_consumes_the_request_then_the_job_ends(tmp_path):
    root = make_root(tmp_path)
    events = []
    clock = FakeClock()
    job = FakeJob(events)
    fp = FakePopen(clock=clock, events=events)

    def supervisor(proc):
        reqs = list(_requests_dir(root).glob("*.json"))
        if not reqs:
            return None
        doc = json.loads(reqs[0].read_text(encoding="utf-8"))
        reqs[0].unlink()
        events.append(("consumed", doc["type"]))
        return 0

    fp.behaviour["sup.py"] = supervisor
    host = make_host(root, make_config(grace=10), popen=fp, job=job, clock=clock)
    host.start()
    t0 = clock()
    host.stop("quit")
    names = [e[0] for e in events]
    assert names.index("consumed") < names.index("terminate")
    assert ("consumed", "shutdown") in events
    assert clock() - t0 < 10, "a supervisor that exits ends the grace early"
    assert fp.by_script("sup.py")[0].killed is False


def test_a3_grace_is_bounded_when_the_supervisor_hangs(tmp_path):
    root = make_root(tmp_path)
    clock = FakeClock()
    job = FakeJob([])
    fp = FakePopen(clock=clock)
    fp.behaviour["sup.py"] = lambda proc: None   # never exits on its own
    host = make_host(root, make_config(grace=7), popen=fp, job=job, clock=clock)
    host.start()
    t0 = clock()
    host.stop("quit")
    assert 7 <= clock() - t0 <= 8
    assert job.terminated == 1


def test_a3_no_job_falls_back_to_owned_handles(tmp_path):
    root = make_root(tmp_path)
    clock = FakeClock()
    fp = FakePopen(clock=clock)
    fp.behaviour["sup.py"] = lambda proc: None
    host = make_host(root, make_config(grace=2), popen=fp, job=None, clock=clock)
    host.start()
    host.stop("quit")
    assert fp.by_script("sup.py")[0].killed is True
    assert all(p.returncode is not None for p in fp.procs)


def test_a3_stop_is_idempotent_and_never_respawns(tmp_path):
    root = make_root(tmp_path)
    clock = FakeClock()
    fp = FakePopen(clock=clock)
    job = FakeJob([])
    host = make_host(root, make_config(), popen=fp, job=job, clock=clock)
    host.start()
    host.stop("quit")
    host.stop("again")
    spawned = len(fp.procs)
    for _ in range(10):
        host.tick()
        clock.sleep(5)
    assert len(fp.procs) == spawned
    assert job.terminated == 1
    assert read_status(root)["reason"] == "quit"


# ------------------------------------------------- A2 parent death


def test_a2_parent_death_runs_the_same_stop(tmp_path):
    root = make_root(tmp_path)
    events = []
    alive = {"v": True}
    job = FakeJob(events, snapshot=_snapshot(root))
    fp = FakePopen(events=events)
    host = make_host(root, make_config(), popen=fp, job=job,
                     parent_alive=lambda: alive["v"])
    host.start()
    assert host.tick() is True
    alive["v"] = False
    assert host.tick() is False
    assert job.terminated == 1
    assert [r["type"] for r in job.seen_at_terminate.values()] == ["shutdown"]
    doc = read_status(root)
    assert doc["state"] == "halted" and doc["reason"] == "parent_exit"


def test_a2_dead_parent_at_launch_starts_nothing(tmp_path):
    root = make_root(tmp_path)
    fp = FakePopen()
    host = make_host(root, make_config(), popen=fp, job=FakeJob([]),
                     parent_alive=lambda: False)
    host.run(threading.Event())
    assert fp.calls == []
    assert read_status(root)["reason"] == "parent_exit"


# ------------------------------------------------------ A4 attach


def test_a4_attach_mode_starts_nothing(tmp_path):
    root = make_root(tmp_path)
    fp = FakePopen()
    job_calls = []
    probe = lambda: sh.Probe("attach", "healthy supervisor", "https://127.0.0.1:8888", 4242)  # noqa: E731
    host = make_host(root, make_config(), popen=fp, job=FakeJob([]),
                     probe=probe, job_calls=job_calls)
    host.start()
    for _ in range(5):
        host.tick()
    assert fp.calls == [], "attach mode spawns nothing"
    assert job_calls == [], "attach mode creates no job"
    doc = read_status(root)
    assert doc["mode"] == "attach"
    assert doc["origin"] == "https://127.0.0.1:8888"
    assert all(s["owned"] is False and s["state"] == "idle" for s in doc["services"])
    host.stop("quit")
    assert not _requests_dir(root).exists(), "never shut down a supervisor it does not own"


def test_a4_blocked_mode_starts_nothing(tmp_path):
    root = make_root(tmp_path)
    fp = FakePopen()
    probe = lambda: sh.Probe("blocked", ":1 served without a supervisor", None, None)  # noqa: E731
    host = make_host(root, make_config(), popen=fp, probe=probe)
    host.start()
    host.tick()
    assert fp.calls == []
    doc = read_status(root)
    assert doc["mode"] == "blocked" and doc["state"] == "blocked"
    # the shell's overall state is its worst service state: blocked -> error view
    assert all(s["state"] == "blocked" and s["owned"] is False for s in doc["services"])


def _lock(root: Path, pid: int, start: float) -> None:
    p = root / "ops" / "runtime" / "supervisor.pid"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"pid": pid, "start_time": start}), encoding="utf-8")


@pytest.mark.parametrize("sup, origin, port_open, mode", [
    (True, "https://127.0.0.1:8888", True, "attach"),
    (True, None, True, "blocked"),
    (True, None, False, "blocked"),
    (False, "http://127.0.0.1:8888", True, "blocked"),
    (False, None, True, "blocked"),
    (False, None, False, "owned"),
])
def test_a4_probe_decision_table(tmp_path, sup, origin, port_open, mode):
    root = make_root(tmp_path)
    if sup:
        _lock(root, 777, time.time())
    probe = sh.probe_existing(
        root, 8888, holder_alive=lambda path: sup,
        fetch=lambda port: origin, port_open=lambda port: port_open)
    assert probe.mode == mode
    if mode == "attach":
        assert probe.origin == origin and probe.supervisor_pid == 777


class _Health(BaseHTTPRequestHandler):
    body = b"{}"

    def do_GET(self):  # noqa: N802
        payload = self.body if self.path == "/api/health" else b"{}"
        self.send_response(200 if self.path == "/api/health" else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.mark.parametrize("alive, mode", [(True, "attach"), (False, "blocked")])
def test_a4_probe_against_a_real_local_health_endpoint(tmp_path, alive, mode):
    root = make_root(tmp_path)
    handler = type("H", (_Health,), {"body": json.dumps({"alive": alive}).encode()})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        _lock(root, os.getpid(), time.time())
        probe = sh.probe_existing(root, port)
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(5)
    assert probe.mode == mode
    if alive:
        assert probe.origin == f"http://127.0.0.1:{port}"
        assert probe.supervisor_pid == os.getpid()


def test_a4_nothing_listening_and_no_lock_is_owned(tmp_path):
    root = make_root(tmp_path)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert sh.probe_existing(root, port).mode == "owned"


def test_lock_holder_alive_reads_the_supervisor_lock(tmp_path):
    root = make_root(tmp_path)
    lock = root / "ops" / "runtime" / "supervisor.pid"
    assert sh.lock_holder_alive(lock) is False
    _lock(root, os.getpid(), time.time())
    assert sh.lock_holder_alive(lock) is True
    lock.write_text("not json", encoding="utf-8")
    assert sh.lock_holder_alive(lock) is False


@WINDOWS_ONLY
def test_lock_holder_alive_rejects_a_reused_pid(tmp_path):
    root = make_root(tmp_path)
    # the lock predates this process's creation: the pid was reused
    _lock(root, os.getpid(), 1.0)
    assert sh.lock_holder_alive(root / "ops" / "runtime" / "supervisor.pid") is False


# ---------------------------------------------------- A5 backoff


def test_a5_backoff_delay_is_capped_and_restarts_are_counted(tmp_path):
    root = make_root(tmp_path)
    clock = FakeClock()
    fp = FakePopen(clock=clock)
    fp.behaviour["a.py"] = lambda proc: 1   # crashes at once, every time
    backoff = {"initial_s": 1, "factor": 2, "max_s": 8, "max_restarts": 6,
               "window_s": 600, "stable_s": 30}
    host = make_host(root, make_config(backoff=backoff), popen=fp,
                     job=FakeJob([]), clock=clock)
    host.start()
    for _ in range(400):
        clock.sleep(0.5)
        host.tick()
    times = fp.spawn_times["a.py"]
    assert len(times) == 1 + 6, "max_restarts restarts, then give up"
    gaps = [round(b - a - 0.5, 3) for a, b in zip(times, times[1:])]
    assert gaps == [1, 2, 4, 8, 8, 8], gaps
    a = svc_status(read_status(root), "agent_a")
    assert a["state"] == "failed"
    assert a["restarts"] == 6
    assert "exit" in a["last_error"]
    # a long quiet period later the host still does not respawn it
    for _ in range(50):
        host.tick()
        clock.sleep(100)
    assert len(fp.by_script("a.py")) == 7
    assert svc_status(read_status(root), "agent_b")["state"] == "running"


def test_a5_restart_cap_is_per_window(tmp_path):
    root = make_root(tmp_path)
    clock = FakeClock()
    fp = FakePopen(clock=clock)
    started = {}

    def runs_twenty_seconds(proc):
        started.setdefault(proc.pid, clock())
        return 2 if clock() - started[proc.pid] >= 20 else None

    fp.behaviour["a.py"] = runs_twenty_seconds
    backoff = {"initial_s": 1, "factor": 2, "max_s": 4, "max_restarts": 2,
               "window_s": 10, "stable_s": 300}
    host = make_host(root, make_config(backoff=backoff), popen=fp,
                     job=FakeJob([]), clock=clock)
    host.start()
    for _ in range(2000):
        host.tick()
        clock.sleep(0.5)
    assert len(fp.by_script("a.py")) > 10, "exits spaced past the window never trip the cap"
    assert svc_status(read_status(root), "agent_a")["state"] in ("running", "pending")
    gaps = [b - a for a, b in zip(fp.spawn_times["a.py"], fp.spawn_times["a.py"][1:])]
    assert max(gaps) <= 20 + 0.5 + 4 + 0.5


def test_a5_a_stable_run_resets_the_delay(tmp_path):
    root = make_root(tmp_path)
    clock = FakeClock()
    fp = FakePopen(clock=clock)
    started = {}

    def runs_a_minute(proc):
        started.setdefault(proc.pid, clock())
        return 1 if clock() - started[proc.pid] >= 60 else None

    fp.behaviour["a.py"] = runs_a_minute
    # window_s below two run lengths: only the delay reset is under test here
    backoff = {"initial_s": 1, "factor": 2, "max_s": 8, "max_restarts": 4,
               "window_s": 100, "stable_s": 30}
    host = make_host(root, make_config(backoff=backoff), popen=fp,
                     job=FakeJob([]), clock=clock)
    host.start()
    for _ in range(1000):
        host.tick()
        clock.sleep(0.5)
    times = fp.spawn_times["a.py"]
    assert len(times) > 5
    gaps = {round(b - a, 3) for a, b in zip(times[1:], times[2:])}
    assert gaps == {60 + 0.5 + 1}, gaps
    assert svc_status(read_status(root), "agent_a")["state"] != "failed"


def test_a5_spawn_failure_backs_off_and_gives_up(tmp_path):
    root = make_root(tmp_path)
    clock = FakeClock()
    fp = FakePopen(clock=clock)
    fp.fail.add("b.py")
    host = make_host(root, make_config(), popen=fp, job=FakeJob([]), clock=clock)
    host.start()
    for _ in range(400):
        host.tick()
        clock.sleep(0.5)
    tries = [c for c in fp.calls if FakePopen.script_of(c[0]) == "b.py"]
    assert len(tries) == 1 + 4
    b = svc_status(read_status(root), "agent_b")
    assert b["state"] == "failed" and "spawn" in b["last_error"]


def test_a5_supervisor_clean_exit_is_not_restarted(tmp_path):
    root = make_root(tmp_path)
    clock = FakeClock()
    fp = FakePopen(clock=clock)
    fp.behaviour["sup.py"] = lambda proc: 0
    host = make_host(root, make_config(), popen=fp, job=FakeJob([]), clock=clock)
    host.start()
    for _ in range(40):
        host.tick()
        clock.sleep(0.5)
    assert len(fp.by_script("sup.py")) == 1
    assert svc_status(read_status(root), "supervisor")["state"] == "halted"


def test_a5_policy_delays_never_exceed_the_cap():
    pol = sh.BackoffPolicy(initial_s=0.5, factor=3, max_s=30, max_restarts=5,
                           window_s=60, stable_s=10)
    delays = [pol.delay(n) for n in range(1, 40)]
    assert delays[0] == 0.5
    assert max(delays) == 30
    assert delays == sorted(delays)


# ---------------------------------------------- A8 atomic status


def test_a8_status_shape_and_kit_vocabulary(tmp_path):
    root = make_root(tmp_path)
    clock = FakeClock()
    fp = FakePopen(clock=clock)
    fp.behaviour["a.py"] = lambda proc: 1
    host = make_host(root, make_config(), popen=fp, job=FakeJob([]), clock=clock)
    host.start()
    kit = set(json.loads(TOKENS_JSON.read_text(encoding="utf-8"))["states"])
    kit.discard("_README")
    seen = set()
    for _ in range(200):
        host.tick()
        clock.sleep(0.5)
        doc = read_status(root)
        seen.add(doc["state"])
        seen.update(s["state"] for s in doc["services"])
    host.stop("quit")
    doc = read_status(root)
    seen.add(doc["state"])
    seen.update(s["state"] for s in doc["services"])
    assert seen <= kit, seen - kit
    assert {"running", "failed", "halted"} <= seen
    assert doc["schema"] == 1
    for key in ("updated", "host_pid", "parent_pid", "profile", "mode", "state",
                "job", "origin", "healthy", "reason", "services"):
        assert key in doc, key
    for s in doc["services"]:
        for key in ("name", "role", "state", "pid", "port", "restarts",
                    "last_error", "owned", "in_job"):
            assert key in s, key
    assert svc_status(doc, "supervisor")["port"] == 8888
    leftovers = [p.name for p in (root / "ops" / "runtime").iterdir()
                 if p.name.endswith(".tmp")]
    assert leftovers == []


def test_a8_a_concurrent_reader_never_sees_a_torn_file(tmp_path):
    target = tmp_path / "status.json"
    stop = threading.Event()
    torn, reads = [], [0]

    def reader():
        while not stop.is_set():
            time.sleep(0.001)   # a poller, not a busy loop
            try:
                raw = target.read_text(encoding="utf-8")
            except (FileNotFoundError, PermissionError):
                continue
            reads[0] += 1
            try:
                json.loads(raw)
            except ValueError:
                torn.append(raw[:80])

    t = threading.Thread(target=reader)
    t.start()
    try:
        for i in range(300):
            sh.atomic_write_json(target, {"i": i, "pad": "x" * (i * 37 % 4000)})
    finally:
        stop.set()
        t.join(10)
    assert torn == []
    assert reads[0] > 0
    assert json.loads(target.read_text(encoding="utf-8"))["i"] == 299
    assert [p.name for p in tmp_path.iterdir()] == ["status.json"]


# ------------------------------------- shell contract (PKG-3 reader)

# The schema-1 field set the shell parses, copied from the header comment and
# parseStatus / normService of rc-shell/src/service_status.js (PKG-3). Copied,
# not executed: this test needs no node. Extra keys the host writes are
# ignored by that reader.
SHELL_STATUS_FIELDS = ("schema", "updated", "mode", "host_pid", "origin", "services")
SHELL_SERVICE_FIELDS = ("name", "state", "pid", "port", "restarts", "last_error")
SHELL_MODES = ("owned", "attach")        # parseStatus: any other mode reads as null
SHELL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")   # NAME_RE
SHELL_MAX_STATUS_BYTES = 64 * 1024       # MAX_STATUS_BYTES
SHELL_MAX_ERROR_CHARS = 240              # MAX_ERROR_CHARS
SHELL_MAX_PID = 0xFFFFFFFF               # MAX_PID
SHELL_HEARTBEAT_MAX_S = 10               # "rewritten at least every 10 s"


def _assert_shell_schema(raw: str, mode: str) -> dict:
    assert len(raw) <= SHELL_MAX_STATUS_BYTES
    doc = json.loads(raw)
    for key in SHELL_STATUS_FIELDS:
        assert key in doc, key
    assert doc["schema"] == 1
    updated = datetime.fromisoformat(doc["updated"])
    assert updated.tzinfo is not None, "an ISO stamp without a zone is ambiguous"
    assert abs((datetime.now(timezone.utc) - updated).total_seconds()) < 60
    assert doc["mode"] == mode
    if mode in SHELL_MODES:
        assert doc["mode"] in SHELL_MODES
    pid = doc["host_pid"]
    assert isinstance(pid, int) and not isinstance(pid, bool) and 1 <= pid <= SHELL_MAX_PID
    assert doc["origin"] is None or (isinstance(doc["origin"], str)
                                     and 0 < len(doc["origin"].strip()) <= 256)
    kit = set(json.loads(TOKENS_JSON.read_text(encoding="utf-8"))["states"]) - {"_README"}
    services = doc["services"]
    assert isinstance(services, list) and services
    names = [s["name"] for s in services]
    assert len(set(names)) == len(names)
    for s in services:
        for key in SHELL_SERVICE_FIELDS:
            assert key in s, (s.get("name"), key)
        assert SHELL_NAME_RE.match(s["name"]), s["name"]
        assert s["state"] in kit, s["state"]
        assert s["pid"] is None or (type(s["pid"]) is int and 1 <= s["pid"] <= SHELL_MAX_PID)
        assert s["port"] is None or (type(s["port"]) is int and 1 <= s["port"] <= 65535)
        assert type(s["restarts"]) is int and s["restarts"] >= 0
        err = s["last_error"]
        assert err is None or (isinstance(err, str) and len(err) <= SHELL_MAX_ERROR_CHARS
                               and re.fullmatch(r"[\x20-\x7e]*", err)), err
    return doc


def test_status_round_trips_the_shell_schema_in_every_mode(tmp_path):
    root = make_root(tmp_path)
    clock = FakeClock()
    fp = FakePopen(clock=clock)
    fp.fail.add("b.py")
    fp.fail_message = ("caf" + chr(0xE9) + " \t\n") * 200   # long, non-ASCII, multi-line
    host = make_host(root, make_config(), popen=fp, job=FakeJob([]), clock=clock)
    host.start()
    status = root / "ops" / "runtime" / "launcher_status.json"
    doc = _assert_shell_schema(status.read_text(encoding="utf-8"), "owned")
    assert svc_status(doc, "agent_b")["last_error"].startswith("spawn failed: caf")
    for _ in range(400):
        clock.sleep(0.5)
        host.tick()
    doc = _assert_shell_schema(status.read_text(encoding="utf-8"), "owned")
    assert svc_status(doc, "agent_b")["state"] == "failed"
    assert svc_status(doc, "agent_a")["pid"] == fp.by_script("a.py")[-1].pid
    host.stop("quit")
    _assert_shell_schema(status.read_text(encoding="utf-8"), "owned")

    attach_root = make_root(tmp_path / "attach")
    probe = lambda: sh.Probe("attach", "ok", "http://127.0.0.1:8888", 9)  # noqa: E731
    host = make_host(attach_root, make_config(), popen=FakePopen(), probe=probe)
    host.start()
    doc = _assert_shell_schema(
        (attach_root / "ops" / "runtime" / "launcher_status.json").read_text(encoding="utf-8"),
        "attach")
    assert doc["origin"] == "http://127.0.0.1:8888"


@pytest.mark.parametrize("mode", ["owned", "attach", "blocked"])
def test_status_heartbeat_rewrites_an_unchanged_file(tmp_path, mode):
    assert 0 < sh.STATUS_HEARTBEAT_S <= SHELL_HEARTBEAT_MAX_S
    root = make_root(tmp_path)
    clock = FakeClock()
    probe = lambda: sh.Probe(mode, "unit", "http://127.0.0.1:8888" if mode == "attach" else None,  # noqa: E731
                             None)
    host = make_host(root, make_config(), popen=FakePopen(clock=clock),
                     job=FakeJob([]), clock=clock, probe=probe)
    host.start()
    status = root / "ops" / "runtime" / "launcher_status.json"
    for _ in range(3):
        status.unlink()
        clock.sleep(sh.STATUS_HEARTBEAT_S / 2)
        host.tick()
        assert not status.exists(), "an unchanged document is not rewritten every tick"
        clock.sleep(sh.STATUS_HEARTBEAT_S / 2)
        host.tick()
        assert status.exists(), "the heartbeat rewrites an unchanged document"


def test_shutdown_request_is_one_json_file_the_supervisor_globs(tmp_path):
    runtime = tmp_path / "runtime"
    path = sh.write_shutdown_request(runtime, "unit")
    assert path.parent == runtime / "supervisor_requests"
    assert [p.name for p in path.parent.glob("*.json")] == [path.name]
    assert [p.name for p in path.parent.iterdir()] == [path.name]
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    assert doc["type"] == "shutdown" and doc["reason"] == "unit"


# ------------------------------------------------ lock + CLI


def test_host_lock_is_single_instance(tmp_path):
    p = tmp_path / "service_host.pid"
    a = sh.HostLock(p)
    b = sh.HostLock(p)
    assert a.acquire() is True
    try:
        assert b.acquire() is False
        assert json.loads(p.read_text(encoding="utf-8"))["pid"] == os.getpid()
    finally:
        a.release()
    assert b.acquire() is True
    b.release()


def test_main_rejects_a_bad_manifest_with_exit_2(tmp_path):
    root = make_root(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": 1, "services": []}), encoding="utf-8")
    assert sh.main(["--root", str(root), "--services", str(bad), "--no-stdin"]) == 2
    assert not (root / "ops" / "runtime" / "launcher_status.json").exists()


def test_main_refuses_a_second_host_with_exit_3(tmp_path):
    root = make_root(tmp_path)
    lock = sh.HostLock(root / "ops" / "runtime" / "service_host.pid")
    assert lock.acquire()
    try:
        assert sh.main(["--root", str(root), "--services", str(SERVICES_JSON),
                        "--no-stdin"]) == 3
    finally:
        lock.release()
    assert not (root / "ops" / "runtime" / "launcher_status.json").exists()


# ----------------------------------------- real processes (Windows)


FAKE_AGENT = r'''
import os, subprocess, sys, time
from pathlib import Path
name = sys.argv[1]
out = Path.cwd() / "pids"
out.mkdir(exist_ok=True)
pids = [os.getpid()]
if "--grandchild" in sys.argv:
    gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"],
                          creationflags=0x08000000)
    pids.append(gc.pid)
tmp = out / (name + ".tmp")
tmp.write_text("\n".join(str(p) for p in pids))
tmp.replace(out / (name + ".pid"))
time.sleep(300)
'''

FAKE_SUPERVISOR = r'''
import json, os, sys, time
from pathlib import Path
root = Path.cwd()
cfg = sys.argv[sys.argv.index("--config") + 1]
json.loads(Path(cfg).read_text(encoding="utf-8"))
out = root / "pids"
out.mkdir(exist_ok=True)
tmp = out / "supervisor.tmp"
tmp.write_text(str(os.getpid()))
tmp.replace(out / "supervisor.pid")
req = root / "ops" / "runtime" / "supervisor_requests"
while True:
    for p in sorted(req.glob("*.json")) if req.is_dir() else []:
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
        p.unlink()
        if doc.get("type") == "shutdown":
            (root / "got_shutdown").write_text("1")
            sys.exit(0)
    time.sleep(0.05)
'''


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _real_backend(tmp_path: Path) -> tuple[Path, Path]:
    root = make_root(tmp_path)
    (root / "fake_agent.py").write_text(FAKE_AGENT, encoding="utf-8")
    (root / "fake_supervisor.py").write_text(FAKE_SUPERVISOR, encoding="utf-8")
    manifest = {
        "schema": 1, "dashboard_port": _free_port(), "tick_s": 0.1,
        "stop_grace_s": 10,
        "backoff": {"initial_s": 1, "factor": 2, "max_s": 4, "max_restarts": 3,
                    "window_s": 60, "stable_s": 30},
        "services": [
            {"name": "supervisor", "role": "supervisor",
             "argv": ["fake_supervisor.py", "--config", "{supervisor_config}"],
             "restart": "on-failure"},
            {"name": "agent_a", "argv": ["fake_agent.py", "agent_a", "--grandchild"]},
            {"name": "agent_b", "argv": ["fake_agent.py", "agent_b"]},
        ],
    }
    svc = tmp_path / "services.json"
    svc.write_text(json.dumps(manifest), encoding="utf-8")
    return root, svc


class _Handles:
    """Process handles held from the moment a fake service reports its pid,
    so liveness and cleanup act on THAT process object - never on a pid the
    OS may have handed to an unrelated process since."""

    def __init__(self, pids):
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._k32 = k32
        # SYNCHRONIZE | PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION
        self.handles = {pid: k32.OpenProcess(0x00100000 | 0x0001 | 0x1000, False, pid)
                        for pid in pids}

    def alive(self) -> list[int]:
        return [pid for pid, h in self.handles.items()
                if h and self._k32.WaitForSingleObject(h, 0) == 0x102]

    def close(self) -> None:
        for pid in self.alive():
            self._k32.TerminateProcess(self.handles[pid], 1)
        for h in self.handles.values():
            if h:
                self._k32.CloseHandle(h)
        self.handles = {}


def _wait_for(pred, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.1)
    return pred()


def _child_pids(root: Path) -> list[int]:
    out = []
    for p in sorted((root / "pids").glob("*.pid")):
        out += [int(x) for x in p.read_text().split()]
    return out


def _start_real_host(root, svc, parent_pid, *, stdin_control):
    argv = [sys.executable, "-I", str(HOST_PY), "--root", str(root),
            "--services", str(svc), "--parent-pid", str(parent_pid)]
    if not stdin_control:
        argv.append("--no-stdin")
    return subprocess.Popen(
        argv, stdin=subprocess.PIPE if stdin_control else subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=NO_WINDOW)


def _all_up(root: Path) -> bool:
    names = {p.name for p in (root / "pids").glob("*.pid")} if (root / "pids").is_dir() else set()
    if names != {"agent_a.pid", "agent_b.pid", "supervisor.pid"}:
        return False
    try:
        doc = read_status(root)
    except (OSError, ValueError):
        return False
    return all(s["state"] == "running" for s in doc["services"])


class _RealRun:
    def __init__(self, tmp_path, *, stdin_control):
        self.root, svc = _real_backend(tmp_path)
        self.parent = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(300)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        self.host = _start_real_host(self.root, svc, self.parent.pid,
                                     stdin_control=stdin_control)
        self.procs = None

    def up(self) -> _Handles:
        assert _wait_for(lambda: _all_up(self.root), 60), "fake services never came up"
        pids = _child_pids(self.root)
        assert len(pids) == 4, pids   # 3 services + agent_a's grandchild
        self.procs = _Handles(pids)
        assert sorted(self.procs.alive()) == sorted(pids)
        doc = read_status(self.root)
        assert doc["job"] is True and all(s["in_job"] for s in doc["services"])
        return self.procs

    def cleanup(self) -> None:
        for proc in (self.host, self.parent):
            if proc.poll() is None:
                proc.kill()
                proc.wait(10)
            if proc.stdin is not None:
                proc.stdin.close()
        if self.procs is not None:
            self.procs.close()


@WINDOWS_ONLY
def test_real_parent_death_kills_every_service_and_grandchild(tmp_path):
    run = _RealRun(tmp_path, stdin_control=False)
    try:
        procs = run.up()
        run.parent.kill()
        run.parent.wait(10)
        assert run.host.wait(60) == 0
        assert _wait_for(lambda: not procs.alive(), 15), procs.alive()
        doc = read_status(run.root)
        assert doc["state"] == "halted" and doc["reason"] == "parent_exit"
        assert (run.root / "got_shutdown").is_file(), "same graceful stop as a quit"
    finally:
        run.cleanup()


@WINDOWS_ONLY
def test_real_hard_killed_host_takes_the_whole_job_with_it(tmp_path):
    run = _RealRun(tmp_path, stdin_control=False)
    try:
        procs = run.up()
        run.host.kill()           # no stop code runs: only the job can do this
        run.host.wait(10)
        assert _wait_for(lambda: not procs.alive(), 15), procs.alive()
        assert not (run.root / "got_shutdown").exists()
    finally:
        run.cleanup()


@WINDOWS_ONLY
def test_real_stdin_stop_is_graceful(tmp_path):
    run = _RealRun(tmp_path, stdin_control=True)
    try:
        procs = run.up()
        run.host.stdin.write(b"stop\n")
        run.host.stdin.flush()
        assert run.host.wait(60) == 0
        assert (run.root / "got_shutdown").is_file()
        assert _wait_for(lambda: not procs.alive(), 15), procs.alive()
        doc = read_status(run.root)
        assert doc["state"] == "halted" and doc["reason"] == "stdin_stop"
        assert not list(_requests_dir(run.root).glob("*.json"))
        assert not (run.root / "ops" / "runtime" / "service_host.pid").exists()
    finally:
        run.cleanup()

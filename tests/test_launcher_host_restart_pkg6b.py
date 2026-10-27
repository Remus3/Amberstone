# arch: PKG-6b service host command channel + per-service restart | section=tests | frozen=no
"""PKG-6b (docs/PACKAGING_PLAN.md section 4, residual WA11): the service
host gains a command channel and restarts the services an update names.

Before PKG-6b the host's stdin accepted only `stop`, so nothing could restart
the out-of-process services the supervisor's restart never reaches
(ops/launcher/updater.py RESTART CLASSIFIER, level `relaunch`). Now one JSON
line per command:

    {"cmd": "restart", "id": "<id>", "services": ["lcu_agent", "vision"]}

  H1 parse: a strict schema (object, cmd, id, 1..16 known-shaped names, a
     line-length cap); everything else is refused with a stable code
  H2 a running agent is ended by its OWNED handle and respawned at once, the
     exit not counted against its restart-on-exit backoff
  H3 a pending / failed / halted service is (re)started now, its backoff
     window reset (new code may well fix what made it give up)
  H4 the supervisor restart is graceful (the same shutdown request a quit
     writes), respawned even though its clean exit would halt it, killed
     after the grace when it hangs, and its unconsumed request removed first
  H5 vision / ds belong to RC's own watchdogs (grandchildren in the job):
     the host ends the process that holds the service port ONLY when it is
     inside this host's job, and RC's watchdog respawns it
  H6 app / shell are the shell's to act on (respawn the host / relaunch);
     attach and blocked mode refuse every restart; unknown names are
     reported, never guessed at
  H7 commands are queued by the stdin thread and applied only inside tick();
     outcomes land in launcher_status.json (`commands`, bounded)
  H8 every name the updater can report is handled; the watchdog ports
     mirror core/ports.py

Unit tests reuse the fakes of tests/test_launcher_service_host.py. The
WINDOWS_ONLY tests start tiny listener processes on free loopback ports in
tmp_path - never an RC service, never an RC port.
"""
from __future__ import annotations

import io
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from core import ports
from ops.launcher import service_host as sh
from ops.launcher import updater as up
from tests.test_launcher_service_host import (
    WINDOWS_ONLY,
    FakeClock,
    FakeJob,
    FakePopen,
    make_config,
    make_host,
    make_root,
    read_status,
    svc_status,
)

ROOT = Path(__file__).resolve().parent.parent
SERVICES_JSON = ROOT / "ops" / "launcher" / "services.json"
NO_WINDOW = 0x08000000


def _line(services, cid="c1", cmd="restart"):
    return json.dumps({"cmd": cmd, "id": cid, "services": list(services)})


def _host(tmp_path, *, behaviour=None, terminator=None, probe=None, job=True):
    root = make_root(tmp_path)
    clock = FakeClock()
    fp = FakePopen(clock=clock)
    for script, fn in (behaviour or {}).items():
        fp.behaviour[script] = fn
    calls = []

    def term(job_obj, port):
        calls.append((job_obj, port))
        return terminator(job_obj, port) if terminator else "terminated"

    host = make_host(root, make_config(), popen=fp, job=FakeJob([]) if job else None,
                     clock=clock, probe=probe)
    host._terminate_port_owner = term
    host.start()
    return host, fp, clock, root, calls


def _command(doc, cid):
    return next(c for c in doc["commands"] if c["id"] == cid)


# ---------------------------------------------------------- H1 parse


def test_h1_a_valid_restart_line_parses():
    cmd = sh.parse_command(_line(["lcu_agent", "vision", "lcu_agent"], cid="u-1.2:3"))
    assert cmd.cmd == "restart"
    assert cmd.id == "u-1.2:3"
    assert cmd.services == ("lcu_agent", "vision")   # de-duplicated, order kept


def test_h1_a_stop_object_parses():
    assert sh.parse_command('{"cmd": "stop"}').cmd == "stop"


@pytest.mark.parametrize("raw, code", [
    ("not json", "json"),
    ("[1, 2]", "shape"),
    ('{"cmd": "reboot", "id": "x", "services": ["a"]}', "cmd"),
    ('{"cmd": "restart", "id": "bad id!", "services": ["lcu_agent"]}', "id"),
    ('{"cmd": "restart", "id": "x", "services": []}', "services"),
    ('{"cmd": "restart", "id": "x", "services": "lcu_agent"}', "services"),
    ('{"cmd": "restart", "id": "x", "services": ["Bad-Name"]}', "services"),
    ('{"cmd": "restart", "id": "x", "services": [1]}', "services"),
])
def test_h1_malformed_commands_are_refused_with_a_stable_code(raw, code):
    with pytest.raises(sh.CommandError) as info:
        sh.parse_command(raw)
    assert info.value.code == code


def test_h1_too_many_services_and_an_oversized_line_are_refused():
    many = [f"svc_{i}" for i in range(sh.MAX_COMMAND_SERVICES + 1)]
    with pytest.raises(sh.CommandError) as info:
        sh.parse_command(_line(many))
    assert info.value.code == "services"
    with pytest.raises(sh.CommandError) as info:
        sh.parse_command('{"cmd": "restart", "id": "' + "x" * sh.MAX_COMMAND_CHARS + '"}')
    assert info.value.code == "size"


def test_h1_a_missing_id_is_generated():
    cmd = sh.parse_command('{"cmd": "restart", "services": ["lcu_agent"]}')
    assert sh.COMMAND_ID_RE.match(cmd.id)


# ----------------------------------------------- H2 running agent restart


def test_h2_running_agent_is_terminated_by_handle_and_respawned_now(tmp_path):
    host, fp, clock, root, _ = _host(tmp_path)
    old = fp.by_script("a.py")[0]
    host.submit_command(_line(["agent_a"]))
    host.tick()
    assert old.terminated, "ended by its owned handle"
    host.tick()
    procs = fp.by_script("a.py")
    assert len(procs) == 2 and procs[1].pid != old.pid
    doc = read_status(root)
    a = svc_status(doc, "agent_a")
    assert a["state"] == "running" and a["pid"] == procs[1].pid
    assert a["restarts"] == 1
    assert _command(doc, "c1")["results"] == {"agent_a": "restarted"}
    rt = next(r for r in host._services if r.spec.name == "agent_a")
    assert rt.consecutive == 0 and len(rt.exits) == 0, "not counted as a crash"
    # The other services were left alone.
    assert len(fp.by_script("b.py")) == 1 and len(fp.by_script("sup.py")) == 1


def test_h2_a_hung_agent_is_killed_after_the_grace(tmp_path):
    host, fp, clock, root, _ = _host(tmp_path)
    old = fp.by_script("a.py")[0]
    old.terminate = lambda: setattr(old, "terminated", True)   # ignores it
    host.submit_command(_line(["agent_a"]))
    host.tick()
    assert old.terminated and not old.killed
    clock.sleep(host.config.stop_grace_s + 0.1)
    host.tick()
    assert old.killed
    host.tick()
    assert len(fp.by_script("a.py")) == 2
    assert _command(read_status(root), "c1")["results"]["agent_a"] == "restarted"


# ------------------------------------------ H3 not-running services


def test_h3_a_failed_service_is_started_with_a_fresh_window(tmp_path):
    host, fp, clock, root, _ = _host(tmp_path, behaviour={"a.py": lambda p: 1})
    for _ in range(200):
        host.tick()
        clock.sleep(0.5)
    assert svc_status(read_status(root), "agent_a")["state"] == "failed"
    before = len(fp.by_script("a.py"))
    fp.behaviour["a.py"] = None   # the update fixed it
    host.submit_command(_line(["agent_a"], cid="fix"))
    host.tick()
    assert len(fp.by_script("a.py")) == before + 1
    a = svc_status(read_status(root), "agent_a")
    assert a["state"] == "running"
    rt = next(r for r in host._services if r.spec.name == "agent_a")
    assert len(rt.exits) == 0 and rt.consecutive == 0
    assert _command(read_status(root), "fix")["results"] == {"agent_a": "restarted"}


def test_h3_a_service_waiting_out_its_backoff_starts_now(tmp_path):
    host, fp, clock, root, _ = _host(tmp_path)
    fp.by_script("a.py")[0].returncode = 1
    host.tick()
    assert svc_status(read_status(root), "agent_a")["state"] == "pending"
    host.submit_command(_line(["agent_a"]))
    host.tick()
    assert len(fp.by_script("a.py")) == 2
    assert svc_status(read_status(root), "agent_a")["state"] == "running"


# ------------------------------------------------ H4 supervisor restart


def _requests(root: Path):
    d = root / "ops" / "runtime" / "supervisor_requests"
    return sorted(d.glob("*.json")) if d.is_dir() else []


def test_h4_supervisor_restart_is_graceful_and_respawns_after_a_clean_exit(tmp_path):
    host, fp, clock, root, _ = _host(tmp_path)
    sup = fp.by_script("sup.py")[0]
    host.submit_command(_line(["supervisor"], cid="s"))
    host.tick()
    reqs = _requests(root)
    assert len(reqs) == 1
    doc = json.loads(reqs[0].read_text(encoding="utf-8"))
    assert doc["type"] == "shutdown" and doc["reason"].startswith("restart")
    assert not sup.terminated and not sup.killed, "graceful: the request, not a kill"
    assert _command(read_status(root), "s")["results"] == {"supervisor": "restarting"}
    reqs[0].unlink()          # the supervisor consumed it ...
    sup.returncode = 0        # ... and exited cleanly
    host.tick()
    sups = fp.by_script("sup.py")
    assert len(sups) == 2, "a clean exit must not halt a requested restart"
    assert svc_status(read_status(root), "supervisor")["state"] == "running"
    assert _command(read_status(root), "s")["results"] == {"supervisor": "restarted"}


def test_h4_a_hung_supervisor_is_killed_and_its_request_removed_first(tmp_path):
    host, fp, clock, root, _ = _host(tmp_path)
    sup = fp.by_script("sup.py")[0]
    host.submit_command(_line(["supervisor"]))
    host.tick()
    assert len(_requests(root)) == 1
    clock.sleep(host.config.stop_grace_s + 0.1)
    host.tick()
    assert sup.killed
    host.tick()
    assert len(fp.by_script("sup.py")) == 2
    assert _requests(root) == [], "an unconsumed request would stop the new supervisor"


# ------------------------------------------- H5 watchdog-owned services


def test_h5_vision_and_ds_go_to_the_job_scoped_port_terminator(tmp_path):
    host, fp, clock, root, calls = _host(tmp_path)
    host.submit_command(_line(["vision", "ds"], cid="w"))
    host.tick()
    assert [port for _job, port in calls] == [sh.WATCHDOG_PORTS["vision"],
                                              sh.WATCHDOG_PORTS["ds"]]
    assert all(job is host.job for job, _port in calls)
    assert _command(read_status(root), "w")["results"] == {
        "vision": "terminated", "ds": "terminated"}


def test_h5_no_job_refuses_without_touching_any_process(tmp_path):
    host, fp, clock, root, calls = _host(tmp_path, job=False)
    host.submit_command(_line(["vision"], cid="w"))
    host.tick()
    assert calls == []
    assert _command(read_status(root), "w")["results"] == {"vision": "refused:no-job"}


def test_h5_a_terminator_fault_is_reported_not_raised(tmp_path):
    def boom(_job, _port):
        raise OSError("access denied")
    host, fp, clock, root, _ = _host(tmp_path, terminator=boom)
    host.submit_command(_line(["ds"], cid="w"))
    assert host.tick() is True
    assert _command(read_status(root), "w")["results"] == {"ds": "refused:error"}


# ------------------------------------------- H6 shell-owned and refusals


def test_h6_app_shell_and_unknown_names(tmp_path):
    host, fp, clock, root, calls = _host(tmp_path)
    host.submit_command(_line(["app", "shell", "phase3_supervisor"], cid="x"))
    host.tick()
    assert _command(read_status(root), "x")["results"] == {
        "app": "refused:respawn-host", "shell": "refused:relaunch-shell",
        "phase3_supervisor": "not-configured"}
    assert calls == [] and len(fp.calls) == 3, "nothing spawned or ended"


@pytest.mark.parametrize("mode", ["attach", "blocked"])
def test_h6_attach_and_blocked_refuse_every_restart(tmp_path, mode):
    probe = (lambda: sh.Probe(mode, "healthy supervisor", "https://127.0.0.1:1",
                              4242)) if mode == "attach" else \
        (lambda: sh.Probe(mode, ":1 held", None, None))
    host, fp, clock, root, calls = _host(tmp_path, probe=probe)
    host.submit_command(_line(["agent_a", "vision"], cid="r"))
    host.tick()
    assert fp.calls == [] and calls == []
    assert _command(read_status(root), "r")["results"] == {
        "agent_a": "refused:not-owned", "vision": "refused:not-owned"}


def test_h6_a_bad_line_is_recorded_and_changes_nothing(tmp_path):
    host, fp, clock, root, _ = _host(tmp_path)
    host.submit_command('{"cmd": "restart", "id": "bad", "services": []}')
    host.tick()
    doc = read_status(root)
    rec = doc["commands"][-1]
    assert rec["error"] == "services" and rec["results"] == {}
    assert len(fp.calls) == 3


# ------------------------------------------------ H7 queue + status


def test_h7_commands_apply_only_inside_tick(tmp_path):
    host, fp, clock, root, _ = _host(tmp_path)
    t = threading.Thread(target=host.submit_command, args=(_line(["agent_a"]),))
    t.start()
    t.join(5)
    assert not fp.by_script("a.py")[0].terminated, "queued, not applied off-thread"
    host.tick()
    assert fp.by_script("a.py")[0].terminated


def test_h7_the_queue_is_bounded(tmp_path):
    host, fp, clock, root, _ = _host(tmp_path)
    for i in range(sh.MAX_PENDING_COMMANDS + 5):
        host.submit_command(_line(["agent_a"], cid=f"c{i}"))
    assert host._commands_in.qsize() == sh.MAX_PENDING_COMMANDS


def test_h7_status_keeps_the_last_commands_only(tmp_path):
    host, fp, clock, root, _ = _host(tmp_path)
    for i in range(sh.COMMAND_HISTORY + 3):
        host.submit_command(_line(["app"], cid=f"c{i}"))
        host.tick()
    doc = read_status(root)
    assert [c["id"] for c in doc["commands"]] == [
        f"c{i}" for i in range(3, sh.COMMAND_HISTORY + 3)]
    for c in doc["commands"]:
        assert set(c) >= {"id", "cmd", "at", "results"}


def test_h7_stdin_channel_queues_json_and_stops_on_stop(tmp_path):
    host, fp, clock, root, _ = _host(tmp_path)
    event = threading.Event()
    stream = io.StringIO(_line(["agent_a"]) + "\n" + "hello\n" + "stop\n")
    sh._watch_stdin(host, event, stream)
    assert event.is_set() and host.stop_reason == "stdin_stop"
    assert host._commands_in.qsize() == 2   # the JSON line and the unknown line


def test_h7_a_json_line_alone_never_stops_the_host():
    class _H:
        stop_reason = None

        def __init__(self):
            self.got = []

        def submit_command(self, line):
            self.got.append(line)

    h = _H()
    event = threading.Event()
    gate = threading.Event()

    class _Stream:
        def __iter__(self):
            yield _line(["agent_a"]) + "\n"
            gate.wait(5)

    t = threading.Thread(target=sh._watch_stdin, args=(h, event, _Stream()), daemon=True)
    t.start()
    deadline = time.monotonic() + 5
    while not h.got and time.monotonic() < deadline:
        time.sleep(0.01)
    assert h.got and not event.is_set()
    gate.set()
    t.join(5)


def test_h7_stop_during_a_pending_restart_never_respawns(tmp_path):
    host, fp, clock, root, _ = _host(tmp_path)
    old = fp.by_script("a.py")[0]
    old.terminate = lambda: setattr(old, "terminated", True)
    host.submit_command(_line(["agent_a"]))
    host.tick()
    host.stop("quit")
    assert host.tick() is False
    assert len(fp.by_script("a.py")) == 1


# ------------------------------------------------- H8 coverage + mirrors


def test_h8_every_updater_service_name_is_handled():
    names = {s["name"] for s in json.loads(SERVICES_JSON.read_text(encoding="utf-8"))["services"]}
    handled = names | set(sh.WATCHDOG_PORTS) | set(sh.SHELL_ACTIONS)
    assert set(up.ALL_SERVICE_NAMES) <= handled, set(up.ALL_SERVICE_NAMES) - handled


def test_h8_watchdog_ports_mirror_core_ports():
    assert sh.WATCHDOG_PORTS == {"vision": ports.VISION, "ds": ports.DS_ENGINE}


# ----------------------------------------------- H5 real Win32 path


LISTENER = r'''
import socket, sys, time
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(("127.0.0.1", int(sys.argv[1])))
s.listen(1)
open(sys.argv[2], "w").write("up")
time.sleep(120)
'''


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_listener(tmp_path: Path, port: int, *, suspended: bool):
    script = tmp_path / "listener.py"
    script.write_text(LISTENER, encoding="utf-8")
    flag = tmp_path / f"up-{port}"
    flags = NO_WINDOW | (sh.CREATE_SUSPENDED if suspended else 0)
    proc = subprocess.Popen([sys.executable, "-I", str(script), str(port), str(flag)],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=flags)
    return proc, flag


def _wait(pred, timeout=30.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


@WINDOWS_ONLY
def test_h5_real_port_owner_lookup_and_job_scoped_terminate(tmp_path):
    job = sh.WinJob.create()
    assert job is not None
    port = _free_port()
    proc, flag = _start_listener(tmp_path, port, suspended=True)
    try:
        assert job.adopt(proc)
        assert _wait(flag.is_file), "listener never came up"
        assert _wait(lambda: sh.port_listener_pids(port) == [proc.pid])
        assert sh.terminate_job_listener(job, port) == "terminated"
        proc.wait(15)
        assert proc.returncode is not None
        assert sh.terminate_job_listener(job, port) == "not-running"
    finally:
        if proc.poll() is None:
            proc.kill()
        job.terminate()
        job.close()


@WINDOWS_ONLY
def test_h5_real_listener_outside_the_job_is_left_alone(tmp_path):
    job = sh.WinJob.create()
    assert job is not None
    port = _free_port()
    proc, flag = _start_listener(tmp_path, port, suspended=False)
    try:
        assert _wait(flag.is_file), "listener never came up"
        assert _wait(lambda: sh.port_listener_pids(port) == [proc.pid])
        assert sh.terminate_job_listener(job, port) == "refused:not-in-job"
        time.sleep(0.3)
        assert proc.poll() is None, "a process outside the job must never be ended"
    finally:
        proc.kill()
        proc.wait(10)
        job.close()


@WINDOWS_ONLY
def test_h5_real_terminate_without_a_job_handle_refuses():
    assert sh.terminate_job_listener(None, _free_port()) == "refused:no-job"

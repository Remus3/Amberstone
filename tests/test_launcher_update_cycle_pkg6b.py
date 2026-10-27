# arch: PKG-6b backend update cycle (check / stage / apply / finish / verify / recover) | section=tests | frozen=no
"""PKG-6b (docs/PACKAGING_PLAN.md section 4, residual WA11): the update cycle
the shell runs, ops/launcher/update_cycle.py.

One `run` drives the PKG-2 updater (ops/launcher/updater.py) end to end:

  C1 check: no newer release = up-to-date, nothing staged, nothing written
  C2 stage -> apply -> finish -> verify through the REAL deploy worker
     (ops/rc_transactional_deploy.py do_deploy, driven the way the frozen
     supervisor drives it); the verify step waits for a NEW main.py run
     after a supervised restart, then reports what still needs a restart
  C3 a live game defers the apply (exit 3); the staging is kept and reused
     by the next cycle (no second archive read)
  C4 a request the supervisor has not finished is left pending (exit 0) and
     the next cycle resumes it
  C5 a failed deploy (the worker already rolled back) reports failed and
     never runs recover
  C6 the app does not come back after the update: recover() is called (the
     supervisor's own rollback, no healthy app needed) and the cycle says so
  C7 the shell quits mid-verify: interrupted, no recover; the next cycle
     re-verifies and returns the restart actions it still owes
  C8 restart actions: what the host restarts, whether the shell respawns
     the host (app) or relaunches itself (shell)
  C9 one cycle at a time (a lock; a dead holder's lock is taken over)
  C10 refusals keep their stable code (linked checkout, integrity)
  C11 the CLI prints ONE JSON line; exit 0 / 1 / 3; the script runs under
      `-I` exactly as the shell spawns it, with no RC module on sys.path

Every root is tmp_path; no network (the updater suite's socket tripwire is
reused); the supervisor is simulated inside the injected sleep.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ops.launcher import update_cycle as uc
from ops.launcher import updater as up
from tests.test_launcher_updater import (  # noqa: F401 - _no_network is an autouse fixture
    NEW_FILES,
    _no_network,
    build_release,
    make_root,
    run_worker,
)

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "ops" / "launcher"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def no_game():
    return None


class FakeClock:
    def __init__(self):
        self.t = 5000.0

    def __call__(self):
        return self.t


def _health(root: Path, *, alive=True, run_id="r1") -> None:
    """A READY main.py heartbeat (fix round F1: the post-import
    last_state_provider_ok and a live pid are part of readiness)."""
    p = root / "ops" / "runtime" / "health.json"
    p.write_text(json.dumps({"alive": alive, "run_id": run_id, "pid": os.getpid(),
                             "last_state_provider_ok": True}), encoding="ascii")


class Supervisor:
    """The injected sleep: between two polls of the cycle, do what the frozen
    supervisor does (run the deploy worker on a queued request, handle the
    worker's restart request) and what the restarted main.py does (a fresh
    health.json with a NEW run id - or none, when it never comes back)."""

    def __init__(self, root: Path, clock: FakeClock, *, worker=True, comes_back=True):
        self.root = root
        self.clock = clock
        self.worker = worker
        self.comes_back = comes_back
        self.ran = 0
        self.restarts = 0

    def __call__(self, seconds):
        self.clock.t += max(float(seconds), 0.01)
        rt = self.root / "ops" / "runtime"
        # The worker's restart request is handled one poll LATER than the
        # deploy, so a verify that accepted the old run's heartbeat would
        # pass before main.py ever restarted.
        for req in sorted((rt / "supervisor_requests").glob("*.restart.json")):
            req.unlink()
            self.restarts += 1
            if self.comes_back:
                _health(self.root, run_id=f"r{1 + self.restarts}")
            else:
                (rt / "health.json").unlink(missing_ok=True)
        if self.worker:
            for req in sorted((rt / "deploy_requests").glob("*.json")):
                result = run_worker(self.root, req)
                assert result["ok"], result
                self.ran += 1


class CountingSource(up.LocalSource):
    def __init__(self, directory):
        super().__init__(directory)
        self.reads = []

    def read(self, release, name, max_bytes):
        self.reads.append(name)
        return super().read(release, name, max_bytes)


def _setup(tmp_path, files=None, version="1.1.0", **kw):
    root = make_root(tmp_path)
    _health(root)
    rel = build_release(tmp_path / "rel", version, NEW_FILES if files is None else files, **kw)
    return root, CountingSource(rel)


def _cycle(root, source, clock, sleep, **kw):
    kw.setdefault("game_check", no_game)
    kw.setdefault("shell_version", "9.9.9")
    kw.setdefault("serving", lambda: True)            # never the live :8888
    kw.setdefault("supervisor_alive", lambda: True)   # never the live lock
    return uc.run_cycle(root, source, clock=clock, sleep=sleep, **kw)


def _sup_requests(root):
    d = root / "ops" / "runtime" / "supervisor_requests"
    return sorted(p.name for p in d.glob("*.json")) if d.is_dir() else []


# ------------------------------------------------------------- C1 check


def test_c1_no_newer_release_is_up_to_date(tmp_path):
    root = make_root(tmp_path)
    empty = tmp_path / "rel"
    empty.mkdir()
    clock = FakeClock()
    res = _cycle(root, up.LocalSource(empty), clock, Supervisor(root, clock))
    assert res.status == "up-to-date" and res.exit_code == 0
    assert res.current == "1.0.0"
    assert not (root / "ops" / "runtime" / "staging").exists()
    assert not (root / "ops" / "runtime" / "deploy_requests").exists()


# ------------------------------------------- C2 end to end, real worker


def test_c2_end_to_end_through_the_real_worker(tmp_path):
    root, src = _setup(tmp_path)
    clock = FakeClock()
    sup = Supervisor(root, clock)
    res = _cycle(root, src, clock, sup)
    assert res.status == "applied", res.to_dict()
    assert res.exit_code == 0 and res.version == "1.1.0"
    assert sup.ran == 1 and sup.restarts == 1
    for rel, data in NEW_FILES.items():
        assert (root / rel).read_bytes() == data
    assert up.installed_version(root) == "1.1.0"
    # core/a.py with hot_reload not watching = a supervised restart of main.py,
    # which the supervisor already did: nothing is left for the host.
    assert res.restart["app"] == "restart"
    assert res.restart["host_services"] == []
    assert res.restart["respawn_host"] is False
    assert res.restart["relaunch_shell"] is False
    doc = uc.read_cycle(root)
    assert doc["verify"] is None and doc["last"]["status"] == "applied"
    assert up.read_state(root).get("pending") is None


def test_c2_verify_waits_for_a_new_run_after_a_supervised_restart(tmp_path):
    root, src = _setup(tmp_path)
    clock = FakeClock()
    sup = Supervisor(root, clock)
    seen = []

    def health():
        doc = uc.readiness(root)
        seen.append(doc["run_id"])
        return doc

    res = _cycle(root, src, clock, sup, health=health)
    assert res.status == "applied"
    assert seen[0] == "r1", "the old run was still alive when verify began"
    assert seen[-1] == "r2", "verified on the NEW run, not the old one"


def test_c2_out_of_process_code_names_the_services_to_restart(tmp_path):
    files = {"core/a.py": b"A = 1\n", "web/js/main.js": b"// v1\n", "data/x.json": b"{}\n",
             "vision_server/extra.py": b"X = 1\n", "tools/lcu_agent.py": b"L = 1\n"}
    root, src = _setup(tmp_path, files=files)
    clock = FakeClock()
    res = _cycle(root, src, clock, Supervisor(root, clock))
    assert res.status == "applied", res.to_dict()
    assert res.restart["level"] == "relaunch"
    assert res.restart["host_services"] == ["lcu_agent", "vision"]
    assert res.restart["respawn_host"] is False


# ------------------------------------------------- C3 live game deferral


def test_c3_a_live_game_defers_and_the_staging_is_reused(tmp_path):
    root, src = _setup(tmp_path)
    clock = FakeClock()
    sup = Supervisor(root, clock)
    res = _cycle(root, src, clock, sup, game_check=lambda: "process league of legends.exe")
    assert res.status == "deferred" and res.exit_code == 3
    assert res.code == "game_live"
    assert (root / "ops" / "runtime" / "staging" / "1.1.0").is_dir()
    assert not list((root / "ops" / "runtime").glob("deploy_requests/*.json"))
    assert "backend-1.1.0.zip" in src.reads
    src.reads.clear()
    res = _cycle(root, src, clock, sup)
    assert res.status == "applied", res.to_dict()
    assert "backend-1.1.0.zip" not in src.reads, "a verified staging is reused"


def test_c3_a_dirty_staging_is_restaged(tmp_path):
    root, src = _setup(tmp_path)
    clock = FakeClock()
    sup = Supervisor(root, clock)
    _cycle(root, src, clock, sup, game_check=lambda: "health has_game")
    (root / "ops" / "runtime" / "staging" / "1.1.0" / "payload" / "core" / "b.py").write_bytes(
        b"import os\n")
    src.reads.clear()
    res = _cycle(root, src, clock, sup)
    assert res.status == "applied", res.to_dict()
    assert "backend-1.1.0.zip" in src.reads
    assert (root / "core" / "b.py").read_bytes() == NEW_FILES["core/b.py"]


# --------------------------------------------------- C4 pending + resume


def test_c4_an_unfinished_request_is_pending_then_resumed(tmp_path):
    root, src = _setup(tmp_path)
    clock = FakeClock()
    res = _cycle(root, src, clock, Supervisor(root, clock, worker=False),
                 finish_timeout_s=30)
    assert res.status == "pending" and res.exit_code == 0
    assert up.read_state(root)["pending"]["version"] == "1.1.0"
    sup = Supervisor(root, clock)
    res = _cycle(root, src, clock, sup)
    assert res.status == "applied", res.to_dict()
    assert sup.ran == 1
    assert up.installed_version(root) == "1.1.0"


# ------------------------------------------------------ C5 failed deploy


def test_c5_a_failed_deploy_is_reported_and_never_recovered(tmp_path, monkeypatch):
    root, src = _setup(tmp_path)
    clock = FakeClock()
    called = []
    monkeypatch.setattr(uc.up, "recover", lambda *a, **k: called.append(1))

    def failing_supervisor(seconds):
        clock.t += seconds
        d = root / "ops" / "runtime" / "deploy_requests"
        for req in sorted(d.glob("*.json")):
            out = root / "ops" / "runtime" / "deploy_results"
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{req.stem}.json").write_text(json.dumps(
                {"ok": False, "phase": "health_check", "rollback": True}), encoding="ascii")
            req.unlink()

    res = _cycle(root, src, clock, failing_supervisor)
    assert res.status == "failed" and res.exit_code == 1
    assert called == []
    assert up.installed_version(root) == "1.0.0"


# ---------------------------------------------- C6 recover when app is down


def test_c6_the_app_not_coming_back_runs_recover(tmp_path):
    root, src = _setup(tmp_path)
    clock = FakeClock()
    res = _cycle(root, src, clock, Supervisor(root, clock, comes_back=False),
                 health_timeout_s=60)
    assert res.status == "recovered" and res.exit_code == 1, res.to_dict()
    names = _sup_requests(root)
    assert any(n.endswith("-reset_circuit_breaker.json") for n in names), names
    assert any(n.endswith("-rollback.json") for n in names), names
    assert up.installed_version(root) == "1.0.0", "the record stepped back"
    assert uc.read_cycle(root)["verify"] is None


def test_c6_a_refused_recover_is_reported_with_its_code(tmp_path, monkeypatch):
    root, src = _setup(tmp_path)
    clock = FakeClock()

    def refuse(*_a, **_k):
        raise up.StateError("a later backup exists")

    monkeypatch.setattr(uc.up, "recover", refuse)
    res = _cycle(root, src, clock, Supervisor(root, clock, comes_back=False),
                 health_timeout_s=60)
    assert res.status == "failed" and res.code == "state"
    assert "recover" in res.detail


# --------------------------------------------- C7 interrupted + re-verify


def test_c7_quit_mid_verify_is_interrupted_then_reverified(tmp_path, monkeypatch):
    files = {"core/a.py": b"A = 2\n", "web/js/main.js": b"// v1\n", "data/x.json": b"{}\n",
             "vision_server/extra.py": b"X = 1\n"}
    root, src = _setup(tmp_path, files=files)
    clock = FakeClock()
    sup = Supervisor(root, clock, comes_back=False)
    called = []
    real_recover = uc.up.recover
    monkeypatch.setattr(uc.up, "recover", lambda *a, **k: called.append(1))
    res = _cycle(root, src, clock, sup, parent_alive=lambda: sup.ran == 0)
    assert res.status == "interrupted" and res.exit_code == 0, res.to_dict()
    assert called == []
    assert uc.read_cycle(root)["verify"]["version"] == "1.1.0"
    # Next launch: the app is up again; the cycle re-verifies and still owes
    # the vision restart.
    monkeypatch.setattr(uc.up, "recover", real_recover)
    sup.comes_back = True   # the relaunched app is up again
    _health(root, run_id="r9")
    res = _cycle(root, src, clock, sup)
    assert res.status == "applied", res.to_dict()
    assert res.restart["host_services"] == ["vision"]
    assert uc.read_cycle(root)["verify"] is None


def test_c7_a_halted_host_reads_as_interrupted(tmp_path):
    root, src = _setup(tmp_path)
    clock = FakeClock()
    sup = Supervisor(root, clock, comes_back=False)

    def sleep(seconds):
        sup(seconds)
        (root / "ops" / "runtime" / "launcher_status.json").write_text(
            json.dumps({"schema": 1, "state": "halted", "mode": "owned",
                        # fix round 2 (B1): halted counts only for a live host
                        # writing a fresh status - this one is stopping now.
                        "host_pid": os.getpid(), "updated": up.utc_now()}),
            encoding="ascii")

    res = _cycle(root, src, clock, sleep, health_timeout_s=60)
    assert res.status == "interrupted", res.to_dict()


# ------------------------------------------------- C8 restart actions


@pytest.mark.parametrize("services, host, respawn, relaunch", [
    ([], [], False, False),
    (["vision", "ds", "lcu_agent"], ["ds", "lcu_agent", "vision"], False, False),
    (["app", "vision"], [], True, False),
    (["shell"], [], False, True),
    (["supervisor", "phase3_supervisor"], ["phase3_supervisor", "supervisor"], False, False),
])
def test_c8_restart_actions(services, host, respawn, relaunch):
    plan = {"level": "relaunch" if services else "none", "app": "none",
            "services": services, "stale_check": False}
    act = uc.restart_actions(plan)
    assert act["host_services"] == host
    assert act["respawn_host"] is respawn
    assert act["relaunch_shell"] is relaunch


def test_c8_no_plan_means_nothing_to_restart():
    act = uc.restart_actions(None)
    assert act["host_services"] == [] and not act["respawn_host"] and not act["relaunch_shell"]


def test_c8_unknown_service_names_never_reach_the_host():
    act = uc.restart_actions({"level": "relaunch", "app": "none",
                              "services": ["vision", "Bad Name", "x" * 80]})
    assert act["host_services"] == ["vision"]


# ------------------------------------------------------------ C9 lock


def test_c9_a_live_holder_makes_the_cycle_busy(tmp_path):
    root, src = _setup(tmp_path)
    lock = uc.lock_path(root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": os.getpid(), "at": 0}), encoding="ascii")
    clock = FakeClock()
    res = _cycle(root, src, clock, Supervisor(root, clock))
    assert res.status == "busy" and res.exit_code == 0
    assert lock.is_file(), "never removes a lock it does not own"
    assert src.reads == []


def test_c9_a_dead_holders_lock_is_taken_over_and_released(tmp_path, monkeypatch):
    root, src = _setup(tmp_path)
    lock = uc.lock_path(root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": 999999, "at": 0}), encoding="ascii")
    monkeypatch.setattr(uc, "_pid_alive", lambda pid: pid == os.getpid())
    clock = FakeClock()
    res = _cycle(root, src, clock, Supervisor(root, clock))
    assert res.status == "applied", res.to_dict()
    assert not lock.exists()


# ----------------------------------------------------------- C10 refusals


def test_c10_a_linked_checkout_is_refused(tmp_path):
    root, src = _setup(tmp_path)
    (root / ".git").mkdir()
    clock = FakeClock()
    res = _cycle(root, src, clock, Supervisor(root, clock))
    assert res.status == "refused" and res.code == "state" and res.exit_code == 1
    assert not uc.lock_path(root).exists()


def test_c10_an_integrity_failure_refuses_and_stages_nothing(tmp_path):
    root, src = _setup(tmp_path, archive_sha="0" * 64)
    clock = FakeClock()
    res = _cycle(root, src, clock, Supervisor(root, clock))
    assert res.status == "refused" and res.code == "integrity"
    assert not (root / "ops" / "runtime" / "staging" / "1.1.0").exists()


def test_c10_an_unexpected_fault_is_an_error_not_a_traceback(tmp_path, monkeypatch):
    root, src = _setup(tmp_path)

    def boom(*_a, **_k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(uc.up, "check", boom)
    clock = FakeClock()
    res = _cycle(root, src, clock, Supervisor(root, clock))
    assert res.status == "error" and res.exit_code == 1
    assert res.code == "RuntimeError"
    assert not uc.lock_path(root).exists()


# --------------------------------------------------------------- C11 CLI


def test_c11_cli_prints_one_json_line_and_maps_exit_codes(tmp_path, capsys, monkeypatch):
    root, _src = _setup(tmp_path)
    monkeypatch.setattr(uc.up, "game_live", lambda *_a, **_k: "process league of legends.exe")
    code = uc.main(["--root", str(root), "run", "--source", f"local:{tmp_path / 'rel'}",
                    "--shell-version", "9.9.9"])
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    doc = json.loads(out[0])
    assert code == 3 and doc["status"] == "deferred" and doc["ok"] is False
    code = uc.main(["--root", str(root), "status"])
    doc = json.loads(capsys.readouterr().out.strip())
    assert code == 0 and doc["installed"] == "1.0.0"
    assert doc["cycle"]["last"]["status"] == "deferred"


def test_c11_bad_source_spec_is_refused(tmp_path, capsys):
    root = make_root(tmp_path)
    code = uc.main(["--root", str(root), "run", "--source", "ftp://x"])
    doc = json.loads(capsys.readouterr().out.strip())
    assert code == 1 and doc["status"] == "refused" and doc["code"] == "update"


def test_c11_the_script_runs_isolated_as_the_shell_spawns_it(tmp_path):
    bundle = tmp_path / "bundle" / "ops" / "launcher"
    bundle.mkdir(parents=True)
    for name in ("__init__.py", "service_host.py", "first_run.py", "updater.py",
                 "update_cycle.py"):
        shutil.copyfile(LAUNCHER / name, bundle / name)
    root = make_root(tmp_path)
    empty = tmp_path / "rel"
    empty.mkdir()
    proc = subprocess.run(
        [sys.executable, "-I", str(bundle / "update_cycle.py"), "--root", str(root),
         "run", "--source", f"local:{empty}", "--parent-pid", str(os.getpid())],
        capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
    assert proc.returncode == 0, proc.stderr[-400:]
    lines = proc.stdout.strip().splitlines()
    assert len(lines) == 1
    doc = json.loads(lines[0])
    assert doc["status"] == "up-to-date" and doc["current"] == "1.0.0"


def test_c11_static_no_rc_import_and_windowless_children_only():
    src = (LAUNCHER / "update_cycle.py").read_text(encoding="utf-8")
    for bad in ("from core", "import core", "from app", "from dashboard"):
        assert bad not in src, bad
    assert "DETACHED_PROCESS" not in src
    assert src.isascii() and "\r" not in src

# arch: PKG-6b fix round - update path hardening (review findings F1-F7) | section=tests | frozen=no
"""PKG-6b fix round: the adversarial review of 6e09c8bc1 (findings F1-F7).

  F1 verify needs a POST-IMPORT readiness signal held for a stable window:
     main.py writes alive=True from DevRuntime (main.py:98) before
     `import coach_integration` (main.py:171); `last_state_provider_ok` is
     written only once main.py wired its state provider (main.py:208), i.e.
     after every import and the app constructor. A crash-looping or
     import-broken new run never verifies; `resume` finishes / recovers with
     no /api/state at all.
  F2 a deploy cut by a quit (.deploying left behind, no result: the
     supervisor removes it only in its own finally) is detected after
     DEPLOYING_STALE_S of observation, the half-copied files are salvaged
     into a recovery point from the worker's own backup (a torn backup file
     is moved out first so the supervisor's rollback never copies it), and
     recover() runs; the host's stop waits (bounded) while a deploy is in
     flight.
  F3 owed restarts are health-checked: `resume --restarts-sent` waits for
     every named service to come back on a new process and stay up, and
     recovers when one does not.
  F4 a version that ended recovered / failed / lost is never re-applied;
     a newer release still is.
  F6 recover() is re-entrant: a marker written FIRST makes a kill between
     its supervisor requests and its record update re-detectable, and the
     next call (or cycle) completes it without duplicating requests.
     Offline (no live supervisor) it restores the backup itself.
  F7 hot_reload: the old run's fresh heartbeat no longer passes; the
     stable window restarts on every run change.

Every root is tmp_path; no network (the updater suite's socket tripwire);
the supervisor and main.py are simulated in the injected sleep / probes.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from ops.launcher import service_host as sh
from ops.launcher import update_cycle as uc
from ops.launcher import updater as up
from tests.test_launcher_service_host import FakeClock as HostClock
from tests.test_launcher_service_host import FakeJob, FakePopen, make_config, make_host
from tests.test_launcher_service_host import make_root as make_host_root
from tests.test_launcher_updater import (  # noqa: F401 - _no_network is an autouse fixture
    BASE_FILES,
    NEW_FILES,
    _no_network,
    build_release,
    make_root,
    run_worker,
)


def no_game():
    return None


class Clock:
    def __init__(self, t=5000.0):
        self.t = t

    def __call__(self):
        return self.t


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _setup(tmp_path, files=None, version="1.1.0"):
    root = make_root(tmp_path)
    rel = build_release(tmp_path / f"rel-{version}", version, NEW_FILES if files is None else files)
    return root, up.LocalSource(rel)


def _staged_apply(tmp_path):
    root, src = _setup(tmp_path)
    up.stage(root, src, src.release("1.1.0"), shell_version="9.9.9")
    res = up.apply(root, "1.1.0", game_check=no_game, hot_reload_active=False)
    return root, src, res


def _sup_requests(root):
    d = root / "ops" / "runtime" / "supervisor_requests"
    return sorted(p.name for p in d.glob("*.json")) if d.is_dir() else []


# A scripted main.py: each call returns the next readiness sample.
def sample(run_id="r2", *, alive=True, ready=True, age_s=1.0, pid_alive=True):
    return {"alive": alive, "ready": ready, "run_id": run_id, "age_s": age_s,
            "pid_alive": pid_alive}


class Script:
    """health() for the cycle: `fn(t)` gives the sample at cycle clock t."""

    def __init__(self, clock, fn):
        self.clock = clock
        self.fn = fn
        self.seen = []

    def __call__(self):
        s = self.fn(self.clock.t)
        self.seen.append(s.get("run_id"))
        return s


class Sim:
    """The injected sleep: the frozen supervisor runs the worker on a queued
    request; nothing else changes (main.py is scripted separately)."""

    def __init__(self, root, clock, *, worker=True):
        self.root, self.clock, self.worker = root, clock, worker
        self.ran = 0

    def __call__(self, seconds):
        self.clock.t += max(float(seconds), 0.01)
        rt = self.root / "ops" / "runtime"
        for req in sorted((rt / "supervisor_requests").glob("*.restart.json")):
            req.unlink()
        if self.worker:
            for req in sorted((rt / "deploy_requests").glob("*.json")):
                assert run_worker(self.root, req)["ok"]
                self.ran += 1


def _cycle(root, src, clock, sleep, health, **kw):
    kw.setdefault("game_check", no_game)
    kw.setdefault("shell_version", "9.9.9")
    kw.setdefault("serving", lambda: True)
    kw.setdefault("supervisor_alive", lambda: True)
    return uc.run_cycle(root, src, clock=clock, sleep=sleep, health=health, **kw)


# ------------------------------------------------------- F1 readiness


def test_f1_alive_before_imports_is_not_ready(tmp_path):
    """The new run heartbeats alive=True but never reaches its state
    provider (an import broke): not ready, so the cycle recovers."""
    root, src = _setup(tmp_path)
    clock = Clock()
    h = Script(clock, lambda t: sample("r2", ready=False))
    res = _cycle(root, src, clock, Sim(root, clock), h, health_timeout_s=90)
    assert res.status == "recovered", res.to_dict()


def test_f1_a_crash_looping_new_run_never_verifies(tmp_path):
    """Every poll shows a NEW alive, ready run id (the supervisor restarting
    a crashing main.py): no run is stable for the window."""
    root, src = _setup(tmp_path)
    clock = Clock()
    h = Script(clock, lambda t: sample(f"r{int(t)}"))
    res = _cycle(root, src, clock, Sim(root, clock), h, health_timeout_s=90)
    assert res.status == "recovered", res.to_dict()


def test_f1_a_stale_or_dead_heartbeat_is_not_stable(tmp_path):
    root, src = _setup(tmp_path)
    clock = Clock()
    h = Script(clock, lambda t: sample("r2", age_s=uc.HEARTBEAT_STALE_S + 1))
    assert _cycle(root, src, clock, Sim(root, clock), h,
                  health_timeout_s=90).status == "recovered"
    root2, src2 = _setup(tmp_path / "b")
    h2 = Script(clock, lambda t: sample("r2", pid_alive=False))
    assert _cycle(root2, src2, clock, Sim(root2, clock), h2,
                  health_timeout_s=90).status == "recovered"


def test_f1_ready_and_stable_for_the_window_verifies(tmp_path):
    root, src = _setup(tmp_path)
    clock = Clock()
    start = clock.t
    h = Script(clock, lambda t: sample("r2"))
    res = _cycle(root, src, clock, Sim(root, clock), h, stable_s=30)
    assert res.status == "applied", res.to_dict()
    assert clock.t - start >= 30, "held for the whole stable window"


def test_f1_not_serving_at_the_end_of_the_window_is_not_ready(tmp_path):
    root, src = _setup(tmp_path)
    clock = Clock()
    h = Script(clock, lambda t: sample("r2"))
    res = _cycle(root, src, clock, Sim(root, clock), h, serving=lambda: False,
                 health_timeout_s=90)
    assert res.status == "recovered", res.to_dict()


def test_f1_the_default_probe_reads_the_post_import_signal(tmp_path):
    root = make_root(tmp_path)
    p = root / "ops" / "runtime" / "health.json"
    p.write_text(json.dumps({"alive": True, "run_id": "a", "pid": os.getpid()}), "ascii")
    s = uc.readiness(root)
    assert s["alive"] and s["pid_alive"] and s["ready"] is False and s["run_id"] == "a"
    p.write_text(json.dumps({"alive": True, "run_id": "a", "pid": os.getpid(),
                             "last_state_provider_ok": True}), "ascii")
    assert uc.readiness(root)["ready"] is True


def test_f1_resume_recovers_with_no_api_state(tmp_path):
    """The app is down (crash loop) and the shell has no fresh /api/state:
    `resume` still finds the verify record and recovers."""
    root, src = _setup(tmp_path)
    clock = Clock()
    h = Script(clock, lambda t: sample("r2", ready=False))
    res = _cycle(root, src, clock, Sim(root, clock), h, parent_alive=lambda: clock.t < 5010)
    assert res.status == "interrupted"
    assert uc.read_cycle(root)["verify"]["version"] == "1.1.0"
    res = uc.resume_cycle(root, clock=clock, sleep=Sim(root, clock), health=h,
                          serving=lambda: False, supervisor_alive=lambda: True,
                          health_timeout_s=60)
    assert res.status == "recovered", res.to_dict()


def test_f1_resume_with_nothing_recorded_is_idle(tmp_path):
    root = make_root(tmp_path)
    res = uc.resume_cycle(root, clock=Clock(), sleep=lambda s: None)
    assert res.status == "idle" and res.exit_code == 0


# --------------------------------------------------- F7 hot_reload verify


def test_f7_hot_reload_old_heartbeat_does_not_pass_a_broken_restart(tmp_path):
    """hot_reload restarts main.py AFTER the settle window began; the new run
    never becomes ready. The old run's fresh heartbeat must not verify it."""
    root, src = _setup(tmp_path)
    (root / "ops" / "runtime" / "hot_reload.json").write_text('{"watching": true}', "ascii")
    clock = Clock()
    t0 = clock.t

    def fn(t):
        if t - t0 < 26:
            return sample("r1")                    # old run, still fine
        return sample("r2", ready=False)            # the reload broke it
    res = _cycle(root, src, clock, Sim(root, clock), Script(clock, fn), health_timeout_s=90,
                 settle_s=20)
    assert res.status == "recovered", res.to_dict()


def test_f7_hot_reload_that_never_restarts_verifies_on_the_stable_old_run(tmp_path):
    root, src = _setup(tmp_path)
    (root / "ops" / "runtime" / "hot_reload.json").write_text('{"watching": true}', "ascii")
    clock = Clock()
    res = _cycle(root, src, clock, Sim(root, clock), Script(clock, lambda t: sample("r1")))
    assert res.status == "applied", res.to_dict()


# ----------------------------------------------- F2 interrupted deploy


def _half_deploy(root, res, *, torn=False):
    """What a quit leaves mid-deploy: the request renamed to .deploying, the
    worker's backup of core/a.py, the live file overwritten (or, torn, the
    backup itself half-written and the live file untouched), core/b.py
    created - and no result."""
    rid = res.request_id
    req = res.request_path
    req.rename(req.with_suffix(".deploying"))
    broot = root / "ops" / "backups" / f"20261026-120000-{rid}"
    (broot / "core").mkdir(parents=True)
    if torn:
        (broot / "core" / "a.py").write_bytes(b"A =")
    else:
        (broot / "core" / "a.py").write_bytes(BASE_FILES["core/a.py"])
        (root / "core" / "a.py").write_bytes(NEW_FILES["core/a.py"])
        (root / "core" / "b.py").write_bytes(NEW_FILES["core/b.py"])
    return broot


def test_f2_stale_deploying_is_interrupted_and_salvaged(tmp_path):
    root, _src, res = _staged_apply(tmp_path)
    broot = _half_deploy(root, res)
    t = [1_000_000.0]
    assert up.finish(root, now=lambda: t[0]).status == "pending"   # first sighting
    t[0] += up.DEPLOYING_STALE_S - 1
    assert up.finish(root, now=lambda: t[0]).status == "pending"
    t[0] += 2
    fin = up.finish(root, now=lambda: t[0])
    assert fin.status == "interrupted", fin
    assert up.read_state(root).get("pending") is None
    assert not (root / "ops" / "runtime" / "deploy_requests" /
                f"{res.request_id}.deploying").exists()
    rec = up.read_installed(root)
    assert rec["version"] == "1.1.0" and rec["previous"]["version"] == "1.0.0"
    assert rec["pre_hashes"] == {"core/a.py": _sha(BASE_FILES["core/a.py"])}
    assert rec["created"] == ["core/b.py"]
    assert Path(rec["backup_root"]).resolve() == broot.resolve()
    out = up.recover(root)
    assert any(n.endswith("-rollback.json") for n in _sup_requests(root))
    assert out["quarantine"]["moved"] == ["core/b.py"]
    assert up.installed_version(root) == "1.0.0"


def test_f2_a_torn_backup_is_moved_out_and_never_restored(tmp_path):
    root, _src, res = _staged_apply(tmp_path)
    broot = _half_deploy(root, res, torn=True)
    t = [1_000_000.0]
    up.finish(root, now=lambda: t[0])
    t[0] += up.DEPLOYING_STALE_S + 1
    assert up.finish(root, now=lambda: t[0]).status == "interrupted"
    assert not (broot / "core" / "a.py").exists(), "the supervisor would copy it over live"
    rec = up.read_installed(root)
    assert rec["pre_hashes"] == {} and rec["created"] == []
    assert (root / "core" / "a.py").read_bytes() == BASE_FILES["core/a.py"]
    up.recover(root)
    names = _sup_requests(root)
    assert any(n.endswith("-restart.json") for n in names)
    assert not any(n.endswith("-rollback.json") for n in names)


def test_f2_a_deploy_the_supervisor_is_still_running_is_never_salvaged(tmp_path):
    """Picked up late: the .deploying file is old on disk but was first SEEN
    now; staleness counts from the first sighting, not the file's mtime."""
    root, _src, res = _staged_apply(tmp_path)
    req = res.request_path
    os.utime(req, (time.time() - 10_000, time.time() - 10_000))
    req.rename(req.with_suffix(".deploying"))
    assert up.finish(root).status == "pending"
    assert up.read_state(root)["pending"]["deploying_seen_at"]


def test_f2_the_cycle_recovers_an_interrupted_deploy(tmp_path):
    root, src = _setup(tmp_path)
    clock = Clock()
    wall = [1_000_000.0]

    def quit_mid_deploy(seconds):
        clock.t += seconds
        wall[0] += seconds
        d = root / "ops" / "runtime" / "deploy_requests"
        for req in sorted(d.glob("*.json")):
            _half_deploy(root, type("R", (), {"request_id": req.stem, "request_path": req})())
    res = _cycle(root, src, clock, quit_mid_deploy, Script(clock, lambda t: sample("r1")),
                 now=lambda: wall[0], finish_timeout_s=30)
    assert res.status == "pending"
    wall[0] += up.DEPLOYING_STALE_S + 60
    res = uc.resume_cycle(root, clock=clock, sleep=quit_mid_deploy, now=lambda: wall[0],
                          health=Script(clock, lambda t: sample("r1")), serving=lambda: True,
                          supervisor_alive=lambda: True, finish_timeout_s=30)
    assert res.status == "recovered", res.to_dict()
    assert "1.1.0" in uc.read_cycle(root)["bad_versions"]


def test_f2_host_stop_waits_while_a_deploy_is_in_flight(tmp_path):
    root = make_host_root(tmp_path)
    clock = HostClock()
    fp = FakePopen(clock=clock)
    job = FakeJob([])
    host = make_host(root, make_config(grace=5.0), popen=fp, job=job, clock=clock)
    host.start()
    dep = root / "ops" / "runtime" / "deploy_requests" / "launcher-update-1.1.0-1-ab.deploying"
    dep.parent.mkdir(parents=True)
    dep.write_text("{}", encoding="ascii")
    t0 = clock.t
    gone_at = t0 + 40

    def sleep(seconds):
        clock.sleep(seconds)
        if clock.t >= gone_at and dep.exists():
            dep.unlink()   # the worker finished; the supervisor removed it
    host._sleep = sleep
    host.stop("quit")
    assert job.terminated == 1
    assert clock.t >= gone_at, "the job was not ended under a running deploy"
    assert clock.t < t0 + sh.DEPLOY_STOP_GRACE_S


def test_f2_host_stop_grace_is_bounded_even_with_a_deploy(tmp_path):
    root = make_host_root(tmp_path)
    clock = HostClock()
    host = make_host(root, make_config(grace=5.0), popen=FakePopen(clock=clock),
                     job=FakeJob([]), clock=clock)
    host.start()
    dep = root / "ops" / "runtime" / "deploy_requests" / "x.deploying"
    dep.parent.mkdir(parents=True)
    dep.write_text("{}", encoding="ascii")
    t0 = clock.t
    host.stop("quit")
    assert t0 + sh.DEPLOY_STOP_GRACE_S <= clock.t < t0 + sh.DEPLOY_STOP_GRACE_S + 1


# ----------------------------------------------------- F6 re-entrant recover


def _applied(tmp_path):
    root, src = _setup(tmp_path)
    up.stage(root, src, src.release("1.1.0"), shell_version="9.9.9")
    res = up.apply(root, "1.1.0", game_check=no_game, hot_reload_active=False)
    assert run_worker(root, res.request_path)["ok"]
    assert up.finish(root).status == "ok"
    return root


def test_f6_a_kill_between_requests_and_record_is_completed_once(tmp_path, monkeypatch):
    root = _applied(tmp_path)
    real = up._restore_previous

    def killed(*_a, **_k):
        raise KeyboardInterrupt("killed mid-recover")
    monkeypatch.setattr(up, "_restore_previous", killed)
    with pytest.raises(KeyboardInterrupt):
        up.recover(root)
    marker = up.read_state(root).get("recovering")
    assert marker and marker["version"] == "1.1.0" and marker["requests"]
    assert up.installed_version(root) == "1.1.0"
    before = _sup_requests(root)
    monkeypatch.setattr(up, "_restore_previous", real)
    up.recover(root)
    assert _sup_requests(root) == before, "requests are not written twice"
    assert up.installed_version(root) == "1.0.0"
    assert up.read_state(root).get("recovering") is None


def test_f6_a_kill_before_any_request_redoes_the_requests(tmp_path, monkeypatch):
    root = _applied(tmp_path)
    real = up._write_json
    calls = []

    def flaky(path, data):
        if "supervisor_requests" in str(path) and not calls:
            calls.append(1)
            raise KeyboardInterrupt("killed before the first request")
        return real(path, data)
    monkeypatch.setattr(up, "_write_json", flaky)
    with pytest.raises(KeyboardInterrupt):
        up.recover(root)
    assert up.read_state(root)["recovering"]["requests"] is None
    up.recover(root)
    names = _sup_requests(root)
    assert any(n.endswith("-rollback.json") for n in names)
    assert up.installed_version(root) == "1.0.0"


def test_f6_the_cycle_completes_an_interrupted_recover_first(tmp_path, monkeypatch):
    root = _applied(tmp_path)
    real = up._restore_previous
    monkeypatch.setattr(up, "_restore_previous",
                        lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        up.recover(root)
    monkeypatch.setattr(up, "_restore_previous", real)
    res = uc.resume_cycle(root, clock=Clock(), sleep=lambda s: None,
                          supervisor_alive=lambda: True)
    assert res.status == "recovered", res.to_dict()
    assert up.installed_version(root) == "1.0.0"


def test_f6_offline_recover_restores_the_backup_itself(tmp_path):
    root = _applied(tmp_path)
    assert (root / "core" / "a.py").read_bytes() == NEW_FILES["core/a.py"]
    out = up.recover(root, offline=True)
    assert out["status"] == "restored"
    assert (root / "core" / "a.py").read_bytes() == BASE_FILES["core/a.py"]
    assert not (root / "core" / "b.py").exists()
    assert not [n for n in _sup_requests(root) if n.startswith("launcher-recover-")],         "no supervisor to read them"
    assert up.installed_version(root) == "1.0.0"


def test_f6_the_cycle_recovers_offline_when_no_supervisor_runs(tmp_path):
    root, src = _setup(tmp_path)
    clock = Clock()
    res = _cycle(root, src, clock, Sim(root, clock), Script(clock, lambda t: sample("r2", alive=False)),
                 health_timeout_s=60, supervisor_alive=lambda: False)
    assert res.status == "recovered", res.to_dict()
    assert (root / "core" / "a.py").read_bytes() == BASE_FILES["core/a.py"]


# --------------------------------------------------------- F4 bad versions


def test_f4_a_recovered_version_is_never_reapplied(tmp_path):
    root, src = _setup(tmp_path)
    clock = Clock()
    bad = Script(clock, lambda t: sample("r2", ready=False))
    assert _cycle(root, src, clock, Sim(root, clock), bad,
                  health_timeout_s=60).status == "recovered"
    assert uc.read_cycle(root)["bad_versions"]["1.1.0"]["status"] == "recovered"
    res = _cycle(root, src, clock, Sim(root, clock), Script(clock, lambda t: sample("r3")))
    assert res.status == "skipped" and res.exit_code == 0, res.to_dict()
    assert res.version == "1.1.0"
    assert up.installed_version(root) == "1.0.0"


def test_f4_a_newer_release_is_still_offered(tmp_path):
    root, src = _setup(tmp_path)
    clock = Clock()
    assert _cycle(root, src, clock, Sim(root, clock), Script(clock, lambda t: sample("r2", ready=False)),
                  health_timeout_s=60).status == "recovered"
    newer = dict(NEW_FILES, **{"core/c.py": b"C = 1\n"})
    rel = build_release(tmp_path / "rel-1.1.0", "1.2.0", newer)
    res = _cycle(root, up.LocalSource(rel), clock, Sim(root, clock),
                 Script(clock, lambda t: sample("r4")))
    assert res.status == "applied", res.to_dict()
    assert up.installed_version(root) == "1.2.0"


def test_f4_check_excludes_named_versions(tmp_path):
    rel = build_release(tmp_path / "rel", "1.1.0", NEW_FILES)
    build_release(rel, "1.2.0", NEW_FILES)
    src = up.LocalSource(rel)
    assert up.check(src, current_version="1.0.0").version == "1.2.0"
    assert up.check(src, current_version="1.0.0", exclude={"1.2.0"}).version == "1.1.0"
    assert up.check(src, current_version="1.0.0", exclude={"1.2.0", "1.1.0"}) is None


def test_f4_a_failed_deploy_is_recorded_bad(tmp_path):
    root, src = _setup(tmp_path)
    clock = Clock()

    def failing(seconds):
        clock.t += seconds
        d = root / "ops" / "runtime" / "deploy_requests"
        for req in sorted(d.glob("*.json")):
            out = root / "ops" / "runtime" / "deploy_results"
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{req.stem}.json").write_text(json.dumps({"ok": False, "phase": "compile"}),
                                                  "ascii")
            req.unlink()
    assert _cycle(root, src, clock, failing, Script(clock, lambda t: sample())).status == "failed"
    assert uc.read_cycle(root)["bad_versions"]["1.1.0"]["status"] == "failed"


# ---------------------------------------------------- F3 owed restarts


VISION_FILES = {"core/a.py": b"A = 1\n", "web/js/main.js": b"// v1\n", "data/x.json": b"{}\n",
                "vision_server/extra.py": b"X = 1\n"}


class Services:
    """services_probe for the cycle: name -> {restarted, healthy, pid}."""

    def __init__(self, clock, fn):
        self.clock, self.fn = clock, fn

    def __call__(self, owed):
        return {name: self.fn(name, self.clock.t) for name in owed["names"]}


def _owed(tmp_path):
    root, src = _setup(tmp_path, files=VISION_FILES)
    clock = Clock()
    res = _cycle(root, src, clock, Sim(root, clock), Script(clock, lambda t: sample("r1")))
    assert res.status == "applied" and res.restart["host_services"] == ["vision"]
    owed = uc.read_cycle(root)["owed"]
    assert owed["names"] == ["vision"] and owed["version"] == "1.1.0"
    return root, src, clock


def _resume(root, clock, services, **kw):
    kw.setdefault("health", Script(clock, lambda t: sample("r1")))
    kw.setdefault("serving", lambda: True)
    kw.setdefault("supervisor_alive", lambda: True)
    kw.setdefault("game_check", no_game)
    return uc.resume_cycle(root, clock=clock, sleep=Sim(root, clock),
                           services_probe=services, **kw)


def test_f3_owed_restarts_are_reported_until_the_shell_sends_them(tmp_path):
    root, _src, clock = _owed(tmp_path)
    res = _resume(root, clock, Services(clock, lambda n, t: {"restarted": False, "healthy": True,
                                                             "pid": 1}))
    assert res.status == "owed" and res.restart["host_services"] == ["vision"]
    assert uc.read_cycle(root)["owed"] is not None


def test_f3_restarted_and_stable_services_verify(tmp_path):
    root, _src, clock = _owed(tmp_path)
    res = _resume(root, clock, Services(clock, lambda n, t: {"restarted": True, "healthy": True,
                                                             "pid": 77}),
                  restarts_sent=True)
    assert res.status == "applied", res.to_dict()
    assert uc.read_cycle(root)["owed"] is None
    assert res.restart["host_services"] == []


def test_f3_a_service_that_does_not_come_back_is_recovered(tmp_path):
    root, _src, clock = _owed(tmp_path)
    res = _resume(root, clock, Services(clock, lambda n, t: {"restarted": False, "healthy": False,
                                                             "pid": None}),
                  restarts_sent=True, health_timeout_s=60)
    assert res.status == "recovered", res.to_dict()
    assert res.restart["host_services"] == ["vision"], "the old code must be loaded again"
    assert "1.1.0" in uc.read_cycle(root)["bad_versions"]
    assert up.installed_version(root) == "1.0.0"


def test_f3_a_crash_looping_service_is_not_stable(tmp_path):
    root, _src, clock = _owed(tmp_path)
    res = _resume(root, clock, Services(clock, lambda n, t: {"restarted": True, "healthy": True,
                                                             "pid": int(t)}),
                  restarts_sent=True, health_timeout_s=60)
    assert res.status == "recovered", res.to_dict()


def test_f3_a_failed_restart_during_a_game_defers_the_recover(tmp_path):
    root, _src, clock = _owed(tmp_path)
    res = _resume(root, clock, Services(clock, lambda n, t: {"restarted": False, "healthy": False,
                                                             "pid": None}),
                  restarts_sent=True, health_timeout_s=60,
                  game_check=lambda: "process league of legends.exe")
    assert res.status == "deferred" and res.exit_code == 3
    assert up.installed_version(root) == "1.1.0"
    assert uc.read_cycle(root)["owed"] is not None


def test_f3_the_default_probe_reads_host_status_and_ports(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    rt = root / "ops" / "runtime"
    after = "2030-01-01T00:00:00+00:00"
    (rt / "launcher_status.json").write_text(json.dumps({
        "schema": 1, "updated": up.utc_now(), "mode": "owned", "state": "running",
        "host_pid": 4321,
        "services": [{"name": "lcu_agent", "state": "running", "pid": 55, "started": after}]}),
        "ascii")
    monkeypatch.setattr(uc.sh, "port_listener_pids", lambda port: [66] if port == 8889 else [])
    monkeypatch.setattr(uc.sh, "process_created", lambda pid: 2e9)
    owed = {"names": ["lcu_agent", "vision", "ds"], "respawn_host": False,
            "host_pid_before": 1, "at_epoch": 1.8e9}
    got = uc.services_state(root, owed)
    assert got["lcu_agent"] == {"restarted": True, "healthy": True, "pid": 55}
    assert got["vision"] == {"restarted": True, "healthy": True, "pid": 66}
    assert got["ds"]["healthy"] is False
    owed2 = dict(owed, names=["app"], respawn_host=True)
    assert uc.services_state(root, owed2)["app"]["restarted"] is True

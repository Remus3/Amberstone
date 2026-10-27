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

    def __init__(self, root, clock, *, worker=True, after_worker=None):
        self.root, self.clock, self.worker = root, clock, worker
        self.ran = 0
        self.restarts = 0
        self.after_worker = after_worker

    def __call__(self, seconds):
        self.clock.t += max(float(seconds), 0.01)
        rt = self.root / "ops" / "runtime"
        for req in sorted((rt / "supervisor_requests").glob("*.restart.json")):
            req.unlink()
            self.restarts += 1
        if self.worker:
            for req in sorted((rt / "deploy_requests").glob("*.json")):
                assert run_worker(self.root, req)["ok"]
                self.ran += 1
                if self.after_worker:
                    self.after_worker()


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


def _fresh_watcher(root: Path, *, stale: bool = False) -> None:
    """A running main.py (health.json started_at) and its hot_reload watcher
    status, written in THIS run (fresh) - or, stale, before the run began."""
    rt = root / "ops" / "runtime"
    hr = rt / "hot_reload.json"
    hr.write_text('{"watching": true}', encoding="ascii")
    started = up.utc_now()
    if stale:
        os.utime(hr, (time.time() - 3600, time.time() - 3600))
    else:
        old = time.time() - 120
        started = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(old))
    (rt / "health.json").write_text(json.dumps({
        "alive": True, "run_id": "r1", "pid": os.getpid(), "started_at": started,
        "last_state_provider_ok": True}), encoding="ascii")


def _reload_fired(root: Path, changed):
    def write():
        (root / "ops" / "runtime" / "hot_reload.json").write_text(json.dumps({
            "watching": True, "last_compile": f"OK ({len(changed)} file(s))",
            "changed": list(changed)}), encoding="ascii")
    return write


def test_f7_hot_reload_watching_requires_a_watcher_of_the_current_run(tmp_path):
    root = make_root(tmp_path)
    (root / "ops" / "runtime" / "hot_reload.json").write_text('{"watching": true}', "ascii")
    assert up.hot_reload_watching(root) is False, "no live run: nobody is watching"
    _fresh_watcher(root)
    assert up.hot_reload_watching(root) is True
    _fresh_watcher(root, stale=True)
    assert up.hot_reload_watching(root) is False, "status from an older run"


def test_f7_a_stale_watcher_falls_back_to_a_supervised_restart(tmp_path):
    root, src = _setup(tmp_path)
    _fresh_watcher(root, stale=True)
    clock = Clock()
    sim = Sim(root, clock)
    res = _cycle(root, src, clock, sim, Script(clock, lambda t: sample("r1")),
                 health_timeout_s=60)
    assert sim.restarts == 1, "force_restart: the worker asked the supervisor"
    assert res.status == "recovered", "the old run r1 never passes a supervised restart"


def test_f7_a_fresh_watcher_that_ignored_the_change_verifies_on_the_old_run(tmp_path):
    root, src = _setup(tmp_path)
    _fresh_watcher(root)
    clock = Clock()
    sim = Sim(root, clock)
    res = _cycle(root, src, clock, sim, Script(clock, lambda t: sample("r1")))
    assert sim.restarts == 0
    assert res.status == "applied", res.to_dict()


def test_f7_a_reload_that_fired_needs_a_new_run(tmp_path):
    root, src = _setup(tmp_path)
    _fresh_watcher(root)
    clock = Clock()
    sim = Sim(root, clock, after_worker=_reload_fired(root, ["core/a.py"]))
    res = _cycle(root, src, clock, sim, Script(clock, lambda t: sample("r1")),
                 health_timeout_s=60)
    assert res.status == "recovered", res.to_dict()


def test_f7_a_reload_that_fired_and_came_back_verifies(tmp_path):
    root, src = _setup(tmp_path)
    _fresh_watcher(root)
    clock = Clock()
    sim = Sim(root, clock, after_worker=_reload_fired(root, ["core/a.py"]))
    t0 = clock.t
    res = _cycle(root, src, clock, sim,
                 Script(clock, lambda t: sample("r1" if t - t0 < 10 else "r2")))
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
    kw = {"now": lambda: t[0], "uptime": lambda: t[0]}
    assert up.finish(root, **kw).status == "pending"   # first sighting
    t[0] += up.DEPLOYING_STALE_S - 1
    assert up.finish(root, **kw).status == "pending"
    t[0] += 2
    fin = up.finish(root, **kw)
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
    kw = {"now": lambda: t[0], "uptime": lambda: t[0]}
    up.finish(root, **kw)
    t[0] += up.DEPLOYING_STALE_S + 1
    assert up.finish(root, **kw).status == "interrupted"
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
                 now=lambda: wall[0], uptime=lambda: wall[0], finish_timeout_s=30)
    assert res.status == "pending"
    wall[0] += up.DEPLOYING_STALE_S + 60
    res = uc.resume_cycle(root, clock=clock, sleep=quit_mid_deploy, now=lambda: wall[0],
                          uptime=lambda: wall[0],
                          health=Script(clock, lambda t: sample("r1")), serving=lambda: True,
                          supervisor_alive=lambda: True, finish_timeout_s=30)
    assert res.status == "recovered", res.to_dict()
    assert "1.1.0" in uc.read_cycle(root)["bad_versions"]


class _TimedJob(FakeJob):
    def __init__(self, clock):
        super().__init__([])
        self.clock = clock
        self.terminated_at = None

    def terminate(self):
        super().terminate()
        self.terminated_at = self.clock.t


def _quitting_host(tmp_path):
    """A host whose supervisor exits AT ONCE on its shutdown request (the
    frozen supervisor does not wait for its deploy thread,
    ops/rc_supervisor.py:1309-1314) - so every service is gone while the
    deploy worker, a grandchild in the job, may still be copying."""
    root = make_host_root(tmp_path)
    clock = HostClock()
    fp = FakePopen(clock=clock)
    reqs = root / "ops" / "runtime" / "supervisor_requests"
    fp.behaviour["sup.py"] = lambda proc: 0 if any(reqs.glob("launcher-shutdown-*.json")) \
        else None
    job = _TimedJob(clock)
    host = make_host(root, make_config(grace=5.0), popen=fp, job=job, clock=clock)
    host.start()
    d = root / "ops" / "runtime" / "deploy_requests"
    d.mkdir(parents=True)
    return root, clock, host, job, d


def test_b2_quit_waits_for_the_deploy_worker_after_the_supervisor_exited(tmp_path):
    root, clock, host, job, d = _quitting_host(tmp_path)
    (d / "launcher-update-1.1.0-1-ab.deploying").write_text("{}", encoding="ascii")
    t0 = clock.t
    done_at = t0 + 40

    def sleep(seconds):
        clock.sleep(seconds)
        res = root / "ops" / "runtime" / "deploy_results" / "launcher-update-1.1.0-1-ab.json"
        if clock.t >= done_at and not res.exists():
            res.parent.mkdir(parents=True, exist_ok=True)
            res.write_text('{"ok": true}', encoding="ascii")   # the worker finished
    host._sleep = sleep
    host.stop("quit")
    assert not any(rt.alive() for rt in host._services)
    assert job.terminated_at is not None
    assert job.terminated_at >= done_at, "the job was ended under a copying worker"
    assert job.terminated_at < t0 + sh.DEPLOY_STOP_GRACE_S


def test_b2_quit_grace_is_bounded_while_a_worker_never_finishes(tmp_path):
    _root, clock, host, job, d = _quitting_host(tmp_path)
    (d / "x.deploying").write_text("{}", encoding="ascii")
    t0 = clock.t
    host.stop("quit")
    assert t0 + sh.DEPLOY_STOP_GRACE_S <= job.terminated_at < t0 + sh.DEPLOY_STOP_GRACE_S + 1


def test_b9_a_deploying_that_already_has_a_result_does_not_hold_the_quit(tmp_path):
    root, clock, host, job, d = _quitting_host(tmp_path)
    (d / "done.deploying").write_text("{}", encoding="ascii")
    res = root / "ops" / "runtime" / "deploy_results" / "done.json"
    res.parent.mkdir(parents=True)
    res.write_text('{"ok": true}', encoding="ascii")
    t0 = clock.t
    host.stop("quit")
    assert job.terminated_at < t0 + 1, "a finished deploy is not in flight"


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


# =============================================== fix round 2 (B1, B3-B9)


def _dead_pid() -> int:
    import subprocess
    import sys
    p = subprocess.Popen([sys.executable, "-c", "pass"], creationflags=0x08000000
                         if os.name == "nt" else 0)
    p.wait(30)
    return p.pid


def _status(root: Path, **doc) -> None:
    base = {"schema": 1, "updated": up.utc_now(), "mode": "owned", "state": "running",
            "host_pid": os.getpid(), "services": []}
    base.update(doc)
    (root / "ops" / "runtime" / "launcher_status.json").write_text(json.dumps(base), "ascii")


def test_b1_halted_counts_only_for_a_live_fresh_host(tmp_path):
    root = make_root(tmp_path)
    _status(root, state="halted")
    assert uc._host_halted(root) is True, "this host is stopping right now"
    _status(root, state="halted", host_pid=_dead_pid())
    assert uc._host_halted(root) is False, "a dead host's last word"
    _status(root, state="halted", updated="2020-01-01T00:00:00+00:00")
    assert uc._host_halted(root) is False, "stale"


def test_b1_a_stale_halted_status_never_blocks_a_recover(tmp_path):
    """The respawned host died on import: the status file still holds the OLD
    host's "halted". The restart check must recover, not report interrupted."""
    root, _src, clock = _owed(tmp_path)
    _status(root, state="halted", host_pid=_dead_pid(), updated="2020-01-01T00:00:00+00:00")
    res = _resume(root, clock, Services(clock, lambda n, t: {"restarted": False, "healthy": False,
                                                             "pid": None}),
                  restarts_sent=True, health_timeout_s=60)
    assert res.status == "recovered", res.to_dict()
    assert uc.read_cycle(root)["owed"] is None


def test_b4_a_restart_check_marks_the_owed_record_sent(tmp_path):
    root, _src, clock = _owed(tmp_path)
    res = _resume(root, clock, Services(clock, lambda n, t: {"restarted": False, "healthy": False,
                                                             "pid": None}),
                  restarts_sent=True, health_timeout_s=60,
                  game_check=lambda: "process league of legends.exe")
    assert res.status == "deferred"
    assert uc.read_cycle(root)["owed"]["sent_at"], "the shell retries a sent check"


def _commands_status(root, outcome, *, at="2030-01-01T00:00:00+00:00"):
    _status(root, commands=[{"id": "shell-1", "cmd": "restart", "at": at,
                             "results": {"vision": outcome}}])


def test_b6_a_service_the_host_does_not_own_is_skipped_never_failed(tmp_path, monkeypatch):
    root, _src, clock = _owed(tmp_path)
    _commands_status(root, "refused:not-in-job")
    monkeypatch.setattr(uc.sh, "port_listener_pids", lambda port: [66])
    monkeypatch.setattr(uc.sh, "process_created", lambda pid: 1.0)   # older than the deploy
    owed = uc.read_cycle(root)["owed"]
    owed["at_epoch"] = 1.8e9
    assert uc.services_state(root, owed)["vision"]["skip"] == "refused:not-in-job"
    res = _resume(root, clock, lambda o: uc.services_state(root, dict(o, at_epoch=1.8e9)),
                  restarts_sent=True, health_timeout_s=60)
    assert res.status == "applied-unrestarted", res.to_dict()   # fix round 3 (R2)
    assert "not ours" in res.detail and res.exit_code == 0
    assert "1.1.0" not in uc.read_cycle(root)["bad_versions"]
    assert up.installed_version(root) == "1.1.0"


def test_b3_restarts_the_host_deferred_are_owed_again(tmp_path):
    root, _src, clock = _owed(tmp_path)
    _commands_status(root, "deferred:game-live")
    owed = dict(uc.read_cycle(root)["owed"], at_epoch=1.8e9)
    assert uc.services_state(root, owed)["vision"]["deferred"] == "deferred:game-live"
    res = _resume(root, clock, lambda o: uc.services_state(root, dict(o, at_epoch=1.8e9)),
                  restarts_sent=True)
    assert res.status == "owed" and res.restart["host_services"] == ["vision"]
    assert uc.read_cycle(root)["owed"].get("sent_at") is None
    assert "1.1.0" not in uc.read_cycle(root)["bad_versions"]


def _mixed_apply(tmp_path, live_before_worker):
    """apply hashes core/a.py, then the live file changes BEFORE the worker
    runs; the worker backs up those bytes and overwrites the file."""
    root, _src, res = _staged_apply(tmp_path)
    (root / "core" / "a.py").write_bytes(live_before_worker)
    req = res.request_path
    req.rename(req.with_suffix(".deploying"))
    broot = root / "ops" / "backups" / f"20261026-120000-{res.request_id}"
    (broot / "core").mkdir(parents=True)
    (broot / "core" / "a.py").write_bytes(live_before_worker)
    return root, broot


def test_b7_a_good_backup_of_a_file_changed_before_the_worker_ran_is_kept(tmp_path):
    root, broot = _mixed_apply(tmp_path, b"A = 9\n")
    (root / "core" / "a.py").write_bytes(NEW_FILES["core/a.py"])   # the worker overwrote it
    t = [1e6]
    kw = {"now": lambda: t[0], "uptime": lambda: t[0]}
    up.finish(root, **kw)
    t[0] += up.DEPLOYING_STALE_S + 1
    assert up.finish(root, **kw).status == "interrupted"
    assert (broot / "core" / "a.py").read_bytes() == b"A = 9\n", "kept for the rollback"
    rec = up.read_installed(root)
    assert rec["pre_hashes"] == {"core/a.py": _sha(b"A = 9\n")}
    up.recover(root, offline=True)
    assert (root / "core" / "a.py").read_bytes() == b"A = 9\n"


def test_b7_a_backup_whose_file_was_never_overwritten_is_moved_out(tmp_path):
    root, broot = _mixed_apply(tmp_path, b"A = 9\n")   # live still the backed-up bytes
    t = [1e6]
    kw = {"now": lambda: t[0], "uptime": lambda: t[0]}
    up.finish(root, **kw)
    t[0] += up.DEPLOYING_STALE_S + 1
    assert up.finish(root, **kw).status == "interrupted"
    assert not (broot / "core" / "a.py").exists()
    assert up.read_installed(root)["pre_hashes"] == {}


def test_b8_staleness_follows_boot_uptime_not_the_wall_clock(tmp_path):
    root, _src, res = _staged_apply(tmp_path)
    _half_deploy(root, res)
    wall, upt = [1e6], [5000.0]
    kw = {"now": lambda: wall[0], "uptime": lambda: upt[0]}
    assert up.finish(root, **kw).status == "pending"
    wall[0] += 10_000          # a clock jump: not evidence
    upt[0] += 10
    assert up.finish(root, **kw).status == "pending"
    upt[0] += up.DEPLOYING_STALE_S
    assert up.finish(root, **kw).status == "interrupted"


def test_b8_a_reboot_since_the_first_sighting_is_stale_at_once(tmp_path):
    root, _src, res = _staged_apply(tmp_path)
    _half_deploy(root, res)
    upt = [5000.0]
    kw = {"now": lambda: 1e6, "uptime": lambda: upt[0]}
    assert up.finish(root, **kw).status == "pending"
    upt[0] = 30.0              # uptime went backwards: the machine rebooted
    assert up.finish(root, **kw).status == "interrupted"


def test_b8_the_default_uptime_is_monotonic_and_boot_relative():
    a = up.boot_uptime_s()
    b = up.boot_uptime_s()
    assert 0 < a <= b < 10 ** 8


def test_b9_a_deploying_left_next_to_its_result_is_cleaned(tmp_path):
    root, _src, res = _staged_apply(tmp_path)
    dep = res.request_path.with_suffix(".deploying")
    res.request_path.rename(dep)
    out = root / "ops" / "runtime" / "deploy_results"
    out.mkdir(parents=True)
    (out / f"{res.request_id}.json").write_text(json.dumps(
        {"ok": False, "phase": "health_check", "rollback": True}), "ascii")
    assert up.finish(root).status == "failed"
    assert not dep.exists()


# =============================================== fix round 3 (R1-R7, F7 DEFERRED)


def _failing_after_quit(root, clock, *, quit=True):
    """The injected sleep: the host's quit lands while the worker runs; the
    supervisor stopped main.py, so the worker's heartbeat wait failed and it
    rolled back (ops/rc_transactional_deploy.py:860-874)."""
    def sleep(seconds):
        clock.t += seconds
        d = root / "ops" / "runtime" / "deploy_requests"
        for req in sorted(d.glob("*.json")):
            if quit:
                sh.record_host_stop(root / "ops" / "runtime", "quit")
            out = root / "ops" / "runtime" / "deploy_results"
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{req.stem}.json").write_text(json.dumps(
                {"ok": False, "phase": "health_check", "rollback": True}), "ascii")
            req.unlink()
    return sleep


def test_r1_a_quit_during_the_deploy_never_marks_the_release_bad(tmp_path):
    root, src = _setup(tmp_path)
    clock = Clock()
    res = _cycle(root, src, clock, _failing_after_quit(root, clock), Script(clock, lambda t: sample()))
    assert res.status == "interrupted" and res.exit_code == 0, res.to_dict()
    assert uc.read_cycle(root)["bad_versions"] == {}
    res = _cycle(root, src, clock, Sim(root, clock), Script(clock, lambda t: sample("r1")))
    assert res.status == "applied", "the next idle cycle retries the release"


def test_r1_a_genuine_failure_with_no_quit_is_still_bad(tmp_path):
    root, src = _setup(tmp_path)
    clock = Clock()
    res = _cycle(root, src, clock, _failing_after_quit(root, clock, quit=False),
                 Script(clock, lambda t: sample()))
    assert res.status == "failed"
    assert "1.1.0" in uc.read_cycle(root)["bad_versions"]


def test_r1_a_quit_before_the_deploy_window_does_not_excuse_it(tmp_path):
    root, src = _setup(tmp_path)
    sh.record_host_stop(root / "ops" / "runtime", "an older quit")
    marks = json.loads((root / "ops" / "runtime" / "launcher" / "host_stops.json").read_text())
    marks["stops"][0]["at"] -= 3600
    (root / "ops" / "runtime" / "launcher" / "host_stops.json").write_text(json.dumps(marks))
    clock = Clock()
    res = _cycle(root, src, clock, _failing_after_quit(root, clock, quit=False),
                 Script(clock, lambda t: sample()))
    assert res.status == "failed" and "1.1.0" in uc.read_cycle(root)["bad_versions"]


def test_r1_an_interrupted_deploy_after_a_quit_recovers_without_a_bad_mark(tmp_path):
    root, src = _setup(tmp_path)
    clock = Clock()
    wall = [1_000_000.0]

    def quit_mid_deploy(seconds):
        clock.t += seconds
        wall[0] += seconds
        d = root / "ops" / "runtime" / "deploy_requests"
        for req in sorted(d.glob("*.json")):
            sh.record_host_stop(root / "ops" / "runtime", "quit")
            _half_deploy(root, type("R", (), {"request_id": req.stem, "request_path": req})())
    # The host marks its stop on the real wall clock, like apply's request
    # time; only the boot uptime (staleness) is injected here.
    res = _cycle(root, src, clock, quit_mid_deploy, Script(clock, lambda t: sample("r1")),
                 uptime=lambda: wall[0], finish_timeout_s=30)
    assert res.status == "pending"
    wall[0] += up.DEPLOYING_STALE_S + 60
    res = uc.resume_cycle(root, clock=clock, sleep=quit_mid_deploy,
                          uptime=lambda: wall[0], health=Script(clock, lambda t: sample("r1")),
                          serving=lambda: True, supervisor_alive=lambda: True, finish_timeout_s=30)
    assert res.status == "recovered", res.to_dict()
    assert uc.read_cycle(root)["bad_versions"] == {}, "a quit is not a bad release"


def test_r1_the_host_records_its_stop_before_it_asks_the_supervisor(tmp_path, monkeypatch):
    root = make_host_root(tmp_path)
    clock = HostClock()
    host = make_host(root, make_config(grace=1.0), popen=FakePopen(clock=clock),
                     job=FakeJob([]), clock=clock)
    host.start()
    marks = root / "ops" / "runtime" / "launcher" / "host_stops.json"
    seen = []
    real = sh.write_shutdown_request

    def spy(runtime_dir, reason):
        seen.append(marks.is_file())
        return real(runtime_dir, reason)
    monkeypatch.setattr(sh, "write_shutdown_request", spy)
    host.stop("quit")
    assert seen == [True], "the marker exists before the shutdown request"
    doc = json.loads(marks.read_text(encoding="ascii"))
    assert doc["stops"][-1]["reason"] == "quit"
    assert abs(doc["stops"][-1]["at"] - time.time()) < 60


def test_r1_the_host_mark_list_is_bounded(tmp_path):
    rt = tmp_path / "rt"
    for i in range(sh.HOST_STOP_HISTORY + 5):
        sh.record_host_stop(rt, f"r{i}")
    doc = json.loads((rt / "launcher" / "host_stops.json").read_text(encoding="ascii"))
    assert len(doc["stops"]) == sh.HOST_STOP_HISTORY
    assert doc["stops"][-1]["reason"] == f"r{sh.HOST_STOP_HISTORY + 4}"


def test_r2_open_failed_outside_the_job_is_not_ours(tmp_path):
    root, _src, clock = _owed(tmp_path)
    _commands_status(root, "refused:open-failed")
    owed = dict(uc.read_cycle(root)["owed"], at_epoch=1.8e9)
    assert uc.services_state(root, owed)["vision"]["skip"] == "refused:open-failed"
    assert "refused:terminate-failed" not in uc.NOT_OURS, "in the job but unkillable = a failure"


def test_r2_attach_mode_refusals_are_unrestarted_not_verified(tmp_path):
    root, _src, clock = _owed(tmp_path)
    _commands_status(root, "refused:not-owned")
    res = _resume(root, clock, lambda o: uc.services_state(root, dict(o, at_epoch=1.8e9)),
                  restarts_sent=True)
    assert res.status == "applied-unrestarted", res.to_dict()
    assert "restart" in res.detail.lower()
    assert uc.read_cycle(root)["bad_versions"] == {}


LCU_FILES = {"core/a.py": b"A = 2\n", "web/js/main.js": b"// v1\n", "data/x.json": b"{}\n",
             "tools/lcu_agent.py": b"L = 1\n"}


def test_r4_a_recover_owes_restarts_for_the_rolled_back_files(tmp_path):
    root, src = _setup(tmp_path, files=LCU_FILES)
    clock = Clock()
    res = _cycle(root, src, clock, Sim(root, clock), Script(clock, lambda t: sample("r2", ready=False)),
                 health_timeout_s=60)
    assert res.status == "recovered", res.to_dict()
    assert res.restart["host_services"] == ["lcu_agent"], \
        "lcu_agent may hold the rolled-back code: it restarts on the restored files"


def test_r4_recover_waits_for_the_supervisor_to_take_its_rollback(tmp_path):
    root, src = _setup(tmp_path)
    clock = Clock()
    consumed = []
    seen = []

    def sim(seconds):
        Sim(root, clock)(seconds)
        reqs = sorted((root / "ops" / "runtime" / "supervisor_requests").glob("launcher-recover-*"))
        if reqs:
            seen.append(clock.t)
        if reqs and len(seen) >= 3:   # the supervisor takes it a few polls later
            for r in reqs:
                r.unlink()
            consumed.append(clock.t)
    t_before = clock.t
    res = _cycle(root, src, clock, sim, Script(clock, lambda t: sample("r2", ready=False)),
                 health_timeout_s=60)
    assert res.status == "recovered"
    assert consumed and clock.t >= consumed[0], "returned only after the supervisor took it"
    assert clock.t - t_before < 60 + uc.SUPERVISOR_TAKE_S + 60


def test_r5_busy_from_state_mirrors_the_shell_gate():
    assert uc.busy_from_state({"lcu": {"phase": "Lobby"}, "liveclient": {}, "health": {}}) is None
    assert uc.busy_from_state({"lcu": {"phase": "ChampSelect"}}) == "lcu phase ChampSelect"
    assert uc.busy_from_state({"lcu": {"phase": "Lobby"}, "health": {"has_game": True}})
    assert uc.busy_from_state({"liveclient": {"activePlayer": {}}})
    assert uc.busy_from_state(None) == "no /api/state"
    js = (Path(__file__).resolve().parent.parent / "rc-shell" / "src" / "backend_update.js").read_text()
    assert 'IDLE_PHASES = Object.freeze(["", "None", "Lobby"])' in js
    assert uc.IDLE_PHASES == ("", "None", "Lobby"), "mirrors the shell's gate"


def test_r5_apply_defers_in_champ_select(tmp_path, monkeypatch):
    root, src = _setup(tmp_path)
    monkeypatch.setattr(uc.up, "game_live", lambda *a, **k: None)
    monkeypatch.setattr(uc, "fetch_api_state", lambda r: {"lcu": {"phase": "ChampSelect"}})
    clock = Clock()
    res = uc.run_cycle(root, src, clock=clock, sleep=Sim(root, clock), shell_version="9.9.9",
                       serving=lambda: True, supervisor_alive=lambda: True)
    assert res.status == "deferred" and res.exit_code == 3, res.to_dict()
    assert "ChampSelect" in res.detail


def test_r7_a_failing_completion_backs_off_then_asks_for_attention(tmp_path, monkeypatch):
    root = _applied(tmp_path)
    st = up.read_state(root)
    up._write_state(root, dict(st, recovering={"version": "1.1.0", "kinds": [], "requests": None}))

    def boom(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(uc.up, "recover", boom)
    t = [1e6]
    codes = []
    for _ in range(uc.RECOVER_ATTENTION_AFTER):
        res = uc.resume_cycle(root, clock=Clock(), sleep=lambda s: None, now=lambda: t[0],
                              supervisor_alive=lambda: True)
        codes.append(res.code)
        assert res.status == "failed" and res.exit_code == 1
        doc = uc.read_cycle(root)
        assert doc["retry_after"] > t[0], "backs off"
        t[0] = doc["retry_after"] + 1
    assert codes[0] == "recover_failed" and codes[-1] == "recovery_attention"


def test_f7_a_deferred_reload_is_not_quiet(tmp_path):
    root, src = _setup(tmp_path)
    _fresh_watcher(root)
    clock = Clock()

    def deferred():
        (root / "ops" / "runtime" / "hot_reload.json").write_text(json.dumps({
            "watching": True, "pending": ["core/a.py"], "last_change": "2026-10-26T12:00:00",
            "last_compile": "DEFERRED (game in progress)"}), encoding="ascii")
    sim = Sim(root, clock, after_worker=deferred)
    res = _cycle(root, src, clock, sim, Script(clock, lambda t: sample("r1")))
    assert res.status == "deferred" and res.exit_code == 3, res.to_dict()
    assert uc.read_cycle(root)["verify"]["reload_deferred"] is True

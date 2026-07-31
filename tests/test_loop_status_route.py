# arch: tests for GET /api/loop-status (headless-loop status surface) | section=tests | frozen=no
"""Characterization + behavior tests for dashboard.routes_loop_status.

The route is a thin, read-only aggregator over the headless-loop control
files (ops/loop/control/*) + the last git commit. It must be fail-soft per
source (a missing/corrupt file never raises), derive a 3-way state
(stopped/running/idle), and prefer the live claude.done sentinel over the
controller.log fallback for the last-cycle summary.

All file IO is redirected at module-level Path constants so these tests touch
only a tmp dir; the single git call is monkeypatched.
"""
from __future__ import annotations

import json
import os
import time

import pytest

from dashboard import routes_loop_status as mod


class FakeHandler:
    """Minimal StubHandler stand-in capturing the _send(status, body, ctype)."""

    def __init__(self, path: str = "/api/loop-status") -> None:
        self.path = path
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)


@pytest.fixture
def loopdir(tmp_path, monkeypatch):
    """Point the route's control-dir / config / log at a tmp sandbox."""
    ctl = tmp_path / "control"
    ctl.mkdir()
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(mod, "CONTROL_DIR", ctl)
    monkeypatch.setattr(mod, "CONFIG_PATH", cfg)
    monkeypatch.setattr(mod, "CONTROLLER_LOG", ctl / "controller.log")
    # Deterministic git seam so last_commit never shells out in tests.
    monkeypatch.setattr(mod, "_last_commit", lambda: {
        "sha": "deadbeef", "subject": "test commit", "iso": "2026-06-07T00:00:00-05:00",
    })
    return ctl, cfg


def _serve(handler):
    mod._serve_loop_status(handler)
    assert handler.sent is not None
    status, body, ctype = handler.sent
    return status, json.loads(body.decode("utf-8")), ctype


# --------------------------------------------------------------------------- state
def test_stopped_when_stop_file_present(loopdir):
    ctl, cfg = loopdir
    (ctl / "STOP").write_text("max_cycles 10 reached", encoding="utf-8")
    (ctl / "cycle.txt").write_text("10", encoding="utf-8")
    (ctl / "ahk_mode.txt").write_text("live\n", encoding="utf-8")
    cfg.write_text(json.dumps({"max_cycles": 24}), encoding="utf-8")

    status, body, ctype = _serve(FakeHandler())
    assert status == 200
    assert ctype == "application/json"
    assert body["ok"] is True
    assert body["state"] == "stopped"
    assert body["stop_reason"] == "max_cycles 10 reached"
    assert body["cycle"] == 10
    assert body["max_cycles"] == 24
    assert body["mode"] == "live"


def test_running_when_cycle_present_and_no_stop(loopdir):
    ctl, _ = loopdir
    (ctl / "cycle.txt").write_text("3", encoding="utf-8")
    _, body, _ = _serve(FakeHandler())
    assert body["state"] == "running"
    assert body["cycle"] == 3
    assert body["stop_reason"] is None


def test_idle_when_nothing_present(loopdir):
    _, body, _ = _serve(FakeHandler())
    assert body["ok"] is True
    assert body["state"] == "idle"
    assert body["cycle"] is None
    assert body["last_done"] is None
    assert body["budget"] is None


# --------------------------------------------------------------------------- budget
def test_budget_parsed(loopdir):
    ctl, _ = loopdir
    (ctl / "budget.json").write_text(json.dumps({
        "gemini_usd": 0.0, "gemini_ceiling": 999.0,
        "claude_usd_info": 26.1447, "cycle": 10,
    }), encoding="utf-8")
    _, body, _ = _serve(FakeHandler())
    assert body["budget"]["claude_usd_info"] == 26.1447
    assert body["budget"]["gemini_ceiling"] == 999.0
    assert body["budget"]["cycle"] == 10


def test_malformed_budget_is_failsoft(loopdir):
    ctl, _ = loopdir
    (ctl / "budget.json").write_text("{not json", encoding="utf-8")
    status, body, _ = _serve(FakeHandler())
    assert status == 200
    assert body["ok"] is True
    assert body["budget"] is None


# --------------------------------------------------------------------------- last_done
def test_last_done_prefers_sentinel(loopdir):
    ctl, _ = loopdir
    (ctl / "claude.done").write_text(json.dumps({
        "cycle": 10, "sha": "38158e1d0011223344", "tests_pass": 7024,
        "regressions": False, "ts": 1717000000.0,
    }), encoding="utf-8")
    # A log line that should be IGNORED because the sentinel wins.
    (ctl / "controller.log").write_text(
        "2026-06-07T10:38:03 cycle 9: claude.done sha=aaaaaaaa tests=1 regress=True\n",
        encoding="utf-8")
    _, body, _ = _serve(FakeHandler())
    ld = body["last_done"]
    assert ld["source"] == "sentinel"
    assert ld["cycle"] == 10
    assert ld["sha"] == "38158e1d"  # truncated to 8
    assert ld["tests_pass"] == 7024
    assert ld["regressions"] is False


def test_last_done_falls_back_to_log(loopdir):
    ctl, _ = loopdir
    (ctl / "controller.log").write_text(
        "2026-06-07T09:00:00 cycle 8: claude.done sha=11111111 tests=10 regress=False\n"
        "2026-06-07T10:38:03 cycle 10: claude.done sha=38158e1d tests=7024 regress=False\n"
        "2026-06-07T10:38:03 STOP written: max_cycles 10 reached\n",
        encoding="utf-8")
    _, body, _ = _serve(FakeHandler())
    ld = body["last_done"]
    assert ld["source"] == "log"
    assert ld["cycle"] == 10
    assert ld["sha"] == "38158e1d"
    assert ld["tests_pass"] == "7024"  # log values stay strings
    assert ld["regressions"] is False


# --------------------------------------------------------------------------- last_commit + log tail
def test_last_commit_passthrough(loopdir):
    _, body, _ = _serve(FakeHandler())
    assert body["last_commit"] == {
        "sha": "deadbeef", "subject": "test commit",
        "iso": "2026-06-07T00:00:00-05:00",
    }


def test_last_commit_suppresses_console_window(monkeypatch):
    """Regression: the git subprocess must pass CREATE_NO_WINDOW so pythonw does
    not pop a console window on every 4s loop-monitor poll (focus-steal bug)."""
    captured = {}

    class _Done:
        stdout = "abc1234\x1fsubject here\x1f2026-06-20T00:00:00-05:00"

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _Done()

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    result = mod._last_commit()
    assert result == {
        "sha": "abc1234", "subject": "subject here",
        "iso": "2026-06-20T00:00:00-05:00",
    }
    assert "creationflags" in captured["kwargs"]
    assert captured["kwargs"]["creationflags"] == mod._NO_WINDOW
    if os.name == "nt":
        assert mod._NO_WINDOW == 0x08000000  # CREATE_NO_WINDOW


def test_log_tail_is_last_lines(loopdir):
    ctl, _ = loopdir
    lines = [f"line {i}" for i in range(40)]
    (ctl / "controller.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _, body, _ = _serve(FakeHandler())
    tail = body["log_tail"]
    assert tail[-1] == "line 39"
    assert len(tail) <= mod.LOG_TAIL_LINES


def test_last_commit_failsoft_when_git_raises(loopdir, monkeypatch):
    def _boom():
        raise RuntimeError("git missing")
    monkeypatch.setattr(mod, "_last_commit", _boom)
    status, body, _ = _serve(FakeHandler())
    assert status == 200
    assert body["ok"] is True
    assert body["last_commit"] is None


# --------------------------------------------------------------------------- lock states (Mission Control S4)
# Both lock blocks answer FREE / RUNNING / RECLAIMABLE and both decide by
# PROBING the pid. The whole point of the third state is that a dead holder is
# indistinguishable from a live one by file inspection alone, so the tests that
# matter are the ones asserting RECLAIMABLE is NOT reported as RUNNING.
import importlib as _importlib

_lanes_mod = _importlib.import_module("ops.loop.lanes")


def _dead_pid() -> int:
    """A pid that is provably not running.

    Picked by probing rather than hard-coding: a hard-coded 'obviously dead' pid
    can be recycled by the OS and the test then silently asserts the opposite of
    what it claims.
    """
    for candidate in range(999000, 999200):
        if not _lanes_mod.slots.pid_alive(candidate):
            return candidate
    raise AssertionError("no dead pid found in the probe range")


@pytest.fixture
def lanesdir(tmp_path, monkeypatch):
    """Redirect the lane-lock root at a tmp dir (production leaves it None)."""
    root = tmp_path / "lanes"
    monkeypatch.setattr(mod, "LANES_ROOT", root)
    return root


def _write_lock(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_lanes_free_when_no_lock_exists(loopdir, lanesdir):
    status, body, _ = _serve(FakeHandler())
    assert status == 200
    assert body["lanes"]["state"] == "FREE"
    assert body["lanes"]["lane"] is None
    assert not lanesdir.exists(), "reading the lane state must not create the dir"


def test_lanes_running_for_a_live_pid(loopdir, lanesdir):
    _write_lock(lanesdir / "0.lock", {
        "pid": os.getpid(), "lane": "uiux", "run_id": "abc123",
        "worktree": r"C:\wt\uiux", "ts": time.time(),
    })
    _, body, _ = _serve(FakeHandler())
    assert body["lanes"]["state"] == "RUNNING"
    assert body["lanes"]["lane"] == "uiux"
    assert body["lanes"]["run_id"] == "abc123"


def test_lanes_reclaimable_for_a_dead_pid_never_running(loopdir, lanesdir):
    _write_lock(lanesdir / "0.lock", {
        "pid": _dead_pid(), "lane": "ds", "run_id": "gone",
        "worktree": r"C:\wt\ds", "ts": time.time(),
    })
    _, body, _ = _serve(FakeHandler())
    assert body["lanes"]["state"] == "RECLAIMABLE"
    assert body["lanes"]["state"] != "RUNNING"


def test_lanes_failsoft_when_the_module_is_unavailable(loopdir, monkeypatch):
    def _boom():
        raise ModuleNotFoundError("ops.loop.lanes")
    monkeypatch.setattr(mod, "_lanes", _boom)
    status, body, _ = _serve(FakeHandler())
    assert status == 200
    assert body["ok"] is True
    assert body["lanes"] is None
    assert body["controller_lock"] is None


def test_controller_lock_free_when_absent(loopdir, lanesdir):
    _, body, _ = _serve(FakeHandler())
    assert body["controller_lock"]["state"] == "FREE"
    assert body["controller_lock"]["pid"] is None


def test_controller_lock_running_for_a_live_pid(loopdir, lanesdir):
    ctl, _cfg = loopdir
    _write_lock(ctl / "RUNNING.lock", {
        "pid": os.getpid(), "run_id": "live01", "ts": time.time(),
        "repo": r"C:\Riot Commander",
    })
    _, body, _ = _serve(FakeHandler())
    assert body["controller_lock"]["state"] == "RUNNING"
    assert body["controller_lock"]["run_id"] == "live01"


def test_controller_lock_reclaimable_for_a_dead_pid(loopdir, lanesdir):
    # The live 2026-07-30 case: RUNNING.lock held pid 9380, long gone. Every
    # reader that treated EXISTENCE as RUNNING reported a loop that was not
    # there.
    ctl, _cfg = loopdir
    _write_lock(ctl / "RUNNING.lock", {
        "pid": _dead_pid(), "run_id": "eadf15e3", "ts": time.time() - 100,
        "repo": r"C:\Riot Commander",
    })
    _, body, _ = _serve(FakeHandler())
    assert body["controller_lock"]["state"] == "RECLAIMABLE"
    assert body["controller_lock"]["pid"] == _dead_pid()


def test_controller_lock_path_follows_the_patched_control_dir(loopdir, lanesdir):
    ctl, _cfg = loopdir
    assert mod.controller_lock_path() == ctl / "RUNNING.lock"


def test_controller_lock_unparseable_is_presumed_live_inside_the_grace_window(
        loopdir, lanesdir):
    ctl, _cfg = loopdir
    (ctl / "RUNNING.lock").write_text("", encoding="utf-8")
    _, body, _ = _serve(FakeHandler())
    assert body["controller_lock"]["state"] == "RUNNING"


def test_controller_lock_unparseable_past_the_grace_window_is_reclaimable(
        loopdir, lanesdir, monkeypatch):
    ctl, _cfg = loopdir
    lock = ctl / "RUNNING.lock"
    lock.write_text("", encoding="utf-8")
    old = time.time() - (_lanes_mod.WRITE_GRACE_S + 60)
    os.utime(lock, (old, old))
    _, body, _ = _serve(FakeHandler())
    assert body["controller_lock"]["state"] == "RECLAIMABLE"


# --------------------------------------------------------------------------- no writes on the poll path
def _tree(root):
    """Every path under `root` with its size + mtime - a write-detecting print."""
    out = {}
    for path in sorted(root.rglob("*")):
        st = path.stat()
        out[str(path.relative_to(root))] = (path.is_dir(), st.st_size, st.st_mtime_ns)
    return out


def test_poll_path_writes_nothing(loopdir, lanesdir):
    """The dashboard polls this every 4s. A render must never mutate control/.

    Auto-clearing a stale lock inside a read would make two pollers race each
    other into a reclaim, so reclaiming lives in try_acquire_lane alone.
    """
    ctl, _cfg = loopdir
    (ctl / "cycle.txt").write_text("7", encoding="utf-8")
    _write_lock(ctl / "RUNNING.lock", {
        "pid": _dead_pid(), "run_id": "stale", "ts": time.time() - 500,
    })
    _write_lock(lanesdir / "0.lock", {
        "pid": _dead_pid(), "lane": "repo", "run_id": "stale-lane",
        "worktree": r"C:\wt\repo", "ts": time.time() - 500,
    })
    before_ctl, before_lanes = _tree(ctl), _tree(lanesdir)

    for _ in range(3):
        _, body, _ = _serve(FakeHandler())
    # Both stale locks are still RECLAIMABLE, i.e. reported and NOT reaped.
    assert body["controller_lock"]["state"] == "RECLAIMABLE"
    assert body["lanes"]["state"] == "RECLAIMABLE"
    assert _tree(ctl) == before_ctl, "the poll path mutated the control dir"
    assert _tree(lanesdir) == before_lanes, "the poll path mutated the lane dir"


def test_poll_does_not_create_the_lane_dir(loopdir, tmp_path, monkeypatch):
    missing = tmp_path / "never-created"
    monkeypatch.setattr(mod, "LANES_ROOT", missing)
    _serve(FakeHandler())
    assert not missing.exists()


# --------------------------------------------------------------------------- S1/S2/S4 seam
def test_status_and_control_share_one_lane_root(tmp_path, monkeypatch):
    """The `root=` default must resolve identically on both sides of the seam.

    Flagged unpinned in docs/MISSION_CONTROL_PLAN.md: POST /api/loop-control
    fires with no `root=` and GET /api/loop-status reads with no `root=`. If the
    two ever resolve differently the mismatch is SILENT, because each side
    passes its own stubs. This exercises the REAL pair - only `DEFAULT_ROOT` is
    redirected, and it is redirected once, for both.
    """
    from dashboard import routes_loop_control as ctlmod

    monkeypatch.setattr(_lanes_mod, "DEFAULT_ROOT", tmp_path / "lanes")
    monkeypatch.setattr(mod, "LANES_ROOT", None)      # production value
    monkeypatch.setattr(mod, "_last_commit", lambda: None)

    # S5 made a successful claim LAUNCH. This test is about the lock root, so
    # the launcher is stubbed - it must not build a worktree or spawn anything.
    class _StubLauncher:
        @staticmethod
        def worktree_path(lane):
            return tmp_path / "wt" / lane

        @staticmethod
        def launch_lane(lane, *, run_id, token, **kw):
            return {"pid": os.getpid(), "worktree": str(tmp_path / "wt" / lane),
                    "log": str(tmp_path / "lane.log")}

    monkeypatch.setattr(ctlmod, "_launcher", lambda: _StubLauncher)

    status, payload = ctlmod.apply_action("fire_lane", {
        "lane": "uiux",
        "run_id": "seam-test",
        "worktree": str(tmp_path / "wt"),
        "idempotency_key": "aaaaaaaa-bbbb-cccc-dddd-000000000001",
    })
    assert status == 200 and payload["ok"] is True, payload
    token = payload["token"]
    try:
        lanes_block = mod.build_loop_status()["lanes"]
        assert lanes_block["state"] == "RUNNING", (
            "status read a different lane root than control wrote")
        assert lanes_block["lane"] == "uiux"
        assert lanes_block["run_id"] == "seam-test"
    finally:
        _lanes_mod.release_lane(token)

    assert mod.build_loop_status()["lanes"]["state"] == "FREE"


# --------------------------------------------------------------------------- registration
def test_route_registered():
    from dashboard._dispatch import equals  # noqa: F401
    paths = [m for m, _ in mod.GET_ROUTES]
    assert any(matcher("/api/loop-status") for matcher in paths)
    assert mod.POST_ROUTES == []

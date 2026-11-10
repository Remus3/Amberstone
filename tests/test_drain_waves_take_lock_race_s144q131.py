"""S144-Q-131: ops/loop/drain_waves_2_3.py launcher lock - break and release by bytes.

Same root cause as RM-691 (ops/loop/inbox_tick.py) and S144-Q-132
(agents/_supervisor_common.py): `_take_lock` judged a lock stale from one read
of its pid, then unlinked the lock BY PATH. A second launcher that broke the
same stale lock first and re-created it in between lost its fresh lock, so both
launchers ran. An EMPTY lock (a claim between its O_EXCL create and its pid
write) read as pid 0 and was broken at once. `run()` released the lock by path
too, so a launcher whose lock had been broken deleted the next owner's lock.

These pin: the break removes only the bytes it read, a young empty lock is a
claim in flight and is refused, an old empty lock is reclaimed, and the release
removes only this launcher's own claim. Synthetic pids only; every path is
under tmp_path.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ops" / "loop" / "drain_waves_2_3.py"

DEAD_PID = 999_999_001  # synthetic; _pid_alive is stubbed, never probed live


@pytest.fixture
def dw(tmp_path, monkeypatch):
    name = "drain_waves_2_3_lock_under_test"
    spec = importlib.util.spec_from_file_location(name, SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "LOCK", tmp_path / "runtime" / "drain_waves_2_3.lock")
    monkeypatch.setattr(mod, "WT_BASE", tmp_path / "wt")
    monkeypatch.setattr(mod, "DRAIN_DIR", tmp_path / "drain")
    monkeypatch.setattr(mod, "PROGRESS_ROOT", tmp_path)
    monkeypatch.setattr(mod, "LOG", tmp_path / "drain.log")
    monkeypatch.setattr(mod, "RESULT", tmp_path / "result.json")
    monkeypatch.setattr(mod, "STOP_FILE", tmp_path / "DRAIN_STOP")
    yield mod
    sys.modules.pop(name, None)


def _alive_except(dead: set):
    return lambda pid: pid not in dead


def test_break_keeps_a_fresh_lock_another_launcher_made_since_the_read(dw, monkeypatch):
    """The RM-691 interleave: B reads a dead launcher's lock, C breaks it and
    takes a fresh one, then B acts on what it read. B must not take C's lock."""
    dw.LOCK.parent.mkdir(parents=True)
    dw.LOCK.write_bytes(str(DEAD_PID).encode("ascii"))
    results = {}
    state = {"interleaved": False}

    def pid_alive(pid):
        if pid == DEAD_PID and not state["interleaved"]:
            state["interleaved"] = True
            results["c"] = dw._take_lock()  # C runs whole inside B's window
            return False
        return pid != DEAD_PID

    monkeypatch.setattr(dw, "_pid_alive", pid_alive)
    results["b"] = dw._take_lock()
    assert state["interleaved"]
    assert results["c"], "C broke the dead launcher's lock and took a fresh one"
    assert not results["b"], "B deleted C's fresh lock and took it: two launchers"
    assert dw.LOCK.read_bytes() == results["c"]
    leftovers = sorted(p.name for p in dw.LOCK.parent.iterdir())
    assert leftovers == [dw.LOCK.name], leftovers


def test_young_empty_lock_is_a_claim_in_flight_and_is_refused(dw, monkeypatch):
    monkeypatch.setattr(dw, "_pid_alive", _alive_except(set()))
    dw.LOCK.parent.mkdir(parents=True)
    dw.LOCK.write_bytes(b"")
    assert not dw._take_lock()
    assert dw.LOCK.read_bytes() == b"", "an in-flight claim was broken"


def test_old_empty_lock_is_reclaimed(dw, monkeypatch):
    monkeypatch.setattr(dw, "_pid_alive", _alive_except(set()))
    dw.LOCK.parent.mkdir(parents=True)
    dw.LOCK.write_bytes(b"")
    old = time.time() - dw.EMPTY_LOCK_GRACE_S - 60
    os.utime(dw.LOCK, (old, old))
    claim = dw._take_lock()
    assert claim and dw.LOCK.read_bytes() == claim


def test_pid_only_lock_of_a_live_launcher_is_refused(dw, monkeypatch):
    monkeypatch.setattr(dw, "_pid_alive", _alive_except({DEAD_PID}))
    dw.LOCK.parent.mkdir(parents=True)
    dw.LOCK.write_bytes(b"4242")
    assert not dw._take_lock()
    assert dw.LOCK.read_bytes() == b"4242"


def test_pid_only_lock_of_a_dead_launcher_is_reclaimed(dw, monkeypatch):
    monkeypatch.setattr(dw, "_pid_alive", _alive_except({DEAD_PID}))
    dw.LOCK.parent.mkdir(parents=True)
    dw.LOCK.write_bytes(str(DEAD_PID).encode("ascii"))
    claim = dw._take_lock()
    assert claim and dw.LOCK.read_bytes() == claim
    assert dw._lock_pid(claim) == os.getpid()


def test_each_take_writes_a_distinct_claim(dw, monkeypatch):
    monkeypatch.setattr(dw, "_pid_alive", _alive_except(set()))
    first = dw._take_lock()
    dw._drop_lock(first)
    assert not dw.LOCK.exists()
    second = dw._take_lock()
    assert first and second and first != second


def test_drop_leaves_a_lock_another_launcher_holds(dw, monkeypatch):
    monkeypatch.setattr(dw, "_pid_alive", _alive_except(set()))
    mine = dw._take_lock()
    theirs = b"4242 feedfacecafebeef"
    dw.LOCK.write_bytes(theirs)
    dw._drop_lock(mine)
    assert dw.LOCK.read_bytes() == theirs


def test_drop_ignores_a_non_claim(dw):
    dw.LOCK.parent.mkdir(parents=True)
    dw.LOCK.write_bytes(b"4242")
    dw._drop_lock(None)
    dw._drop_lock(True)  # the shape a test stand-in for _take_lock returns
    assert dw.LOCK.read_bytes() == b"4242"


def test_run_releases_only_its_own_claim(dw, monkeypatch):
    """run()'s finally used to unlink the lock by path: a launcher whose lock
    was broken meanwhile deleted the next launcher's lock."""
    monkeypatch.setattr(dw, "_pid_alive", _alive_except(set()))
    monkeypatch.setenv("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", "0")  # restored at teardown
    theirs = b"4242 0123456789abcdef"

    def fleet_route():
        dw.LOCK.write_bytes(theirs)  # broken and re-taken by another launcher
        raise RuntimeError("stop here")

    monkeypatch.setattr(dw, "_fleet_route", fleet_route)
    monkeypatch.setattr(
        dw, "_git",
        lambda *a, **k: __import__("subprocess").CompletedProcess(["git"], 0, "abc\n", ""))
    rc = dw.run(dw.select_waves("3", None))
    assert rc == 1
    assert dw.LOCK.read_bytes() == theirs


def test_run_releases_its_own_claim(dw, monkeypatch):
    monkeypatch.setattr(dw, "_pid_alive", _alive_except(set()))
    monkeypatch.setenv("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", "0")

    def fleet_route():
        assert dw.LOCK.exists()
        raise RuntimeError("stop here")

    monkeypatch.setattr(dw, "_fleet_route", fleet_route)
    monkeypatch.setattr(
        dw, "_git",
        lambda *a, **k: __import__("subprocess").CompletedProcess(["git"], 0, "abc\n", ""))
    assert dw.run(dw.select_waves("3", None)) == 1
    assert not dw.LOCK.exists()

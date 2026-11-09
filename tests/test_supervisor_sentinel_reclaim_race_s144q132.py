"""S144-Q-132 - two supervisor starters that both find a STALE sentinel cannot
both hold the singleton, and a stopping supervisor removes only its own claim.

Root cause (agents/_supervisor_common.py acquire_lock before this row): after
the O_EXCL create failed, acquire_lock read the sentinel's pid, and when that
pid was dead it unlinked the sentinel BY PATH and retried O_EXCL. Starter A
could reclaim the stale sentinel and create its own fresh one between starter
B's read and B's unlink, so B deleted A's FRESH claim, created its own, and
both ran as the supervisor. The same shape as RM-691 (ops/loop/inbox_tick.py),
fixed the same way: the break removes the sentinel only while it still holds
the bytes the starter READ (rename aside, compare, delete or put back).

Same root, second door: an EMPTY sentinel parsed as pid 0 and was reclaimed at
once, but an empty sentinel is also what a live starter's claim looks like
between its O_EXCL create and its pid write. A young empty sentinel is now a
claim in flight (refused); an old one is a crashed claim (reclaimed).

Release: Supervisor.stop unlinked the lock pair by path with no owner check.
It now removes the sentinel only while it holds this process's pid, and the
lockfile only while its pid is this process's.

The interleave runs through the `_pid_alive` seam: acquire_lock calls it after
it has read the sentinel, so the stub runs starter A in full inside B's
window. Every lock file is under tmp_path; the live agents/state/ is never
read or written.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from agents import _supervisor_common as common
from agents import supervisor as sup_mod
from agents.supervisor import Supervisor
from tests._asyncio_isolation import run_coro as _run_coro

DEAD = 999999991
A_PID = 999999992


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Relocate the lock pair (both module namespaces) into tmp_path."""
    st = tmp_path / "state"
    st.mkdir()
    for mod in (common, sup_mod):
        monkeypatch.setattr(mod, "STATE_DIR", st, raising=False)
        monkeypatch.setattr(mod, "LOCKFILE", st / "lockfile", raising=False)
    monkeypatch.setattr(common, "_LOCK_OWNER_PID", None, raising=False)
    monkeypatch.setattr(common, "_LOCK_OWNER_SENTINEL", None, raising=False)
    monkeypatch.setattr(common, "_reap_orphan_lockfile_tmps", lambda: None)
    return st


def _sentinel(st: Path) -> Path:
    return st / "lockfile.sentinel"


def _side_files(st: Path) -> list[str]:
    """Anything a break or a release left beside the lock pair."""
    return sorted(p.name for p in st.iterdir()
                  if p.name not in ("lockfile", "lockfile.sentinel"))


def _mine() -> bytes:
    return str(os.getpid()).encode("ascii")


# ---------------------------------------------------------------------------
# acquire: the reclaim race
# ---------------------------------------------------------------------------

def test_a_starter_never_deletes_a_fresh_claim_made_inside_its_window(
        state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = _sentinel(state)
    sentinel.write_bytes(str(DEAD).encode("ascii"))
    fired: list[int] = []

    def _alive_runs_starter_a(pid: int) -> bool:
        # B has read the stale sentinel. Starter A now reclaims it in full:
        # removes the dead claim and O_EXCL-creates its own live one.
        if not fired:
            fired.append(pid)
            sentinel.unlink()
            fd = os.open(str(sentinel), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "wb") as fh:
                fh.write(str(A_PID).encode("ascii"))
        return False  # the pid B read (DEAD) is dead

    monkeypatch.setattr(common, "_pid_alive", _alive_runs_starter_a)

    won = common.acquire_lock()

    assert fired == [DEAD], "the interleave did not run - the seam moved"
    assert won is False, "B won while A held a fresh claim: two supervisors"
    assert sentinel.read_bytes() == str(A_PID).encode("ascii")
    assert common._LOCK_OWNER_PID is None
    assert _side_files(state) == []


def test_a_dead_pid_sentinel_is_still_reclaimed(
        state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = _sentinel(state)
    sentinel.write_bytes(str(DEAD).encode("ascii"))
    monkeypatch.setattr(common, "_pid_alive", lambda pid: pid == os.getpid())

    assert common.acquire_lock() is True
    assert sentinel.read_bytes() == _mine()
    assert common._LOCK_OWNER_PID == os.getpid()
    assert json.loads((state / "lockfile").read_text("utf-8"))["pid"] == os.getpid()
    assert _side_files(state) == []


def test_a_young_empty_sentinel_is_a_claim_in_flight_not_stale(
        state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = _sentinel(state)
    sentinel.write_bytes(b"")  # a starter between its O_EXCL and its write
    monkeypatch.setattr(common, "_pid_alive", lambda pid: pid == os.getpid())

    assert common.acquire_lock() is False
    assert sentinel.exists() and sentinel.read_bytes() == b""
    assert common._LOCK_OWNER_PID is None
    assert _side_files(state) == []


def test_an_old_empty_sentinel_is_a_crashed_claim_and_is_reclaimed(
        state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = _sentinel(state)
    sentinel.write_bytes(b"")
    old = time.time() - 10 * common.EMPTY_SENTINEL_GRACE_S
    os.utime(sentinel, (old, old))
    monkeypatch.setattr(common, "_pid_alive", lambda pid: pid == os.getpid())

    assert common.acquire_lock() is True
    assert sentinel.read_bytes() == _mine()
    assert _side_files(state) == []


def test_a_sentinel_released_before_the_read_is_won_by_the_retry(
        state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The holder releases between B's failed O_EXCL and B's read: B wins
    with a fresh create, as before."""
    sentinel = _sentinel(state)
    sentinel.write_bytes(str(DEAD).encode("ascii"))
    real_read = Path.read_bytes

    def _gone_then_read(self: Path) -> bytes:
        if self == sentinel and sentinel.exists():
            sentinel.unlink()
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", _gone_then_read)
    monkeypatch.setattr(common, "_pid_alive", lambda pid: pid == os.getpid())

    assert common.acquire_lock() is True
    monkeypatch.undo()
    assert sentinel.read_bytes() == _mine()


def test_remove_if_holds_keeps_a_changed_file(tmp_path: Path) -> None:
    target = tmp_path / "lockfile.sentinel"
    target.write_bytes(b"123")
    assert common._remove_if_holds(target, b"456") is False
    assert target.read_bytes() == b"123"
    assert common._remove_if_holds(target, b"123") is True
    assert not target.exists()
    assert common._remove_if_holds(target, b"123") is True  # already gone
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# release: Supervisor.stop removes only its own claim
# ---------------------------------------------------------------------------

def test_stop_leaves_another_supervisors_lock_pair_alone(state: Path) -> None:
    sentinel = _sentinel(state)
    sentinel.write_bytes(str(A_PID).encode("ascii"))
    lockfile = state / "lockfile"
    lockfile.write_text(json.dumps({"pid": A_PID}), encoding="utf-8")

    _run_coro(Supervisor().stop())

    assert sentinel.read_bytes() == str(A_PID).encode("ascii")
    assert json.loads(lockfile.read_text("utf-8")) == {"pid": A_PID}
    assert _side_files(state) == []


def test_stop_removes_its_own_lock_pair(state: Path) -> None:
    sentinel = _sentinel(state)
    sentinel.write_bytes(_mine())
    lockfile = state / "lockfile"
    lockfile.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

    _run_coro(Supervisor().stop())

    assert not sentinel.exists()
    assert not lockfile.exists()
    assert _side_files(state) == []


def test_release_keeps_a_foreign_sentinel_but_drops_its_own_lockfile(
        state: Path) -> None:
    """The two files are judged separately: each goes only on its own pid."""
    sentinel = _sentinel(state)
    sentinel.write_bytes(str(A_PID).encode("ascii"))
    lockfile = state / "lockfile"
    lockfile.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

    common.release_lock_files()

    assert sentinel.read_bytes() == str(A_PID).encode("ascii")
    assert not lockfile.exists()

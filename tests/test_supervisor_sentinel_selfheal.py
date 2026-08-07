"""RM-173 - the supervisor singleton lock must self-heal its sentinel.

THE DEFECT (measured live on Legion, 2026-08-06). The Phase 3 supervisor
singleton lock is two files:

* ``agents/state/lockfile``           - human/watcher-readable JSON metadata,
  re-stamped every 5s by ``refresh_lock`` (agents/_supervisor_common.py:405).
* ``agents/state/lockfile.sentinel``  - the ACTUAL atomic claim. Created with
  ``os.open(..., O_CREAT|O_EXCL|O_WRONLY)`` in ``acquire_lock``
  (agents/_supervisor_common.py:328 and the reclaim retry at :353), holding a
  BARE ASCII DECIMAL pid with no newline and no JSON.

Only the first of those was re-asserted by the heartbeat. ``Supervisor.stop``
removes BOTH (agents/supervisor.py:400-404) - which is CORRECT release
semantics and is NOT the bug - but so does any other path that clears state
under a live daemon. When that happened the sentinel was simply gone from
02:54 to 20:44 while pid 17836 heartbeated normally and every health signal
read green: the singleton was disarmed for 18 hours with no signal anywhere.

THE FIX UNDER TEST: ``refresh_lock`` re-asserts the sentinel when it is
missing AND this process is the one that won the lock.

THE SHARP EDGE, and why these tests pin BOTH directions. The failure modes are
asymmetric. A DEAD pid in the sentinel is no worse than an absent one - the
next boot reclaims it either way (``acquire_lock`` :342-358). But a LIVE pid
belonging to some OTHER process is far WORSE than absent: reclaim only fires
when the recorded owner is dead, so a wrongly-written live pid wedges every
future legitimate start permanently. The self-heal therefore must never be
able to write a pid that is not this process's own, and must never overwrite
a sentinel it did not create.

Symbols grep-confirmed against the live tree before use:
  _supervisor_common.STATE_DIR                  (_supervisor_common.py:50)
  _supervisor_common.LOCKFILE                   (_supervisor_common.py:51)
  _supervisor_common.acquire_lock               (_supervisor_common.py:307)
  _supervisor_common.refresh_lock               (_supervisor_common.py:405)
  _supervisor_common._pid_alive                 (_supervisor_common.py:264)
  _supervisor_common._atomic_write_json         (_supervisor_common.py:229)
  agents.supervisor.Supervisor.stop unlink pair (supervisor.py:400-404)

ISOLATION. Every fixture writes to a pytest ``tmp_path``. Nothing here may
touch the real ``agents/state/`` - a live supervisor owns it. ``STATE_DIR``
resolves at IMPORT time from ``RC_PHASE3_STATE_DIR`` (RM-170), so the env
override only relocates a CHILD process; for an in-process unit test the
module constants are still the load-bearing seam and monkeypatching them is
required, not optional.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agents import _supervisor_common as common


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _point_state_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Relocate the lock pair into ``tmp_path`` and return that state dir."""
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(common, "STATE_DIR", state)
    monkeypatch.setattr(common, "LOCKFILE", state / "lockfile")
    # Default: this process is NOT the lock owner. Tests opt in explicitly.
    monkeypatch.setattr(common, "_LOCK_OWNER_PID", None, raising=False)
    # The repair counter is a PROCESS global (deliberately cumulative in the
    # daemon); zero it per test or one test's repair leaks into the next
    # assertion about the healthy-payload key set.
    monkeypatch.setattr(common, "_SENTINEL_REPAIRS", 0, raising=False)
    return state


def _claim(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mark this process as the winner of the lock, as acquire_lock does."""
    monkeypatch.setattr(common, "_LOCK_OWNER_PID", os.getpid(), raising=False)


class _LiveChild:
    """A genuinely running foreign process, for the never-overwrite proof.

    A hand-picked integer is not enough: the guard has to be exercised against
    a pid that ``_pid_alive`` really answers True for.
    """

    def __init__(self) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    @property
    def pid(self) -> int:
        return int(self._proc.pid)

    def close(self) -> None:
        # CLAUDE.md hard rule: never Stop-Process. taskkill on Windows.
        if sys.platform.startswith("win"):
            subprocess.run(
                ["taskkill", "/F", "/PID", str(self._proc.pid)],
                capture_output=True, timeout=10,
            )
        else:
            self._proc.kill()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


@pytest.fixture
def live_foreign_pid():
    child = _LiveChild()
    try:
        assert common._pid_alive(child.pid), "fixture child is not alive"
        yield child.pid
    finally:
        child.close()


# ---------------------------------------------------------------------------
# direction 1 - it MUST repair when this process owns the lock
# ---------------------------------------------------------------------------

def test_refresh_lock_reasserts_missing_sentinel_for_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One heartbeat restores a sentinel deleted under the running owner."""
    state = _point_state_at(tmp_path, monkeypatch)
    _claim(monkeypatch)
    sentinel = state / "lockfile.sentinel"
    assert not sentinel.exists()

    common.refresh_lock()

    assert sentinel.exists(), "heartbeat did not re-arm the singleton sentinel"
    # Byte format is load-bearing: acquire_lock parses it with
    # int(read_text(encoding='ascii').strip()). Bare decimal, no newline,
    # no JSON - exactly what os.write(fd, str(pid).encode('ascii')) produces.
    raw = sentinel.read_bytes()
    assert raw == str(os.getpid()).encode("ascii")
    assert b"\n" not in raw and b"{" not in raw


def test_reasserted_sentinel_is_parseable_by_acquire_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The repaired sentinel must read back through acquire_lock's own parse.

    Pins the contract at the consumer rather than restating the byte format:
    a repaired sentinel that acquire_lock cannot parse degrades to pid 0,
    which is silently reclaimable and defeats the whole singleton.
    """
    state = _point_state_at(tmp_path, monkeypatch)
    _claim(monkeypatch)

    common.refresh_lock()

    sentinel = state / "lockfile.sentinel"
    assert int(sentinel.read_text(encoding="ascii").strip() or "0") == os.getpid()


def test_repair_is_idempotent_across_heartbeats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated heartbeats neither rewrite nor churn an intact sentinel."""
    state = _point_state_at(tmp_path, monkeypatch)
    _claim(monkeypatch)
    sentinel = state / "lockfile.sentinel"

    common.refresh_lock()
    first = sentinel.stat().st_mtime_ns
    for _ in range(3):
        common.refresh_lock()

    assert sentinel.stat().st_mtime_ns == first
    assert sentinel.read_bytes() == str(os.getpid()).encode("ascii")
    # And no temp litter beside it (the _atomic_write_json .tmp class).
    assert [p.name for p in state.glob("*.tmp")] == []


# ---------------------------------------------------------------------------
# direction 2 - it MUST NOT repair when this process does not own the lock
# ---------------------------------------------------------------------------

def test_non_owner_never_creates_a_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live_foreign_pid: int
) -> None:
    """The catastrophic case: a live foreign owner, sentinel gone.

    A process that never won the lock must not manufacture a claim just
    because the file is missing - that is how a non-supervisor stamps its own
    pid onto the singleton.
    """
    state = _point_state_at(tmp_path, monkeypatch)
    # Metadata says a live OTHER process holds the lock; sentinel is absent.
    (state / "lockfile").write_text(
        json.dumps({"pid": live_foreign_pid, "host": "somewhere"}), encoding="utf-8"
    )

    common.refresh_lock()

    assert not (state / "lockfile.sentinel").exists(), (
        "a non-owner re-armed the sentinel with its own pid - this steals the "
        "singleton from the live owner"
    )


def test_inherited_owner_flag_from_a_different_pid_does_not_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ownership is per-PID, not per-module.

    A forked or re-exec'd child inherits module state; the flag alone must not
    be trusted without matching it against the CURRENT pid.
    """
    state = _point_state_at(tmp_path, monkeypatch)
    monkeypatch.setattr(common, "_LOCK_OWNER_PID", os.getpid() + 1, raising=False)

    common.refresh_lock()

    assert not (state / "lockfile.sentinel").exists()


def test_owner_never_overwrites_a_live_foreign_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live_foreign_pid: int
) -> None:
    """Sentinel present holding a DIFFERENT live pid -> do nothing.

    This is the worse-than-absent case: overwriting here would hand the
    singleton to a process whose claim the real owner would then outlive.
    """
    state = _point_state_at(tmp_path, monkeypatch)
    _claim(monkeypatch)
    sentinel = state / "lockfile.sentinel"
    sentinel.write_bytes(str(live_foreign_pid).encode("ascii"))

    common.refresh_lock()

    assert sentinel.read_bytes() == str(live_foreign_pid).encode("ascii")


def test_owner_leaves_a_dead_pid_sentinel_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale (dead-pid) sentinel stays put - reclaim belongs to acquire_lock.

    Duplicating the unlink-and-recreate reclaim inside the heartbeat would add
    a second racing writer to the one file whose whole job is to be written
    exactly once, exclusively.
    """
    state = _point_state_at(tmp_path, monkeypatch)
    _claim(monkeypatch)
    dead = 999999999
    monkeypatch.setattr(common, "_pid_alive", lambda pid: pid == os.getpid())
    sentinel = state / "lockfile.sentinel"
    sentinel.write_bytes(str(dead).encode("ascii"))

    common.refresh_lock()

    assert sentinel.read_bytes() == str(dead).encode("ascii")


# ---------------------------------------------------------------------------
# the race, and the exclusivity primitive
# ---------------------------------------------------------------------------

def test_repair_uses_exclusive_create_not_a_plain_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sentinel write must be O_CREAT|O_EXCL, so a reappearance loses.

    A plain write (or a check-then-write) is a TOCTOU: between "it is missing"
    and "write it" another starter can legitimately claim the lock, and the
    heartbeat would then clobber a valid live claim.
    """
    state = _point_state_at(tmp_path, monkeypatch)
    _claim(monkeypatch)
    sentinel = state / "lockfile.sentinel"

    seen: list[tuple[str, int]] = []
    real_open = os.open

    def _spy_open(path, flags, *a, **kw):
        if str(path).endswith("lockfile.sentinel"):
            seen.append((str(path), int(flags)))
        return real_open(path, flags, *a, **kw)

    monkeypatch.setattr(common.os, "open", _spy_open)
    common.refresh_lock()

    assert seen, "the sentinel repair did not go through os.open at all"
    _, flags = seen[-1]
    assert flags & os.O_CREAT, "sentinel repair must create"
    assert flags & os.O_EXCL, "sentinel repair must be exclusive (no clobber)"
    assert sentinel.read_bytes() == str(os.getpid()).encode("ascii")


def test_sentinel_reappearing_mid_repair_is_lost_gracefully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live_foreign_pid: int
) -> None:
    """Lose the race, keep the winner's bytes, do not raise.

    Simulates the exact interleaving: the file is absent when the heartbeat
    decides to repair, and a competing starter creates it before the open
    lands. The heartbeat must yield, and must not take the daemon down.
    """
    state = _point_state_at(tmp_path, monkeypatch)
    _claim(monkeypatch)
    sentinel = state / "lockfile.sentinel"
    real_open = os.open

    def _racing_open(path, flags, *a, **kw):
        if str(path).endswith("lockfile.sentinel") and not sentinel.exists():
            sentinel.write_bytes(str(live_foreign_pid).encode("ascii"))
        return real_open(path, flags, *a, **kw)

    monkeypatch.setattr(common.os, "open", _racing_open)

    common.refresh_lock()  # must not raise

    assert sentinel.read_bytes() == str(live_foreign_pid).encode("ascii")


def test_repair_failure_never_kills_the_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An OSError from the sentinel open must not stop the lockfile stamp.

    The heartbeat is the daemon's liveness signal; a best-effort repair may
    never be able to break it (a wedged repair would present to the frozen
    _Phase3Watcher as stale_heartbeat and trigger a restart).
    """
    state = _point_state_at(tmp_path, monkeypatch)
    _claim(monkeypatch)
    real_open = os.open

    def _boom(path, flags, *a, **kw):
        if str(path).endswith("lockfile.sentinel"):
            raise OSError(13, "permission denied")
        return real_open(path, flags, *a, **kw)

    monkeypatch.setattr(common.os, "open", _boom)

    common.refresh_lock()  # must not raise

    data = json.loads((state / "lockfile").read_text(encoding="utf-8"))
    assert data["pid"] == os.getpid()
    assert "heartbeat_at" in data


# ---------------------------------------------------------------------------
# acquire_lock wiring + the health signal
# ---------------------------------------------------------------------------

def test_acquire_lock_marks_this_process_as_the_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner flag is set by winning the exclusive create, nothing else."""
    state = _point_state_at(tmp_path, monkeypatch)
    assert common.acquire_lock() is True
    assert common._LOCK_OWNER_PID == os.getpid()

    # End-to-end: the very failure that was measured live. Something removes
    # the sentinel under the running daemon; one heartbeat re-arms it.
    (state / "lockfile.sentinel").unlink()
    common.refresh_lock()
    assert (state / "lockfile.sentinel").read_bytes() == str(os.getpid()).encode("ascii")


def test_acquire_lock_failure_does_not_mark_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live_foreign_pid: int
) -> None:
    """Losing to a live owner must leave this process a non-owner forever."""
    state = _point_state_at(tmp_path, monkeypatch)
    (state / "lockfile.sentinel").write_bytes(str(live_foreign_pid).encode("ascii"))

    assert common.acquire_lock() is False
    assert common._LOCK_OWNER_PID != os.getpid()

    # And a losing starter's heartbeat cannot repair its way into ownership.
    (state / "lockfile.sentinel").unlink()
    common.refresh_lock()
    assert not (state / "lockfile.sentinel").exists()


def test_repair_is_visible_in_the_lockfile_and_silent_when_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The health signal: a repair must not be invisible for 18 hours again.

    The lockfile IS the existing health surface (the frozen _Phase3Watcher in
    ops/rc_supervisor.py polls it every cycle), so the counter rides along
    there. The healthy payload keeps its exact prior key set so nothing
    downstream sees a shape change in steady state.
    """
    state = _point_state_at(tmp_path, monkeypatch)
    _claim(monkeypatch)
    lock = state / "lockfile"

    # Healthy: sentinel already intact, no repair, no extra key.
    (state / "lockfile.sentinel").write_bytes(str(os.getpid()).encode("ascii"))
    common.refresh_lock()
    healthy = json.loads(lock.read_text(encoding="utf-8"))
    assert set(healthy) == {"pid", "started_at", "heartbeat_at", "host"}

    # Disarmed then repaired: the count surfaces.
    (state / "lockfile.sentinel").unlink()
    common.refresh_lock()
    repaired = json.loads(lock.read_text(encoding="utf-8"))
    assert repaired.get("sentinel_repairs") == 1

    # It is cumulative and sticky - a later clean heartbeat still reports it,
    # otherwise the signal vanishes 5 seconds after the event that caused it.
    common.refresh_lock()
    still = json.loads(lock.read_text(encoding="utf-8"))
    assert still.get("sentinel_repairs") == 1


def test_repair_is_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A repair writes a WARNING to supervisor.log - the other silent surface."""
    state = _point_state_at(tmp_path, monkeypatch)
    _claim(monkeypatch)
    with caplog.at_level("WARNING", logger="supervisor"):
        common.refresh_lock()
    assert any(
        "sentinel" in r.getMessage().lower() and r.levelname == "WARNING"
        for r in caplog.records
    ), "the sentinel repair produced no log signal"
    assert (state / "lockfile.sentinel").exists()

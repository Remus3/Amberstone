"""S144-Q-138: ops/loop/loop_controller.py claim_repo - claim RUNNING.lock exclusively.

Same root-cause family as RM-691 (ops/loop/inbox_tick.py), S144-Q-131
(ops/loop/drain_waves_2_3.py) and S144-Q-132 (agents/_supervisor_common.py),
in its weakest shape: claim_repo checked `RUNNING.lock` with exists() plus a
pid read, then awrite()'d its own record over whatever was there. Nothing was
exclusive, so two controllers started together both proceeded:

  * create race - both saw no lock; the second awrite replaced the first
    controller's record and both ran in one repo, consuming each other's
    gemini.ready / claude.done handshake files;
  * break race - both read the same dead pid; one reclaimed and wrote its live
    record, and the other then overwrote that live record.

These pin: a lock that appears between the judgment and the write is never
overwritten (the late controller re-judges it and refuses a live holder), a
stale lock is broken only while it still holds the bytes read, and the existing
contracts stay (dead holder reclaimed, own pid kept across an execv reload,
live holder refused with exit 2, an unreadable record reclaimed). Synthetic
pids only; slots.pid_alive is stubbed; every path is under tmp_path.
"""
from __future__ import annotations

import importlib
import json
import os
import types
from pathlib import Path

import pytest

DEAD_PID = 999_999_101  # synthetic; pid_alive is stubbed, never probed live
LIVE_PID = 999_999_202  # synthetic "other controller", reported alive by the stub


@pytest.fixture
def lc(tmp_path, monkeypatch):
    mod = importlib.import_module("ops.loop.loop_controller")
    ctl = tmp_path / "control"
    ctl.mkdir()
    monkeypatch.setattr(mod, "CTL", ctl)
    # log() appends to the PRODUCTION control/controller.log; keep it in a list.
    lines: list[str] = []
    monkeypatch.setattr(mod, "log", lines.append)
    mod._test_lines = lines
    return mod


def _record(pid: int, run_id: str) -> bytes:
    return json.dumps({"pid": pid, "run_id": run_id, "ts": 1.0,
                       "repo": "<repo>"}).encode("utf-8")


def _put(path: Path, data: bytes) -> None:
    """Another controller's atomic write (what the old awrite did)."""
    tmp = path.with_name(path.name + ".other.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _stub_alive(monkeypatch, lc, on_dead=None):
    def pid_alive(pid):
        if pid == DEAD_PID:
            if on_dead is not None:
                on_dead()
            return False
        return pid == LIVE_PID
    monkeypatch.setattr(lc.slots, "pid_alive", pid_alive)


def _leftovers(ctl: Path) -> list[str]:
    return sorted(p.name for p in ctl.iterdir()
                  if p.name not in ("RUNNING.lock", "run_id.txt"))


def test_break_race_never_overwrites_the_winners_live_lock(lc, monkeypatch):
    """B reads a dead pid; C breaks that lock first and writes its live record;
    B must re-judge, see the live holder and refuse - not overwrite C."""
    lock = lc.CTL / "RUNNING.lock"
    lock.write_bytes(_record(DEAD_PID, "ghost"))
    c_bytes = _record(LIVE_PID, "winner")
    fired = []

    def c_wins():
        if not fired:
            fired.append(1)
            _put(lock, c_bytes)

    _stub_alive(monkeypatch, lc, on_dead=c_wins)
    with pytest.raises(SystemExit) as exc:
        lc.claim_repo()
    assert exc.value.code == 2, "B must refuse once C holds the repo"
    assert lock.read_bytes() == c_bytes, (
        "B overwrote C's fresh lock: two controllers in one repo")
    assert not (lc.CTL / "run_id.txt").exists(), "B must not publish a run id"
    assert _leftovers(lc.CTL) == []


def test_create_race_never_overwrites_a_lock_created_after_the_check(lc, monkeypatch):
    """Both controllers saw no lock; C creates it before B writes. B must not
    replace C's record (the old awrite did) and must refuse the live holder."""
    lock = lc.CTL / "RUNNING.lock"
    c_bytes = _record(LIVE_PID, "winner")
    real_uuid = lc.uuid
    fired = []

    def uuid4():
        if not fired:
            fired.append(1)
            _put(lock, c_bytes)
        return real_uuid.uuid4()

    monkeypatch.setattr(lc, "uuid", types.SimpleNamespace(uuid4=uuid4))
    _stub_alive(monkeypatch, lc)
    with pytest.raises(SystemExit) as exc:
        lc.claim_repo()
    assert exc.value.code == 2
    assert lock.read_bytes() == c_bytes, (
        "B replaced a lock created after its check: two controllers in one repo")
    assert _leftovers(lc.CTL) == [], "a failed claim leaves no scratch file"


def test_no_lock_is_claimed_with_the_full_record(lc, monkeypatch):
    _stub_alive(monkeypatch, lc)
    run_id = lc.claim_repo()
    rec = json.loads((lc.CTL / "RUNNING.lock").read_text(encoding="utf-8"))
    assert rec["pid"] == os.getpid() and rec["run_id"] == run_id
    assert (lc.CTL / "run_id.txt").read_text(encoding="utf-8") == run_id
    assert _leftovers(lc.CTL) == []


def test_dead_holder_is_reclaimed(lc, monkeypatch):
    lock = lc.CTL / "RUNNING.lock"
    lock.write_bytes(_record(DEAD_PID, "ghost"))
    _stub_alive(monkeypatch, lc)
    run_id = lc.claim_repo()
    rec = json.loads(lock.read_text(encoding="utf-8"))
    assert rec["pid"] == os.getpid() and rec["run_id"] == run_id
    assert any("reclaiming stale RUNNING.lock" in m for m in lc._test_lines)
    assert _leftovers(lc.CTL) == [], "the broken lock leaves no side file"


def test_live_holder_is_refused_and_left_untouched(lc, monkeypatch, capsys):
    lock = lc.CTL / "RUNNING.lock"
    held = _record(LIVE_PID, "held")
    lock.write_bytes(held)
    _stub_alive(monkeypatch, lc)
    with pytest.raises(SystemExit) as exc:
        lc.claim_repo()
    assert exc.value.code == 2
    assert lock.read_bytes() == held
    assert "already running" in capsys.readouterr().err


def test_own_pid_is_kept_across_an_execv_reload(lc, monkeypatch):
    """restart_for_new_code relies on this: the re-exec'd image keeps the pid
    and must reclaim its own repo, with a fresh run id."""
    lock = lc.CTL / "RUNNING.lock"
    lock.write_bytes(_record(os.getpid(), "before"))
    _stub_alive(monkeypatch, lc)
    run_id = lc.claim_repo()
    rec = json.loads(lock.read_text(encoding="utf-8"))
    assert rec["pid"] == os.getpid() and rec["run_id"] == run_id != "before"


@pytest.mark.parametrize("raw", [b"", b"{not json", b"[1, 2]", b'{"pid": "x"}'])
def test_unreadable_record_is_reclaimed(lc, monkeypatch, raw):
    lock = lc.CTL / "RUNNING.lock"
    lock.write_bytes(raw)
    _stub_alive(monkeypatch, lc)
    run_id = lc.claim_repo()
    assert json.loads(lock.read_text(encoding="utf-8"))["run_id"] == run_id
    assert _leftovers(lc.CTL) == []

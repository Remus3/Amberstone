"""RM-504: a slot-bucket audit that does not depend on any loop having logged.

The leaks RC measured came from acquires that appear in NO RC log, so the audit
reads the BUCKET. It is read-only: a leaked lock is the leak's only artifact.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from tools import slot_bucket_audit as sba

NOW = 2_000_000_000.0


def _lock(root: Path, i: int, **rec) -> Path:
    p = root / f"{i}.lock"
    p.write_text(json.dumps(rec), encoding="utf-8")
    return p


def _audit(root, alive_pids=(), starts=None):
    starts = starts or {}
    return sba.audit(root, stale_after=1000.0, now=NOW,
                     alive=lambda pid: pid in alive_pids,
                     start_time=lambda pid: starts.get(pid))


def test_dead_pid_rc_lock_is_a_leak(tmp_path):
    _lock(tmp_path, 0, pid=111, repo=str(sba.ROOT), run_id="12323c3b", cycle=1, ts=NOW - 50)
    rows = _audit(tmp_path)
    assert rows[0]["verdict"] == "DEAD_PID"
    assert sba.rc_leaks(rows) == rows


def test_pid_reused_is_caught_by_process_start_time(tmp_path):
    """A live pid whose process started AFTER the lock was written is not the
    holder - liveness alone would call this lock healthy."""
    _lock(tmp_path, 0, pid=222, repo="rc-responder", ts=NOW - 500)
    rows = _audit(tmp_path, alive_pids={222}, starts={222: NOW - 100})
    assert rows[0]["verdict"] == "PID_REUSED"
    assert len(sba.rc_leaks(rows)) == 1


def test_live_holder_is_ok(tmp_path):
    _lock(tmp_path, 0, pid=333, repo=str(sba.ROOT), ts=NOW - 50)
    rows = _audit(tmp_path, alive_pids={333}, starts={333: NOW - 900})
    assert rows[0]["verdict"] == "OK"
    assert sba.rc_leaks(rows) == []


def test_over_stale_live_lock_is_a_leak(tmp_path):
    _lock(tmp_path, 0, pid=444, repo=str(sba.ROOT).upper(), ts=NOW - 5000)
    rows = _audit(tmp_path, alive_pids={444}, starts={444: NOW - 9000})
    assert rows[0]["verdict"] == "OVER_STALE"
    assert rows[0]["rc_authored"] is True


def test_foreign_dead_lock_is_reported_but_not_rc_leak(tmp_path):
    _lock(tmp_path, 0, pid=555, repo="C:\\Some Sibling", ts=NOW - 50)
    rows = _audit(tmp_path)
    assert rows[0]["verdict"] == "DEAD_PID"
    assert sba.rc_leaks(rows) == []


def test_zero_byte_lock_is_unreadable_and_reported(tmp_path):
    (tmp_path / "1.lock").write_text("", encoding="utf-8")
    rows = _audit(tmp_path)
    assert rows[0]["verdict"] == "UNREADABLE"
    assert len(sba.rc_leaks(rows)) == 1


def test_audit_is_read_only(tmp_path):
    p = _lock(tmp_path, 0, pid=111, repo=str(sba.ROOT), ts=NOW - 50)
    before = p.read_bytes()
    sba.audit(tmp_path)
    assert p.read_bytes() == before


def test_main_exit_code_reflects_rc_leaks(tmp_path):
    _lock(tmp_path, 0, pid=0, repo=str(sba.ROOT), ts=time.time())
    assert sba.main(["--root", str(tmp_path)]) == 1
    (tmp_path / "0.lock").unlink()
    _lock(tmp_path, 0, pid=os.getpid(), repo=str(sba.ROOT), ts=time.time())
    assert sba.main(["--root", str(tmp_path)]) == 0


def test_missing_bucket_is_empty_not_an_error(tmp_path):
    assert sba.audit(tmp_path / "absent") == []
    assert sba.anomaly_lines(tmp_path / "absent") == []


LOG = """2026-07-28T20:00:00 slots: acquired 0.lock (run_id=eadf15e3 cycle=71)
2026-07-28T20:10:00 slots: released 0.lock
2026-07-28T20:53:47 slots: acquired 0.lock (run_id=eadf15e3 cycle=72)
2026-09-11T16:12:16 slots: acquired 1.lock (run_id=63545b4e cycle=7)
2026-09-11T16:48:57 slots: released 1.lock
2026-09-11T17:00:00 slots: reaped stale slot 0 (pid=1 repo=x)
""".splitlines()


def test_hold_corpus_pairs_and_keeps_unpaired_as_a_floor():
    c = sba.hold_corpus(LOG, stale_after=16200.0)
    assert (c["acquires"], c["releases"], c["reaps"], c["pairs"]) == (3, 2, 1, 2)
    assert c["worst_hold_s"] == 2201
    assert [u["run_id"] for u in c["unpaired"]] == ["eadf15e3"]
    assert "FLOOR" in c["basis"]
    assert c["run_ids"] == ["63545b4e", "eadf15e3"]


# ---- caller-side eager reap (loop_controller.pre_hold_reap) ----------------

def _lc(monkeypatch):
    import importlib
    lc = importlib.import_module("ops.loop.loop_controller")
    lines: list[str] = []
    monkeypatch.setattr(lc, "log", lines.append)
    return lc, lines


def test_pre_hold_reap_logs_full_record_then_reaps_in_a_non_full_bucket(tmp_path, monkeypatch):
    lc, lines = _lc(monkeypatch)
    _lock(tmp_path, 0, pid=0, repo=str(sba.ROOT), run_id="a22618e2", cycle=1,
          ts=time.time() - 10)
    lc.pre_hold_reap(3, root=tmp_path)
    assert not (tmp_path / "0.lock").exists(), "stale lock in a NON-full bucket reaped"
    assert any("a22618e2" in line and "pre-hold reap candidate" in line for line in lines)


def test_pre_hold_reap_leaves_a_live_holder(tmp_path, monkeypatch):
    lc, lines = _lc(monkeypatch)
    _lock(tmp_path, 0, pid=os.getpid(), repo=str(sba.ROOT), ts=time.time())
    lc.pre_hold_reap(3, root=tmp_path)
    assert (tmp_path / "0.lock").exists()
    assert not any("candidate" in line for line in lines)

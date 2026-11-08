#!/usr/bin/env python
"""RM-691 - two fires that both find a STALE inbox_tick.lock cannot both hold it,
and a fire never drops a lock it does not own.

Root cause (ops/loop/inbox_tick.py before RM-691): `_take_lock` read the stale
lock's ts, then unlinked the lock BY PATH and retried O_EXCL. Fire A could
break the stale lock and create its own fresh one between fire B's staleness
read and B's unlink, so B deleted A's FRESH lock, created its own, and both
ran. `_drop_lock` also unlinked by path with no owner check, so the first of
the two to finish deleted the other's live lock on its way out.

The interleave is driven through the injected `clock` seam: B's staleness
compare calls clock() after B has read the lock, so B's clock runs fire A in
full inside B's window. Every root is a tmp dir; no live control file is read.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


tick_mod = _load("rc_loop_inbox_tick_rm691_test", ROOT / "ops" / "loop" / "inbox_tick.py")
fi = tick_mod.fleet_inbox

STALE = json.dumps({"pid": 1, "ts": 0}).encode("ascii")
WINNER = json.dumps({"pid": 2, "ts": 1.0e12, "tok": "winner"}).encode("ascii")


def _lock(root: Path) -> Path:
    return root / tick_mod.LOCK_REL


def _seed(root: Path, data: bytes) -> Path:
    lock = _lock(root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_bytes(data)
    return lock


def _leftovers(root: Path) -> list[str]:
    """Side files a break or a drop left beside the lock (other control files,
    such as the tick's own status file, are not counted)."""
    lock = _lock(root)
    return sorted(p.name for p in lock.parent.iterdir()
                  if p.name.startswith(f"{lock.stem}.") and p.name != lock.name)


def test_a_break_side_file_is_a_lock_the_test_guard_ignores(tmp_path, monkeypatch):
    """A side file left by a failed unlink ends in .lock (kit guard IGNORE)."""
    _seed(tmp_path, STALE)
    names = []
    real = tick_mod.os.rename

    def spy(src, dst):
        names.append(Path(dst).name)
        return real(src, dst)

    monkeypatch.setattr(tick_mod.os, "rename", spy)
    assert tick_mod._take_lock(tmp_path)
    assert names and all(n.startswith("inbox_tick.break-") and n.endswith(".lock")
                         for n in names), names


# ---- 1. the stale-lock break -------------------------------------------------

def test_two_takers_over_one_stale_lock_cannot_both_hold_it(tmp_path):
    lock = _seed(tmp_path, STALE)
    took = {}

    def b_clock():
        # B has read the stale lock; fire A breaks it and takes a fresh one now.
        if "a" not in took:
            took["a"] = tick_mod._take_lock(tmp_path)
            took["a_bytes"] = lock.read_bytes()
        return time.time()

    took["b"] = tick_mod._take_lock(tmp_path, clock=b_clock)
    assert took["a"], "fire A breaks the stale lock and holds it"
    assert not took["b"], "fire B must not break A's FRESH lock (both would hold)"
    assert lock.read_bytes() == took["a_bytes"], "A's lock is left in place"
    assert _leftovers(tmp_path) == [], "the break leaves no side file"


def test_a_stale_lock_is_still_reclaimed_and_leaves_no_side_file(tmp_path):
    lock = _seed(tmp_path, STALE)
    claim = tick_mod._take_lock(tmp_path)
    assert claim
    rec = json.loads(lock.read_text(encoding="ascii"))
    assert rec["pid"] == os.getpid() and rec["ts"] > 0
    assert _leftovers(tmp_path) == []


def test_an_unparseable_lock_falls_back_to_its_mtime(tmp_path):
    lock = _seed(tmp_path, b"not json")
    assert not tick_mod._take_lock(tmp_path), "a fresh unparseable lock is held"
    old = time.time() - tick_mod.LOCK_STALE_S - 60
    os.utime(lock, (old, old))
    assert tick_mod._take_lock(tmp_path), "an old unparseable lock is stale"
    assert _leftovers(tmp_path) == []


def test_a_fresh_lock_is_never_broken(tmp_path):
    lock = _seed(tmp_path, json.dumps({"pid": 1, "ts": time.time()}).encode("ascii"))
    before = lock.read_bytes()
    assert not tick_mod._take_lock(tmp_path)
    assert lock.read_bytes() == before


def test_two_takes_in_one_process_get_distinct_claims(tmp_path):
    """Same pid, same clock: the claims still differ, so a drop can tell them apart."""
    def frozen():
        return 5.0e9

    first = tick_mod._take_lock(tmp_path, clock=frozen)
    first_bytes = _lock(tmp_path).read_bytes()
    _lock(tmp_path).unlink()
    tick_mod._take_lock(tmp_path, clock=frozen)
    assert _lock(tmp_path).read_bytes() != first_bytes
    tick_mod._drop_lock(tmp_path, first)
    assert _lock(tmp_path).exists(), "the first claim cannot drop the second lock"


# ---- 2. the drop: only the owner's lock goes ------------------------------------

def test_drop_removes_this_fires_own_lock(tmp_path):
    claim = tick_mod._take_lock(tmp_path)
    tick_mod._drop_lock(tmp_path, claim)
    assert not _lock(tmp_path).exists()
    assert _leftovers(tmp_path) == []


def test_drop_leaves_another_fires_lock_in_place(tmp_path):
    claim = tick_mod._take_lock(tmp_path)
    _seed(tmp_path, WINNER)  # another fire broke it (as stale) and took it
    tick_mod._drop_lock(tmp_path, claim)
    assert _lock(tmp_path).read_bytes() == WINNER
    assert _leftovers(tmp_path) == []


def _steal_then(root: Path, result):
    """A seam that, mid-pass, lets another fire replace the lock, then returns."""
    def seam(*_a, **_k):
        _lock(root).write_bytes(WINNER)
        return result
    return seam


@pytest.mark.parametrize("entry", ["tick", "close", "migrate_legacy"])
def test_the_losing_fire_does_not_delete_the_winners_lock(tmp_path, monkeypatch, entry):
    """Each lock-holding entry point releases only the lock it took."""
    if entry == "tick":
        monkeypatch.setattr(fi, "scan", _steal_then(tmp_path, []))
        s = tick_mod.tick(tmp_path, inbox=tmp_path / "inbox", agreement=None,
                          participants={}, retired=(), now=datetime(2026, 10, 7, 22))
        assert s["locked"] is False
    elif entry == "close":
        monkeypatch.setattr(fi, "pending_work", _steal_then(tmp_path, []))
        assert tick_mod.close(tmp_path, "2026-10-07-0000-from-MAIN-ORDER-to-RC-x.md",
                              wait_s=0) == []
    else:
        monkeypatch.setattr(tick_mod, "_migrate", _steal_then(tmp_path, {"legacy": 0}))
        assert tick_mod.migrate_legacy(tmp_path)["legacy"] == 0
    assert _lock(tmp_path).read_bytes() == WINNER, "the winner's lock survives"
    assert _leftovers(tmp_path) == []


@pytest.mark.parametrize("entry", ["tick", "close", "migrate_legacy"])
def test_each_entry_point_still_releases_its_own_lock(tmp_path, monkeypatch, entry):
    if entry == "tick":
        s = tick_mod.tick(tmp_path, inbox=tmp_path / "inbox", agreement=None,
                          participants={}, retired=(), now=datetime(2026, 10, 7, 22))
        assert s["locked"] is False
    elif entry == "close":
        assert tick_mod.close(tmp_path, "2026-10-07-0000-from-MAIN-ORDER-to-RC-x.md",
                              wait_s=0) == []
    else:
        assert tick_mod.migrate_legacy(tmp_path)["locked"] is False
    assert not _lock(tmp_path).exists()
    assert _leftovers(tmp_path) == []

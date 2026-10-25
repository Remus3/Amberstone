"""Queue lock must exclude across handles (h01, t-02760f99d1a0)."""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import threading
import time

import pytest

from agents.agent1_lead import scheduler as sch


def _hold(path, ready, release):
    s = sch.Scheduler.__new__(sch.Scheduler)
    s._queue_log = path
    with s._queue_lock() as got:
        ready.put(got)
        release.get(timeout=20)


def _make(path):
    s = sch.Scheduler.__new__(sch.Scheduler)
    s._queue_log = path
    return s


def test_second_holder_excluded_and_compact_skips(tmp_path, monkeypatch):
    log = tmp_path / "task_queue.jsonl"
    log.write_text('{"a":1}\n' * 20, encoding="utf-8")
    before = log.read_bytes()
    ready, release = mp.Queue(), mp.Queue()
    p = mp.Process(target=_hold, args=(log, ready, release))
    p.start()
    try:
        assert ready.get(timeout=20) is True
        monkeypatch.setattr(sch, "_APPEND_LOCK_MAX_WAIT_SEC", 0.3)
        s = _make(log)
        s._lock = threading.RLock()
        t0 = time.monotonic()
        assert s.compact() == (0, 0)
        assert time.monotonic() - t0 >= 0.25
        assert log.read_bytes() == before
    finally:
        release.put(1)
        p.join(20)


@pytest.mark.skipif(os.name != "nt", reason="msvcrt byte locks are mandatory only on Windows")
def test_compact_blocks_lockless_readers_during_the_rewrite(tmp_path, monkeypatch):
    """The sidecar excludes writers only. Readers take no lock, so compact()
    must also hold byte 0 of the DATA file, or a reader in another process
    can read the empty file between truncate and rewrite and clear its task
    list (s134 verifier, measured). A second handle stands in for it."""
    log = tmp_path / "task_queue.jsonl"
    rec = json.dumps({"event": "filed", "task": {"id": "t1", "priority": 50}})
    log.write_text((rec + "\n") * 3, encoding="utf-8")
    s = _make(log)
    s._lock = threading.RLock()
    probes = []
    real = sch.Scheduler._task_dict_from_record
    real_info = sch.logger.info

    def _read(where):
        try:
            log.read_bytes()
            probes.append((where, "read"))
        except PermissionError:
            probes.append((where, "blocked"))

    def parse_probe(r):
        _read("parse")
        return real(r)

    def info_probe(msg, *args, **kwargs):
        # compact() logs this after truncate + write + flush, inside the locks:
        # the probe covers the rewrite window, not only the parse before it.
        if str(msg).startswith("task_queue.jsonl compact"):
            _read("rewritten")
        return real_info(msg, *args, **kwargs)

    monkeypatch.setattr(s, "_task_dict_from_record", parse_probe)
    monkeypatch.setattr(sch.logger, "info", info_probe)
    assert s.compact() == (3, 1)
    assert {w for w, _ in probes} == {"parse", "rewritten"}
    assert {o for _, o in probes} == {"blocked"}
    assert log.read_text(encoding="utf-8") == rec + "\n"
    with s._queue_lock() as again:
        assert again


def test_lock_reacquirable_after_release(tmp_path):
    s = _make(tmp_path / "task_queue.jsonl")
    with s._queue_lock() as a:
        assert a
    with s._queue_lock() as b:
        assert b

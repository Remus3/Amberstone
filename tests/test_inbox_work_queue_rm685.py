#!/usr/bin/env python
"""RM-685 - the inbox tick's WORK rows go through the kit v10 work queue.

Root cause (session 104): ops/loop/inbox_tick.py appended its OWN row shape
({"state": "open"}, no "op", no "sha256") to ops/loop/control/inbox_work.jsonl,
so kit fleet_inbox.pending_work() never saw a row and nothing could close one.

Acceptance (ROADMAP / BACKLOG RM-685):
1. the tick queues through kit enqueue_work (provenance rides on an RC
   companion line keyed by the same note + sha256; the kit is never edited);
2. a queued MAIN ORDER appears in pending_work() and leaves after
   mark_work_done();
3. a closing path an answering session or lane can call (close() / --done);
4. legacy `state` rows are excluded by rule and migrated by migrate_legacy().

Every root is a tmp dir; nothing reads the live inbox or starts a process.
"""
from __future__ import annotations

import functools
import hashlib
import importlib.util
import inspect
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


tick_mod = _load("rc_loop_inbox_tick_rm685_test", ROOT / "ops" / "loop" / "inbox_tick.py")
fi = tick_mod.fleet_inbox

NOW = datetime(2026, 10, 7, 22, 0, 0)
ORDER = "2026-10-07-2200-from-MAIN-ORDER-to-RC-do-a-thing.md"
FIX = "2026-10-07-2201-from-MAIN-FIX-to-RC-x.md"
SIB_ORDER = "2026-10-07-2202-from-SS-ORDER-to-RC-y.md"
NOTE_A = "2026-10-05-0310-from-MAIN-ORDER-to-RC-a.md"
NOTE_B = "2026-10-05-0327-from-MAIN-FIX-to-RC-b.md"
NOTE_C = "2026-10-06-2237-from-MAIN-RULING-to-RC-c.md"
NOTE_D = "2026-10-06-2354-from-MAIN-ORDER-to-RC-gone.md"
PARTS = ("CS", "EW", "LW", "RSC", "SS")


# ---- fixtures --------------------------------------------------------------

def _record(**over):
    rec = {
        "schema": tick_mod.AGREEMENT_SCHEMA,
        "counterparties": ["CS", "EW", "LW", "MAIN", "RSC", "SS"],
        "main": {"code": "MAIN", "outbox": "X:/main/moon_sync_outbox"},
        "budget": "kit",
        "expires": "2026-11-01T00:00:00",
        "authored_by": "operator",
        "authored_at": "2026-10-07T22:00:00",
        "note": "MAIN 0327 RULING: one record, no own hop budget",
    }
    rec.update(over)
    return rec


def _note(inbox: Path, name: str, body: str, mtime: float) -> Path:
    inbox.mkdir(parents=True, exist_ok=True)
    p = inbox / name
    p.write_text(body, encoding="ascii", newline="\n")
    os.utime(p, (mtime, mtime))
    return p


class _Spy:
    """A spawn seam that must never be called by a WORK note."""

    def __init__(self):
        self.calls = []

    def __call__(self, root, code, prompt, **kw):
        self.calls.append(kw)
        return {"rc": 0, "result": "VERDICT: ACK"}


def _tick(root, inbox, **kw):
    kw.setdefault("agreement", _record())
    kw.setdefault("participants", {k: root / "sib" / k for k in PARTS})
    kw.setdefault("retired", {"LL"})
    kw.setdefault("verify", lambda note, outbox: True)
    kw.setdefault("spawn", _Spy())
    kw.setdefault("now", NOW)
    return tick_mod.tick(root, inbox=inbox, **kw)


def _work(root: Path) -> Path:
    return root / tick_mod.WORK_REL


def _work_lines(root: Path) -> list:
    return [json.loads(x) for x in _work(root).read_text(encoding="ascii").splitlines() if x]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _queued_order(root: Path) -> Path:
    inbox = root / "inbox"
    p = _note(inbox, ORDER, "# From MAIN - ORDER to RC\n\nHOP: 1\n", 1)
    s = _tick(root, inbox)
    assert s["escalated"] == 1
    return p


# ---- 1. the tick queues through kit enqueue_work ------------------------------

def test_a_main_order_is_queued_in_the_kit_shape(tmp_path):
    p = _queued_order(tmp_path)
    (row,) = fi.pending_work(tmp_path)
    assert row["op"] == "queued" and row["note"] == ORDER
    assert row["sha256"] == _sha(p)
    assert row["cls"] == "ORDER" and row["sender"] == "MAIN" and row["hop"] == 1
    (mine,) = tick_mod.pending(tmp_path)
    assert mine["provenance"] == "main-verified"
    assert mine["note"] == ORDER and mine["sha256"] == row["sha256"]
    for d in _work_lines(tmp_path):
        assert "state" not in d, "no legacy-shape row is written any more"
        assert d["op"] in ("queued", "rc-provenance")
    assert tick_mod.PROVENANCE_OP == "rc-provenance"


def test_the_provenance_line_is_keyed_by_note_and_sha(tmp_path):
    _queued_order(tmp_path)
    queued, prov = _work_lines(tmp_path)
    assert prov == {"ts": queued["ts"], "op": "rc-provenance", "note": ORDER,
                    "sha256": queued["sha256"], "provenance": "main-verified"}


# ---- 2. acceptance 2: pending_work -> mark_work_done --------------------------

def test_mark_work_done_drains_the_queued_main_order(tmp_path):
    _queued_order(tmp_path)
    (row,) = fi.pending_work(tmp_path)
    fi.mark_work_done(tmp_path, row, outcome="answered")
    assert fi.pending_work(tmp_path) == []
    assert tick_mod.pending(tmp_path) == []


# ---- 3. the closing path --------------------------------------------------------

def test_close_drains_by_note_name_and_records_the_outcome(tmp_path):
    p = _queued_order(tmp_path)
    done = tick_mod.close(tmp_path, str(p), outcome="answered in X sha 73dda790",
                          clock=lambda: 1_800_000_000)
    assert len(done) == 1
    assert done[0]["op"] == "done" and done[0]["note"] == ORDER
    assert done[0]["sha256"] == _sha(p)
    assert done[0]["outcome"] == "answered in X sha 73dda790"
    assert _work_lines(tmp_path)[-1] == done[0]
    assert fi.pending_work(tmp_path) == []
    assert tick_mod.close(tmp_path, ORDER) == [], "a closed row does not close twice"


def test_close_of_an_unknown_note_writes_nothing(tmp_path):
    _queued_order(tmp_path)
    before = _work(tmp_path).read_bytes()
    assert tick_mod.close(tmp_path, "2026-10-07-0000-from-MAIN-ORDER-to-RC-nope.md") == []
    assert _work(tmp_path).read_bytes() == before
    empty = tmp_path / "empty"
    assert tick_mod.close(empty, ORDER) == []
    assert not _work(empty).exists()


# ---- provenance shapes ------------------------------------------------------

def test_unverified_main_and_sibling_orders_carry_their_provenance(tmp_path):
    inbox = tmp_path / "inbox"
    _note(inbox, FIX, "# x\n", 1)
    _note(inbox, SIB_ORDER, "# x\n", 2)
    s = _tick(tmp_path, inbox, verify=lambda n, o: False)
    assert s["escalated"] == 2
    got = [(r["note"], r["provenance"]) for r in tick_mod.pending(tmp_path)]
    assert got == [(FIX, "main-unverified"), (SIB_ORDER, "sibling")]


def test_a_retick_does_not_double_the_row_or_the_provenance_line(tmp_path):
    _queued_order(tmp_path)
    (tmp_path / fi.SEEN_REL).unlink()
    s = _tick(tmp_path, tmp_path / "inbox")
    assert s["escalated"] == 1, "the note is still escalated and marked seen"
    ops = [d["op"] for d in _work_lines(tmp_path)]
    assert ops == ["queued", "rc-provenance"]
    assert len(tick_mod.pending(tmp_path)) == 1


def test_a_rewritten_note_is_a_new_row_with_its_own_provenance(tmp_path):
    inbox = tmp_path / "inbox"
    _queued_order(tmp_path)
    _note(inbox, ORDER, "# From MAIN - ORDER to RC\n\nHOP: 1\n\nrevised\n", 5)
    _tick(tmp_path, inbox, verify=lambda n, o: False)
    rows = tick_mod.pending(tmp_path)
    assert [r["note"] for r in rows] == [ORDER, ORDER]
    assert rows[0]["sha256"] != rows[1]["sha256"]
    assert [r["provenance"] for r in rows] == ["main-verified", "main-unverified"]


def test_pending_defaults_provenance_to_unknown(tmp_path):
    p = _note(tmp_path / "inbox", ORDER, "# x\n", 1)
    d = fi.classify(p.name, "RC", "# x\n")
    fi.enqueue_work(tmp_path, p, d)
    (row,) = tick_mod.pending(tmp_path)
    assert row["provenance"] == "unknown"


# ---- 4. legacy rows: excluded by rule, then migrated --------------------------

def _legacy_fixture(root: Path) -> tuple:
    inbox = root / tick_mod.INBOX_DIR
    a = _note(inbox, NOTE_A, "# From MAIN - ORDER A\n", 1)
    _note(inbox, NOTE_B, "# From MAIN - FIX B\n", 2)
    c = _note(inbox, NOTE_C, "# From MAIN - RULING C\n", 3)
    sha_c = _sha(c)
    lines = [
        json.dumps({"ts": "2026-10-05T03:10:00-05:00", "note": NOTE_A, "cls": "ORDER",
                    "sender": "MAIN", "hop": 1, "provenance": "main-verified",
                    "state": "open"}),
        json.dumps({"ts": "2026-10-05T03:27:00-05:00", "note": NOTE_B, "cls": "FIX",
                    "sender": "MAIN", "hop": 1, "provenance": "main-verified",
                    "state": "open"}),
        "this is not json {",
        json.dumps({"ts": "2026-10-06T22:37:00-05:00", "op": "queued", "note": NOTE_C,
                    "sha256": sha_c, "cls": "RULING", "sender": "MAIN", "hop": 1}),
        json.dumps({"ts": "2026-10-06T22:37:00-05:00", "op": "rc-provenance",
                    "note": NOTE_C, "sha256": sha_c, "provenance": "main-verified"}),
        json.dumps({"ts": "2026-10-08T14:17:00-05:00", "note": NOTE_B, "cls": "FIX",
                    "sender": "MAIN", "provenance": "main-verified", "state": "done",
                    "outcome": "answered in note 1431 (LEDGER 1687)",
                    "by": "session 104"}),
    ]
    raw = ("\n".join(lines) + "\n").encode("ascii")
    path = _work(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw, lines, a, c


def test_legacy_rows_are_excluded_until_migrated_then_converted(tmp_path):
    raw, lines, a, c = _legacy_fixture(tmp_path)
    assert [r["note"] for r in fi.pending_work(tmp_path)] == [NOTE_C], \
        "a row without op is legacy: the kit reader ignores it"
    assert [r["note"] for r in tick_mod.pending(tmp_path)] == [NOTE_C]

    res = tick_mod.migrate_legacy(tmp_path)
    assert res["locked"] is False
    assert (res["legacy"], res["queued"], res["done"]) == (3, 2, 1)
    backup = Path(res["backup"])
    assert backup.parent == _work(tmp_path).parent
    assert backup.name.startswith("inbox_work.jsonl.pre-rm685-")
    assert backup.name.endswith(".bak")
    assert backup.read_bytes() == raw

    out = _work(tmp_path).read_bytes()
    out.decode("ascii")
    assert b"\r" not in out and out.endswith(b"\n") and not out.endswith(b"\n\n")
    text_lines = out.decode("ascii").split("\n")[:-1]
    assert text_lines[4] == "this is not json {", "garbage line kept in place"
    assert text_lines[5:7] == lines[3:5], "kit lines kept byte-for-byte"

    pend = tick_mod.pending(tmp_path)
    assert [r["note"] for r in pend] == [NOTE_A, NOTE_C]
    assert pend[0]["sha256"] == _sha(a)
    assert pend[0]["provenance"] == "main-verified"
    assert pend[0]["cls"] == "ORDER" and pend[0]["hop"] == 1
    assert pend[0]["ts"] == "2026-10-05T03:10:00-05:00"
    assert pend[1]["provenance"] == "main-verified"
    done = [json.loads(x) for x in text_lines[:4] + text_lines[5:] if x.startswith("{")]
    (b_done,) = [d for d in done if d.get("op") == "done"]
    assert b_done["note"] == NOTE_B
    assert "answered in note 1431 (LEDGER 1687)" in b_done["outcome"]
    assert "[by session 104]" in b_done["outcome"]
    assert NOTE_B not in [r["note"] for r in fi.pending_work(tmp_path)]
    assert not any("state" in d for d in done)


def test_a_second_migration_is_a_no_op(tmp_path):
    _legacy_fixture(tmp_path)
    first = tick_mod.migrate_legacy(tmp_path)
    assert first["legacy"] == 3
    after = _work(tmp_path).read_bytes()
    second = tick_mod.migrate_legacy(tmp_path)
    assert second["locked"] is False and second["legacy"] == 0
    assert second["backup"] is None
    assert _work(tmp_path).read_bytes() == after
    baks = list(_work(tmp_path).parent.glob("inbox_work.jsonl.pre-rm685-*.bak"))
    assert len(baks) == 1


def test_a_legacy_pair_whose_note_is_gone_still_closes(tmp_path):
    path = _work(tmp_path)
    path.parent.mkdir(parents=True)
    rows = [{"ts": "t1", "note": NOTE_D, "cls": "ORDER", "sender": "MAIN", "hop": 1,
             "provenance": "main-verified", "state": "open"},
            {"ts": "t2", "note": NOTE_D, "cls": "ORDER", "sender": "MAIN",
             "provenance": "main-verified", "state": "done"}]
    path.write_bytes("".join(json.dumps(r) + "\n" for r in rows).encode("ascii"))
    res = tick_mod.migrate_legacy(tmp_path)
    assert (res["legacy"], res["queued"], res["done"]) == (2, 1, 1)
    lines = _work_lines(tmp_path)
    assert all(d["sha256"] is None for d in lines)
    assert lines[-1]["op"] == "done" and lines[-1]["outcome"] == "done"
    assert fi.pending_work(tmp_path) == []


def test_migrate_under_a_held_tick_lock_writes_nothing(tmp_path):
    raw, _lines, _a, _c = _legacy_fixture(tmp_path)
    lock = tmp_path / tick_mod.LOCK_REL
    lock.write_text(json.dumps({"pid": 1, "ts": time.time()}), encoding="ascii")
    assert tick_mod.migrate_legacy(tmp_path) == {"locked": True, "legacy": 0,
                                                 "undecodable": []}
    assert _work(tmp_path).read_bytes() == raw
    assert not list(_work(tmp_path).parent.glob("*.bak"))
    assert lock.exists(), "a lock this call did not take is never dropped"


def test_migrate_with_nothing_legacy_writes_nothing_and_releases_the_lock(tmp_path):
    res = tick_mod.migrate_legacy(tmp_path)
    assert res["legacy"] == 0 and res["backup"] is None and res["locked"] is False
    assert not _work(tmp_path).exists()
    assert not (tmp_path / tick_mod.LOCK_REL).exists()


# ---- the tick summary --------------------------------------------------------

def test_the_summary_counts_pending_work(tmp_path):
    assert tick_mod._empty_summary(False)["pending"] == 0
    inbox = tmp_path / "inbox"
    _note(inbox, ORDER, "# x\n", 1)
    s = _tick(tmp_path, inbox)
    assert s["pending"] == 1
    assert tick_mod.summary_line(s).startswith("inbox: 1 unseen")
    assert "1 work pending" in tick_mod.summary_line(s)
    dry = _tick(tmp_path, inbox, dry=True)
    assert dry["pending"] == 1, "the dry pass reads the queue too"
    tick_mod.close(tmp_path, ORDER, outcome="answered")
    s2 = _tick(tmp_path, inbox)
    assert s2["pending"] == 0
    assert "work pending" not in tick_mod.summary_line(s2)


def test_a_pending_count_fault_is_an_error_not_a_raise(tmp_path, monkeypatch):
    def boom(_root):
        raise RuntimeError("queue unreadable")

    monkeypatch.setattr(fi, "pending_work", boom)
    s = _tick(tmp_path, tmp_path / "inbox")
    assert s["pending"] == 0
    assert any("queue unreadable" in e for e in s["errors"])


# ---- the CLI -----------------------------------------------------------------

def _no_tick(*a, **k):
    raise AssertionError("a queue flag must not run a tick")


def test_cli_pending_prints_rows_and_runs_no_tick(tmp_path, monkeypatch, capsys):
    _queued_order(tmp_path)
    capsys.readouterr()
    monkeypatch.setattr(tick_mod, "tick", _no_tick)
    assert tick_mod.main(["--root", str(tmp_path), "--pending"]) == 0
    rows = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x]
    assert [(r["note"], r["provenance"]) for r in rows] == [(ORDER, "main-verified")]
    assert not (tmp_path / tick_mod.LAST_REL).exists()


def test_cli_done_closes_once_then_fails(tmp_path, monkeypatch, capsys):
    _queued_order(tmp_path)
    capsys.readouterr()
    monkeypatch.setattr(tick_mod, "tick", _no_tick)
    argv = ["--root", str(tmp_path), "--done", ORDER, "--outcome", "answered 1431"]
    assert tick_mod.main(argv) == 0
    (doc,) = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x]
    assert doc["op"] == "done" and doc["outcome"] == "answered 1431"
    assert tick_mod.main(argv) == 1
    cap = capsys.readouterr()
    assert cap.out == "" and cap.err.strip()
    assert not (tmp_path / tick_mod.LAST_REL).exists()


def test_cli_done_defaults_the_outcome(tmp_path, monkeypatch, capsys):
    _queued_order(tmp_path)
    monkeypatch.setattr(tick_mod, "tick", _no_tick)
    assert tick_mod.main(["--root", str(tmp_path), "--done", ORDER]) == 0
    assert _work_lines(tmp_path)[-1]["outcome"] == "done"


def test_cli_migrate_legacy(tmp_path, monkeypatch, capsys):
    _legacy_fixture(tmp_path)
    monkeypatch.setattr(tick_mod, "tick", _no_tick)
    assert tick_mod.main(["--root", str(tmp_path), "--migrate-legacy"]) == 0
    res = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert res["legacy"] == 3 and res["locked"] is False
    lock = tmp_path / tick_mod.LOCK_REL
    lock.write_text(json.dumps({"pid": 1, "ts": time.time()}), encoding="ascii")
    assert tick_mod.main(["--root", str(tmp_path), "--migrate-legacy"]) == 1
    assert not (tmp_path / tick_mod.LAST_REL).exists()


@pytest.mark.parametrize("argv", [
    ["--pending", "--migrate-legacy"],
    ["--pending", "--done", ORDER],
    ["--dry", "--migrate-legacy"],
])
def test_cli_queue_flags_are_mutually_exclusive(tmp_path, monkeypatch, argv):
    monkeypatch.setattr(tick_mod, "tick", _no_tick)
    with pytest.raises(SystemExit) as exc:
        tick_mod.main(["--root", str(tmp_path), *argv])
    assert exc.value.code == 2


# ---- RM-689 (a): close() / --done hold the tick lock ---------------------------
#
# Root cause: close() read pending_work and appended mark_work_done lines with
# NO lock, while a scheduled tick appends enqueue_work + rc-provenance lines
# under ops/loop/control/inbox_tick.lock. The kit has no lock of its own, so
# the tick lock is the only serialisation for inbox_work.jsonl.

def _hold_lock(root: Path, ts=None) -> Path:
    lock = root / tick_mod.LOCK_REL
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": 1, "ts": time.time() if ts is None else ts}),
                    encoding="ascii")
    return lock


def _never_sleep(_s):
    raise AssertionError("wait_s=0 must not sleep")


class _Sleeps:
    """An injected sleep: records each interval; `on` runs after call N."""

    def __init__(self, on=None):
        self.calls, self.on = [], on or {}

    def __call__(self, s):
        self.calls.append(s)
        hook = self.on.get(len(self.calls))
        if hook is not None:
            hook()


def _lock_seen_by(monkeypatch, name: str) -> list:
    """Wrap kit fleet_inbox.<name> to record the lock file's pid at each call."""
    seen = []
    orig = getattr(fi, name)

    def wrapped(root, *a, **k):
        p = Path(root) / tick_mod.LOCK_REL
        seen.append(json.loads(p.read_text(encoding="ascii"))["pid"]
                    if p.exists() else None)
        return orig(root, *a, **k)

    monkeypatch.setattr(fi, name, wrapped)
    return seen


def test_lock_held_is_a_runtime_error_and_close_has_the_wait_seams():
    assert issubclass(tick_mod.LockHeld, RuntimeError)
    params = inspect.signature(tick_mod.close).parameters
    assert params["wait_s"].default == 30.0
    assert params["sleep"].default is time.sleep


def test_close_under_a_held_lock_raises_and_writes_nothing(tmp_path):
    _queued_order(tmp_path)
    before = _work(tmp_path).read_bytes()
    lock = _hold_lock(tmp_path)
    lock_bytes = lock.read_bytes()
    with pytest.raises(tick_mod.LockHeld):
        tick_mod.close(tmp_path, ORDER, outcome="answered", wait_s=0,
                       sleep=_never_sleep)
    assert _work(tmp_path).read_bytes() == before, "nothing written"
    assert lock.exists() and lock.read_bytes() == lock_bytes, \
        "a lock this call did not take is never dropped"
    assert [r["note"] for r in fi.pending_work(tmp_path)] == [ORDER]


def test_close_waits_a_bounded_time_in_short_polls_then_raises(tmp_path):
    _queued_order(tmp_path)
    before = _work(tmp_path).read_bytes()
    lock = _hold_lock(tmp_path)
    sleeps = _Sleeps()
    with pytest.raises(tick_mod.LockHeld):
        tick_mod.close(tmp_path, ORDER, wait_s=2.0, sleep=sleeps)
    assert sleeps.calls, "a held lock is polled, not failed at once"
    assert all(0 < s <= 0.5 for s in sleeps.calls), "polls about every 0.5 s"
    assert sum(sleeps.calls) == pytest.approx(2.0), "the wait is bounded by wait_s"
    assert _work(tmp_path).read_bytes() == before
    assert lock.exists()


def test_close_waits_then_succeeds_when_the_lock_is_released(tmp_path):
    p = _queued_order(tmp_path)
    lock = _hold_lock(tmp_path)
    sleeps = _Sleeps(on={2: lock.unlink})
    done = tick_mod.close(tmp_path, ORDER, outcome="answered", wait_s=30.0,
                          sleep=sleeps)
    assert len(sleeps.calls) == 2, "the poll stops as soon as the lock is free"
    assert [(d["op"], d["note"], d["sha256"]) for d in done] == \
        [("done", ORDER, _sha(p))]
    assert fi.pending_work(tmp_path) == []
    assert not lock.exists(), "the lock close() took is released"


def test_close_takes_and_releases_the_lock_on_success(tmp_path, monkeypatch):
    _queued_order(tmp_path)
    in_pending = _lock_seen_by(monkeypatch, "pending_work")
    in_done = _lock_seen_by(monkeypatch, "mark_work_done")
    done = tick_mod.close(tmp_path, ORDER, outcome="answered", sleep=_never_sleep)
    assert len(done) == 1
    assert in_pending == [os.getpid()], "pending_work is read under the lock"
    assert in_done == [os.getpid()], "mark_work_done appends under the lock"
    assert not (tmp_path / tick_mod.LOCK_REL).exists()


def test_close_with_no_matching_row_takes_and_releases_the_lock(tmp_path, monkeypatch):
    _queued_order(tmp_path)
    before = _work(tmp_path).read_bytes()
    in_pending = _lock_seen_by(monkeypatch, "pending_work")
    assert tick_mod.close(tmp_path, "2026-10-07-0000-from-MAIN-ORDER-to-RC-nope.md",
                          sleep=_never_sleep) == []
    assert in_pending == [os.getpid()]
    assert _work(tmp_path).read_bytes() == before
    assert not (tmp_path / tick_mod.LOCK_REL).exists()


def test_close_releases_the_lock_when_mark_work_done_raises(tmp_path, monkeypatch):
    _queued_order(tmp_path)

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(fi, "mark_work_done", boom)
    with pytest.raises(OSError, match="disk full"):
        tick_mod.close(tmp_path, ORDER, sleep=_never_sleep)
    assert not (tmp_path / tick_mod.LOCK_REL).exists(), "released in a finally"
    assert [r["note"] for r in fi.pending_work(tmp_path)] == [ORDER]


def test_a_stale_lock_does_not_block_close(tmp_path):
    _queued_order(tmp_path)
    lock = _hold_lock(tmp_path, ts=time.time() - tick_mod.LOCK_STALE_S - 60)
    done = tick_mod.close(tmp_path, ORDER, wait_s=0, sleep=_never_sleep)
    assert len(done) == 1
    assert fi.pending_work(tmp_path) == []
    assert not lock.exists(), "the reclaimed lock is released after the close"


def test_close_with_an_empty_note_name_returns_empty(tmp_path):
    assert tick_mod.close(tmp_path, "", wait_s=0, sleep=_never_sleep) == []
    assert tick_mod.close(tmp_path, None, wait_s=0, sleep=_never_sleep) == []
    assert not (tmp_path / tick_mod.LOCK_REL).exists()
    lock = _hold_lock(tmp_path)
    assert tick_mod.close(tmp_path, "", wait_s=0, sleep=_never_sleep) == []
    assert lock.exists()


def test_cli_done_under_a_held_lock_exits_3_and_writes_nothing(tmp_path, monkeypatch,
                                                               capsys):
    _queued_order(tmp_path)
    capsys.readouterr()
    before = _work(tmp_path).read_bytes()
    lock = _hold_lock(tmp_path)
    monkeypatch.setattr(tick_mod, "tick", _no_tick)
    monkeypatch.setattr(tick_mod, "close",
                        functools.partial(tick_mod.close, wait_s=0, sleep=_never_sleep))
    rc = tick_mod.main(["--root", str(tmp_path), "--done", ORDER, "--outcome", "x"])
    assert rc == 3, "3 = lock held; 1 stays 'no pending row'"
    cap = capsys.readouterr()
    assert cap.out == ""
    assert cap.err == ("inbox_tick: pass held by another fire, --done not applied; "
                       "retry\n")
    cap.err.encode("ascii")
    assert _work(tmp_path).read_bytes() == before
    assert lock.exists()
    assert not (tmp_path / tick_mod.LAST_REL).exists()
    lock.unlink()
    assert tick_mod.main(["--root", str(tmp_path), "--done", ORDER]) == 0
    assert fi.pending_work(tmp_path) == []


# ---- RM-689 (b): migrate_legacy tolerates a BOM, reports undecodable lines ----
#
# Root cause: _legacy_doc json.loads(chunk.decode("utf-8")) failed on a line led
# by a UTF-8 BOM (PowerShell 5.1 writes one), so a BOM-led legacy row was left
# unconverted, invisible to the kit reader; a non-UTF-8 line was kept but never
# reported.

BOM = b"\xef\xbb\xbf"


def _raw_lines(root: Path, chunks: list) -> bytes:
    raw = b"".join(chunks)
    path = _work(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _legacy_open(note, prov=True) -> bytes:
    doc = {"ts": "2026-10-05T03:10:00-05:00", "note": note, "cls": "ORDER",
           "sender": "MAIN", "hop": 1, "state": "open"}
    if prov:
        doc["provenance"] = "main-verified"
    return (json.dumps(doc) + "\n").encode("ascii")


def _legacy_done(note) -> bytes:
    return (json.dumps({"ts": "2026-10-08T14:17:00-05:00", "note": note, "cls": "FIX",
                        "sender": "MAIN", "state": "done", "outcome": "answered 1431",
                        "by": "session 104"}) + "\n").encode("ascii")


def _kit_queued(note, sha) -> bytes:
    return (json.dumps({"ts": "2026-10-06T22:37:00-05:00", "op": "queued", "note": note,
                        "sha256": sha, "cls": "RULING", "sender": "MAIN", "hop": 1})
            + "\n").encode("ascii")


def _notes(root: Path) -> tuple:
    inbox = root / tick_mod.INBOX_DIR
    a = _note(inbox, NOTE_A, "# From MAIN - ORDER A\n", 1)
    b = _note(inbox, NOTE_B, "# From MAIN - FIX B\n", 2)
    c = _note(inbox, NOTE_C, "# From MAIN - RULING C\n", 3)
    return a, b, c


def test_bom_led_legacy_rows_are_converted(tmp_path):
    a, _b, _c = _notes(tmp_path)
    raw = _raw_lines(tmp_path, [BOM + _legacy_open(NOTE_A), _legacy_open(NOTE_B),
                                BOM + _legacy_done(NOTE_B)])
    assert fi.pending_work(tmp_path) == []
    res = tick_mod.migrate_legacy(tmp_path)
    assert (res["legacy"], res["queued"], res["done"]) == (3, 2, 1)
    assert res["undecodable"] == []
    assert Path(res["backup"]).read_bytes() == raw
    out = _work(tmp_path).read_bytes()
    assert BOM not in out, "the BOM does not survive into the kit lines"
    out.decode("ascii")
    (row,) = tick_mod.pending(tmp_path)
    assert row["note"] == NOTE_A and row["sha256"] == _sha(a)
    assert row["provenance"] == "main-verified"
    assert NOTE_B not in [r["note"] for r in fi.pending_work(tmp_path)]
    (b_done,) = [d for d in _work_lines(tmp_path) if d["op"] == "done"]
    assert b_done["note"] == NOTE_B
    assert b_done["outcome"] == "answered 1431 [by session 104]"


def test_a_bom_led_legacy_line_converts_exactly_like_the_bare_line(tmp_path):
    outs = []
    for sub, bom in (("bare", b""), ("bom", BOM)):
        root = tmp_path / sub
        _notes(root)
        _raw_lines(root, [bom + _legacy_open(NOTE_A), bom + _legacy_done(NOTE_B)])
        assert tick_mod.migrate_legacy(root)["legacy"] == 2
        outs.append(_work(root).read_bytes())
    assert outs[0] == outs[1]


def test_bom_led_non_legacy_lines_stay_byte_for_byte(tmp_path):
    _a, _b, c = _notes(tmp_path)
    kit = BOM + _kit_queued(NOTE_C, _sha(c))
    junk = BOM + b"not json at all\n"
    _raw_lines(tmp_path, [kit, _legacy_open(NOTE_A), junk])
    res = tick_mod.migrate_legacy(tmp_path)
    assert res["legacy"] == 1 and res["undecodable"] == []
    chunks = _work(tmp_path).read_bytes().splitlines(keepends=True)
    assert chunks[0] == kit and chunks[-1] == junk


def test_undecodable_lines_are_kept_in_place_and_reported(tmp_path):
    a, _b, c = _notes(tmp_path)
    bad_json = b'{"state": "open", "note": "x\xff"}\n'
    bad_raw = b"\xff\xfe junk\n"
    kit_c = _kit_queued(NOTE_C, _sha(c))
    raw = _raw_lines(tmp_path, [
        _legacy_open(NOTE_A),          # 1 -> queued + rc-provenance
        bad_json,                      # 2 undecodable
        _legacy_open(NOTE_B, False),   # 3 -> queued
        bad_raw,                       # 4 undecodable
        kit_c,                         # 5 kit line
        _legacy_done(NOTE_B),          # 6 -> done
    ])
    res = tick_mod.migrate_legacy(tmp_path)
    assert (res["legacy"], res["queued"], res["done"]) == (3, 2, 1)
    assert res["undecodable"] == [2, 4]
    assert Path(res["backup"]).read_bytes() == raw
    chunks = _work(tmp_path).read_bytes().splitlines(keepends=True)
    assert len(chunks) == 7
    assert chunks[2] == bad_json and chunks[4] == bad_raw, "kept byte-for-byte in place"
    assert chunks[5] == kit_c
    ops = [json.loads(chunks[i])["op"] for i in (0, 1, 3, 6)]
    assert ops == ["queued", "rc-provenance", "queued", "done"]
    pend = tick_mod.pending(tmp_path)
    assert [r["note"] for r in pend] == [NOTE_A, NOTE_C]
    assert pend[0]["sha256"] == _sha(a)


def test_an_undecodable_only_file_writes_nothing_and_reports(tmp_path):
    _a, _b, c = _notes(tmp_path)
    raw = _raw_lines(tmp_path, [_kit_queued(NOTE_C, _sha(c)), b"\xff\xfe junk\n",
                                b"this is not json {\n", BOM + b"\xff\n"])
    res = tick_mod.migrate_legacy(tmp_path)
    assert res["legacy"] == 0 and res["backup"] is None and res["locked"] is False
    assert res["undecodable"] == [2, 4]
    assert _work(tmp_path).read_bytes() == raw
    assert not list(_work(tmp_path).parent.glob("*.bak"))
    assert not (tmp_path / tick_mod.LOCK_REL).exists()


def test_undecodable_is_always_present_and_empty_when_clean(tmp_path):
    assert tick_mod.migrate_legacy(tmp_path / "missing")["undecodable"] == []
    _legacy_fixture(tmp_path)
    assert tick_mod.migrate_legacy(tmp_path)["undecodable"] == []
    assert tick_mod.migrate_legacy(tmp_path)["undecodable"] == [], "the no-op rerun"
    _hold_lock(tmp_path)
    held = tick_mod.migrate_legacy(tmp_path)
    assert held["locked"] is True and held["undecodable"] == []


def test_cli_migrate_legacy_prints_the_undecodable_notice(tmp_path, monkeypatch, capsys):
    _notes(tmp_path)
    _raw_lines(tmp_path, [_legacy_open(NOTE_A), b"\xff\n", _legacy_done(NOTE_B),
                          b'{"note": "\xfe"}\n'])
    monkeypatch.setattr(tick_mod, "tick", _no_tick)
    assert tick_mod.main(["--root", str(tmp_path), "--migrate-legacy"]) == 0
    cap = capsys.readouterr()
    res = json.loads(cap.out.strip().splitlines()[-1])
    assert res["legacy"] == 2 and res["undecodable"] == [2, 4]
    assert cap.err == "inbox_tick: 2 undecodable line(s) kept byte-for-byte: 2, 4\n"
    cap.err.encode("ascii")
    assert tick_mod.main(["--root", str(tmp_path), "--migrate-legacy"]) == 0
    again = capsys.readouterr()
    assert json.loads(again.out.strip().splitlines()[-1])["undecodable"] == [3, 5], \
        "the rerun still reports the kept lines, numbered in the file as it now is"
    assert again.err == "inbox_tick: 2 undecodable line(s) kept byte-for-byte: 3, 5\n"
    _hold_lock(tmp_path)
    assert tick_mod.main(["--root", str(tmp_path), "--migrate-legacy"]) == 1
    assert capsys.readouterr().err == "", "the locked run reports nothing undecodable"


def test_cli_migrate_legacy_on_a_clean_file_prints_no_notice(tmp_path, monkeypatch,
                                                             capsys):
    _legacy_fixture(tmp_path)
    monkeypatch.setattr(tick_mod, "tick", _no_tick)
    assert tick_mod.main(["--root", str(tmp_path), "--migrate-legacy"]) == 0
    assert capsys.readouterr().err == ""

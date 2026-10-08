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

import hashlib
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
    assert tick_mod.migrate_legacy(tmp_path) == {"locked": True, "legacy": 0}
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

"""MAIN 2026-10-08 2246 ORDER section 7 (kit v13) + FLEET-COMMON 10 / 14 e.

Measured before this slice: the last ops/loop/control/headless_usage.jsonl row
was 2026-10-04 (kit 4, no `kind`) and inbox_status.json was stale since
2026-10-07 22:12 while the inbox tick fired every 5 minutes, because
ops/loop/inbox_tick.py never wrote the status file (only fleet_route did).

What is pinned here:
- inbox_tick refreshes the live status file through the KIT's own
  fleet_headless.write_status on EVERY non-dry tick, including a tick with
  nothing to do: "running" / "Checking Inbox" during the pass, then "idle" /
  "Idle" (or "halted" / "Halted" under the responder STOP flag) at the end,
  with next_tick when the caller names its cadence (the CLI: 5 min);
- a dry tick writes no status, a tick that finds the lock held leaves the
  holder's status alone, a pass fault still ends "idle", and a status-write
  fault is a summary error, never a failed tick;
- every fleet_route spawn logs a usage row with a kit `kind` and a NON-EMPTY
  note label (a caller that names no note is labelled by its caller), and a
  fleet_route loaded from a linked worktree still writes budget / status /
  usage in the MAIN checkout (kit main_checkout), the child staying in the
  worktree.

Every root is a tmp dir; no live control file is touched and no process starts.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from ops.loop import fleet_route

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


tick_mod = _load("rc_loop_inbox_tick_status_s7_test", ROOT / "ops" / "loop" / "inbox_tick.py")
fh = tick_mod.fleet_headless
STATUS = fh.STATUS_REL
USAGE = fh.USAGE_REL
BUDGET = fh.BUDGET_REL
NOW = datetime(2026, 10, 7, 22, 0, 0)
TRIAGE_NOTE = "2026-10-07-1000-from-SS-QUESTION-to-RC-a.md"


def _record():
    return {
        "schema": tick_mod.AGREEMENT_SCHEMA,
        "counterparties": ["MAIN", "SS"],
        "main": {"code": "MAIN", "outbox": "X:/main/moon_sync_outbox"},
        "budget": "kit",
        "expires": "2026-11-01T00:00:00",
    }


def _note(inbox: Path, name: str, body: str = "# x\n", mtime: float = 1.0) -> Path:
    import os
    inbox.mkdir(parents=True, exist_ok=True)
    p = inbox / name
    p.write_text(body, encoding="ascii", newline="\n")
    os.utime(p, (mtime, mtime))
    return p


def _tick(root, **kw):
    kw.setdefault("inbox", root / "inbox")
    kw.setdefault("agreement", _record())
    kw.setdefault("participants", {"SS": root / "sib" / "SS"})
    kw.setdefault("retired", set())
    kw.setdefault("verify", lambda note, outbox: True)
    kw.setdefault("now", NOW)
    return tick_mod.tick(root, **kw)


def _status(root: Path) -> dict:
    return json.loads((root / STATUS).read_text(encoding="ascii"))


def _usage(root: Path) -> list:
    return [json.loads(x) for x in (root / USAGE).read_text(encoding="ascii").splitlines() if x]


class _Spy:
    """A triage spawn seam that snapshots the status file at call time."""

    def __init__(self, text="VERDICT: NOREPLY", exc=None):
        self.text, self.exc, self.calls, self.status_seen = text, exc, [], []

    def __call__(self, root, code, prompt, **kw):
        self.calls.append(kw)
        p = Path(root) / STATUS
        self.status_seen.append(json.loads(p.read_text(encoding="ascii"))
                                if p.exists() else None)
        if self.exc is not None:
            raise self.exc
        return {"rc": 0, "result": self.text}


# ---- inbox_tick: the status file on EVERY tick --------------------------------

def test_an_empty_tick_still_refreshes_the_status_file(tmp_path):
    before = time.time()
    s = _tick(tmp_path, spawn=_Spy())
    assert s["unseen"] == 0 and s["errors"] == []
    st = _status(tmp_path)
    assert st["schema"] == 1 and st["kit"] == fh.KIT_VERSION and st["code"] == "RC"
    assert st["state"] == "idle" and st["task"] == "Idle"
    updated = datetime.fromisoformat(st["updated"]).timestamp()
    assert updated >= before - 2, "the status names THIS tick, not a stale one"
    assert st["next_tick"] is None, "a tick that names no cadence claims no next tick"


def test_a_second_tick_refreshes_the_updated_stamp(tmp_path):
    _tick(tmp_path, spawn=_Spy())
    p = tmp_path / STATUS
    stale = _status(tmp_path)
    stale["updated"] = "2026-10-07T22:12:43-05:00"
    p.write_text(json.dumps(stale), encoding="ascii")
    _tick(tmp_path, spawn=_Spy())
    assert _status(tmp_path)["updated"] != "2026-10-07T22:12:43-05:00"


def test_the_tick_names_its_next_tick_when_given_a_cadence(tmp_path):
    before = time.time()
    _tick(tmp_path, spawn=_Spy(), next_tick_s=300)
    nt = datetime.fromisoformat(_status(tmp_path)["next_tick"]).timestamp()
    assert before + 290 <= nt <= time.time() + 310


def test_the_status_reads_checking_inbox_during_the_pass(tmp_path):
    _note(tmp_path / "inbox", TRIAGE_NOTE)
    spy = _Spy()
    s = _tick(tmp_path, spawn=spy)
    assert s["triaged"] == 1, s
    (during,) = spy.status_seen
    assert during is not None, "the pass wrote the status before its first spawn"
    assert during["state"] == "running" and during["task"] == "Checking Inbox"
    assert _status(tmp_path)["state"] == "idle"


def test_the_stop_flag_reads_halted(tmp_path):
    stop = tmp_path / tick_mod.STOP_REL
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("stop\n", encoding="ascii")
    _tick(tmp_path, spawn=_Spy())
    st = _status(tmp_path)
    assert st["state"] == "halted" and st["task"] == "Halted"


def test_a_dry_tick_writes_no_status(tmp_path):
    _note(tmp_path / "inbox", TRIAGE_NOTE)
    _tick(tmp_path, spawn=_Spy(), dry=True)
    assert not (tmp_path / STATUS).exists()


def test_a_held_lock_leaves_the_holders_status_alone(tmp_path):
    lock = tmp_path / tick_mod.LOCK_REL
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"pid": 1, "ts": time.time()}), encoding="ascii")
    held = b'{"state": "running", "task": "Running Session"}'
    (tmp_path / STATUS).write_bytes(held)
    s = _tick(tmp_path, spawn=_Spy())
    assert s["locked"] is True
    assert (tmp_path / STATUS).read_bytes() == held


def test_a_pass_fault_still_ends_idle_and_drops_the_lock(tmp_path):
    _note(tmp_path / "inbox", TRIAGE_NOTE)
    with pytest.raises(RuntimeError):
        _tick(tmp_path, spawn=_Spy(exc=RuntimeError("seam fault")))
    assert _status(tmp_path)["state"] == "idle"
    assert not (tmp_path / tick_mod.LOCK_REL).exists()


def test_a_status_write_fault_is_a_summary_error_not_a_failed_tick(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(tick_mod.fleet_headless, "write_status", boom)
    s = _tick(tmp_path, spawn=_Spy())
    assert s["unseen"] == 0
    assert any(e.startswith("status:") for e in s["errors"]), s["errors"]
    assert not (tmp_path / tick_mod.LOCK_REL).exists()


def test_the_status_goes_through_the_kits_own_writer(tmp_path, monkeypatch):
    calls = []
    real = tick_mod.fleet_headless.write_status

    def spy(root, code, state, task, *a, **k):
        calls.append((Path(root), code, state, task))
        return real(root, code, state, task, *a, **k)

    monkeypatch.setattr(tick_mod.fleet_headless, "write_status", spy)
    _tick(tmp_path, spawn=_Spy())
    assert [c[2:] for c in calls] == [("running", "Checking Inbox"), ("idle", "Idle")]
    assert all(c[0] == tmp_path and c[1] == "RC" for c in calls)
    for _r, _c, state, task in calls:
        assert state in fh.STATES and task in fh.TASKS


def test_fire_step_refreshes_the_status_file(tmp_path):
    lp = _load("rc_loop_lane_progress_status_s7_test", ROOT / "ops" / "loop" / "lane_progress.py")
    prog = lp.LaneProgress.for_lane(1, 3, [("I1", tick_mod.STEP_TASK)], root=tmp_path,
                                    emit=lambda _s: None)
    prog.start()
    tick_mod.fire_step(prog, root=tmp_path, inbox=tmp_path / "inbox", agreement=None,
                       participants={}, retired=set(), spawn=_Spy(), now=NOW)
    assert _status(tmp_path)["state"] == "idle"


def test_the_cli_tick_names_the_responders_five_minute_cadence(tmp_path):
    before = time.time()
    assert tick_mod.main(["--root", str(tmp_path)]) == 0
    st = _status(tmp_path)
    assert st["state"] == "idle"
    nt = datetime.fromisoformat(st["next_tick"]).timestamp()
    assert before + tick_mod.TICK_S - 10 <= nt <= time.time() + tick_mod.TICK_S + 10
    assert tick_mod.TICK_S == 300


# ---- fleet_route: every usage row carries a kind and a non-empty label ---------

class _Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        return CompletedProcess(args=argv, returncode=0,
                                stdout='{"result": "done", "usage": {"input_tokens": 1}}',
                                stderr="")


@pytest.fixture
def rec(monkeypatch):
    r = _Rec()
    monkeypatch.setattr(subprocess, "run", r)
    return r


def test_a_spawn_without_a_note_is_labelled_by_its_caller(rec, tmp_path):
    fleet_route.spawn("T", caller="ci_watchdog", root=tmp_path)
    (row,) = _usage(tmp_path)
    assert row["note"] == "ci_watchdog"
    assert row["kind"] in fh.KINDS, row["kind"]


def test_an_explicit_note_and_kind_reach_the_usage_row(rec, tmp_path):
    fleet_route.spawn("T", caller="run_lane", note="lane-ds", kind="build", root=tmp_path)
    (row,) = _usage(tmp_path)
    assert row["note"] == "lane-ds" and row["kind"] == "build"


def test_the_cli_without_note_labels_the_row_by_caller(rec, tmp_path, monkeypatch):
    monkeypatch.setattr(fleet_route, "ROOT", tmp_path)
    assert fleet_route.main(["--caller", "weekly_hygiene", "--prompt", "x"]) == 0
    (row,) = _usage(tmp_path)
    assert row["note"] == "weekly_hygiene" and row["kind"] in fh.KINDS


def _linked_worktree(tmp_path: Path):
    main = tmp_path / "main"
    gitdir = main / ".git" / "worktrees" / "lane-x"
    gitdir.mkdir(parents=True)
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {gitdir}\n", encoding="ascii")
    return main, wt


def test_a_worktree_copy_logs_usage_in_the_main_checkout(rec, tmp_path, monkeypatch):
    main, wt = _linked_worktree(tmp_path)
    monkeypatch.setattr(fleet_route, "ROOT", wt)
    fleet_route.spawn("T", caller="t", note="lane-x", kind="build")
    (_argv, kw), = rec.calls
    assert Path(kw["cwd"]).resolve() == wt.resolve(), "the child still runs in the worktree"
    assert (main / USAGE).is_file() and (main / STATUS).is_file() and (main / BUDGET).is_file()
    assert not (wt / "ops").exists(), "nothing lands in the worktree's control dir"
    (row,) = _usage(main)
    assert row["kind"] == "build" and row["note"] == "lane-x"


def test_a_worktree_copy_keeps_an_explicit_cwd(rec, tmp_path, monkeypatch):
    main, wt = _linked_worktree(tmp_path)
    other = tmp_path / "other"
    monkeypatch.setattr(fleet_route, "ROOT", wt)
    fleet_route.spawn("T", caller="t", note="n", cwd=other)
    (_argv, kw), = rec.calls
    assert kw["cwd"] == str(other)
    assert (main / USAGE).is_file()


def test_write_idle_from_a_worktree_lands_in_the_main_checkout(tmp_path, monkeypatch):
    main, wt = _linked_worktree(tmp_path)
    monkeypatch.setattr(fleet_route, "ROOT", wt)
    fleet_route.write_idle(300)
    assert json.loads((main / STATUS).read_text(encoding="ascii"))["state"] == "idle"
    assert not (wt / "ops").exists()


def test_the_main_tree_root_is_unchanged(rec, tmp_path, monkeypatch):
    monkeypatch.setattr(fleet_route, "ROOT", tmp_path)
    fleet_route.spawn("T", caller="t", note="n")
    (_argv, kw), = rec.calls
    assert kw["cwd"] == str(tmp_path)
    assert (tmp_path / USAGE).is_file()

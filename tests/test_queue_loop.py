# arch: tests for ops/loop/queue_loop.py (the queue-lane re-fire driver) | section=tests | frozen=no
"""Lane 10 - the driver that re-fires the `queue` worker cycle after cycle.

`lanes.py` decides WHO may run, `lane_launcher.py` turns a claim into a running
worker, and this driver is what makes a ONE-ROW worker into a queue drain. The
behaviours that matter are the ones that fail quietly:

- A stop sentinel must be honoured BEFORE cycle 1, not after it. A driver that
  checks only between cycles fires one unwanted worker on every start, which
  against the `queue` lane means one unwanted RM row executed and committed.
- The lane must be released on EVERY path. The driver holds the lock across a
  multi-hour worker; a leak reads RUNNING to every poller and wedges the whole
  roster, since MAX_SLOTS is 1 and the lanes are mutually exclusive.
- A refused acquire is a NORMAL answer, never an error. `try_acquire_lane`
  returns `{"ok": False, "refused": "lane_held"}` when the operator has fired
  another lane, and a driver that treats that as fatal dies overnight the first
  time the two overlap by one minute.
- The timeout kill must fire exactly ONCE. Two kills against a reissued pid is
  the pid-reuse hazard `lanes.proc_started` exists for (MEASURED 2026-08-02:
  Windows handed a dead lane worker's pid 8820 to SearchFilterHost three
  minutes later).

Nothing here spawns a process, sleeps, or touches the live control plane: every
external dependency of `run_cycle` is an injected seam, and every control /
report directory is a `tmp_path`. That last point is load-bearing rather than
tidy - the REAL `ops/loop/control/STOP` exists on disk right now (content:
"operator halt via LW session 2026-07-28"), so a test that let `stop_reason`
fall through to the default CONTROL dir would pass for the wrong reason.
"""
from __future__ import annotations

import ast
import contextlib
import importlib
import inspect
import json
import time

import pytest

qloop = importlib.import_module("ops.loop.queue_loop")
lanes = importlib.import_module("ops.loop.lanes")
launcher = importlib.import_module("ops.loop.lane_launcher")


# --------------------------------------------------------------------------- fakes
def _seams(*, pid=4242, alive_ticks=0, refuse_times=0, refuse_forever=False,
           launch_exc=None, alive_exc=None, tick=1.0, kill_takes=True):
    """Every external dependency of `run_cycle`, faked and recorded.

    `alive_ticks` is how many polls the worker survives; -1 means it never dies
    (the timeout path). `refuse_times` is how many acquires answer `lane_held`
    before one succeeds; `refuse_forever` never lets go.

    `kill_takes` models what a real `taskkill /F /T` normally does: the process
    STOPS BEING ALIVE. The fake used to leave it running, which no old test
    could notice because the driver killed, broke out of the wait and never
    probed again - the unverified-kill defect itself. `kill_takes=False` is the
    case that defect was hiding: access denied, or a re-parented subagent that
    outlives the wrapper whose pid was killed.

    `log["events"]` is the ORDERED interleaving of alive-probes and kills, which
    is the only way to assert that a probe happened AFTER a kill rather than
    merely that both happened.
    """
    log = {"acquire": [], "release": [], "launch": [], "kill": [], "sleep": [],
           "events": []}
    state = {"clock": 1000.0, "mono": 0.0, "alive": alive_ticks}

    def acquire(lane, *, run_id, worktree, **kw):
        log["acquire"].append({"lane": lane, "run_id": run_id, "worktree": worktree})
        if refuse_forever or len(log["acquire"]) <= refuse_times:
            return {"ok": False, "refused": "lane_held", "holder": "ds", "pid": 999}
        return {"ok": True, "lane": lane, "run_id": run_id,
                "worktree": worktree, "token": f"TOKEN-{run_id}"}

    def release(token, **kw):
        log["release"].append(token)
        return True

    def launch(lane, *, run_id, token, **kw):
        log["launch"].append({"lane": lane, "run_id": run_id, "token": token})
        if launch_exc is not None:
            raise launch_exc
        return {"lane": lane, "run_id": run_id, "pid": pid, "worktree": "wt",
                "log": "log", "prompt": "prompt", "started_at": state["clock"]}

    def alive(probe_pid):
        if alive_exc is not None:
            raise alive_exc
        log["events"].append(("alive", probe_pid))
        if state["alive"] == -1:
            return True
        if state["alive"] > 0:
            state["alive"] -= 1
            return True
        return False

    def kill(probe_pid):
        log["kill"].append(probe_pid)
        log["events"].append(("kill", probe_pid))
        if kill_takes:
            state["alive"] = 0

    def sleep(seconds):
        log["sleep"].append(seconds)

    def clock():
        state["clock"] += tick
        return state["clock"]

    def monotonic():
        # A SECOND, independent source. The driver stamps records with `clock`
        # and measures deadlines with this one, so a test that freezes the wall
        # clock must still see the deadline advance.
        state["mono"] += tick
        return state["mono"]

    return log, {"acquire": acquire, "release": release, "launch": launch,
                 "alive": alive, "kill": kill, "sleep": sleep, "clock": clock,
                 "monotonic": monotonic}


def _mono(start=0.0, tick=1.0):
    """A monotonic source that ADVANCES, independent of the wall-clock seam.

    Separate from `_seams`' own so a test can freeze the wall clock and still
    have the deadline progress - which is the whole point of the two-clock
    split.
    """
    state = {"t": float(start)}

    def monotonic():
        state["t"] += float(tick)
        return state["t"]

    return monotonic


def _loop_seams(**kw):
    """`_seams` plus the CI-gate seams, for `run_loop` callers only.

    They are NOT in `_seams` itself because `run_cycle` does not take them, and
    a shared dict would break every `run_cycle(1, **seams)` call in this file.

    The default `head_sha` answers the SAME sha every time, so the gate reads
    "no push detected" and returns before it ever reaches `gh`. That is what
    keeps the dozen tests which are not about CI hermetic without each one
    having to script a fake CI run - and `gh` is wired to an AssertionError so
    a future change that reaches it fails loudly instead of shelling out.
    """
    log, seams = _seams(**kw)
    log["gh"] = []

    def gh(args):
        log["gh"].append(list(args))
        raise AssertionError(f"no test may shell out to gh: {list(args)}")

    seams["head_sha"] = lambda: "cafe1234"
    seams["gh"] = gh
    return log, seams


def _heads(*shas):
    """A `head_sha` seam walking a scripted list, repeating the last answer.

    The driver reads it before and after each cycle: an UNCHANGED answer is the
    only push signal a driver that never looks inside the lane worktree can
    have, so a test that wants the gate to fire must move it.
    """
    seq = list(shas)

    def head_sha():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return head_sha


def _new_head_every_call():
    """A `head_sha` that never repeats - every cycle looks like a real push."""
    state = {"n": 0}

    def head_sha():
        state["n"] += 1
        return f"sha{state['n']:04d}"

    return head_sha


def _fake_wait(step="success", *, record=None):
    """A `wait_for_ci` seam returning a fixed verdict and recording its kwargs."""
    seen = [] if record is None else record

    def wait(sha, **kw):
        seen.append({"sha": sha, **kw})
        return {"sha": sha, "run_id": 4242, "status": "completed", "step": step,
                "waited_s": 1.0, "detail": f"faked {step}"}

    return seen, wait


# --------------------------------------------------------------------------- constants
def test_the_lane_is_queue_and_the_lock_roster_knows_it():
    """A driver pointed at a lane the lock refuses would fail on every cycle."""
    assert qloop.LANE == "queue"
    assert qloop.LANE in lanes.LANES
    assert qloop.LANE in launcher.LANE_COMMANDS


def test_the_documented_defaults_are_the_shipped_defaults():
    """These are an operator-facing contract, so they get a guard, not a comment."""
    assert qloop.DEFAULT_MAX_CYCLES == 12
    # 14400 (4h), raised from 5400 on 2026-09-06. The kill has to sit ABOVE the
    # worst legitimate cycle, and a cycle is now work plus a CI block of up to
    # 90 minutes (RM-370 measured a real run at 67) plus up to another 90 on a
    # re-dispatch. Cycle 3 measured 83.8 minutes against the old 5400s kill.
    assert qloop.DEFAULT_CYCLE_TIMEOUT_S == 14400
    assert qloop.DEFAULT_CYCLE_TIMEOUT_S > 90 * 60 * 2, (
        "the kill must outlast a 90-minute block plus one re-dispatch, or it "
        "bounds legitimate work instead of a wedge")
    assert qloop.DEFAULT_SETTLE_S == 45
    assert qloop.DEFAULT_POLL_S == 10
    assert qloop.ACQUIRE_RETRIES == 20
    assert qloop.ACQUIRE_WAIT_S == 30


def test_stop_files_are_the_three_documented_sentinels():
    assert [p.name for p in qloop.STOP_FILES] == [
        "STOP", "QUEUE_STOP", "QUEUE_DRAINED"]
    assert qloop.STOP_FILES[0].parent == qloop.CONTROL
    assert qloop.STOP_FILES[1].parent == qloop.CONTROL / "lanes"
    assert qloop.STOP_FILES[2].parent == qloop.CONTROL / "lanes"
    assert qloop.CYCLE_LOG == qloop.REPORTS / "queue_loop.jsonl"


# --------------------------------------------------------------------------- stop_reason
def test_stop_reason_is_none_when_no_sentinel_exists(tmp_path):
    assert qloop.stop_reason(tmp_path) is None


def test_stop_reason_reads_the_GIVEN_control_dir_not_the_live_one(
        tmp_path, monkeypatch):
    """A hardcoded `CONTROL` would leak the live control plane into a caller's dir.

    HERMETIC ON PURPOSE, and the first cut was not. It asserted as a
    precondition that the live `ops/loop/control/STOP` existed - true on this
    box at the time (a stale 2026-07-28 halt) and FALSE everywhere else,
    including CI, where `ops/loop/control/` is gitignored and ships no
    sentinels at all. The test would have gone red the moment that file was
    cleared, which is exactly what happened when the queue lane was first
    fired. A test may never depend on machine state it does not create:
    `feedback_verifier_needs_a_frozen_tree` is the same lesson from the other
    side. The property under test is unchanged - it is now proven by planting
    a sentinel in a FAKE control dir and asserting a different dir stays clean.
    """
    fake_live = tmp_path / "live-control"
    fake_live.mkdir()
    (fake_live / "STOP").write_text("halt", encoding="utf-8")
    monkeypatch.setattr(qloop, "CONTROL", fake_live)

    caller_dir = tmp_path / "caller-control"
    caller_dir.mkdir()
    assert qloop.stop_reason(caller_dir) is None, (
        "stop_reason leaked the module-level CONTROL into a caller's dir")
    # ...and the fake live dir still answers when it IS the one asked about,
    # so the assertion above cannot pass by the sentinel simply being unreadable.
    assert qloop.stop_reason(fake_live) == "STOP"


@pytest.mark.parametrize("rel,expected", [
    ("STOP", "STOP"),
    ("lanes/QUEUE_STOP", "QUEUE_STOP"),
    ("lanes/QUEUE_DRAINED", "QUEUE_DRAINED"),
])
def test_stop_reason_names_whichever_sentinel_exists(tmp_path, rel, expected):
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("halt", encoding="utf-8")
    assert qloop.stop_reason(tmp_path) == expected


# --------------------------------------------------------------------------- run_cycle
def test_a_completed_cycle_launches_once_and_releases_the_lane(tmp_path):
    log, seams = _seams(alive_ticks=2)
    rec = qloop.run_cycle(1, cycle_timeout_s=10_000, poll_s=10, **seams)

    assert rec["outcome"] == "completed"
    assert rec["ok"] is True
    assert rec["pid"] == 4242
    assert rec["cycle"] == 1
    assert len(log["launch"]) == 1
    assert log["kill"] == [], "a worker that exited on its own must not be killed"
    assert len(log["release"]) == 1, "the lane must be released exactly once"


def test_the_record_carries_every_documented_field():
    log, seams = _seams(alive_ticks=1)
    rec = qloop.run_cycle(7, **seams)
    assert set(rec) == {"cycle", "run_id", "ok", "pid", "started_at",
                        "ended_at", "duration_s", "outcome", "detail"}
    assert rec["ended_at"] >= rec["started_at"]
    assert rec["duration_s"] >= 0


def test_the_cycle_claims_a_worktree_and_never_the_main_tree():
    """Worktree-mandatory (operator 2026-07-30) - the lock refuses the main tree,
    and a driver that handed it one would refuse on every single cycle."""
    log, seams = _seams(alive_ticks=0)
    qloop.run_cycle(1, **seams)
    claimed = log["acquire"][0]["worktree"]
    assert claimed
    assert str(claimed) != str(lanes.REPO_ROOT)
    assert str(claimed) == str(launcher.worktree_path(qloop.LANE))


def test_a_launch_error_is_recorded_not_raised_and_still_releases():
    log, seams = _seams(launch_exc=launcher.LaneLaunchError("git worktree add failed"))
    rec = qloop.run_cycle(3, **seams)

    assert rec["outcome"] == "launch_failed"
    assert rec["ok"] is False
    assert "worktree add failed" in rec["detail"]
    assert log["release"] == ["TOKEN-" + rec["run_id"]], (
        "a lane that never started must not stay locked")
    assert log["kill"] == []


def test_the_timeout_path_kills_exactly_once_and_records_timeout_killed():
    log, seams = _seams(alive_ticks=-1, tick=1.0)
    rec = qloop.run_cycle(2, cycle_timeout_s=3, poll_s=10, **seams)

    assert rec["outcome"] == "timeout_killed"
    assert rec["ok"] is False
    assert log["kill"] == [4242], "exactly one kill - a reissued pid must not be re-killed"
    assert len(log["release"]) == 1
    assert log["sleep"], "the wait must have polled rather than spun"
    assert all(s == 10 for s in log["sleep"])


def test_an_unexpected_exception_propagates_only_after_the_release():
    log, seams = _seams(alive_exc=RuntimeError("probe exploded"))
    with pytest.raises(RuntimeError, match="probe exploded"):
        qloop.run_cycle(1, **seams)
    assert len(log["release"]) == 1, (
        "the finally must free the lane before the fault escapes")


# --------------------------------------------------------------------------- refused acquire
def test_a_held_lane_retries_then_records_lane_held_without_dying():
    log, seams = _seams(refuse_forever=True)
    rec = qloop.run_cycle(1, acquire_retries=4, acquire_wait_s=30, **seams)

    assert rec["outcome"] == "lane_held"
    assert rec["ok"] is False
    assert rec["pid"] is None
    assert len(log["acquire"]) == 4, "every retry must be spent before giving up"
    assert log["sleep"] == [30, 30, 30], "no wait after the final attempt"
    assert log["launch"] == [], "a refused acquire must never launch"
    assert log["release"] == [], "there is no token to release"


def test_a_lane_freed_mid_retry_is_claimed_and_run():
    log, seams = _seams(refuse_times=2, alive_ticks=1)
    rec = qloop.run_cycle(1, acquire_retries=6, acquire_wait_s=30, **seams)
    assert rec["outcome"] == "completed"
    assert len(log["acquire"]) == 3
    assert len(log["launch"]) == 1


# --------------------------------------------------------------------------- jsonl ledger
def test_the_cycle_log_is_created_lazily_one_json_object_per_line(tmp_path):
    ledger = tmp_path / "not" / "made" / "yet" / "queue_loop.jsonl"
    log, seams = _loop_seams(alive_ticks=1)
    summary = qloop.run_loop(max_cycles=3, settle_s=45, poll_s=10,
                             control_dir=tmp_path / "control",
                             cycle_log=ledger, emit=lambda line: None, **seams)

    assert ledger.is_file(), "the ledger dir must be created on demand"
    lines = [ln for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 3
    parsed = [json.loads(ln) for ln in lines]
    assert [r["cycle"] for r in parsed] == [1, 2, 3]
    assert parsed == summary["records"]


def test_the_cycle_log_appends_and_never_rewrites(tmp_path):
    ledger = tmp_path / "queue_loop.jsonl"
    ledger.write_text('{"cycle": 0, "outcome": "from-a-previous-run"}\n', encoding="utf-8")
    log, seams = _loop_seams(alive_ticks=1)
    qloop.run_loop(max_cycles=2, control_dir=tmp_path / "control",
                   cycle_log=ledger, emit=lambda line: None, **seams)

    lines = [ln for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 3, "the prior run's row must survive"
    assert json.loads(lines[0])["outcome"] == "from-a-previous-run"


# --------------------------------------------------------------------------- run_loop
def test_run_loop_stops_exactly_at_max_cycles(tmp_path):
    log, seams = _loop_seams(alive_ticks=1)
    summary = qloop.run_loop(max_cycles=4, settle_s=45, poll_s=10,
                             control_dir=tmp_path, cycle_log=tmp_path / "l.jsonl",
                             emit=lambda line: None, **seams)
    assert summary["cycles_run"] == 4
    assert summary["stopped_by"] == "max_cycles"
    assert len(summary["records"]) == 4
    assert len(log["launch"]) == 4


def test_run_loop_settles_BETWEEN_cycles_and_not_after_the_last(tmp_path):
    log, seams = _loop_seams(alive_ticks=0)
    qloop.run_loop(max_cycles=3, settle_s=45, poll_s=10, control_dir=tmp_path,
                   cycle_log=tmp_path / "l.jsonl", emit=lambda line: None, **seams)
    assert log["sleep"].count(45) == 2, "3 cycles means 2 settles, never 3"


def test_a_stop_sentinel_before_cycle_one_runs_zero_cycles(tmp_path):
    (tmp_path / "lanes").mkdir()
    (tmp_path / "lanes" / "QUEUE_STOP").write_text("halt", encoding="utf-8")
    log, seams = _loop_seams(alive_ticks=1)
    summary = qloop.run_loop(max_cycles=5, control_dir=tmp_path,
                             cycle_log=tmp_path / "l.jsonl",
                             emit=lambda line: None, **seams)

    assert summary["cycles_run"] == 0
    assert summary["stopped_by"] == "QUEUE_STOP"
    assert log["acquire"] == [], "nothing may be claimed before the first check"
    assert log["launch"] == []


def test_a_drained_sentinel_written_mid_loop_stops_the_NEXT_cycle(tmp_path):
    """The worker signals an empty queue by dropping QUEUE_DRAINED as it exits.

    The cycle that wrote it is already finished and must still be recorded; the
    driver just must not fire another one.
    """
    drained = tmp_path / "lanes" / "QUEUE_DRAINED"
    drained.parent.mkdir(parents=True, exist_ok=True)
    log, seams = _loop_seams(alive_ticks=1)
    real_launch = seams["launch"]

    def launch_then_drain(lane, *, run_id, token, **kw):
        out = real_launch(lane, run_id=run_id, token=token, **kw)
        if len(log["launch"]) == 2:
            drained.write_text("queue empty", encoding="utf-8")
        return out

    seams["launch"] = launch_then_drain
    summary = qloop.run_loop(max_cycles=9, control_dir=tmp_path,
                             cycle_log=tmp_path / "l.jsonl",
                             emit=lambda line: None, **seams)

    assert summary["cycles_run"] == 2, "the cycle that drained the queue still counts"
    assert summary["stopped_by"] == "QUEUE_DRAINED"
    assert len(log["launch"]) == 2


def test_run_loop_emits_one_line_per_cycle(tmp_path):
    printed = []
    log, seams = _loop_seams(alive_ticks=0)
    qloop.run_loop(max_cycles=3, control_dir=tmp_path, cycle_log=tmp_path / "l.jsonl",
                   emit=printed.append, **seams)
    assert len(printed) == 3
    assert all("completed" in line for line in printed)


# --------------------------------------------------------------------------- main
def test_main_maps_every_flag_onto_run_loop(monkeypatch, tmp_path):
    seen = {}

    def fake_run_loop(**kw):
        seen.update(kw)
        return {"cycles_run": 0, "stopped_by": "max_cycles", "records": []}

    monkeypatch.setattr(qloop, "run_loop", fake_run_loop)
    # `singleton=contextlib.nullcontext` is MANDATORY, not tidiness: without it
    # this takes the REAL `Global\RC_QUEUE_LOOP_DRIVER` mutex, so it passes only
    # while no driver is running and returns EXIT_ALREADY_RUNNING (3) the moment
    # the lane is actually looping. MEASURED 2026-09-06 - it went red against a
    # live driver, which is the one state where the test matters least and the
    # loop matters most. A test may never depend on machine state it does not
    # create; the same lesson cost `stop_reason`'s test a rewrite an hour
    # earlier.
    rc = qloop.main(["--cycles", "3", "--settle", "7", "--poll", "2",
                     "--timeout", "99", "--lane", "queue",
                     "--control-dir", str(tmp_path / "c"),
                     "--reports-dir", str(tmp_path / "r")],
                    singleton=contextlib.nullcontext)
    assert rc == 0
    assert seen["max_cycles"] == 3
    assert seen["settle_s"] == 7
    assert seen["poll_s"] == 2
    assert seen["cycle_timeout_s"] == 99
    assert seen["lane"] == "queue"
    assert str(seen["control_dir"]) == str(tmp_path / "c")
    assert str(seen["cycle_log"]) == str(tmp_path / "r" / "queue_loop.jsonl")


def test_main_once_is_exactly_one_cycle(monkeypatch):
    seen = {}
    monkeypatch.setattr(qloop, "run_loop", lambda **kw: seen.update(kw) or
                        {"cycles_run": 1, "stopped_by": "max_cycles", "records": []})
    # Fake singleton for the same reason as the test above: the real mutex is
    # held whenever the lane is looping, and this test is about argument
    # parsing, not about who holds a lock.
    assert qloop.main(["--once", "--cycles", "50"],
                      singleton=contextlib.nullcontext) == 0
    assert seen["max_cycles"] == 1, "--once must win over --cycles"


# ===========================================================================
# Adversarial-gate findings, 2026-09-05. Every test below was RED against the
# driver as shipped, and each names the defect it closes. They are grouped by
# defect rather than by function because the defects span run_cycle / run_loop /
# main / the launcher.
# ===========================================================================

# ------------------------------------------------- 1. the kill is VERIFIED
def test_a_kill_that_takes_is_re_probed_before_it_is_called_timeout_killed():
    """The old code killed, broke out of the wait, and never looked again.

    `_taskkill` swallows its own failure on purpose (a kill that raised would
    turn one bad cycle into a dead driver), so the ONLY evidence the kill took
    is the liveness probe coming back false afterwards.
    """
    log, seams = _seams(alive_ticks=-1, tick=1.0)
    seams["monotonic"] = _mono(tick=1.0)
    rec = qloop.run_cycle(2, cycle_timeout_s=3, poll_s=10, kill_grace_s=30, **seams)

    assert rec["outcome"] == "timeout_killed"
    assert rec["ok"] is False
    assert log["kill"] == [4242], "still exactly one kill"
    events = log["events"]
    after_kill = events[events.index(("kill", 4242)) + 1:]
    assert ("alive", 4242) in after_kill, (
        "the kill must be re-probed, not assumed to have worked")


def test_a_kill_that_does_NOT_take_records_timeout_kill_failed():
    """taskkill can fail: access denied, or a re-parented subagent that
    outlives the wrapper whose pid was killed. The old code recorded
    `timeout_killed` either way, and cycle N+1 then fired a SECOND worker into
    the same lane worktree - the two-writers index corruption the module
    docstring calls unrecoverable.
    """
    log, seams = _seams(alive_ticks=-1, tick=1.0, kill_takes=False)
    seams["monotonic"] = _mono(tick=1.0)
    rec = qloop.run_cycle(2, cycle_timeout_s=3, poll_s=10, kill_grace_s=25, **seams)

    assert rec["outcome"] == "timeout_kill_failed"
    assert rec["ok"] is False
    assert log["kill"] == [4242], (
        "exactly one kill even here - a reissued pid must not be re-killed")
    assert "4242" in rec["detail"], "the operator needs the pid that survived"
    assert len(log["release"]) == 1, "the lane is still released on this path"


def test_the_kill_grace_polls_no_slower_than_the_grace_itself():
    """A 10s poll step against a 2s grace would sleep straight past the answer
    and report a failed kill that actually worked."""
    log, seams = _seams(alive_ticks=-1, tick=1.0, kill_takes=False)
    seams["monotonic"] = _mono(tick=1.0)
    rec = qloop.run_cycle(1, cycle_timeout_s=2, poll_s=10, kill_grace_s=2, **seams)

    assert rec["outcome"] == "timeout_kill_failed"
    assert [s for s in log["sleep"] if s != 10] == [2]


def test_run_loop_STOPS_the_whole_loop_when_the_kill_did_not_take(tmp_path):
    """Never fire another cycle into a worktree that may still have a live
    writer. Ending the night early is a cost; a corrupted index is not."""
    log, seams = _loop_seams(alive_ticks=-1, tick=1.0, kill_takes=False)
    seams["monotonic"] = _mono(tick=1.0)
    summary = qloop.run_loop(max_cycles=6, cycle_timeout_s=3, poll_s=10,
                             kill_grace_s=20, settle_s=45, control_dir=tmp_path,
                             cycle_log=tmp_path / "l.jsonl",
                             emit=lambda line: None, **seams)

    assert summary["cycles_run"] == 1
    assert summary["stopped_by"] == "timeout_kill_failed"
    assert len(log["launch"]) == 1, "no second worker into a worktree with a live writer"
    assert 45 not in log["sleep"], "it must stop, not settle and carry on"


# ------------------------------------------- 2. the deadline is MONOTONIC
def test_the_deadline_uses_monotonic_and_the_record_still_uses_wall_time():
    """Two clocks on purpose: a JSONL row an operator reads at 3am needs wall
    time, and a deadline needs a clock that cannot step backward."""
    params = inspect.signature(qloop.run_cycle).parameters
    assert params["clock"].default is time.time
    assert params["monotonic"].default is time.monotonic
    assert inspect.signature(qloop.run_loop).parameters["monotonic"].default is time.monotonic


def test_a_frozen_wall_clock_no_longer_prevents_the_timeout():
    """MEASURED by the gate: with `clock` frozen, run_cycle never terminated and
    had to be killed at RC=124, because the deadline was `clock() >= started_at
    + timeout` against a clock that never moved. `time.time` is not monotonic,
    so an NTP step backward does the same thing to a real overnight run.
    """
    log, seams = _seams(alive_ticks=-1, tick=0.0)      # a wall clock that never moves
    seams["monotonic"] = _mono(tick=1.0)
    probed = {"n": 0}
    real_alive = seams["alive"]

    def bounded_alive(pid):
        probed["n"] += 1
        # A HARD bound, so a regression fails this test instead of hanging the
        # suite the way the gate's own probe hung.
        assert probed["n"] < 500, "run_cycle did not terminate under a frozen clock"
        return real_alive(pid)

    seams["alive"] = bounded_alive
    rec = qloop.run_cycle(1, cycle_timeout_s=5, poll_s=10, kill_grace_s=5, **seams)

    assert rec["outcome"] == "timeout_killed"
    assert rec["started_at"] == rec["ended_at"], "the wall clock really was frozen"


def test_the_deadline_is_charged_from_LAUNCH_not_from_cycle_start():
    """`started_at` was taken BEFORE the acquire-retry loop, so up to
    ACQUIRE_RETRIES * ACQUIRE_WAIT_S (600s) of legitimate waiting for another
    lane was billed to the worker's budget."""
    log, seams = _seams(refuse_times=3, alive_ticks=2, tick=1.0)
    now = {"t": 0.0}
    seams["monotonic"] = lambda: now["t"]
    real_acquire, real_alive = seams["acquire"], seams["alive"]

    def slow_acquire(lane, **kw):
        now["t"] += 30.0          # one ACQUIRE_WAIT_S of patience per refusal
        return real_acquire(lane, **kw)

    def slow_alive(pid):
        now["t"] += 20.0          # the worker itself runs 60s across three polls
        return real_alive(pid)

    seams["acquire"], seams["alive"] = slow_acquire, slow_alive
    rec = qloop.run_cycle(1, cycle_timeout_s=100, poll_s=10, acquire_retries=6,
                          acquire_wait_s=30, kill_grace_s=5, **seams)

    assert rec["outcome"] == "completed"
    assert log["kill"] == [], (
        "180s of monotonic time passed but 120s of it was waiting for another "
        "lane - charging that to the worker kills a healthy run")


def test_the_timeout_detail_states_the_TRUE_elapsed_worker_time():
    """The old message read `worker still alive after {cycle_timeout_s}s`,
    which was the BUDGET, not the elapsed time - false by up to the ten minutes
    of acquire patience that preceded the launch."""
    log, seams = _seams(alive_ticks=-1, tick=1.0)
    seams["monotonic"] = _mono(tick=7.0)
    rec = qloop.run_cycle(1, cycle_timeout_s=20, poll_s=10, kill_grace_s=5, **seams)

    assert rec["outcome"] == "timeout_killed"
    assert "21.0s" in rec["detail"], rec["detail"]
    assert "20" in rec["detail"], "the budget it was measured against is still named"


# ------------------------------------- 3. one fault does not end the night
def test_an_unexpected_fault_is_recorded_as_an_error_row_and_the_loop_goes_on(
        monkeypatch, tmp_path):
    """One unexpected fault ended the whole night AND left no JSONL trace,
    because `append_record` is only reached on the normal path."""
    log, seams = _loop_seams(alive_ticks=1)
    ledger = tmp_path / "l.jsonl"
    calls = {"n": 0}
    real_run_cycle = qloop.run_cycle

    def flaky(cycle, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("seam exploded")
        return real_run_cycle(cycle, **kw)

    monkeypatch.setattr(qloop, "run_cycle", flaky)
    summary = qloop.run_loop(max_cycles=4, settle_s=45, poll_s=10,
                             control_dir=tmp_path, cycle_log=ledger,
                             emit=lambda line: None, **seams)

    outcomes = [r["outcome"] for r in summary["records"]]
    assert summary["cycles_run"] == 4, "one fault must not end the night"
    assert outcomes == ["completed", "error", "completed", "completed"]
    bad = summary["records"][1]
    assert bad["ok"] is False
    assert "seam exploded" in bad["detail"]
    assert set(bad) == set(summary["records"][0]), "one row shape for one consumer"
    rows = [json.loads(ln) for ln in
            ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert [r["outcome"] for r in rows] == outcomes, "the fault must leave a trace"


def test_three_CONSECUTIVE_errors_stop_the_loop(monkeypatch, tmp_path):
    """A fault that repeats is a fault that will repeat all night."""
    log, seams = _loop_seams(alive_ticks=1)
    monkeypatch.setattr(qloop, "run_cycle",
                        lambda cycle, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    summary = qloop.run_loop(max_cycles=9, max_consecutive_errors=3,
                             settle_s=45, control_dir=tmp_path,
                             cycle_log=tmp_path / "l.jsonl",
                             emit=lambda line: None, **seams)

    assert summary["cycles_run"] == 3
    assert summary["stopped_by"] == "consecutive_errors"
    assert [r["outcome"] for r in summary["records"]] == ["error"] * 3


def test_a_NON_consecutive_error_does_not_stop_the_loop(monkeypatch, tmp_path):
    log, seams = _loop_seams(alive_ticks=1)
    calls = {"n": 0}
    real_run_cycle = qloop.run_cycle

    def every_other(cycle, **kw):
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            raise RuntimeError("boom")
        return real_run_cycle(cycle, **kw)

    monkeypatch.setattr(qloop, "run_cycle", every_other)
    summary = qloop.run_loop(max_cycles=6, max_consecutive_errors=2,
                             settle_s=45, control_dir=tmp_path,
                             cycle_log=tmp_path / "l.jsonl",
                             emit=lambda line: None, **seams)

    assert summary["cycles_run"] == 6
    assert summary["stopped_by"] == "max_cycles"
    assert [r["outcome"] for r in summary["records"]] == [
        "completed", "error", "completed", "error", "completed", "error"]


# ------------------------------------------- 4. ONE driver, and a locked ledger
def test_the_driver_binds_the_repo_winmutex_file_not_a_reimplementation():
    """winmutex.py is BYTE-IDENTICAL-BY-CONTRACT with the Sibling-A copy
    (SHARED_SHA256 in tests/test_loop_concurrency.py): consumed here, never
    edited and never re-implemented."""
    from pathlib import Path
    assert Path(qloop.winmutex.__file__).resolve() == (
        Path(qloop.__file__).resolve().parent / "winmutex.py")
    assert hasattr(qloop.winmutex, "hold")
    assert hasattr(qloop.winmutex, "MutexTimeout")


def test_the_driver_and_the_ledger_hold_DISTINCT_named_mutexes():
    """One shared name would be wrong, not merely untidy: the driver holds its
    singleton for the whole multi-hour run, so an append under that same name
    would make every other appender wait out the night."""
    assert qloop.DRIVER_MUTEX != qloop.LEDGER_MUTEX
    assert "QUEUE" in qloop.DRIVER_MUTEX.upper()


def test_a_second_driver_refuses_to_start_and_returns_a_distinct_code(monkeypatch):
    """Two drivers interleave on the lane lock, each burning up to ten minutes
    per cycle on `lane_held`, and both append to one ledger."""
    ran = []
    monkeypatch.setattr(qloop, "run_loop", lambda **kw: ran.append(kw) or
                        {"cycles_run": 0, "stopped_by": "max_cycles", "records": []})

    @contextlib.contextmanager
    def already_held():
        raise qloop.winmutex.MutexTimeout("held by another driver")
        yield None      # pragma: no cover - unreachable, keeps this a generator

    rc = qloop.main(["--cycles", "3"], singleton=already_held)
    assert rc == qloop.EXIT_ALREADY_RUNNING
    assert rc != 0
    assert ran == [], "the second driver must not run a single cycle"


def test_the_singleton_is_held_across_the_WHOLE_run(monkeypatch):
    """A guard released before the run is no guard at all."""
    events = []

    @contextlib.contextmanager
    def guard():
        events.append("enter")
        try:
            yield None
        finally:
            events.append("exit")

    monkeypatch.setattr(qloop, "run_loop", lambda **kw: events.append("run") or
                        {"cycles_run": 1, "stopped_by": "max_cycles", "records": []})
    assert qloop.main(["--once"], singleton=guard) == qloop.EXIT_OK
    assert events == ["enter", "run", "exit"]


def test_append_record_writes_INSIDE_the_ledger_mutex(tmp_path):
    """`steer.py` already serialises its appends this way; this did a bare
    open(..., "a")."""
    ledger = tmp_path / "l.jsonl"
    events = []

    @contextlib.contextmanager
    def hold():
        events.append(("enter", ledger.exists()))
        try:
            yield None
        finally:
            events.append(("exit", ledger.exists()))

    qloop.append_record({"cycle": 1, "outcome": "completed"}, ledger, hold=hold)

    assert events == [("enter", False), ("exit", True)], (
        "the write must happen INSIDE the held mutex, not beside it")
    assert json.loads(ledger.read_text(encoding="utf-8").strip())["cycle"] == 1


# --------------------------- 5. zero cycles is not success, and the banner lied
def test_the_new_hardening_defaults_are_the_shipped_defaults():
    assert qloop.DEFAULT_KILL_GRACE_S == 15
    assert qloop.DEFAULT_MAX_CONSECUTIVE_ERRORS == 3
    assert qloop.OUTCOME_KILL_FAILED == "timeout_kill_failed"
    assert qloop.OUTCOME_ERROR == "error"
    assert qloop.EXIT_OK == 0
    assert qloop.EXIT_STOP_SENTINEL not in (0, qloop.EXIT_ALREADY_RUNNING)
    assert qloop.EXIT_ALREADY_RUNNING != 0


def test_main_returns_a_distinct_code_and_names_the_sentinel_AND_its_path(
        tmp_path, capsys):
    """`ops/loop/control/STOP` exists on this box right now (content: "operator
    halt via LW session 2026-07-28"), so a fire today runs zero cycles - and
    main returned 0, over which the launcher printed a success banner."""
    control = tmp_path / "control"
    (control / "lanes").mkdir(parents=True)
    sentinel = control / "lanes" / "QUEUE_DRAINED"
    sentinel.write_text("queue empty", encoding="utf-8")

    rc = qloop.main(["--cycles", "5", "--control-dir", str(control),
                     "--reports-dir", str(tmp_path / "r")],
                    singleton=contextlib.nullcontext)
    out = capsys.readouterr().out

    assert rc == qloop.EXIT_STOP_SENTINEL
    assert rc != 0
    assert "QUEUE_DRAINED" in out
    assert str(sentinel) in out, "the operator needs the PATH, not just the name"


def test_main_gives_the_two_hard_stops_their_own_exit_codes(monkeypatch, capsys):
    """A night that ended at cycle 2 must not look like one that ran all twelve.

    `timeout_kill_failed` is the serious one: the worker outlived its kill, so
    the lane worktree may still have a live writer in it, and that is the
    unrecoverable two-writers class. Exiting 0 there hid it from the launcher,
    from a scheduled task, and from any `$LASTEXITCODE` check.
    """
    monkeypatch.setattr(qloop, "run_loop", lambda **kw: {
        "cycles_run": 2, "stopped_by": qloop.OUTCOME_KILL_FAILED, "records": []})
    rc = qloop.main(["--cycles", "12"], singleton=contextlib.nullcontext)
    out = capsys.readouterr().out
    assert rc == qloop.EXIT_KILL_FAILED and rc != 0
    assert "rc-lane-queue" in out, "the operator needs the worktree to check"

    monkeypatch.setattr(qloop, "run_loop", lambda **kw: {
        "cycles_run": 3, "stopped_by": qloop.STOPPED_BY_CONSECUTIVE_ERRORS,
        "records": []})
    assert qloop.main(["--cycles", "12"], singleton=contextlib.nullcontext) == \
        qloop.EXIT_CONSECUTIVE_ERRORS

    # The normal ends stay 0, or the codes mean nothing.
    monkeypatch.setattr(qloop, "run_loop", lambda **kw: {
        "cycles_run": 12, "stopped_by": qloop.STOPPED_BY_MAX_CYCLES, "records": []})
    assert qloop.main(["--cycles", "12"], singleton=contextlib.nullcontext) == \
        qloop.EXIT_OK
    # A sentinel that appeared MID-run is a successful drain, not a refusal.
    monkeypatch.setattr(qloop, "run_loop", lambda **kw: {
        "cycles_run": 7, "stopped_by": "QUEUE_DRAINED", "records": []})
    assert qloop.main(["--cycles", "12"], singleton=contextlib.nullcontext) == \
        qloop.EXIT_OK


def test_the_nonzero_exit_codes_are_distinct():
    """Two codes sharing a number is the same defect as everything exiting 0."""
    codes = [qloop.EXIT_OK, qloop.EXIT_STOP_SENTINEL, qloop.EXIT_ALREADY_RUNNING,
             qloop.EXIT_KILL_FAILED, qloop.EXIT_CONSECUTIVE_ERRORS,
             qloop.EXIT_CI_RED]
    assert len(set(codes)) == len(codes), codes


def test_main_still_returns_zero_when_zero_cycles_were_simply_asked_for(monkeypatch):
    """`--cycles 0` is a deliberate no-op, not a refused run."""
    monkeypatch.setattr(qloop, "run_loop", lambda **kw:
                        {"cycles_run": 0, "stopped_by": "max_cycles", "records": []})
    assert qloop.main(["--cycles", "0"],
                      singleton=contextlib.nullcontext) == qloop.EXIT_OK


def test_the_launcher_quotes_the_driver_path_because_the_repo_root_has_a_space():
    """MEASURED on the first real fire, 2026-09-05.

    `Start-Process -ArgumentList @($driver, ...)` joins with spaces and quotes
    nothing, so `C:\\Riot Commander\\ops\\loop\\queue_loop.py` reached pythonw as
    `C:\\Riot` and it died with `can't open file`. Start-Process had already
    issued a real pid and the launcher had already printed `queue-loop driver
    started`, so the night would have produced nothing while reporting success -
    the same silent shape as the DETACHED_PROCESS case in lane_launcher.py.

    Structural, because the .ps1 cannot be imported: the assertion is that the
    driver path is interpolated INSIDE escaped quotes in the argument list.
    """
    text = (lanes.REPO_ROOT / "ops/loop/launch_queue_loop.ps1").read_text(
        encoding="utf-8")

    arg_lines = [ln for ln in text.splitlines() if "$argList" in ln and "=" in ln]
    assert arg_lines, "the launcher no longer builds an $argList"
    built = arg_lines[0]
    assert '"`"$driver`""' in built, (
        "the driver path must be quoted in the argument list - the repo root "
        f"contains a space. Got: {built.strip()}")
    assert not any(part.strip() == "$driver" for part in built.split(",")), (
        "a bare $driver element is the measured 2026-09-05 defect")


def test_the_launcher_refuses_to_start_over_a_stop_sentinel_unless_forced():
    """The .ps1 has no python to import, so this is a structural read of it.

    Without the check it printed `queue-loop driver started` over a driver that
    was about to run zero cycles.
    """
    text = (lanes.REPO_ROOT / "ops/loop/launch_queue_loop.ps1").read_text(
        encoding="utf-8")

    assert "[switch]$Force" in text, "the -Force escape hatch must exist"
    for rel in ("control\\STOP", "control\\lanes\\QUEUE_STOP",
                "control\\lanes\\QUEUE_DRAINED"):
        assert rel in text, f"the launcher must check {rel}"
    assert text.index("if (-not $Force)") < text.index("Start-Process"), (
        "the refusal must precede the launch, not follow it")
    # Non-zero and BEFORE the spawn, so the "driver started" banner cannot be
    # printed over a refusal. 2 is queue_loop.EXIT_STOP_SENTINEL: one number for
    # one condition, whichever half of the pair refused.
    assert text.index("exit 2") < text.index("Start-Process")


# ---------------------------- 6. a pid is not an identity (pid reuse)
def test_the_identity_probe_is_the_SAME_predicate_lane_state_uses():
    """One definition, so the driver and the dashboard can never disagree about
    whether a lane's holder is still the process that claimed it."""
    params = inspect.signature(qloop.run_cycle).parameters
    assert params["alive"].default is lanes.slots.pid_alive
    assert params["proc_started"].default is lanes.proc_started
    assert params["stranger"].default is lanes._holder_is_a_stranger


def test_a_reissued_pid_is_treated_as_DEAD_not_as_a_live_worker():
    """`alive` is pid-only. Windows reuses pids (MEASURED 2026-08-02: a dead
    lane worker's pid 8820 became SearchFilterHost three minutes later), so a
    driver that reads the stranger as its own worker waits out the whole 5400s
    budget and then kills an innocent process."""
    log, seams = _seams(alive_ticks=-1, tick=1.0)      # the pid stays alive forever
    seams["monotonic"] = _mono(tick=1.0)
    seams["proc_started"] = lambda pid: 100.0
    probes = []

    def stranger(pid, started):
        probes.append((pid, started))
        return len(probes) >= 2        # a different process holds the pid now

    seams["stranger"] = stranger
    rec = qloop.run_cycle(1, cycle_timeout_s=10_000, poll_s=10, kill_grace_s=5,
                          **seams)

    assert rec["outcome"] == "completed", "a reissued pid means our worker exited"
    assert log["kill"] == [], "and an innocent process must never be killed"
    assert probes[0] == (4242, 100.0), (
        "the identity compared is the one captured AT LAUNCH")


def test_a_worker_with_no_readable_start_time_falls_back_to_the_pid_probe():
    """Fail-soft: psutil may be absent, or the worker may be gone before its
    start time can be read. Every uncertain case must degrade to the plain pid
    probe rather than declare a live worker dead."""
    log, seams = _seams(alive_ticks=2, tick=1.0)
    seams["monotonic"] = _mono(tick=1.0)
    seams["proc_started"] = lambda pid: None
    seen = []

    def stranger(pid, started):
        seen.append(started)
        return False                   # lanes._holder_is_a_stranger's answer for None

    seams["stranger"] = stranger
    rec = qloop.run_cycle(1, cycle_timeout_s=10_000, poll_s=10, **seams)

    assert rec["outcome"] == "completed"
    assert seen and all(s is None for s in seen)


# ===========================================================================
# 7. THE CI WAIT BELONGS TO THE DRIVER, NOT TO THE PROMPT. Added 2026-09-06.
#
# `tools/headless-queue.md` section 9 told the WORKER to block until its own
# `ci` run completed. `.github/workflows/ci.yml:38-40` sets
# `cancel-in-progress: true` on the group
# `${{ github.workflow }}-${{ github.ref }}-${{ github.event_name }}`, a run
# takes 45 to 67 minutes and a cycle takes 25 to 45, so cycle N+1's run cancels
# cycle N's in WHATEVER group. MEASURED over six cycles: cycles 2 and 3 blocked
# (102.7 and 113.3 minutes, both green); cycles 4, 5 and 6 ran 45 / 24.2 / 38.5
# minutes, which is shorter than a run, so those workers exited early and three
# consecutive dispatch runs were cancelled. An instruction a worker can
# rationalize past is not a mechanism. Nothing can cancel a run while the only
# thing that would trigger the next one is the driver, and the driver is
# waiting - and cycles are already serial, so that is structural.
# ===========================================================================
CI_STEP_NAME = "full dual suite (RM-119 - push CI now gates the whole tree)"


def _gh_key(args):
    """Which scripted answer a `gh` argv wants.

    `run view` is TWO different questions (`--json status,conclusion` while
    polling, `--json jobs` once it completes) and they must be scriptable
    apart, or a test cannot make a run whose conclusion disagrees with its
    step - which is the whole point of reading `jobs[].steps[]`.
    """
    if args[:2] == ["workflow", "run"]:
        return "dispatch"
    if args[:2] == ["run", "list"]:
        return "list"
    if args[:2] == ["run", "view"]:
        return "jobs" if args[-1] == "jobs" else "view"
    return " ".join(args)


def _fake_gh(**answers):
    """A scripted `gh` seam. Every value is a list of (returncode, payload).

    Answers are consumed in order and the LAST one repeats forever, so a poll
    loop of unknown length needs exactly one trailing entry. A payload that is
    not a string is json.dumps'd, so a test writes the shape it means. An
    unscripted call is an AssertionError rather than a silent empty answer - a
    fake that invents a reply for a call nobody expected is how a seam test
    passes while proving nothing.
    """
    calls = []
    queues = {k: list(v) for k, v in answers.items()}

    def gh(args):
        args = [str(a) for a in args]
        calls.append(args)
        queue = queues.get(_gh_key(args))
        if not queue:
            raise AssertionError(f"unscripted gh call: {args}")
        rc, payload = queue[0] if len(queue) == 1 else queue.pop(0)
        return rc, payload if isinstance(payload, str) else json.dumps(payload)

    return calls, gh


def _row(rid, sha, *, status="completed", conclusion="success",
         event="workflow_dispatch"):
    return {"databaseId": rid, "headSha": sha, "status": status,
            "conclusion": conclusion, "event": event}


def _jobs(step="success", *, job="check", job_conclusion="success",
          step_name=CI_STEP_NAME, steps=None):
    """A `gh run view --json jobs` payload.

    The nightly job is always present because a `workflow_dispatch` really does
    run both (`ci.yml:44`), and a driver that read the FIRST job would then
    grade the wrong one.
    """
    named = [{"name": "Set up job", "conclusion": "success"},
             {"name": step_name, "conclusion": step}] if steps is None else steps
    return {"jobs": [
        {"name": "nightly-full-suite", "conclusion": "failure",
         "steps": [{"name": step_name, "conclusion": "failure"}]},
        {"name": job, "conclusion": job_conclusion, "steps": named}]}


def test_wait_for_ci_prefers_an_EXISTING_dispatch_run_over_a_push_run():
    """A dispatch run outlives a later push; a push run does not.

    `event_name` is part of the concurrency group, so only another
    `workflow_dispatch` can supersede a dispatch run - and the next one is a
    whole cycle away because cycles are serial.
    """
    calls, gh = _fake_gh(
        list=[(0, [_row(11, "abc", event="push"),
                   _row(22, "abc", event="workflow_dispatch")])],
        jobs=[(0, _jobs("success"))])
    out = qloop.wait_for_ci("abc", budget_s=600, poll_s=60, gh=gh,
                            sleep=lambda s: None, monotonic=_mono())

    assert out["step"] == "success"
    assert out["run_id"] == 22, "the push run must not be the one watched"
    assert out["sha"] == "abc"
    assert out["status"] == "completed"
    assert not [c for c in calls if _gh_key(c) == "dispatch"], (
        "a run for this sha already existed - triggering another is a waste "
        "of a 45-minute runner and starts a race with the next cycle")


def test_wait_for_ci_TRIGGERS_a_run_when_none_exists_for_the_sha():
    calls, gh = _fake_gh(
        list=[(0, [_row(11, "other", event="push")]),
              (0, [_row(33, "abc", event="workflow_dispatch"),
                   _row(11, "other", event="push")])],
        dispatch=[(0, "")],
        jobs=[(0, _jobs("success"))])
    out = qloop.wait_for_ci("abc", budget_s=600, poll_s=60, gh=gh,
                            sleep=lambda s: None, monotonic=_mono())

    assert out["step"] == "success"
    assert out["run_id"] == 33
    assert ["workflow", "run", "ci.yml", "--ref", "main"] in calls


def test_a_triggered_run_on_a_DESCENDANT_sha_is_accepted_and_records_ITS_sha():
    """`gh workflow run` takes a BRANCH ref, so it builds `main` as of trigger
    time - our commit, or a descendant of it. A later sha subsumes an earlier
    one, so the run is accepted and the sha it ACTUALLY built is what the
    record carries. Recording the requested sha instead would be a quiet lie
    in the one row that has to be citable.
    """
    calls, gh = _fake_gh(
        list=[(0, [_row(11, "other", event="push")]),
              (0, [_row(44, "def-later", event="workflow_dispatch")])],
        dispatch=[(0, "")],
        jobs=[(0, _jobs("success"))])
    out = qloop.wait_for_ci("abc", budget_s=600, poll_s=60, gh=gh,
                            sleep=lambda s: None, monotonic=_mono())

    assert out["step"] == "success"
    assert out["run_id"] == 44
    assert out["sha"] == "def-later", "the record must name the sha CI built"


def test_wait_for_ci_POLLS_until_the_run_completes():
    calls, gh = _fake_gh(
        list=[(0, [_row(55, "abc", status="in_progress", conclusion=None)])],
        view=[(0, {"status": "in_progress", "conclusion": None}),
              (0, {"status": "in_progress", "conclusion": None}),
              (0, {"status": "completed", "conclusion": "success"})],
        jobs=[(0, _jobs("success"))])
    slept = []
    out = qloop.wait_for_ci("abc", budget_s=100_000, poll_s=60, gh=gh,
                            sleep=slept.append, monotonic=_mono())

    assert out["step"] == "success"
    assert slept == [60, 60, 60], "it must poll at poll_s, not spin"
    assert len([c for c in calls if _gh_key(c) == "view"]) == 3


def test_budget_exhaustion_returns_timeout_and_NEVER_raises():
    """A run that outlasts the budget is not a red and not a green. It is
    recorded and the night goes on - an exception here would end it."""
    calls, gh = _fake_gh(
        list=[(0, [_row(66, "abc", status="in_progress", conclusion=None)])],
        view=[(0, {"status": "in_progress", "conclusion": None})])
    out = qloop.wait_for_ci("abc", budget_s=5, poll_s=1, gh=gh,
                            sleep=lambda s: None, monotonic=_mono(tick=2.0))

    assert out["step"] == "timeout"
    assert out["run_id"] == 66
    assert "5" in out["detail"], "the budget it was measured against"
    assert not [c for c in calls if _gh_key(c) == "jobs"], (
        "a run that never completed has no step conclusion to read")


def test_a_CANCELLED_run_is_re_dispatched_exactly_once():
    """`cancel-in-progress` is the whole reason this wait exists, so the one
    outcome it must handle gracefully is the run being superseded anyway."""
    calls, gh = _fake_gh(
        list=[(0, [_row(77, "abc", conclusion="cancelled")]),
              (0, [_row(88, "abc"), _row(77, "abc", conclusion="cancelled")])],
        dispatch=[(0, "")],
        jobs=[(0, _jobs("success"))])
    out = qloop.wait_for_ci("abc", budget_s=600, poll_s=60, gh=gh,
                            sleep=lambda s: None, monotonic=_mono())

    assert out["step"] == "success"
    assert out["run_id"] == 88
    assert len([c for c in calls if _gh_key(c) == "dispatch"]) == 1


def test_a_SECOND_cancelled_run_is_reported_cancelled_and_not_retried_again():
    """ONCE. A driver that re-dispatched on every cancel would burn the whole
    budget starting runs instead of watching one, and a cancelled run may never
    be dressed up as green."""
    calls, gh = _fake_gh(
        list=[(0, [_row(77, "abc", conclusion="cancelled")]),
              (0, [_row(88, "abc", conclusion="cancelled")])],
        dispatch=[(0, "")])
    out = qloop.wait_for_ci("abc", budget_s=600, poll_s=60, gh=gh,
                            sleep=lambda s: None, monotonic=_mono())

    assert out["step"] == "cancelled"
    assert out["run_id"] == 88
    assert len([c for c in calls if _gh_key(c) == "dispatch"]) == 1


def test_a_gh_NON_ZERO_exit_returns_unavailable_and_never_raises():
    """FAIL SOFT ON TOOLING, NEVER ON THE VERDICT. A CLI hiccup - gh not
    installed, an expired token, a 502 from the API - may not wedge or end an
    overnight loop."""
    calls, gh = _fake_gh(list=[(1, "gh: could not find any workflows")])
    out = qloop.wait_for_ci("abc", budget_s=600, poll_s=60, gh=gh,
                            sleep=lambda s: None, monotonic=_mono())

    assert out["step"] == "unavailable"
    assert out["run_id"] is None
    assert "could not find any workflows" in out["detail"]


def test_UNPARSEABLE_json_returns_unavailable_rather_than_exploding():
    calls, gh = _fake_gh(list=[(0, "not json at all")])
    out = qloop.wait_for_ci("abc", budget_s=600, poll_s=60, gh=gh,
                            sleep=lambda s: None, monotonic=_mono())
    assert out["step"] == "unavailable"
    assert "JSON" in out["detail"] or "json" in out["detail"]


def test_a_MISSING_field_returns_unavailable_rather_than_a_KeyError():
    calls, gh = _fake_gh(
        list=[(0, [_row(99, "abc")])],
        jobs=[(0, {"jobs": [{"name": "check", "conclusion": "success"}]})])
    out = qloop.wait_for_ci("abc", budget_s=600, poll_s=60, gh=gh,
                            sleep=lambda s: None, monotonic=_mono())
    assert out["step"] == "unavailable"


def test_a_SKIPPED_check_job_reports_skipped_and_never_success():
    """A green run may have SKIPPED the job that matters: `check` carries
    `if: github.event_name != 'schedule'` (`ci.yml:143`), so the scheduled
    nightly never runs it. Citing the run conclusion there is how a night of
    untested pushes reads as twelve green cycles."""
    calls, gh = _fake_gh(
        list=[(0, [_row(101, "abc")])],
        jobs=[(0, _jobs("success", job_conclusion="skipped"))])
    out = qloop.wait_for_ci("abc", budget_s=600, poll_s=60, gh=gh,
                            sleep=lambda s: None, monotonic=_mono())
    assert out["step"] == "skipped"


def test_an_ABSENT_check_job_reports_skipped_too():
    calls, gh = _fake_gh(
        list=[(0, [_row(102, "abc")])],
        jobs=[(0, _jobs("success", job="nightly-only"))])
    out = qloop.wait_for_ci("abc", budget_s=600, poll_s=60, gh=gh,
                            sleep=lambda s: None, monotonic=_mono())
    assert out["step"] == "skipped"


def test_the_verdict_is_the_STEP_conclusion_not_the_run_conclusion():
    """Read `jobs[].steps[]`, never the run conclusion - the measured rule this
    whole function exists to encode."""
    calls, gh = _fake_gh(
        list=[(0, [_row(103, "abc", conclusion="success")])],
        jobs=[(0, _jobs("failure"))])
    out = qloop.wait_for_ci("abc", budget_s=600, poll_s=60, gh=gh,
                            sleep=lambda s: None, monotonic=_mono())

    assert out["step"] == "failure", (
        "the run said success; the step that gates the tree did not")
    assert out["status"] == "completed"


def test_the_result_carries_exactly_the_documented_fields():
    calls, gh = _fake_gh(list=[(0, [_row(104, "abc")])],
                         jobs=[(0, _jobs("success"))])
    out = qloop.wait_for_ci("abc", budget_s=600, poll_s=60, gh=gh,
                            sleep=lambda s: None, monotonic=_mono())
    assert set(out) == {"sha", "run_id", "status", "step", "waited_s", "detail"}
    assert out["waited_s"] >= 0


def test_allow_trigger_False_never_fires_a_run():
    """The re-dispatch is a WRITE against the repo's CI minutes. A caller that
    only wants to read must be able to say so."""
    calls, gh = _fake_gh(list=[(0, [_row(105, "other")])])
    out = qloop.wait_for_ci("abc", budget_s=600, poll_s=60, allow_trigger=False,
                            gh=gh, sleep=lambda s: None, monotonic=_mono())
    assert out["step"] == "unavailable"
    assert not [c for c in calls if _gh_key(c) == "dispatch"]


def test_every_step_value_is_one_of_the_seven_documented_words():
    assert qloop.CI_STEPS == ("success", "failure", "cancelled", "skipped",
                              "timeout", "unavailable", "unknown")
    assert qloop.CI_FAILURE == "failure"
    assert qloop.DEFAULT_CI_WAIT_S == 5400


def test_the_gh_seam_is_injectable_and_defaults_to_the_one_wrapper():
    """One seam for every `gh` call, so no test can shell out by accident and
    every timeout / window flag is set in one place."""
    params = inspect.signature(qloop.wait_for_ci).parameters
    assert params["gh"].default is qloop._gh
    assert params["sleep"].default is time.sleep
    assert params["monotonic"].default is time.monotonic
    assert params["allow_trigger"].default is True


def test_NO_test_in_this_module_shells_out_for_ci():
    """The `gh` seam is always injected - structurally, not by convention.

    A single test that forgot it would fire a real `gh workflow run` against
    the live repo from the suite, which is a 45-minute runner and a race with
    whatever the queue lane is doing at the time.
    """
    tree = ast.parse(open(__file__, encoding="utf-8").read())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name in ("_gh", "_head_sha"):
            offenders.append(("direct call to a shelling seam", node.lineno))
        if name == "wait_for_ci" and not any(
                kw.arg in ("gh", None) for kw in node.keywords):
            offenders.append(("wait_for_ci without a gh seam", node.lineno))
    assert not offenders, offenders


# ------------------------------------------- 7b. the gate, wired into run_loop
def test_the_ci_verdict_lands_INSIDE_the_cycles_jsonl_record(tmp_path):
    """One row carries the cycle AND its verdict. Two files, or a verdict in
    the log only, means nobody can join them at 3am."""
    ledger = tmp_path / "l.jsonl"
    log, seams = _loop_seams(alive_ticks=1)
    seams["head_sha"] = _new_head_every_call()
    seen, seams["wait"] = _fake_wait("success")
    printed = []
    summary = qloop.run_loop(max_cycles=2, control_dir=tmp_path,
                             cycle_log=ledger, emit=printed.append, **seams)

    rows = [json.loads(ln) for ln in
            ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == 2
    assert [r["ci"]["step"] for r in rows] == ["success", "success"]
    assert rows[0]["ci"]["run_id"] == 4242
    assert rows == summary["records"], "the ledger and the summary are one thing"
    assert len(seen) == 2, "one wait per pushed cycle"
    assert any("success" in line and "ci" in line for line in printed)


def test_the_ci_wait_is_charged_the_configured_budget_and_the_shared_seams(tmp_path):
    log, seams = _loop_seams(alive_ticks=1)
    seams["head_sha"] = _new_head_every_call()
    seen, seams["wait"] = _fake_wait("success")
    qloop.run_loop(max_cycles=1, ci_wait_s=1234, ci_poll_s=7,
                   control_dir=tmp_path, cycle_log=tmp_path / "l.jsonl",
                   emit=lambda line: None, **seams)

    assert seen[0]["budget_s"] == 1234
    assert seen[0]["poll_s"] == 7
    assert seen[0]["gh"] is seams["gh"], "one gh seam, not a second one"
    assert seen[0]["sha"] == "sha0002", "the sha the cycle PUSHED, not the one before"


def test_a_ci_FAILURE_stops_the_loop(tmp_path):
    """Continuing to push rows onto a red `main` compounds a break nobody is
    watching. Ending the night early is the cheaper half of that trade."""
    log, seams = _loop_seams(alive_ticks=1)
    seams["head_sha"] = _new_head_every_call()
    seen, seams["wait"] = _fake_wait("failure")
    summary = qloop.run_loop(max_cycles=6, settle_s=45, control_dir=tmp_path,
                             cycle_log=tmp_path / "l.jsonl",
                             emit=lambda line: None, **seams)

    assert summary["cycles_run"] == 1
    assert summary["stopped_by"] == "ci_red"
    assert summary["stopped_by"] == qloop.STOPPED_BY_CI_RED
    assert len(log["launch"]) == 1, "no second row onto a red main"
    assert 45 not in log["sleep"], "it must stop, not settle and carry on"
    assert summary["records"][0]["ci"]["step"] == "failure", (
        "the evidence for why the night ended has to reach the ledger")


@pytest.mark.parametrize("step", ["cancelled", "timeout", "skipped",
                                  "unavailable", "unknown"])
def test_every_NON_red_verdict_is_recorded_and_the_loop_CONTINUES(tmp_path, step):
    """Only `failure` is red. A cancelled run is a superseded run, a timeout is
    a slow runner, `skipped` means the job did not run and `unavailable` means
    the CLI hiccuped - none of them is evidence that `main` is broken, and a
    driver that stopped on them would end most nights at cycle one."""
    log, seams = _loop_seams(alive_ticks=1)
    seams["head_sha"] = _new_head_every_call()
    seen, seams["wait"] = _fake_wait(step)
    summary = qloop.run_loop(max_cycles=3, control_dir=tmp_path,
                             cycle_log=tmp_path / "l.jsonl",
                             emit=lambda line: None, **seams)

    assert summary["cycles_run"] == 3
    assert summary["stopped_by"] == "max_cycles"
    assert [r["ci"]["step"] for r in summary["records"]] == [step] * 3


def test_no_ci_gate_skips_the_wait_ENTIRELY(tmp_path):
    log, seams = _loop_seams(alive_ticks=1)
    seams["head_sha"] = _new_head_every_call()
    seen, seams["wait"] = _fake_wait("failure")
    summary = qloop.run_loop(max_cycles=3, ci_gate=False, control_dir=tmp_path,
                             cycle_log=tmp_path / "l.jsonl",
                             emit=lambda line: None, **seams)

    assert summary["cycles_run"] == 3, "a red verdict cannot stop a gate that is off"
    assert seen == [], "the wait must not be called at all"
    assert all("ci" not in r for r in summary["records"]), (
        "an ABSENT key is how a row says no gate ran - never a `skipped` "
        "verdict, which already means the check JOB was skipped")


def test_the_wait_is_skipped_when_NO_PUSH_can_be_detected(tmp_path):
    """`origin/main` unmoved across the cycle means the worker shipped nothing -
    a recall-closed row, a refuted row, a drained queue. There is no run to
    wait for, and dispatching one would burn 45 minutes of runner on the
    previous cycle's commit."""
    log, seams = _loop_seams(alive_ticks=1)          # head_sha is constant here
    seen, seams["wait"] = _fake_wait("success")
    summary = qloop.run_loop(max_cycles=2, control_dir=tmp_path,
                             cycle_log=tmp_path / "l.jsonl",
                             emit=lambda line: None, **seams)

    assert summary["cycles_run"] == 2
    assert seen == []
    assert all("ci" not in r for r in summary["records"])


def test_the_wait_is_skipped_for_every_outcome_other_than_completed(tmp_path):
    """A lane_held or launch_failed cycle never ran a worker, so there is
    nothing of ours in CI to grade."""
    log, seams = _loop_seams(refuse_forever=True)
    seams["head_sha"] = _new_head_every_call()
    seen, seams["wait"] = _fake_wait("failure")
    summary = qloop.run_loop(max_cycles=2, acquire_retries=1,
                             control_dir=tmp_path, cycle_log=tmp_path / "l.jsonl",
                             emit=lambda line: None, **seams)

    assert [r["outcome"] for r in summary["records"]] == ["lane_held"] * 2
    assert seen == []
    assert all("ci" not in r for r in summary["records"])


def test_an_UNREADABLE_head_sha_records_unavailable_and_the_loop_continues(tmp_path):
    """Fail soft on tooling. A `git ls-remote` that cannot reach the remote is
    not a reason to abandon eleven more rows - but it is not silence either,
    because a night with no verdicts must not read like a night of greens."""
    log, seams = _loop_seams(alive_ticks=1)
    seams["head_sha"] = lambda: None
    seen, seams["wait"] = _fake_wait("success")
    summary = qloop.run_loop(max_cycles=2, control_dir=tmp_path,
                             cycle_log=tmp_path / "l.jsonl",
                             emit=lambda line: None, **seams)

    assert summary["cycles_run"] == 2
    assert seen == [], "there is no sha to wait on"
    assert [r["ci"]["step"] for r in summary["records"]] == ["unavailable"] * 2
    assert set(summary["records"][0]["ci"]) == {
        "sha", "run_id", "status", "step", "waited_s", "detail"}, (
        "one result shape, whether the verdict came from CI or from the probe "
        "that never reached it")


def test_the_ci_seams_default_to_the_real_implementations():
    params = inspect.signature(qloop.run_loop).parameters
    assert params["wait"].default is qloop.wait_for_ci
    assert params["head_sha"].default is qloop._head_sha
    assert params["gh"].default is qloop._gh
    assert params["ci_gate"].default is True, (
        "the gate is the point - an opt-in gate is the prose contract again")
    assert params["ci_wait_s"].default == qloop.DEFAULT_CI_WAIT_S


def test_main_threads_ci_wait_and_no_ci_gate_onto_run_loop(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(qloop, "run_loop", lambda **kw: seen.update(kw) or
                        {"cycles_run": 1, "stopped_by": "max_cycles", "records": []})
    assert qloop.main(["--once", "--ci-wait", "600"],
                      singleton=contextlib.nullcontext) == qloop.EXIT_OK
    assert seen["ci_wait_s"] == 600
    assert seen["ci_gate"] is True

    seen.clear()
    assert qloop.main(["--once", "--no-ci-gate"],
                      singleton=contextlib.nullcontext) == qloop.EXIT_OK
    assert seen["ci_gate"] is False
    assert seen["ci_wait_s"] == qloop.DEFAULT_CI_WAIT_S


def test_main_returns_EXIT_CI_RED_when_the_loop_stopped_on_a_red(monkeypatch, capsys):
    """A night that ended at cycle 2 on a red `main` must not report the same
    number as a night that ran all twelve."""
    monkeypatch.setattr(qloop, "run_loop", lambda **kw: {
        "cycles_run": 2, "stopped_by": qloop.STOPPED_BY_CI_RED, "records": []})
    rc = qloop.main(["--cycles", "12"], singleton=contextlib.nullcontext)
    out = capsys.readouterr().out
    assert rc == qloop.EXIT_CI_RED
    assert rc != 0
    assert "ci" in out.lower()


# --------------------------------------------------------------------------- house rules
def _code_strings(path):
    """Every string literal that is NOT a docstring.

    Lifted from tests/test_lane_launcher.py. Scanning raw text would match this
    module's own prose about the rule - the comments-cite-the-bug trap that made
    an earlier guard red.
    """
    tree = ast.parse(open(path, encoding="utf-8").read())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value not in docstrings]


def test_the_kill_path_uses_taskkill_not_stop_process():
    """CLAUDE.md hard rule: Stop-Process hangs the MCP pipe."""
    strings = _code_strings(qloop.__file__)
    assert "taskkill" in strings
    assert not [s for s in strings if "Stop-Process" in s]


def test_the_driver_binds_one_lanes_object_not_a_second_copy():
    """A second lanes module carries its own `_OWNED`, so the release no-ops.

    MEASURED in lane_launcher's first cut: the repoint updated one `_OWNED` and
    the release consulted another, and the lane could never be freed.
    """
    assert qloop.lanes is lanes
    assert qloop.lanes is launcher.lanes
    assert qloop.lane_launcher is launcher
    assert qloop.slots is lanes.slots


def test_the_shipped_files_are_seven_bit_ascii():
    """Repo-wide hard rule - a UTF-8 dash in a .ps1 is a PowerShell 5.1 parse
    failure, not a cosmetic issue (2026-05-18 boot-script incident)."""
    root = lanes.REPO_ROOT
    for rel in ("ops/loop/queue_loop.py", "tests/test_queue_loop.py",
                "ops/loop/launch_queue_loop.ps1"):
        raw = (root / rel).read_bytes()
        bad = sorted({b for b in raw if b > 0x7F})
        assert not bad, f"{rel} carries non-ASCII bytes: {bad}"

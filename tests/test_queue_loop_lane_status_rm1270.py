"""RM-1270 (MAIN ORDER 2215 item 6, the live half): queue_loop.run_loop writes the
lane_status.log stop and resume lines, under an injected root only.

No injected root writes nothing at all, which is what keeps the existing run_loop
callers in the test files away from the live log. main() is the one injector.

The residue a verifier named (s152 IN2): the three hard stops - CI red, a kill
that did not take, consecutive errors - wrote no line, and only the sentinel and
fair-yield stops had a test. Every run_loop stop path is now driven below.
"""
from __future__ import annotations

import contextlib
import datetime

import pytest

from tests.test_queue_loop import (
    _fake_wait,
    _loop_seams,
    _mono,
    _new_head_every_call,
    lanes,
    qloop,
)


def _quiet(*_a):
    return None


def _status(lanes_dir) -> list:
    path = lanes_dir.parent / "lane_status.log"
    if not path.exists():
        return []
    return [line.split()[1:] for line in path.read_text(encoding="ascii").splitlines()]


@pytest.fixture
def control(tmp_path):
    root = tmp_path / "control"
    (root / "lanes").mkdir(parents=True)
    return root


@pytest.mark.parametrize("rel,reason", [
    ("STOP", "STOP"), ("lanes/QUEUE_STOP", "operator"), ("lanes/QUEUE_DRAINED", "STOP"),
])
def test_a_stop_sentinel_logs_one_stop_with_its_reason(control, rel, reason):
    (control / rel).write_text("x", encoding="ascii")
    _log, seams = _loop_seams(alive_ticks=1)
    summary = qloop.run_loop(max_cycles=2, control_dir=control, status_root=control / "lanes",
                             cycle_log=control / "c.jsonl", emit=_quiet, **seams)
    assert summary["cycles_run"] == 0
    assert _status(control / "lanes") == [["queue", "stop", reason]]


def test_a_relaunch_into_the_same_sentinel_does_not_log_twice(control):
    (control / "STOP").write_text("x", encoding="ascii")
    for _ in range(2):
        _log, seams = _loop_seams(alive_ticks=1)
        qloop.run_loop(max_cycles=1, control_dir=control, status_root=control / "lanes",
                       cycle_log=control / "c.jsonl", emit=_quiet, **seams)
    assert _status(control / "lanes") == [["queue", "stop", "STOP"]]


def test_a_fair_yield_logs_a_cap_stop(control):
    _log, seams = _loop_seams(alive_ticks=1)
    seams["should_yield"] = lambda: True
    summary = qloop.run_loop(max_cycles=3, control_dir=control, status_root=control / "lanes",
                             cycle_log=control / "c.jsonl", emit=_quiet, **seams)
    assert summary["stopped_by"] == qloop.STOPPED_BY_FAIR_YIELD
    assert _status(control / "lanes") == [["queue", "stop", "cap"]]


def test_a_refused_claim_writes_no_resume(control):
    """The open stop stays open: only the real claim in lanes.py closes it."""
    lanes.mark_lane_stopped("queue", "cap", root=control / "lanes")
    _log, seams = _loop_seams(refuse_forever=True)
    summary = qloop.run_loop(max_cycles=2, control_dir=control, status_root=control / "lanes",
                             cycle_log=control / "c.jsonl", acquire_retries=1,
                             emit=_quiet, **seams)
    assert [r["outcome"] for r in summary["records"]] == ["lane_held", "lane_held"]
    assert _status(control / "lanes") == [["queue", "stop", "cap"]]


def test_a_lane_never_stopped_logs_nothing(control):
    _log, seams = _loop_seams(alive_ticks=1)
    qloop.run_loop(max_cycles=2, control_dir=control, status_root=control / "lanes",
                   cycle_log=control / "c.jsonl", emit=_quiet, **seams)
    assert _status(control / "lanes") == []


def test_no_injected_root_touches_no_status_log(control, monkeypatch):
    """Recorded, not raised: run_loop's helper swallows an exception by design."""
    calls = []
    monkeypatch.setattr(qloop.lanes, "mark_lane_stopped", lambda *a, **k: calls.append(a))
    (control / "STOP").write_text("x", encoding="ascii")
    _log, seams = _loop_seams(alive_ticks=1)
    summary = qloop.run_loop(max_cycles=1, control_dir=control,
                             cycle_log=control / "c.jsonl", emit=_quiet, **seams)
    assert summary["stopped_by"] == "STOP"
    assert calls == []


def test_a_status_fault_is_said_and_never_ends_the_loop(control, monkeypatch):
    def boom(*_a, **_k):
        raise ValueError("bad lane")
    monkeypatch.setattr(qloop.lanes, "mark_lane_stopped", boom)
    (control / "STOP").write_text("x", encoding="ascii")
    said = []
    _log, seams = _loop_seams(alive_ticks=1)
    summary = qloop.run_loop(max_cycles=1, control_dir=control, status_root=control / "lanes",
                             cycle_log=control / "c.jsonl", emit=said.append, **seams)
    assert summary["stopped_by"] == "STOP"
    assert any("lane status" in line for line in said)


# ---- every non-sentinel stop path (s152 IN2: the hard stops wrote no line) ----

# The reason vocabulary is pinned (limit / STOP / operator / cap). A hard stop is
# the driver's own halt: not the operator's file, not a cap, not a usage limit.
STOP_PATHS = {"fair_yield": "cap", "ci_red": "STOP", "kill_failed": "STOP",
              "consecutive_errors": "STOP"}


def _boom_cycle(_cycle, **_kw):
    raise RuntimeError("boom")


def _stop_path(path, monkeypatch):
    """(run_loop kwargs that end the loop on `path`, the stopped_by it reads)."""
    if path == "fair_yield":
        _log, seams = _loop_seams(alive_ticks=1)
        seams["should_yield"] = lambda: True
        return {"max_cycles": 3, **seams}, qloop.STOPPED_BY_FAIR_YIELD
    if path == "ci_red":
        _log, seams = _loop_seams(alive_ticks=1)
        seams["head_sha"] = _new_head_every_call()
        _seen, seams["wait"] = _fake_wait(qloop.CI_FAILURE)
        return {"max_cycles": 3, **seams}, qloop.STOPPED_BY_CI_RED
    if path == "kill_failed":
        _log, seams = _loop_seams(alive_ticks=-1, tick=1.0, kill_takes=False)
        seams["monotonic"] = _mono(tick=1.0)
        return ({"max_cycles": 3, "cycle_timeout_s": 3, "poll_s": 10,
                 "kill_grace_s": 20, **seams}, qloop.OUTCOME_KILL_FAILED)
    assert path == "consecutive_errors"
    _log, seams = _loop_seams(alive_ticks=1)
    monkeypatch.setattr(qloop, "run_cycle", _boom_cycle)
    return ({"max_cycles": 5, "max_consecutive_errors": 2, **seams},
            qloop.STOPPED_BY_CONSECUTIVE_ERRORS)


def _outcomes(summary) -> list:
    return [r["outcome"] for r in summary["records"]]


@pytest.mark.parametrize("lane", ["queue", "ds"])
@pytest.mark.parametrize("path", sorted(STOP_PATHS))
def test_every_stop_path_logs_one_stop_with_its_lane_and_reason(control, monkeypatch,
                                                                path, lane):
    kw, stopped_by = _stop_path(path, monkeypatch)
    summary = qloop.run_loop(lane=lane, control_dir=control, status_root=control / "lanes",
                             cycle_log=control / "c.jsonl", emit=_quiet, **kw)
    assert summary["stopped_by"] == stopped_by
    raw = (control / "lane_status.log").read_text(encoding="ascii").splitlines()
    assert len(raw) == 1, raw
    ts, *rest = raw[0].split(" ")
    assert rest == [lane, "stop", STOP_PATHS[path]]
    assert datetime.datetime.fromisoformat(ts).tzinfo is not None


@pytest.mark.parametrize("path", sorted(STOP_PATHS))
def test_a_status_fault_on_any_stop_path_is_said_and_changes_nothing(control, monkeypatch,
                                                                     path):
    kw, stopped_by = _stop_path(path, monkeypatch)
    base = qloop.run_loop(control_dir=control, cycle_log=control / "a.jsonl",
                          emit=_quiet, **kw)

    def boom(*_a, **_k):
        raise OSError("disk gone")

    monkeypatch.setattr(qloop.lanes, "mark_lane_stopped", boom)
    kw, _ = _stop_path(path, monkeypatch)
    said = []
    got = qloop.run_loop(control_dir=control, status_root=control / "lanes",
                         cycle_log=control / "b.jsonl", emit=said.append, **kw)
    assert (got["stopped_by"], got["cycles_run"], _outcomes(got)) == (
        stopped_by, base["cycles_run"], _outcomes(base))
    assert sum("lane status" in line for line in said) == 1
    assert _status(control / "lanes") == []


@pytest.mark.parametrize("path", sorted(STOP_PATHS))
def test_no_injected_root_logs_no_stop_on_any_path(control, monkeypatch, path):
    calls = []
    monkeypatch.setattr(qloop.lanes, "mark_lane_stopped", lambda *a, **k: calls.append(a))
    kw, stopped_by = _stop_path(path, monkeypatch)
    summary = qloop.run_loop(control_dir=control, cycle_log=control / "c.jsonl",
                             emit=_quiet, **kw)
    assert summary["stopped_by"] == stopped_by
    assert calls == []


def test_a_hard_stop_after_an_open_cap_stop_replaces_its_reason(control, monkeypatch):
    """The newest stop is the open one, so the next claim resumes it as STOP."""
    lanes.mark_lane_stopped("queue", "cap", root=control / "lanes")
    kw, _ = _stop_path("consecutive_errors", monkeypatch)
    qloop.run_loop(control_dir=control, status_root=control / "lanes",
                   cycle_log=control / "c.jsonl", emit=_quiet, **kw)
    assert _status(control / "lanes") == [["queue", "stop", "cap"], ["queue", "stop", "STOP"]]
    assert lanes.mark_lane_resumed("queue", root=control / "lanes") is True
    assert _status(control / "lanes")[-1] == ["queue", "resume", "STOP"]


@pytest.mark.parametrize("argv,expected", [
    (True, lambda tmp: tmp / "c" / "lanes"),
    (False, lambda _tmp: qloop.CONTROL / "lanes"),
])
def test_main_injects_the_control_dirs_lanes_folder(tmp_path, monkeypatch, argv, expected):
    seen = {}

    def fake_run_loop(**kw):
        seen.update(kw)
        return {"cycles_run": 0, "stopped_by": "max_cycles", "records": []}

    monkeypatch.setattr(qloop, "run_loop", fake_run_loop)
    args = ["--once", "--reports-dir", str(tmp_path / "r")]
    if argv:
        args += ["--control-dir", str(tmp_path / "c")]
    assert qloop.main(args, singleton=contextlib.nullcontext) == 0
    assert seen["status_root"] == expected(tmp_path)

"""RM-1270 (MAIN ORDER 2215 item 6, the live half): queue_loop.run_loop writes the
lane_status.log stop and resume lines, under an injected root only.

No injected root writes nothing at all, which is what keeps the existing run_loop
callers in the test files away from the live log. main() is the one injector.
"""
from __future__ import annotations

import contextlib

import pytest

from tests.test_queue_loop import _loop_seams, lanes, qloop


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

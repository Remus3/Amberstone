"""MAIN ORDER 2026-10-31 2215 item 6: ops/loop/lanes.py appends one line per lane
stop / resume to ops/loop/control/lane_status.log, with its reason.

The shape is pinned here because a reader greps the log by column. The refusal
paths are driven through the real kit lock layer on a tmp tree, so a live
lane_status.log is never touched.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lanes = _load("rc_loop_lanes_status_log_test", ROOT / "ops" / "loop" / "lanes.py")
LINE_RE = re.compile(
    r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d (?P<lane>\S+) "
    r"(?P<action>stop|resume) (?P<reason>limit|STOP|operator|cap)$")


@pytest.fixture
def root(tmp_path):
    lanes_dir = tmp_path / "ops" / "loop" / "control" / "lanes"
    lanes_dir.mkdir(parents=True)
    lanes._STOPPED.clear()
    yield lanes_dir
    lanes._STOPPED.clear()


def _log(root) -> list:
    path = root.parent / "lane_status.log"
    return path.read_text(encoding="ascii").splitlines() if path.exists() else []


def _worktree(tmp_path, name) -> str:
    wt = tmp_path / "wt" / name
    wt.mkdir(parents=True, exist_ok=True)
    return str(wt)


@pytest.mark.parametrize("action,reason", [
    ("stop", "limit"), ("stop", "STOP"), ("stop", "operator"), ("stop", "cap"),
    ("resume", "limit"), ("resume", "STOP"), ("resume", "operator"), ("resume", "cap"),
])
def test_line_shape_is_ts_lane_action_reason(root, action, reason):
    assert lanes.log_lane_event("ds", action, reason, root=root) is True
    lines = _log(root)
    assert len(lines) == 1
    match = LINE_RE.match(lines[0])
    assert match, lines[0]
    assert match.group("lane", "action", "reason") == ("ds", action, reason)


def test_lines_append_and_end_in_lf(root):
    lanes.log_lane_event("ds", "stop", "cap", root=root)
    lanes.log_lane_event("ds", "resume", "cap", root=root)
    raw = (root.parent / "lane_status.log").read_bytes()
    assert raw.count(b"\n") == 2 and b"\r" not in raw and raw.endswith(b"\n")


@pytest.mark.parametrize("action,reason", [
    ("paused", "cap"), ("stop", "because"), ("stop", ""), ("", "cap"),
])
def test_an_unknown_action_or_reason_is_refused_and_writes_nothing(root, action, reason):
    with pytest.raises(ValueError):
        lanes.log_lane_event("ds", action, reason, root=root)
    assert _log(root) == []


def test_a_lane_name_with_a_space_cannot_break_the_columns(root):
    with pytest.raises(ValueError):
        lanes.log_lane_event("d s", "stop", "cap", root=root)
    assert _log(root) == []


def test_a_log_fault_never_raises(root, monkeypatch):
    def boom(_path, _data):
        raise OSError("disk gone")
    monkeypatch.setattr(lanes, "_append_status_line", boom)
    assert lanes.log_lane_event("ds", "stop", "cap", root=root) is False


def test_a_cap_refusal_logs_once_then_resume_on_the_next_acquire(root, tmp_path, monkeypatch):
    monkeypatch.setattr(lanes.fleet_lanes, "try_acquire_lane",
                        lambda *a, **k: {"ok": False, "refused": "lanes_full", "holders": []})
    for _ in range(3):
        assert lanes.try_acquire_lane("ds", run_id="r", worktree=_worktree(tmp_path, "a"),
                                      root=root)["refused"] == "lanes_full"
    assert [line.split()[1:] for line in _log(root)] == [["ds", "stop", "cap"]]
    monkeypatch.undo()
    got = lanes.try_acquire_lane("ds", run_id="r", worktree=_worktree(tmp_path, "b"), root=root)
    assert got["ok"] is True
    lanes.release_lane(got["token"], root=root)
    assert [line.split()[1:] for line in _log(root)] == [
        ["ds", "stop", "cap"], ["ds", "resume", "cap"]]


def test_an_admission_refusal_is_a_cap_stop(root, tmp_path, monkeypatch):
    monkeypatch.setattr(lanes.fleet_lanes, "try_acquire_lane",
                        lambda *a, **k: {"ok": False, "refused": "admission", "reason": "ram"})
    lanes.try_acquire_lane("ds", run_id="r", worktree=_worktree(tmp_path, "a"), root=root)
    assert [line.split()[1:] for line in _log(root)] == [["ds", "stop", "cap"]]


def test_a_held_name_is_not_a_stop(root, tmp_path):
    got = lanes.try_acquire_lane("ds", run_id="r1", worktree=_worktree(tmp_path, "a"), root=root)
    assert got["ok"] is True
    again = lanes.try_acquire_lane("ds", run_id="r2", worktree=_worktree(tmp_path, "b"), root=root)
    assert again["refused"] == "lane_held"
    lanes.release_lane(got["token"], root=root)
    assert _log(root) == []


def test_a_plain_acquire_with_no_prior_stop_logs_nothing(root, tmp_path):
    got = lanes.try_acquire_lane("ds", run_id="r", worktree=_worktree(tmp_path, "a"), root=root)
    assert got["ok"] is True
    lanes.release_lane(got["token"], root=root)
    assert _log(root) == []


def test_a_stop_and_resume_for_a_stop_file_pair_up(root):
    assert lanes.mark_lane_stopped("queue", "STOP", root=root) is True
    assert lanes.mark_lane_stopped("queue", "STOP", root=root) is False
    assert lanes.mark_lane_resumed("queue", root=root) is True
    assert lanes.mark_lane_resumed("queue", root=root) is False
    assert [line.split()[1:] for line in _log(root)] == [
        ["queue", "stop", "STOP"], ["queue", "resume", "STOP"]]

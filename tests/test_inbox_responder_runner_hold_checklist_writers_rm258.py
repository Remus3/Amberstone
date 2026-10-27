"""RM-258: the runner's hold-artifact and fire-checklist writers are atomic.

tools/inbox_responder_runner.py `_hold_write` publishes the per-cycle hold
artifacts the operator reads (status.txt, note.txt, proposal.json,
reasons.json, draft.md ...), and `fire_checklist` keeps the headless fire's run
counter (inbox_responder_fires.txt) and its rendered item-13 block
(inbox_responder_checklist.txt). Each hand-rolled `<name>.tmp` plus a bare
Path.replace: a destination-derived scratch name, no fsync and no WinError 5
retry. A refused rename on the counter silently loses the run count (the
caller swallows every fault), so the next fire re-uses a session number.

They now route through core.polled_json. On-disk bytes are unchanged:
`_hold_write` still encodes ASCII with backslashreplace and no newline
translation, and the checklist files keep their exact UTF-8 bytes.

No process, no live inbox, no git: tmp roots only. The progress-file write
(tools.session_checklist.write_progress) is stubbed so nothing reaches a live
progress directory.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import core.polled_json as pj
from tools import inbox_responder_runner as runner
from tools import session_checklist as scl

CYCLE = "20261027T120000Z-abcd"
TEXT = "line one\nnon-ascii \u00e9 here\n"
TEXT_BYTES = b"line one\nnon-ascii \\xe9 here\n"


def _record_writes(monkeypatch):
    seen = []
    real = pj._write_then_replace

    def rec(path, data):
        seen.append((Path(path).name, bytes(data)))
        return real(path, data)

    monkeypatch.setattr(pj, "_write_then_replace", rec)
    return seen


def _flaky_rename(monkeypatch, count: int):
    real = pj.os.replace
    refusals = [count]

    def flaky(src, dst):
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(pj.os, "replace", flaky)
    monkeypatch.setattr(pj.time, "sleep", lambda _s: None)
    return refusals


@pytest.fixture
def no_progress(monkeypatch):
    calls = []
    monkeypatch.setattr(scl, "write_progress", lambda *a, **k: calls.append((a, k)) or {})
    return calls


def _result(root):
    return SimpleNamespace(root=root, cycle_id=CYCLE)


def test_rm258_hold_write_routes_through_polled_json(tmp_path, monkeypatch):
    seen = _record_writes(monkeypatch)
    path = runner._hold_write(_result(tmp_path), "status.txt", TEXT)
    assert path == runner.held_dir(tmp_path, CYCLE) / "status.txt"
    assert seen == [("status.txt", TEXT_BYTES)]
    assert path.read_bytes() == TEXT_BYTES
    assert b"\r" not in path.read_bytes()
    assert [x.name for x in path.parent.iterdir()] == ["status.txt"]


def test_rm258_hold_write_survives_a_transient_rename_refusal(tmp_path, monkeypatch):
    refusals = _flaky_rename(monkeypatch, 2)
    path = runner._hold_write(_result(tmp_path), "note.txt", TEXT)
    assert refusals == [0]
    assert path.read_bytes() == TEXT_BYTES
    assert [x.name for x in path.parent.iterdir()] == ["note.txt"]


def test_rm258_fire_checklist_writes_route_through_polled_json(tmp_path, monkeypatch,
                                                               no_progress):
    seen = _record_writes(monkeypatch)
    block = runner.fire_checklist(tmp_path, "c1")
    assert block is not None
    expected_log = (block + "\n").encode("utf-8")
    assert seen == [(runner.CHECKLIST_COUNT_NAME, b"1\n"),
                    (runner.CHECKLIST_LOG_NAME, expected_log)]
    rt = tmp_path / "ops" / "runtime"
    assert (rt / runner.CHECKLIST_COUNT_NAME).read_bytes() == b"1\n"
    assert (rt / runner.CHECKLIST_LOG_NAME).read_bytes() == expected_log
    assert sorted(x.name for x in rt.iterdir()) == sorted(
        [runner.CHECKLIST_COUNT_NAME, runner.CHECKLIST_LOG_NAME])
    assert len(no_progress) == 1


def test_rm258_fire_checklist_end_reuses_the_count(tmp_path, monkeypatch, no_progress):
    runner.fire_checklist(tmp_path, "c1")
    seen = _record_writes(monkeypatch)
    block = runner.fire_checklist(tmp_path, "c1", done=True, termination="answered")
    # The end write re-renders the log and leaves the counter alone.
    assert seen == [(runner.CHECKLIST_LOG_NAME, (block + "\n").encode("utf-8"))]
    counter = tmp_path / "ops" / "runtime" / runner.CHECKLIST_COUNT_NAME
    assert counter.read_bytes() == b"1\n"


def test_rm258_fire_checklist_count_survives_a_transient_rename_refusal(tmp_path, monkeypatch,
                                                                       no_progress):
    """Before RM-258 one refused rename lost the run count silently (the
    caller swallows the fault), so the next fire re-used the session number."""
    refusals = _flaky_rename(monkeypatch, 2)
    assert runner.fire_checklist(tmp_path, "c1") is not None
    assert refusals == [0]
    counter = tmp_path / "ops" / "runtime" / runner.CHECKLIST_COUNT_NAME
    assert counter.read_bytes() == b"1\n"
    assert runner.fire_checklist(tmp_path, "c2") is not None
    assert counter.read_bytes() == b"2\n"

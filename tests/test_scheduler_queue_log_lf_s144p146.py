"""RM-481 residual (s144, RM-1532): the task-queue log is written as LF.

``Scheduler`` opens ``task_queue.jsonl`` in text mode twice with no
``newline=``: ``_append_log`` ("a") and ``_open_for_rewrite`` ("r+", used by
``compact()``). On Windows the text layer turns every "\\n" into "\\r\\n", so
the file the supervisor and the cron shim share carried CRLF. The LF sweep
(tests/test_tracked_writer_lf_sweep.py) never saw it: its detector looked for
"w" modes only and skipped "r+" / "x", and the tree-wide ratchet inherits that
detector. This module pins both writers to LF bytes and the detector to the
two write modes it missed.

``pathlib.Path.open`` reaches ``io.open``, not ``builtins.open``, so the shared
``force_crlf`` fixture does not intercept it; the fixture below patches
``Path.open`` directly and proves itself with a positive control.
"""
from __future__ import annotations

import pathlib

import pytest

from tests.test_scheduler_queue_reload import (
    QueueTask,
    _external_append,
    _new_scheduler,
    _record_line,
)
from tests.test_tracked_writer_lf_sweep import _violations


@pytest.fixture
def path_open_crlf(monkeypatch):
    """Reproduce the Windows LF -> CRLF text translation on Path.open."""
    orig = pathlib.Path.open

    def _open(self, mode="r", buffering=-1, encoding=None, errors=None,
              newline=None):
        if "b" not in mode and any(c in mode for c in "wax+") and newline is None:
            newline = "\r\n"
        return orig(self, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(pathlib.Path, "open", _open)


def test_positive_control_bare_path_open_produces_crlf(tmp_path, path_open_crlf):
    target = tmp_path / "control.txt"
    with target.open("w", encoding="utf-8") as fh:
        fh.write("a\nb\n")
    assert target.read_bytes() == b"a\r\nb\r\n", "harness failed to force CRLF"


def test_append_log_writes_lf(tmp_path, path_open_crlf):
    log = tmp_path / "q.jsonl"
    s = _new_scheduler(log)
    ts = "2026-11-05T00:00:00+00:00"
    for tid in ("t-a", "t-b"):
        s._append_log("filed", QueueTask(
            id=tid, op="op", owner_agent="6", priority=50, status="ready",
            created_at=ts, updated_at=ts))
    raw = log.read_bytes()
    assert raw.count(b"\n") == 2
    assert b"\r" not in raw


def test_compact_rewrites_lf(tmp_path, path_open_crlf):
    log = tmp_path / "q.jsonl"
    s = _new_scheduler(log, precreate=True)
    _external_append(log, _record_line("t-a", priority=20))
    _external_append(log, _record_line("t-b", priority=30))
    _external_append(log, _record_line("t-b", priority=31, event="updated"))
    assert s.compact() == (3, 2)
    raw = log.read_bytes()
    assert raw.count(b"\n") == 2
    assert b"\r" not in raw


def test_compact_still_reads_a_crlf_file_written_by_an_older_build(tmp_path):
    """The reader side stays tolerant: an existing CRLF log compacts to LF."""
    log = tmp_path / "q.jsonl"
    s = _new_scheduler(log, precreate=True)
    lines = [_record_line("t-a"), _record_line("t-a", event="updated"),
             _record_line("t-b")]
    log.write_bytes(b"".join(line.rstrip("\n").encode("utf-8") + b"\r\n"
                             for line in lines))
    assert s.compact() == (3, 2)
    raw = log.read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2


@pytest.mark.parametrize("mode", ["r+", "x", "w", "xt", "r+t"])
def test_detector_flags_every_text_write_mode_without_newline(mode):
    assert len(_violations(f"open('f', {mode!r}, encoding='utf-8')\n")) == 1
    assert len(_violations(f"p.open({mode!r}, encoding='utf-8')\n")) == 1
    assert _violations(f"p.open({mode!r}, encoding='utf-8', newline='\\n')\n") == []


@pytest.mark.parametrize("mode", ["r", "rb", "rb+", "r+b", "xb", "wb", "a", "ab"])
def test_detector_leaves_read_binary_and_append_modes_alone(mode):
    assert _violations(f"open('f', {mode!r})\n") == []

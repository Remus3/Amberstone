"""RM-258 residual: tools/replay_roster_pull.py writes its status file through
core.polled_json.

The tool is the hourly RC-ReplayRosterPull scheduled task (docs/OPERATIONS.md
scheduled-task table), so `_write_status` runs unattended every hour against
`ops/runtime/replay_roster_status.json`. It wrote a destination-derived
`<status>.json.tmp` scratch with Path.write_text (CRLF on Windows) and swapped
it in with a bare Path.replace: no fsync, no WinError 5 retry while a reader
holds the target open, one scratch name for every concurrent run (a manual
run overlapping the hourly one), and a refused rename left the scratch file
behind.

The write now goes through `polled_json.atomic_write_text` (per-writer scratch
name, fsync, bounded retry, scratch removed on failure, LF bytes verbatim). An
OSError is still logged and swallowed: the status file is a verdict record and
must never turn a finished pull into a crash.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import polled_json  # noqa: E402
from tools import replay_roster_pull as rpp  # noqa: E402

_DOC = {"updated": "2026-10-28T00:00:00+00:00", "accounts": 3, "stale_ids": 1,
        "replays_blocked": False, "replays_blocked_accounts": 0,
        "blocked_acknowledged": False, "exit": 0}


@pytest.fixture
def status(tmp_path, monkeypatch):
    path = tmp_path / "runtime" / "replay_roster_status.json"
    monkeypatch.setattr(rpp, "_STATUS_PATH", path)
    return path


def _spy_replace(monkeypatch):
    seen = []
    real = polled_json._replace_with_retry

    def spy(src, dst):
        seen.append((Path(src), Path(dst)))
        real(src, dst)

    monkeypatch.setattr(polled_json, "_replace_with_retry", spy)
    return seen


def test_the_status_file_is_renamed_through_polled_json(status, monkeypatch):
    seen = _spy_replace(monkeypatch)
    rpp._write_status(dict(_DOC))
    assert len(seen) == 1, seen
    src, dst = seen[0]
    assert dst == status
    # Per-writer scratch (pid + token) beside the target, never `<name>.tmp`.
    assert src.parent == status.parent
    assert re.fullmatch(
        re.escape(f"{status.name}.{os.getpid()}.") + r"[0-9a-f]{8}\.tmp",
        src.name), src.name
    # Same document and layout the old writer serialized, LF only on disk.
    expected = (json.dumps(_DOC, indent=2, sort_keys=True) + "\n").encode("utf-8")
    assert status.read_bytes() == expected
    assert b"\r" not in status.read_bytes()
    assert [p.name for p in status.parent.iterdir()] == [status.name]


def test_a_refused_rename_is_logged_and_leaves_no_scratch(status, monkeypatch,
                                                          caplog):
    status.parent.mkdir(parents=True)
    status.write_bytes(b'{"exit": 1}\n')

    def refused(src, dst):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", refused)
    with caplog.at_level(logging.WARNING, logger="replay_roster_pull"):
        rpp._write_status(dict(_DOC))  # swallowed, never raised
    assert "could not write" in caplog.text
    # The previous verdict survives intact and no scratch file is left behind.
    assert status.read_bytes() == b'{"exit": 1}\n'
    assert [p.name for p in status.parent.iterdir()] == [status.name]

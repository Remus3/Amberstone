"""RM-263 - the polled-JSON writers must be crash-durable, not only reader-atomic.

core/polled_json._write_then_replace used to do `tmp.write_bytes(data)` then
os.replace with no flush/fsync. A rename is ordered on NTFS but the scratch
file's DATA is not guaranteed on disk, so a hard kill (`taskkill /F` is RC's
prescribed restart path) or a power loss between the write and the lazy flush
can publish a correctly-named destination holding zero or partial bytes.

Measured 2026-10-04 on Legion before adopting the fix (2.2 KB indented JSON,
200 writes per arm, tmp + os.replace on the repo volume):
  no fsync: median 0.56-0.59 ms, p95 0.65-0.70 ms
  fsync:    median 1.73-1.85 ms, p95 3.64-3.66 ms
So the cost is ~1.2 ms median / ~3 ms p95 per write, against a coach tick
measured in seconds - adopted.

The guard is STRUCTURAL: it records the order of fsync and os.replace and
asserts the scratch file's descriptor was fsynced BEFORE the rename published
it. A crash cannot be simulated portably; the ordering is what makes it safe.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import core.polled_json as pj


def _record(monkeypatch):
    events: list[tuple[str, object]] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def fake_fsync(fd):
        events.append(("fsync", fd))
        return real_fsync(fd)

    def fake_replace(src, dst):
        events.append(("replace", Path(src).name))
        return real_replace(src, dst)

    monkeypatch.setattr(pj.os, "fsync", fake_fsync)
    monkeypatch.setattr(pj.os, "replace", fake_replace)
    return events


@pytest.mark.parametrize(
    "writer, arg",
    [
        (pj.atomic_write_json, {"a": 1}),
        (pj.atomic_write_text, "restart\n"),
        (pj.atomic_write_bytes, b"\x00\x01"),
    ],
)
def test_scratch_file_is_fsynced_before_the_rename(tmp_path, monkeypatch, writer, arg):
    events = _record(monkeypatch)
    dest = tmp_path / "x.json"
    writer(dest, arg)
    kinds = [k for k, _ in events]
    assert "fsync" in kinds, f"no fsync before publish: {events}"
    assert kinds.index("fsync") < kinds.index("replace"), events
    assert dest.exists()


def test_fsync_failure_aborts_the_publish_and_leaves_no_scratch(tmp_path, monkeypatch):
    """If the data cannot be made durable the old destination must survive."""
    dest = tmp_path / "x.json"
    dest.write_bytes(b'{"old": true}')

    def boom(fd):
        raise OSError(5, "simulated fsync failure")

    monkeypatch.setattr(pj.os, "fsync", boom)
    with pytest.raises(OSError):
        pj.atomic_write_json(dest, {"new": True})
    assert dest.read_bytes() == b'{"old": true}'
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_docstring_claims_crash_durability_honestly():
    doc = pj.__doc__ or ""
    assert "fsync" in doc, "module docstring must state the crash-durability contract"

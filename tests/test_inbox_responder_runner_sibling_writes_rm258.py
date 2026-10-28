"""RM-258: the runner's two sibling-inbox writes use a per-writer scratch.

tools/inbox_responder_runner.py writes two files into a SIBLING's inbox: the
bounce (`_emit_bounce`, a tmp + rename) and the reply (`_deliver`, a tmp + a
no-clobber hard link). Both built their scratch from the destination alone
(`_<file>.tmp`), so two writers of one name shared one scratch file, and the
bounce finished with a bare Path.replace: no fsync, no WinError 5 retry, and
one refused rename silently dropped the bounce.

The leading `_` is load-bearing (the sibling's inbox reader skips underscore
names, so a half-written file is never read as a note), which is why these two
sites cannot use core.polled_json's `<name>.<pid>.<hex>.tmp` as is. They now
take `_<file>.<pid>.<hex>.tmp`, and the bounce renames through
core.polled_json's bounded retry after an fsync. Bytes on disk are unchanged.

tmp roots only: no process, no live inbox, no git.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

import core.polled_json as pj
from tools import inbox_responder_runner as runner


def _result(root: Path, inbox: Path, *, detail: str = "empty-proposal",
            cycle_id: str = "20261027T000000-1-abcdef") -> runner.CycleResult:
    return runner.CycleResult(
        cycle_id=cycle_id, ts="2026-10-27T00:00:00", pid=os.getpid(), dry=False,
        root=root, log_root=root, termination="exhausted",
        termination_detail=detail, agreement_id="agr-1",
        note="2026-10-27-0000-from-ZZ-to-RC-synthetic.md", note_sha12="0" * 12,
        sender="ZZ", bounce_target=inbox)


@pytest.fixture
def dirs(tmp_path):
    root = tmp_path / "root"
    inbox = tmp_path / "inbox"
    root.mkdir()
    inbox.mkdir()
    return root, inbox


def _record_renames(monkeypatch, inbox: Path):
    seen: list[tuple[str, str]] = []
    real_replace, real_fsync = pj.os.replace, pj.os.fsync

    def rec_replace(src, dst):
        kind = "replace" if Path(dst).parent == inbox else "replace-other"
        seen.append((kind, Path(src).name))
        return real_replace(src, dst)

    def rec_fsync(fd):
        seen.append(("fsync", ""))
        return real_fsync(fd)

    monkeypatch.setattr(pj.os, "replace", rec_replace)
    monkeypatch.setattr(pj.os, "fsync", rec_fsync)
    return seen


def _bounce_scratch(seen) -> list[str]:
    return [name for kind, name in seen if kind == "replace"]


def _assert_hidden_per_writer(name: str, filename: str) -> None:
    assert name.startswith("_" + filename + "."), name
    assert name.endswith(".tmp"), name
    assert f".{os.getpid()}." in name, name


def test_bounce_scratch_is_hidden_and_per_writer(dirs, monkeypatch):
    root, inbox = dirs
    seen = _record_renames(monkeypatch, inbox)
    first = _result(root, inbox, cycle_id="20261027T000000-1-aaaaaa")
    second = _result(root, inbox, cycle_id="20261027T000001-1-bbbbbb")
    second.note_sha12 = "1" * 12
    runner._emit_bounce(first)
    runner._emit_bounce(second)
    names = _bounce_scratch(seen)
    assert len(names) == 2, seen
    assert names[0] != names[1]
    _assert_hidden_per_writer(names[0], first.bounce["filename"])
    _assert_hidden_per_writer(names[1], second.bounce["filename"])


def test_bounce_fsyncs_before_the_rename(dirs, monkeypatch):
    root, inbox = dirs
    seen = _record_renames(monkeypatch, inbox)
    result = _result(root, inbox)
    runner._emit_bounce(result)
    # The allowance record is written first (its own fsync + rename), so the
    # bounce's fsync is the event right before the inbox rename, not any fsync.
    kinds = [kind for kind, _ in seen]
    assert kinds.count("replace") == 1, seen
    assert kinds[kinds.index("replace") - 1] == "fsync", seen


def test_bounce_bytes_are_unchanged(dirs):
    root, inbox = dirs
    result = _result(root, inbox, detail="rule:caf" + chr(0xE9))
    runner._emit_bounce(result)
    data = (inbox / result.bounce["filename"]).read_bytes()
    assert data == runner.bounce_body(result).encode("ascii", errors="backslashreplace")
    assert b"\r" not in data
    assert b"caf\\xe9" in data


def test_bounce_survives_two_transient_permission_errors(dirs, monkeypatch):
    root, inbox = dirs
    real = pj.os.replace
    refusals = [2]

    def flaky(src, dst):
        if Path(dst).parent == inbox and refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(pj.os, "replace", flaky)
    monkeypatch.setattr(pj.time, "sleep", lambda _s: None)
    result = _result(root, inbox)
    runner._emit_bounce(result)
    assert refusals == [0]
    assert result.bounce is not None
    assert [p.name for p in inbox.iterdir()] == [result.bounce["filename"]]


def test_a_bounce_refused_for_good_leaves_no_scratch(dirs, monkeypatch):
    root, inbox = dirs
    real = pj.os.replace

    def refused(src, dst):
        if Path(dst).parent == inbox:
            raise PermissionError(13, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(pj.os, "replace", refused)
    monkeypatch.setattr(pj.time, "sleep", lambda _s: None)
    result = _result(root, inbox)
    runner._emit_bounce(result)
    assert result.bounce is None
    assert list(inbox.iterdir()) == []


def test_bounce_leaves_another_writers_fixed_name_scratch_alone(dirs):
    root, inbox = dirs
    result = _result(root, inbox)
    filename = runner.bounce_filename(result.cycle_id, result.note)
    planted = inbox / ("_" + filename + ".tmp")
    planted.write_bytes(b"another writer\n")
    runner._emit_bounce(result)
    assert planted.read_bytes() == b"another writer\n"
    assert (inbox / filename).read_bytes() == runner.bounce_body(result).encode("ascii")


def _deliver(root: Path, inbox: Path, filename: str, assembled: str):
    note = root / "note.md"
    note.write_bytes(b"note\n")
    result = _result(root, inbox)
    return runner._deliver(result, inbox, filename, assembled, result.note, {},
                           note.stat(), datetime.now())


def test_delivery_scratch_is_hidden_and_per_writer(dirs, monkeypatch):
    root, inbox = dirs
    seen: list[str] = []
    real = runner.deliver_link

    def rec(tmp, dest):
        seen.append(Path(tmp).name)
        return real(tmp, dest)

    monkeypatch.setattr(runner, "deliver_link", rec)
    assert _deliver(root, inbox, "reply-a.md", "a\n") is None
    assert _deliver(root, inbox, "reply-b.md", "b\n") is None
    assert len(seen) == 2
    _assert_hidden_per_writer(seen[0], "reply-a.md")
    _assert_hidden_per_writer(seen[1], "reply-b.md")
    assert sorted(p.name for p in inbox.iterdir()) == ["reply-a.md", "reply-b.md"]
    assert (inbox / "reply-a.md").read_bytes() == b"a\n"


def test_delivery_leaves_another_writers_fixed_name_scratch_alone(dirs):
    root, inbox = dirs
    planted = inbox / "_reply.md.tmp"
    planted.write_bytes(b"another writer\n")
    assert _deliver(root, inbox, "reply.md", "ours\n") is None
    assert planted.read_bytes() == b"another writer\n"
    assert (inbox / "reply.md").read_bytes() == b"ours\n"

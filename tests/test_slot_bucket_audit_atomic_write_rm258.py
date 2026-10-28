"""RM-258 residual: the slot_bucket_audit hold-corpus write goes through core.polled_json.

`main()` in tools/slot_bucket_audit.py (`--hold-corpus LOG --out FILE`)
hand-rolled a destination-derived `<file>.tmp`, wrote it with
Path.write_bytes and swapped it in with a bare Path.replace: no fsync, no
WinError 5 retry, a scratch name shared by every concurrent run, no parent
created on demand, and a failed rename left the scratch file beside the
corpus.

Each test drives `main()` on a tiny synthetic controller log in tmp_path,
spies on `core.polled_json.atomic_write_bytes`, then checks the exact on-disk
bytes (the corpus serialized with indent=1, ASCII, one trailing LF, no CR)
and that no scratch file is left beside the corpus. Every path lives under
tmp_path; the bucket is never read.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core import polled_json
from tools import slot_bucket_audit as sba

_LOG = """2026-07-01T10:00:00 slots: acquired 0.lock (run_id=0000aaaa cycle=1)
2026-07-01T10:05:00 slots: released 0.lock
2026-07-01T10:06:00 slots: acquired 1.lock (run_id=0000bbbb cycle=2)
"""


@pytest.fixture
def spy(monkeypatch):
    calls = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def _log(tmp_path: Path) -> Path:
    p = tmp_path / "controller.log"
    p.write_bytes(_LOG.encode("ascii"))
    return p


def _scratch(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir() if p.name.endswith(".tmp"))


def test_hold_corpus_out_routes_through_polled_json(tmp_path, spy):
    log = _log(tmp_path)
    out = tmp_path / "sub" / "corpus.json"

    rc = sba.main(["--hold-corpus", str(log), "--out", str(out)])

    assert rc == 0
    expected = json.dumps(
        sba.hold_corpus(_LOG.splitlines(), sba.slots.DEFAULT_STALE_AFTER),
        indent=1) + "\n"
    assert [p for p, _ in spy] == [out]
    on_disk = out.read_bytes()
    assert on_disk == spy[0][1] == expected.encode("ascii")
    assert b"\r" not in on_disk
    assert json.loads(on_disk)["pairs"] == 1
    assert _scratch(out.parent) == []


def test_hold_corpus_without_out_writes_nothing(tmp_path, spy, capsys):
    log = _log(tmp_path)

    rc = sba.main(["--hold-corpus", str(log)])

    assert rc == 0
    assert spy == []
    assert json.loads(capsys.readouterr().out)["acquires"] == 2


def test_failed_swap_keeps_the_prior_corpus_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    log = _log(tmp_path)
    out = tmp_path / "corpus.json"
    before = b'{"prior": true}\n'
    out.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        sba.main(["--hold-corpus", str(log), "--out", str(out)])

    assert out.read_bytes() == before
    assert _scratch(tmp_path) == []

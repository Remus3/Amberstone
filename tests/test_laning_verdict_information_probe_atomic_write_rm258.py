"""RM-258 residual: the laning_verdict_information_probe artifact goes through core.polled_json.

`_write_report()` in tools/laning_verdict_information_probe.py (the `--out`
probe artifact, default ops/runtime/laning_verdict_information_probe.json)
hand-rolled a destination-derived `<out>.tmp`, wrote it with Path.write_text
(CRLF on Windows) and swapped it in with a bare os.replace: no fsync, no
WinError 5 retry, a scratch name shared by every concurrent run, and a failed
rename left the scratch file beside the artifact.

Each test calls `_write_report()` on a small synthetic report in tmp_path,
spies on `core.polled_json.atomic_write_bytes`, then checks the exact on-disk
bytes (indent=2, ASCII, no trailing newline, no CR) and that no scratch file
is left beside the artifact. Every path lives under tmp_path; the rewind DB
is never read.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core import polled_json
from tools import laning_verdict_information_probe as probe

_REPORT = {
    "generated_at": "2026-01-01T00:00:00+00:00",
    "mode": "sr",
    "levels": {"6": {"agreement": 0.5, "mutual_information_bits": 0.0}},
    "note": "caf" + chr(0xE9),
}


@pytest.fixture
def spy(monkeypatch):
    calls = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def _scratch(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir() if p.name.endswith(".tmp"))


def test_write_report_routes_through_polled_json(tmp_path, spy):
    out = tmp_path / "sub" / "laning_verdict_information_probe.json"

    probe._write_report(_REPORT, out)

    expected = json.dumps(_REPORT, indent=2, ensure_ascii=True).encode("ascii")
    assert [p for p, _ in spy] == [out]
    on_disk = out.read_bytes()
    assert on_disk == spy[0][1] == expected
    assert b"\r" not in on_disk
    assert json.loads(on_disk) == _REPORT
    assert _scratch(out.parent) == []


def test_write_report_replaces_a_prior_artifact(tmp_path, spy):
    out = tmp_path / "laning_verdict_information_probe.json"
    out.write_bytes(b'{"prior": true}')

    probe._write_report(_REPORT, out)

    assert json.loads(out.read_bytes()) == _REPORT
    assert _scratch(tmp_path) == []


def test_failed_swap_keeps_the_prior_artifact_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    out = tmp_path / "laning_verdict_information_probe.json"
    before = b'{"prior": true}'
    out.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        probe._write_report(_REPORT, out)

    assert out.read_bytes() == before
    assert _scratch(tmp_path) == []

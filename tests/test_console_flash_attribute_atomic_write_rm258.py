"""RM-258 residual: the console-flash report write goes through core.polled_json.

`_write_atomic` in tools/console_flash_attribute.py hand-rolled a
destination-derived `<file>.tmp` plus a bare `Path.replace`: no fsync, no
WinError 5 retry, a scratch name shared by every concurrent run, and a failed
rename left the scratch file beside the report. It also went through
`Path.write_text`, which on Windows rewrote every LF as CRLF.

Each test spies on `core.polled_json.atomic_write_bytes`, then checks the
exact on-disk bytes (the rendered report, ASCII with `?` for anything else,
LF only) and that no scratch file is left beside the report. Every path lives
under tmp_path.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import polled_json  # noqa: E402
from tools import console_flash_attribute as cfa  # noqa: E402

_TEXT = "line one\nline two \u00e9\n"
_EXPECTED = b"line one\nline two ?\n"


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


def test_report_write_routes_through_polled_json(tmp_path, spy):
    target = tmp_path / "sub" / "report.txt"

    cfa._write_atomic(target, _TEXT)

    assert [p for p, _ in spy] == [target]
    on_disk = target.read_bytes()
    assert on_disk == spy[0][1] == _EXPECTED
    assert b"\r" not in on_disk
    assert _scratch(target.parent) == []


def test_failed_swap_keeps_the_prior_report_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    target = tmp_path / "report.txt"
    before = b"prior report\n"
    target.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        cfa._write_atomic(target, _TEXT)

    assert target.read_bytes() == before
    assert _scratch(target.parent) == []

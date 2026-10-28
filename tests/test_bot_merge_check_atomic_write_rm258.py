"""RM-258 residual: the bot-merge-check watermark write goes through core.polled_json.

`_atomic_write` in tools/bot_merge_check.py hand-rolled a destination-derived
`<file>.json.tmp` plus a bare `Path.replace`: no fsync, no WinError 5 retry, a
scratch name shared by every concurrent run, and a failed rename left the
scratch file beside the watermark.

Each test spies on `core.polled_json.atomic_write_bytes`, then checks the
exact on-disk bytes (`json.dumps(..., sort_keys=True) + "\\n"` as ASCII, LF
only, unchanged from the old writer) and that no scratch file is left beside
the watermark. Every path lives under tmp_path.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import polled_json  # noqa: E402
from tools import bot_merge_check as bmc  # noqa: E402

_SHA = "0123456789abcdef0123456789abcdef01234567"
_NOW = "2026-10-27T12:00:00-05:00"


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


def _expected_bytes() -> bytes:
    return (json.dumps({"ref": "origin/main", "clean_through": _SHA,
                        "updated": _NOW}, sort_keys=True) + "\n").encode("ascii")


def test_watermark_write_routes_through_polled_json(tmp_path, spy, monkeypatch):
    monkeypatch.setattr(bmc, "_now", lambda: _NOW)
    state = tmp_path / bmc.STATE_REL

    bmc.write_state(tmp_path, "origin/main", _SHA)

    assert [p for p, _ in spy] == [state]
    on_disk = state.read_bytes()
    assert on_disk == spy[0][1] == _expected_bytes()
    assert b"\r" not in on_disk
    assert bmc._read_state(tmp_path)["clean_through"] == _SHA
    assert _scratch(state.parent) == []


def test_failed_swap_keeps_the_prior_watermark_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    monkeypatch.setattr(bmc, "_now", lambda: _NOW)
    state = tmp_path / bmc.STATE_REL
    state.parent.mkdir(parents=True)
    before = b'{"clean_through": "prior"}\n'
    state.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        bmc.write_state(tmp_path, "origin/main", _SHA)

    assert state.read_bytes() == before
    assert _scratch(state.parent) == []

"""RM-258 residual: the ds_patch_diff `--json` report write goes through core.polled_json.

`main()` in tools/ds_patch_diff.py hand-rolled a destination-derived
`<file>.tmp` plus a bare `Path.replace`: no fsync, no WinError 5 retry, a
scratch name shared by every concurrent run, and a failed rename left the
scratch file beside the report.

Each test spies on `core.polled_json.atomic_write_bytes`, then checks the
exact on-disk bytes (the report serialized with indent=1, ASCII-escaped,
LF only, no trailing newline - unchanged from the old writer) and that no
scratch file is left beside the report. Every path lives under tmp_path.
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
from tools import ds_patch_diff as dpd  # noqa: E402


def _snapshots(root: Path) -> tuple[Path, Path]:
    for patch, total in (("1.0", 300), ("2.0", 350)):
        d = root / patch
        d.mkdir(parents=True)
        items = {"version": patch, "data": {"1001": {
            "name": "Boots " + chr(0xE9),
            "gold": {"base": 300, "total": total, "sell": 210}}}}
        (d / "items.json").write_bytes(json.dumps(items).encode("utf-8"))
        (d / "manifest.json").write_bytes(
            json.dumps({"ddragon_version": patch}).encode("utf-8"))
    return root / "1.0", root / "2.0"


def _argv(old: Path, new: Path, out: Path) -> list[str]:
    return [str(old), str(new), "--sections", "items",
            "--json", str(out), "--quiet"]


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


def test_json_report_write_routes_through_polled_json(tmp_path, spy):
    old, new = _snapshots(tmp_path / "snaps")
    out = tmp_path / "sub" / "diff.json"

    assert dpd.main(_argv(old, new, out)) == 0

    expected = json.dumps(
        dpd.diff_snapshots(old, new, ["items"], 0.0), indent=1).encode("utf-8")
    assert [p for p, _ in spy] == [out]
    on_disk = out.read_bytes()
    assert on_disk == spy[0][1] == expected
    assert b"\r" not in on_disk
    assert _scratch(out.parent) == []


def test_failed_swap_keeps_the_prior_report_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    old, new = _snapshots(tmp_path / "snaps")
    out = tmp_path / "diff.json"
    before = b'{"prior": true}'
    out.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        dpd.main(_argv(old, new, out))

    assert out.read_bytes() == before
    assert _scratch(out.parent) == []

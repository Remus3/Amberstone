"""RM-258 residual: champion_loadout_validate_meta writes through core.polled_json.

`_atomic_write` in tools/champion_loadout_validate_meta.py rewrote the live
data/champion_loadouts.json (read by the running app's loadout resolver)
through a destination-derived `<target>.tmp` and a bare Path.replace: no
fsync, no WinError 5 retry, and one scratch name for every concurrent run.

Each test points the tool's `_LOADOUTS` at a tmp copy carrying one SR path
with its boots at items[2] (one BOOTS_AT_INDEX_2 fix), spies on
`core.polled_json.atomic_write_bytes`, then checks the exact on-disk bytes
(indent=2, ASCII, one trailing LF, no CR) and that no scratch file is left
beside the loadouts.
"""
from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from core import polled_json
from tools import champion_loadout_validate_meta as vm


def _loadouts(items: list[str]) -> dict:
    return {"champions": {"Ashe": {"variants": {"sr-collapsed": {
        "build_paths": [{"key": "core", "items": items}]}}}}}


_DRIFTED = ["Kraken Slayer", "Infinity Edge", "Berserker's Greaves",
            "Lord Dominik's Regards"]
_FIXED = ["Kraken Slayer", "Berserker's Greaves", "Infinity Edge",
          "Lord Dominik's Regards"]


def _bytes(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=True)
            + "\n").encode("ascii")


@pytest.fixture
def target(tmp_path, monkeypatch):
    path = tmp_path / "champion_loadouts.json"
    path.write_bytes(_bytes(_loadouts(_DRIFTED)))
    monkeypatch.setattr(vm, "_LOADOUTS", path)
    return path


@pytest.fixture
def spy(monkeypatch):
    calls = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def _run(monkeypatch, *flags: str) -> int:
    monkeypatch.setattr(sys, "argv", ["champion_loadout_validate_meta.py",
                                      *flags])
    with redirect_stdout(io.StringIO()):
        return vm.main()


def _scratch(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir() if p.name.endswith(".tmp"))


def test_fix_routes_through_polled_json(target, spy, monkeypatch):
    assert _run(monkeypatch, "--no-backup") == 0

    assert [p for p, _ in spy] == [target]
    on_disk = target.read_bytes()
    assert on_disk == spy[0][1] == _bytes(_loadouts(_FIXED))
    assert b"\r" not in on_disk
    assert _scratch(target.parent) == []
    assert sorted(p.name for p in target.parent.iterdir()) == [target.name]


def test_backup_still_written_before_the_swap(target, spy, monkeypatch):
    assert _run(monkeypatch) == 0

    assert [p for p, _ in spy] == [target]
    baks = sorted(target.parent.glob("champion_loadouts.json.bak-slice-a-*"))
    assert len(baks) == 1
    assert baks[0].read_bytes() == _bytes(_loadouts(_DRIFTED))
    assert target.read_bytes() == _bytes(_loadouts(_FIXED))
    assert _scratch(target.parent) == []


def test_failed_swap_keeps_the_prior_loadouts_and_leaves_no_scratch(
        target, monkeypatch):
    before = target.read_bytes()

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        _run(monkeypatch, "--no-backup")

    assert target.read_bytes() == before
    assert _scratch(target.parent) == []

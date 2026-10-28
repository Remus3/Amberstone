"""RM-258 residual: the item-213 loadout cleanup writes through core.polled_json.

`_atomic_write()` in tools/champion_loadout_cleanup_pollution_item213.py
rewrites data/champion_loadouts.json (the tracked file the dashboard and the
loadout producers read) through a destination-derived
`tempfile.mkstemp(prefix=path.name + ".")` scratch and a bare Path.replace:
no fsync, no WinError 5 retry, and a scratch file left behind when the swap
fails.

Each test writes into tmp_path, spies on
`core.polled_json.atomic_write_bytes`, then checks the exact on-disk bytes
(indent 2, ensure_ascii, one trailing LF) and that no scratch file is left
beside the target.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import polled_json
from tools import champion_loadout_cleanup_pollution_item213 as cl

_OBJ = {"champions": {"Kai'Sa": {"variants": {"sr-collapsed": {
    "label": "Caf" + chr(0xE9) + " build", "build_paths": [{"items": ["A", "B"]}]}}}}}


def _expected(obj) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=True) + "\n").encode("ascii")


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


def test_atomic_write_routes_through_polled_json(tmp_path, spy):
    target = tmp_path / "champion_loadouts.json"
    target.write_bytes(b"prior\n")

    cl._atomic_write(target, _OBJ)

    assert [p for p, _ in spy] == [target]
    assert spy[0][1] == target.read_bytes() == _expected(_OBJ)
    assert b"\r\n" not in target.read_bytes()
    assert _scratch(tmp_path) == []


def test_main_writes_the_loadouts_through_polled_json(tmp_path, monkeypatch, spy):
    target = tmp_path / "champion_loadouts.json"
    obj = {"champions": {}}
    target.write_bytes(_expected(obj))
    monkeypatch.setattr(cl, "_LOADOUTS_PATH", target)

    assert cl.main(["--no-backup"]) == 0

    assert [p for p, _ in spy] == [target]
    assert target.read_bytes() == _expected(obj)
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


def test_refused_swap_keeps_the_prior_file_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    target = tmp_path / "champion_loadouts.json"
    target.write_bytes(b"prior\n")
    fired = []

    def _refuse(a, b):
        fired.append((a, b))
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", _refuse)
    with pytest.raises(PermissionError):
        cl._atomic_write(target, _OBJ)
    assert len(fired) == 1
    assert target.read_bytes() == b"prior\n"
    assert _scratch(tmp_path) == []


def test_tool_carries_no_hand_rolled_rename():
    text = Path(cl.__file__).read_text(encoding="utf-8")
    assert "mkstemp(" not in text
    assert ".replace(path)" not in text

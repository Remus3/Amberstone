"""RM-258 residual: the item-s8 loadout sweep writes through core.polled_json.

`main()` in tools/champion_loadout_sweep_item_s8.py rewrote
data/champion_loadouts.json (the tracked file the dashboard and the loadout
producers read) through a fixed destination-derived `.json.tmp` scratch and a
bare Path.replace: no fsync, no WinError 5 retry, a scratch name shared by
any two concurrent runs, and the scratch left behind when the swap fails.

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
from tools import champion_loadout_sweep_item_s8 as sw

_OBJ = {"champions": {"Kai'Sa": {"label": "Caf" + chr(0xE9) + " build"}}}


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


def test_main_writes_the_loadouts_through_polled_json(tmp_path, monkeypatch, spy):
    target = tmp_path / "champion_loadouts.json"
    target.write_bytes(json.dumps(_OBJ).encode("ascii"))
    monkeypatch.setattr(sw, "_LOADOUTS_PATH", target)

    assert sw.main(["--no-backup"]) == 0

    assert [p for p, _ in spy] == [target]
    assert spy[0][1] == target.read_bytes() == _expected(_OBJ)
    assert b"\r\n" not in target.read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


def test_refused_swap_keeps_the_prior_file_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    target = tmp_path / "champion_loadouts.json"
    prior = json.dumps(_OBJ).encode("ascii")
    target.write_bytes(prior)
    monkeypatch.setattr(sw, "_LOADOUTS_PATH", target)
    fired = []

    def _refuse(a, b):
        fired.append((a, b))
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", _refuse)
    with pytest.raises(PermissionError):
        sw.main(["--no-backup"])
    assert len(fired) == 1
    assert target.read_bytes() == prior
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


def test_dry_run_writes_nothing(tmp_path, monkeypatch, spy):
    target = tmp_path / "champion_loadouts.json"
    prior = json.dumps(_OBJ).encode("ascii")
    target.write_bytes(prior)
    monkeypatch.setattr(sw, "_LOADOUTS_PATH", target)

    assert sw.main(["--dry-run"]) == 0

    assert spy == []
    assert target.read_bytes() == prior


def test_tool_carries_no_hand_rolled_rename():
    text = Path(sw.__file__).read_text(encoding="utf-8")
    assert '.with_suffix(".json.tmp")' not in text
    assert "tmp.replace(" not in text

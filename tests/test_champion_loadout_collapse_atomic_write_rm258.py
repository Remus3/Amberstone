"""RM-258 residual: the collapse tool writes the loadouts through core.polled_json.

`atomic_write_loadouts()` in tools/champion_loadout_collapse_to_paths.py
rewrote data/champion_loadouts.json (the tracked file the dashboard and the
loadout producers read) through its own tempfile.mkstemp + os.replace loop:
no fsync before the rename. Its `dest` default (and backup_loadouts') was
also bound at import time, so main() read a patched `_LOADOUTS_PATH` but
wrote and backed up the original one.

Each test writes into tmp_path, spies on
`core.polled_json.atomic_write_bytes`, then checks the exact on-disk bytes
(indent 2, ensure_ascii, one trailing LF) and that no scratch file is left
beside the target. The main() tests first assert the late-bound default, so
on the old source they fail before main() can touch the real data file.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from core import polled_json
from tools import champion_loadout_collapse_to_paths as cp

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


def _late_bound(fn) -> None:
    assert inspect.signature(fn).parameters["dest"].default is None, (
        f"{fn.__name__} binds its dest default at import time")


def test_writer_goes_through_polled_json(tmp_path, spy):
    target = tmp_path / "champion_loadouts.json"
    cp.atomic_write_loadouts(_OBJ, dest=target)

    assert [p for p, _ in spy] == [target]
    assert spy[0][1] == target.read_bytes() == _expected(_OBJ)
    assert b"\r\n" not in target.read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


def test_refused_swap_keeps_the_prior_file_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    target = tmp_path / "champion_loadouts.json"
    prior = json.dumps(_OBJ).encode("ascii")
    target.write_bytes(prior)
    fired = []

    def _refuse(a, b):
        fired.append((a, b))
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", _refuse)
    with pytest.raises(PermissionError):
        cp.atomic_write_loadouts(_OBJ, dest=target)
    assert len(fired) == 1
    assert target.read_bytes() == prior
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


def test_main_writes_and_backs_up_the_patched_path(tmp_path, monkeypatch, spy):
    _late_bound(cp.atomic_write_loadouts)
    _late_bound(cp.backup_loadouts)
    target = tmp_path / "champion_loadouts.json"
    prior = json.dumps(_OBJ).encode("ascii")
    target.write_bytes(prior)
    monkeypatch.setattr(cp, "_LOADOUTS_PATH", target)

    assert cp.main([]) == 0

    assert [p for p, _ in spy] == [target]
    assert target.read_bytes() == spy[0][1]
    baks = [p for p in tmp_path.iterdir() if p.name != target.name]
    assert [p.name.startswith(target.name + ".bak-item178-") for p in baks] == [True]
    assert baks[0].read_bytes() == prior


def test_dry_run_writes_nothing(tmp_path, monkeypatch, spy):
    _late_bound(cp.atomic_write_loadouts)
    target = tmp_path / "champion_loadouts.json"
    prior = json.dumps(_OBJ).encode("ascii")
    target.write_bytes(prior)
    monkeypatch.setattr(cp, "_LOADOUTS_PATH", target)

    assert cp.main(["--dry-run"]) == 0

    assert spy == []
    assert target.read_bytes() == prior
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


def test_tool_carries_no_hand_rolled_rename():
    text = Path(cp.__file__).read_text(encoding="utf-8")
    assert "mkstemp(" not in text
    assert "os.replace(" not in text

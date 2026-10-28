"""RM-258 residual: the autogen tool writes the loadouts through core.polled_json.

`atomic_write_loadouts()` in tools/champion_loadout_autogen.py rewrote
data/champion_loadouts.json (the tracked file the dashboard and the loadout
producers read) through its own tempfile.mkstemp + os.fdopen + os.replace
loop: no fsync before the rename and no WinError 5 retry.

Each test writes into tmp_path (through the module's `_LOADOUTS_PATH`, which
the writer reads at call time), spies on `core.polled_json.atomic_write_bytes`,
then checks the exact on-disk bytes (top-level order kept, champions and
variants sorted, indent 2, ensure_ascii False so UTF-8, one trailing LF) and
that no scratch file is left beside the target.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import polled_json
from tools import champion_loadout_autogen as autogen

_E_ACUTE = chr(0xE9)
_PAYLOAD = {
    "champions": {
        "Zed": {"default_per_mode": {}, "variants": {"b": {}, "a": {}}},
        "Kai'Sa": {"default_per_mode": {},
                   "variants": {"x": {"label": "Caf" + _E_ACUTE}}},
    },
    "_doc": ["d"],
    "_schema_version": 1,
}


def _expected() -> bytes:
    ordered = {
        "_schema_version": 1,
        "_doc": ["d"],
        "champions": {
            "Kai'Sa": {"default_per_mode": {},
                       "variants": {"x": {"label": "Caf" + _E_ACUTE}}},
            "Zed": {"default_per_mode": {}, "variants": {"a": {}, "b": {}}},
        },
    }
    text = json.dumps(ordered, ensure_ascii=False, indent=2) + "\n"
    return text.encode("utf-8")


@pytest.fixture
def target(tmp_path, monkeypatch):
    path = tmp_path / "champion_loadouts.json"
    monkeypatch.setattr(autogen, "_LOADOUTS_PATH", path)
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


def test_writer_goes_through_polled_json(target, spy):
    autogen.atomic_write_loadouts(_PAYLOAD)

    assert [p for p, _ in spy] == [target]
    assert spy[0][1] == target.read_bytes() == _expected()
    assert b"\r\n" not in target.read_bytes()
    assert sorted(p.name for p in target.parent.iterdir()) == [target.name]


def test_writer_creates_a_missing_parent(tmp_path, monkeypatch, spy):
    path = tmp_path / "data" / "champion_loadouts.json"
    monkeypatch.setattr(autogen, "_LOADOUTS_PATH", path)
    autogen.atomic_write_loadouts(_PAYLOAD)
    assert path.read_bytes() == _expected()


def test_refused_swap_keeps_the_prior_file_and_leaves_no_scratch(
        target, monkeypatch):
    prior = json.dumps(_PAYLOAD).encode("ascii")
    target.write_bytes(prior)
    fired = []

    def _refuse(a, b):
        fired.append((a, b))
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", _refuse)
    with pytest.raises(PermissionError):
        autogen.atomic_write_loadouts(_PAYLOAD)
    assert len(fired) == 1
    assert target.read_bytes() == prior
    assert sorted(p.name for p in target.parent.iterdir()) == [target.name]


def test_tool_carries_no_hand_rolled_rename():
    text = Path(autogen.__file__).read_text(encoding="utf-8")
    assert "mkstemp(" not in text
    assert "os.replace(" not in text

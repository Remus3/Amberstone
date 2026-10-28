"""RM-258 residual: the pick/ban target generator writes through core.polled_json.

`atomic_write()` in tools/daemon_slayer_pickban_targets_generate.py wrote
data/daemon_slayer/<patch>/pickban_targets.json (a tracked table the coach
reads) through its own tempfile.mkstemp + os.fdopen + os.replace loop: no
fsync before the rename and no WinError 5 retry.

Each test writes into tmp_path, spies on `core.polled_json.atomic_write_bytes`,
then checks that the on-disk bytes equal `_serialize()` (the --check path's
text) encoded as UTF-8, and that no scratch file is left beside the target.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import polled_json
from tools import daemon_slayer_pickban_targets_generate as gen

_PAYLOAD = {
    "patch": "16.11.1",
    "mode": "sr",
    "level": 11,
    "top_k": 3,
    "ranking": "debiased_relative",
    "targets": {
        "Zac": {"pick_into": ["Ahri"], "ban_against": ["Vayne"]},
        "Kai" + chr(0x2019) + "Sa": {"pick_into": [], "ban_against": []},
    },
}


def _expected() -> bytes:
    text = json.dumps(_PAYLOAD, ensure_ascii=True, indent=2, sort_keys=True)
    return (text + "\n").encode("utf-8")


@pytest.fixture
def spy(monkeypatch):
    calls = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def test_writer_goes_through_polled_json(tmp_path, spy):
    out = tmp_path / "pickban_targets.json"
    gen.atomic_write(_PAYLOAD, out)

    assert [p for p, _ in spy] == [out]
    assert spy[0][1] == out.read_bytes() == _expected()
    assert out.read_bytes() == gen._serialize(_PAYLOAD).encode("utf-8")
    assert b"\r\n" not in out.read_bytes()
    assert all(b < 0x80 for b in out.read_bytes())
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]


def test_writer_creates_a_missing_parent(tmp_path, spy):
    out = tmp_path / "16.11.1" / "pickban_targets.json"
    gen.atomic_write(_PAYLOAD, out)
    assert out.read_bytes() == _expected()


def test_refused_swap_keeps_the_prior_file_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    out = tmp_path / "pickban_targets.json"
    prior = b'{"prior": true}\n'
    out.write_bytes(prior)
    fired = []

    def _refuse(a, b):
        fired.append((a, b))
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", _refuse)
    with pytest.raises(PermissionError):
        gen.atomic_write(_PAYLOAD, out)
    assert len(fired) == 1
    assert out.read_bytes() == prior
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]


def test_tool_carries_no_hand_rolled_rename():
    text = Path(gen.__file__).read_text(encoding="utf-8")
    assert "mkstemp(" not in text
    assert "os.replace(" not in text

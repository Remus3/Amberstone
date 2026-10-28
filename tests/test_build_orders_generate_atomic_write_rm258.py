"""RM-258 residual: the build-order table generator writes through core.polled_json.

`atomic_write()` in tools/daemon_slayer_build_orders_generate.py wrote each
data/daemon_slayer/<patch>/build_orders_<mode>.json (tracked tables the coach
reads) through its own tempfile.mkstemp + os.fdopen + os.replace loop: no
fsync before the rename and no WinError 5 retry.

Each test writes into tmp_path, spies on `core.polled_json.atomic_write_bytes`,
then checks the exact on-disk bytes (sort_keys, indent 2, ensure_ascii True,
one trailing LF) and that no scratch file is left beside the target.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import polled_json
from tools import daemon_slayer_build_orders_generate as gen

_PAYLOAD = {
    "version": "16.11.1",
    "mode": "sr",
    "generated_at": "2026-06-02T00:00:00Z",
    "build_orders": {
        "Zac": {"ad_heavy": ["1"], "balanced": ["2"], "ap_heavy": ["3"]},
        "Kai" + chr(0x2019) + "Sa": {"ad_heavy": [], "balanced": [],
                                     "ap_heavy": []},
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
    out = tmp_path / "build_orders_sr.json"
    gen.atomic_write(_PAYLOAD, out)

    assert [p for p, _ in spy] == [out]
    assert spy[0][1] == out.read_bytes() == _expected()
    assert b"\r\n" not in out.read_bytes()
    assert all(b < 0x80 for b in out.read_bytes())
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]


def test_writer_creates_a_missing_parent(tmp_path, spy):
    out = tmp_path / "16.11.1" / "build_orders_sr.json"
    gen.atomic_write(_PAYLOAD, out)
    assert out.read_bytes() == _expected()


def test_refused_swap_keeps_the_prior_file_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    out = tmp_path / "build_orders_sr.json"
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

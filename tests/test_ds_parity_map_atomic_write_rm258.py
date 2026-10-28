"""RM-258 residual: the ds_parity_map `--json` map write goes through core.polled_json.

`main()` in tools/ds_parity_map.py hand-rolled a destination-derived
`<file>.tmp` plus a bare `Path.replace`: no fsync, no WinError 5 retry, a
scratch name shared by every concurrent run, and a failed rename left the
scratch file beside the map.

`build_map` is replaced with a synthetic map, so no test imports the DS
server. Each test spies on `core.polled_json.atomic_write_bytes`, then checks
the exact on-disk bytes (the map serialized with indent=2 and sort_keys,
ASCII-escaped, LF only, no trailing newline - unchanged from the old writer)
and that no scratch file is left beside the map. Every path lives under
tmp_path.
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
from tools import ds_parity_map as dpm  # noqa: E402

_MAP = {
    "/rank": {
        "body_keys": ["champion", "item_ids"],
        "engine": "rank_items " + chr(0xE9),
        "engine_params": ["champion", "item_ids", "rune_ids"],
        "carried": ["champion", "item_ids"],
        "dropped": [],
        "unreachable": ["rune_ids"],
    },
    "/dps": {
        "body_keys": ["champion"],
        "engine": "compute_dps",
        "engine_params": ["champion"],
        "carried": ["champion"],
        "dropped": [],
        "unreachable": [],
    },
}


@pytest.fixture
def synthetic_map(monkeypatch):
    monkeypatch.setattr(dpm, "build_map", lambda: json.loads(json.dumps(_MAP)))


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


def test_json_map_write_routes_through_polled_json(tmp_path, synthetic_map,
                                                   spy):
    out = tmp_path / "sub" / "ds_parity_map.json"

    assert dpm.main(["--json", "--out", str(out)]) == 0

    expected = json.dumps(_MAP, indent=2, sort_keys=True).encode("utf-8")
    assert [p for p, _ in spy] == [out]
    on_disk = out.read_bytes()
    assert on_disk == spy[0][1] == expected
    assert b"\r" not in on_disk
    assert _scratch(out.parent) == []


def test_failed_swap_keeps_the_prior_map_and_leaves_no_scratch(
        tmp_path, synthetic_map, monkeypatch):
    out = tmp_path / "ds_parity_map.json"
    before = b'{"prior": true}'
    out.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        dpm.main(["--json", "--out", str(out)])

    assert out.read_bytes() == before
    assert _scratch(out.parent) == []

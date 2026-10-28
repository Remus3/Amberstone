"""RM-258 residual: the DDragon mirror writers go through core.polled_json.

tools/ddragon_mirror_refresh.py runs as the daily RC-DDragonMirrorRefresh
task (docs/OPERATIONS.md) and fetches assets on a thread pool while the
dashboard serves the same tree. Its two helpers, `_atomic_write_bytes` (every
asset) and `_atomic_write_json` (bundles, champion details, the manifest and
_index.json), hand-rolled a destination-derived `<file>.tmp` plus a bare
os.replace: no fsync, no WinError 5 retry, one scratch name shared by every
concurrent writer of a file, and a failed rename left the scratch file beside
the target.

Each test spies on `core.polled_json.atomic_write_bytes`, then checks the
exact on-disk bytes (for JSON: indent=2, sort_keys, ASCII-escaped, LF only,
one trailing newline - unchanged from the old writer) and that no scratch file
is left. Every path lives under tmp_path; nothing touches the network.
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
from tools import ddragon_mirror_refresh as ddr  # noqa: E402

_PAYLOAD = {
    "latest_pulled": "16.18.1",
    "bundles": ["item", "champion"],
    "nested": {"b": [2, 3], "a": "synthetic " + chr(0xE9)},
}


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


def test_json_write_routes_through_polled_json(tmp_path, spy):
    out = tmp_path / "16.18.1" / "champion_detail" / "Ahri.json"

    ddr._atomic_write_json(out, _PAYLOAD)

    expected = (json.dumps(_PAYLOAD, indent=2, sort_keys=True) + "\n").encode(
        "utf-8")
    assert [p for p, _ in spy] == [out]
    on_disk = out.read_bytes()
    assert on_disk == spy[0][1] == expected
    assert b"\r" not in on_disk
    assert _scratch(out.parent) == []


def test_asset_write_routes_through_polled_json(tmp_path, spy):
    out = tmp_path / "web" / "16.18.1" / "img" / "item" / "1001.png"
    body = b"\x89PNG\r\n\x1a\n" + bytes(range(256))

    ddr._atomic_write_bytes(out, body)

    assert [p for p, _ in spy] == [out]
    assert out.read_bytes() == spy[0][1] == body
    assert _scratch(out.parent) == []


@pytest.mark.parametrize("writer, payload", [
    (ddr._atomic_write_json, _PAYLOAD),
    (ddr._atomic_write_bytes, b"new asset bytes"),
])
def test_failed_swap_keeps_the_prior_file_and_leaves_no_scratch(
        tmp_path, monkeypatch, writer, payload):
    out = tmp_path / "_index.json"
    before = b'{"prior": true}\n'
    out.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        writer(out, payload)

    assert out.read_bytes() == before
    assert _scratch(out.parent) == []

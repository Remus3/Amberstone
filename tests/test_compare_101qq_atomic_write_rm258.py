"""RM-258 residual: the compare_101qq_vs_ddragon id map goes through core.polled_json.

`main()` in tools/compare_101qq_vs_ddragon.py (the `--out` canonical
id_map.json) hand-rolled a destination-derived `<out>.tmp`, wrote it with
Path.write_text and swapped it in with a bare Path.replace: no fsync, no
WinError 5 retry, one scratch name shared by every concurrent run, and on
Windows write_text turned every LF of the indented JSON into CRLF.

Each test aligns the tracked wrapped 101.qq fixture (6 champion ids, the same
input tests/test_probe_101qq_script.py uses), spies on
`core.polled_json.atomic_write_text`, then checks the exact on-disk bytes
(the sorted, ASCII, indent=2 JSON, LF only) and that no scratch file is left
beside the map. The last test runs the tool as the bare
`python tools/compare_101qq_vs_ddragon.py` CLI (only tools/ on sys.path),
because the module keeps no top-level core import and the lazy one has to
resolve there too.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from core import polled_json
from tools import compare_101qq_vs_ddragon as cmp_mod

_TOOL = Path(cmp_mod.__file__).resolve()
_WRAPPED = (Path(__file__).resolve().parent / "fixtures" / "qq101"
            / "hero_rank_double_wrapped.json")


def _expected_bytes() -> bytes:
    raw = json.loads(_WRAPPED.read_text(encoding="utf-8-sig"))
    alignment = cmp_mod.build_alignment(cmp_mod.unwrap_envelope(raw),
                                        cmp_mod.load_ddragon_keys(),
                                        cmp_mod.load_override())
    assert len(alignment["aligned"]) == 6
    return json.dumps(alignment["aligned"], ensure_ascii=True, indent=2,
                      sort_keys=True).encode("ascii")


def _run(out: Path) -> int:
    with redirect_stdout(io.StringIO()):
        return cmp_mod.main(["--json", str(_WRAPPED), "--out", str(out)])


@pytest.fixture
def spy(monkeypatch):
    calls = []
    real = polled_json.atomic_write_text

    def _spy(path, content):
        calls.append((Path(path), content))
        real(path, content)

    monkeypatch.setattr(polled_json, "atomic_write_text", _spy)
    return calls


def _scratch(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir() if p.name.endswith(".tmp"))


def test_id_map_routes_through_polled_json(tmp_path, spy):
    out = tmp_path / "sub" / "101qq_id_map.json"

    assert _run(out) == 0

    assert [p for p, _ in spy] == [out]
    on_disk = out.read_bytes()
    assert on_disk == spy[0][1].encode("utf-8") == _expected_bytes()
    assert b"\r" not in on_disk
    assert _scratch(out.parent) == []


def test_id_map_replaces_a_prior_map(tmp_path, spy):
    out = tmp_path / "101qq_id_map.json"
    out.write_bytes(b"{}\n")

    assert _run(out) == 0

    assert out.read_bytes() == _expected_bytes()
    assert _scratch(tmp_path) == []


def test_failed_swap_keeps_the_prior_map_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    out = tmp_path / "101qq_id_map.json"
    before = b"{}\n"
    out.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        _run(out)

    assert out.read_bytes() == before
    assert _scratch(tmp_path) == []


def test_bare_cli_writes_the_map(tmp_path):
    out = tmp_path / "out" / "101qq_id_map.json"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [sys.executable, str(_TOOL), "--json", str(_WRAPPED),
         "--out", str(out)],
        cwd=str(tmp_path), env=env, capture_output=True, text=True,
        timeout=120, creationflags=flags)

    assert proc.returncode == 0, proc.stderr
    assert out.read_bytes() == _expected_bytes()
    assert _scratch(out.parent) == []

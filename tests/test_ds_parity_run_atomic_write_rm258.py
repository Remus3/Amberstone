"""RM-258 residual: the ds_parity_run report write goes through core.polled_json.

`main()` in tools/ds_parity_run.py hand-rolled a destination-derived
`<file>.tmp` plus a bare `Path.replace`: no fsync, no WinError 5 retry, a
scratch name shared by every concurrent run, and a failed rename left the
scratch file beside the report.

`run` is replaced with a synthetic report, so no test imports the DS server
or calls :8860. Each test spies on `core.polled_json.atomic_write_bytes`,
then checks the exact on-disk bytes (the report serialized with indent=2,
ASCII-escaped, LF only, no trailing newline - unchanged from the old writer)
and that no scratch file is left beside the report. Every path lives under
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
from tools import ds_parity_run as dpr  # noqa: E402

_REPORT = {
    "repo_engine_version": "9.9.9",
    "live_engine_version": "9.9.9",
    "fixtures": 2,
    "counts": {"PARITY": 1, "SKEW": 1},
    "results": [
        {"id": "fx-parity", "route": "/dps", "verdict": "PARITY"},
        {"id": "fx-skew", "route": "/rank", "verdict": "SKEW",
         "detail": "synthetic " + chr(0xE9)},
    ],
}


@pytest.fixture
def fixtures_file(tmp_path):
    fx = tmp_path / "fixtures.jsonl"
    fx.write_bytes(
        b'{"id": "fx-parity", "route": "/dps", "body": {}}\n'
        b'{"id": "fx-skew", "route": "/rank", "body": {}}\n')
    return fx


@pytest.fixture
def synthetic_run(monkeypatch):
    monkeypatch.setattr(dpr, "run",
                        lambda fixtures: json.loads(json.dumps(_REPORT)))


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


def test_report_write_routes_through_polled_json(tmp_path, fixtures_file,
                                                 synthetic_run, spy):
    out = tmp_path / "sub" / "ds_parity_report.json"

    assert dpr.main(["--report", str(out),
                     "--fixtures", str(fixtures_file)]) == 0

    expected = json.dumps(_REPORT, indent=2).encode("utf-8")
    assert [p for p, _ in spy] == [out]
    on_disk = out.read_bytes()
    assert on_disk == spy[0][1] == expected
    assert b"\r" not in on_disk
    assert _scratch(out.parent) == []


def test_failed_swap_keeps_the_prior_report_and_leaves_no_scratch(
        tmp_path, fixtures_file, synthetic_run, monkeypatch):
    out = tmp_path / "ds_parity_report.json"
    before = b'{"prior": true}'
    out.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        dpr.main(["--report", str(out), "--fixtures", str(fixtures_file)])

    assert out.read_bytes() == before
    assert _scratch(out.parent) == []

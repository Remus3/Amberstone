"""RM-258 residual: the DS cross-eval data writers go through core.polled_json.

`main()` in tools/ds_cross_eval/probe_champion.py and the batch loop in
tools/ds_cross_eval/run_all.py wrote each per-champion record
(`<out>/data/<canon>.json`, default ops/audit/ds_cross_eval/data/, TRACKED) by
building a destination-derived `<canon>.tmp`, writing it with Path.write_text
and swapping it in with a bare Path.replace: no fsync, no WinError 5 retry, one
scratch name for every concurrent run, and a failed rename left the scratch
file beside the record.

Both now call probe_champion._write_probe, which hands the same
`json.dumps(data, indent=2)` text (ASCII-escaped, no trailing newline) to
core.polled_json.atomic_write_text. Each test spies on that writer and checks
the exact on-disk bytes and that no scratch file is left. The engine probe is
monkeypatched to a synthetic record; every path lives under tmp_path.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from core import polled_json
from tools.ds_cross_eval import probe_champion as pc
from tools.ds_cross_eval import run_all

# A non-ASCII value proves the ASCII escaping of the old json.dumps call holds.
_DATA = {"champion": "Annie", "level": 11, "note": "caf" + chr(0xE9),
         "comp_grid": [{"a": 1}, {"b": 2}]}


def _expected(data: dict) -> bytes:
    return json.dumps(data, indent=2).encode("ascii")


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


def test_write_probe_routes_through_polled_json(tmp_path, spy):
    fp = tmp_path / "data" / "Annie.json"
    fp.parent.mkdir()

    pc._write_probe(fp, _DATA)

    assert [p for p, _ in spy] == [fp]
    on_disk = fp.read_bytes()
    assert on_disk == _expected(_DATA)
    assert b"\r" not in on_disk
    assert _scratch(fp.parent) == []


def test_write_probe_replaces_a_prior_record(tmp_path, spy):
    fp = tmp_path / "Annie.json"
    fp.write_bytes(b'{"old": true}')

    pc._write_probe(fp, _DATA)

    assert fp.read_bytes() == _expected(_DATA)
    assert _scratch(tmp_path) == []


def test_failed_swap_keeps_the_prior_record_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    fp = tmp_path / "Annie.json"
    fp.write_bytes(b'{"old": true}')

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        pc._write_probe(fp, _DATA)

    assert fp.read_bytes() == b'{"old": true}'
    assert _scratch(tmp_path) == []


def test_probe_champion_main_writes_through_the_helper(tmp_path, spy,
                                                       monkeypatch):
    monkeypatch.setattr(pc, "probe", lambda ch: dict(_DATA))
    monkeypatch.setattr(sys, "argv", ["probe_champion.py", "Annie",
                                      "--out", str(tmp_path)])

    assert pc.main() == 0

    fp = tmp_path / "data" / "Annie.json"
    assert [p for p, _ in spy] == [fp]
    assert fp.read_bytes() == _expected(_DATA)
    assert _scratch(fp.parent) == []


def test_run_all_main_writes_each_record_through_the_helper(tmp_path, spy,
                                                            monkeypatch):
    def _probe(ch):
        if ch == "Broken":
            raise ValueError("no such champion")
        return dict(_DATA, champion=ch)

    monkeypatch.setattr(run_all, "roster", lambda: ["Ahri", "Broken", "Annie"])
    monkeypatch.setattr(run_all.P, "probe", _probe)

    assert run_all.main(outdir=tmp_path / "data") == 1

    outdir = tmp_path / "data"
    assert [p for p, _ in spy] == [outdir / "Ahri.json", outdir / "Annie.json"]
    assert (outdir / "Ahri.json").read_bytes() == _expected(
        dict(_DATA, champion="Ahri"))
    assert sorted(p.name for p in outdir.iterdir()) == ["Ahri.json",
                                                         "Annie.json"]

"""RM-258 residual: the tft_cv_accuracy report write goes through core.polled_json.

`_write_json` in tools/tft_cv_accuracy.py (the `--json-out` report) hand-rolled
a destination-derived `<file>.tmp`, wrote it with Path.write_text (CRLF on
Windows) and swapped it in with a bare Path.replace: no fsync, no WinError 5
retry, a scratch name shared by every concurrent run, and a failed rename left
the scratch file beside the report.

Each test spies on `core.polled_json.atomic_write_text`, then checks the exact
on-disk bytes (the report serialized with indent=1, ASCII-escaped, one
trailing LF, no CR) and that no scratch file is left beside the report. The
CLI case drives `main()` through `--predictions` and `--json-out` on a tiny
labelled set in tmp_path (no frames, no extractor, no corpus). Every path
lives under tmp_path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import tools.tft_cv_accuracy as acc
from core import polled_json

_DOC = {
    "schema": acc.REPORT_SCHEMA,
    "match_id": "synthetic-rm258",
    "fields": {"gold": {"correct": 1, "total": 2}},
    "note": "synthetic " + chr(0xE9),
}


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


def test_report_write_routes_through_polled_json(tmp_path, spy):
    out = tmp_path / "sub" / "report.json"

    acc._write_json(out, _DOC)

    expected = json.dumps(_DOC, indent=1, sort_keys=False) + "\n"
    assert [p for p, _ in spy] == [out]
    on_disk = out.read_bytes()
    assert on_disk == spy[0][1].encode("utf-8") == expected.encode("utf-8")
    assert b"\r" not in on_disk
    assert _scratch(out.parent) == []


def test_cli_json_out_routes_through_polled_json(tmp_path, spy):
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({
        "schema": acc.SCHEMA, "match": "synthetic-rm258",
        "frames": [{"frame": "game_0001.jpg", "labels": {"gold": 12}}],
    }), encoding="utf-8")
    preds = tmp_path / "preds.json"
    preds.write_text(json.dumps({"game_0001.jpg": {"gold": 12}}), encoding="utf-8")
    out = tmp_path / "report.json"

    rc = acc.main(["--corpus", str(tmp_path / "no-such-corpus"),
                   "--labels", str(labels), "--predictions", str(preds),
                   "--json-out", str(out), "--match-id", "synthetic-rm258"])

    assert rc == 0
    assert [p for p, _ in spy] == [out]
    on_disk = out.read_bytes()
    assert b"\r" not in on_disk and on_disk.endswith(b"}\n")
    assert json.loads(on_disk)["schema"] == acc.REPORT_SCHEMA
    assert _scratch(tmp_path) == []


def test_failed_swap_keeps_the_prior_report_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    out = tmp_path / "report.json"
    before = b'{"prior": true}\n'
    out.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        acc._write_json(out, _DOC)

    assert out.read_bytes() == before
    assert _scratch(out.parent) == []

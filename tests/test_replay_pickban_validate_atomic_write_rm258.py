"""RM-258 residual: the replay_pickban_validate gate artifact goes through core.polled_json.

`_write_report()` in tools/replay_pickban_validate.py (the `--out` gate
artifact, default ops/runtime/pickban_validation.json) hand-rolled a
destination-derived `<out>.tmp`, wrote it with Path.write_text (CRLF on
Windows) and swapped it in with a bare os.replace: no fsync, no WinError 5
retry, a scratch name shared by every concurrent run, and a failed rename
left the scratch file beside the artifact.

Each test calls `_write_report()` on a small synthetic report in tmp_path,
spies on `core.polled_json.atomic_write_bytes`, then checks the exact on-disk
bytes (indent=2, ASCII, no trailing newline, no CR) and that no scratch file
is left beside the artifact. The last test runs the tool as a SCRIPT (so
sys.path[0] is tools/, not the repo root) to pin that the lazy core import
still resolves. Every path lives under tmp_path; the rewind DB and the
shipped pickban targets are never read.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from core import polled_json
from tools import replay_pickban_validate as pv

_REPORT = {
    "generated_at": "2026-01-01T00:00:00+00:00",
    "verdict": "no_signal",
    "buckets": {"gold": {"n_decisive": 2, "agreement": 0.5}},
    "note": "caf" + chr(0xE9),
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


def test_write_report_routes_through_polled_json(tmp_path, spy):
    out = tmp_path / "sub" / "pickban_validation.json"

    pv._write_report(_REPORT, out)

    expected = json.dumps(_REPORT, indent=2, ensure_ascii=True).encode("ascii")
    assert [p for p, _ in spy] == [out]
    on_disk = out.read_bytes()
    assert on_disk == spy[0][1] == expected
    assert b"\r" not in on_disk
    assert json.loads(on_disk) == _REPORT
    assert _scratch(out.parent) == []


def test_write_report_replaces_a_prior_artifact(tmp_path, spy):
    out = tmp_path / "pickban_validation.json"
    out.write_bytes(b'{"prior": true}')

    pv._write_report(_REPORT, out)

    assert json.loads(out.read_bytes()) == _REPORT
    assert _scratch(tmp_path) == []


def test_failed_swap_keeps_the_prior_artifact_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    out = tmp_path / "pickban_validation.json"
    before = b'{"prior": true}'
    out.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        pv._write_report(_REPORT, out)

    assert out.read_bytes() == before
    assert _scratch(tmp_path) == []


def test_script_run_writes_the_artifact(tmp_path):
    db = tmp_path / "rewind_history.db"
    sqlite3.connect(db).close()
    targets = tmp_path / "pickban_targets.json"
    targets.write_bytes(json.dumps({"targets": {
        "Garen": {"counters": [{"champion": "Vex"}], "good_against": []},
    }}).encode("ascii"))
    out = tmp_path / "out" / "pickban_validation.json"
    script = Path(pv.__file__).resolve()
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    proc = subprocess.run(
        [sys.executable, str(script), "--db", str(db), "--targets",
         str(targets), "--out", str(out)],
        cwd=str(tmp_path), env=env, capture_output=True, text=True,
        timeout=120, **kwargs)

    assert proc.returncode == 0, proc.stderr
    on_disk = out.read_bytes()
    assert b"\r" not in on_disk
    assert isinstance(json.loads(on_disk), dict)
    assert _scratch(out.parent) == []

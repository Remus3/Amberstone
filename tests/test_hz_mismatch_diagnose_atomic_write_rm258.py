"""RM-258 residual: the hz_mismatch_diagnose report goes through core.polled_json.

`write_markdown()` in tools/hz_mismatch_diagnose.py (the `--md-path` markdown
report, default ops/audit/HZ_MISMATCH_DIAGNOSE.md, TRACKED) hand-rolled a
destination-derived `<md>.tmp`, wrote it with Path.write_bytes and swapped it
in with a bare Path.replace: no fsync, no WinError 5 retry and one scratch name
shared by every concurrent run.

Each test diagnoses one synthetic record in tmp_path, spies on
`core.polled_json.atomic_write_bytes`, then checks the exact on-disk bytes
(UTF-8, LF only) and that no scratch file is left beside the report. The last
test runs the tool as the bare `python tools/hz_mismatch_diagnose.py` CLI
(only tools/ on sys.path), because the module may carry no top-level core
import and the lazy one has to resolve there too.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from core import polled_json
from tools import hz_mismatch_diagnose as diag

_TOOL = Path(diag.__file__).resolve()


def _report() -> dict:
    # A covered back_off precompute against a Haiku "hold" native: one
    # genuine-mismatch class (same shape as test_hz_mismatch_diagnose).
    rec = {"mode": "aram", "my_champion": "Annie", "enemy": "Caitlyn",
           "covered": True,
           "choices": [{"key": "A", "label": "Back off Caitlyn",
                        "expected_outcome": "net swing -0.10; you remove 30% "
                                            "of Caitlyn, they remove 42% of "
                                            "you"}],
           "native_action": "hold and farm", "native_choices": []}
    report = diag.diagnose([rec], now="2026-06-21T00:00:00Z")
    assert report["genuine_mismatches"] == 1
    return report


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


def test_write_markdown_routes_through_polled_json(tmp_path, spy):
    report = _report()
    out = tmp_path / "sub" / "HZ_MISMATCH_DIAGNOSE.md"

    diag.write_markdown(report, out)

    expected = diag.render_markdown(report).encode("utf-8")
    assert [p for p, _ in spy] == [out]
    on_disk = out.read_bytes()
    assert on_disk == spy[0][1] == expected
    assert b"\r" not in on_disk
    assert _scratch(out.parent) == []


def test_write_markdown_replaces_a_prior_report(tmp_path, spy):
    report = _report()
    out = tmp_path / "HZ_MISMATCH_DIAGNOSE.md"
    out.write_bytes(b"# prior\n")

    diag.write_markdown(report, out)

    assert out.read_bytes() == diag.render_markdown(report).encode("utf-8")
    assert _scratch(tmp_path) == []


def test_failed_swap_keeps_the_prior_report_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    out = tmp_path / "HZ_MISMATCH_DIAGNOSE.md"
    before = b"# prior\n"
    out.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        diag.write_markdown(_report(), out)

    assert out.read_bytes() == before
    assert _scratch(tmp_path) == []


def test_bare_cli_writes_the_report(tmp_path):
    out = tmp_path / "out" / "HZ_MISMATCH_DIAGNOSE.md"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [sys.executable, str(_TOOL), "--choice-path",
         str(tmp_path / "missing.jsonl"), "--md-path", str(out)],
        cwd=str(tmp_path), env=env, capture_output=True, text=True,
        timeout=120, creationflags=flags)

    assert proc.returncode == 0, proc.stderr
    body = out.read_bytes()
    assert body.startswith(b"#")
    assert b"\r" not in body
    assert _scratch(out.parent) == []

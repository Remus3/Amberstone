"""RM-258 residual: the agent6 report sanitizer writes through core.polled_json.

`main(["--apply"])` in tools/sanitize_agent6_reports.py rewrote each dirty
report through a fixed `<name>.<suffix>.tmp` scratch file plus a bare
Path.replace: no fsync before the rename, no WinError 5 retry, and the scratch
left behind when the rename failed.

Each test points the tool's `REPORTS_DIR` at tmp_path and spies on
`core.polled_json.atomic_write_bytes`, so the tracked reports directory is
never read or written.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from core import polled_json
from tools import sanitize_agent6_reports as tool

_DIRTY = ("# RC Weekly Health " + chr(0x2014) + " 2026-08-25\r\n"
          "\r\n"
          "| match_history.db | 0.00 B | " + chr(0x2713) + " |\r\n")
_CLEAN = (b"# RC Weekly Health  -  2026-08-25\r\n"
          b"\r\n"
          b"| match_history.db | 0.00 B | OK |\r\n")


@pytest.fixture
def reports(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "reports"
    d.mkdir()
    (d / "dirty.md").write_bytes(_DIRTY.encode("utf-8"))
    (d / "clean.md").write_bytes(b"# ok\r\n")
    monkeypatch.setattr(tool, "REPORTS_DIR", d)
    return d


@pytest.fixture
def spy(monkeypatch):
    calls: list[tuple[Path, bytes]] = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def test_apply_writes_through_polled_json(reports, spy):
    assert tool.main(["--apply"]) == 0
    dirty = reports / "dirty.md"
    assert spy == [(dirty, _CLEAN)]
    # CRLF survives byte for byte; only the non-ASCII codepoints moved.
    assert dirty.read_bytes() == _CLEAN
    assert (reports / "clean.md").read_bytes() == b"# ok\r\n"
    assert sorted(p.name for p in reports.iterdir()) == ["clean.md", "dirty.md"]


def test_check_and_report_modes_write_nothing(reports, spy):
    assert tool.main(["--check"]) == 1
    assert tool.main([]) == 0
    assert spy == []
    assert (reports / "dirty.md").read_bytes() == _DIRTY.encode("utf-8")


def test_refused_swap_keeps_the_prior_file_and_leaves_no_scratch(
        reports, monkeypatch):
    prior = (reports / "dirty.md").read_bytes()
    fired = []

    def _refuse(a, b):
        fired.append((a, b))
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", _refuse)
    with pytest.raises(PermissionError):
        tool.main(["--apply"])
    assert len(fired) == 1
    assert (reports / "dirty.md").read_bytes() == prior
    assert sorted(p.name for p in reports.iterdir()) == ["clean.md", "dirty.md"]


def test_rerun_is_a_no_op(reports, spy):
    tool.main(["--apply"])
    assert tool.main(["--apply"]) == 0
    assert len(spy) == 1


def test_script_mode_resolves_core_from_any_cwd(tmp_path):
    # docs-guards runs `python tools/sanitize_agent6_reports.py --check`; in
    # script mode sys.path[0] is tools/, so the core import must not depend
    # on the cwd or PYTHONPATH.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, tool.__file__, "--check"],
        capture_output=True, text=True, cwd=str(tmp_path), env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_tool_carries_no_hand_rolled_rename():
    text = Path(tool.__file__).read_text(encoding="utf-8")
    assert "os.replace" not in text
    assert ".tmp" not in text
    assert "tmp.replace(" not in text
    assert "polled_json.atomic_write_bytes(" in text

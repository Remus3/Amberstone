"""RM-258 residual: tools/strip_u2500.py writes through core.polled_json.

`_process_file()` rewrote each granted file through a fixed
`<name>.u2500tmp` scratch file plus a bare os.replace: no fsync before the
rename, no WinError 5 retry, and the scratch left behind beside the source
file when the rename failed. It now hands the same rewritten bytes to
`core.polled_json.atomic_write_bytes`.

Every test points the tool's ROOT at tmp_path and spies on
`core.polled_json.atomic_write_bytes`; no tracked file is read or written.
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core import polled_json
from tools import strip_u2500 as tool

_ROOT = Path(__file__).resolve().parents[1]

# Two U+2500 runs, CRLF kept as authored, plus a non-ASCII neighbour
# (U+00E9) that must survive untouched.
_SRC = (b"# " + tool.U2500_BYTES * 3 + b" rule\r\n"
        + b"caf\xc3\xa9 " + tool.U2500_BYTES + b"\n")
_OUT = b"# --- rule\r\ncaf\xc3\xa9 -\n"


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, "ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def spy(monkeypatch):
    calls: list[tuple[Path, bytes]] = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def _run(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["strip_u2500.py", *argv])
    return tool.main()


def test_apply_goes_through_polled_json(root, spy, monkeypatch):
    target = root / "doc.py"
    target.write_bytes(_SRC)
    assert _run(monkeypatch, "--allow-frozen", "doc.py") == 0
    assert spy == [(target, _OUT)]
    assert target.read_bytes() == _OUT
    assert sorted(p.name for p in root.iterdir()) == ["doc.py"]


def test_dry_run_writes_nothing(root, spy, monkeypatch):
    target = root / "doc.py"
    target.write_bytes(_SRC)
    assert _run(monkeypatch, "--allow-frozen", "doc.py", "--dry-run") == 0
    assert spy == []
    assert target.read_bytes() == _SRC


def test_hard_skip_is_never_written(root, spy, monkeypatch):
    target = root / "doc.py"
    target.write_bytes(_SRC)
    monkeypatch.setattr(tool, "_HARD_SKIP_FROZEN", frozenset({"doc.py"}))
    assert _run(monkeypatch, "--allow-frozen", "doc.py") == 1
    assert spy == []
    assert target.read_bytes() == _SRC


def test_refused_swap_keeps_the_source_and_leaves_no_scratch(
        root, monkeypatch):
    target = root / "doc.py"
    target.write_bytes(_SRC)
    fired = []

    def _refuse(a, b):
        fired.append((a, b))
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", _refuse)
    with pytest.raises(PermissionError):
        _run(monkeypatch, "--allow-frozen", "doc.py")
    assert len(fired) == 1
    assert target.read_bytes() == _SRC
    assert sorted(p.name for p in root.iterdir()) == ["doc.py"]


def test_writer_source_has_no_hand_rolled_swap():
    src = inspect.getsource(tool._process_file)
    assert "polled_json.atomic_write_bytes" in src
    assert "u2500tmp" not in src
    assert "os.replace" not in src


def test_script_mode_resolves_core_from_a_foreign_cwd(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "tools" / "strip_u2500.py"),
         "--no-such-option"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    # Usage error (exit 2) means the module imported, core included, and
    # argparse ran; no file was touched.
    assert proc.returncode == 2, proc.stderr
    assert "ModuleNotFoundError" not in proc.stderr

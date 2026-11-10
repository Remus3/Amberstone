"""RM-258 residual: the CLI re-pin tool's evidence writer uses core.polled_json.

`_write_ascii` in tools/repin_subagent_cli.py wrote each evidence file
(codeword.txt, <control>.stderr.txt, summary.json) through a fixed
`<name>.tmp` scratch file plus a bare Path.replace: no fsync before the
rename, no WinError 5 retry, and the scratch left behind when the rename
failed. The PINNED_CLI write (`write_pin`) is not touched here: its rename
is the injected `replace=` seam the RM-795 tests drive.

Every test writes under tmp_path and spies on
`core.polled_json.atomic_write_bytes`; nothing spawns and no tracked file is
read or written.
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core import polled_json
from tools import repin_subagent_cli as repin

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def spy(monkeypatch):
    calls: list[tuple[Path, bytes]] = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def test_write_ascii_goes_through_polled_json(tmp_path, spy):
    target = tmp_path / "summary.json"
    repin._write_ascii(target, '{"a": 1}\n')
    assert spy == [(target, b'{"a": 1}\n')]
    assert target.read_bytes() == b'{"a": 1}\n'
    assert sorted(p.name for p in tmp_path.iterdir()) == ["summary.json"]


def test_write_ascii_keeps_its_lf_and_ascii_normalisation(tmp_path, spy):
    # Same bytes the old tmp.write_bytes produced: CRLF folded to LF, every
    # non-ASCII character replaced by "?".
    target = tmp_path / "canary.stderr.txt"
    repin._write_ascii(target, "line one\r\ncaf\u00e9\n")
    assert target.read_bytes() == b"line one\ncaf?\n"
    assert spy == [(target, b"line one\ncaf?\n")]


def test_refused_swap_keeps_the_prior_file_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    target = tmp_path / "codeword.txt"
    target.write_bytes(b"OLD\n")
    fired = []

    def _refuse(a, b):
        fired.append((a, b))
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", _refuse)
    with pytest.raises(PermissionError):
        repin._write_ascii(target, "NEW\n")
    assert len(fired) == 1
    assert target.read_bytes() == b"OLD\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["codeword.txt"]


def test_writer_source_has_no_hand_rolled_swap():
    src = inspect.getsource(repin._write_ascii)
    assert "polled_json.atomic_write_bytes" in src
    assert ".tmp" not in src
    assert "replace(" not in src.replace('.replace("\\r\\n", "\\n")', "")


def test_script_mode_resolves_core_from_a_foreign_cwd(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "tools" / "repin_subagent_cli.py"),
         "--no-such-option"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
        check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    # Usage error (exit 2) means the module imported, core included, and
    # argparse ran; nothing spawned.
    assert proc.returncode == 2, proc.stderr
    assert "ModuleNotFoundError" not in proc.stderr

"""RM-258 residual: tools/ascii_escape_py.py --apply writes through core.polled_json.

`main(["--apply", ...])` rewrote each tracked .py through a fixed
`<name>.ascii_tmp` scratch file plus a bare Path.replace: no fsync before the
rename, no WinError 5 retry, and the scratch left behind beside the source
file when the rename failed. It now hands the same ASCII bytes (the file's own
CRLF / LF newlines kept) to `core.polled_json.atomic_write_bytes`.

Every test writes under tmp_path (an absolute path argument wins over the
tool's REPO join) and spies on `core.polled_json.atomic_write_bytes`; no
tracked file is read or written.
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core import polled_json
from tools import ascii_escape_py as tool

_ROOT = Path(__file__).resolve().parents[1]

# A comment arrow (transliterated) and a string-literal e-acute (escaped).
_SRC = '# a \u2192 b\nX = "caf\u00e9"\n'
_OUT = b'# a -> b\nX = "caf\\xe9"\n'


@pytest.fixture
def spy(monkeypatch):
    calls: list[tuple[Path, bytes]] = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def test_apply_goes_through_polled_json(tmp_path, spy):
    target = tmp_path / "mod.py"
    target.write_bytes(_SRC.encode("utf-8"))
    assert tool.main(["--apply", str(target)]) == 0
    assert spy == [(target, _OUT)]
    assert target.read_bytes() == _OUT
    assert sorted(p.name for p in tmp_path.iterdir()) == ["mod.py"]


def test_apply_keeps_the_files_own_crlf(tmp_path, spy):
    target = tmp_path / "crlf.py"
    target.write_bytes(_SRC.replace("\n", "\r\n").encode("utf-8"))
    assert tool.main(["--apply", str(target)]) == 0
    assert target.read_bytes() == _OUT.replace(b"\n", b"\r\n")
    assert len(spy) == 1


def test_dry_run_writes_nothing(tmp_path, spy):
    target = tmp_path / "mod.py"
    target.write_bytes(_SRC.encode("utf-8"))
    assert tool.main([str(target)]) == 0
    assert spy == []
    assert target.read_bytes() == _SRC.encode("utf-8")


def test_refused_swap_keeps_the_source_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    target = tmp_path / "mod.py"
    target.write_bytes(_SRC.encode("utf-8"))
    fired = []

    def _refuse(a, b):
        fired.append((a, b))
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", _refuse)
    with pytest.raises(PermissionError):
        tool.main(["--apply", str(target)])
    assert len(fired) == 1
    assert target.read_bytes() == _SRC.encode("utf-8")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["mod.py"]


def test_main_source_has_no_hand_rolled_swap():
    src = inspect.getsource(tool.main)
    assert "polled_json.atomic_write_bytes" in src
    assert "ascii_tmp" not in src
    assert ".replace(path)" not in src


def test_script_mode_resolves_core_from_a_foreign_cwd(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "tools" / "ascii_escape_py.py"),
         "--no-such-option"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
        check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    # Usage error (exit 2) means the module imported, core included, and
    # argparse ran; no file was touched.
    assert proc.returncode == 2, proc.stderr
    assert "ModuleNotFoundError" not in proc.stderr

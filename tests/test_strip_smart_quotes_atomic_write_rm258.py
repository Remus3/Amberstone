"""RM-258 residual: tools/strip_smart_quotes.py --apply writes through core.polled_json.

`main()` with `--apply` rewrote each tracked file through a fixed
`<name>.sqtmp` scratch file plus a bare os.replace: no fsync before the
rename, no WinError 5 retry, and the scratch left behind beside the source
file when the rename failed. It now hands the same rewritten bytes to
`core.polled_json.atomic_write_bytes`.

Every test points the tool's ROOT and tracked-file list at tmp_path and spies
on `core.polled_json.atomic_write_bytes`; no tracked file is read or written.
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core import polled_json
from tools import strip_smart_quotes as tool

_ROOT = Path(__file__).resolve().parents[1]

# Smart quotes, an em-dash, an ellipsis and an NBSP, CRLF kept as authored,
# plus one U+201D in mojibake context (next to U+20AC) that must survive.
_MOJI = tool.RDQUO + chr(0x20AC)
_SRC = (tool.LDQUO + "a" + tool.RDQUO + " " + tool.LSQUO + "b" + tool.RSQUO
        + "\r\n"
        + "c " + tool.EMDASH + " d" + tool.HELLIP + tool.NBSP + "e\n"
        + "f " + _MOJI + " g\n").encode("utf-8")
# The dash rule maps the bare glyph to " - ", so the authored spaces stay.
_OUT = ("\"a\" 'b'\r\nc  -  d... e\nf " + _MOJI + " g\n").encode("utf-8")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    files: list[Path] = []
    monkeypatch.setattr(tool, "ROOT", tmp_path)
    monkeypatch.setattr(tool, "_tracked_files", lambda: list(files))
    return tmp_path, files


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
    monkeypatch.setattr(sys, "argv", ["strip_smart_quotes.py", *argv])
    return tool.main()


def test_apply_goes_through_polled_json(tree, spy, monkeypatch):
    root, files = tree
    target = root / "doc.md"
    target.write_bytes(_SRC)
    files.append(target)
    assert _run(monkeypatch, "--apply") == 0
    assert spy == [(target, _OUT)]
    assert target.read_bytes() == _OUT
    assert sorted(p.name for p in root.iterdir()) == ["doc.md"]


def test_dry_run_writes_nothing(tree, spy, monkeypatch):
    root, files = tree
    target = root / "doc.md"
    target.write_bytes(_SRC)
    files.append(target)
    assert _run(monkeypatch) == 0
    assert spy == []
    assert target.read_bytes() == _SRC


def test_frozen_file_is_not_written_without_a_grant(tree, spy, monkeypatch):
    root, files = tree
    target = root / "main.py"
    target.write_bytes(_SRC)
    files.append(target)
    assert _run(monkeypatch, "--apply") == 0
    assert spy == []
    assert target.read_bytes() == _SRC


def test_refused_swap_keeps_the_source_and_leaves_no_scratch(
        tree, monkeypatch):
    root, files = tree
    target = root / "doc.md"
    target.write_bytes(_SRC)
    files.append(target)
    fired = []

    def _refuse(a, b):
        fired.append((a, b))
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", _refuse)
    with pytest.raises(PermissionError):
        _run(monkeypatch, "--apply")
    assert len(fired) == 1
    assert target.read_bytes() == _SRC
    assert sorted(p.name for p in root.iterdir()) == ["doc.md"]


def test_main_source_has_no_hand_rolled_swap():
    src = inspect.getsource(tool.main)
    assert "polled_json.atomic_write_bytes" in src
    assert "sqtmp" not in src
    assert "os.replace" not in src


def test_script_mode_resolves_core_from_a_foreign_cwd(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "tools" / "strip_smart_quotes.py"),
         "--no-such-option"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
        check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    # Usage error (exit 2) means the module imported, core included, and
    # argparse ran; no file was touched.
    assert proc.returncode == 2, proc.stderr
    assert "ModuleNotFoundError" not in proc.stderr

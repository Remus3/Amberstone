"""RM-258 residual: tools/web_ascii_sweep.py writes through core.polled_json.

`write_source()` rewrote each swept web/ file through a fixed
`<name>.rm125tmp` scratch file plus a bare Path.replace: no fsync before the
rename, no WinError 5 retry, and the scratch left behind beside the source
file when the rename failed. It now hands the same UTF-8 bytes to
`core.polled_json.atomic_write_bytes`.

Every test sweeps a tree under tmp_path (`--root`) and spies on
`core.polled_json.atomic_write_bytes`; no tracked file is read or written.
Glyph literals are spelled \\uXXXX so this file stays 7-bit ASCII itself.
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core import polled_json
from tools import web_ascii_sweep as tool

_ROOT = Path(__file__).resolve().parents[1]

# A comment-span U+2500 run (swept), CRLF kept as authored, and a LIVE-span
# U+2500 inside a string literal (left alone by design).
_SRC = '// \u2500\u2500 rule\r\nconst s = "\u2500";\r\n'.encode()
_OUT = '// -- rule\r\nconst s = "\u2500";\r\n'.encode()


@pytest.fixture
def web(tmp_path):
    root = tmp_path / "web"
    root.mkdir()
    return root


@pytest.fixture
def spy(monkeypatch):
    calls: list[tuple[Path, bytes]] = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def test_apply_goes_through_polled_json(web, spy):
    target = web / "a.js"
    target.write_bytes(_SRC)
    assert tool.main(["--apply", "--root", str(web)]) == 0
    assert spy == [(target, _OUT)]
    assert target.read_bytes() == _OUT
    assert sorted(p.name for p in web.iterdir()) == ["a.js"]


def test_dry_run_writes_nothing(web, spy):
    target = web / "a.js"
    target.write_bytes(_SRC)
    assert tool.main(["--dry-run", "--root", str(web)]) == 0
    assert spy == []
    assert target.read_bytes() == _SRC


def test_unmapped_comment_glyph_refuses_every_write(web, spy):
    swept = web / "a.js"
    swept.write_bytes(_SRC)
    # U+E000 (private use) is absent from REPLACEMENTS.
    bad = web / "b.js"
    bad_src = "// \ue000\n".encode()
    bad.write_bytes(bad_src)
    assert "\ue000" not in tool.REPLACEMENTS
    assert tool.main(["--apply", "--root", str(web)]) == 2
    assert spy == []
    assert swept.read_bytes() == _SRC
    assert bad.read_bytes() == bad_src


def test_refused_swap_keeps_the_source_and_leaves_no_scratch(web, monkeypatch):
    target = web / "a.js"
    target.write_bytes(_SRC)
    fired = []

    def _refuse(a, b):
        fired.append((a, b))
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", _refuse)
    with pytest.raises(PermissionError):
        tool.main(["--apply", "--root", str(web)])
    assert len(fired) == 1
    assert target.read_bytes() == _SRC
    assert sorted(p.name for p in web.iterdir()) == ["a.js"]


def test_writer_source_has_no_hand_rolled_swap():
    src = inspect.getsource(tool.write_source)
    assert "polled_json.atomic_write_bytes" in src
    assert "rm125tmp" not in src
    assert ".replace(" not in src


def test_script_mode_resolves_core_from_a_foreign_cwd(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "tools" / "web_ascii_sweep.py"),
         "--no-such-option"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    # Usage error (exit 2) means the module imported, core included, and
    # argparse ran; no file was touched.
    assert proc.returncode == 2, proc.stderr
    assert "ModuleNotFoundError" not in proc.stderr

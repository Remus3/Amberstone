"""RM-258 residual: the notices write goes through core.polled_json.

`_write_atomic` in tools/build_third_party_notices.py wrote `--out` through
a `.<name>.<pid>.tmp` scratch and a bare `Path.replace`: no fsync, no
WinError 5 retry, and a refused rename left the scratch file beside the
notices. main() now hands the same ASCII bytes to
`core.polled_json.atomic_write_bytes`.

The inputs are missing on purpose (the fail-closed path): build() still
renders an INCOMPLETE notices file, main() writes it unless --check, and the
exit code is 1. Every path lives under tmp_path.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import polled_json  # noqa: E402
from tools import build_third_party_notices as tpn  # noqa: E402

_TOOL = _ROOT / "tools" / "build_third_party_notices.py"


def _argv(tmp_path: Path, out: Path, *extra: str) -> list[str]:
    return ["--requirements", str(tmp_path / "nope.txt"),
            "--node-root", str(tmp_path / "shell"), "--out", str(out), *extra]


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


def test_notices_write_routes_through_polled_json(tmp_path, spy):
    out = tmp_path / "dist" / "THIRD_PARTY_NOTICES.txt"

    assert tpn.main(_argv(tmp_path, out)) == 1

    assert [p for p, _ in spy] == [out]
    on_disk = out.read_bytes()
    assert on_disk == spy[0][1]
    assert b"NOT AUDITED" in on_disk
    assert b"\r" not in on_disk and all(c < 128 for c in on_disk)
    assert _scratch(out.parent) == []


def test_check_mode_writes_nothing(tmp_path, spy):
    out = tmp_path / "dist" / "never.txt"

    assert tpn.main(_argv(tmp_path, out, "--check")) == 1

    assert spy == []
    assert not out.exists()


def test_failed_swap_keeps_the_prior_notices_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    out = tmp_path / "THIRD_PARTY_NOTICES.txt"
    before = b"prior notices\n"
    out.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        tpn.main(_argv(tmp_path, out))

    assert out.read_bytes() == before
    assert _scratch(tmp_path) == []


def test_tool_has_no_hand_rolled_swap():
    tree = ast.parse(_TOOL.read_text(encoding="utf-8"))
    funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_write_atomic" not in funcs
    renames = [n.lineno for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in ("replace", "rename")
               and not (n.args and isinstance(n.args[0], ast.Constant)
                        and isinstance(n.args[0].value, str))]
    assert renames == [], renames
    assert "polled_json.atomic_write_bytes" in ast.get_source_segment(
        _TOOL.read_text(encoding="utf-8"),
        next(n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == "main"))


def test_script_mode_writes_through_core_from_a_foreign_cwd(tmp_path):
    out = tmp_path / "out" / "n.txt"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, str(_TOOL), *_argv(tmp_path, out)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
        check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert "ModuleNotFoundError" not in proc.stderr, proc.stderr
    assert proc.returncode == 1, proc.stderr
    assert out.is_file()
    assert _scratch(out.parent) == []

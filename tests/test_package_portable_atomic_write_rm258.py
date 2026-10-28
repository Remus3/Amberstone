"""RM-258 residual: tools/package_portable.py writes through core.polled_json.

The portable-archive packer (PKG-4) used to hand-roll its swap: it built the
zip in a fixed `<archive>.tmp` derived from the destination and renamed it
with a bare `Path.replace` (no fsync, no WinError 5 retry), then wrote the
`<archive>.sha256` sidecar with a plain `write_text`. Both now hand their
bytes to `core.polled_json.atomic_write_bytes` (per-writer scratch, fsync,
bounded retry, scratch removed on failure). The archive is built in memory
(the packer already read the whole archive back to hash it, so the peak is
unchanged in kind) and the digest is taken from the very bytes published.

Every path lives under tmp_path; nothing runs tools/build_portable.py.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import polled_json  # noqa: E402
from tools import package_portable as pp  # noqa: E402

_TOOL = _ROOT / "tools" / "package_portable.py"


def _staged(tmp_path: Path) -> Path:
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / pp.bp.MANIFEST_NAME).write_bytes(json.dumps({
        "build_tool": pp.bp.BUILD_TOOL, "bundle": pp.bp.BUNDLE_NAME,
        "version": "1.0.0", "source_commit": "0" * 40,
        "python": {"mode": "none"}}).encode("utf-8"))
    (staged / "main.py").write_bytes(b"print('synthetic')\n")
    return staged


@pytest.fixture
def spy(monkeypatch):
    calls = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), bytes(data)))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def _litter(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir() if p.name.endswith(".tmp"))


def _deny_every_rename(monkeypatch):
    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))


def test_archive_and_sidecar_route_through_polled_json(tmp_path, spy):
    dist = tmp_path / "dist"
    name = pp.archive_name("1.2.3")

    assert pp.package(out_dir=dist, version="1.2.3", staged_dir=_staged(tmp_path)) == 0

    archive, side = dist / name, dist / (name + ".sha256")
    assert [p for p, _ in spy] == [archive, side]
    assert archive.read_bytes() == spy[0][1]
    digest = hashlib.sha256(spy[0][1]).hexdigest()
    assert side.read_bytes() == spy[1][1] == f"{digest}  {name}\n".encode("ascii")
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    assert f"{pp.ZIP_ROOT_NAME}/main.py" in names
    assert f"{pp.ZIP_ROOT_NAME}/{pp.PACKAGE_MANIFEST}" in names
    assert _litter(dist) == []


def test_refused_archive_rename_keeps_the_prior_archive_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    staged = _staged(tmp_path)
    dist = tmp_path / "dist"
    dist.mkdir()
    archive = dist / pp.archive_name("1")
    before = b"prior archive bytes"
    archive.write_bytes(before)
    _deny_every_rename(monkeypatch)

    assert pp.package(out_dir=dist, version="1", staged_dir=staged) == 1

    assert archive.read_bytes() == before
    assert sorted(p.name for p in dist.iterdir()) == [archive.name]


def test_refused_sidecar_write_fails_the_run_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    real = polled_json.atomic_write_bytes

    def _refuse_sidecar(path, data):
        if Path(path).name.endswith(".sha256"):
            raise PermissionError(5, "Access is denied", str(path))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _refuse_sidecar)
    dist = tmp_path / "dist"

    assert pp.package(out_dir=dist, version="1", staged_dir=_staged(tmp_path)) == 1

    assert not (dist / (pp.archive_name("1") + ".sha256")).exists()
    assert _litter(dist) == []


def test_tool_has_no_hand_rolled_swap():
    src = _TOOL.read_text(encoding="utf-8")
    tree = ast.parse(src)
    renames = [n.lineno for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in ("replace", "rename")
               and not (n.args and isinstance(n.args[0], ast.Constant)
                        and isinstance(n.args[0].value, str))]
    assert renames == [], renames
    writes = [n.lineno for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr in ("write_text", "write_bytes")]
    assert writes == [], writes
    assert '".tmp"' not in src


def test_script_mode_imports_core_from_a_foreign_cwd(tmp_path):
    # Script mode puts tools/ (not the repo root) first on sys.path; the
    # packer must still resolve core/ with no PYTHONPATH from any cwd.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, str(_TOOL), "--staged", str(_staged(tmp_path)),
         "--output", str(tmp_path / "dist"), "--version", "9"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "dist" / pp.archive_name("9")).is_file()
    assert _litter(tmp_path / "dist") == []

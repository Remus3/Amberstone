"""RM-493: a .pyc write is invisible to the git freeze witness and must move
the filesystem one.

The positive control is load-bearing: the SAME write is shown to leave
`git status --porcelain` empty, so the test proves the gap it closes, not just
that a hash changes when a file does.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from tools import freeze_witness as fw


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, text=True)


def _frozen_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    (tmp_path / "mod.py").write_text("X = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "freeze")
    return tmp_path


def test_pyc_write_is_invisible_to_git_but_moves_the_filesystem_witness(tmp_path: Path):
    root = _frozen_repo(tmp_path)
    before = fw.snapshot(root)
    cache = root / "__pycache__"
    cache.mkdir()
    (cache / "mod.cpython-314.pyc").write_bytes(b"\x00bytecode")
    assert fw.git_witness(root) == "", "control: git must NOT see the .pyc"
    after = fw.snapshot(root)
    assert after["digest"] != before["digest"]
    assert fw.diff(before, after)["added"] == ["__pycache__/mod.cpython-314.pyc"]


def test_verify_cli_reports_frozen_then_drift(tmp_path: Path):
    root = _frozen_repo(tmp_path)
    snap_file = tmp_path.parent / f"{tmp_path.name}_snap.json"
    assert fw.main(["snapshot", str(root), "--out", str(snap_file)]) == 0
    assert fw.main(["verify", str(root), str(snap_file)]) == 0
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_bytes(b"1")
    assert fw.main(["verify", str(root), str(snap_file)]) == 1


def test_git_dir_is_not_part_of_the_witness(tmp_path: Path):
    root = _frozen_repo(tmp_path)
    assert not any(k.startswith(".git/") for k in fw.snapshot(root)["entries"])

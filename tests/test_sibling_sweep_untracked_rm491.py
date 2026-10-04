"""RM-491: the hand-run tree arm must see an untracked (not yet staged) file.

CLAUDE.md tells a session to run the sweep's tree arm BY HAND on new work, and
new work is untracked until `git add`. The universe was `git ls-files -z` only,
so a fresh file was outside it and a clean report proved nothing about it.
Gitignored files stay out (`--exclude-standard`): they are never pushed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from tools import sibling_name_sweep as sweep


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    (tmp_path / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt", ".gitignore")
    (tmp_path / "new_work.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("runtime\n", encoding="utf-8")
    return tmp_path


def test_untracked_file_is_in_the_tree_universe(tmp_path: Path):
    root = _repo(tmp_path)
    stats = sweep.ScanStats()
    paths = {b.path for b in sweep.iter_tree_blobs(root, stats)}
    assert "new_work.py" in paths
    assert "tracked.txt" in paths
    assert stats.untracked == 1
    assert stats.files == len(paths)


def test_gitignored_file_stays_out(tmp_path: Path):
    root = _repo(tmp_path)
    paths = {b.path for b in sweep.iter_tree_blobs(root, sweep.ScanStats())}
    assert "ignored.txt" not in paths

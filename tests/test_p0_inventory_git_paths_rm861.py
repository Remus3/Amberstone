"""RM-861 (ops/audit/p0_inventory.py site): tracked paths are read as themselves.

`main()` built its tracked set from a bare `git ls-files` split with
`.splitlines()`. With core.quotePath on (git's default) git C-quotes a
non-ASCII name (`"d\\304\\201\\303\\251.txt"`), so the walked on-disk name
never matched the set and a TRACKED file was counted as untracked/ignored and
marked `n` in the largest-files table. `.splitlines()` also splits a name on
U+2028, U+0085 and the other non-newline line breaks; `-z` has neither problem.

Every repo here is a throwaway under tmp_path with git's global config pinned
to an empty file, the system config off, `GIT_CONFIG_COUNT` cleared and
core.quotePath set ON in the repo, so no host-wide setting decides the result.
Source stays ASCII: every non-ASCII probe is built with chr().
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_P0 = _ROOT / "ops" / "audit" / "p0_inventory.py"

_NAME = "d" + chr(0x0101) + chr(0x00E9)


def _load():
    spec = importlib.util.spec_from_file_location("_rm861_p0_inventory", _P0)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def git_env(tmp_path, monkeypatch):
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="ascii")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in list(os.environ):
        if key == "GIT_CONFIG_COUNT" or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            monkeypatch.delenv(key, raising=False)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(key, raising=False)
    return dict(os.environ)


def _repo(tmp_path: Path, env: dict, tracked: list[str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args) -> None:
        subprocess.run(["git", *args], cwd=repo, capture_output=True, env=env, check=True)

    run("init", "-q", ".")
    run("config", "user.email", "rm861@test")
    run("config", "user.name", "rm861")
    run("config", "core.quotepath", "true")
    run("config", "core.autocrlf", "false")
    for rel in tracked:
        (repo / rel).write_bytes(b"x" * 8 + b"\n")
    run("add", "-A")
    run("commit", "-q", "-m", "base")
    return repo


def _inventory(tmp_path: Path, repo: Path, monkeypatch) -> tuple[str, str]:
    out = tmp_path / "out"
    out.mkdir()
    p0 = _load()
    monkeypatch.setattr(p0, "ROOT", repo)
    monkeypatch.setattr(p0, "OUT_DIR", out)
    assert p0.main() == 0
    md = (out / "P0_INVENTORY.md").read_text(encoding="utf-8")
    csv_text = (out / "p0_inventory_full.csv").read_text(encoding="utf-8")
    return md, csv_text


def test_control_ascii_tracked_files_count_as_tracked(tmp_path, git_env, monkeypatch):
    repo = _repo(tmp_path, git_env, ["a.txt", "b.txt"])
    md, _ = _inventory(tmp_path, repo, monkeypatch)
    assert "- Total: 2 files" in md
    assert "- Git-tracked: 2 files" in md
    assert "- Untracked/ignored on disk: 0 files" in md


def test_a_tracked_non_ascii_name_counts_as_tracked(tmp_path, git_env, monkeypatch):
    rel = _NAME + ".txt"
    repo = _repo(tmp_path, git_env, ["a.txt", rel])
    md, csv_text = _inventory(tmp_path, repo, monkeypatch)
    assert "- Git-tracked: 2 files" in md
    assert "- Untracked/ignored on disk: 0 files" in md
    assert "| Y | " + rel + " |" in md
    assert rel in csv_text


def test_a_name_with_a_unicode_line_separator_counts_as_tracked(tmp_path, git_env, monkeypatch):
    """U+2028 is a line break to str.splitlines(), never to `ls-files -z`."""
    rel = "x" + chr(0x2028) + "y.txt"
    try:
        repo = _repo(tmp_path, git_env, ["a.txt", rel])
    except OSError:
        pytest.skip("filesystem refuses a U+2028 file name")
    md, _ = _inventory(tmp_path, repo, monkeypatch)
    assert "- Git-tracked: 2 files" in md


def test_an_untracked_non_ascii_name_stays_untracked(tmp_path, git_env, monkeypatch):
    repo = _repo(tmp_path, git_env, ["a.txt"])
    (repo / (_NAME + ".txt")).write_bytes(b"y\n")
    md, _ = _inventory(tmp_path, repo, monkeypatch)
    assert "- Total: 2 files" in md
    assert "- Git-tracked: 1 files" in md
    assert "- Untracked/ignored on disk: 1 files" in md

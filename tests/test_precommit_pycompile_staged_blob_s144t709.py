"""S144-T-709 - the commit gate's py_compile step compiles the STAGED bytes.

scripts/precommit_pycompile.py is step 2 of .githooks/pre-commit and its docstring promises to
"py_compile every staged .py file before the commit lands". Measured 2026-11-09 it compiled the
WORKING-TREE copy instead, so:

- a broken file staged and then fixed (or deleted) in the working tree committed the broken
  bytes with "py_compile OK" (a gate escape);
- a good file staged and then broken in the working tree refused a correct commit;
- a symlink-to-regular-file type change (status T) was never listed (filter ACMR);
- a gitlink named ``*.py`` (a directory in the working tree) crashed the gate with a traceback;
- every run wrote ``__pycache__/*.pyc`` into the tree being committed;
- a git failure was an unhandled traceback, and the refusal text carried the absolute path.

Every test drives the real script in a throwaway repo (the script is copied in, so its ROOT is
that repo) and reads its exit code and output.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "precommit_pycompile.py"
_BROKEN = b"def broken(:\n"
_GOOD = b"x = 1\n"


@pytest.fixture
def env(tmp_path, monkeypatch):
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="ascii")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for key in list(os.environ):
        if key == "GIT_CONFIG_COUNT" or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            monkeypatch.delenv(key, raising=False)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "PYTHONDONTWRITEBYTECODE",
                "PYTHONPYCACHEPREFIX"):
        monkeypatch.delenv(key, raising=False)
    return dict(os.environ)


def _repo(tmp_path: Path, env: dict) -> tuple[Path, callable]:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "precommit_pycompile.py").write_bytes(_SCRIPT.read_bytes())

    def git(*args, stdin: bytes | None = None, extra: dict | None = None) -> str:
        return subprocess.run(
            ["git", *args], cwd=repo, input=stdin, capture_output=True,
            env={**env, **(extra or {})}, check=True,
        ).stdout.decode("utf-8", "replace").strip()

    git("init", "-q", ".")
    git("config", "user.email", "t709@test")
    git("config", "user.name", "t709")
    git("config", "core.autocrlf", "false")
    (repo / "base.txt").write_bytes(b"base\n")
    git("add", "base.txt")
    git("commit", "-qm", "base")
    return repo, git


def _gate(repo: Path, env: dict, extra: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "precommit_pycompile.py")],
        cwd=repo, capture_output=True, env={**env, **(extra or {})}, timeout=120,
        check=False,
    )


def _err(proc: subprocess.CompletedProcess) -> str:
    return proc.stderr.decode("utf-8", "replace")


def _stage(repo: Path, git, rel: str, data: bytes) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    git("add", "--", rel)


def _blob(git, data: bytes) -> str:
    return git("hash-object", "-w", "--stdin", stdin=data)


def test_staged_broken_then_fixed_in_worktree_is_refused(tmp_path, env):
    repo, git = _repo(tmp_path, env)
    _stage(repo, git, "pkg/a.py", _BROKEN)
    (repo / "pkg" / "a.py").write_bytes(_GOOD)
    proc = _gate(repo, env)
    assert proc.returncode == 1, _err(proc)
    assert "pkg/a.py" in _err(proc)


def test_staged_broken_then_deleted_from_worktree_is_refused(tmp_path, env):
    repo, git = _repo(tmp_path, env)
    _stage(repo, git, "a.py", _BROKEN)
    (repo / "a.py").unlink()
    proc = _gate(repo, env)
    assert proc.returncode == 1, _err(proc)


def test_staged_good_then_broken_in_worktree_passes(tmp_path, env):
    repo, git = _repo(tmp_path, env)
    _stage(repo, git, "a.py", _GOOD)
    (repo / "a.py").write_bytes(_BROKEN)
    proc = _gate(repo, env)
    assert proc.returncode == 0, _err(proc)
    assert b"py_compile OK (1 file(s))" in proc.stdout


def test_symlink_to_broken_regular_file_type_change_is_compiled(tmp_path, env):
    repo, git = _repo(tmp_path, env)
    link = _blob(git, b"target.py")
    git("update-index", "--add", "--cacheinfo", f"120000,{link},x.py")
    git("commit", "-qm", "link")
    git("update-index", "--cacheinfo", f"100644,{_blob(git, _BROKEN)},x.py")
    assert git("diff", "--cached", "--name-status") == "T\tx.py"
    proc = _gate(repo, env)
    assert proc.returncode == 1, _err(proc)
    assert "x.py" in _err(proc)


def test_staged_symlink_entry_is_not_compiled_as_python(tmp_path, env):
    repo, git = _repo(tmp_path, env)
    link = _blob(git, b"not python (")
    git("update-index", "--add", "--cacheinfo", f"120000,{link},x.py")
    proc = _gate(repo, env)
    assert proc.returncode == 0, _err(proc)
    assert b"py_compile OK" in proc.stdout or proc.stdout == b""


def test_gitlink_named_py_is_skipped_not_a_crash(tmp_path, env):
    repo, git = _repo(tmp_path, env)
    head = git("rev-parse", "HEAD")
    git("update-index", "--add", "--cacheinfo", f"160000,{head},sub.py")
    (repo / "sub.py").mkdir()
    proc = _gate(repo, env)
    assert proc.returncode == 0, _err(proc)
    assert "Traceback" not in _err(proc)


def test_respects_the_hook_index_file(tmp_path, env):
    """git commit --only / -a hand the hook a GIT_INDEX_FILE; that index is what lands."""
    repo, git = _repo(tmp_path, env)
    alt = {"GIT_INDEX_FILE": str(repo / ".git" / "index.alt")}
    git("read-tree", "HEAD", extra=alt)
    git("update-index", "--add", "--cacheinfo", f"100644,{_blob(git, _BROKEN)},a.py", extra=alt)
    (repo / "a.py").write_bytes(_GOOD)
    assert _gate(repo, env).returncode == 0
    proc = _gate(repo, env, alt)
    assert proc.returncode == 1, _err(proc)


def test_no_bytecode_is_written_into_the_tree(tmp_path, env):
    repo, git = _repo(tmp_path, env)
    _stage(repo, git, "pkg/a.py", _GOOD)
    proc = _gate(repo, env)
    assert proc.returncode == 0, _err(proc)
    assert not list(repo.rglob("*.pyc"))


def test_refusal_names_the_repo_relative_path_only(tmp_path, env):
    repo, git = _repo(tmp_path, env)
    _stage(repo, git, "pkg/a.py", _BROKEN)
    proc = _gate(repo, env)
    err = _err(proc)
    assert proc.returncode == 1
    assert "pkg/a.py" in err and "line 1" in err and "SyntaxError" in err
    assert str(tmp_path) not in err and tmp_path.as_posix() not in err


def test_git_failure_is_a_clean_refusal(tmp_path, env):
    root = tmp_path / "norepo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "precommit_pycompile.py").write_bytes(_SCRIPT.read_bytes())
    proc = subprocess.run([sys.executable, str(root / "scripts" / "precommit_pycompile.py")],
                          cwd=root, capture_output=True, env=env, timeout=120, check=False)
    assert proc.returncode == 1
    assert "Traceback" not in _err(proc)
    assert "pre-commit:" in _err(proc)


def test_coding_cookie_and_bom_compile_like_py_compile(tmp_path, env):
    repo, git = _repo(tmp_path, env)
    _stage(repo, git, "latin.py", b"# -*- coding: latin-1 -*-\ns = '\xe9'\n")
    _stage(repo, git, "bom.py", b"\xef\xbb\xbfx = 1\n")
    _stage(repo, git, "bad_utf8.py", b"s = '\xe9'\n")
    proc = _gate(repo, env)
    err = _err(proc)
    assert proc.returncode == 1
    assert "bad_utf8.py" in err
    assert "latin.py" not in err and "bom.py" not in err


def test_null_byte_and_non_python_suffix(tmp_path, env):
    repo, git = _repo(tmp_path, env)
    _stage(repo, git, "zero.py", b"x = 1\x00\n")
    _stage(repo, git, "notes.txt", _BROKEN)
    _stage(repo, git, "a.pyc.bak", _BROKEN)
    proc = _gate(repo, env)
    err = _err(proc)
    assert proc.returncode == 1
    assert "zero.py" in err and "notes.txt" not in err and "a.pyc.bak" not in err


def test_nothing_staged_is_silent_success(tmp_path, env):
    repo, _git = _repo(tmp_path, env)
    proc = _gate(repo, env)
    assert proc.returncode == 0 and proc.stdout == b"" and proc.stderr == b""


def test_a_real_commit_with_the_fixed_worktree_does_not_land(tmp_path, env):
    """End to end through git's own hook runner: HEAD must not move."""
    repo, git = _repo(tmp_path, env)
    hooks = repo / "hooks"
    hooks.mkdir()
    py = Path(sys.executable).as_posix()
    (hooks / "pre-commit").write_bytes(
        b'#!/bin/sh\n"' + py.encode() + b'" "$(git rev-parse --show-toplevel)'
        b'/scripts/precommit_pycompile.py" || exit 1\n')
    (hooks / "pre-commit").chmod(0o755)
    git("config", "core.hooksPath", "hooks")
    before = git("rev-parse", "HEAD")
    _stage(repo, git, "a.py", _BROKEN)
    (repo / "a.py").write_bytes(_GOOD)
    proc = subprocess.run(["git", "commit", "-qm", "broken"], cwd=repo, capture_output=True,
                          env=env, timeout=120, check=False)
    assert proc.returncode != 0
    assert git("rev-parse", "HEAD") == before


def test_refusal_shows_the_staged_line_not_the_worktree_line(tmp_path, env):
    """traceback's formatter re-read the line from the working-tree file (linecache)."""
    repo, git = _repo(tmp_path, env)
    _stage(repo, git, "a.py", b"def staged_only(:\n")
    (repo / "a.py").write_bytes(b"worktree_only = 1\n")
    proc = _gate(repo, env)
    err = _err(proc)
    assert proc.returncode == 1
    assert "def staged_only(:" in err
    assert "worktree_only" not in err


def test_compile_warning_is_one_line_without_the_worktree_source(tmp_path, env):
    repo, git = _repo(tmp_path, env)
    _stage(repo, git, "w.py", b'x = "\\d"\n')
    (repo / "w.py").write_bytes(b"worktree_only = 1\n")
    proc = _gate(repo, env)
    err = _err(proc)
    assert proc.returncode == 0, err
    assert "w.py:1: SyntaxWarning:" in err
    assert "worktree_only" not in err


def _load(root: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("precommit_pycompile_t709", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = root
    return mod


@pytest.mark.parametrize("raw", [b":\x00a.py\x00", b":100644 100644 x\x00a.py\x00",
                                 b":000000 100644 0 1 A\x00"])
def test_malformed_raw_diff_is_a_clean_refusal(tmp_path, monkeypatch, capsys, raw):
    mod = _load(tmp_path)
    monkeypatch.setattr(mod, "_git", lambda args, stdin=None: raw)
    assert mod.main() == 1
    assert "cannot read the staged files" in capsys.readouterr().err


@pytest.mark.parametrize("out", [b"", b"abc blob 3\nx", b"abc missing\n", b"abc blob 1x\nx\n",
                                 b"zzz blob 1\nx\n"])
def test_malformed_cat_file_is_a_clean_refusal(tmp_path, monkeypatch, capsys, out):
    mod = _load(tmp_path)

    def fake(args, stdin=None):
        if args[0] == "diff":
            return b":000000 100644 " + b"0" * 40 + b" abc A\x00a.py\x00"
        return out

    monkeypatch.setattr(mod, "_git", fake)
    assert mod.main() == 1
    assert "cannot read the staged files" in capsys.readouterr().err

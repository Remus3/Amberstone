"""RM-818 verifier N2: the commit gate never linted a non-ASCII-named file.

`git diff --cached` writes a path holding a byte over 0x7F in its QUOTED form
(core.quotePath, on by default): `+++ "b/d\\304\\201.py"`. tools/precommit_gate.py
keyed that header text as the path, so the key ended in `.py"`, the file
never reached ruff, and a staged d<U+0101>.py with an unused import passed
with exit 0. Every git call in the gate now runs with -c core.quotepath=false,
so the header carries the real name.

The repo is a throwaway under tmp_path, with git's global config pinned to an
empty file and the system config off, so a host-wide quotepath setting cannot
decide the result. No ruff.toml: ruff's default rules include F401.

Source stays ASCII: every non-ASCII probe is built with chr().
"""
from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))

import precommit_gate as G  # noqa: E402

from tests._module_view import bind_subprocess  # noqa: E402

_A_MACRON = chr(0x0101)
requires_ruff = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None, reason="ruff is not importable by this interpreter"
)


@pytest.fixture
def git_env(tmp_path, monkeypatch):
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="ascii")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return {**os.environ}


def _staged(tmp_path: Path, env: dict, name: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args):
        subprocess.run(["git", *args], cwd=repo, capture_output=True, env=env, check=True)

    run("init", "-q", ".")
    run("config", "user.email", "gate@test")
    run("config", "user.name", "gate")
    (repo / "base.txt").write_text("base\n", encoding="ascii")
    run("add", "-A")
    run("commit", "-qm", "base")
    (repo / name).write_text("import os\n", encoding="ascii")
    run("add", "-A")
    return repo


def _gate(monkeypatch, capsys, repo: Path):
    monkeypatch.chdir(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO("git commit"))
    rc = G.main()
    return rc, capsys.readouterr().err


def test_the_staged_diff_keys_a_non_ascii_path_by_its_real_name(tmp_path, git_env):
    name = "d" + _A_MACRON + ".py"
    repo = _staged(tmp_path, git_env, name)
    assert sorted(G._staged_added(str(repo))) == [name]
    assert G._staged_new_paths(str(repo)) == [name]


@requires_ruff
@pytest.mark.parametrize("name", ["d" + _A_MACRON + ".py", "d.py"])
def test_a_staged_unused_import_blocks_whatever_the_file_is_called(
        name, tmp_path, git_env, monkeypatch, capsys):
    repo = _staged(tmp_path, git_env, name)
    rc, err = _gate(monkeypatch, capsys, repo)
    assert rc == 2, (rc, err[-1500:])
    assert "F401" in err, err[-1500:]


def test_every_git_call_turns_quotepath_off(tmp_path, git_env, monkeypatch):
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(list(argv))

        class _P:
            stdout, stderr, returncode = "", "", 0
        return _P()

    bind_subprocess(monkeypatch, G, run=fake_run)
    G._git(["diff", "--cached", "--unified=0"], str(tmp_path))
    G._git(["diff", "--cached", "--name-status", "-z"], str(tmp_path))
    assert seen and all(argv[:3] == ["git", "-c", "core.quotepath=false"] for argv in seen), seen

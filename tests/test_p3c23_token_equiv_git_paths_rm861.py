"""RM-861 (ops/audit/p3c23_token_equiv.py site): changed paths are read as themselves.

`changed_ds_files()` read a bare `git diff --name-only` through the locale
(`text=True`) and split it with `.splitlines()`. With core.quotePath on (git's
default) git C-quotes a non-ASCII name (`"agents/daemon_slayer/d\\304\\201.py"`),
the trailing quote fails the `.endswith(".py")` filter, and the changed file
silently drops out of the proof: a code edit in it still reports PROOF PASS.
With quotePath off the name is decoded through the locale (cp1252 on Windows
outside UTF-8 mode) and `git show HEAD:<mojibake>` fails. `.splitlines()` also
splits a name on U+2028; `-z` plus an explicit UTF-8 decode has none of these.

Every repo here is a throwaway under tmp_path with git's global config pinned
to an empty file, the system config off and `GIT_CONFIG_COUNT` cleared, so no
host-wide setting decides the result. Source stays ASCII: every non-ASCII probe
is built with chr().
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_P3 = _ROOT / "ops" / "audit" / "p3c23_token_equiv.py"

_DS = "agents/daemon_slayer/"
_NAME = _DS + "d" + chr(0x0101) + chr(0x00E9) + ".py"

_BASE = b'"""doc"""\nX = 1  # note\n'
_COMMENT_ONLY = b'"""doc"""\nX = 1  # note edited\n'
_CODE_EDIT = b'"""doc"""\nX = 2  # note\n'


def _load():
    spec = importlib.util.spec_from_file_location("_rm861_p3c23_token_equiv", _P3)
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


def _repo(tmp_path: Path, env: dict, tracked: list[str], quotepath: str = "true") -> Path:
    repo = tmp_path / "repo"
    (repo / "agents" / "daemon_slayer").mkdir(parents=True)

    def run(*args) -> None:
        subprocess.run(["git", *args], cwd=repo, capture_output=True, env=env, check=True)

    run("init", "-q", ".")
    run("config", "user.email", "rm861@test")
    run("config", "user.name", "rm861")
    run("config", "core.quotepath", quotepath)
    run("config", "core.autocrlf", "false")
    for rel in tracked:
        (repo / rel).write_bytes(_BASE)
    run("add", "-A")
    run("commit", "-q", "-m", "base")
    return repo


def _module(repo: Path, monkeypatch):
    p3 = _load()
    monkeypatch.setattr(p3, "REPO", repo)
    return p3


def test_control_ascii_changed_file_is_listed(tmp_path, git_env, monkeypatch):
    repo = _repo(tmp_path, git_env, [_DS + "a.py"])
    (repo / _DS / "a.py").write_bytes(_COMMENT_ONLY)
    p3 = _module(repo, monkeypatch)
    assert p3.changed_ds_files() == [_DS + "a.py"]
    assert p3.main() == 0


def test_a_changed_non_ascii_name_is_listed_as_itself(tmp_path, git_env, monkeypatch):
    repo = _repo(tmp_path, git_env, [_DS + "a.py", _NAME])
    (repo / _NAME).write_bytes(_COMMENT_ONLY)
    p3 = _module(repo, monkeypatch)
    assert p3.changed_ds_files() == [_NAME]


def test_a_code_edit_in_a_non_ascii_file_fails_the_proof(tmp_path, git_env, monkeypatch, capsys):
    """The fail-open: a quoted name dropped out and the proof passed without it."""
    repo = _repo(tmp_path, git_env, [_DS + "a.py", _NAME])
    (repo / _DS / "a.py").write_bytes(_COMMENT_ONLY)
    (repo / _NAME).write_bytes(_CODE_EDIT)
    p3 = _module(repo, monkeypatch)
    assert p3.main() == 2
    out = capsys.readouterr().out
    assert "PROOF FAIL: 2 files" in out


def test_a_name_with_a_unicode_line_separator_is_listed_whole(tmp_path, git_env, monkeypatch):
    """U+2028 is a line break to str.splitlines(), never to `diff -z`."""
    rel = _DS + "x" + chr(0x2028) + "y.py"
    try:
        repo = _repo(tmp_path, git_env, [_DS + "a.py", rel], quotepath="false")
    except OSError:
        pytest.skip("filesystem refuses a U+2028 file name")
    (repo / rel).write_bytes(_COMMENT_ONLY)
    p3 = _module(repo, monkeypatch)
    assert p3.changed_ds_files() == [rel]


def test_a_non_ascii_name_survives_a_non_utf8_locale(tmp_path, git_env):
    """quotePath off + a child outside UTF-8 mode: the decode must not be the locale's."""
    repo = _repo(tmp_path, git_env, [_DS + "a.py", _NAME], quotepath="false")
    (repo / _NAME).write_bytes(_COMMENT_ONLY)
    code = (
        "import importlib.util, json, sys\n"
        "from pathlib import Path\n"
        "spec = importlib.util.spec_from_file_location('p3', sys.argv[1])\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "mod.REPO = Path(sys.argv[2])\n"
        "print(json.dumps({'files': mod.changed_ds_files(), 'rc': mod.main()}))\n"
    )
    env = {k: v for k, v in git_env.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env["PYTHONIOENCODING"] = "ascii:backslashreplace"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [sys.executable, "-X", "utf8=0", "-c", code, str(_P3), str(repo)],
        capture_output=True, env=env, creationflags=flags, check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    last = proc.stdout.decode("ascii").strip().splitlines()[-1]
    result = json.loads(last)
    assert result == {"files": [_NAME], "rc": 0}

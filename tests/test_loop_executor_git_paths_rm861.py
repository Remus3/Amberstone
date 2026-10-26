"""RM-861 (ops/loop/executor.py site): index paths are read as themselves.

Two readers took `git ls-files` path output through the locale (`text=True`)
and split it with `.splitlines()`:

- `_repo_path` (via `_git_out`) resolves a premise token by BASENAME from the
  index. Under git's default core.quotePath a tracked file under a non-ASCII
  directory comes back C-quoted (`"caf\\303\\251/x.md"`), its basename keeps the
  trailing quote, and the token silently resolves to nothing - the grounding
  finding never fires. With quotePath off the name is decoded through the locale
  (cp1252 on Windows outside UTF-8 mode) and the returned path is mojibake.
- `_hook_index_modes` keys each mode by the basename of the listed path. A
  quoted path gives the key `pre-commit"`, so `gate_inactive_reason` reads the
  hook as absent from the index and SKIPS the mode check: a hook tracked 100644
  passes the gate (fail-open). `core.hooksPath` itself was read through the
  locale too, so a non-ASCII hooks dir read as missing in a non-UTF-8 child.

Fix: `ls-files -z` (and `-s -z`), an explicit UTF-8 decode, split on NUL.

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
_EXEC = _ROOT / "ops" / "loop" / "executor.py"

_DIR = "caf" + chr(0x00E9) + chr(0x0101)
_DOC = _DIR + "/rm861-premise.md"
_HOOKS = "h" + chr(0x00E9) + "ks"
_HOOK_NAMES = ("pre-commit", "commit-msg")


def _load():
    spec = importlib.util.spec_from_file_location("_rm861_loop_executor", _EXEC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def executor():
    return _load()


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


def _repo(tmp_path: Path, env: dict, files: list[str], quotepath: str = "true",
          hooks_path: str | None = None) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args) -> None:
        subprocess.run(["git", *args], cwd=repo, capture_output=True, env=env, check=True)

    run("init", "-q", ".")
    run("config", "user.email", "rm861@test")
    run("config", "user.name", "rm861")
    run("config", "core.quotepath", quotepath)
    run("config", "core.autocrlf", "false")
    run("config", "core.filemode", "false")
    for rel in files:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(b"#!/bin/sh\nexit 0\n")
    run("add", "-A")
    # Pinned so the test does not depend on the platform's default mode.
    for rel in files:
        run("update-index", "--chmod=-x", "--", rel)
    run("commit", "-q", "-m", "base")
    if hooks_path is not None:
        run("config", "core.hooksPath", hooks_path)
    return repo


def _hook_files(base: str) -> list[str]:
    return [f"{base}/{n}" for n in _HOOK_NAMES]


def test_control_ascii_basename_resolves(tmp_path, git_env, executor):
    repo = _repo(tmp_path, git_env, ["docs/rm861-premise.md"])
    assert executor._repo_path(str(repo), "rm861-premise.md") == "docs/rm861-premise.md"


def test_a_basename_under_a_non_ascii_dir_resolves_as_itself(tmp_path, git_env, executor):
    """Quoted, the basename kept a trailing quote and the token resolved to ""."""
    repo = _repo(tmp_path, git_env, [_DOC])
    assert executor._repo_path(str(repo), "rm861-premise.md") == _DOC


def test_a_name_with_a_unicode_line_separator_resolves_whole(tmp_path, git_env, executor):
    """U+2028 is a line break to str.splitlines(), never to `ls-files -z`."""
    rel = "x" + chr(0x2028) + "y/rm861-premise.md"
    try:
        repo = _repo(tmp_path, git_env, [rel], quotepath="false")
    except OSError:
        pytest.skip("filesystem refuses a U+2028 file name")
    assert executor._repo_path(str(repo), "rm861-premise.md") == rel


def test_control_ascii_hook_modes_are_keyed_by_basename(tmp_path, git_env, executor):
    repo = _repo(tmp_path, git_env, _hook_files(".githooks"))
    modes = executor._hook_index_modes(repo, repo / ".githooks")
    assert modes == {n: "100644" for n in _HOOK_NAMES}


def test_hook_modes_under_a_non_ascii_dir_are_keyed_by_basename(tmp_path, git_env, executor):
    repo = _repo(tmp_path, git_env, _hook_files(_HOOKS))
    modes = executor._hook_index_modes(repo, repo / _HOOKS)
    assert modes == {n: "100644" for n in _HOOK_NAMES}


def test_a_non_executable_hook_under_a_non_ascii_dir_fails_the_gate(tmp_path, git_env, executor):
    """The fail-open: a quoted key read as "not in the index" and the mode check was skipped."""
    repo = _repo(tmp_path, git_env, _hook_files(".githooks") + _hook_files(_HOOKS),
                 hooks_path=_HOOKS)
    reason = executor.gate_inactive_reason(str(repo))
    assert reason is not None and "tracked non-executable" in reason, reason


def test_non_ascii_paths_survive_a_non_utf8_locale(tmp_path, git_env):
    """quotePath off + a child outside UTF-8 mode: the decode must not be the locale's."""
    repo = _repo(tmp_path, git_env, [_DOC] + _hook_files(".githooks") + _hook_files(_HOOKS),
                 quotepath="false", hooks_path=_HOOKS)
    code = (
        "import importlib.util, json, sys\n"
        "from pathlib import Path\n"
        "spec = importlib.util.spec_from_file_location('ex', sys.argv[1])\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "sys.modules['ex'] = mod\n"
        "spec.loader.exec_module(mod)\n"
        "root = Path(sys.argv[2])\n"
        "print(json.dumps({\n"
        "    'path': mod._repo_path(str(root), 'rm861-premise.md'),\n"
        "    'gate': mod.gate_inactive_reason(str(root)),\n"
        "}))\n"
    )
    env = {k: v for k, v in git_env.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env["PYTHONIOENCODING"] = "ascii:backslashreplace"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [sys.executable, "-X", "utf8=0", "-c", code, str(_EXEC), str(repo)],
        capture_output=True, env=env, creationflags=flags, check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    result = json.loads(proc.stdout.decode("ascii").strip().splitlines()[-1])
    assert result["path"] == _DOC
    assert result["gate"] is not None and "tracked non-executable" in result["gate"], result

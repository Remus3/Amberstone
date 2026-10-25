"""RM-861 (tools/truth_gate.py site): `check_git` reads git path output as itself.

`check_git` fed the report's "git" block from `git status -s` and
`git log --oneline -1` in a text-mode child with no `encoding=`, and with
core.quotePath on (git's default):

- a dirty non-ASCII name was reported C-QUOTED (`"core/d\\304\\201..."`), a
  name that is not on disk;
- the decode went through the locale, so under a cp1252 console a UTF-8 byte
  cp1252 lacks (0x81) faulted the reader thread, stdout came back None and
  `check_git` raised AttributeError instead of reporting;
- `.strip()` on the whole status text ate the leading space of the first
  `XY path` line, so an unstaged edit (` M`) read as a staged one (`M `).

Every repo here is a throwaway under tmp_path with git's global config pinned
to an empty file, the system config off, `GIT_CONFIG_COUNT` cleared and
core.quotePath set ON in the repo, so no host-wide setting decides the result.
Source stays ASCII: every non-ASCII probe is built with chr().
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
_TG = _ROOT / "tools" / "truth_gate.py"

_A_MACRON = chr(0x0101)   # UTF-8 C4 81 (cp1252 has no 0x81)
_E_ACUTE = chr(0x00E9)    # UTF-8 C3 A9 (cp1252 maps both bytes: mojibake)
_NAME = "d" + _A_MACRON + _E_ACUTE


def _load():
    spec = importlib.util.spec_from_file_location("_rm861_truth_gate", _TG)
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


def _repo(tmp_path: Path, env: dict, subject: str = "base") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args) -> None:
        subprocess.run(["git", *args], cwd=repo, capture_output=True, env=env, check=True)

    run("init", "-q", ".")
    run("config", "user.email", "rm861@test")
    run("config", "user.name", "rm861")
    run("config", "core.quotepath", "true")
    run("config", "core.autocrlf", "false")
    run("config", "i18n.commitEncoding", "utf-8")
    (repo / "base.txt").write_bytes(b"base\n")
    run("add", "-A")
    msg = tmp_path / "msg.txt"
    msg.write_bytes(subject.encode("utf-8") + b"\n")
    run("commit", "-q", "-F", str(msg))
    return repo


def test_control_a_clean_repo_reports_clean(tmp_path, git_env, monkeypatch):
    repo = _repo(tmp_path, git_env)
    tg = _load()
    monkeypatch.setattr(tg, "ROOT", repo)
    obs = tg.check_git()
    assert obs["clean"] is True
    assert obs["dirty_files"] == []
    assert obs["head"].endswith(" base")


def test_a_dirty_non_ascii_name_is_reported_as_itself(tmp_path, git_env, monkeypatch):
    repo = _repo(tmp_path, git_env)
    # At the root: `status -s` folds an untracked directory to "core/".
    rel = _NAME + ".py"
    (repo / rel).write_bytes(b"x\n")
    tg = _load()
    monkeypatch.setattr(tg, "ROOT", repo)
    obs = tg.check_git()
    assert obs["clean"] is False
    assert obs["dirty_files"] == ["?? " + rel]


def test_an_unstaged_edit_on_the_first_line_keeps_its_status_column(tmp_path, git_env, monkeypatch):
    repo = _repo(tmp_path, git_env)
    (repo / "base.txt").write_bytes(b"edited\n")
    tg = _load()
    monkeypatch.setattr(tg, "ROOT", repo)
    assert tg.check_git()["dirty_files"] == [" M base.txt"]


def test_check_git_decodes_utf8_under_a_cp1252_locale(tmp_path, git_env):
    """Run in a child with UTF-8 mode OFF (a plain Windows console is cp1252),
    so the interpreter's own utf8 mode cannot mask a locale decode."""
    subject = "fix " + _NAME
    repo = _repo(tmp_path, git_env, subject=subject)
    rel = _NAME + ".txt"
    (repo / rel).write_bytes(b"x\n")
    code = (
        "import importlib.util, json, sys\n"
        "from pathlib import Path\n"
        "spec = importlib.util.spec_from_file_location('tg', sys.argv[1])\n"
        "mod = importlib.util.module_from_spec(spec); sys.modules['tg'] = mod\n"
        "spec.loader.exec_module(mod)\n"
        "mod.ROOT = Path(sys.argv[2])\n"
        "sys.stdout.write(json.dumps(mod.check_git()))\n"
    )
    env = {k: v for k, v in git_env.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    out = subprocess.run([sys.executable, "-X", "utf8=0", "-c", code, str(_TG), str(repo)],
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[-600:]
    obs = json.loads(out.stdout.decode("ascii"))
    assert obs["dirty_files"] == ["?? " + rel]
    assert obs["head"].endswith(" " + subject)
